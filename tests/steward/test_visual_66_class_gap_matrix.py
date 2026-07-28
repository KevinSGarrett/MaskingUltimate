from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest
import yaml

from maskfactory.steward.continuous_contract import canonical_sha256
from maskfactory.steward.visual_66_class_gap_matrix import (
    Visual66ClassGapMatrixError,
    build_visual_66_class_gap_matrix,
    validate_visual_66_class_gap_matrix,
)
from maskfactory.vlm.critic_catalog import DEFAULT_CATALOG_PATH, load_catalog


def _catalog_bytes() -> bytes:
    return DEFAULT_CATALOG_PATH.read_bytes()


def _catalog_binding() -> dict:
    catalog = load_catalog()
    return {
        "catalog_id": catalog["catalog_id"],
        "catalog_sha256": catalog["sha256"],
        "promoted_model_ids": sorted(
            model["model_id"] for model in catalog["models"] if model["lifecycle"] == "promoted"
        ),
        "promoted_role_assignments": {
            role_id: sorted(
                model["model_id"]
                for model in catalog["models"]
                if model["lifecycle"] == "promoted" and role_id in model["assigned_roles"]
            )
            for role_id in ("primary_visual_critic", "independent_juror")
        },
    }


def _ontology() -> bytes:
    labels = [
        {
            "id": index,
            "name": (
                {
                    0: "background",
                    1: "hair",
                    24: "left_thumb",
                    46: "left_toes",
                    65: "anus",
                }.get(index, f"class_{index}")
            ),
            "map": "part",
            "side": "na" if index == 0 else "center",
            "enabled": True,
        }
        for index in range(66)
    ]
    return yaml.safe_dump({"labels": labels}, sort_keys=False).encode()


def _readiness() -> bytes:
    catalog_bytes = _catalog_bytes()
    value = {
        "schema_version": "maskfactory.visual_reference_readiness.v1",
        "authority_boundary": {
            "classification": "REFERENCE_COVERAGE_ONLY",
            "promotion_allowed": False,
            "qualified_mask_truth_present": False,
            "qualified_high_end_primary_present": False,
            "qualified_independent_family_juror_present": False,
        },
        "reference_library": {
            "benchmark_body_part_tag_counts": {
                "part_hair": 10,
                "part_hand_fingers": 4,
                "part_foot_toes": 3,
                "part_groin_intimate": 2,
            }
        },
        "sources": {
            "critic_catalog": {
                "path": str(DEFAULT_CATALOG_PATH.resolve()),
                "bytes": len(catalog_bytes),
                "sha256": hashlib.sha256(catalog_bytes).hexdigest(),
            }
        },
        "critic_catalog": _catalog_binding(),
        "readiness": {
            "ready_for_source_bound_candidate_screening": True,
            "ready_for_source_bound_candidate_selection": False,
            "metadata_candidate_selection_requires_direct_visual_confirmation": True,
            "ready_for_visual_qualification": False,
        },
        "self_sha256": "0" * 64,
    }
    value["self_sha256"] = canonical_sha256(value)
    return json.dumps(value).encode()


def _crosswalk() -> bytes:
    return json.dumps(
        {
            "schema_version": "maskfactory.nude_external_ontology_crosswalk.v1",
            "not_directly_supplied_as_reliable_fine_masks": [
                "left_nipple",
                "right_nipple",
                "penis_glans",
            ],
        }
    ).encode()


def _build() -> dict:
    return build_visual_66_class_gap_matrix(
        ontology_bytes=_ontology(),
        ontology_git_commit="a" * 40,
        ontology_git_path="configs/ontology_v2.yaml",
        ontology_git_blob="b" * 40,
        readiness_bytes=_readiness(),
        critic_catalog_bytes=_catalog_bytes(),
        crosswalk_bytes=_crosswalk(),
        observed_at_utc="2026-07-27T00:00:00Z",
    )


def test_builds_exact_no_credit_66_class_matrix() -> None:
    receipt = _build()
    validate_visual_66_class_gap_matrix(receipt)
    assert [row["class_id"] for row in receipt["classes"]] == list(range(66))
    assert receipt["summary"]["classes_with_current_qualified_mask_truth"] == 0
    assert receipt["summary"]["promotion_eligible_classes"] == 0
    assert receipt["authority_boundary"]["candidate_materialization_allowed"] is False
    assert receipt["classes"][24]["reference_metadata_tag"] == "part_hand_fingers"
    assert receipt["classes"][46]["reference_metadata_tag"] == "part_foot_toes"
    assert receipt["classes"][65]["completed_calibration_only"] is True


def test_rejects_noncontiguous_part_ids() -> None:
    ontology = yaml.safe_load(_ontology())
    ontology["labels"][5]["id"] = 99
    with pytest.raises(
        Visual66ClassGapMatrixError,
        match="exactly 0..65",
    ):
        build_visual_66_class_gap_matrix(
            ontology_bytes=yaml.safe_dump(ontology).encode(),
            ontology_git_commit="a" * 40,
            ontology_git_path="configs/ontology_v2.yaml",
            ontology_git_blob="b" * 40,
            readiness_bytes=_readiness(),
            critic_catalog_bytes=_catalog_bytes(),
            crosswalk_bytes=_crosswalk(),
            observed_at_utc="2026-07-27T00:00:00Z",
        )


def test_validator_rejects_resealed_promotion_claim() -> None:
    receipt = deepcopy(_build())
    receipt["summary"]["promotion_eligible_classes"] = 1
    receipt["self_sha256"] = "0" * 64
    receipt["self_sha256"] = canonical_sha256(receipt)
    with pytest.raises(
        Visual66ClassGapMatrixError,
        match="exceeds current authority",
    ):
        validate_visual_66_class_gap_matrix(receipt)
