from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.vlm.canonical_polygon_panels import (
    PANEL_NAMES,
    render_candidate_panels,
)
from maskfactory.vlm.canonical_polygon_semantic_review import (
    CanonicalPolygonSemanticReviewError,
    build_semantic_review,
    verify_semantic_review,
)
from maskfactory.vlm.canonical_polygon_source_candidates import sha256_file
from maskfactory.vlm.critic_catalog import canonical_sha256


def _panel_report(tmp_path: Path) -> dict:
    sample_id = "sample_001"
    source = np.zeros((32, 48, 3), dtype=np.uint8)
    mask = np.zeros((32, 48), dtype=bool)
    mask[4:12, 5:17] = True
    panels = render_candidate_panels(source, mask, tmp_path / sample_id)
    contact_path = tmp_path / "contact_sheet.png"
    Image.new("RGB", (64, 64)).save(contact_path, format="PNG")
    report = {
        "schema_version": "maskfactory.canonical_polygon_candidate_panels.v1",
        "authority_claimed": False,
        "visual_alignment_qualification_complete": False,
        "critic_positive_control_authority_granted": False,
        "record_count": 1,
        "panel_count": len(PANEL_NAMES),
        "records": [
            {
                "sample_id": sample_id,
                "canonical_label": "anus",
                "dataset_id": "dataset",
                "assigned_partition": "test",
                **panels,
                "visual_alignment_reviewed": False,
                "critic_positive_control_eligible": False,
                "gold_or_production_authority": False,
            }
        ],
        "contact_sheet": {
            "path": "contact_sheet.png",
            "sha256": sha256_file(contact_path),
            "scheduling_and_navigation_aid_only": True,
            "per_record_evidence_required": True,
        },
    }
    report["self_sha256"] = canonical_sha256(report)
    return report


def _decision(**overrides: object) -> dict:
    value = {
        "sample_id": "sample_001",
        "verdict": "reject",
        "reason_code": "wrong_target_or_label",
        "evidence_panels": ["target_zoom", "full_context"],
        "review_note": "The exact record shows a different target.",
    }
    value.update(overrides)
    return value


def test_builds_complete_review_without_control_or_gold_authority(
    tmp_path: Path,
) -> None:
    report = _panel_report(tmp_path)
    result = build_semantic_review(
        panel_report=report,
        panel_root=tmp_path,
        decisions=[_decision()],
    )
    verify_semantic_review(result, report)
    assert result["verdict_counts"] == {"reject": 1}
    assert result["positive_control_count"] == 0
    assert result["critic_control_authority_granted"] is False
    assert result["records"][0]["critic_negative_control_eligible"] is False


@pytest.mark.parametrize(
    "decisions,error",
    [
        ([], "every exact record"),
        ([_decision(sample_id="unknown")], "unknown or duplicate"),
        (
            [_decision(verdict="reject", reason_code="ambiguous_target_scope")],
            "ambiguity must abstain",
        ),
        (
            [_decision(evidence_panels=["missing"])],
            "review evidence panels are invalid",
        ),
    ],
)
def test_incomplete_or_invalid_reviews_fail_closed(
    tmp_path: Path, decisions: list[dict], error: str
) -> None:
    with pytest.raises(CanonicalPolygonSemanticReviewError, match=error):
        build_semantic_review(
            panel_report=_panel_report(tmp_path),
            panel_root=tmp_path,
            decisions=decisions,
        )


def test_verifier_rejects_authority_upgrade(tmp_path: Path) -> None:
    report = _panel_report(tmp_path)
    result = build_semantic_review(
        panel_report=report,
        panel_root=tmp_path,
        decisions=[_decision()],
    )
    changed = copy.deepcopy(result)
    changed["records"][0]["critic_negative_control_eligible"] = True
    changed["self_sha256"] = canonical_sha256(
        {key: value for key, value in changed.items() if key != "self_sha256"}
    )
    with pytest.raises(CanonicalPolygonSemanticReviewError, match="authority"):
        verify_semantic_review(changed, report)
