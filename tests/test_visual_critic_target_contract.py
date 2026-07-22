from __future__ import annotations

from copy import deepcopy

import pytest

from maskfactory.vlm.target_contract import (
    TargetContractError,
    authorize_critic_invocation,
    target_contract_sha256,
    validate_target_contract,
)


def _contract() -> dict:
    contract = {
        "schema_version": "1.0.0",
        "contract_id": "target-image-1-p0-left-hand",
        "source": {"image_id": "image-1", "sha256": "a" * 64, "width": 100, "height": 80},
        "owner": {
            "person_index": 0,
            "character_instance_id": "character-1-instance-0",
            "person_mask_sha256": "b" * 64,
        },
        "target": {
            "label_id": "left_hand",
            "expected_presence": "visible_nonempty",
            "minimum_area_pixels": 10,
            "maximum_area_pixels": 1200,
            "allowed_roi_xyxy": [10, 5, 60, 70],
            "inclusion_rule": "visible_pixels_only",
            "exclusion_rule": "exclude_occluded_outside_owner_and_named_labels",
        },
        "candidate": {
            "mask_sha256": "c" * 64,
            "width": 100,
            "height": 80,
            "binary_values": [0, 255],
        },
        "excluded_labels": ["left_forearm", "torso"],
        "protected_regions": [
            {
                "region_id": "protected-left-forearm",
                "label_id": "left_forearm",
                "owner_person_index": 0,
                "mask_sha256": "d" * 64,
            }
        ],
        "transforms": {
            "source_to_candidate": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "candidate_to_source": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        },
    }
    contract["contract_sha256"] = target_contract_sha256(contract)
    return contract


def _reseal(contract: dict) -> None:
    contract["contract_sha256"] = target_contract_sha256(contract)


def _contract_v2() -> dict:
    identity = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    contract = {
        "schema_version": "2.0.0",
        "contract_id": "target-v2-image-1-p0-left-hand",
        "source": {
            "image_id": "image-1",
            "encoded_sha256": "a" * 64,
            "decoded_pixel_sha256": "b" * 64,
            "width": 100,
            "height": 80,
            "decoder": {
                "name": "Pillow",
                "version": "12.0",
                "exif_orientation": "applied",
                "color_policy": "RGB",
                "icc_policy": "converted_srgb",
                "alpha_policy": "composite_black",
            },
        },
        "owner": {
            "person_index": 0,
            "character_instance_id": "character-1-instance-0",
            "person_mask_sha256": "c" * 64,
        },
        "target": {
            "label_id": "left_hand",
            "ontology_version": "2.0.0",
            "ontology_sha256": "d" * 64,
            "label_scale": "atomic_anatomy",
            "laterality": "left",
            "perspective": "character_perspective",
            "visibility_policy": "visible_only",
            "expected_state": "present",
            "inclusions": ["all visible left-hand pixels"],
            "exclusions": ["left forearm", "clothing", "background"],
            "allowed_roi_xyxy": [10, 5, 60, 70],
            "overlap_policy": {
                "protected_overlap_max_pixels": 0,
                "cross_person_overlap_max_pixels": 0,
                "containment_rule": "inside_owner",
            },
            "topology_policy": {
                "minimum_components": 1,
                "maximum_components": 6,
                "holes_allowed": False,
                "thin_structures_expected": True,
            },
            "context": {
                "truncated": False,
                "contact": False,
                "self_occluded": False,
                "cross_person_occluded": False,
                "crop_edge": False,
                "out_of_frame": False,
            },
        },
        "candidate": {
            "encoded_sha256": "e" * 64,
            "decoded_pixel_sha256": "f" * 64,
            "width": 100,
            "height": 80,
            "binary_values": [0, 255],
            "coordinate_space": "canonical_source_pixels",
        },
        "protected_regions": [
            {
                "region_id": "left-forearm",
                "label_id": "left_forearm",
                "owner_person_index": 0,
                "mask_sha256": "1" * 64,
                "overlap_max_pixels": 0,
            }
        ],
        "transforms": {
            "coordinate_space": "canonical_source_pixels",
            "chain": [
                {
                    "operation": "identity",
                    "from_space": "canonical_source_pixels",
                    "to_space": "canonical_source_pixels",
                    "matrix": identity,
                    "inverse_matrix": identity,
                }
            ],
            "round_trip_sha256": "2" * 64,
        },
        "package": {"package_id": "package-1", "revision": 2, "parent_revision": 1},
    }
    _reseal(contract)
    return contract


def test_exact_target_contract_authorizes_hash_bound_invocation() -> None:
    contract = _contract()
    result = authorize_critic_invocation(
        contract,
        source_sha256="a" * 64,
        candidate_mask_sha256="c" * 64,
        source_size=(100, 80),
    )
    assert result["contract_id"] == contract["contract_id"]
    assert len(result["invocation_sha256"]) == 64


def test_v2_target_contract_binds_complete_semantics_and_decoded_pixels() -> None:
    contract = _contract_v2()
    validate_target_contract(contract)
    result = authorize_critic_invocation(
        contract,
        source_sha256="b" * 64,
        candidate_mask_sha256="f" * 64,
        source_size=(100, 80),
    )
    assert result["contract_sha256"] == contract["contract_sha256"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda row: row["source"].pop("decoded_pixel_sha256"), "incomplete"),
        (lambda row: row["target"].pop("laterality"), "incomplete"),
        (lambda row: row["target"].__setitem__("perspective", "viewer"), "perspective"),
        (lambda row: row["target"]["context"].pop("contact"), "incomplete"),
        (lambda row: row["package"].__setitem__("parent_revision", 2), "parent revision"),
    ],
)
def test_v2_target_contract_missing_semantics_fail_before_review(mutation, message: str) -> None:
    contract = deepcopy(_contract_v2())
    mutation(contract)
    _reseal(contract)
    with pytest.raises(TargetContractError, match=message):
        validate_target_contract(contract)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda row: row.pop("owner"), "fields are incomplete"),
        (lambda row: row["target"].__setitem__("label_id", ""), "ambiguous"),
        (lambda row: row["target"].__setitem__("minimum_area_pixels", True), "nonnegative"),
        (
            lambda row: row["target"].__setitem__("expected_presence", "maybe"),
            "expected_presence",
        ),
        (lambda row: row["target"].__setitem__("allowed_roi_xyxy", [0, 0, 101, 80]), "escapes"),
        (lambda row: row["candidate"].__setitem__("binary_values", [0, 1]), "strict binary"),
        (lambda row: row["candidate"].__setitem__("width", 99), "geometry differs"),
        (lambda row: row["excluded_labels"].append("left_hand"), "excluded label"),
        (
            lambda row: row["protected_regions"][0].__setitem__("owner_person_index", 1),
            "owner differs",
        ),
        (
            lambda row: row["transforms"].__setitem__(
                "candidate_to_source", [[1, 0, 1], [0, 1, 0], [0, 0, 1]]
            ),
            "round-trip",
        ),
    ],
)
def test_missing_or_ambiguous_target_fields_fail_before_call(mutation, message: str) -> None:
    contract = deepcopy(_contract())
    mutation(contract)
    if "contract_sha256" in contract:
        _reseal(contract)
    with pytest.raises(TargetContractError, match=message):
        validate_target_contract(contract)


@pytest.mark.parametrize(
    ("source_hash", "candidate_hash", "size", "message"),
    [
        ("e" * 64, "c" * 64, (100, 80), "source hash"),
        ("a" * 64, "e" * 64, (100, 80), "candidate hash"),
        ("a" * 64, "c" * 64, (99, 80), "source geometry"),
    ],
)
def test_live_input_drift_fails_before_critic_call(
    source_hash: str, candidate_hash: str, size: tuple[int, int], message: str
) -> None:
    with pytest.raises(TargetContractError, match=message):
        authorize_critic_invocation(
            _contract(),
            source_sha256=source_hash,
            candidate_mask_sha256=candidate_hash,
            source_size=size,
        )


def test_empty_target_requires_exact_zero_area_bounds() -> None:
    contract = _contract()
    contract["target"]["expected_presence"] = "visible_empty"
    contract["target"]["minimum_area_pixels"] = 0
    contract["target"]["maximum_area_pixels"] = 0
    _reseal(contract)
    validate_target_contract(contract)

    contract["target"]["maximum_area_pixels"] = 1
    _reseal(contract)
    with pytest.raises(TargetContractError, match="zero area"):
        validate_target_contract(contract)
