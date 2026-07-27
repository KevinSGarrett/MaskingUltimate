"""Deterministic autonomous-resolution workload for the ontology-v2 pilot."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .ontology_v2_authority_pilot import canonical_sha256, verify_authority_pilot

SCHEMA_VERSION = "maskfactory.ontology_v2_resolution_workload.v2"
AUTHORITY = "scheduling_only_no_semantic_mask_gold_or_certificate_authority"
REQUIRED_STAGES = (
    "source_identity",
    "coverage_target_validation",
    "provider_proposals",
    "owner_and_candidate_binding",
    "canonical_target_contract_materialization",
    "deterministic_hard_qa",
    "qualified_primary_visual_review",
    "independent_family_juror_review",
    "bounded_repair_if_needed",
    "semantic_alignment",
    "immutable_outcome",
)


class OntologyV2ResolutionWorkloadError(ValueError):
    """The resolution workload violated its closed scheduling contract."""


def _sha(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_resolution_workload(
    pilot: Mapping[str, Any], *, pilot_manifest_file_sha256: str
) -> dict[str, Any]:
    """Build queued work without upgrading any pilot evidence or authority."""

    verify_authority_pilot(pilot)
    if len(pilot_manifest_file_sha256) != 64:
        raise OntologyV2ResolutionWorkloadError("pilot_manifest_file_sha256_invalid")
    entries: list[dict[str, Any]] = []
    for image in pilot["images"]:
        for coverage_target_ordinal, target in enumerate(image["coverage_targets"]):
            coverage_target_hash = _sha(target)
            identity = {
                "pilot_manifest_self_sha256": pilot["self_sha256"],
                "image_id": image["image_id"],
                "coverage_target_ordinal": coverage_target_ordinal,
                "source_encoded_sha256": image["source_encoded_sha256"],
                "coverage_target_sha256": coverage_target_hash,
            }
            entries.append(
                {
                    "work_unit_id": f"v2r_{_sha(identity)[:32]}",
                    "ordinal": 0,
                    "image_id": image["image_id"],
                    "coverage_target_ordinal": coverage_target_ordinal,
                    "source_kind": image["source_kind"],
                    "source_path": image["source_path"],
                    "runpod_path": image.get("runpod_path"),
                    "source_encoded_sha256": image["source_encoded_sha256"],
                    "source_decoded_pixel_sha256": image.get("source_decoded_pixel_sha256"),
                    "split_group_id": image["split_group_id"],
                    "coverage_target": dict(target),
                    "coverage_target_sha256": coverage_target_hash,
                    "status": "queued",
                    "attempt_count": 0,
                    "max_attempts": 3,
                    "lease": None,
                    "result": None,
                    "authority": "none",
                    "required_stages": list(REQUIRED_STAGES),
                }
            )
    entries.sort(
        key=lambda row: (
            row["coverage_target"]["canonical_label"],
            row["coverage_target"]["requested_state"],
            row["source_encoded_sha256"],
        )
    )
    for ordinal, entry in enumerate(entries):
        entry["ordinal"] = ordinal
    core: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "ontology_v2_autonomous_resolution_workload",
        "authority": AUTHORITY,
        "pilot_manifest_file_sha256": pilot_manifest_file_sha256,
        "pilot_manifest_self_sha256": pilot["self_sha256"],
        "ontology_version": pilot["ontology_version"],
        "ontology_sha256": pilot["ontology_sha256"],
        "work_unit_count": len(entries),
        "queued_count": len(entries),
        "completed_count": 0,
        "failed_count": 0,
        "completion_claimed": False,
        "required_stages": list(REQUIRED_STAGES),
        "entries": entries,
        "claim_limits": [
            "queue membership is not semantic review, mask truth, gold, or certification",
            "contact sheets and provider agreement cannot complete a work unit",
            "every work unit requires both qualified independent visual roles",
            "one failed work unit cannot stop unrelated work units",
            "all pixel changes require a new immutable candidate and complete re-review",
        ],
    }
    core["self_sha256"] = canonical_sha256(core)
    verify_resolution_workload(core, pilot=pilot)
    return core


def verify_resolution_workload(
    workload: Mapping[str, Any], *, pilot: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    required = {
        "schema_version",
        "artifact_type",
        "authority",
        "pilot_manifest_file_sha256",
        "pilot_manifest_self_sha256",
        "ontology_version",
        "ontology_sha256",
        "work_unit_count",
        "queued_count",
        "completed_count",
        "failed_count",
        "completion_claimed",
        "required_stages",
        "entries",
        "claim_limits",
        "self_sha256",
    }
    if set(workload) != required:
        raise OntologyV2ResolutionWorkloadError("workload_top_level_fields_not_closed")
    if (
        workload["schema_version"] != SCHEMA_VERSION
        or workload["authority"] != AUTHORITY
        or workload["completion_claimed"] is not False
        or workload["completed_count"] != 0
        or workload["failed_count"] != 0
        or workload["required_stages"] != list(REQUIRED_STAGES)
    ):
        raise OntologyV2ResolutionWorkloadError("workload_authority_boundary_invalid")
    if canonical_sha256(workload) != workload["self_sha256"]:
        raise OntologyV2ResolutionWorkloadError("workload_self_hash_mismatch")
    entries = workload["entries"]
    if not isinstance(entries, list) or not entries:
        raise OntologyV2ResolutionWorkloadError("workload_entries_invalid")
    if workload["work_unit_count"] != len(entries) or workload["queued_count"] != len(entries):
        raise OntologyV2ResolutionWorkloadError("workload_counts_invalid")
    expected_entry_fields = {
        "work_unit_id",
        "ordinal",
        "image_id",
        "coverage_target_ordinal",
        "source_kind",
        "source_path",
        "runpod_path",
        "source_encoded_sha256",
        "source_decoded_pixel_sha256",
        "split_group_id",
        "coverage_target",
        "coverage_target_sha256",
        "status",
        "attempt_count",
        "max_attempts",
        "lease",
        "result",
        "authority",
        "required_stages",
    }
    ids: set[str] = set()
    actual_bindings: set[tuple[str, int, str]] = set()
    for ordinal, entry in enumerate(entries):
        if set(entry) != expected_entry_fields:
            raise OntologyV2ResolutionWorkloadError("workload_entry_fields_not_closed")
        if entry["work_unit_id"] in ids:
            raise OntologyV2ResolutionWorkloadError("workload_duplicate_work_unit")
        ids.add(entry["work_unit_id"])
        if (
            entry["ordinal"] != ordinal
            or entry["status"] != "queued"
            or entry["attempt_count"] != 0
            or entry["max_attempts"] != 3
            or entry["lease"] is not None
            or entry["result"] is not None
            or entry["authority"] != "none"
            or entry["required_stages"] != list(REQUIRED_STAGES)
        ):
            raise OntologyV2ResolutionWorkloadError("workload_entry_state_invalid")
        if _sha(entry["coverage_target"]) != entry["coverage_target_sha256"]:
            raise OntologyV2ResolutionWorkloadError("workload_coverage_target_hash_mismatch")
        actual_bindings.add(
            (
                entry["image_id"],
                entry["coverage_target_ordinal"],
                entry["coverage_target_sha256"],
            )
        )
    if pilot is not None:
        verify_authority_pilot(pilot)
        if workload["pilot_manifest_self_sha256"] != pilot["self_sha256"]:
            raise OntologyV2ResolutionWorkloadError("workload_pilot_binding_mismatch")
        expected_bindings = {
            (image["image_id"], coverage_target_ordinal, _sha(target))
            for image in pilot["images"]
            for coverage_target_ordinal, target in enumerate(image["coverage_targets"])
        }
        if actual_bindings != expected_bindings:
            raise OntologyV2ResolutionWorkloadError("workload_coverage_population_mismatch")
    return {
        "status": "PASS_QUEUED_NO_AUTHORITY",
        "work_unit_count": len(entries),
        "completed_count": 0,
        "completion_claimed": False,
    }


__all__ = [
    "AUTHORITY",
    "REQUIRED_STAGES",
    "SCHEMA_VERSION",
    "OntologyV2ResolutionWorkloadError",
    "build_resolution_workload",
    "verify_resolution_workload",
]
