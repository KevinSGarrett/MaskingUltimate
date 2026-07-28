"""Run or verify MF-P6-08.08 deterministic autonomy demonstration evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.autonomy.demonstration import (
    run_autonomous_gold_demonstration,
    verify_autonomous_gold_demonstration,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        report = json.loads(args.output.read_text(encoding="utf-8"))
        verify_autonomous_gold_demonstration(report)
    else:
        report = run_autonomous_gold_demonstration(args.workdir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {"report_id": report["report_id"], "report_sha256": report["report_sha256"]},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
