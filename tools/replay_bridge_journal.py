"""Replay/reconstruct additive producer bridge journal state from signed history."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.bridge.journal import (
    BridgeJournalError,
    reconstruct_bridge_journal_state,
    validate_bridge_journal_reconstruction_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entries", required=True, type=Path)
    parser.add_argument("--checkpoints", type=Path, default=None)
    parser.add_argument("--trusted-keys", required=True, type=Path)
    parser.add_argument("--decided-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--main-prerequisite",
        action="append",
        default=[],
        help="Repeatable Main prerequisite id marked satisfied for this observation.",
    )
    args = parser.parse_args()

    entries = json.loads(args.entries.read_text(encoding="utf-8"))
    checkpoints = (
        json.loads(args.checkpoints.read_text(encoding="utf-8")) if args.checkpoints else []
    )
    trusted_keys = json.loads(args.trusted_keys.read_text(encoding="utf-8"))
    evidence = reconstruct_bridge_journal_state(
        entries,
        checkpoints=checkpoints,
        trusted_signing_keys=trusted_keys,
        decided_at=args.decided_at,
        main_prerequisites_satisfied=args.main_prerequisite,
    )
    issues = validate_bridge_journal_reconstruction_evidence(evidence)
    if issues:
        raise BridgeJournalError(*issues)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if evidence["status"] == "reconstructed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
