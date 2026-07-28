#!/usr/bin/env python3
"""Build a hash-bound calibration-only admission receipt from exact decisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.vlm.canonical_polygon_calibration_admission import (
    build_canonical_polygon_calibration_admission,
)


def _load_object(path: Path, *, document_name: str) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{document_name} must be a JSON object:{path}")
    return value


def _load_decisions(path: Path) -> list:
    document = _load_object(
        path,
        document_name="decisions document (containing a 'decisions' list)",
    )
    decisions = document.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError(f"decisions document must contain a 'decisions' list:{path}")
    return decisions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--panel-report", type=Path, required=True)
    parser.add_argument("--panel-root", type=Path, required=True)
    parser.add_argument(
        "--decisions",
        type=Path,
        required=True,
        help="JSON object containing the required 'decisions' list",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite immutable receipt:{args.output}")
    document = build_canonical_polygon_calibration_admission(
        candidates=_load_object(args.candidates, document_name="candidate document"),
        panel_report=_load_object(args.panel_report, document_name="panel report document"),
        panel_root=args.panel_root,
        decisions=_load_decisions(args.decisions),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "record_count": document["record_count"],
                "admitted_calibration_only_count": document["admitted_calibration_only_count"],
                "abstained_count": document["abstained_count"],
                "rejected_count": document["rejected_count"],
                "self_sha256": document["self_sha256"],
                "authority": document["authority"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
