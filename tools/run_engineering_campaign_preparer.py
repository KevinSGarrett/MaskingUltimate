#!/usr/bin/env python3
"""CPU-only preparation of one tracker-bound 25-mission local campaign."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from maskfactory.steward.engineering_campaign_preparer import (  # noqa: E402
    prepare_engineering_campaign,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--tracker",
        type=Path,
        default=PROJECT_ROOT / "Plan" / "Tracker" / "tracker.json",
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--packet-parent", type=Path, required=True)
    parser.add_argument("--campaign-inbox", type=Path, required=True)
    parser.add_argument(
        "--runtime-contract",
        type=Path,
        default=PROJECT_ROOT / "configs" / "self_hosted_steward_runtime_v1.json",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    preparation = prepare_engineering_campaign(
        repo_root=args.repo_root,
        tracker_path=args.tracker,
        source_path=args.source,
        packet_parent=args.packet_parent,
        campaign_inbox=args.campaign_inbox,
        runtime_contract_path=args.runtime_contract,
    )
    print(json.dumps(preparation, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
