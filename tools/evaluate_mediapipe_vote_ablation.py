"""Build or verify a frozen MediaPipe handedness-vote ablation report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.providers.mediapipe_ablation import build_report, verify_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    parser.add_argument("--truth-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--allow-failed-result", action="store_true")
    args = parser.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.verify:
        report = json.loads(args.output.read_text(encoding="utf-8"))
        verify_report(
            report,
            cases,
            truth_manifest_path=args.truth_manifest,
            require_pass=not args.allow_failed_result,
        )
    else:
        report = build_report(cases, truth_manifest_path=args.truth_manifest)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(args.output.name + ".tmp")
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(args.output)
        if report["result"] != "pass" and not args.allow_failed_result:
            raise SystemExit(
                "MediaPipe vote ablation did not pass: " + ", ".join(report["findings"])
            )
    print(
        json.dumps(
            {
                "benchmark_id": report["benchmark_id"],
                "result": report["result"],
                "sha256": report["sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
