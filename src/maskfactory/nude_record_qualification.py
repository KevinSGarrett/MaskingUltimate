"""Fail-closed per-record qualification for the adult-corpus batch queue."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

REQUIRED_PANEL_KINDS = (
    "source",
    "mask",
    "overlay",
    "contour",
    "ownership",
)
REQUIRED_REVIEW_ROLES = frozenset({"primary_visual_critic", "independent_juror"})
TERMINAL_OUTCOMES = frozenset({"accepted", "repaired", "abstained", "rejected"})


class NudeRecordQualificationError(ValueError):
    """A record tried to cross a qualification boundary without exact evidence."""


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha256(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise NudeRecordQualificationError(f"{field}_invalid")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NudeRecordQualificationError(f"{field}_invalid")
    return value


def _verify_file(entry: Mapping[str, Any], *, kind: str) -> dict[str, str]:
    path_value = _nonempty(entry.get("path"), f"panel_{kind}_path")
    expected = _sha256(entry.get("sha256"), f"panel_{kind}_sha256")
    path = Path(path_value)
    if not path.is_file():
        raise NudeRecordQualificationError(f"panel_{kind}_missing")
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    if observed != expected:
        raise NudeRecordQualificationError(f"panel_{kind}_hash_mismatch")
    return {"path": str(path.resolve()), "sha256": observed}


def verify_complete_panel_evidence(panels: Mapping[str, Any]) -> dict[str, Any]:
    """Verify five separate record views; a contact sheet alone is never sufficient."""

    if set(panels) != set(REQUIRED_PANEL_KINDS):
        raise NudeRecordQualificationError("complete_five_view_panel_evidence_required")
    verified = {kind: _verify_file(panels[kind], kind=kind) for kind in REQUIRED_PANEL_KINDS}
    bundle = {"required_kinds": list(REQUIRED_PANEL_KINDS), "panels": verified}
    bundle["panel_bundle_sha256"] = _canonical_sha256(bundle)
    return bundle


def _verify_provider_comparison(
    comparison: Mapping[str, Any], *, selected_mask_sha256: str
) -> dict[str, Any]:
    if comparison.get("status") != "pass":
        raise NudeRecordQualificationError("provider_comparison_not_passed")
    if comparison.get("selected_mask_sha256") != selected_mask_sha256:
        raise NudeRecordQualificationError("provider_selected_mask_mismatch")
    report_sha256 = _sha256(comparison.get("report_sha256"), "provider_report_sha256")
    candidates = comparison.get("candidates")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise NudeRecordQualificationError("provider_candidates_invalid")
    normalized: list[dict[str, str]] = []
    identities: set[str] = set()
    families: set[str] = set()
    selected_present = False
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise NudeRecordQualificationError(f"provider_candidate_{index}_invalid")
        provider_id = _nonempty(candidate.get("provider_id"), "provider_id")
        family_id = _nonempty(candidate.get("family_id"), "provider_family_id")
        revision = _nonempty(candidate.get("revision"), "provider_revision")
        artifact_sha256 = _sha256(candidate.get("artifact_sha256"), "provider_artifact_sha256")
        mask_sha256 = _sha256(candidate.get("mask_sha256"), "provider_mask_sha256")
        identity = f"{provider_id}@{revision}"
        if identity in identities:
            raise NudeRecordQualificationError("provider_candidate_duplicate")
        identities.add(identity)
        families.add(family_id)
        selected_present = selected_present or mask_sha256 == selected_mask_sha256
        normalized.append(
            {
                "provider_id": provider_id,
                "family_id": family_id,
                "revision": revision,
                "artifact_sha256": artifact_sha256,
                "mask_sha256": mask_sha256,
            }
        )
    if len(normalized) < 2 or len(families) < 2:
        raise NudeRecordQualificationError("independent_provider_comparison_required")
    if not selected_present:
        raise NudeRecordQualificationError("selected_mask_absent_from_provider_candidates")
    return {
        "status": "pass",
        "report_sha256": report_sha256,
        "selected_mask_sha256": selected_mask_sha256,
        "candidates": normalized,
    }


def _verify_hard_qc(hard_qc: Mapping[str, Any], *, selected_mask_sha256: str) -> dict[str, str]:
    if hard_qc.get("status") != "pass":
        raise NudeRecordQualificationError("hard_qc_veto")
    if hard_qc.get("mask_sha256") != selected_mask_sha256:
        raise NudeRecordQualificationError("hard_qc_mask_mismatch")
    return {
        "status": "pass",
        "mask_sha256": selected_mask_sha256,
        "policy_sha256": _sha256(hard_qc.get("policy_sha256"), "hard_qc_policy_sha256"),
        "report_sha256": _sha256(hard_qc.get("report_sha256"), "hard_qc_report_sha256"),
    }


def _verify_strict_reviews(
    reviews: Sequence[Mapping[str, Any]],
    *,
    selected_mask_sha256: str,
    panel_bundle_sha256: str,
) -> list[dict[str, Any]]:
    if not isinstance(reviews, Sequence) or isinstance(reviews, (str, bytes)):
        raise NudeRecordQualificationError("strict_reviews_invalid")
    normalized: list[dict[str, Any]] = []
    roles: set[str] = set()
    families: set[str] = set()
    for review in reviews:
        if not isinstance(review, Mapping):
            raise NudeRecordQualificationError("strict_review_invalid")
        role = _nonempty(review.get("role"), "strict_review_role")
        if role not in REQUIRED_REVIEW_ROLES or role in roles:
            raise NudeRecordQualificationError("strict_review_role_quorum_invalid")
        if review.get("verdict") != "pass":
            raise NudeRecordQualificationError("strict_review_not_passed")
        if review.get("mask_sha256") != selected_mask_sha256:
            raise NudeRecordQualificationError("strict_review_mask_mismatch")
        if review.get("panel_bundle_sha256") != panel_bundle_sha256:
            raise NudeRecordQualificationError("strict_review_panel_bundle_mismatch")
        evidence = _nonempty(review.get("evidence"), "strict_review_evidence")
        if evidence.strip().lower() in {"pass", "looks good", "approved", "ok"}:
            raise NudeRecordQualificationError("strict_review_rubber_stamp_rejected")
        family_id = _nonempty(review.get("family_id"), "strict_review_family_id")
        roles.add(role)
        families.add(family_id)
        normalized.append(
            {
                "role": role,
                "model_id": _nonempty(review.get("model_id"), "strict_review_model_id"),
                "family_id": family_id,
                "revision": _nonempty(review.get("revision"), "strict_review_revision"),
                "certificate_sha256": _sha256(
                    review.get("certificate_sha256"), "strict_review_certificate_sha256"
                ),
                "prompt_sha256": _sha256(
                    review.get("prompt_sha256"), "strict_review_prompt_sha256"
                ),
                "mask_sha256": selected_mask_sha256,
                "panel_bundle_sha256": panel_bundle_sha256,
                "verdict": "pass",
                "confidence": float(review.get("confidence", -1)),
                "evidence": evidence,
            }
        )
        if not 0 <= normalized[-1]["confidence"] <= 1:
            raise NudeRecordQualificationError("strict_review_confidence_invalid")
    if roles != REQUIRED_REVIEW_ROLES or len(families) != 2:
        raise NudeRecordQualificationError("independent_strict_review_quorum_required")
    return sorted(normalized, key=lambda row: row["role"])


def _verify_repair(
    repair: Mapping[str, Any] | None, *, outcome: str, selected_mask_sha256: str
) -> dict[str, Any] | None:
    if outcome == "accepted":
        if repair is not None:
            raise NudeRecordQualificationError("accepted_outcome_cannot_claim_repair")
        return None
    if outcome != "repaired":
        return None
    if not isinstance(repair, Mapping):
        raise NudeRecordQualificationError("repair_lineage_required")
    attempt = repair.get("attempt")
    maximum = repair.get("max_attempts")
    if (
        not isinstance(attempt, int)
        or isinstance(attempt, bool)
        or not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or not 1 <= attempt <= maximum <= 3
    ):
        raise NudeRecordQualificationError("bounded_repair_attempt_invalid")
    parent = _sha256(repair.get("parent_mask_sha256"), "repair_parent_mask_sha256")
    if parent == selected_mask_sha256:
        raise NudeRecordQualificationError("repair_made_no_mask_progress")
    return {
        "attempt": attempt,
        "max_attempts": maximum,
        "parent_mask_sha256": parent,
        "selected_mask_sha256": selected_mask_sha256,
        "repair_policy_sha256": _sha256(repair.get("repair_policy_sha256"), "repair_policy_sha256"),
        "repair_report_sha256": _sha256(repair.get("repair_report_sha256"), "repair_report_sha256"),
    }


def qualify_terminal_record(
    record: Mapping[str, Any], *, panels: Mapping[str, Any]
) -> dict[str, Any]:
    """Produce one hash-bound queue payload for a fully reviewed terminal candidate."""

    outcome = record.get("outcome")
    if outcome not in TERMINAL_OUTCOMES:
        raise NudeRecordQualificationError("terminal_outcome_invalid")
    if outcome in {"abstained", "rejected"}:
        raise NudeRecordQualificationError(
            "abstained_or_rejected_outcomes_require_the_separate_failure_receipt_path"
        )
    sample_id = _nonempty(record.get("sample_id"), "sample_id")
    source_sha256 = _sha256(record.get("source_sha256"), "source_sha256")
    selected_mask_sha256 = _sha256(record.get("mask_sha256"), "mask_sha256")
    panel_evidence = verify_complete_panel_evidence(panels)
    provider_comparison = _verify_provider_comparison(
        record.get("provider_comparison", {}), selected_mask_sha256=selected_mask_sha256
    )
    hard_qc = _verify_hard_qc(record.get("hard_qc", {}), selected_mask_sha256=selected_mask_sha256)
    strict_reviews = _verify_strict_reviews(
        record.get("strict_reviews", ()),
        selected_mask_sha256=selected_mask_sha256,
        panel_bundle_sha256=panel_evidence["panel_bundle_sha256"],
    )
    repair = _verify_repair(
        record.get("repair"), outcome=str(outcome), selected_mask_sha256=selected_mask_sha256
    )
    evidence = {
        "schema_version": "maskfactory.nude_record_qualification.v1",
        "sample_id": sample_id,
        "source_sha256": source_sha256,
        "mask_sha256": selected_mask_sha256,
        "outcome": outcome,
        "provider_comparison": provider_comparison,
        "hard_qc": hard_qc,
        "panel_evidence": panel_evidence,
        "strict_reviews": strict_reviews,
        "repair": repair,
        "authority": "machine_verified_candidate",
        "human_gold": False,
        "production_mask_authority": False,
        "operational_certificate_issued": False,
    }
    evidence_sha256 = _canonical_sha256(evidence)
    return {
        "sample_id": sample_id,
        "source_sha256": source_sha256,
        "mask_sha256": selected_mask_sha256,
        "outcome": outcome,
        "evidence_sha256": evidence_sha256,
        "qualification_evidence": evidence,
    }


def validate_qualified_queue_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute an accepted/repaired receipt before durable queue mutation."""

    if payload.get("outcome") not in {"accepted", "repaired"}:
        raise NudeRecordQualificationError("qualified_queue_outcome_invalid")
    evidence = payload.get("qualification_evidence")
    if not isinstance(evidence, Mapping):
        raise NudeRecordQualificationError("qualification_evidence_required")
    if evidence.get("schema_version") != "maskfactory.nude_record_qualification.v1":
        raise NudeRecordQualificationError("qualification_evidence_schema_invalid")
    for field in ("sample_id", "source_sha256", "mask_sha256", "outcome"):
        if payload.get(field) != evidence.get(field):
            raise NudeRecordQualificationError(f"qualification_{field}_mismatch")
    expected = _sha256(payload.get("evidence_sha256"), "evidence_sha256")
    observed = _canonical_sha256(dict(evidence))
    if observed != expected:
        raise NudeRecordQualificationError("qualification_evidence_hash_mismatch")
    if (
        evidence.get("authority") != "machine_verified_candidate"
        or evidence.get("human_gold") is not False
        or evidence.get("production_mask_authority") is not False
        or evidence.get("operational_certificate_issued") is not False
    ):
        raise NudeRecordQualificationError("qualification_authority_boundary_invalid")
    panel_evidence = evidence.get("panel_evidence")
    if not isinstance(panel_evidence, Mapping):
        raise NudeRecordQualificationError("qualification_panel_evidence_invalid")
    panels = panel_evidence.get("panels")
    if not isinstance(panels, Mapping):
        raise NudeRecordQualificationError("qualification_panels_invalid")
    verified_panels = verify_complete_panel_evidence(panels)
    if verified_panels != panel_evidence:
        raise NudeRecordQualificationError("qualification_panel_evidence_drift")
    _verify_provider_comparison(
        evidence.get("provider_comparison", {}),
        selected_mask_sha256=str(payload["mask_sha256"]),
    )
    _verify_hard_qc(evidence.get("hard_qc", {}), selected_mask_sha256=str(payload["mask_sha256"]))
    _verify_strict_reviews(
        evidence.get("strict_reviews", ()),
        selected_mask_sha256=str(payload["mask_sha256"]),
        panel_bundle_sha256=str(panel_evidence.get("panel_bundle_sha256")),
    )
    _verify_repair(
        evidence.get("repair"),
        outcome=str(payload["outcome"]),
        selected_mask_sha256=str(payload["mask_sha256"]),
    )
    return dict(payload)


__all__ = [
    "NudeRecordQualificationError",
    "REQUIRED_PANEL_KINDS",
    "REQUIRED_REVIEW_ROLES",
    "qualify_terminal_record",
    "validate_qualified_queue_payload",
    "verify_complete_panel_evidence",
]
