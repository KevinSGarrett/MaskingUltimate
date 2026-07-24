"""Hash-bound RunPod Serverless command worker for MaskFactory campaigns."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any

import runpod

SESSION_ID = "019f91d1-ea20-7d81-83ff-03d393eaa1f5"
MAX_TIMEOUT_SECONDS = 1800
MAX_CAPTURE_BYTES = 65536
ALLOWED_ROOTS = (
    Path("/workspace/maskfactory"),
    Path("/workspace/packages"),
    Path("/workspace/wave64"),
    Path("/workspace/maskfactory_runtime"),
)
ALLOWED_ENVIRONMENT = frozenset(
    {
        "CUDA_VISIBLE_DEVICES",
        "HF_HOME",
        "PYTHONPATH",
        "TORCH_HOME",
        "TRANSFORMERS_CACHE",
    }
)
ALLOWED_EXECUTABLE_NAMES = frozenset({"python", "python3", "bash"})


class ContractError(RuntimeError):
    pass


def _resolved(path: str) -> Path:
    return Path(path).resolve(strict=True)


def _under_allowed_root(path: Path) -> bool:
    resolved_roots = tuple(root.resolve(strict=True) for root in ALLOWED_ROOTS if root.exists())
    return any(path == root or root in path.parents for root in resolved_roots)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_binding_files(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ContractError("binding_files must be a non-empty array")
    bindings: list[dict[str, str]] = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise ContractError("binding file fields are invalid")
        path = _resolved(row["path"])
        if not path.is_file() or not _under_allowed_root(path):
            raise ContractError(f"binding file is outside allowed roots: {path}")
        expected = row["sha256"]
        if not isinstance(expected, str) or len(expected) != 64:
            raise ContractError("binding file sha256 is invalid")
        if _sha256(path) != expected:
            raise ContractError(f"binding file hash mismatch: {path}")
        bindings.append({"path": str(path), "sha256": expected})
    return bindings


def _validate_argv(value: Any) -> list[str]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 128
        or not all(isinstance(part, str) and part for part in value)
    ):
        raise ContractError("argv must contain 1-128 non-empty strings")
    executable = value[0]
    executable_name = Path(executable).name
    if executable_name not in ALLOWED_EXECUTABLE_NAMES:
        resolved_executable = _resolved(executable)
        if not _under_allowed_root(resolved_executable):
            raise ContractError("executable is outside allowed roots")
    if executable_name in {"python", "python3", "bash"}:
        if len(value) < 2:
            raise ContractError("interpreter invocation requires a bound script")
        script = _resolved(value[1])
        if not script.is_file() or not _under_allowed_root(script):
            raise ContractError("interpreter script is outside allowed roots")
    return list(value)


def handler(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("input")
    if not isinstance(value, dict):
        raise ContractError("input must be an object")
    if value.get("session_id") != SESSION_ID:
        raise ContractError("MaskFactory session binding mismatch")
    argv = _validate_argv(value.get("argv"))
    bindings = _validate_binding_files(value.get("binding_files"))
    bound_paths = {row["path"] for row in bindings}
    executable_name = Path(argv[0]).name
    if executable_name in {"python", "python3", "bash"}:
        if str(_resolved(argv[1])) not in bound_paths:
            raise ContractError("interpreter script must be hash-bound")
    timeout_seconds = value.get("timeout_seconds")
    if (
        not isinstance(timeout_seconds, int)
        or timeout_seconds < 1
        or timeout_seconds > MAX_TIMEOUT_SECONDS
    ):
        raise ContractError("timeout_seconds is outside endpoint contract")
    cwd = _resolved(value.get("cwd", "/workspace/maskfactory"))
    if not cwd.is_dir() or not _under_allowed_root(cwd):
        raise ContractError("cwd is outside allowed roots")
    requested_env = value.get("env", {})
    if not isinstance(requested_env, dict) or not set(requested_env) <= ALLOWED_ENVIRONMENT:
        raise ContractError("environment override is not allowed")
    if not all(
        isinstance(key, str) and isinstance(item, str) for key, item in requested_env.items()
    ):
        raise ContractError("environment values must be strings")
    environment = dict(os.environ)
    environment.update(requested_env)
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        timeout=timeout_seconds,
    )
    stdout = result.stdout[-MAX_CAPTURE_BYTES:].decode("utf-8", errors="replace")
    stderr = result.stderr[-MAX_CAPTURE_BYTES:].decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(
            f"MaskFactory command failed with {result.returncode}; stderr tail: {stderr[-4000:]}"
        )
    return {
        "schema_version": "maskfactory.runpod_serverless_command_result.v1",
        "returncode": result.returncode,
        "stdout_tail": stdout,
        "stderr_tail": stderr,
        "binding_files": bindings,
    }


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
