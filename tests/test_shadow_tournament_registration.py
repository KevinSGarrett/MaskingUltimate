from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from maskfactory.providers.shadow_registration import (
    AUTHORITY,
    EXPECTED_SHADOW_CHALLENGERS,
    MODERNIZATION_CHALLENGERS,
    SAM31_SHADOW_ROLES,
    ShadowRegistrationError,
    expected_shadow_challengers,
    run_host_side_shadow_tournaments,
    validate_host_side_shadow_evidence,
    verify_shadow_challenger_roster,
)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (
    ROOT / "qa" / "live_verification" / "host_side_shadow_tournament_registration_20260719.json"
)


def test_frozen_roster_covers_every_modernization_challenger() -> None:
    roster = expected_shadow_challengers()
    assert set(roster) == set(EXPECTED_SHADOW_CHALLENGERS)
    registered = {key for keys in roster.values() for key in keys}
    assert MODERNIZATION_CHALLENGERS <= registered
    assert "sam3_1" in roster["concept_detector"]
    assert "sam3_1" in roster["interactive_segmenter"]
    assert "rf_detr_medium" in roster["person_detector"]
    assert {"rtmw_x", "rtmo_crowd"} <= set(roster["pose_provider"])
    assert "sam3d_body" in roster["geometry_provider"]
    assert {
        "birefnet_dynamic",
        "birefnet_hr",
        "birefnet_hr_matting",
    } <= set(roster["silhouette_provider"])
    assert {"qwen3_vl_4b", "qwen3_vl_8b_quantized"} <= set(roster["vlm_reviewer"])
    assert "eomt_dinov3" in roster["custom_segmenter"]


def test_live_pipeline_roster_matches_frozen_registration() -> None:
    result = verify_shadow_challenger_roster()
    assert result["result"] == "pass_roster_matches_pipeline"
    assert result["authority"] == AUTHORITY
    assert result["sam31_shadow_roles"] == sorted(SAM31_SHADOW_ROLES)
    assert result["challenger_lifecycle"]["sam3_1"] == "planned"
    for role, challengers in EXPECTED_SHADOW_CHALLENGERS.items():
        assert tuple(result["observed_challengers"][role]) == challengers
        active = result["active_providers"].get(role)
        assert active not in challengers


def test_host_side_shadow_tournaments_run_installed_and_skip_planned() -> None:
    document = run_host_side_shadow_tournaments()
    validate_host_side_shadow_evidence(document)
    assert document["result"] == "pass_host_side_shadow_tournaments_no_live_gpu"
    assert document["wsl_gpu_smoke_claimed"] is False
    assert document["promotion_claimed"] is False
    assert document["completion_credit"] is False

    assert document["planned_skips_by_role"]["concept_detector"]["sam3_1"] == (
        "lifecycle_state=planned"
    )
    assert document["planned_skips_by_role"]["interactive_segmenter"]["sam3_1"] == (
        "lifecycle_state=planned"
    )
    assert document["planned_skips_by_role"]["geometry_provider"]["sam3d_body"] == (
        "lifecycle_state=planned"
    )
    assert document["planned_skips_by_role"]["person_detector"]["yolo26_person"] == (
        "lifecycle_state=planned"
    )

    assert document["runnable_by_role"]["person_detector"] == ["rf_detr_medium"]
    assert document["runnable_by_role"]["pose_provider"] == ["rtmw_x", "rtmo_crowd"]
    assert document["runnable_by_role"]["silhouette_provider"] == [
        "birefnet_dynamic",
        "birefnet_hr",
        "birefnet_hr_matting",
    ]
    assert document["runnable_by_role"]["vlm_reviewer"] == [
        "qwen2_5_vl_7b",
        "qwen3_vl_4b",
        "qwen3_vl_8b_quantized",
    ]
    assert document["runnable_by_role"]["custom_segmenter"] == ["eomt_dinov3"]
    assert "sam3_1" not in {row["provider_key"] for row in document["executed_calls"]}
    assert document["challenger_audit"]["rf_detr_medium"]["shadow_runnable"] is True
    assert document["challenger_audit"]["sam3_1"]["shadow_runnable"] is False
    assert document["sam31_shadow_wiring"]["live_wsl_gpu_smoke"] == (
        "needs_kevin_ubuntu_ext4_repair"
    )


def test_host_side_evidence_rejects_hash_and_authority_drift() -> None:
    document = run_host_side_shadow_tournaments()
    tampered = copy.deepcopy(document)
    tampered["authority"] = "promotion"
    with pytest.raises(ShadowRegistrationError, match="hash_mismatch"):
        validate_host_side_shadow_evidence(tampered)

    overclaim = copy.deepcopy(document)
    overclaim["wsl_gpu_smoke_claimed"] = True
    payload = {key: value for key, value in overclaim.items() if key != "sha256"}
    import hashlib

    overclaim["sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with pytest.raises(ShadowRegistrationError, match="overclaims_wsl_gpu"):
        validate_host_side_shadow_evidence(overclaim)


def test_roster_rejects_challenger_removed_from_pipeline(tmp_path: Path) -> None:
    pipeline = yaml.safe_load((ROOT / "configs/pipeline.yaml").read_text(encoding="utf-8"))
    pipeline["provider_roles"]["person_detector"]["challengers"] = ["yolo26_person"]
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(pipeline), encoding="utf-8")
    with pytest.raises(ShadowRegistrationError, match="shadow_roster_mismatch"):
        verify_shadow_challenger_roster(pipeline_path=path)


def test_sealed_live_verification_evidence_is_hash_bound() -> None:
    assert EVIDENCE.is_file(), f"missing sealed evidence: {EVIDENCE}"
    document = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    validate_host_side_shadow_evidence(document)
    fresh = run_host_side_shadow_tournaments()
    assert document["sha256"] == fresh["sha256"]
    assert document["role_manifest_sha256"] == fresh["role_manifest_sha256"]
    assert set(document["challenger_audit"]) == MODERNIZATION_CHALLENGERS
