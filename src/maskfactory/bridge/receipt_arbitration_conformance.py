"""Producer-side Mode A/Mode B receipt arbitration conformance oracle.

Main owns routing choice/branch/abstention signatures. This module consumes
shared ``mask_acquisition_receipt`` fields, recomputes exact-scope eligibility
and normalized ranking under a pinned policy, and validates a Main decision
without executing or signing controller routes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from jsonschema import Draft202012Validator

from maskfactory.validation import canonical_document_sha256

POLICY_PATH = (
    Path(__file__).parents[3] / "configs" / "bridge_receipt_arbitration_conformance_policy.yaml"
)
SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "receipt_arbitration_conformance_evidence.schema.json"
)
POLICY_ID = "maskfactory-bridge-receipt-arbitration-conformance-v1"

_MODE_A = "mode_a_package_read"
_MODE_B = frozenset({"mode_b_live_predict", "mode_b_live_refine"})
_DRAFT_OR_WEAKER = frozenset({"invalid", "hypothesis", "draft"})


class ReceiptArbitrationConformanceError(ValueError):
    """Arbitration policy or inputs are unavailable or malformed."""


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ReceiptArbitrationConformanceError("receipt arbitration policy unavailable") from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise ReceiptArbitrationConformanceError("unexpected receipt arbitration policy")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise ReceiptArbitrationConformanceError("receipt arbitration policy hash mismatch")
    codes = policy.get("reason_codes")
    if not isinstance(codes, list) or not codes or len(codes) != len(set(codes)):
        raise ReceiptArbitrationConformanceError("receipt arbitration policy is not closed")
    return dict(policy)


def _ordered(policy: Mapping[str, Any], reasons: Sequence[str]) -> list[str]:
    return [code for code in policy["reason_codes"] if code in set(reasons)] or ["eligible"]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _region_fingerprint(regions: object) -> list[dict[str, Any]]:
    rows = [row for row in regions or () if isinstance(row, Mapping)]
    fingerprint = [
        {
            "region_id": row.get("region_id"),
            "artifact_identity_sha256": row.get("artifact_identity_sha256"),
            "decoded_mask_sha256": row.get("decoded_mask_sha256"),
            "coordinate_space": row.get("coordinate_space"),
            "required_minimum_authority_state": row.get("required_minimum_authority_state"),
        }
        for row in rows
    ]
    return sorted(fingerprint, key=lambda row: json.dumps(row, sort_keys=True))


def _artifact_fingerprint(artifacts: object) -> list[dict[str, Any]]:
    rows = [row for row in artifacts or () if isinstance(row, Mapping)]
    fingerprint = [
        {
            "intent_id": row.get("intent_id"),
            "label": row.get("label"),
            "artifact_kind": row.get("artifact_kind"),
            "mask_type": row.get("mask_type"),
            "coordinate_space": row.get("coordinate_space"),
            "decoded_mask_sha256": row.get("decoded_mask_sha256"),
        }
        for row in rows
    ]
    return sorted(fingerprint, key=lambda row: json.dumps(row, sort_keys=True))


def comparable_scope_identity(
    receipt: Mapping[str, Any], *, ontology_version: str
) -> dict[str, Any]:
    """Build the closed exact-scope identity used before any ranking."""
    media = _mapping(receipt.get("media_scope"))
    source = _mapping(receipt.get("source_binding"))
    subject = _mapping(receipt.get("subject_binding"))
    transform = _mapping(receipt.get("transform_validation"))
    lineage = _mapping(receipt.get("lineage"))
    use = _mapping(receipt.get("use_eligibility"))
    return {
        "project_id": receipt.get("project_id"),
        "run_id": receipt.get("run_id"),
        "job_id": receipt.get("job_id"),
        "pass_id": receipt.get("pass_id"),
        "ontology_version": ontology_version,
        "media_scope": {
            "scope_kind": media.get("scope_kind"),
            "sequence_id": media.get("sequence_id"),
            "shot_id": media.get("shot_id"),
            "take_id": media.get("take_id"),
            "source_video_sha256": media.get("source_video_sha256"),
            "decoded_frame_sha256": media.get("decoded_frame_sha256"),
            "frame_index": media.get("frame_index"),
        },
        "source_decoded_pixel_sha256": source.get("decoded_pixel_sha256"),
        "subject_binding": {
            "character_id": subject.get("character_id"),
            "character_revision": subject.get("character_revision"),
            "scene_instance_id": subject.get("scene_instance_id"),
            "canonical_person_id": subject.get("canonical_person_id"),
            "person_index": subject.get("person_index"),
        },
        "transform_chain_sha256": transform.get("transform_chain_sha256"),
        "output_coordinate_space": transform.get("output_coordinate_space"),
        "target_regions": _region_fingerprint(lineage.get("input_target_regions")),
        "protected_regions": _region_fingerprint(lineage.get("input_protected_regions")),
        "artifacts": _artifact_fingerprint(receipt.get("artifacts")),
        "exact_use_scope": use.get("exact_use_scope"),
        "required_authority_state": use.get("required_authority_state"),
    }


def comparable_scope_sha256(receipt: Mapping[str, Any], *, ontology_version: str) -> str:
    return canonical_document_sha256(
        comparable_scope_identity(receipt, ontology_version=ontology_version)
    )


def _is_wrapper_certified_mode_a(receipt: Mapping[str, Any]) -> bool:
    lineage = _mapping(receipt.get("lineage"))
    authority = _mapping(receipt.get("authority"))
    return (
        receipt.get("access_mode") == _MODE_A
        and lineage.get("operation_kind") == "package_read"
        and lineage.get("package_certificate_status") == "active"
        and lineage.get("package_certificate_exact_scope_match") is True
        and authority.get("authority_state") == "certified"
        and authority.get("certificate_status") == "active"
        and authority.get("certificate_exact_scope_match") is True
    )


def _is_uncertified_mode_b_draft(receipt: Mapping[str, Any]) -> bool:
    authority = _mapping(receipt.get("authority"))
    return (
        receipt.get("access_mode") in _MODE_B
        and authority.get("authority_state") in _DRAFT_OR_WEAKER
    )


def _has_incompatible_latent(receipt: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    forbidden = set(policy.get("forbidden_representation_classes") or ())
    allowed_kinds = set(policy.get("allowed_artifact_kinds") or ())
    for row in receipt.get("artifacts") or ():
        if not isinstance(row, Mapping):
            return True
        kind = row.get("artifact_kind")
        representation = row.get("representation_class")
        if representation in forbidden:
            return True
        if isinstance(kind, str) and ("latent" in kind.lower()):
            return True
        if allowed_kinds and kind not in allowed_kinds:
            return True
    return False


def _normalize_freshness(
    *,
    completed_at: object,
    decided_at: str,
    max_age_seconds: int,
) -> float | None:
    completed = _parse_time(completed_at)
    decided = _parse_time(decided_at)
    if completed is None or decided is None or decided < completed:
        return None
    age = (decided - completed).total_seconds()
    if age > max_age_seconds:
        return None
    return max(0.0, 1.0 - (age / float(max_age_seconds)))


def _score_cost(total_ms: object, peak_vram_mb: object, policy: Mapping[str, Any]) -> float | None:
    cost = policy["cost"]
    if not isinstance(total_ms, int) or total_ms < 0:
        return None
    if not isinstance(peak_vram_mb, int) or peak_vram_mb < 0:
        return None
    time_score = max(0.0, 1.0 - (total_ms / float(cost["reference_total_ms"])))
    vram_score = max(0.0, 1.0 - (peak_vram_mb / float(cost["reference_peak_vram_mb"])))
    return (time_score + vram_score) / 2.0


def _evaluate_candidate(
    candidate: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    producer_heads: Mapping[str, Any],
    decided_at: str,
    expected_scope_sha256: str | None,
) -> dict[str, Any]:
    receipt = _mapping(candidate.get("receipt"))
    authority = _mapping(receipt.get("authority"))
    qa = _mapping(receipt.get("qa"))
    execution = _mapping(receipt.get("execution_observation"))
    resources = _mapping(execution.get("resources"))
    release = _mapping(receipt.get("release_binding"))
    reasons: list[str] = []

    ontology = producer_heads.get("ontology_version")
    if not isinstance(ontology, str) or not ontology:
        reasons.append("producer_head_mismatch")
        ontology = ""
    scope_sha = (
        comparable_scope_sha256(receipt, ontology_version=ontology) if ontology else ("0" * 64)
    )
    if expected_scope_sha256 is not None and scope_sha != expected_scope_sha256:
        reasons.append("incompatible_scope")

    if receipt.get("result") != "succeeded":
        reasons.append("candidate_ineligible")
    if _has_incompatible_latent(receipt, policy):
        reasons.append("incompatible_latent")

    ranks = policy["authority_rank"]
    observed_authority = authority.get("authority_state")
    floor = producer_heads.get("required_authority_floor")
    if (
        observed_authority not in ranks
        or floor not in ranks
        or ranks[observed_authority] < ranks[floor]
    ):
        reasons.append("authority_insufficient")

    required_qa = producer_heads.get("required_qa_status")
    qa_ranks = policy["qa_status_rank"]
    if qa.get("status") not in qa_ranks or required_qa not in qa_ranks:
        reasons.append("qa_not_passed")
    elif qa_ranks[qa["status"]] < qa_ranks[required_qa]:
        reasons.append("qa_not_passed")
    uncertainty = qa.get("uncertainty")
    max_uncertainty = producer_heads.get("max_uncertainty")
    if not isinstance(uncertainty, (int, float)) or not isinstance(max_uncertainty, (int, float)):
        reasons.append("qa_not_passed")
    elif float(uncertainty) > float(max_uncertainty):
        reasons.append("qa_not_passed")

    if release.get("release_payload_sha256") != producer_heads.get("release_payload_sha256"):
        reasons.append("producer_head_mismatch")
    if release.get("capability_snapshot_sha256") != producer_heads.get(
        "capability_snapshot_sha256"
    ):
        reasons.append("producer_head_mismatch")
    if authority.get("revocation_index_sha256") not in {
        None,
        producer_heads.get("revocation_index_sha256"),
    }:
        # drafts may omit revocation; certified/active paths must match current head
        if authority.get("certificate_status") in {"active", "revoked", "expired", "superseded"}:
            if authority.get("revocation_index_sha256") != producer_heads.get(
                "revocation_index_sha256"
            ):
                reasons.append("producer_head_mismatch")
    if authority.get("certificate_status") == "revoked":
        reasons.append("candidate_ineligible")

    freshness = _normalize_freshness(
        completed_at=receipt.get("completed_at"),
        decided_at=decided_at,
        max_age_seconds=int(policy["freshness"]["max_age_seconds"]),
    )
    if freshness is None:
        reasons.append("freshness_stale")

    risk = candidate.get("preservation_risk")
    risk_policy = policy["preservation_risk"]
    if not isinstance(risk, (int, float)) or not (
        float(risk_policy["minimum"]) <= float(risk) <= float(risk_policy["maximum"])
    ):
        reasons.append("preservation_risk_missing_or_invalid")
        risk = None
    elif float(risk) > float(producer_heads.get("max_preservation_risk")):
        reasons.append("preservation_risk_exceeds_budget")

    total_ms = execution.get("total_ms")
    peak_vram = resources.get("peak_vram_mb")
    cost_score = _score_cost(total_ms, peak_vram, policy)
    if cost_score is None:
        reasons.append("cost_missing_or_invalid")
    else:
        if isinstance(total_ms, int) and total_ms > int(producer_heads.get("max_total_ms")):
            reasons.append("cost_exceeds_budget")
        if isinstance(peak_vram, int) and peak_vram > int(producer_heads.get("max_peak_vram_mb")):
            reasons.append("cost_exceeds_budget")

    # Mode A access/status alone never invents certified rank.
    access_bonus = 0.0
    if (
        policy["dominance"]["mode_a_access_alone_grants_no_rank"]
        and receipt.get("access_mode") == _MODE_A
        and not _is_wrapper_certified_mode_a(receipt)
    ):
        access_bonus = 0.0

    authority_score = float(ranks.get(observed_authority, 0)) / float(max(ranks.values()) or 1)
    qa_score = float(qa_ranks.get(qa.get("status"), 0)) / float(max(qa_ranks.values()) or 1)
    preservation_safety = None if risk is None else max(0.0, 1.0 - float(risk))

    receipt_hash = candidate.get("receipt_payload_sha256")
    if not isinstance(receipt_hash, str):
        receipt_hash = receipt.get("receipt_payload_sha256")
    if not isinstance(receipt_hash, str):
        reasons.append("receipt_binding_mismatch")
        receipt_hash = "0" * 64

    ordered_reasons = _ordered(policy, reasons)
    eligible = ordered_reasons == ["eligible"]
    return {
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "receipt": receipt,
        "receipt_payload_sha256": receipt_hash,
        "access_mode": str(receipt.get("access_mode") or ""),
        "authority_state": str(observed_authority or "invalid"),
        "comparable_scope_sha256": scope_sha,
        "eligible": eligible,
        "ineligibility_reasons": [] if eligible else ordered_reasons,
        "scores": {
            "authority": authority_score + access_bonus,
            "qa": qa_score,
            "freshness": 0.0 if freshness is None else freshness,
            "preservation_safety": 0.0 if preservation_safety is None else preservation_safety,
            "cost_efficiency": 0.0 if cost_score is None else cost_score,
        },
        "wrapper_certified_mode_a": _is_wrapper_certified_mode_a(receipt),
        "uncertified_mode_b_draft": _is_uncertified_mode_b_draft(receipt),
    }


def _composite(scores: Mapping[str, float], policy: Mapping[str, Any]) -> float:
    total = 0.0
    weight_sum = 0.0
    for name, spec in policy["dimensions"].items():
        weight = float(spec["weight"])
        value = float(scores[name])
        total += weight * value
        weight_sum += weight
    return total / weight_sum if weight_sum else 0.0


def _arbitrate(
    evaluated: Sequence[Mapping[str, Any]], *, policy: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, Any]]]:
    eligible = [row for row in evaluated if row["eligible"]]
    dominance: list[dict[str, str]] = []
    if policy["dominance"]["wrapper_certified_mode_a_beats_uncertified_mode_b_draft"] and any(
        row["wrapper_certified_mode_a"] for row in eligible
    ):
        kept: list[Mapping[str, Any]] = []
        for row in eligible:
            if row["uncertified_mode_b_draft"]:
                dominance.append(
                    {
                        "candidate_id": row["candidate_id"],
                        "reason": "wrapper_mode_a_dominates_draft",
                    }
                )
            else:
                kept.append(row)
        eligible = list(kept)

    score_rows: list[dict[str, Any]] = []
    for row in eligible:
        composite = _composite(row["scores"], policy)
        score_rows.append(
            {
                "candidate_id": row["candidate_id"],
                "authority": row["scores"]["authority"],
                "qa": row["scores"]["qa"],
                "freshness": row["scores"]["freshness"],
                "preservation_safety": row["scores"]["preservation_safety"],
                "cost_efficiency": row["scores"]["cost_efficiency"],
                "composite": composite,
            }
        )
    score_rows.sort(key=lambda row: (-row["composite"], row["candidate_id"]))

    if not score_rows:
        return (
            {
                "outcome": "abstain",
                "selected_candidate_ids": [],
                "reason_codes": ["no_eligible_candidates"],
            },
            dominance,
            score_rows,
        )

    top = score_rows[0]["composite"]
    epsilon = float(policy["ambiguity"]["score_epsilon"])
    close = [row for row in score_rows if abs(row["composite"] - top) <= epsilon]
    # Authority/QA hard guards: never prefer cheaper/newer weaker authority.
    if policy["dominance"]["cost_cannot_overcome_authority_or_qa"] and len(close) > 1:
        best_authority = max(row["authority"] for row in close)
        best_qa = max(row["qa"] for row in close)
        close = [
            row
            for row in close
            if abs(row["authority"] - best_authority) <= epsilon
            and abs(row["qa"] - best_qa) <= epsilon
        ]

    close_ids = sorted(row["candidate_id"] for row in close)
    max_branch = int(policy["ambiguity"]["max_branch_alternatives"])
    if len(close_ids) == 1:
        oracle = {
            "outcome": "choose",
            "selected_candidate_ids": close_ids,
            "reason_codes": ["eligible"],
        }
    elif len(close_ids) <= max_branch:
        oracle = {
            "outcome": "branch",
            "selected_candidate_ids": close_ids,
            "reason_codes": ["close_alternatives_branch"],
        }
    else:
        oracle = {
            "outcome": "abstain",
            "selected_candidate_ids": [],
            "reason_codes": ["close_alternatives_abstain"],
        }
    return oracle, dominance, score_rows


def normalize_and_arbitrate_receipts(
    candidates: Sequence[Mapping[str, Any]],
    *,
    decided_at: str,
    producer_heads: Mapping[str, Any],
    pinned_comparable_scope_sha256: str | None = None,
) -> dict[str, Any]:
    """Normalize eligible receipts and deterministically choose, branch, or abstain."""
    policy = _policy()
    if not candidates:
        raise ReceiptArbitrationConformanceError("candidates required")
    if len({str(row.get("candidate_id")) for row in candidates}) != len(candidates):
        raise ReceiptArbitrationConformanceError("candidate_id values must be unique")

    ontology = producer_heads.get("ontology_version")
    if not isinstance(ontology, str) or not ontology:
        raise ReceiptArbitrationConformanceError("producer ontology_version required")

    scope_hashes = {
        comparable_scope_sha256(_mapping(row.get("receipt")), ontology_version=ontology)
        for row in candidates
    }
    scope_sha256 = pinned_comparable_scope_sha256
    if scope_sha256 is None:
        if len(scope_hashes) != 1:
            raise ReceiptArbitrationConformanceError(
                "incompatible scopes cannot be ranked together"
            )
        scope_sha256 = next(iter(scope_hashes))

    evaluated = [
        _evaluate_candidate(
            row,
            policy=policy,
            producer_heads=producer_heads,
            decided_at=decided_at,
            expected_scope_sha256=scope_sha256,
        )
        for row in candidates
    ]
    # Order-invariant evaluation: sort by candidate_id before arbitration.
    evaluated.sort(key=lambda row: row["candidate_id"])
    oracle, dominance, scores = _arbitrate(evaluated, policy=policy)
    return {
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "comparable_scope_sha256": scope_sha256,
        "evaluated": evaluated,
        "oracle_decision": oracle,
        "dominance_eliminations": dominance,
        "normalized_scores": scores,
    }


def build_receipt_arbitration_conformance_evidence(
    candidates: Sequence[Mapping[str, Any]],
    main_decision: Mapping[str, Any] | None,
    *,
    decided_at: str,
    producer_heads: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a Main arbitration decision against the producer-side oracle."""
    policy = _policy()
    reasons: list[str] = []
    main = main_decision if isinstance(main_decision, Mapping) else {}
    main_scope = main.get("comparable_scope_sha256")
    if not isinstance(main_scope, str):
        main_scope = None
        reasons.append("main_decision_missing_or_malformed")

    try:
        arbitration = normalize_and_arbitrate_receipts(
            candidates,
            decided_at=decided_at,
            producer_heads=producer_heads,
            pinned_comparable_scope_sha256=main_scope,
        )
    except ReceiptArbitrationConformanceError as exc:
        raise ReceiptArbitrationConformanceError(str(exc)) from exc

    evaluated = arbitration["evaluated"]
    oracle = arbitration["oracle_decision"]
    signature = _mapping(main.get("signature"))
    signature_present = all(
        isinstance(signature.get(field), str) and signature.get(field)
        for field in ("key_id", "public_key_base64", "signed_payload_sha256", "value_base64")
    )
    if not signature_present:
        reasons.append("main_signature_missing")

    if main.get("policy_sha256") != policy["policy_sha256"]:
        reasons.append("main_decision_disagrees")
    if main.get("comparable_scope_sha256") != arbitration["comparable_scope_sha256"]:
        reasons.append("incompatible_scope")

    main_receipts = main.get("receipt_payload_sha256s")
    expected_receipts = sorted({row["receipt_payload_sha256"] for row in evaluated})
    if not isinstance(main_receipts, list) or sorted(main_receipts) != expected_receipts:
        reasons.append("receipt_binding_mismatch")

    main_outcome = main.get("outcome")
    main_selected = main.get("selected_candidate_ids")
    if main_outcome not in set(policy["main_decision_outcomes"]):
        reasons.append("main_decision_missing_or_malformed")
        main_outcome = None
    if not isinstance(main_selected, list) or not all(
        isinstance(item, str) for item in main_selected
    ):
        reasons.append("main_decision_missing_or_malformed")
        main_selected = []
    else:
        main_selected = list(main_selected)

    if main_outcome != oracle["outcome"] or sorted(main_selected) != sorted(
        oracle["selected_candidate_ids"]
    ):
        reasons.append("main_decision_disagrees")

    # Silent weakening: Main may not select an ineligible or dominated candidate.
    eligible_ids = {row["candidate_id"] for row in evaluated if row["eligible"]}
    dominated = {row["candidate_id"] for row in arbitration["dominance_eliminations"]}
    for candidate_id in main_selected:
        if candidate_id not in eligible_ids or candidate_id in dominated:
            reasons.append("pass_requirement_weakened")

    # Newness cannot invent authority: selecting a draft when a wrapper Mode A exists.
    if any(row["wrapper_certified_mode_a"] and row["eligible"] for row in evaluated):
        for row in evaluated:
            if row["candidate_id"] in main_selected and row["uncertified_mode_b_draft"]:
                reasons.append("pass_requirement_weakened")

    candidate_rows = [
        {
            "candidate_id": row["candidate_id"],
            "receipt_payload_sha256": row["receipt_payload_sha256"],
            "access_mode": row["access_mode"],
            "authority_state": row["authority_state"],
            "comparable_scope_sha256": row["comparable_scope_sha256"],
            "eligible": row["eligible"],
            "ineligibility_reasons": row["ineligibility_reasons"],
        }
        for row in sorted(evaluated, key=lambda item: item["candidate_id"])
    ]
    rejected = [
        {"candidate_id": row["candidate_id"], "reasons": row["ineligibility_reasons"]}
        for row in candidate_rows
        if not row["eligible"]
    ]
    evidence = {
        "schema_version": "1.0.0",
        "record_type": "receipt_arbitration_conformance_evidence",
        "decided_at": decided_at,
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "comparable_scope_sha256": arbitration["comparable_scope_sha256"],
        "producer_heads": {
            "release_payload_sha256": producer_heads.get("release_payload_sha256"),
            "capability_snapshot_sha256": producer_heads.get("capability_snapshot_sha256"),
            "revocation_index_sha256": producer_heads.get("revocation_index_sha256"),
            "ontology_version": producer_heads.get("ontology_version"),
            "required_authority_floor": producer_heads.get("required_authority_floor"),
            "required_qa_status": producer_heads.get("required_qa_status"),
            "max_preservation_risk": producer_heads.get("max_preservation_risk"),
            "max_total_ms": producer_heads.get("max_total_ms"),
            "max_peak_vram_mb": producer_heads.get("max_peak_vram_mb"),
            "max_uncertainty": producer_heads.get("max_uncertainty"),
        },
        "candidates": candidate_rows,
        "eligible_candidate_ids": sorted(
            row["candidate_id"]
            for row in evaluated
            if row["eligible"] and row["candidate_id"] not in dominated
        ),
        "rejected_candidates": rejected,
        "normalized_scores": arbitration["normalized_scores"],
        "dominance_eliminations": arbitration["dominance_eliminations"],
        "oracle_decision": oracle,
        "main_decision": {
            "outcome": main_outcome,
            "selected_candidate_ids": sorted(main_selected),
            "comparable_scope_sha256": (
                main.get("comparable_scope_sha256")
                if isinstance(main.get("comparable_scope_sha256"), str)
                else None
            ),
            "receipt_payload_sha256s": (
                sorted(main_receipts) if isinstance(main_receipts, list) else []
            ),
            "policy_sha256": (
                main.get("policy_sha256") if isinstance(main.get("policy_sha256"), str) else None
            ),
            "signature_present": signature_present,
        },
        "status": "accepted" if not reasons else "rejected",
        "rejection_reasons": _ordered(policy, reasons),
        "decision_sha256": "",
    }
    evidence["decision_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("decision_sha256",)
    )
    return evidence


def validate_receipt_arbitration_conformance_evidence(
    evidence: Mapping[str, Any],
) -> tuple[str, ...]:
    """Validate schema, policy binding, hash, and status/reason coherence."""
    issues: list[str] = []
    try:
        policy = _policy()
    except ReceiptArbitrationConformanceError as exc:
        return (str(exc),)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    issues.extend(
        f"schema:{error.validator}"
        for error in Draft202012Validator(schema).iter_errors(dict(evidence))
    )
    if (
        evidence.get("policy_id") != policy["policy_id"]
        or evidence.get("policy_sha256") != policy["policy_sha256"]
    ):
        issues.append("policy_drift")
    expected = canonical_document_sha256(evidence, excluded_top_level_fields=("decision_sha256",))
    if evidence.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")
    allowed = set(policy["reason_codes"])
    reasons = evidence.get("rejection_reasons")
    if not isinstance(reasons, list) or not reasons or not set(reasons).issubset(allowed):
        issues.append("decision_reason_code")
    if (evidence.get("status") == "accepted") != (reasons == ["eligible"]):
        issues.append("decision_status_reasons")
    return tuple(sorted(set(issues)))


__all__ = [
    "ReceiptArbitrationConformanceError",
    "build_receipt_arbitration_conformance_evidence",
    "comparable_scope_identity",
    "comparable_scope_sha256",
    "normalize_and_arbitrate_receipts",
    "validate_receipt_arbitration_conformance_evidence",
]
