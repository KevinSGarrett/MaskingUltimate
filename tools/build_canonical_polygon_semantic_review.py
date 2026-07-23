#!/usr/bin/env python3
"""Build a hash-bound semantic review from exact per-record decisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.vlm.canonical_polygon_semantic_review import (
    build_semantic_review,
    verify_semantic_review,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel-report", type=Path, required=True)
    parser.add_argument("--panel-root", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    panel_report = json.loads(args.panel_report.read_text(encoding="utf-8"))
    decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
    result = build_semantic_review(
        panel_report=panel_report,
        panel_root=args.panel_root,
        decisions=decisions["decisions"],
    )
    verify_semantic_review(result, panel_report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "record_count": result["record_count"],
                "verdict_counts": result["verdict_counts"],
                "reason_counts": result["reason_counts"],
                "authority_claimed": result["authority_claimed"],
                "self_sha256": result["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
