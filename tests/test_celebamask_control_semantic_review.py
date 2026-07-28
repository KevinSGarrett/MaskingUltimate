from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.vlm.canonical_polygon_source_candidates import sha256_file
from maskfactory.vlm.celebamask_control_candidates import (
    SCHEMA_VERSION as CANDIDATE_SCHEMA,
)
from maskfactory.vlm.celebamask_control_panels import (
    materialize_celebamask_control_panels,
)
from maskfactory.vlm.celebamask_control_semantic_review import (
    CelebAMaskControlSemanticReviewError,
    build_celebamask_control_semantic_review,
    verify_celebamask_control_semantic_review,
)
from maskfactory.vlm.critic_catalog import canonical_sha256


def _panel_report(tmp_path: Path) -> tuple[dict, Path]:
    source_root = tmp_path / "source"
    source_path = source_root / "CelebA-HQ-img" / "1.jpg"
    mask_path = source_root / "CelebAMask-HQ-mask-anno" / "0" / "00001_hair.png"
    source_path.parent.mkdir(parents=True)
    mask_path.parent.mkdir(parents=True)
    Image.fromarray(np.full((32, 32, 3), 90, dtype=np.uint8)).save(source_path)
    mask = np.zeros((16, 16), dtype=np.uint8)
    mask[2:10, 4:12] = 255
    Image.fromarray(mask).save(mask_path)
    record = {
        "sample_id": "celebamask_00001_hair",
        "source_image_id": "celebamask_00001",
        "canonical_label": "hair",
        "raw_label": "hair",
        "assigned_partition": "qualification_test",
        "source_relative_path": "CelebA-HQ-img/1.jpg",
        "source_sha256": sha256_file(source_path),
        "source_dimensions": [32, 32],
        "mask_relative_path": "CelebAMask-HQ-mask-anno/0/00001_hair.png",
        "mask_sha256": sha256_file(mask_path),
        "mask_dimensions": [16, 16],
        "mask_pixel_count": 64,
        "mask_values": [0, 255],
        "alignment_policy": "resize_source_to_mask_bilinear",
        "external_reference_qualification_complete": False,
        "visual_alignment_reviewed": False,
        "critic_control_eligible": False,
        "gold_or_production_authority": False,
    }
    candidates = {
        "schema_version": CANDIDATE_SCHEMA,
        "selected_count": 1,
        "selected": [record],
        "authority_claimed": False,
        "critic_control_authority_granted": False,
        "gold_or_production_authority_granted": False,
    }
    candidates["self_sha256"] = canonical_sha256(candidates)
    output_root = tmp_path / "panels"
    report = materialize_celebamask_control_panels(
        source_root=source_root,
        candidate_document=candidates,
        output_root=output_root,
    )
    return report, output_root


def _decision(**overrides: object) -> dict:
    value = {
        "sample_id": "celebamask_00001_hair",
        "verdict": "pass",
        "reason_code": "exact_visible_target_alignment",
        "evidence_panels": ["target_zoom"],
        "review_note": "The visible target boundary is aligned.",
    }
    value.update(overrides)
    return value


def test_pass_remains_alignment_candidate_without_control_authority(
    tmp_path: Path,
) -> None:
    report, root = _panel_report(tmp_path)
    result = build_celebamask_control_semantic_review(
        panel_report=report,
        panel_root=root,
        decisions=[_decision()],
    )
    verify_celebamask_control_semantic_review(result, report)
    assert result["verdict_counts"] == {"pass": 1}
    assert result["visual_alignment_pass_candidates_by_label"] == {"hair": 1}
    assert result["records"][0]["visual_alignment_pass_candidate"] is True
    assert result["records"][0]["critic_control_eligible"] is False


@pytest.mark.parametrize(
    "decision,error",
    [
        (_decision(verdict="pass", reason_code="material_underfill"), "pass reason"),
        (
            _decision(verdict="abstain", reason_code="protected_region_leakage"),
            "abstention reason",
        ),
        (
            _decision(verdict="reject", reason_code="exact_visible_target_alignment"),
            "reject reason",
        ),
        (_decision(evidence_panels=["missing"]), "evidence panels"),
    ],
)
def test_invalid_closed_verdicts_fail(tmp_path: Path, decision: dict, error: str) -> None:
    report, root = _panel_report(tmp_path)
    with pytest.raises(CelebAMaskControlSemanticReviewError, match=error):
        build_celebamask_control_semantic_review(
            panel_report=report,
            panel_root=root,
            decisions=[decision],
        )


def test_authority_upgrade_fails_verification(tmp_path: Path) -> None:
    report, root = _panel_report(tmp_path)
    result = build_celebamask_control_semantic_review(
        panel_report=report,
        panel_root=root,
        decisions=[_decision()],
    )
    changed = copy.deepcopy(result)
    changed["records"][0]["critic_control_eligible"] = True
    changed["self_sha256"] = canonical_sha256(
        {key: value for key, value in changed.items() if key != "self_sha256"}
    )
    with pytest.raises(CelebAMaskControlSemanticReviewError, match="authority"):
        verify_celebamask_control_semantic_review(changed, report)
