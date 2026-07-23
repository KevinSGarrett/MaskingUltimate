"""Bind exact-record semantic screening to canonical polygon evidence panels."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .canonical_polygon_panels import verify_candidate_panel_report
from .critic_catalog import canonical_sha256

SCHEMA_VERSION = "maskfactory.canonical_polygon_semantic_review.v1"
REVIEWER_ROLE = "codex_direct_exact_record_visual_review"
VERDICTS = {"reject", "abstain"}
REASON_CODES = {
    "wrong_target_or_label",
    "material_overfill_or_wrong_scale",
    "ambiguous_target_scope",
}


class CanonicalPolygonSemanticReviewError(ValueError):
    """Semantic review is incomplete, unbound, or attempts an authority upgrade."""


def build_semantic_review(
    *,
    panel_report: Mapping[str, Any],
    panel_root: Any,
    decisions: Sequence[Mapping[str, Any]],
    reviewer_role: str = REVIEWER_ROLE,
) -> dict[str, Any]:
    """Build a closed review artifact without upgrading external supervision."""

    verify_candidate_panel_report(panel_report, panel_root)
    records = panel_report.get("records")
    if not isinstance(records, list):
        raise CanonicalPolygonSemanticReviewError("panel report records are invalid")
    by_id = {record.get("sample_id"): record for record in records}
    if len(by_id) != len(records) or None in by_id:
        raise CanonicalPolygonSemanticReviewError("panel sample identities are invalid")
    if len(decisions) != len(records):
        raise CanonicalPolygonSemanticReviewError("every exact record requires one verdict")

    reviewed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for decision in decisions:
        sample_id = decision.get("sample_id")
        if not isinstance(sample_id, str) or sample_id not in by_id or sample_id in seen:
            raise CanonicalPolygonSemanticReviewError(
                f"unknown or duplicate review sample:{sample_id}"
            )
        seen.add(sample_id)
        verdict = decision.get("verdict")
        reason_code = decision.get("reason_code")
        if verdict not in VERDICTS or reason_code not in REASON_CODES:
            raise CanonicalPolygonSemanticReviewError(f"invalid closed verdict:{sample_id}")
        if verdict == "abstain" and reason_code != "ambiguous_target_scope":
            raise CanonicalPolygonSemanticReviewError(
                f"abstention reason is not ambiguity:{sample_id}"
            )
        if verdict == "reject" and reason_code == "ambiguous_target_scope":
            raise CanonicalPolygonSemanticReviewError(f"ambiguity must abstain:{sample_id}")
        evidence_panels = decision.get("evidence_panels")
        if (
            not isinstance(evidence_panels, list)
            or not evidence_panels
            or any(name not in by_id[sample_id].get("panel_files", {}) for name in evidence_panels)
        ):
            raise CanonicalPolygonSemanticReviewError(
                f"review evidence panels are invalid:{sample_id}"
            )
        reviewed.append(
            {
                "sample_id": sample_id,
                "canonical_label": by_id[sample_id]["canonical_label"],
                "dataset_id": by_id[sample_id]["dataset_id"],
                "assigned_partition": by_id[sample_id]["assigned_partition"],
                "panel_set_sha256": by_id[sample_id]["panel_set_sha256"],
                "verdict": verdict,
                "reason_code": reason_code,
                "evidence_panels": list(evidence_panels),
                "review_note": str(decision.get("review_note", "")),
                "critic_positive_control_eligible": False,
                "critic_negative_control_eligible": False,
                "gold_or_production_authority": False,
            }
        )
    if seen != set(by_id):
        raise CanonicalPolygonSemanticReviewError("review coverage is incomplete")

    verdict_counts = Counter(item["verdict"] for item in reviewed)
    reason_counts = Counter(item["reason_code"] for item in reviewed)
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "canonical_polygon_exact_record_semantic_screening",
        "reviewer_role": reviewer_role,
        "panel_report_sha256": panel_report["self_sha256"],
        "record_count": len(reviewed),
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "semantic_screening_complete": True,
        "positive_control_count": 0,
        "authority_claimed": False,
        "critic_control_authority_granted": False,
        "gold_or_production_authority_granted": False,
        "claim_limits": [
            "direct exact-record screening only",
            "external-reference qualification remains required",
            "no critic qualification authority",
            "no gold, training-truth, certificate, or production authority",
        ],
        "records": reviewed,
        "next_required_stage": (
            "source new exact canonical positive controls and separately qualify "
            "eligible negative controls before critic-role qualification"
        ),
    }
    document["self_sha256"] = canonical_sha256(document)
    return document


def verify_semantic_review(document: Mapping[str, Any], panel_report: Mapping[str, Any]) -> None:
    """Fail closed on drift, incomplete coverage, or an authority upgrade."""

    payload = {key: value for key, value in document.items() if key != "self_sha256"}
    if document.get("self_sha256") != canonical_sha256(payload):
        raise CanonicalPolygonSemanticReviewError("semantic review self hash mismatch")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise CanonicalPolygonSemanticReviewError("semantic review schema mismatch")
    if document.get("panel_report_sha256") != panel_report.get("self_sha256"):
        raise CanonicalPolygonSemanticReviewError("panel report binding mismatch")
    if (
        document.get("authority_claimed") is not False
        or document.get("critic_control_authority_granted") is not False
        or document.get("gold_or_production_authority_granted") is not False
    ):
        raise CanonicalPolygonSemanticReviewError("semantic review upgraded authority")
    records = document.get("records")
    panel_records = panel_report.get("records")
    if not isinstance(records, list) or not isinstance(panel_records, list):
        raise CanonicalPolygonSemanticReviewError("semantic review records are invalid")
    expected = {record["sample_id"]: record["panel_set_sha256"] for record in panel_records}
    actual = {record.get("sample_id"): record.get("panel_set_sha256") for record in records}
    if actual != expected or document.get("record_count") != len(expected):
        raise CanonicalPolygonSemanticReviewError("semantic review coverage drifted")
    if any(
        record.get("critic_positive_control_eligible") is not False
        or record.get("critic_negative_control_eligible") is not False
        or record.get("gold_or_production_authority") is not False
        for record in records
    ):
        raise CanonicalPolygonSemanticReviewError("record authority was upgraded")
