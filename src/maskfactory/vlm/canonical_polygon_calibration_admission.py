"""Seal per-record calibration-only decisions for canonical polygon candidates."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .canonical_polygon_panels import PANEL_NAMES, verify_candidate_panel_report
from .canonical_polygon_source_candidates import verify_canonical_polygon_source_candidates
from .critic_catalog import canonical_sha256

SCHEMA_VERSION = "maskfactory.canonical_polygon_calibration_admission.v1"
VERDICTS = frozenset({"admitted_calibration_only", "abstained", "rejected"})
REASONS = {
    "admitted_calibration_only": frozenset({"visible_target_localized_bounded_control"}),
    "abstained": frozenset({"ambiguous_target_scope"}),
    "rejected": frozenset(
        {
            "wrong_target_or_label",
            "material_overfill_or_wrong_scale",
            "disconnected_or_irregular_boundary_leakage",
        }
    ),
}


class CanonicalPolygonCalibrationAdmissionError(ValueError):
    """A calibration receipt is incomplete, unbound, or authority-expanding."""


def _decision_by_id(
    decisions: Sequence[Mapping[str, Any]], candidate_ids: set[str]
) -> dict[str, Mapping[str, Any]]:
    if len(decisions) != len(candidate_ids):
        raise CanonicalPolygonCalibrationAdmissionError("every candidate requires one decision")
    result: dict[str, Mapping[str, Any]] = {}
    for decision in decisions:
        if not isinstance(decision, Mapping):
            raise CanonicalPolygonCalibrationAdmissionError("decision is not an object")
        sample_id = decision.get("sample_id")
        verdict = decision.get("screening_verdict")
        reason = decision.get("reason_code")
        evidence = decision.get("evidence_panels")
        note = decision.get("review_note")
        if (
            not isinstance(sample_id, str)
            or sample_id not in candidate_ids
            or sample_id in result
            or verdict not in VERDICTS
            or reason not in REASONS[verdict]
            or not isinstance(evidence, list)
            or not evidence
            or any(item not in PANEL_NAMES for item in evidence)
            or not isinstance(note, str)
            or not note.strip()
        ):
            raise CanonicalPolygonCalibrationAdmissionError(
                f"invalid exact-record decision:{sample_id}"
            )
        result[sample_id] = decision
    if set(result) != candidate_ids:
        raise CanonicalPolygonCalibrationAdmissionError("decision coverage is incomplete")
    return result


def build_canonical_polygon_calibration_admission(
    *,
    candidates: Mapping[str, Any],
    panel_report: Mapping[str, Any],
    panel_root: Path,
    decisions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bind every interactive decision to exact immutable candidate/panel evidence."""

    verify_canonical_polygon_source_candidates(candidates)
    verify_candidate_panel_report(panel_report, panel_root)
    if panel_report.get("candidate_set_sha256") != candidates.get("self_sha256"):
        raise CanonicalPolygonCalibrationAdmissionError("candidate/panel binding drift")
    selected = candidates.get("selected")
    panel_records = panel_report.get("records")
    if not isinstance(selected, list) or not isinstance(panel_records, list):
        raise CanonicalPolygonCalibrationAdmissionError("candidate/panel records are invalid")
    candidate_by_id = {str(item.get("sample_id")): item for item in selected}
    panel_by_id = {str(item.get("sample_id")): item for item in panel_records}
    if (
        len(candidate_by_id) != len(selected)
        or "None" in candidate_by_id
        or set(candidate_by_id) != set(panel_by_id)
        or len(panel_by_id) != len(panel_records)
    ):
        raise CanonicalPolygonCalibrationAdmissionError("candidate/panel identities drift")
    decision_by_id = _decision_by_id(decisions, set(candidate_by_id))
    results: list[dict[str, Any]] = []
    for sample_id in sorted(candidate_by_id):
        candidate = candidate_by_id[sample_id]
        panel = panel_by_id[sample_id]
        decision = decision_by_id[sample_id]
        if (
            candidate.get("external_reference_qualification_complete") is not False
            or candidate.get("critic_positive_control_eligible") is not False
            or candidate.get("gold_or_production_authority") is not False
            or panel.get("visual_alignment_reviewed") is not False
            or panel.get("critic_positive_control_eligible") is not False
            or panel.get("gold_or_production_authority") is not False
        ):
            raise CanonicalPolygonCalibrationAdmissionError(
                f"candidate/panel authority drift:{sample_id}"
            )
        result = {
            "candidate_id": sample_id,
            "sample_id": sample_id,
            "dataset_id": candidate["dataset_id"],
            "lineage_group": candidate["lineage_group"],
            "assigned_partition": candidate["assigned_partition"],
            "raw_label": candidate["raw_label"],
            "canonical_label": candidate["canonical_label"],
            "candidate_kind": candidate["candidate_kind"],
            "source_sha256": candidate["source_sha256"],
            "mask_sha256": candidate["mask_sha256"],
            "panel_set_sha256": panel["panel_set_sha256"],
            "panel_sha256s": panel["panel_sha256s"],
            "screening_verdict": decision["screening_verdict"],
            "reason_code": decision["reason_code"],
            "evidence_panels": list(decision["evidence_panels"]),
            "screening_basis": [
                "interactive session-agent review of exact source, binary-mask, overlay, contour, full-context, and target-zoom panels",
                "sealed source-label contract and hard-QC candidate evidence remain calibration-only",
                decision["review_note"].strip(),
            ],
            "external_reference_qualification_complete": False,
            "critic_role_authority_granted": False,
            "gold_or_training_truth_granted": False,
            "production_or_certificate_authority_granted": False,
            "strict_visual_pass_claimed": False,
        }
        results.append(result)
    counts = Counter(item["screening_verdict"] for item in results)
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "canonical_polygon_per_record_calibration_control_admission",
        "candidate_set_self_sha256": candidates["self_sha256"],
        "panel_report_candidate_set_sha256": panel_report["candidate_set_sha256"],
        "panel_report_self_sha256": panel_report["self_sha256"],
        "record_count": len(results),
        "admitted_calibration_only_count": counts["admitted_calibration_only"],
        "abstained_count": counts["abstained"],
        "rejected_count": counts["rejected"],
        "authority": {
            "calibration_controls_only": True,
            "source_label_authority_granted": False,
            "critic_role_authority_granted": False,
            "gold_or_training_truth_granted": False,
            "production_or_certificate_authority_granted": False,
            "strict_visual_pass_claimed": False,
        },
        "results": results,
        "claim_limits": [
            "Interactive per-record screening is non-certifying and non-production.",
            "Admission is limited to calibration-control eligibility; it does not grant source qualification, gold, training truth, critic-role, production, or certificate authority.",
            "Rejected and abstained records remain excluded unless a separately bound review supersedes this receipt.",
            "This receipt binds immutable candidate and panel manifests and does not modify upstream labels, source assets, split assignments, or provenance policy.",
        ],
        "next_required_stage": "Use only an explicitly approved bounded calibration-control plan; this receipt does not authorize training, model selection, scoring, or truth-label mutation.",
    }
    document["self_sha256"] = canonical_sha256(document)
    verify_canonical_polygon_calibration_admission(document, candidates, panel_report, panel_root)
    return document


def verify_canonical_polygon_calibration_admission(
    document: Mapping[str, Any],
    candidates: Mapping[str, Any],
    panel_report: Mapping[str, Any],
    panel_root: Path,
) -> None:
    """Fail closed on source drift, incomplete screening, or authority mutation."""

    verify_canonical_polygon_source_candidates(candidates)
    verify_candidate_panel_report(panel_report, panel_root)
    payload = {key: value for key, value in document.items() if key != "self_sha256"}
    if document.get("self_sha256") != canonical_sha256(payload):
        raise CanonicalPolygonCalibrationAdmissionError("admission self hash mismatch")
    if (
        document.get("schema_version") != SCHEMA_VERSION
        or document.get("candidate_set_self_sha256") != candidates.get("self_sha256")
        or document.get("panel_report_candidate_set_sha256") != panel_report.get("candidate_set_sha256")
        or document.get("panel_report_self_sha256") != panel_report.get("self_sha256")
    ):
        raise CanonicalPolygonCalibrationAdmissionError("admission input binding drift")
    authority = document.get("authority")
    expected_authority = {
        "calibration_controls_only": True,
        "source_label_authority_granted": False,
        "critic_role_authority_granted": False,
        "gold_or_training_truth_granted": False,
        "production_or_certificate_authority_granted": False,
        "strict_visual_pass_claimed": False,
    }
    if authority != expected_authority:
        raise CanonicalPolygonCalibrationAdmissionError("admission authority drift")
    selected = candidates.get("selected")
    panel_rows = panel_report.get("records")
    results = document.get("results")
    if not isinstance(selected, list) or not isinstance(panel_rows, list) or not isinstance(results, list):
        raise CanonicalPolygonCalibrationAdmissionError("admission records are invalid")
    candidates_by_id = {str(item.get("sample_id")): item for item in selected}
    panels_by_id = {str(item.get("sample_id")): item for item in panel_rows}
    results_by_id = {str(item.get("sample_id")): item for item in results}
    if (
        len(results_by_id) != len(results)
        or set(results_by_id) != set(candidates_by_id)
        or set(candidates_by_id) != set(panels_by_id)
        or document.get("record_count") != len(results)
    ):
        raise CanonicalPolygonCalibrationAdmissionError("admission coverage drift")
    counts = Counter()
    for sample_id, result in results_by_id.items():
        candidate = candidates_by_id[sample_id]
        panel = panels_by_id[sample_id]
        verdict = result.get("screening_verdict")
        reason = result.get("reason_code")
        if (
            verdict not in VERDICTS
            or reason not in REASONS[verdict]
            or result.get("candidate_id") != sample_id
            or result.get("panel_set_sha256") != panel.get("panel_set_sha256")
            or result.get("panel_sha256s") != panel.get("panel_sha256s")
            or result.get("canonical_label") != candidate.get("canonical_label")
            or result.get("raw_label") != candidate.get("raw_label")
            or result.get("assigned_partition") != candidate.get("assigned_partition")
            or result.get("candidate_kind") != candidate.get("candidate_kind")
            or result.get("source_sha256") != candidate.get("source_sha256")
            or result.get("mask_sha256") != candidate.get("mask_sha256")
            or not isinstance(result.get("evidence_panels"), list)
            or not result["evidence_panels"]
            or any(item not in PANEL_NAMES for item in result["evidence_panels"])
            or result.get("external_reference_qualification_complete") is not False
            or result.get("critic_role_authority_granted") is not False
            or result.get("gold_or_training_truth_granted") is not False
            or result.get("production_or_certificate_authority_granted") is not False
            or result.get("strict_visual_pass_claimed") is not False
        ):
            raise CanonicalPolygonCalibrationAdmissionError(
                f"admission record authority or binding drift:{sample_id}"
            )
        counts[verdict] += 1
    if (
        document.get("admitted_calibration_only_count") != counts["admitted_calibration_only"]
        or document.get("abstained_count") != counts["abstained"]
        or document.get("rejected_count") != counts["rejected"]
    ):
        raise CanonicalPolygonCalibrationAdmissionError("admission summary drift")


__all__ = [
    "CanonicalPolygonCalibrationAdmissionError",
    "build_canonical_polygon_calibration_admission",
    "verify_canonical_polygon_calibration_admission",
]
