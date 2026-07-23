"""Compile exact QA-threshold calibration coverage from JSONL evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from maskfactory.autonomy.qa_threshold_calibration import build_calibration_report


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"expected JSON object at {path}:{line_number}")
        records.append(value)
    return records


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("configs/autonomous_gold_qa_threshold_calibration_policy.json"),
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("configs/autonomous_gold_qa_thresholds.yaml"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_calibration_report(
        calibration_run_id=args.run_id,
        policy=_read_json(args.policy),
        records=_read_jsonl(args.records),
        registry_path=args.registry,
    )
    _write_atomic(args.output, report)
    print(
        json.dumps(
            {
                "status": report["report"]["status"],
                "record_count": report["report"]["record_count"],
                "report_sha256": report["report"]["report_sha256"],
                "authority_claim": report["report"]["authority_claim"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
