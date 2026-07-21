"""Evaluate additive bridge recovery evidence from an observation document.

Documents Main-owned runtime dependencies that this producer tool does not
execute: durable journal retention, atomic append+side-effects, remote
execution history, cache tombstone/rebuild, node-pack install/rollback, and
signed decision snapshots.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.bridge.recovery import (
    EXTERNAL_MAIN_DEPENDENCIES,
    RecoveryError,
    build_recovery_evidence,
    validate_recovery_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", type=Path)
    parser.add_argument("--decided-at")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--list-main-dependencies",
        action="store_true",
        help="print Main-owned runtime dependencies and exit",
    )
    args = parser.parse_args()

    if args.list_main_dependencies:
        print(json.dumps(list(EXTERNAL_MAIN_DEPENDENCIES), indent=2))
        return 0

    if args.observation is None or args.decided_at is None or args.output is None:
        parser.error("--observation, --decided-at, and --output are required")

    observation = json.loads(args.observation.read_text(encoding="utf-8"))
    evidence = build_recovery_evidence(observation, decided_at=args.decided_at)
    issues = validate_recovery_evidence(evidence)
    if issues:
        raise RecoveryError("; ".join(issues))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if evidence.get("transaction", {}).get("commit_ready") is True:
        return 0
    return 2 if evidence["status"] == "accepted" else 3


if __name__ == "__main__":
    raise SystemExit(main())
