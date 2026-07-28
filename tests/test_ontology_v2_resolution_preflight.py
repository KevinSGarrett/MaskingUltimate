from __future__ import annotations

import copy
import hashlib

import numpy as np
import pytest
from PIL import Image

from maskfactory.authority.operational_certificate import canonical_decoded_raster_sha256
from maskfactory.ontology_v2_authority_pilot import canonical_sha256
from maskfactory.ontology_v2_inactive_gates import REQUIRED_PILOT_STATES, appended_v2_part_names
from maskfactory.ontology_v2_resolution_preflight import (
    STATUS,
    OntologyV2ResolutionPreflightError,
    build_resolution_preflight,
    verify_resolution_preflight,
)
from maskfactory.ontology_v2_resolution_workload import build_resolution_workload


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pilot(tmp_path):
    labels = appended_v2_part_names()
    combinations = [(label, state) for state in REQUIRED_PILOT_STATES for label in labels]
    images = []
    for index in range(24):
        path = tmp_path / f"pilot-{index:02d}.png"
        pixels = np.full((4, 5, 3), index, dtype=np.uint8)
        Image.fromarray(pixels, mode="RGB").save(path)
        targets = []
        for label, state in combinations[index::24]:
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
                "runpod_path": path.as_posix(),
                "source_encoded_sha256": _sha256(path),
                "source_decoded_pixel_sha256": canonical_decoded_raster_sha256(
                    pixels, channel_layout="RGB"
                ),
                "width": 5,
                "height": 4,
                "split_group_id": f"group-{index}",
                "mask_truth_authority": False,
                "coverage_targets": targets,
            }
        )
    pilot = {
        "schema_version": "maskfactory.ontology_v2_authority_pilot.v2",
        "artifact_type": "ontology_v2_real_image_authority_pilot",
        "authority": "real_image_pilot_selection_no_mask_truth_or_gold_authority",
        "ontology_version": "body_parts_v2",
        "ontology_sha256": "a" * 64,
        "active_runtime_ontology": "body_parts_v1",
        "production_activation_performed": False,
        "mandatory_human_anchor": False,
        "pilot_complete": False,
        "selection_status": "real_source_selection_complete_authority_resolution_open",
        "source_lineage": {},
        "image_count": len(images),
        "maskedwarehouse_image_count": 20,
        "reference_image_count": 4,
        "coverage_target_count": len(combinations),
        "requested_states": sorted(REQUIRED_PILOT_STATES),
        "requested_appended_classes": sorted(labels),
        "resolved_states": [],
        "missing_resolved_states": sorted(REQUIRED_PILOT_STATES),
        "semantic_positive_count": 0,
        "images": images,
        "claim_limits": [],
    }
    pilot["self_sha256"] = canonical_sha256(pilot)
    return pilot


def test_preflight_binds_real_source_bytes_and_all_work_units(tmp_path) -> None:
    pilot = _pilot(tmp_path)
    workload = build_resolution_workload(pilot, pilot_manifest_file_sha256="b" * 64)

    receipt = build_resolution_preflight(
        pilot,
        workload,
        pilot_file_sha256="c" * 64,
        workload_file_sha256="d" * 64,
    )

    assert receipt["status"] == STATUS
    assert receipt["image_count"] == 24
    assert receipt["work_unit_count"] == 90
    assert receipt["semantic_resolution_performed"] is False
    assert receipt["visual_review_performed"] is False
    assert receipt["mask_or_gold_authority"] is False
    assert verify_resolution_preflight(receipt, pilot=pilot, workload=workload)["status"] == STATUS


def test_preflight_rejects_work_unit_runtime_path_drift(tmp_path) -> None:
    pilot = _pilot(tmp_path)
    workload = build_resolution_workload(pilot, pilot_manifest_file_sha256="b" * 64)
    changed = copy.deepcopy(workload)
    changed["entries"][0]["runpod_path"] = "/workspace/not-the-bound-source.png"
    changed["self_sha256"] = canonical_sha256(changed)

    with pytest.raises(OntologyV2ResolutionPreflightError, match="runtime_path_mismatch"):
        build_resolution_preflight(
            pilot,
            changed,
            pilot_file_sha256="c" * 64,
            workload_file_sha256="d" * 64,
        )


def test_preflight_rejects_encoded_source_drift(tmp_path) -> None:
    pilot = _pilot(tmp_path)
    workload = build_resolution_workload(pilot, pilot_manifest_file_sha256="b" * 64)
    source = tmp_path / "pilot-00.png"
    source.write_bytes(b"not-an-image")

    with pytest.raises(OntologyV2ResolutionPreflightError, match="encoded_sha_mismatch"):
        build_resolution_preflight(
            pilot,
            workload,
            pilot_file_sha256="c" * 64,
            workload_file_sha256="d" * 64,
        )


def test_preflight_rejects_resealed_target_row_tamper(tmp_path) -> None:
    pilot = _pilot(tmp_path)
    workload = build_resolution_workload(pilot, pilot_manifest_file_sha256="b" * 64)
    receipt = build_resolution_preflight(
        pilot,
        workload,
        pilot_file_sha256="c" * 64,
        workload_file_sha256="d" * 64,
    )
    receipt["coverage_target_rows"][0]["coverage_target_sha256"] = "e" * 64
    receipt["self_sha256"] = canonical_sha256(receipt)

    with pytest.raises(OntologyV2ResolutionPreflightError, match="target_rows_mismatch"):
        verify_resolution_preflight(receipt, pilot=pilot, workload=workload)
