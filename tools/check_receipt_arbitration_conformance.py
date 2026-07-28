"""Evaluate receipt arbitration conformance against producer policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.bridge.receipt_arbitration_conformance import (
    ReceiptArbitrationConformanceError,
    build_receipt_arbitration_conformance_evidence,
    validate_receipt_arbitration_conformance_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--main-decision", required=True, type=Path)
    parser.add_argument("--producer-heads", required=True, type=Path)
    parser.add_argument("--decided-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    main_decision = json.loads(args.main_decision.read_text(encoding="utf-8"))
    producer_heads = json.loads(args.producer_heads.read_text(encoding="utf-8"))
    evidence = build_receipt_arbitration_conformance_evidence(
        candidates,
        main_decision,
        decided_at=args.decided_at,
        producer_heads=producer_heads,
    )
    issues = validate_receipt_arbitration_conformance_evidence(evidence)
    if issues:
        raise ReceiptArbitrationConformanceError("; ".join(issues))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if evidence["status"] == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
