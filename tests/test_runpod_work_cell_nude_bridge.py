from __future__ import annotations

import json
from pathlib import Path

import pytest

from maskfactory.autonomy.work_cell_nude_bridge import (
    NudeWorkCellBridgeError,
    build_work_cell_artifacts_from_nude_qualified_record,
)
from maskfactory.autonomy.work_cell_receipts import receipt_from_stage_artifact
from maskfactory.nude_record_qualification import (
    qualify_terminal_record,
    verify_complete_panel_evidence,
)
from test_nude_record_qualification import _panels, _record

HEX = "a" * 64


def _qualified(tmp_path: Path) -> dict:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    return qualify_terminal_record(_record(bundle["panel_bundle_sha256"]), panels=panels)


def test_qualified_nude_record_builds_work_cell_artifacts_without_faking_certificate(
    tmp_path: Path,
) -> None:
    payload = _qualified(tmp_path)
    artifacts = build_work_cell_artifacts_from_nude_qualified_record(
        payload,
        target_contract_sha256=HEX,
    )
    assert set(artifacts) == {
        "source_decode",
        "detection_ownership",
        "provider_tournament",
        "hard_qc",
        "primary_visual_review",
        "independent_visual_review",
    }
    assert artifacts["source_decode"]["decoded_pixel_sha256"]
    assert artifacts["detection_ownership"]["ownership_status"] == "verified"
    assert artifacts["provider_tournament"]["family_count"] == 2
    assert artifacts["hard_qc"]["hard_veto_count"] == 0
    assert artifacts["primary_visual_review"]["verdict"] == "pass"
    assert "package_freeze" not in artifacts
    assert "certification" not in artifacts

    for stage, artifact in artifacts.items():
        receipt = receipt_from_stage_artifact(
            stage=stage,
            status=artifact["work_cell_status"],
            artifact=artifact,
            evidence_sha256=HEX,
        )
        assert receipt["stage"] == stage
        assert receipt["status"] == "pass"


def test_qualified_nude_record_adds_package_and_certificate_only_when_exact_hashes_exist(
    tmp_path: Path,
) -> None:
    artifacts = build_work_cell_artifacts_from_nude_qualified_record(
        _qualified(tmp_path),
        target_contract_sha256=HEX,
        package_sha256="b" * 64,
        certificate_sha256="c" * 64,
        authority_tier="operationally_certified_artifact",
    )
    assert artifacts["package_freeze"]["package_sha256"] == "b" * 64
    assert artifacts["certification"]["certificate_sha256"] == "c" * 64
    assert artifacts["certification"]["authority_tier"] == "operationally_certified_artifact"


def test_qualified_nude_record_rejects_partial_certificate_claim(tmp_path: Path) -> None:
    with pytest.raises(NudeWorkCellBridgeError, match="certificate_hash_and_authority"):
        build_work_cell_artifacts_from_nude_qualified_record(
            _qualified(tmp_path),
            target_contract_sha256=HEX,
            certificate_sha256="c" * 64,
        )


def test_qualified_nude_record_bridge_revalidates_payload_before_conversion(
    tmp_path: Path,
) -> None:
    payload = _qualified(tmp_path)
    tampered = json.loads(json.dumps(payload))
    tampered["qualification_evidence"]["production_mask_authority"] = True
    with pytest.raises(Exception, match="qualification_evidence_hash_mismatch"):
        build_work_cell_artifacts_from_nude_qualified_record(
            tampered,
            target_contract_sha256=HEX,
        )
