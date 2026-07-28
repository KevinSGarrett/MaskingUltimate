from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from maskfactory.ontology_v2_inactive_gates import (
    INACTIVE_STATUS,
    PILOT_IMAGE_MIN,
    REQUIRED_PILOT_STATES,
    OntologyV2InactiveGateError,
    appended_v2_part_names,
    build_cvat_v2_pilot_matrix_contract,
    build_inactive_path_static_report,
    evaluate_cvat_v2_pilot_readiness,
    fixture_pilot_probe_manifest,
    refuse_apply_when_activation_requested,
    refuse_migration_production_claims,
    require_inactive_v2_authority,
)
from maskfactory.ontology_v2_manifest import OntologyV2ManifestError, migrate_v1_manifest_file


def test_inactive_authority_refuses_production_activation_claims() -> None:
    ok = require_inactive_v2_authority(
        {
            "activation_status": INACTIVE_STATUS,
            "ontology_version": "body_parts_v2",
            "active_runtime_ontology": "body_parts_v1",
            "production_activation_performed": False,
        }
    )
    assert ok["production_activation_performed"] is False
    with pytest.raises(OntologyV2InactiveGateError, match="production_activation_performed"):
        require_inactive_v2_authority(
            {
                "activation_status": INACTIVE_STATUS,
                "production_activation_performed": True,
            }
        )
    with pytest.raises(OntologyV2InactiveGateError, match="approved_design_not_active"):
        require_inactive_v2_authority({"activation_status": "active"})


def test_migration_refusal_blocks_gold_and_activation_claims() -> None:
    refuse_migration_production_claims(
        {
            "mask_ontology_version": "body_parts_v2",
            "workflow_status": "in_review",
            "ontology_migration": {"status": "awaiting_v2_authority_resolution"},
            "production_activation_performed": False,
        }
    )
    with pytest.raises(OntologyV2InactiveGateError, match="gold/exported/active"):
        refuse_migration_production_claims(
            {
                "mask_ontology_version": "body_parts_v2",
                "workflow_status": "approved_gold",
            }
        )
    with pytest.raises(OntologyV2InactiveGateError, match="activate_v2"):
        refuse_apply_when_activation_requested(dry_run=True, extras={"activate_v2": True})


def test_migrate_apply_refuses_activation_extras(tmp_path: Path) -> None:
    manifest = {
        "schema_version": "1.0.0",
        "mask_ontology_version": "body_parts_v1",
        "image_id": "img_inactive_gate_probe",
        "instance_id": "p0",
        "files": {"source.png": "abc"},
        "parts": {},
        "workflow_status": "draft",
    }
    # Minimal enabled v1 parts for migration are heavy; exercise extras gate only.
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    with pytest.raises(OntologyV2ManifestError, match="activate_v2"):
        migrate_v1_manifest_file(
            path,
            report_path=tmp_path / "report.json",
            dry_run=True,
            extras={"activate_v2": True},
        )


def test_pilot_matrix_contract_is_deterministic_and_inactive() -> None:
    first = build_cvat_v2_pilot_matrix_contract()
    second = build_cvat_v2_pilot_matrix_contract()
    assert first == second
    assert first["activation_status"] == INACTIVE_STATUS
    assert first["pilot_complete"] is False
    assert first["governed_real_sources_required"] is True
    assert first["mandatory_human_anchor"] is False
    assert first["maskedwarehouse_root"] == "C:/Comfy_UI_Main/MaskedWarehouse"
    assert (
        first["reference_library_root"] == "F:/Reference_Images/Ultimate_Masking_Reference_Images"
    )
    assert first["image_count_min"] == PILOT_IMAGE_MIN
    assert set(first["required_states"]) == set(REQUIRED_PILOT_STATES)
    assert first["required_appended_classes"] == list(appended_v2_part_names())
    assert len(first["required_appended_classes"]) == 10


def test_fixture_pilot_probe_covers_matrix_but_never_completes() -> None:
    manifest = fixture_pilot_probe_manifest()
    report = evaluate_cvat_v2_pilot_readiness(manifest)
    assert report["matrix_structurally_ready"] is True
    assert report["image_count_in_range"] is True
    assert report["distinct_image_count"] == 24
    assert report["missing_states"] == []
    assert report["missing_appended_classes"] == []
    assert report["fixture_probe_row_count"] == 24
    assert report["maskedwarehouse_authority_row_count"] == 0
    assert report["reference_library_coverage_row_count"] == 0
    assert report["pilot_complete"] is False
    assert report["completion_eligible"] is False
    assert report["remaining_blocker"] == (
        "exact hash-bound real-source authority and coverage pilot not yet complete"
    )


def test_pilot_gate_refuses_completion_and_mandatory_human_anchor_claims() -> None:
    manifest = fixture_pilot_probe_manifest()
    bad_complete = copy.deepcopy(manifest)
    bad_complete["pilot_complete"] = True
    with pytest.raises(OntologyV2InactiveGateError, match="pilot_complete"):
        evaluate_cvat_v2_pilot_readiness(bad_complete)

    bad_auth = copy.deepcopy(manifest)
    bad_auth["mandatory_human_anchor"] = True
    with pytest.raises(OntologyV2InactiveGateError, match="mandatory_human_anchor"):
        evaluate_cvat_v2_pilot_readiness(bad_auth)

    bad_alias = copy.deepcopy(manifest)
    bad_alias["images"][0]["alias_exported_as_canonical"] = True
    with pytest.raises(OntologyV2InactiveGateError, match="alias_exported_as_canonical"):
        evaluate_cvat_v2_pilot_readiness(bad_alias)

    duplicate = copy.deepcopy(manifest)
    duplicate["images"][1]["image_id"] = duplicate["images"][0]["image_id"]
    with pytest.raises(OntologyV2InactiveGateError, match="duplicate pilot image_id"):
        evaluate_cvat_v2_pilot_readiness(duplicate)


def test_inactive_path_static_report_never_claims_activation() -> None:
    report = build_inactive_path_static_report(pilot_manifest=fixture_pilot_probe_manifest())
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["production_activation_performed"] is False
    assert report["production_activation_claimed"] is False
    assert report["pilot_readiness"]["pilot_complete"] is False
    assert "body_parts_v2 production activation" in report["honest_non_claims"]
    assert "MF-P1-12.09" in report["items"]
