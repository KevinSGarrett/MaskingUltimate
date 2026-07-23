"""Bridge qualified adult-corpus records into RunPod work-cell stage artifacts.

The adult-corpus queue already has rich per-record evidence for provider
comparison, deterministic hard-QA, five-view visual evidence, ownership, and
strict-review votes.  The autonomous work-cell uses a smaller stage artifact
contract.  This module maps the former to the latter without inventing missing
authority.

Package freeze and certification artifacts are emitted only when exact package
and certificate hashes are supplied by their real stage tools.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from ..nude_record_qualification import validate_qualified_queue_payload


class NudeWorkCellBridgeError(ValueError):
    """A nude-corpus qualification record cannot be represented as work-cell evidence."""


def canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise NudeWorkCellBridgeError(f"{field}_sha256_required")
    try:
        int(value, 16)
    except ValueError as exc:
        raise NudeWorkCellBridgeError(f"{field}_sha256_required") from exc
    return value


def _candidate_count(comparison: Mapping[str, Any]) -> int:
    candidates = comparison.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise NudeWorkCellBridgeError("provider_candidates_required")
    return len(candidates)


def _family_count(comparison: Mapping[str, Any]) -> int:
    candidates = comparison.get("candidates")
    if not isinstance(candidates, list):
        raise NudeWorkCellBridgeError("provider_candidates_required")
    families = {
        candidate.get("family_id") for candidate in candidates if isinstance(candidate, Mapping)
    }
    families.discard(None)
    if not families:
        raise NudeWorkCellBridgeError("provider_families_required")
    return len(families)


def _review(evidence: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    reviews = evidence.get("strict_reviews")
    if not isinstance(reviews, list):
        raise NudeWorkCellBridgeError("strict_reviews_required")
    matches = [
        review for review in reviews if isinstance(review, Mapping) and review.get("role") == role
    ]
    if len(matches) != 1:
        raise NudeWorkCellBridgeError(f"{role}_review_required")
    return matches[0]


def _source_decode_artifact(evidence: Mapping[str, Any]) -> dict[str, Any]:
    pixel = evidence.get("pixel_semantic_visual_evidence")
    if not isinstance(pixel, Mapping):
        raise NudeWorkCellBridgeError("pixel_semantic_visual_evidence_required")
    geometry = pixel.get("source_geometry")
    if (
        not isinstance(geometry, list)
        or len(geometry) != 2
        or not all(isinstance(value, int) and value > 0 for value in geometry)
    ):
        raise NudeWorkCellBridgeError("source_geometry_invalid")
    return {
        "schema_version": "maskfactory.runpod_stage.source_decode.v1",
        "work_cell_status": "pass",
        "decoded_pixel_sha256": _sha(
            pixel.get("decoded_source_pixels_sha256"), "decoded_source_pixels"
        ),
        "alpha_policy": "absent",
        "width": int(geometry[1]),
        "height": int(geometry[0]),
        "nude_record_qualification_sha256": _sha(evidence.get("evidence_sha256"), "evidence"),
    }


def _detection_ownership_artifact(
    evidence: Mapping[str, Any], *, target_contract_sha256: str
) -> dict[str, Any]:
    ownership = evidence.get("ownership")
    if not isinstance(ownership, Mapping):
        raise NudeWorkCellBridgeError("ownership_evidence_required")
    person_index = ownership.get("person_index")
    status = ownership.get("status")
    return {
        "schema_version": "maskfactory.runpod_stage.detection_ownership.v1",
        "work_cell_status": "pass" if status == "verified" else "repairable",
        "target_contract_sha256": _sha(target_contract_sha256, "target_contract"),
        "person_count": max(int(person_index) + 1 if isinstance(person_index, int) else 1, 1),
        "ownership_status": "verified" if status == "verified" else "ambiguous",
        "ownership_report_sha256": _sha(ownership.get("report_sha256"), "ownership_report"),
    }


def _provider_tournament_artifact(evidence: Mapping[str, Any]) -> dict[str, Any]:
    comparison = evidence.get("provider_comparison")
    if not isinstance(comparison, Mapping):
        raise NudeWorkCellBridgeError("provider_comparison_required")
    status = comparison.get("status")
    artifact = {
        "schema_version": "maskfactory.runpod_stage.provider_tournament.v1",
        "work_cell_status": "pass" if status == "pass" else "repairable",
        "tournament_report_sha256": _sha(comparison.get("report_sha256"), "tournament_report"),
        "family_count": _family_count(comparison),
        "candidate_count": _candidate_count(comparison),
    }
    if status == "pass":
        artifact["winner_mask_sha256"] = _sha(comparison.get("selected_mask_sha256"), "winner_mask")
    return artifact


def _hard_qc_artifact(evidence: Mapping[str, Any]) -> dict[str, Any]:
    hard_qc = evidence.get("hard_qc")
    if not isinstance(hard_qc, Mapping):
        raise NudeWorkCellBridgeError("hard_qc_required")
    status = hard_qc.get("status")
    return {
        "schema_version": "maskfactory.runpod_stage.hard_qc.v1",
        "work_cell_status": "pass" if status == "pass" else "repairable",
        "qa_vector_sha256": _sha(hard_qc.get("report_sha256"), "hard_qc_report"),
        "hard_veto_count": 0 if status == "pass" else 1,
    }


def _visual_artifact(evidence: Mapping[str, Any], *, stage: str, role: str) -> dict[str, Any]:
    review = _review(evidence, role)
    verdict = review.get("verdict")
    return {
        "schema_version": f"maskfactory.runpod_stage.{stage}.v1",
        "work_cell_status": "pass" if verdict == "pass" else "repairable",
        "panel_sha256": _sha(review.get("panel_bundle_sha256"), "panel_bundle"),
        "critic_report_sha256": canonical_sha256(dict(review)),
        "verdict": "pass" if verdict == "pass" else "repairable",
        "role_certificate_sha256": _sha(review.get("certificate_sha256"), "role_certificate"),
    }


def build_work_cell_artifacts_from_nude_qualified_record(
    payload: Mapping[str, Any],
    *,
    target_contract_sha256: str,
    package_sha256: str | None = None,
    certificate_sha256: str | None = None,
    authority_tier: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Convert one validated nude queue terminal receipt to work-cell artifacts.

    The returned mapping may stop at independent visual review.  Package and
    certification stages are included only when their exact hashes are provided.
    """

    qualified = validate_qualified_queue_payload(payload)
    evidence = dict(qualified["qualification_evidence"])
    evidence["evidence_sha256"] = qualified["evidence_sha256"]
    artifacts = {
        "source_decode": _source_decode_artifact(evidence),
        "detection_ownership": _detection_ownership_artifact(
            evidence, target_contract_sha256=target_contract_sha256
        ),
        "provider_tournament": _provider_tournament_artifact(evidence),
        "hard_qc": _hard_qc_artifact(evidence),
        "primary_visual_review": _visual_artifact(
            evidence, stage="primary_visual_review", role="primary_visual_critic"
        ),
        "independent_visual_review": _visual_artifact(
            evidence, stage="independent_visual_review", role="independent_juror"
        ),
    }
    if package_sha256 is not None:
        artifacts["package_freeze"] = {
            "schema_version": "maskfactory.runpod_stage.package_freeze.v1",
            "work_cell_status": "pass",
            "package_sha256": _sha(package_sha256, "package"),
            "active_label_count": 1,
        }
    if certificate_sha256 is not None or authority_tier is not None:
        if certificate_sha256 is None or authority_tier is None:
            raise NudeWorkCellBridgeError("certificate_hash_and_authority_tier_required")
        artifacts["certification"] = {
            "schema_version": "maskfactory.runpod_stage.certification.v1",
            "work_cell_status": "pass",
            "certificate_sha256": _sha(certificate_sha256, "certificate"),
            "authority_tier": authority_tier,
        }
    return artifacts


__all__ = [
    "NudeWorkCellBridgeError",
    "build_work_cell_artifacts_from_nude_qualified_record",
    "canonical_sha256",
]
