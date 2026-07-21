"""CLI for producer intake of authenticated downstream repair feedback."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.bridge.feedback_intake import (
    FeedbackIntakeError,
    FeedbackIntakeLedger,
    intake_bridge_feedback,
    validate_feedback_intake_evidence,
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feedback", required=True, type=Path)
    parser.add_argument("--parent-request", required=True, type=Path)
    parser.add_argument("--parent-receipt", required=True, type=Path)
    parser.add_argument("--certificate", required=True, type=Path)
    parser.add_argument("--trusted-keys", required=True, type=Path)
    parser.add_argument("--decided-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--ledger-out", type=Path)
    parser.add_argument("--qa-report", type=Path)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--capability", type=Path)
    parser.add_argument("--semantic-profile", type=Path)
    parser.add_argument("--current-policy", type=Path)
    parser.add_argument("--current-parent-heads", type=Path)
    parser.add_argument("--write-attempt", type=Path)
    parser.add_argument("--parent-bytes-before", type=Path)
    parser.add_argument("--parent-bytes-after", type=Path)
    parser.add_argument("--revocation-status", type=str)
    args = parser.parse_args()

    ledger = FeedbackIntakeLedger.from_dict(_load(args.ledger) if args.ledger else None)
    evidence = intake_bridge_feedback(
        _load(args.feedback),
        decided_at=args.decided_at,
        trusted_signing_keys=_load(args.trusted_keys),
        parent_request=_load(args.parent_request),
        parent_receipt=_load(args.parent_receipt),
        certificate=_load(args.certificate),
        ledger=ledger,
        release_snapshot=_load(args.release) if args.release else None,
        capability_snapshot=_load(args.capability) if args.capability else None,
        semantic_profile=_load(args.semantic_profile) if args.semantic_profile else None,
        current_policy=_load(args.current_policy) if args.current_policy else None,
        qa_report=_load(args.qa_report) if args.qa_report else None,
        current_parent_heads=(
            _load(args.current_parent_heads) if args.current_parent_heads else None
        ),
        revocation_status=args.revocation_status,
        write_attempt=_load(args.write_attempt) if args.write_attempt else None,
        parent_bytes_before=_load(args.parent_bytes_before) if args.parent_bytes_before else None,
        parent_bytes_after=_load(args.parent_bytes_after) if args.parent_bytes_after else None,
    )
    issues = validate_feedback_intake_evidence(evidence)
    if issues:
        raise FeedbackIntakeError("; ".join(issues))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.ledger_out is not None:
        args.ledger_out.parent.mkdir(parents=True, exist_ok=True)
        args.ledger_out.write_text(
            json.dumps(ledger.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0 if evidence["status"] == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
