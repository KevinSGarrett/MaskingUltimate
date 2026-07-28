"""Fail-closed authority classification for historical CAA populations."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


class HistoricalCaaReconciliationError(ValueError):
    """Historical lifecycle/package evidence is incomplete or contradictory."""


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def classify_historical_caa_authority(audit: Mapping[str, Any]) -> dict[str, Any]:
    """Reconcile lifecycle, primary packages, and the isolated 220 audit subset."""

    if (
        not isinstance(audit, Mapping)
        or audit.get("schema_version") != "maskfactory.runpod_caa_reconciliation_audit.v1"
        or audit.get("operation") != "read_only_sanitized_caa_reconciliation"
        or audit.get("authority_claimed") is not False
    ):
        raise HistoricalCaaReconciliationError("CAA audit envelope is invalid")
    body = {key: value for key, value in audit.items() if key != "inventory_sha256"}
    if audit.get("inventory_sha256") != _sha256(body):
        raise HistoricalCaaReconciliationError("CAA audit inventory seal is invalid")
    row = audit.get("reconciliation")
    if not isinstance(row, Mapping):
        raise HistoricalCaaReconciliationError("CAA reconciliation row is missing")
    required_counts = (
        "database_image_count",
        "database_truth_count",
        "primary_materialized_package_count",
        "primary_lifecycle_path_exists_count",
        "primary_lifecycle_hash_verified_count",
        "primary_source_hash_verified_count",
        "primary_winner_hash_verified_count",
        "primary_complete_semantic_quorum_count",
        "primary_current_authority_eligible_count",
        "isolated_materialized_package_count",
        "isolated_overlap_with_primary_count",
        "isolated_complete_semantic_quorum_count",
        "isolated_current_authority_eligible_count",
        "lifecycle_only_count",
        "primary_without_lifecycle_count",
    )
    if any(
        isinstance(row.get(field), bool) or not isinstance(row.get(field), int) or row[field] < 0
        for field in required_counts
    ):
        raise HistoricalCaaReconciliationError("CAA reconciliation counts are invalid")
    total = row["primary_materialized_package_count"]
    if (
        row.get("database_image_truth_exact_match") is not True
        or row.get("primary_matches_database_exactly") is not True
        or row.get("isolated_is_exact_primary_subset") is not True
        or row["database_image_count"] != total
        or row["database_truth_count"] != total
        or row["primary_lifecycle_path_exists_count"] != total
        or row["primary_source_hash_verified_count"] != total
        or row["primary_winner_hash_verified_count"] != total
        or row["isolated_overlap_with_primary_count"] != row["isolated_materialized_package_count"]
        or row["lifecycle_only_count"] != 0
        or row["primary_without_lifecycle_count"] != 0
    ):
        raise HistoricalCaaReconciliationError("CAA lifecycle/package sets do not reconcile")
    eligible = row["primary_current_authority_eligible_count"]
    complete_bindings = row["primary_complete_semantic_quorum_count"]
    lifecycle_current = row["primary_lifecycle_hash_verified_count"]
    if eligible > min(total, complete_bindings, lifecycle_current):
        raise HistoricalCaaReconciliationError("CAA eligible count exceeds current evidence")
    isolated_eligible = row["isolated_current_authority_eligible_count"]
    if isolated_eligible > row["isolated_complete_semantic_quorum_count"]:
        raise HistoricalCaaReconciliationError("isolated CAA eligibility exceeds bindings")
    quarantined = total - eligible
    result = {
        "schema_version": "maskfactory.historical_caa_authority_reconciliation.v1",
        "source_audit_sha256": audit["inventory_sha256"],
        "lifecycle_record_count": row["database_image_count"],
        "materialized_primary_package_count": total,
        "isolated_audit_subset_count": row["isolated_materialized_package_count"],
        "lifecycle_only_count": row["lifecycle_only_count"],
        "primary_without_lifecycle_count": row["primary_without_lifecycle_count"],
        "current_semantic_and_quorum_binding_count": complete_bindings,
        "current_lifecycle_hash_binding_count": lifecycle_current,
        "current_authority_eligible_count": eligible,
        "quarantined_legacy_package_count": quarantined,
        "machine_candidate_use_count": 0,
        "operational_use_count": 0,
        "autonomous_training_truth_count": eligible,
        "isolated_subset_is_not_additional_population": True,
        "historical_bytes_preserved": True,
        "authority_claimed": False,
        "training_admission_allowed": eligible > 0 and quarantined == 0,
        "production_mask_authority_allowed": False,
        "required_action": (
            "publish_new_immutable_package_revisions_with_current_semantic_alignment_"
            "and_independent_critic_quorum"
        ),
    }
    return {**result, "report_sha256": _sha256(result)}


__all__ = ["HistoricalCaaReconciliationError", "classify_historical_caa_authority"]
