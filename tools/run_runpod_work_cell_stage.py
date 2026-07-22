#!/usr/bin/env python
"""Run one RunPod stage command, then emit its autonomous work-cell receipt.

This is the production glue for `subprocess_json` handlers.  The controller
passes a leased work item on stdin.  This wrapper forwards that same JSON to the
real stage command, requires a hash-bound artifact at the declared path, and
then converts the artifact to the closed work-cell receipt schema.

The wrapper deliberately does not infer pixels or authority.  The invoked stage
must write the artifact fields needed by the work-cell contract.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from maskfactory.autonomy.work_cell_receipts import (
    WorkCellReceiptError,
    load_json_artifact,
    receipt_from_stage_artifact,
)


def _read_work() -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise WorkCellReceiptError("leased work stdin is not json") from exc
    if not isinstance(payload, dict):
        raise WorkCellReceiptError("leased work stdin must be an object")
    return payload


def _record_id(work: dict[str, Any]) -> str:
    value = work.get("record_id")
    if not isinstance(value, str) or not value:
        raise WorkCellReceiptError("leased work record_id is required")
    return value


def _artifact_path(args: argparse.Namespace, work: dict[str, Any]) -> Path:
    if args.artifact is not None:
        return args.artifact
    if args.artifact_root is None:
        raise WorkCellReceiptError("--artifact or --artifact-root is required")
    filename = f"{_record_id(work)}.{args.stage}.json"
    return args.artifact_root / args.stage / filename


def _render_command(command: list[str], *, artifact: Path, stage: str, record_id: str) -> list[str]:
    replacements = {
        "{artifact}": str(artifact),
        "{stage}": stage,
        "{record_id}": record_id,
    }
    rendered: list[str] = []
    for raw in command:
        value = raw
        for token, replacement in replacements.items():
            value = value.replace(token, replacement)
        rendered.append(value)
    return rendered


def _run_stage_command(
    command: list[str],
    *,
    artifact: Path,
    args: argparse.Namespace,
    work: dict[str, Any],
) -> None:
    if not command:
        raise WorkCellReceiptError("stage command is required")
    artifact.parent.mkdir(parents=True, exist_ok=True)
    environment = {
        **os.environ,
        "MASKFACTORY_WORK_CELL_STAGE": args.stage,
        "MASKFACTORY_WORK_CELL_RECORD_ID": _record_id(work),
        "MASKFACTORY_WORK_CELL_ARTIFACT": str(artifact),
    }
    rendered = _render_command(
        command, artifact=artifact, stage=args.stage, record_id=_record_id(work)
    )
    completed = subprocess.run(
        rendered,
        input=json.dumps(work, sort_keys=True),
        text=True,
        capture_output=True,
        cwd=args.cwd,
        env=environment,
        timeout=args.timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()[-2000:]
        raise WorkCellReceiptError(f"stage command failed rc={completed.returncode}: {stderr}")


def _status(args: argparse.Namespace, artifact: dict[str, Any]) -> str:
    value = args.status or artifact.get("work_cell_status") or artifact.get("receipt_status")
    if not isinstance(value, str) or not value:
        raise WorkCellReceiptError("--status or artifact work_cell_status is required")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--status")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--actor-kind")
    parser.add_argument("--cwd", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("stage_command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = list(args.stage_command)
    if command and command[0] == "--":
        command = command[1:]

    try:
        work = _read_work()
        if work.get("stage") != args.stage:
            raise WorkCellReceiptError("requested stage does not match leased work stage")
        artifact_path = _artifact_path(args, work)
        _run_stage_command(command, artifact=artifact_path, args=args, work=work)
        artifact, artifact_sha256 = load_json_artifact(artifact_path)
        receipt = receipt_from_stage_artifact(
            stage=args.stage,
            status=_status(args, artifact),
            artifact=artifact,
            evidence_sha256=artifact_sha256,
            actor_kind=args.actor_kind,
        )
    except (subprocess.TimeoutExpired, WorkCellReceiptError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    json.dump(receipt, sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
