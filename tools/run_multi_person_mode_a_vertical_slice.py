"""Run or validate MF-P6-12.03 producer multi-person Mode A vertical-slice evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.bridge.multi_person_mode_a_vertical_slice import (
    run_multi_person_mode_a_vertical_slice,
    validate_multi_person_mode_a_vertical_slice_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        evidence = json.loads(args.output.read_text(encoding="utf-8"))
        issues = validate_multi_person_mode_a_vertical_slice_evidence(evidence)
        if issues:
            raise SystemExit(
                f"multi-person mode a vertical slice evidence invalid: {', '.join(issues)}"
            )
    else:
        evidence = run_multi_person_mode_a_vertical_slice(args.workdir)
        issues = validate_multi_person_mode_a_vertical_slice_evidence(evidence)
        if issues:
            raise SystemExit(
                f"multi-person mode a vertical slice evidence invalid: {', '.join(issues)}"
            )
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
                "mf_p6_12_03_complete": evidence["claim_boundary"]["mf_p6_12_03_complete"],
                "rejection_reasons": evidence["rejection_reasons"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
