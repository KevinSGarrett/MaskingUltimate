from __future__ import annotations

from copy import deepcopy

import pytest

from maskfactory.vlm import canonical_polygon_calibration_admission as admission
from maskfactory.vlm.canonical_polygon_panels import PANEL_NAMES
from maskfactory.vlm.critic_catalog import canonical_sha256


def _inputs() -> tuple[dict, dict]:
    candidates = {
        "self_sha256": "a" * 64,
        "selected": [
            {
                "sample_id": "case_train",
                "dataset_id": "roboflow_mange_v3",
                "lineage_group": "mange",
                "assigned_partition": "train",
                "raw_label": "female face",
                "canonical_label": "head_face",
                "candidate_kind": "coarse_anatomy",
                "source_sha256": "b" * 64,
                "mask_sha256": "c" * 64,
                "external_reference_qualification_complete": False,
                "critic_positive_control_eligible": False,
                "gold_or_production_authority": False,
            },
            {
                "sample_id": "case_test",
                "dataset_id": "roboflow_mange_v3",
                "lineage_group": "mange",
                "assigned_partition": "test",
                "raw_label": "male face",
                "canonical_label": "head_face",
                "candidate_kind": "coarse_anatomy",
                "source_sha256": "d" * 64,
                "mask_sha256": "e" * 64,
                "external_reference_qualification_complete": False,
                "critic_positive_control_eligible": False,
                "gold_or_production_authority": False,
            },
        ],
    }
    panel_records = []
    for index, candidate in enumerate(candidates["selected"]):
        hashes = {name: f"{index + 1:064x}" for name in PANEL_NAMES}
        panel_records.append(
            {
                "sample_id": candidate["sample_id"],
                "panel_set_sha256": canonical_sha256(hashes),
                "panel_sha256s": hashes,
                "visual_alignment_reviewed": False,
                "critic_positive_control_eligible": False,
                "gold_or_production_authority": False,
            }
        )
    panels = {
        "self_sha256": "f" * 64,
        "candidate_set_sha256": candidates["self_sha256"],
        "records": panel_records,
    }
    return candidates, panels


def _decisions() -> list[dict]:
    return [
        {
            "sample_id": "case_train",
            "screening_verdict": "admitted_calibration_only",
            "reason_code": "visible_target_localized_bounded_control",
            "evidence_panels": ["source", "overlay", "contour", "target_zoom"],
            "review_note": "The target face is visibly localized with a coherent boundary.",
        },
        {
            "sample_id": "case_test",
            "screening_verdict": "abstained",
            "reason_code": "ambiguous_target_scope",
            "evidence_panels": ["source", "overlay", "full_context"],
            "review_note": "The target scope is ambiguous in the scene.",
        },
    ]


def _bypass_upstream_verifiers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admission, "verify_canonical_polygon_source_candidates", lambda *_: None)
    monkeypatch.setattr(admission, "verify_candidate_panel_report", lambda *_: None)


def test_builds_complete_calibration_only_receipt(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _bypass_upstream_verifiers(monkeypatch)
    candidates, panels = _inputs()
    document = admission.build_canonical_polygon_calibration_admission(
        candidates=candidates,
        panel_report=panels,
        panel_root=tmp_path,
        decisions=_decisions(),
    )
    admission.verify_canonical_polygon_calibration_admission(
        document, candidates, panels, tmp_path
    )
    assert document["admitted_calibration_only_count"] == 1
    assert document["abstained_count"] == 1
    assert document["rejected_count"] == 0
    assert document["authority"]["critic_role_authority_granted"] is False


def test_rejects_incomplete_or_invalid_decisions(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _bypass_upstream_verifiers(monkeypatch)
    candidates, panels = _inputs()
    with pytest.raises(admission.CanonicalPolygonCalibrationAdmissionError, match="every candidate"):
        admission.build_canonical_polygon_calibration_admission(
            candidates=candidates,
            panel_report=panels,
            panel_root=tmp_path,
            decisions=_decisions()[:1],
        )
    decisions = _decisions()
    decisions[0]["evidence_panels"] = ["not_a_panel"]
    with pytest.raises(admission.CanonicalPolygonCalibrationAdmissionError, match="invalid exact-record"):
        admission.build_canonical_polygon_calibration_admission(
            candidates=candidates,
            panel_report=panels,
            panel_root=tmp_path,
            decisions=decisions,
        )


def test_authority_mutation_breaks_receipt(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _bypass_upstream_verifiers(monkeypatch)
    candidates, panels = _inputs()
    document = admission.build_canonical_polygon_calibration_admission(
        candidates=candidates,
        panel_report=panels,
        panel_root=tmp_path,
        decisions=_decisions(),
    )
    drifted = deepcopy(document)
    drifted["authority"]["gold_or_training_truth_granted"] = True
    drifted["self_sha256"] = canonical_sha256(
        {key: value for key, value in drifted.items() if key != "self_sha256"}
    )
    with pytest.raises(admission.CanonicalPolygonCalibrationAdmissionError, match="authority"):
        admission.verify_canonical_polygon_calibration_admission(
            drifted, candidates, panels, tmp_path
        )
