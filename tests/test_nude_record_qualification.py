from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from maskfactory.nude_record_qualification import (
    NudeRecordQualificationError,
    qualify_terminal_record,
    validate_qualified_queue_payload,
    verify_complete_panel_evidence,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _panels(tmp_path: Path) -> dict[str, dict[str, str]]:
    result = {}
    for kind in ("source", "mask", "overlay", "contour", "ownership"):
        path = tmp_path / f"{kind}.png"
        path.write_bytes(f"panel:{kind}".encode())
        result[kind] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return result


def _record(panel_bundle_sha256: str, *, outcome: str = "accepted") -> dict[str, object]:
    selected = _sha("selected-mask")
    record: dict[str, object] = {
        "sample_id": "adult-sample-0001",
        "source_sha256": _sha("source"),
        "mask_sha256": selected,
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
                },
                {
                    "provider_id": "birefnet",
                    "family_id": "birefnet",
                    "revision": "rev-b",
                    "artifact_sha256": _sha("birefnet-artifact"),
                    "mask_sha256": _sha("other-mask"),
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
    assert authority["human_gold"] is False
    assert authority["production_mask_authority"] is False
    assert authority["operational_certificate_issued"] is False
    assert validate_qualified_queue_payload(result) == result


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
