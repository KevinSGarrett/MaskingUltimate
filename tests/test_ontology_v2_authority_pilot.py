from __future__ import annotations

import copy

import pytest

from maskfactory.ontology_v2_authority_pilot import (
    AUTHORITY,
    SCHEMA_VERSION,
    OntologyV2AuthorityPilotError,
    canonical_sha256,
    verify_authority_pilot,
)
from maskfactory.ontology_v2_inactive_gates import REQUIRED_PILOT_STATES, appended_v2_part_names


def _manifest(tmp_path):
    images = []
    labels = appended_v2_part_names()
    for index in range(24):
        path = tmp_path / f"image-{index}.jpg"
        path.write_bytes(f"image-{index}".encode())
        targets = []
        for ordinal, state in enumerate(REQUIRED_PILOT_STATES):
            label = labels[(index + ordinal) % len(labels)]
            targets.append(
                {
                    "canonical_label": label,
                    "requested_state": state,
                    "current_state": "unreviewed_for_v2",
                    "state_evidence_basis": "qualified_autonomous_visual_resolution_pending",
                    "semantic_positive_authority": False,
                    "qualified_visual_resolution_required": True,
                }
            )
        images.append(
            {
                "image_id": f"pilot_{index:024d}",
                "source_kind": (
                    "maskedwarehouse_external_candidate"
                    if index < 20
                    else "reference_library_coverage"
                ),
                "source_path": path.as_posix(),
                "source_encoded_sha256": __import__("hashlib")
                .sha256(path.read_bytes())
                .hexdigest(),
                "split_group_id": f"group-{index}",
                "mask_truth_authority": False,
                "coverage_targets": targets,
            }
        )
    # Ensure the global class vocabulary is exact even though each row is bounded.
    for index, label in enumerate(labels):
        images[index]["coverage_targets"].append(
            {
                "canonical_label": label,
                "requested_state": "visible",
                "current_state": "unreviewed_for_v2",
                "state_evidence_basis": "qualified_autonomous_visual_resolution_pending",
                "semantic_positive_authority": False,
                "qualified_visual_resolution_required": True,
            }
        )
    document = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "ontology_v2_real_image_authority_pilot",
        "authority": AUTHORITY,
        "ontology_version": "body_parts_v2",
        "ontology_sha256": "a" * 64,
        "active_runtime_ontology": "body_parts_v1",
        "production_activation_performed": False,
        "mandatory_human_anchor": False,
        "pilot_complete": False,
        "selection_status": "real_source_selection_complete_authority_resolution_open",
        "source_lineage": {},
        "image_count": 24,
        "maskedwarehouse_image_count": 20,
        "reference_image_count": 4,
        "coverage_target_count": sum(len(row["coverage_targets"]) for row in images),
        "requested_states": sorted(REQUIRED_PILOT_STATES),
        "requested_appended_classes": sorted(labels),
        "resolved_states": [],
        "missing_resolved_states": sorted(REQUIRED_PILOT_STATES),
        "semantic_positive_count": 0,
        "images": images,
        "claim_limits": [],
    }
    document["self_sha256"] = canonical_sha256(document)
    return document


def test_real_pilot_verifier_accepts_selection_without_promoting_authority(tmp_path) -> None:
    document = _manifest(tmp_path)
    result = verify_authority_pilot(document, rehash_sources=True)
    assert result["status"] == "PASS_SELECTION_AUTHORITY_RESOLUTION_OPEN"
    assert result["pilot_complete"] is False
    assert result["requested_state_count"] == 9
    assert result["requested_class_count"] == 10


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(pilot_complete=True), "authority_boundary"),
        (
            lambda value: value["images"][0].update(mask_truth_authority=True),
            "mask_truth",
        ),
        (
            lambda value: value["images"][0]["coverage_targets"][0].update(
                semantic_positive_authority=True
            ),
            "promoted",
        ),
        (
            lambda value: value["images"][1].update(
                source_encoded_sha256=value["images"][0]["source_encoded_sha256"]
            ),
            "distinct",
        ),
    ],
)
def test_real_pilot_verifier_fails_closed(tmp_path, mutate, message: str) -> None:
    document = copy.deepcopy(_manifest(tmp_path))
    mutate(document)
    document["self_sha256"] = canonical_sha256(document)
    with pytest.raises(OntologyV2AuthorityPilotError, match=message):
        verify_authority_pilot(document)
