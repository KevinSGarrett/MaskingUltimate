"""Build an immutable Plan-27 telemetry successor for a terminal campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from maskfactory.steward.engineering_campaign_telemetry import (
    build_engineering_campaign_telemetry_bundle,
)

LAUNCH_MANIFEST_SCHEMA = "maskfactory.engineering_campaign_telemetry_launch.v1"
ZERO_SHA256 = "0" * 64
REQUIRED_DEPLOYMENT_PATHS = (
    "src/maskfactory/steward/engineering_campaign_runtime_packet.py",
    "src/maskfactory/steward/engineering_campaign_telemetry.py",
    "tools/build_engineering_campaign_telemetry.py",
)


def _canonical_sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_launch_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"telemetry launch manifest is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise SystemExit("telemetry launch manifest must be an object")
    expected_keys = {
        "baseline_usage_units_per_accepted_artifact",
        "campaign_root",
        "contract",
        "database",
        "launch_manifest_sha256",
        "limitations",
        "output_root",
        "runtime_packet_root",
        "schema_version",
        "terminal_adoption_review_seconds",
        "terminal_adoption_usage_units",
    }
    if set(value) != expected_keys:
        raise SystemExit("telemetry launch manifest fields are invalid")
    if value["schema_version"] != LAUNCH_MANIFEST_SCHEMA:
        raise SystemExit("telemetry launch manifest schema is invalid")
    supplied_sha = value["launch_manifest_sha256"]
    if not isinstance(supplied_sha, str) or len(supplied_sha) != 64:
        raise SystemExit("telemetry launch manifest self hash is invalid")
    canonical = dict(value)
    canonical["launch_manifest_sha256"] = ZERO_SHA256
    if _canonical_sha256(canonical) != supplied_sha:
        raise SystemExit("telemetry launch manifest self hash mismatch")
    limitations = value["limitations"]
    if (
        not isinstance(limitations, list)
        or not limitations
        or any(not isinstance(item, str) or not item for item in limitations)
        or len(set(limitations)) != len(limitations)
    ):
        raise SystemExit("telemetry launch manifest limitations are invalid")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch-manifest", type=Path)
    parser.add_argument("--campaign-root", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--runtime-packet-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--baseline-usage-units-per-accepted-artifact",
        type=float,
    )
    parser.add_argument(
        "--terminal-adoption-usage-units",
        type=float,
    )
    parser.add_argument(
        "--terminal-adoption-review-seconds",
        type=float,
    )
    parser.add_argument("--limitation", action="append")
    args = parser.parse_args()
    direct_values = {
        "baseline_usage_units_per_accepted_artifact": (
            args.baseline_usage_units_per_accepted_artifact
        ),
        "campaign_root": args.campaign_root,
        "contract": args.contract,
        "database": args.database,
        "limitations": args.limitation,
        "output_root": args.output_root,
        "runtime_packet_root": args.runtime_packet_root,
        "terminal_adoption_review_seconds": args.terminal_adoption_review_seconds,
        "terminal_adoption_usage_units": args.terminal_adoption_usage_units,
    }
    if args.launch_manifest is not None:
        if any(value is not None for value in direct_values.values()):
            parser.error("--launch-manifest cannot be combined with direct arguments")
        launch = _load_launch_manifest(args.launch_manifest)
    else:
        missing = [name for name, value in direct_values.items() if value is None]
        if missing:
            parser.error(f"missing required arguments: {', '.join(sorted(missing))}")
        launch = direct_values
    repo_root = Path(__file__).resolve().parents[1]
    bundle = build_engineering_campaign_telemetry_bundle(
        repo_root=repo_root,
        campaign_root=Path(launch["campaign_root"]),
        contract_path=Path(launch["contract"]),
        database=Path(launch["database"]),
        runtime_packet_root=Path(launch["runtime_packet_root"]),
        output_root=Path(launch["output_root"]),
        baseline_usage_units_per_accepted_artifact=(
            float(launch["baseline_usage_units_per_accepted_artifact"])
        ),
        terminal_adoption_usage_units=float(launch["terminal_adoption_usage_units"]),
        terminal_adoption_review_seconds=float(launch["terminal_adoption_review_seconds"]),
        limitations=list(launch["limitations"]),
    )
    print(
        json.dumps(
            {
                "bundle_sha256": bundle["bundle_sha256"],
                "campaign_id": bundle["campaign_id"],
                "event_count": len(bundle["events"]),
                "output_root": str(launch["output_root"]),
                "slo_passed": bundle["slo"]["passed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
