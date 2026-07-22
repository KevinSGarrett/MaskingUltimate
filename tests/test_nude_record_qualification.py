from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from maskfactory.nude_person_ownership import resolve_person_instance_ownership
from maskfactory.nude_record_qualification import (
    NudeRecordQualificationError,
    qualify_input_terminal_record,
    qualify_nonacceptance_record,
    qualify_terminal_record,
    validate_input_terminal_queue_payload,
    validate_nonacceptance_queue_payload,
    validate_qualified_queue_payload,
    verify_complete_panel_evidence,
)
from maskfactory.providers.disagreement import binary_mask_sha256

_PANEL_CONTEXTS: dict[str, tuple[str, str, np.ndarray]] = {}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _ownership(mask: np.ndarray, source_sha256: str, *, ambiguous: bool = False) -> dict:
    boxes = (
        [(0, [8, 6, 40, 42]), (1, [10, 8, 38, 40])]
        if ambiguous
        else [(0, [8, 6, 40, 42]), (1, [0, 0, 8, 8])]
    )
    reports = [
        {
            "provider_id": provider,
            "family_id": family,
            "source_sha256": source_sha256,
            "report_sha256": _sha(provider),
            "persons": [
                {"person_index": index, "bbox_xyxy": box, "confidence": 0.9} for index, box in boxes
            ],
        }
        for provider, family in (("yolo11m", "yolo"), ("rf_detr_medium", "rfdetr"))
    ]
    return resolve_person_instance_ownership(
        mask,
        source_sha256=source_sha256,
        mask_sha256=binary_mask_sha256(mask),
        candidate_label="breast_region",
        detector_reports=reports,
    )


def _panels(tmp_path: Path) -> dict[str, dict[str, str]]:
    source = np.full((48, 48, 3), 40, dtype=np.uint8)
    source[12:36, 14:34] = [180, 130, 100]
    original = tmp_path / "original.png"
    Image.fromarray(source).save(original)
    source_sha = hashlib.sha256(original.read_bytes()).hexdigest()
    mask = np.zeros((48, 48), dtype=bool)
    mask[12:36, 14:34] = True
    mask_rgb = np.repeat((mask.astype(np.uint8) * 255)[..., None], 3, axis=2)
    overlay = source.copy()
    overlay[mask] = [120, 20, 20]
    contour = source.copy()
    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(contour, contours, -1, (255, 0, 0), 2)
    ownership_image = Image.fromarray(source.copy())
    ImageDraw.Draw(ownership_image).rectangle((14, 12, 34, 36), outline=(255, 0, 0), width=2)
    arrays = {
        "source": source,
        "mask": mask_rgb,
        "overlay": overlay,
        "contour": contour,
        "ownership": np.asarray(ownership_image),
    }
    result = {}
    for kind, array in arrays.items():
        path = tmp_path / f"{kind}.png"
        Image.fromarray(array).save(path)
        result[kind] = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    result["source"]["original_source_path"] = str(original)
    bundle = verify_complete_panel_evidence(result)
    _PANEL_CONTEXTS[bundle["panel_bundle_sha256"]] = (
        source_sha,
        binary_mask_sha256(mask),
        mask,
    )
    return result


def _record(panel_bundle_sha256: str, *, outcome: str = "accepted") -> dict[str, object]:
    source_sha256, selected, mask = _PANEL_CONTEXTS[panel_bundle_sha256]
    ownership = _ownership(mask, source_sha256)
    record: dict[str, object] = {
        "sample_id": "adult-sample-0001",
        "candidate_label": "breast_region",
        "source_sha256": source_sha256,
        "mask_sha256": selected,
        "ownership": ownership,
        "outcome": outcome,
        "provider_comparison": {
            "status": "pass",
            "selected_mask_sha256": selected,
            "report_sha256": _sha("comparison"),
            "candidates": [
                {
                    "provider_id": "sam31",
                    "family_id": "sam",
                    "revision": "rev-a",
                    "artifact_sha256": _sha("sam-artifact"),
                    "mask_sha256": selected,
                    "person_index": 0,
                },
                {
                    "provider_id": "birefnet",
                    "family_id": "birefnet",
                    "revision": "rev-b",
                    "artifact_sha256": _sha("birefnet-artifact"),
                    "mask_sha256": _sha("other-mask"),
                    "person_index": 0,
                },
            ],
        },
        "hard_qc": {
            "status": "pass",
            "mask_sha256": selected,
            "policy_sha256": _sha("hard-policy"),
            "report_sha256": _sha("hard-report"),
        },
        "strict_reviews": [
            {
                "role": "primary_visual_critic",
                "model_id": "internvl",
                "family_id": "internvl",
                "revision": "rev-i",
                "certificate_sha256": _sha("internvl-cert"),
                "prompt_sha256": _sha("prompt"),
                "mask_sha256": selected,
                "panel_bundle_sha256": panel_bundle_sha256,
                "person_index": 0,
                "ownership_report_sha256": ownership["report_sha256"],
                "verdict": "pass",
                "confidence": 0.94,
                "evidence": "The target boundary follows the visible anatomy and excludes background.",
            },
            {
                "role": "independent_juror",
                "model_id": "qwen",
                "family_id": "qwen",
                "revision": "rev-q",
                "certificate_sha256": _sha("qwen-cert"),
                "prompt_sha256": _sha("prompt"),
                "mask_sha256": selected,
                "panel_bundle_sha256": panel_bundle_sha256,
                "person_index": 0,
                "ownership_report_sha256": ownership["report_sha256"],
                "verdict": "pass",
                "confidence": 0.91,
                "evidence": "Contour and ownership views agree with the selected person and label.",
            },
        ],
    }
    return record


def test_accepted_record_binds_all_evidence_without_granting_production_authority(
    tmp_path: Path,
) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    result = qualify_terminal_record(_record(bundle["panel_bundle_sha256"]), panels=panels)
    assert result["outcome"] == "accepted"
    assert len(result["evidence_sha256"]) == 64
    authority = result["qualification_evidence"]
    assert authority["authority"] == "machine_verified_candidate"
    assert authority["candidate_label"] == "breast_region"
    assert authority["label_scale_hard_qc"]["mask_image_area_ratio"] == pytest.approx(480 / 2304)
    assert authority["human_gold"] is False
    assert authority["production_mask_authority"] is False
    assert authority["operational_certificate_issued"] is False
    assert validate_qualified_queue_payload(result) == result


def test_terminal_receipt_rejects_whole_person_scale_for_fine_label(tmp_path: Path) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    record = _record(bundle["panel_bundle_sha256"])
    record["candidate_label"] = "nipple"
    with pytest.raises(NudeRecordQualificationError, match="label_scale_hard_qc_invalid"):
        qualify_terminal_record(record, panels=panels)


def test_queue_recomputes_label_scale_after_label_and_receipt_hash_rewrite(
    tmp_path: Path,
) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    result = qualify_terminal_record(_record(bundle["panel_bundle_sha256"]), panels=panels)
    result["candidate_label"] = "nipple"
    result["qualification_evidence"]["candidate_label"] = "nipple"
    result["evidence_sha256"] = _canonical_sha256(result["qualification_evidence"])
    with pytest.raises(NudeRecordQualificationError, match="label_scale_hard_qc_invalid"):
        validate_qualified_queue_payload(result)


def test_contact_sheet_or_missing_view_cannot_replace_per_record_evidence(tmp_path: Path) -> None:
    panels = _panels(tmp_path)
    panels.pop("ownership")
    panels["contact_sheet"] = panels["source"]
    with pytest.raises(NudeRecordQualificationError, match="five_view"):
        verify_complete_panel_evidence(panels)


def test_panel_hash_drift_fails_closed(tmp_path: Path) -> None:
    panels = _panels(tmp_path)
    Path(panels["overlay"]["path"]).write_bytes(b"drift")
    with pytest.raises(NudeRecordQualificationError, match="overlay_hash_mismatch"):
        verify_complete_panel_evidence(panels)


def test_terminal_receipt_requires_original_source_pixel_binding(tmp_path: Path) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    panels["source"].pop("original_source_path")
    with pytest.raises(NudeRecordQualificationError, match="original_source_path_required"):
        qualify_terminal_record(_record(bundle["panel_bundle_sha256"]), panels=panels)


def test_acceptance_requires_verified_exact_person_instance_ownership(tmp_path: Path) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    record = _record(bundle["panel_bundle_sha256"])
    _, _, mask = _PANEL_CONTEXTS[bundle["panel_bundle_sha256"]]
    record["ownership"] = _ownership(mask, str(record["source_sha256"]), ambiguous=True)
    ownership_report_sha256 = record["ownership"]["report_sha256"]  # type: ignore[index]
    for review in record["strict_reviews"]:  # type: ignore[union-attr]
        review["person_index"] = None
        review["ownership_report_sha256"] = ownership_report_sha256
    for candidate in record["provider_comparison"]["candidates"]:  # type: ignore[index]
        candidate["person_index"] = None
    with pytest.raises(
        NudeRecordQualificationError, match="verified_person_instance_ownership_required"
    ):
        qualify_terminal_record(record, panels=panels)


def test_hard_qc_veto_cannot_be_cleared_by_passing_critics(tmp_path: Path) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    record = _record(bundle["panel_bundle_sha256"])
    record["hard_qc"]["status"] = "fail"  # type: ignore[index]
    with pytest.raises(NudeRecordQualificationError, match="hard_qc_veto"):
        qualify_terminal_record(record, panels=panels)


def test_provider_and_critic_families_must_be_independent(tmp_path: Path) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    record = _record(bundle["panel_bundle_sha256"])
    record["provider_comparison"]["candidates"][1]["family_id"] = "sam"  # type: ignore[index]
    with pytest.raises(NudeRecordQualificationError, match="independent_provider"):
        qualify_terminal_record(record, panels=panels)


def test_provider_and_critic_votes_must_match_verified_person_ownership(tmp_path: Path) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    record = _record(bundle["panel_bundle_sha256"])
    record["provider_comparison"]["candidates"][1]["person_index"] = 1  # type: ignore[index]
    with pytest.raises(NudeRecordQualificationError, match="provider_person_index_mismatch"):
        qualify_terminal_record(record, panels=panels)
    record = _record(bundle["panel_bundle_sha256"])
    record["strict_reviews"][0]["ownership_report_sha256"] = _sha("wrong-owner")  # type: ignore[index]
    with pytest.raises(NudeRecordQualificationError, match="ownership_report_mismatch"):
        qualify_terminal_record(record, panels=panels)
    record = _record(bundle["panel_bundle_sha256"])
    record["strict_reviews"][1]["family_id"] = "internvl"  # type: ignore[index]
    with pytest.raises(NudeRecordQualificationError, match="independent_strict"):
        qualify_terminal_record(record, panels=panels)


def test_rubber_stamp_and_cross_record_panel_binding_fail(tmp_path: Path) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    record = _record(bundle["panel_bundle_sha256"])
    record["strict_reviews"][0]["evidence"] = "Looks good"  # type: ignore[index]
    with pytest.raises(NudeRecordQualificationError, match="rubber_stamp"):
        qualify_terminal_record(record, panels=panels)
    record = _record(bundle["panel_bundle_sha256"])
    record["strict_reviews"][0]["panel_bundle_sha256"] = _sha("other-panel")  # type: ignore[index]
    with pytest.raises(NudeRecordQualificationError, match="panel_bundle_mismatch"):
        qualify_terminal_record(record, panels=panels)


def test_repaired_outcome_requires_bounded_progress_and_parent_lineage(tmp_path: Path) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    record = _record(bundle["panel_bundle_sha256"], outcome="repaired")
    record["repair"] = {
        "attempt": 1,
        "max_attempts": 2,
        "parent_mask_sha256": _sha("parent-mask"),
        "repair_policy_sha256": _sha("repair-policy"),
        "repair_report_sha256": _sha("repair-report"),
    }
    result = qualify_terminal_record(record, panels=panels)
    assert result["qualification_evidence"]["repair"]["attempt"] == 1
    record["repair"]["parent_mask_sha256"] = record["mask_sha256"]  # type: ignore[index]
    with pytest.raises(NudeRecordQualificationError, match="no_mask_progress"):
        qualify_terminal_record(record, panels=panels)


def test_abstain_and_reject_use_separate_failure_receipt_path(tmp_path: Path) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    for outcome in ("abstained", "rejected"):
        with pytest.raises(NudeRecordQualificationError, match="separate_failure_receipt"):
            qualify_terminal_record(
                _record(bundle["panel_bundle_sha256"], outcome=outcome), panels=panels
            )


def test_queue_payload_revalidation_rejects_hash_and_authority_tampering(tmp_path: Path) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    result = qualify_terminal_record(_record(bundle["panel_bundle_sha256"]), panels=panels)
    result["qualification_evidence"]["human_gold"] = True
    with pytest.raises(NudeRecordQualificationError, match="evidence_hash_mismatch"):
        validate_qualified_queue_payload(result)


def test_uncertain_reviews_create_hash_bound_abstention_receipt(tmp_path: Path) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    record = _record(bundle["panel_bundle_sha256"])
    record.update(
        {
            "outcome": "abstained",
            "failure_stage": "strict_review",
            "reasons": ["independent_review_uncertain"],
        }
    )
    record["strict_reviews"][1]["verdict"] = "uncertain"  # type: ignore[index]
    result = qualify_nonacceptance_record(record, panels=panels)
    assert result["qualification_evidence"]["authority"] == "no_mask_authority"
    assert validate_nonacceptance_queue_payload(result) == result


def test_ambiguous_ownership_routes_to_abstention_without_claiming_an_owner(
    tmp_path: Path,
) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    record = _record(bundle["panel_bundle_sha256"])
    record.update(
        {
            "outcome": "abstained",
            "failure_stage": "strict_review",
            "reasons": ["person_instance_ownership_ambiguous"],
        }
    )
    record["strict_reviews"][1]["verdict"] = "uncertain"  # type: ignore[index]
    _, _, mask = _PANEL_CONTEXTS[bundle["panel_bundle_sha256"]]
    record["ownership"] = _ownership(mask, str(record["source_sha256"]), ambiguous=True)
    ownership_report_sha256 = record["ownership"]["report_sha256"]  # type: ignore[index]
    for review in record["strict_reviews"]:  # type: ignore[union-attr]
        review["person_index"] = None
        review["ownership_report_sha256"] = ownership_report_sha256
    for candidate in record["provider_comparison"]["candidates"]:  # type: ignore[index]
        candidate["person_index"] = None
    result = qualify_nonacceptance_record(record, panels=panels)
    assert result["qualification_evidence"]["ownership"]["status"] == "ambiguous"
    record["ownership"]["person_index"] = 0  # type: ignore[index]
    with pytest.raises(NudeRecordQualificationError, match="cannot_claim_owner"):
        qualify_nonacceptance_record(record, panels=panels)


def test_hard_qc_rejection_retains_reviews_but_cannot_claim_authority(tmp_path: Path) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    record = _record(bundle["panel_bundle_sha256"])
    record.update(
        {
            "outcome": "rejected",
            "failure_stage": "hard_qc",
            "reasons": ["deterministic_boundary_veto"],
        }
    )
    record["hard_qc"]["status"] = "fail"  # type: ignore[index]
    result = qualify_nonacceptance_record(record, panels=panels)
    assert result["qualification_evidence"]["hard_qc"]["status"] == "fail"
    assert result["qualification_evidence"]["production_mask_authority"] is False


def test_nonacceptance_requires_full_independent_review_and_reason(tmp_path: Path) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    record = _record(bundle["panel_bundle_sha256"])
    record.update({"outcome": "abstained", "failure_stage": "strict_review", "reasons": []})
    with pytest.raises(NudeRecordQualificationError, match="failure_reasons_required"):
        qualify_nonacceptance_record(record, panels=panels)


def test_repair_exhaustion_is_bounded_and_reason_coded(tmp_path: Path) -> None:
    panels = _panels(tmp_path)
    bundle = verify_complete_panel_evidence(panels)
    record = _record(bundle["panel_bundle_sha256"])
    record.update(
        {
            "outcome": "rejected",
            "failure_stage": "repair_exhausted",
            "reasons": ["bounded_repair_exhausted"],
            "repair": {
                "attempts": 3,
                "max_attempts": 3,
                "last_parent_mask_sha256": _sha("parent"),
                "repair_policy_sha256": _sha("repair-policy"),
                "repair_report_sha256": _sha("repair-report"),
            },
        }
    )
    record["strict_reviews"][0]["verdict"] = "fail"  # type: ignore[index]
    result = qualify_nonacceptance_record(record, panels=panels)
    assert result["qualification_evidence"]["repair"]["attempts"] == 3


def test_quarantine_receipt_has_no_mask_or_authority() -> None:
    result = qualify_input_terminal_record(
        {
            "sample_id": "bad-input",
            "source_sha256": _sha("source"),
            "source_role": "polygon_external_supervision",
            "registry_sha256": _sha("registry"),
            "shard_sha256": _sha("shard"),
            "outcome": "quarantined",
            "reasons": ["decode_failed"],
            "input_report_sha256": _sha("input-report"),
        }
    )
    evidence = result["qualification_evidence"]
    assert evidence["mask_generated"] is False
    assert evidence["training_authority"] is False
    assert validate_input_terminal_queue_payload(result) == result


def test_holdout_requires_evaluation_role_policy_and_split_group() -> None:
    with pytest.raises(NudeRecordQualificationError, match="holdout_source_role_invalid"):
        qualify_input_terminal_record(
            {
                "sample_id": "unsafe-holdout",
                "source_sha256": _sha("source"),
                "source_role": "polygon_external_supervision",
                "registry_sha256": _sha("registry"),
                "shard_sha256": _sha("shard"),
                "outcome": "holdout",
                "reasons": ["evaluation_only"],
                "input_report_sha256": _sha("input-report"),
                "holdout_policy_sha256": _sha("holdout-policy"),
                "split_group_id": "group-1",
            }
        )
