"""Build or verify a hash-bound, denominator-explicit autonomy metrics report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.autonomy.metrics import (
    build_autonomy_metrics_report_from_inputs,
    render_autonomy_metrics_dashboard,
    validate_autonomy_metrics_report,
)


def _load(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return document


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("document", type=Path, help="source inputs, or a report with --verify")
    parser.add_argument("--output", type=Path, help="required report path when building")
    parser.add_argument("--dashboard", type=Path, help="optional rendered Markdown path")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify and args.output is not None:
        parser.error("--output is not valid with --verify")
    if not args.verify and args.output is None:
        parser.error("--output is required when building")

    if args.verify:
        report = _load(args.document)
        validate_autonomy_metrics_report(report)
    else:
        report = build_autonomy_metrics_report_from_inputs(_load(args.document))
        _write_atomic(args.output, json.dumps(report, indent=2, sort_keys=True) + "\n")
    dashboard = render_autonomy_metrics_dashboard(report)
    if args.dashboard is not None:
        _write_atomic(args.dashboard, dashboard + "\n")
    print(
        json.dumps(
            {
                "cohort_id": report["cohort"]["cohort_id"],
                "sha256": report["sha256"],
                "source_input_sha256": report["source_input_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
