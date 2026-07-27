"""Build an immutable Plan-27 telemetry successor for a terminal campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.steward.engineering_campaign_telemetry import (
    build_engineering_campaign_telemetry_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--runtime-packet-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--baseline-usage-units-per-accepted-artifact",
        type=float,
        required=True,
    )
    parser.add_argument(
        "--terminal-adoption-usage-units",
        type=float,
        required=True,
    )
    parser.add_argument(
        "--terminal-adoption-review-seconds",
        type=float,
        required=True,
    )
    parser.add_argument("--limitation", action="append", required=True)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    bundle = build_engineering_campaign_telemetry_bundle(
        repo_root=repo_root,
        campaign_root=args.campaign_root,
        contract_path=args.contract,
        database=args.database,
        runtime_packet_root=args.runtime_packet_root,
        output_root=args.output_root,
        baseline_usage_units_per_accepted_artifact=(
            args.baseline_usage_units_per_accepted_artifact
        ),
        terminal_adoption_usage_units=args.terminal_adoption_usage_units,
        terminal_adoption_review_seconds=args.terminal_adoption_review_seconds,
        limitations=args.limitation,
    )
    print(
        json.dumps(
            {
                "bundle_sha256": bundle["bundle_sha256"],
                "campaign_id": bundle["campaign_id"],
                "event_count": len(bundle["events"]),
                "output_root": str(args.output_root),
                "slo_passed": bundle["slo"]["passed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
