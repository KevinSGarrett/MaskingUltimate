"""Bind exact-record CelebAMask control alignment decisions to panel evidence."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .celebamask_control_panels import verify_celebamask_control_panel_report
from .critic_catalog import canonical_sha256

SCHEMA_VERSION = "maskfactory.celebamask_control_semantic_review.v1"
REVIEWER_ROLE = "codex_direct_exact_record_visual_review"
VERDICTS = {"pass", "reject", "abstain"}
REASON_CODES = {
    "exact_visible_target_alignment",
    "protected_region_leakage",
    "material_overfill_or_wrong_scale",
    "material_underfill",
    "ambiguous_target_boundary",
}


class CelebAMaskControlSemanticReviewError(ValueError):
    """Control review is incomplete, unbound, or upgrades authority."""


def build_celebamask_control_semantic_review(
    *,
    panel_report: Mapping[str, Any],
    panel_root: Path,
    decisions: Sequence[Mapping[str, Any]],
    reviewer_role: str = REVIEWER_ROLE,
) -> dict[str, Any]:
    """Build one closed exact-record verdict for every panel record."""

    verify_celebamask_control_panel_report(panel_report, panel_root)
    panel_records = panel_report.get("records")
    if not isinstance(panel_records, list):
        raise CelebAMaskControlSemanticReviewError("panel records are invalid")
    by_id = {record.get("sample_id"): record for record in panel_records}
    if len(by_id) != len(panel_records) or None in by_id:
        raise CelebAMaskControlSemanticReviewError("panel identities are invalid")
    if len(decisions) != len(panel_records):
        raise CelebAMaskControlSemanticReviewError("every exact record requires one verdict")

    reviewed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for decision in decisions:
        sample_id = decision.get("sample_id")
        if not isinstance(sample_id, str) or sample_id not in by_id or sample_id in seen:
            raise CelebAMaskControlSemanticReviewError(
                f"unknown or duplicate review sample:{sample_id}"
            )
        seen.add(sample_id)
        verdict = decision.get("verdict")
        reason_code = decision.get("reason_code")
        if verdict not in VERDICTS or reason_code not in REASON_CODES:
            raise CelebAMaskControlSemanticReviewError(f"invalid closed verdict:{sample_id}")
        if verdict == "pass" and reason_code != "exact_visible_target_alignment":
            raise CelebAMaskControlSemanticReviewError(
                f"pass reason is not exact alignment:{sample_id}"
            )
        if verdict == "abstain" and reason_code != "ambiguous_target_boundary":
            raise CelebAMaskControlSemanticReviewError(
                f"abstention reason is not ambiguity:{sample_id}"
            )
        if verdict == "reject" and reason_code in {
            "exact_visible_target_alignment",
            "ambiguous_target_boundary",
        }:
            raise CelebAMaskControlSemanticReviewError(f"reject reason is invalid:{sample_id}")
        evidence_panels = decision.get("evidence_panels")
        if (
            not isinstance(evidence_panels, list)
            or not evidence_panels
            or any(
                panel not in by_id[sample_id].get("panel_files", {}) for panel in evidence_panels
            )
        ):
            raise CelebAMaskControlSemanticReviewError(
                f"review evidence panels are invalid:{sample_id}"
            )
        reviewed.append(
            {
                "sample_id": sample_id,
                "canonical_label": by_id[sample_id]["canonical_label"],
                "assigned_partition": by_id[sample_id]["assigned_partition"],
                "source_image_id": by_id[sample_id]["source_image_id"],
                "panel_set_sha256": by_id[sample_id]["panel_set_sha256"],
                "verdict": verdict,
                "reason_code": reason_code,
                "evidence_panels": list(evidence_panels),
                "review_note": str(decision.get("review_note", "")),
                "visual_alignment_pass_candidate": verdict == "pass",
                "external_reference_qualification_complete": False,
                "critic_control_eligible": False,
                "gold_or_production_authority": False,
            }
        )
    if seen != set(by_id):
        raise CelebAMaskControlSemanticReviewError("review coverage is incomplete")

    verdict_counts = Counter(record["verdict"] for record in reviewed)
    reason_counts = Counter(record["reason_code"] for record in reviewed)
    pass_by_label = Counter(
        record["canonical_label"] for record in reviewed if record["verdict"] == "pass"
    )
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "celebamask_exact_record_control_alignment_review",
        "reviewer_role": reviewer_role,
        "panel_report_sha256": panel_report["self_sha256"],
        "record_count": len(reviewed),
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "visual_alignment_pass_candidates_by_label": dict(sorted(pass_by_label.items())),
        "semantic_screening_complete": True,
        "external_reference_qualification_complete": False,
        "authority_claimed": False,
        "critic_control_authority_granted": False,
        "gold_or_production_authority_granted": False,
        "records": reviewed,
        "claim_limits": [
            "exact-record visual alignment screening only",
            "pass means alignment candidate, not qualified critic control",
            "identity/split and external-reference qualification remain open",
            "external masks remain non-gold weighted supervision",
            "no certificate or production authority",
        ],
        "next_required_stage": (
            "complete external-reference qualification and identity/split review, "
            "then freeze only eligible pass records as critic controls"
        ),
    }
    document["self_sha256"] = canonical_sha256(document)
    return document


def verify_celebamask_control_semantic_review(
    document: Mapping[str, Any], panel_report: Mapping[str, Any]
) -> None:
    """Fail closed on drift, incomplete coverage, or authority promotion."""

    payload = {key: value for key, value in document.items() if key != "self_sha256"}
    if document.get("self_sha256") != canonical_sha256(payload):
        raise CelebAMaskControlSemanticReviewError("review self hash mismatch")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise CelebAMaskControlSemanticReviewError("review schema mismatch")
    if document.get("panel_report_sha256") != panel_report.get("self_sha256"):
        raise CelebAMaskControlSemanticReviewError("panel report binding mismatch")
    if (
        document.get("authority_claimed") is not False
        or document.get("critic_control_authority_granted") is not False
        or document.get("gold_or_production_authority_granted") is not False
        or document.get("external_reference_qualification_complete") is not False
    ):
        raise CelebAMaskControlSemanticReviewError("review authority was upgraded")
    records = document.get("records")
    panel_records = panel_report.get("records")
    if not isinstance(records, list) or not isinstance(panel_records, list):
        raise CelebAMaskControlSemanticReviewError("review records are invalid")
    expected = {record["sample_id"]: record["panel_set_sha256"] for record in panel_records}
    actual = {record.get("sample_id"): record.get("panel_set_sha256") for record in records}
    if actual != expected or document.get("record_count") != len(expected):
        raise CelebAMaskControlSemanticReviewError("review coverage drifted")
    if any(
        record.get("critic_control_eligible") is not False
        or record.get("gold_or_production_authority") is not False
        or record.get("external_reference_qualification_complete") is not False
        for record in records
    ):
        raise CelebAMaskControlSemanticReviewError("record authority was upgraded")
