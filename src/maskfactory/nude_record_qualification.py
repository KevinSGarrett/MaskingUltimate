"""Fail-closed per-record qualification for the adult-corpus batch queue."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image

from .nude_polygon_hard_qc import NudePolygonQcError, evaluate_anatomy_mask_scale
from .nude_visual_evidence import verify_pixel_semantic_visual_evidence

REQUIRED_PANEL_KINDS = (
    "source",
    "mask",
    "overlay",
    "contour",
    "ownership",
)
REQUIRED_REVIEW_ROLES = frozenset({"primary_visual_critic", "independent_juror"})
TERMINAL_OUTCOMES = frozenset({"accepted", "repaired", "abstained", "rejected"})
FAILURE_STAGES = frozenset({"provider_comparison", "hard_qc", "strict_review", "repair_exhausted"})


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


def _verify_pixel_semantic_evidence(
    record: Mapping[str, Any], panels: Mapping[str, Any]
) -> dict[str, Any]:
    source_entry = panels.get("source")
    if not isinstance(source_entry, Mapping):
        raise NudeRecordQualificationError("source_panel_entry_invalid")
    original_source_path = source_entry.get("original_source_path")
    if not isinstance(original_source_path, str) or not original_source_path:
        raise NudeRecordQualificationError("original_source_path_required")
    try:
        return verify_pixel_semantic_visual_evidence(
            original_source_path=Path(original_source_path),
            original_source_sha256=str(record.get("source_sha256") or ""),
            selected_mask_sha256=str(record.get("mask_sha256") or ""),
            views={kind: panels[kind] for kind in REQUIRED_PANEL_KINDS},
        )
    except ValueError as exc:
        raise NudeRecordQualificationError(f"pixel_semantic_visual_evidence_invalid:{exc}") from exc


def _verify_label_scale(panels: Mapping[str, Any], *, candidate_label: str) -> dict[str, Any]:
    mask_entry = panels.get("mask")
    if not isinstance(mask_entry, Mapping):
        raise NudeRecordQualificationError("mask_panel_entry_invalid")
    path = Path(_nonempty(mask_entry.get("path"), "panel_mask_path"))
    try:
        pixels = np.asarray(Image.open(path).convert("L")) > 0
        return evaluate_anatomy_mask_scale(pixels, candidate_label=candidate_label)
    except (OSError, NudePolygonQcError) as exc:
        raise NudeRecordQualificationError(f"label_scale_hard_qc_invalid:{exc}") from exc


def _verify_provider_comparison(
    comparison: Mapping[str, Any],
    *,
    selected_mask_sha256: str,
    allowed_statuses: frozenset[str] = frozenset({"pass"}),
    expected_person_index: int | None,
) -> dict[str, Any]:
    if comparison.get("status") not in allowed_statuses:
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
        person_index = candidate.get("person_index")
        if person_index is not None and (
            not isinstance(person_index, int) or isinstance(person_index, bool) or person_index < 0
        ):
            raise NudeRecordQualificationError("provider_person_index_invalid")
        if expected_person_index is not None and person_index != expected_person_index:
            raise NudeRecordQualificationError("provider_person_index_mismatch")
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
                "person_index": person_index,
            }
        )
    if len(normalized) < 2 or len(families) < 2:
        raise NudeRecordQualificationError("independent_provider_comparison_required")
    if not selected_present:
        raise NudeRecordQualificationError("selected_mask_absent_from_provider_candidates")
    return {
        "status": comparison["status"],
        "report_sha256": report_sha256,
        "selected_mask_sha256": selected_mask_sha256,
        "candidates": normalized,
    }


def _verify_ownership(
    ownership: Mapping[str, Any],
    *,
    source_sha256: str,
    selected_mask_sha256: str,
    acceptance_required: bool,
) -> dict[str, Any]:
    if not isinstance(ownership, Mapping):
        raise NudeRecordQualificationError("ownership_evidence_required")
    status = ownership.get("status")
    if status not in {"verified", "ambiguous", "unresolved"}:
        raise NudeRecordQualificationError("ownership_status_invalid")
    if ownership.get("source_sha256") != source_sha256:
        raise NudeRecordQualificationError("ownership_source_mismatch")
    if ownership.get("mask_sha256") != selected_mask_sha256:
        raise NudeRecordQualificationError("ownership_mask_mismatch")
    report_sha256 = _sha256(ownership.get("report_sha256"), "ownership_report_sha256")
    person_index = ownership.get("person_index")
    owner_id = ownership.get("owner_id")
    scene_instance_id = ownership.get("scene_instance_id")
    if status == "verified":
        if not isinstance(person_index, int) or isinstance(person_index, bool) or person_index < 0:
            raise NudeRecordQualificationError("ownership_person_index_invalid")
        owner_id = _nonempty(owner_id, "ownership_owner_id")
        scene_instance_id = _nonempty(scene_instance_id, "ownership_scene_instance_id")
    else:
        if acceptance_required:
            raise NudeRecordQualificationError("verified_person_instance_ownership_required")
        if person_index is not None or owner_id is not None or scene_instance_id is not None:
            raise NudeRecordQualificationError("ambiguous_ownership_cannot_claim_owner")
    return {
        "status": status,
        "source_sha256": source_sha256,
        "mask_sha256": selected_mask_sha256,
        "person_index": person_index,
        "owner_id": owner_id,
        "scene_instance_id": scene_instance_id,
        "report_sha256": report_sha256,
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
    expected_person_index: int,
    ownership_report_sha256: str,
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
        if review.get("person_index") != expected_person_index:
            raise NudeRecordQualificationError("strict_review_person_index_mismatch")
        if review.get("ownership_report_sha256") != ownership_report_sha256:
            raise NudeRecordQualificationError("strict_review_ownership_report_mismatch")
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
                "person_index": expected_person_index,
                "ownership_report_sha256": ownership_report_sha256,
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
    candidate_label = _nonempty(record.get("candidate_label"), "candidate_label")
    source_sha256 = _sha256(record.get("source_sha256"), "source_sha256")
    selected_mask_sha256 = _sha256(record.get("mask_sha256"), "mask_sha256")
    panel_evidence = verify_complete_panel_evidence(panels)
    pixel_semantic_evidence = _verify_pixel_semantic_evidence(record, panels)
    label_scale_hard_qc = _verify_label_scale(panels, candidate_label=candidate_label)
    ownership = _verify_ownership(
        record.get("ownership", {}),
        source_sha256=source_sha256,
        selected_mask_sha256=selected_mask_sha256,
        acceptance_required=True,
    )
    provider_comparison = _verify_provider_comparison(
        record.get("provider_comparison", {}),
        selected_mask_sha256=selected_mask_sha256,
        expected_person_index=int(ownership["person_index"]),
    )
    hard_qc = _verify_hard_qc(record.get("hard_qc", {}), selected_mask_sha256=selected_mask_sha256)
    strict_reviews = _verify_strict_reviews(
        record.get("strict_reviews", ()),
        selected_mask_sha256=selected_mask_sha256,
        panel_bundle_sha256=panel_evidence["panel_bundle_sha256"],
        expected_person_index=int(ownership["person_index"]),
        ownership_report_sha256=str(ownership["report_sha256"]),
    )
    repair = _verify_repair(
        record.get("repair"), outcome=str(outcome), selected_mask_sha256=selected_mask_sha256
    )
    evidence = {
        "schema_version": "maskfactory.nude_record_qualification.v3",
        "sample_id": sample_id,
        "candidate_label": candidate_label,
        "source_sha256": source_sha256,
        "mask_sha256": selected_mask_sha256,
        "outcome": outcome,
        "provider_comparison": provider_comparison,
        "hard_qc": hard_qc,
        "panel_evidence": panel_evidence,
        "pixel_semantic_visual_evidence": pixel_semantic_evidence,
        "label_scale_hard_qc": label_scale_hard_qc,
        "ownership": ownership,
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
        "candidate_label": candidate_label,
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
    if evidence.get("schema_version") != "maskfactory.nude_record_qualification.v3":
        raise NudeRecordQualificationError("qualification_evidence_schema_invalid")
    for field in ("sample_id", "candidate_label", "source_sha256", "mask_sha256", "outcome"):
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
    pixel_semantic_evidence = evidence.get("pixel_semantic_visual_evidence")
    if not isinstance(pixel_semantic_evidence, Mapping):
        raise NudeRecordQualificationError("pixel_semantic_visual_evidence_required")
    original_source_path = pixel_semantic_evidence.get("original_source_path")
    if not isinstance(original_source_path, str) or not original_source_path:
        raise NudeRecordQualificationError("original_source_path_required")
    semantic_panels = {kind: dict(panels[kind]) for kind in REQUIRED_PANEL_KINDS}
    semantic_panels["source"]["original_source_path"] = original_source_path
    observed_semantic = _verify_pixel_semantic_evidence(evidence, semantic_panels)
    if dict(pixel_semantic_evidence) != observed_semantic:
        raise NudeRecordQualificationError("pixel_semantic_visual_evidence_drift")
    observed_scale = _verify_label_scale(
        panels, candidate_label=str(evidence.get("candidate_label") or "")
    )
    if evidence.get("label_scale_hard_qc") != observed_scale:
        raise NudeRecordQualificationError("label_scale_hard_qc_drift")
    _verify_ownership(
        evidence.get("ownership", {}),
        source_sha256=str(payload["source_sha256"]),
        selected_mask_sha256=str(payload["mask_sha256"]),
        acceptance_required=True,
    )
    _verify_provider_comparison(
        evidence.get("provider_comparison", {}),
        selected_mask_sha256=str(payload["mask_sha256"]),
        expected_person_index=int(evidence["ownership"]["person_index"]),
    )
    _verify_hard_qc(evidence.get("hard_qc", {}), selected_mask_sha256=str(payload["mask_sha256"]))
    _verify_strict_reviews(
        evidence.get("strict_reviews", ()),
        selected_mask_sha256=str(payload["mask_sha256"]),
        panel_bundle_sha256=str(panel_evidence.get("panel_bundle_sha256")),
        expected_person_index=int(evidence["ownership"]["person_index"]),
        ownership_report_sha256=str(evidence["ownership"]["report_sha256"]),
    )
    _verify_repair(
        evidence.get("repair"),
        outcome=str(payload["outcome"]),
        selected_mask_sha256=str(payload["mask_sha256"]),
    )
    return dict(payload)


def _verify_nonacceptance_reviews(
    reviews: Sequence[Mapping[str, Any]],
    *,
    selected_mask_sha256: str,
    panel_bundle_sha256: str,
    expected_person_index: int | None,
    ownership_report_sha256: str,
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
        verdict = review.get("verdict")
        if role not in REQUIRED_REVIEW_ROLES or role in roles:
            raise NudeRecordQualificationError("strict_review_role_quorum_invalid")
        if verdict not in {"pass", "fail", "uncertain"}:
            raise NudeRecordQualificationError("strict_review_verdict_invalid")
        if review.get("mask_sha256") != selected_mask_sha256:
            raise NudeRecordQualificationError("strict_review_mask_mismatch")
        if review.get("panel_bundle_sha256") != panel_bundle_sha256:
            raise NudeRecordQualificationError("strict_review_panel_bundle_mismatch")
        if review.get("person_index") != expected_person_index:
            raise NudeRecordQualificationError("strict_review_person_index_mismatch")
        if review.get("ownership_report_sha256") != ownership_report_sha256:
            raise NudeRecordQualificationError("strict_review_ownership_report_mismatch")
        evidence = _nonempty(review.get("evidence"), "strict_review_evidence")
        if evidence.strip().lower() in {"pass", "fail", "uncertain", "looks good", "ok"}:
            raise NudeRecordQualificationError("strict_review_rubber_stamp_rejected")
        family_id = _nonempty(review.get("family_id"), "strict_review_family_id")
        confidence = float(review.get("confidence", -1))
        if not 0 <= confidence <= 1:
            raise NudeRecordQualificationError("strict_review_confidence_invalid")
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
                "person_index": expected_person_index,
                "ownership_report_sha256": ownership_report_sha256,
                "verdict": verdict,
                "confidence": confidence,
                "evidence": evidence,
            }
        )
    if roles != REQUIRED_REVIEW_ROLES or len(families) != 2:
        raise NudeRecordQualificationError("independent_strict_review_quorum_required")
    return sorted(normalized, key=lambda row: row["role"])


def qualify_nonacceptance_record(
    record: Mapping[str, Any], *, panels: Mapping[str, Any]
) -> dict[str, Any]:
    """Create a full abstain/reject receipt without granting mask authority."""

    outcome = record.get("outcome")
    if outcome not in {"abstained", "rejected"}:
        raise NudeRecordQualificationError("nonacceptance_outcome_invalid")
    sample_id = _nonempty(record.get("sample_id"), "sample_id")
    candidate_label = _nonempty(record.get("candidate_label"), "candidate_label")
    source_sha256 = _sha256(record.get("source_sha256"), "source_sha256")
    selected_mask_sha256 = _sha256(record.get("mask_sha256"), "mask_sha256")
    failure_stage = record.get("failure_stage")
    if failure_stage not in FAILURE_STAGES:
        raise NudeRecordQualificationError("failure_stage_invalid")
    reasons = record.get("reasons")
    if (
        not isinstance(reasons, Sequence)
        or isinstance(reasons, (str, bytes))
        or not reasons
        or any(not isinstance(reason, str) or not reason.strip() for reason in reasons)
    ):
        raise NudeRecordQualificationError("failure_reasons_required")
    panel_evidence = verify_complete_panel_evidence(panels)
    pixel_semantic_evidence = _verify_pixel_semantic_evidence(record, panels)
    label_scale_hard_qc = _verify_label_scale(panels, candidate_label=candidate_label)
    ownership = _verify_ownership(
        record.get("ownership", {}),
        source_sha256=source_sha256,
        selected_mask_sha256=selected_mask_sha256,
        acceptance_required=False,
    )
    provider_comparison = _verify_provider_comparison(
        record.get("provider_comparison", {}),
        selected_mask_sha256=selected_mask_sha256,
        allowed_statuses=frozenset({"pass", "fail", "abstain"}),
        expected_person_index=ownership["person_index"],
    )
    if failure_stage == "provider_comparison" and provider_comparison["status"] == "pass":
        raise NudeRecordQualificationError("provider_failure_stage_requires_nonpass")
    reviews = _verify_nonacceptance_reviews(
        record.get("strict_reviews", ()),
        selected_mask_sha256=selected_mask_sha256,
        panel_bundle_sha256=panel_evidence["panel_bundle_sha256"],
        expected_person_index=ownership["person_index"],
        ownership_report_sha256=str(ownership["report_sha256"]),
    )
    verdicts = {review["verdict"] for review in reviews}
    if outcome == "abstained" and "uncertain" not in verdicts:
        raise NudeRecordQualificationError("abstain_requires_uncertain_review")
    if outcome == "rejected" and failure_stage == "strict_review" and "fail" not in verdicts:
        raise NudeRecordQualificationError("strict_review_reject_requires_fail")
    hard_qc = record.get("hard_qc")
    if not isinstance(hard_qc, Mapping) or hard_qc.get("status") not in {"pass", "fail"}:
        raise NudeRecordQualificationError("hard_qc_status_invalid")
    if hard_qc.get("mask_sha256") != selected_mask_sha256:
        raise NudeRecordQualificationError("hard_qc_mask_mismatch")
    hard_qc_evidence = {
        "status": hard_qc["status"],
        "mask_sha256": selected_mask_sha256,
        "policy_sha256": _sha256(hard_qc.get("policy_sha256"), "hard_qc_policy_sha256"),
        "report_sha256": _sha256(hard_qc.get("report_sha256"), "hard_qc_report_sha256"),
    }
    if failure_stage == "hard_qc" and hard_qc_evidence["status"] != "fail":
        raise NudeRecordQualificationError("hard_qc_failure_stage_requires_veto")
    repair = record.get("repair")
    repair_evidence = None
    if failure_stage == "repair_exhausted":
        if not isinstance(repair, Mapping):
            raise NudeRecordQualificationError("repair_exhaustion_evidence_required")
        attempts = repair.get("attempts")
        maximum = repair.get("max_attempts")
        if (
            not isinstance(attempts, int)
            or isinstance(attempts, bool)
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or attempts != maximum
            or not 1 <= maximum <= 3
        ):
            raise NudeRecordQualificationError("repair_exhaustion_invalid")
        repair_evidence = {
            "attempts": attempts,
            "max_attempts": maximum,
            "last_parent_mask_sha256": _sha256(
                repair.get("last_parent_mask_sha256"), "repair_parent_mask_sha256"
            ),
            "last_candidate_mask_sha256": selected_mask_sha256,
            "repair_policy_sha256": _sha256(
                repair.get("repair_policy_sha256"), "repair_policy_sha256"
            ),
            "repair_report_sha256": _sha256(
                repair.get("repair_report_sha256"), "repair_report_sha256"
            ),
        }
    evidence = {
        "schema_version": "maskfactory.nude_record_nonacceptance.v3",
        "sample_id": sample_id,
        "candidate_label": candidate_label,
        "source_sha256": source_sha256,
        "mask_sha256": selected_mask_sha256,
        "outcome": outcome,
        "failure_stage": failure_stage,
        "reasons": sorted(set(reasons)),
        "provider_comparison": provider_comparison,
        "hard_qc": hard_qc_evidence,
        "panel_evidence": panel_evidence,
        "pixel_semantic_visual_evidence": pixel_semantic_evidence,
        "label_scale_hard_qc": label_scale_hard_qc,
        "ownership": ownership,
        "strict_reviews": reviews,
        "repair": repair_evidence,
        "authority": "no_mask_authority",
        "human_gold": False,
        "production_mask_authority": False,
        "operational_certificate_issued": False,
    }
    evidence_sha256 = _canonical_sha256(evidence)
    return {
        "sample_id": sample_id,
        "candidate_label": candidate_label,
        "source_sha256": source_sha256,
        "mask_sha256": selected_mask_sha256,
        "outcome": outcome,
        "evidence_sha256": evidence_sha256,
        "qualification_evidence": evidence,
    }


def validate_nonacceptance_queue_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute an abstain/reject receipt before durable queue mutation."""

    if payload.get("outcome") not in {"abstained", "rejected"}:
        raise NudeRecordQualificationError("nonacceptance_queue_outcome_invalid")
    evidence = payload.get("qualification_evidence")
    if not isinstance(evidence, Mapping):
        raise NudeRecordQualificationError("qualification_evidence_required")
    panels = evidence.get("panel_evidence", {}).get("panels")
    if not isinstance(panels, Mapping):
        raise NudeRecordQualificationError("qualification_panels_invalid")
    pixel_semantic_evidence = evidence.get("pixel_semantic_visual_evidence")
    if not isinstance(pixel_semantic_evidence, Mapping):
        raise NudeRecordQualificationError("pixel_semantic_visual_evidence_required")
    original_source_path = pixel_semantic_evidence.get("original_source_path")
    if not isinstance(original_source_path, str) or not original_source_path:
        raise NudeRecordQualificationError("original_source_path_required")
    semantic_panels = {kind: dict(panels[kind]) for kind in REQUIRED_PANEL_KINDS}
    semantic_panels["source"]["original_source_path"] = original_source_path
    rebuilt = qualify_nonacceptance_record(
        {
            "sample_id": evidence.get("sample_id"),
            "candidate_label": evidence.get("candidate_label"),
            "source_sha256": evidence.get("source_sha256"),
            "mask_sha256": evidence.get("mask_sha256"),
            "outcome": evidence.get("outcome"),
            "failure_stage": evidence.get("failure_stage"),
            "reasons": evidence.get("reasons"),
            "provider_comparison": evidence.get("provider_comparison"),
            "hard_qc": evidence.get("hard_qc"),
            "strict_reviews": evidence.get("strict_reviews"),
            "repair": evidence.get("repair"),
            "ownership": evidence.get("ownership"),
        },
        panels=semantic_panels,
    )
    if dict(evidence) != rebuilt["qualification_evidence"]:
        raise NudeRecordQualificationError("nonacceptance_evidence_drift")
    for field in (
        "sample_id",
        "candidate_label",
        "source_sha256",
        "mask_sha256",
        "outcome",
        "evidence_sha256",
    ):
        if payload.get(field) != rebuilt.get(field):
            raise NudeRecordQualificationError(f"nonacceptance_{field}_mismatch")
    return dict(payload)


def qualify_input_terminal_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Bind an input quarantine or isolated holdout without fabricating mask evidence."""

    outcome = record.get("outcome")
    if outcome not in {"quarantined", "holdout"}:
        raise NudeRecordQualificationError("input_terminal_outcome_invalid")
    sample_id = _nonempty(record.get("sample_id"), "sample_id")
    source_sha256 = _sha256(record.get("source_sha256"), "source_sha256")
    source_role = _nonempty(record.get("source_role"), "source_role")
    registry_sha256 = _sha256(record.get("registry_sha256"), "registry_sha256")
    shard_sha256 = _sha256(record.get("shard_sha256"), "shard_sha256")
    reasons = record.get("reasons")
    if (
        not isinstance(reasons, Sequence)
        or isinstance(reasons, (str, bytes))
        or not reasons
        or any(not isinstance(reason, str) or not reason.strip() for reason in reasons)
    ):
        raise NudeRecordQualificationError("input_terminal_reasons_required")
    evidence: dict[str, Any] = {
        "schema_version": "maskfactory.nude_input_terminal.v1",
        "sample_id": sample_id,
        "source_sha256": source_sha256,
        "source_role": source_role,
        "registry_sha256": registry_sha256,
        "shard_sha256": shard_sha256,
        "outcome": outcome,
        "reasons": sorted(set(reasons)),
        "input_report_sha256": _sha256(record.get("input_report_sha256"), "input_report_sha256"),
        "mask_generated": False,
        "training_authority": False,
        "production_mask_authority": False,
    }
    if outcome == "holdout":
        if source_role != "bbox_evaluation_only":
            raise NudeRecordQualificationError("holdout_source_role_invalid")
        evidence["holdout_policy_sha256"] = _sha256(
            record.get("holdout_policy_sha256"), "holdout_policy_sha256"
        )
        evidence["split_group_id"] = _nonempty(record.get("split_group_id"), "split_group_id")
        evidence["evaluation_only"] = True
    else:
        if record.get("holdout_policy_sha256") is not None:
            raise NudeRecordQualificationError("quarantine_cannot_claim_holdout_policy")
        evidence["evaluation_only"] = False
    evidence_sha256 = _canonical_sha256(evidence)
    return {
        "sample_id": sample_id,
        "source_sha256": source_sha256,
        "outcome": outcome,
        "evidence_sha256": evidence_sha256,
        "qualification_evidence": evidence,
    }


def validate_input_terminal_queue_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute a quarantine/holdout receipt before durable queue mutation."""

    evidence = payload.get("qualification_evidence")
    if not isinstance(evidence, Mapping):
        raise NudeRecordQualificationError("qualification_evidence_required")
    rebuilt = qualify_input_terminal_record(evidence)
    if dict(evidence) != rebuilt["qualification_evidence"]:
        raise NudeRecordQualificationError("input_terminal_evidence_drift")
    for field in ("sample_id", "source_sha256", "outcome", "evidence_sha256"):
        if payload.get(field) != rebuilt.get(field):
            raise NudeRecordQualificationError(f"input_terminal_{field}_mismatch")
    return dict(payload)


__all__ = [
    "NudeRecordQualificationError",
    "FAILURE_STAGES",
    "REQUIRED_PANEL_KINDS",
    "REQUIRED_REVIEW_ROLES",
    "qualify_terminal_record",
    "qualify_nonacceptance_record",
    "qualify_input_terminal_record",
    "validate_input_terminal_queue_payload",
    "validate_nonacceptance_queue_payload",
    "validate_qualified_queue_payload",
    "verify_complete_panel_evidence",
]
