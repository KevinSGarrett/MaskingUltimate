"""Run or validate MF-P6-12.04 producer Mode B vertical-slice evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.bridge.mode_b_vertical_slice import (
    run_mode_b_vertical_slice,
    validate_mode_b_vertical_slice_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument(
        "--probe-live-loopback",
        action="store_true",
        help="Optionally probe Windows 127.0.0.1:8765/health (does not fabricate success).",
    )
    args = parser.parse_args()
    if args.verify:
        evidence = json.loads(args.output.read_text(encoding="utf-8"))
        issues = validate_mode_b_vertical_slice_evidence(evidence)
        if issues:
            raise SystemExit(f"mode b vertical slice evidence invalid: {', '.join(issues)}")
    else:
        evidence = run_mode_b_vertical_slice(
            args.workdir,
            probe_live_loopback=args.probe_live_loopback,
        )
        issues = validate_mode_b_vertical_slice_evidence(evidence)
        if issues:
            raise SystemExit(f"mode b vertical slice evidence invalid: {', '.join(issues)}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "decision_sha256": evidence["decision_sha256"],
                "producer_fixture_slice_complete": evidence["claim_boundary"][
                    "producer_fixture_slice_complete"
                ],
                "mf_p6_12_04_complete": evidence["claim_boundary"]["mf_p6_12_04_complete"],
                "rejection_reasons": evidence["rejection_reasons"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
