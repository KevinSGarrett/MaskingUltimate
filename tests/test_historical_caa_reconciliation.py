from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from maskfactory.autonomy.historical_caa_reconciliation import (
    HistoricalCaaReconciliationError,
    classify_historical_caa_authority,
)


def _seal(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _audit() -> dict:
    body = {
        "schema_version": "maskfactory.runpod_caa_reconciliation_audit.v1",
        "operation": "read_only_sanitized_caa_reconciliation",
        "authority_claimed": False,
        "workspace_exists": True,
        "databases": [],
        "package_roots": [],
        "reconciliation": {
            "database_image_count": 641,
            "database_truth_count": 641,
            "database_image_truth_exact_match": True,
            "primary_materialized_package_count": 641,
            "primary_lifecycle_path_exists_count": 641,
            "primary_lifecycle_hash_verified_count": 0,
            "primary_source_hash_verified_count": 641,
            "primary_winner_hash_verified_count": 641,
            "primary_complete_semantic_quorum_count": 0,
            "primary_current_authority_eligible_count": 0,
            "primary_matches_database_exactly": True,
            "isolated_materialized_package_count": 220,
            "isolated_overlap_with_primary_count": 220,
            "isolated_complete_semantic_quorum_count": 0,
            "isolated_current_authority_eligible_count": 0,
            "isolated_is_exact_primary_subset": True,
            "lifecycle_only_count": 0,
            "primary_without_lifecycle_count": 0,
        },
    }
    return {**body, "inventory_sha256": _seal(body)}


def test_current_641_population_is_entirely_quarantined_and_220_is_only_a_subset() -> None:
    result = classify_historical_caa_authority(_audit())
    assert result["lifecycle_record_count"] == 641
    assert result["materialized_primary_package_count"] == 641
    assert result["isolated_audit_subset_count"] == 220
    assert result["isolated_subset_is_not_additional_population"] is True
    assert result["quarantined_legacy_package_count"] == 641
    assert result["current_authority_eligible_count"] == 0
    assert result["machine_candidate_use_count"] == 0
    assert result["operational_use_count"] == 0
    assert result["autonomous_training_truth_count"] == 0
    assert result["training_admission_allowed"] is False
    assert result["production_mask_authority_allowed"] is False


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("primary_matches_database_exactly", False, "sets do not reconcile"),
        ("isolated_overlap_with_primary_count", 219, "sets do not reconcile"),
        ("lifecycle_only_count", 1, "sets do not reconcile"),
        ("primary_source_hash_verified_count", 640, "sets do not reconcile"),
    ],
)
def test_set_or_hash_drift_fails_closed(field: str, value, message: str) -> None:
    audit = _audit()
    audit["reconciliation"][field] = value
    audit["inventory_sha256"] = _seal(
        {key: item for key, item in audit.items() if key != "inventory_sha256"}
    )
    with pytest.raises(HistoricalCaaReconciliationError, match=message):
        classify_historical_caa_authority(audit)


def test_inventory_tamper_and_eligibility_overclaim_fail_closed() -> None:
    tampered = _audit()
    tampered["reconciliation"]["database_image_count"] = 640
    with pytest.raises(HistoricalCaaReconciliationError, match="inventory seal"):
        classify_historical_caa_authority(tampered)

    overclaimed = deepcopy(_audit())
    overclaimed["reconciliation"]["primary_current_authority_eligible_count"] = 1
    overclaimed["inventory_sha256"] = _seal(
        {key: item for key, item in overclaimed.items() if key != "inventory_sha256"}
    )
    with pytest.raises(HistoricalCaaReconciliationError, match="eligible count exceeds"):
        classify_historical_caa_authority(overclaimed)
