from __future__ import annotations

import pytest

from maskfactory.residual_blocker_inventory import (
    ResidualBlockerInventoryError,
    classify_residual,
    refuse_inventory_overclaim,
    run_residual_blocker_inventory_suite,
)
from maskfactory.validation import validate_document


def test_overclaim_fail_closed() -> None:
    with pytest.raises(ResidualBlockerInventoryError, match="host_side_static_gaps_remain"):
        refuse_inventory_overclaim({"host_side_static_gaps_remain": True})
    with pytest.raises(ResidualBlockerInventoryError, match="gold_claimed"):
        refuse_inventory_overclaim({"gold_claimed": True})
    with pytest.raises(ResidualBlockerInventoryError, match="any_item_completed_by_this_inventory"):
        refuse_inventory_overclaim({"any_item_completed_by_this_inventory": True})


def test_classify_known_non_delegable_buckets() -> None:
    assert (
        classify_residual(
            {
                "id": "MF-P1-08.02",
                "description": "Annotate image 1 fully in CVAT",
                "blocked_reason": "NEEDS KEVIN: CVAT annotation clicks",
                "notes": [],
            }
        )[0]
        == "NEEDS_KEVIN_CVAT"
    )
    assert (
        classify_residual(
            {
                "id": "MF-P6-11.01",
                "description": "MaskFactoryAdapter",
                "blocked_reason": "AWAITING_MAIN/STATIC_PASS",
                "notes": [],
            }
        )[0]
        == "AWAITING_MAIN"
    )
    assert (
        classify_residual(
            {
                "id": "MF-P9-14.06",
                "description": "18k retrieval",
                "blocked_reason": "capacity-held under 150 GiB soft floor",
                "notes": [],
            }
        )[0]
        == "DISK_HEAVY_CORPUS"
    )


def test_suite_seals_schema_valid_inventory() -> None:
    report = run_residual_blocker_inventory_suite()
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["host_side_static_gaps_remain"] is False
    assert report["any_item_completed_by_this_inventory"] is False
    assert report["doctor_green_claimed"] is False
    assert report["gold_claimed"] is False
    assert report["main_complete_claimed"] is False
    assert report["production_evidence_pass_claimed"] is False
    assert report["unfinished_item_count"] == len(report["items"])
    assert report["unfinished_item_count"] >= 1
    assert sum(report["residual_class_counts"].values()) == report["unfinished_item_count"]
    assert report["residual_class_counts"]["NEEDS_KEVIN_CVAT"] >= 1
    assert report["residual_class_counts"]["AWAITING_MAIN"] >= 1
    assert validate_document(report, "residual_blocker_inventory_report") == ()
