#!/usr/bin/env python3
"""Read-only MaskFactory local storage admission check."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from maskfactory.steward.storage_guard import (  # noqa: E402
    LocalStorageGuard,
    StorageGuardError,
    StoragePolicy,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--policy",
        type=Path,
        default=PROJECT_ROOT / "configs" / "local_workspace_hygiene_v1.json",
    )
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--kind",
        choices=(
            "incremental_backup",
            "worktree",
            "runtime_evidence",
            "full_repository_bundle",
        ),
    )
    parser.add_argument("--expected-bytes", type=int, default=0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    policy = StoragePolicy.load(args.policy)
    guard = LocalStorageGuard(policy)
    snapshot = guard.snapshot(args.root)
    decision = "snapshot_only"
    error = None
    if args.kind:
        try:
            guard.require_allocation(
                kind=args.kind,
                expected_bytes=args.expected_bytes,
                free_bytes=snapshot.free_bytes,
            )
            decision = "admitted"
        except StorageGuardError as exc:
            decision = "blocked"
            error = str(exc)
    print(
        json.dumps(
            {
                "schema_version": "maskfactory_local_storage_guard_receipt.v1",
                "decision": decision,
                "error": error,
                "snapshot": snapshot.__dict__,
                "requested_kind": args.kind,
                "expected_bytes": args.expected_bytes,
            },
            sort_keys=True,
        )
    )
    return 2 if decision == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
