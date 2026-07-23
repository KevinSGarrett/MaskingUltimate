"""Subprocess-backed stage handlers for RunPod autonomous work-cell missions.

These handlers are the bridge between the durable mission controller and the
real RunPod tools.  Each stage command receives the leased work item as JSON on
stdin and must return one closed work-cell receipt as JSON on stdout.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence


class CommandStageHandlerError(RuntimeError):
    """A stage command failed, returned malformed output, or drifted from its binding."""


def canonical_sha256(value: Mapping[str, Any]) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_binding_sha256(spec: Mapping[str, Any]) -> str:
    """Hash the command binding that must match the mission stage version."""

    document = {
        key: value
        for key, value in dict(spec).items()
        if key not in {"implementation_sha256", "description"}
    }
    return canonical_sha256(document)


class CommandStageHandler:
    """Run one exact stage command and parse its JSON receipt."""

    def __init__(
        self,
        *,
        stage: str,
        command: Sequence[str],
        implementation_sha256: str,
        timeout_seconds: int,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        if not stage:
            raise ValueError("stage required")
        if not command:
            raise ValueError("command required")
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        self.stage = stage
        self.command = tuple(str(part) for part in command)
        self.implementation_sha256 = implementation_sha256
        self.timeout_seconds = timeout_seconds
        self.cwd = Path(cwd) if cwd is not None else None
        self.env = dict(env or {})

    @classmethod
    def from_spec(cls, stage: str, spec: Mapping[str, Any], *, base: Path) -> "CommandStageHandler":
        expected = str(spec["implementation_sha256"])
        observed = command_binding_sha256(spec)
        if observed != expected:
            raise CommandStageHandlerError(f"command handler binding hash mismatch: {stage}")
        for binding_file in spec.get("binding_files") or ():
            path = Path(str(binding_file["path"]))
            if not path.is_absolute():
                path = base / path
            if file_sha256(path) != binding_file["sha256"]:
                raise CommandStageHandlerError(
                    f"command handler binding file hash mismatch: {stage}"
                )
        cwd = spec.get("cwd")
        resolved_cwd = None
        if isinstance(cwd, str):
            resolved_cwd = Path(cwd)
            if not resolved_cwd.is_absolute():
                resolved_cwd = base / resolved_cwd
        return cls(
            stage=stage,
            command=spec["command"],
            implementation_sha256=expected,
            timeout_seconds=int(spec["timeout_seconds"]),
            cwd=resolved_cwd,
            env=spec.get("env") or {},
        )

    def __call__(self, work: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = json.dumps(dict(work), sort_keys=True)
        environment = os.environ.copy()
        environment.update(self.env)
        completed = subprocess.run(
            list(self.command),
            input=payload,
            text=True,
            capture_output=True,
            cwd=self.cwd,
            env=environment,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise CommandStageHandlerError(
                f"{self.stage} command failed rc={completed.returncode}: "
                f"{completed.stderr.strip()[:500]}"
            )
        try:
            receipt = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise CommandStageHandlerError(f"{self.stage} command returned non-json") from exc
        if not isinstance(receipt, dict):
            raise CommandStageHandlerError(f"{self.stage} command returned non-object")
        if receipt.get("stage") != self.stage:
            raise CommandStageHandlerError(f"{self.stage} command returned wrong stage")
        return receipt
