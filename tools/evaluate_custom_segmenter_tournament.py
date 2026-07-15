"""Build or verify the frozen custom-segmenter fair-training report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.training.custom_segmenter_tournament import build_report, verify_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    runs = json.loads(args.runs.read_text(encoding="utf-8"))
    if args.verify:
        report = json.loads(args.output.read_text(encoding="utf-8"))
        verify_report(report, runs)
    else:
        report = build_report(runs)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "sha256": report["sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
