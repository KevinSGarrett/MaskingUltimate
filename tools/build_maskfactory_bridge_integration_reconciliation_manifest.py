"""Reconcile the frozen bridge packet with a later base-integration tree.

The original preservation manifest is immutable evidence of the producer
packet before commit.  A later merge may legitimately update base-owned files
that were also present in that packet.  This manifest records every such byte
change without rewriting the producer packet or weakening the twelve wire
contract hashes consumed by Comfy_UI_Main.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT / "Plan" / "Instructions" / "10_AUTONOMOUS_CORE_BRIDGE_PLANNING_PRESERVATION_MANIFEST.json"
)
OUTPUT = (
    ROOT
    / "Plan"
    / "Instructions"
    / "11_AUTONOMOUS_CORE_BRIDGE_INTEGRATION_RECONCILIATION_MANIFEST.json"
)
PRODUCER_COMMIT = "938b46949e277d92f26d9411fd5710005c506677"
INTEGRATION_BASE_COMMIT = "85d4c19b7974c1b64f48176d91211defbaba35a0"
WIRE_CONTRACT_PATHS = (
    "src/maskfactory/schemas/mask_acquisition_receipt.schema.json",
    "src/maskfactory/schemas/mask_acquisition_request.schema.json",
    "src/maskfactory/schemas/mask_authority_invalidation_event.schema.json",
    "src/maskfactory/schemas/mask_bridge_error.schema.json",
    "src/maskfactory/schemas/mask_bridge_event.schema.json",
    "src/maskfactory/schemas/mask_bridge_semantic_invariant_profile.schema.json",
    "src/maskfactory/schemas/mask_repair_feedback.schema.json",
    "src/maskfactory/schemas/maskfactory_adoption_receipt.schema.json",
    "src/maskfactory/schemas/maskfactory_capability_snapshot.schema.json",
    "src/maskfactory/schemas/maskfactory_consumer_requirements.schema.json",
    "src/maskfactory/schemas/maskfactory_release_snapshot.schema.json",
    "src/maskfactory/schemas/operational_autonomy_certificate.schema.json",
)
BASE_OWNED_SUPERSESSION_PATHS = {
    "Plan/Tracker/DASHBOARD.md",
    "Plan/Tracker/phases/P0.md",
    "Plan/Tracker/phases/P2.md",
    "Plan/Tracker/phases/P3.md",
    "Plan/Tracker/tracker.json",
    "src/maskfactory/validation.py",
}
INTEGRATION_PROTOCOL_UPDATE_PATHS = {
    "Plan/Instructions/09_CROSS_PROJECT_BRIDGE_RELEASE_AND_SESSION_HANDOFF.md",
    "tests/test_tracker_completion_profiles.py",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def _load_source() -> dict[str, Any]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    claimed = source["manifest_sha256"]
    payload = {key: value for key, value in source.items() if key != "manifest_sha256"}
    if _canonical_sha256(payload) != claimed:
        raise RuntimeError("source_preservation_manifest_self_seal_mismatch")
    return source


def _live_record(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    exists = path.is_file()
    return {
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else None,
        "sha256": _sha256_bytes(path.read_bytes()) if exists else None,
    }


def build_manifest(*, generated_at: str | None = None) -> dict[str, Any]:
    source = _load_source()
    source_entries = source["source_state"]["entries"]
    by_path = {entry["path"]: entry for entry in source_entries}
    drift: list[dict[str, Any]] = []
    unchanged = 0
    for entry in source_entries:
        live = _live_record(entry["path"])
        if (
            live["exists"] == entry["exists"]
            and live["size_bytes"] == entry["size_bytes"]
            and live["sha256"] == entry["sha256"]
        ):
            unchanged += 1
            continue
        relative = entry["path"]
        if relative in BASE_OWNED_SUPERSESSION_PATHS:
            classification = "base_owned_supersession_after_packet_freeze"
        elif relative in INTEGRATION_PROTOCOL_UPDATE_PATHS:
            classification = "integration_reconciliation_protocol_update"
        else:
            raise RuntimeError(f"unaccounted_integration_drift:{relative}")
        drift.append(
            {
                "path": relative,
                "classification": classification,
                "producer_exists": entry["exists"],
                "producer_size_bytes": entry["size_bytes"],
                "producer_sha256": entry["sha256"],
                "integration_exists": live["exists"],
                "integration_size_bytes": live["size_bytes"],
                "integration_sha256": live["sha256"],
            }
        )
    drift.sort(key=lambda row: row["path"].casefold())

    wire_contracts: list[dict[str, Any]] = []
    for relative in WIRE_CONTRACT_PATHS:
        entry = by_path.get(relative)
        if entry is None:
            raise RuntimeError(f"wire_contract_missing_from_source_manifest:{relative}")
        live = _live_record(relative)
        if not live["exists"] or live["sha256"] != entry["sha256"]:
            raise RuntimeError(f"wire_contract_changed_during_base_integration:{relative}")
        wire_contracts.append(
            {
                "path": relative,
                "sha256": entry["sha256"],
                "size_bytes": entry["size_bytes"],
            }
        )

    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "manifest_id": "maskfactory_autonomous_core_bridge_integration_reconciliation_v1",
        "generated_at": generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authority": "integration_reconciliation_only_no_runtime_release_or_artifact_authority",
        "runtime_completion_claimed": False,
        "source_preservation_manifest": {
            "path": SOURCE.relative_to(ROOT).as_posix(),
            "manifest_sha256": source["manifest_sha256"],
            "entry_count": source["source_state"]["entry_count"],
            "entries_sha256": source["source_state"]["entries_sha256"],
        },
        "git_lineage": {
            "immutable_producer_packet_commit": PRODUCER_COMMIT,
            "integrated_base_commit": INTEGRATION_BASE_COMMIT,
            "integration_strategy": "non_rewriting_merge_commit",
        },
        "reconciliation": {
            "source_entry_count": len(source_entries),
            "unchanged_entry_count": unchanged,
            "reconciled_change_count": len(drift),
            "base_owned_supersession_count": sum(
                row["classification"] == "base_owned_supersession_after_packet_freeze"
                for row in drift
            ),
            "integration_protocol_update_count": sum(
                row["classification"] == "integration_reconciliation_protocol_update"
                for row in drift
            ),
            "reconciled_changes": drift,
            "unaccounted_drift_count": 0,
        },
        "wire_contract_freeze": {
            "contract_count": len(wire_contracts),
            "all_exactly_unchanged": True,
            "contracts": wire_contracts,
        },
    }
    document["manifest_sha256"] = _canonical_sha256(document)
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    existing = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.is_file() else None
    generated_at = str(existing["generated_at"]) if existing is not None else None
    document = build_manifest(generated_at=generated_at)
    rendered = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != rendered:
            raise SystemExit("integration reconciliation manifest is stale")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(rendered, encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "reconciled_change_count": document["reconciliation"]["reconciled_change_count"],
                "manifest_sha256": document["manifest_sha256"],
                "wire_contract_count": document["wire_contract_freeze"]["contract_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
