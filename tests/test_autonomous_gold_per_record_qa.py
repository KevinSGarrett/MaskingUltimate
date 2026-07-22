import hashlib
from pathlib import Path

import numpy as np
import pytest

from maskfactory.autonomy.package_semantic_alignment import final_mask_set_sha256
from maskfactory.autonomy.per_record_qa import (
    PerRecordQaError,
    decoded_mask_sha256,
    per_record_qa_vector_sha256,
    validate_per_record_qa_vector,
)
from maskfactory.autonomy.qa_thresholds import REQUIRED_METRICS
from maskfactory.io.hashing import sha256_file
from maskfactory.io.png_strict import write_binary_mask
from maskfactory.vlm.target_contract import target_contract_sha256

H = "a" * 64


def _contract(mask: Path) -> dict:
    encoded = sha256_file(mask)
    decoded = decoded_mask_sha256(mask)
    identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    contract = {
        "schema_version": "2.0.0",
        "contract_id": "target-left-forearm-r2",
        "source": {
            "image_id": "img-001",
            "encoded_sha256": "b" * 64,
            "decoded_pixel_sha256": "c" * 64,
            "width": 32,
            "height": 24,
            "decoder": {
                "name": "pillow",
                "version": "fixture",
                "exif_orientation": "normalized",
                "color_policy": "srgb",
                "icc_policy": "converted",
                "alpha_policy": "composited_black",
            },
        },
        "owner": {
            "person_index": 0,
            "character_instance_id": "character-001",
            "person_mask_sha256": "d" * 64,
        },
        "target": {
            "label_id": "left_forearm",
            "ontology_version": "body_parts_v2",
            "ontology_sha256": "e" * 64,
            "label_scale": "atomic_anatomy",
            "laterality": "left",
            "perspective": "character_perspective",
            "visibility_policy": "visible_only",
            "expected_state": "present",
            "inclusions": ["visible_left_forearm_skin"],
            "exclusions": ["hand", "upper_arm", "clothing"],
            "allowed_roi_xyxy": [0, 0, 32, 24],
            "overlap_policy": {
                "protected_overlap_max_pixels": 0,
                "cross_person_overlap_max_pixels": 0,
                "containment_rule": "inside_owner",
            },
            "topology_policy": {
                "minimum_components": 1,
                "maximum_components": 2,
                "holes_allowed": False,
                "thin_structures_expected": False,
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
            "encoded_sha256": encoded,
            "decoded_pixel_sha256": decoded,
            "width": 32,
            "height": 24,
            "binary_values": [0, 255],
            "coordinate_space": "source_pixel",
        },
        "protected_regions": [],
        "transforms": {
            "coordinate_space": "source_pixel",
            "chain": [
                {
                    "operation": "identity",
                    "from_space": "source_pixel",
                    "to_space": "source_pixel",
                    "matrix": identity,
                    "inverse_matrix": identity,
                }
            ],
            "round_trip_sha256": "f" * 64,
        },
        "package": {"package_id": "pkg-001", "revision": 2, "parent_revision": 1},
    }
    contract["contract_sha256"] = target_contract_sha256(contract)
    return contract


def _fixture(tmp_path: Path):
    root = tmp_path / "package"
    mask = write_binary_mask(
        root / "masks/left_forearm.png",
        np.pad(np.ones((8, 10), dtype=np.uint8) * 255, ((8, 8), (11, 11))),
    )
    manifest = {
        "parts": {
            "left_forearm": {
                "status": "draft_model_generated",
                "mask_file": "masks/left_forearm.png",
            }
        }
    }
    contract = _contract(mask)
    registry = {
        "registry_id": "autonomous_gold_per_label_context_qa_v1",
        "registry_file_sha256": "1" * 64,
        "resolved_registry_sha256": "2" * 64,
        "ontology_sha256": "e" * 64,
        "calibration_evidence_sha256": "3" * 64,
        "qualification_status": "qualified_for_autonomous_gold",
        "authority_eligible": True,
        "resolved_label_threshold_sha256s": {"left_forearm": "4" * 64},
    }
    metrics = [
        {
            "metric": name,
            "status": "pass",
            "value": True,
            "evidence_sha256": hashlib.sha256(f"evidence:{name}".encode()).hexdigest(),
            "executor_sha256": "5" * 64,
        }
        for name in sorted(REQUIRED_METRICS)
    ]
    vector = {
        "schema_version": "1.0.0",
        "vector_id": "qa-vector-001",
        "image_id": "img-001",
        "person_index": 0,
        "character_instance_id": "character-001",
        "package_id": "pkg-001",
        "package_revision": 2,
        "parent_package_revision": 1,
        "final_mask_set_sha256": final_mask_set_sha256(root, manifest),
        "registry_binding": {
            key: value
            for key, value in registry.items()
            if key != "resolved_label_threshold_sha256s"
        },
        "labels": [
            {
                "label": "left_forearm",
                "target_contract_sha256": contract["contract_sha256"],
                "threshold_resolution_sha256": "4" * 64,
                "mask_encoded_sha256": sha256_file(mask),
                "mask_decoded_pixel_sha256": decoded_mask_sha256(mask),
                "metrics": metrics,
                "hard_vetoes_passed": True,
                "status": "pass",
            }
        ],
        "status": "pass",
        "authority_claim": "qualified_deterministic_QA_only_not_gold",
    }
    vector["vector_sha256"] = per_record_qa_vector_sha256(vector)
    return root, manifest, {"left_forearm": contract}, registry, vector


def _validate(fixture):
    root, manifest, contracts, registry, vector = fixture
    return validate_per_record_qa_vector(
        vector,
        package_root=root,
        manifest=manifest,
        target_contracts=contracts,
        qualified_registry=registry,
    )


def _reseal(vector: dict) -> None:
    vector["vector_sha256"] = per_record_qa_vector_sha256(vector)


def test_exact_per_record_qa_vector_passes_and_binds_all_metrics(tmp_path: Path):
    result = _validate(_fixture(tmp_path))
    assert result["status"] == "pass"
    assert result["labels"] == ["left_forearm"]
    assert result["registry_file_sha256"] == "1" * 64


def test_unqualified_registry_cannot_authorize_vector(tmp_path: Path):
    fixture = list(_fixture(tmp_path))
    fixture[3]["authority_eligible"] = False
    with pytest.raises(PerRecordQaError, match="not qualified"):
        _validate(fixture)


def test_missing_or_not_applicable_mandatory_metric_fails(tmp_path: Path):
    fixture = list(_fixture(tmp_path))
    vector = fixture[4]
    vector["labels"][0]["metrics"] = vector["labels"][0]["metrics"][:-1]
    _reseal(vector)
    with pytest.raises(PerRecordQaError, match="schema is invalid"):
        _validate(fixture)
    fixture = list(_fixture(tmp_path / "na"))
    vector = fixture[4]
    next(row for row in vector["labels"][0]["metrics"] if row["metric"] == "cross_person_bleed")[
        "status"
    ] = "not_applicable"
    _reseal(vector)
    with pytest.raises(PerRecordQaError, match="mandatory metrics"):
        _validate(fixture)


@pytest.mark.parametrize("kind", ["mask", "target", "threshold", "mask_set", "identity"])
def test_exact_binding_drift_fails_closed(tmp_path: Path, kind: str):
    fixture = list(_fixture(tmp_path))
    vector = fixture[4]
    if kind == "mask":
        vector["labels"][0]["mask_encoded_sha256"] = H
    elif kind == "target":
        vector["labels"][0]["target_contract_sha256"] = H
    elif kind == "threshold":
        vector["labels"][0]["threshold_resolution_sha256"] = H
    elif kind == "mask_set":
        vector["final_mask_set_sha256"] = H
    else:
        vector["character_instance_id"] = "wrong-owner"
    _reseal(vector)
    with pytest.raises(PerRecordQaError):
        _validate(fixture)


def test_vector_content_tamper_without_reseal_fails(tmp_path: Path):
    fixture = list(_fixture(tmp_path))
    fixture[4]["labels"][0]["metrics"][0]["value"] = False
    with pytest.raises(PerRecordQaError, match="hash mismatch"):
        _validate(fixture)
