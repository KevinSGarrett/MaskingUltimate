#!/usr/bin/env python
"""Emit one autonomous work-cell receipt from a RunPod stage artifact.

The command is designed for `subprocess_json` handlers.  It reads the leased
work item from stdin, validates that the requested stage matches the lease, then
converts an exact JSON artifact into the closed receipt consumed by
`manage_runpod_autonomous_work_cell.py result`.
"""

from __future__ import annotations

import argparse
import json
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--actor-kind")
    parser.add_argument(
        "--evidence-sha256",
        help="Optional explicit evidence hash. Defaults to the artifact file SHA-256.",
    )
    args = parser.parse_args()

    try:
        work = _read_work()
        if work.get("stage") != args.stage:
            raise WorkCellReceiptError("requested stage does not match leased work stage")
        artifact, artifact_sha256 = load_json_artifact(args.artifact)
        receipt = receipt_from_stage_artifact(
            stage=args.stage,
            status=args.status,
            artifact=artifact,
            evidence_sha256=args.evidence_sha256 or artifact_sha256,
            actor_kind=args.actor_kind,
        )
    except WorkCellReceiptError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    json.dump(receipt, sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
