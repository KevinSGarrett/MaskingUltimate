"""Authenticated, replay-protected producer intake for downstream repair feedback.

Additive MF-P6-11.05 boundary: resolve signed ``mask_repair_feedback`` against exact
current parent/release/capability/policy/certificate/source/owner/transform/QA/
protected state, enforce hypothesis/attempt budgets via an append-only ledger, and
emit reject / mine / candidate / quarantine decisions without mutating frozen
packages, certificates, or creating truth authority.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

import yaml
from jsonschema import Draft202012Validator

from maskfactory.bridge.journal import BridgeJournalError, append_bridge_journal_event
from maskfactory.validation import (
    canonical_document_sha256,
    validate_idempotency_records,
    validate_mask_repair_feedback,
)

POLICY_PATH = Path(__file__).parents[3] / "configs" / "bridge_feedback_intake_policy.yaml"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "feedback_intake_evidence.schema.json"
POLICY_ID = "maskfactory-bridge-feedback-intake-v1"

_SIGNATURE_ISSUES = frozenset(
    {
        "signature_required",
        "missing_trust_anchor",
        "ed25519_encoding",
        "trusted_key_hash",
        "trusted_key_role",
        "trusted_key_status",
        "trusted_key_validity",
        "trusted_key_set_binding",
        "signature_payload_binding",
        "ed25519_signature_verification",
        "canonical_payload_hash",
        "authentication_replay_window",
        "authentication_expired",
    }
)


class FeedbackIntakeError(ValueError):
    """Feedback intake policy or ledger state is unavailable/malformed."""


@dataclass
class FeedbackIntakeLedger:
    """Append-only producer ledger for feedback identity, nonce, and hypothesis history."""

    by_feedback_id: MutableMapping[str, dict[str, Any]] = field(default_factory=dict)
    nonces: MutableMapping[str, str] = field(default_factory=dict)
    hypotheses: MutableMapping[str, list[dict[str, str]]] = field(default_factory=dict)
    observations: MutableMapping[str, str] = field(default_factory=dict)
    decisions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "by_feedback_id": dict(self.by_feedback_id),
            "nonces": dict(self.nonces),
            "hypotheses": {key: list(rows) for key, rows in self.hypotheses.items()},
            "observations": dict(self.observations),
            "decisions": list(self.decisions),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> FeedbackIntakeLedger:
        if not isinstance(payload, Mapping):
            return cls()
        hypotheses_raw = payload.get("hypotheses") or {}
        return cls(
            by_feedback_id=dict(payload.get("by_feedback_id") or {}),
            nonces=dict(payload.get("nonces") or {}),
            hypotheses={
                str(key): [dict(row) for row in rows if isinstance(row, Mapping)]
                for key, rows in hypotheses_raw.items()
                if isinstance(rows, list)
            },
            observations=dict(payload.get("observations") or {}),
            decisions=[
                dict(row) for row in payload.get("decisions") or () if isinstance(row, Mapping)
            ],
        )


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FeedbackIntakeError("feedback intake policy unavailable") from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise FeedbackIntakeError("unexpected feedback intake policy")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise FeedbackIntakeError("feedback intake policy hash mismatch")
    codes = policy.get("reason_codes")
    if not isinstance(codes, list) or not codes or len(codes) != len(set(codes)):
        raise FeedbackIntakeError("feedback intake policy reason codes are invalid")
    return dict(policy)


def _ordered(policy: Mapping[str, Any], reasons: Sequence[str]) -> list[str]:
    return [code for code in policy["reason_codes"] if code in set(reasons)] or ["eligible"]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _chain_key(feedback: Mapping[str, Any]) -> str:
    return "|".join(str(feedback.get(field) or "") for field in ("project_id", "run_id", "pass_id"))


def _nonce_key(feedback: Mapping[str, Any]) -> str | None:
    auth = _mapping(feedback.get("authentication"))
    principal = auth.get("principal_id")
    nonce = auth.get("nonce")
    if isinstance(principal, str) and isinstance(nonce, str):
        return f"{principal}|{nonce}"
    return None


def _artifact_ids(rows: object) -> set[str]:
    return {
        str(row.get("artifact_identity_sha256"))
        for row in rows or ()
        if isinstance(row, Mapping) and isinstance(row.get("artifact_identity_sha256"), str)
    }


def _parent_fingerprint(
    *,
    parent_request: Mapping[str, Any],
    parent_receipt: Mapping[str, Any],
    certificate: Mapping[str, Any],
) -> dict[str, str | None]:
    return {
        "request_payload_sha256": (
            str(parent_request["request_payload_sha256"])
            if isinstance(parent_request.get("request_payload_sha256"), str)
            else None
        ),
        "receipt_payload_sha256": (
            str(parent_receipt["receipt_payload_sha256"])
            if isinstance(parent_receipt.get("receipt_payload_sha256"), str)
            else None
        ),
        "certificate_payload_sha256": (
            str(certificate["certificate_payload_sha256"])
            if isinstance(certificate.get("certificate_payload_sha256"), str)
            else None
        ),
    }


def _resolve_binding_reasons(
    feedback: Mapping[str, Any],
    *,
    parent_request: Mapping[str, Any],
    parent_receipt: Mapping[str, Any],
    certificate: Mapping[str, Any],
    release_snapshot: Mapping[str, Any] | None,
    capability_snapshot: Mapping[str, Any] | None,
    semantic_profile: Mapping[str, Any] | None,
    current_policy: Mapping[str, Any] | None,
    qa_report: Mapping[str, Any] | None,
    current_parent_heads: Mapping[str, Any] | None,
    revocation_status: str | None,
) -> list[str]:
    reasons: list[str] = []
    if not parent_request or not parent_receipt or not certificate:
        reasons.append("parent_evidence_missing")
        return reasons

    heads = _mapping(current_parent_heads)
    fingerprint = _parent_fingerprint(
        parent_request=parent_request,
        parent_receipt=parent_receipt,
        certificate=certificate,
    )
    for head_key, expected in fingerprint.items():
        observed = heads.get(head_key)
        if observed is not None and observed != expected:
            reasons.append("stale_parent")
            break
    binding = _mapping(feedback.get("parent_receipt_binding"))
    if binding.get("receipt_payload_sha256") != parent_receipt.get(
        "receipt_payload_sha256"
    ) or binding.get("request_payload_sha256") != parent_request.get("request_payload_sha256"):
        reasons.append("stale_parent")

    provider = _mapping(feedback.get("provider_binding"))
    parent_provider = _mapping(parent_receipt.get("provider_binding"))
    if parent_provider and any(
        provider.get(field) != parent_provider.get(field)
        for field in ("stack_id", "stack_sha256", "execution_fingerprint_sha256")
    ):
        reasons.append("provider_binding_drift")

    subject = _mapping(feedback.get("subject_binding"))
    request_subject = _mapping(parent_request.get("subject"))
    if any(
        subject.get(field) != request_subject.get(field)
        for field in (
            "scene_instance_id",
            "canonical_person_id",
            "person_index",
            "provider_person_index",
        )
    ):
        reasons.append("subject_binding_drift")
    assignment = _mapping(request_subject.get("assignment_evidence"))
    if subject.get("assignment_evidence_sha256") != assignment.get("mapping_sha256"):
        reasons.append("subject_binding_drift")

    policy_binding = _mapping(feedback.get("policy_binding"))
    eligibility = _mapping(parent_receipt.get("use_eligibility"))
    current = _mapping(current_policy)
    expected_policy_id = current.get("policy_id") or eligibility.get("policy_id")
    expected_policy_sha = current.get("policy_sha256") or eligibility.get("policy_sha256")
    if (
        policy_binding.get("policy_id") != expected_policy_id
        or policy_binding.get("policy_sha256") != expected_policy_sha
    ):
        reasons.append("policy_binding_drift")

    protected_feedback = _artifact_ids(feedback.get("protected_artifact_bindings"))
    protected_parent = _artifact_ids(parent_request.get("protected_regions"))
    if protected_parent and protected_feedback != protected_parent:
        reasons.append("protected_scope_mismatch")
    if not protected_parent and protected_feedback:
        reasons.append("protected_scope_mismatch")

    output_feedback = _artifact_ids(feedback.get("output_artifact_bindings"))
    output_parent = _artifact_ids(parent_receipt.get("artifacts"))
    if output_feedback != output_parent:
        reasons.append("output_binding_drift")

    transform = _mapping(feedback.get("transform_binding"))
    parent_transform = _mapping(parent_receipt.get("transform_validation"))
    if any(
        transform.get(field) != parent_transform.get(field)
        for field in ("transform_chain_id", "transform_chain_sha256", "executed_step_sha256s")
    ):
        reasons.append("transform_binding_drift")

    qa_binding = _mapping(feedback.get("qa_binding"))
    parent_qa = _mapping(parent_receipt.get("qa"))
    report = _mapping(qa_report)
    report_hash = report.get("report_sha256") or report.get("qa_report_sha256")
    if qa_binding.get("qa_report_sha256") != parent_qa.get("report_sha256"):
        reasons.append("qa_failure_id_mismatch")
    if isinstance(report_hash, str) and qa_binding.get("qa_report_sha256") != report_hash:
        reasons.append("qa_failure_id_mismatch")
    claimed_failures = {
        value for value in qa_binding.get("blocking_failure_ids") or () if isinstance(value, str)
    }
    known_failures = {
        value
        for value in (
            report.get("blocking_failure_ids")
            or report.get("failure_ids")
            or parent_qa.get("blocking_failures")
            or ()
        )
        if isinstance(value, str)
    }
    if not claimed_failures or not claimed_failures.issubset(known_failures):
        reasons.append("qa_failure_id_mismatch")

    release_binding = _mapping(feedback.get("release_binding"))
    parent_release = _mapping(parent_receipt.get("release_binding"))
    release = _mapping(release_snapshot)
    if release:
        if release_binding.get("release_id") != release.get("release_id") or release_binding.get(
            "release_payload_sha256"
        ) != release.get("release_payload_sha256"):
            reasons.append("release_binding_drift")
    elif any(
        release_binding.get(field) != parent_release.get(field)
        for field in ("release_id", "release_payload_sha256")
    ):
        reasons.append("release_binding_drift")

    capability = _mapping(capability_snapshot)
    capability_hash = capability.get("snapshot_sha256") or capability.get(
        "capability_snapshot_sha256"
    )
    if isinstance(capability_hash, str):
        if release_binding.get("capability_snapshot_sha256") != capability_hash:
            reasons.append("capability_binding_drift")
        capability_id = capability.get("snapshot_id") or capability.get("capability_snapshot_id")
        if (
            isinstance(capability_id, str)
            and release_binding.get("capability_snapshot_id") != capability_id
        ):
            reasons.append("capability_binding_drift")
    elif any(
        release_binding.get(field) != parent_release.get(field)
        for field in ("capability_snapshot_id", "capability_snapshot_sha256")
    ):
        reasons.append("capability_binding_drift")

    profile = _mapping(semantic_profile)
    profile_hash = profile.get("profile_sha256") or profile.get("semantic_profile_sha256")
    if (
        isinstance(profile_hash, str)
        and release_binding.get("semantic_profile_sha256") != profile_hash
    ):
        reasons.append("semantic_profile_drift")

    cert_binding = _mapping(feedback.get("certificate_binding"))
    output_scope = _mapping(certificate.get("certified_output_scope"))
    revocation = _mapping(certificate.get("revocation"))
    if (
        cert_binding.get("certificate_id") != certificate.get("certificate_id")
        or cert_binding.get("certificate_sha256") != certificate.get("certificate_payload_sha256")
        or cert_binding.get("certificate_scope_sha256") != output_scope.get("scope_sha256")
        or cert_binding.get("status") != certificate.get("status")
        or cert_binding.get("revocation_checkpoint_sha256")
        != revocation.get("revocation_index_sha256")
    ):
        reasons.append("certificate_binding_drift")
    if certificate.get("status") != "active" or revocation_status in {
        "revoked",
        "superseded",
        "expired",
    }:
        reasons.append("revocation_active")

    source = _mapping(feedback.get("source_binding"))
    request_source = _mapping(parent_request.get("source"))
    if any(
        source.get(field) != request_source.get(field)
        for field in ("artifact_id", "encoded_sha256", "decoded_pixel_sha256")
    ):
        reasons.append("source_binding_drift")

    authority = _mapping(feedback.get("authority_binding"))
    parent_authority = _mapping(parent_receipt.get("authority"))
    if authority.get("authority_state") != parent_authority.get("authority_state"):
        reasons.append("authority_binding_drift")
    if authority.get("truth_tier") != parent_receipt.get("truth_tier"):
        reasons.append("authority_binding_drift")

    return reasons


def _budget_reasons(feedback: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    budget = _mapping(feedback.get("retry_budget"))
    attempt = budget.get("attempt")
    maximum = budget.get("maximum_attempts")
    remaining = budget.get("remaining_attempts")
    if isinstance(attempt, int) and isinstance(maximum, int) and attempt >= maximum:
        reasons.append("attempt_cap_exhausted")
    if isinstance(remaining, int) and remaining <= 0:
        reasons.append("attempt_cap_exhausted")
    progress = _mapping(feedback.get("progress_guard"))
    no_progress = progress.get("no_progress_count")
    max_no_progress = progress.get("maximum_no_progress_count")
    if (
        isinstance(no_progress, int)
        and isinstance(max_no_progress, int)
        and no_progress >= max_no_progress
    ):
        reasons.append("no_progress_exhausted")
    return reasons


def _ledger_reasons(
    feedback: Mapping[str, Any],
    *,
    body_sha: str,
    ledger: FeedbackIntakeLedger,
    policy: Mapping[str, Any],
) -> tuple[list[str], dict[str, Any] | None]:
    reasons: list[str] = []
    feedback_id = feedback.get("feedback_id")
    prior_decision = None
    if isinstance(feedback_id, str):
        prior = ledger.by_feedback_id.get(feedback_id)
        if isinstance(prior, Mapping):
            if prior.get("feedback_payload_sha256") == body_sha:
                prior_decision = dict(prior.get("evidence") or {})
            else:
                reasons.append("feedback_id_body_collision")

    nonce = _nonce_key(feedback)
    if nonce is not None:
        previous_body = ledger.nonces.get(nonce)
        if previous_body is not None and previous_body != body_sha:
            reasons.append("authentication_nonce_replay")

    batch_issues = validate_idempotency_records([*ledger.decisions, dict(feedback)])
    if any(issue.validator == "authentication_nonce_replay" for issue in batch_issues):
        reasons.append("authentication_nonce_replay")
    if any(issue.validator == "quality_retry_material_change" for issue in batch_issues):
        reasons.append("duplicate_hypothesis")

    hypothesis = _mapping(feedback.get("hypothesis"))
    hypothesis_id = hypothesis.get("hypothesis_id")
    material = hypothesis.get("material_change_sha256")
    chain = _chain_key(feedback)
    history = list(ledger.hypotheses.get(chain) or ())
    max_history = int(policy.get("max_hypothesis_history") or 32)
    if len(history) >= max_history:
        reasons.append("attempt_cap_exhausted")
    for row in history:
        if row.get("hypothesis_id") == hypothesis_id:
            reasons.append("duplicate_hypothesis")
        if row.get("material_change_sha256") == material:
            reasons.append("immaterial_hypothesis")

    for defect in feedback.get("defects") or ():
        if not isinstance(defect, Mapping):
            continue
        target = defect.get("target_artifact_identity_sha256")
        observation = defect.get("observation_sha256")
        defect_class = defect.get("class")
        if not isinstance(target, str) or not isinstance(observation, str):
            continue
        key = f"{chain}|{target}|{defect_class}"
        prior_observation = ledger.observations.get(key)
        if prior_observation is not None and prior_observation != observation:
            reasons.append("conflicting_observation")

    return reasons, prior_decision


def _write_reasons(
    write_attempt: Mapping[str, Any] | None,
    *,
    policy: Mapping[str, Any],
    parent_bytes_before: Mapping[str, Any] | None,
    parent_bytes_after: Mapping[str, Any] | None,
) -> list[str]:
    reasons: list[str] = []
    forbidden = {
        str(value)
        for value in policy.get("forbidden_write_targets") or ()
        if isinstance(value, str)
    }
    attempt = _mapping(write_attempt)
    target = attempt.get("target_kind")
    if isinstance(target, str) and target in forbidden:
        reasons.append("unauthorized_write_attempt")
    before = _mapping(parent_bytes_before)
    after = _mapping(parent_bytes_after) if parent_bytes_after is not None else before
    for byte_key in (
        "parent_package_sha256",
        "parent_certificate_sha256",
        "parent_mask_sha256",
        "truth_tier_sha256",
    ):
        if before.get(byte_key) != after.get(byte_key):
            reasons.append("parent_mutation_blocked")
            break
    return reasons


def _build_child_candidate(feedback: Mapping[str, Any], *, body_sha: str) -> dict[str, Any]:
    hypothesis = _mapping(feedback.get("hypothesis"))
    parent = _mapping(feedback.get("parent_receipt_binding"))
    feedback_id = str(feedback.get("feedback_id"))
    candidate = {
        "candidate_id": f"mfcand_{body_sha[:24]}",
        "parent_receipt_id": parent.get("receipt_id"),
        "parent_receipt_payload_sha256": parent.get("receipt_payload_sha256"),
        "parent_request_payload_sha256": parent.get("request_payload_sha256"),
        "hypothesis_id": hypothesis.get("hypothesis_id"),
        "material_change_sha256": hypothesis.get("material_change_sha256"),
        "feedback_id": feedback_id,
        "feedback_payload_sha256": body_sha,
        "requested_action": feedback.get("requested_action"),
        "creates_truth": False,
        "mutates_parent": False,
        "candidate_sha256": "",
    }
    candidate["candidate_sha256"] = canonical_document_sha256(
        candidate, excluded_top_level_fields=("candidate_sha256",)
    )
    return candidate


def _mining_retention(feedback: Mapping[str, Any]) -> dict[str, Any]:
    observations = sorted(
        {
            str(row.get("observation_sha256"))
            for row in feedback.get("defects") or ()
            if isinstance(row, Mapping) and isinstance(row.get("observation_sha256"), str)
        }
    )
    return {
        "corpus_kind": "advisory_non_gold",
        "observation_sha256s": observations,
        "enters_training_gold": False,
        "enters_operational_certificate_evidence": False,
        "enters_production_masks": False,
    }


def _decide_outcome(
    *,
    policy: Mapping[str, Any],
    reasons: Sequence[str],
    feedback: Mapping[str, Any],
    prior_decision: Mapping[str, Any] | None,
) -> str:
    if prior_decision is not None:
        return "idempotent_replay"
    hard = [
        code
        for code in reasons
        if code
        not in {
            "eligible",
            "no_progress_exhausted",
            "attempt_cap_exhausted",
        }
    ]
    if hard:
        return "rejected"
    if "no_progress_exhausted" in reasons or "attempt_cap_exhausted" in reasons:
        return "quarantine_and_abstain"
    action = feedback.get("requested_action")
    if action in set(policy.get("quarantine_actions") or ()):
        return "quarantine_and_abstain"
    if action in set(policy.get("mining_actions") or ()):
        return "mining_only"
    if action in set(policy.get("candidate_actions") or ()):
        return "candidate_created"
    return "rejected"


def _commit_ledger(
    ledger: FeedbackIntakeLedger,
    *,
    feedback: Mapping[str, Any],
    body_sha: str,
    evidence: Mapping[str, Any],
) -> None:
    feedback_id = feedback.get("feedback_id")
    if isinstance(feedback_id, str):
        ledger.by_feedback_id[feedback_id] = {
            "feedback_payload_sha256": body_sha,
            "evidence": dict(evidence),
        }
    nonce = _nonce_key(feedback)
    if nonce is not None:
        ledger.nonces[nonce] = body_sha
    hypothesis = _mapping(feedback.get("hypothesis"))
    chain = _chain_key(feedback)
    history = list(ledger.hypotheses.get(chain) or ())
    if isinstance(hypothesis.get("hypothesis_id"), str) and isinstance(
        hypothesis.get("material_change_sha256"), str
    ):
        history.append(
            {
                "hypothesis_id": str(hypothesis["hypothesis_id"]),
                "material_change_sha256": str(hypothesis["material_change_sha256"]),
                "feedback_id": str(feedback_id or ""),
            }
        )
        ledger.hypotheses[chain] = history
    for defect in feedback.get("defects") or ():
        if not isinstance(defect, Mapping):
            continue
        target = defect.get("target_artifact_identity_sha256")
        observation = defect.get("observation_sha256")
        defect_class = defect.get("class")
        if isinstance(target, str) and isinstance(observation, str):
            ledger.observations[f"{chain}|{target}|{defect_class}"] = observation
    ledger.decisions.append(
        {
            "feedback_id": feedback_id,
            "feedback_payload_sha256": body_sha,
            "authentication": dict(_mapping(feedback.get("authentication"))),
            "hypothesis": dict(hypothesis),
            "project_id": feedback.get("project_id"),
            "run_id": feedback.get("run_id"),
            "pass_id": feedback.get("pass_id"),
            "attempt_id": feedback.get("attempt_id"),
        }
    )


def intake_bridge_feedback(
    feedback: Mapping[str, Any],
    *,
    decided_at: str,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]],
    parent_request: Mapping[str, Any],
    parent_receipt: Mapping[str, Any],
    certificate: Mapping[str, Any],
    ledger: FeedbackIntakeLedger | None = None,
    release_snapshot: Mapping[str, Any] | None = None,
    capability_snapshot: Mapping[str, Any] | None = None,
    semantic_profile: Mapping[str, Any] | None = None,
    current_policy: Mapping[str, Any] | None = None,
    qa_report: Mapping[str, Any] | None = None,
    current_parent_heads: Mapping[str, Any] | None = None,
    revocation_status: str | None = None,
    write_attempt: Mapping[str, Any] | None = None,
    parent_bytes_before: Mapping[str, Any] | None = None,
    parent_bytes_after: Mapping[str, Any] | None = None,
    journal_entries: Sequence[Mapping[str, Any]] | None = None,
    journal_private_key: Any | None = None,
    journal_signing_key_id: str | None = None,
    journal_id: str = "maskfactory-feedback-intake",
) -> dict[str, Any]:
    """Validate, resolve, ledger, and decide one advisory repair feedback document."""
    policy = _policy()
    active_ledger = ledger if ledger is not None else FeedbackIntakeLedger()
    reasons: list[str] = []

    document_issues = validate_mask_repair_feedback(
        feedback,
        trusted_signing_keys=trusted_signing_keys,
        parent_receipt=parent_receipt,
        parent_request=parent_request,
        certificate=certificate,
    )
    if document_issues:
        reasons.append("feedback_document_invalid")
        if any(issue.validator in _SIGNATURE_ISSUES for issue in document_issues):
            reasons.append("feedback_forgery")

    body_sha = (
        str(feedback["feedback_payload_sha256"])
        if isinstance(feedback.get("feedback_payload_sha256"), str)
        else canonical_document_sha256(
            feedback, excluded_top_level_fields=("feedback_payload_sha256", "signature")
        )
    )

    reasons.extend(
        _resolve_binding_reasons(
            feedback,
            parent_request=parent_request,
            parent_receipt=parent_receipt,
            certificate=certificate,
            release_snapshot=release_snapshot,
            capability_snapshot=capability_snapshot,
            semantic_profile=semantic_profile,
            current_policy=current_policy,
            qa_report=qa_report,
            current_parent_heads=current_parent_heads,
            revocation_status=revocation_status,
        )
    )
    reasons.extend(_budget_reasons(feedback))
    ledger_reasons, prior_decision = _ledger_reasons(
        feedback, body_sha=body_sha, ledger=active_ledger, policy=policy
    )
    reasons.extend(ledger_reasons)
    reasons.extend(
        _write_reasons(
            write_attempt,
            policy=policy,
            parent_bytes_before=parent_bytes_before,
            parent_bytes_after=parent_bytes_after,
        )
    )

    ordered = _ordered(policy, reasons)
    outcome = _decide_outcome(
        policy=policy,
        reasons=ordered,
        feedback=feedback,
        prior_decision=prior_decision,
    )
    if prior_decision is not None and outcome == "idempotent_replay":
        replay = dict(prior_decision)
        replay["outcome"] = "idempotent_replay"
        replay["decided_at"] = decided_at
        replay["decision_sha256"] = ""
        replay["decision_sha256"] = canonical_document_sha256(
            replay, excluded_top_level_fields=("decision_sha256",)
        )
        return replay

    before = _mapping(parent_bytes_before)
    after = _mapping(parent_bytes_after) if parent_bytes_after is not None else before
    package_before = before.get("parent_package_sha256")
    package_after = after.get("parent_package_sha256")
    cert_before = before.get("parent_certificate_sha256") or certificate.get(
        "certificate_payload_sha256"
    )
    cert_after = after.get("parent_certificate_sha256") or cert_before
    if package_before is None:
        package_before = parent_receipt.get("receipt_payload_sha256")
        package_after = package_before
    parent_unchanged = package_before == package_after and cert_before == cert_after
    if not parent_unchanged:
        ordered = _ordered(policy, [*ordered, "parent_mutation_blocked"])
        outcome = "rejected"

    child_candidate = None
    mining_retention = None
    repair_handoff = None
    if outcome == "candidate_created":
        child_candidate = _build_child_candidate(feedback, body_sha=body_sha)
        hypothesis = _mapping(feedback.get("hypothesis"))
        repair_handoff = {
            "accepted_parent_id": str(parent_receipt.get("receipt_id") or ""),
            "hypothesis_id": str(hypothesis.get("hypothesis_id") or ""),
            "material_change_sha256": str(hypothesis.get("material_change_sha256") or ""),
            "eligible_for_durable_repair": True,
        }
    elif outcome in {"mining_only", "quarantine_and_abstain"}:
        mining_retention = _mining_retention(feedback)

    journal_event = None
    journal_head = None
    event_type = (
        "repair_feedback_accepted"
        if outcome in {"candidate_created", "mining_only", "quarantine_and_abstain"}
        else "repair_feedback_rejected"
    )
    event_body = {
        "event_type": event_type,
        "feedback_id": feedback.get("feedback_id"),
        "feedback_payload_sha256": body_sha,
        "outcome": outcome,
        "rejection_reasons": ordered,
        "parent_receipt_payload_sha256": parent_receipt.get("receipt_payload_sha256"),
    }
    event_body_sha = canonical_document_sha256(event_body)
    journal_event = {
        "event_type": event_type,
        "event_body_sha256": event_body_sha,
        "producer_owned": True,
    }
    if journal_private_key is not None and journal_signing_key_id and journal_entries is not None:
        try:
            _updated, entry, _replayed = append_bridge_journal_event(
                journal_entries,
                journal_id=journal_id,
                state="decision",
                idempotency_key=f"feedback:{feedback.get('feedback_id')}:{body_sha}",
                event_body=event_body,
                occurred_at=decided_at,
                private_key=journal_private_key,
                signing_key_id=journal_signing_key_id,
            )
            journal_head = entry.get("entry_sha256")
        except BridgeJournalError:
            ordered = _ordered(policy, [*ordered, "feedback_document_invalid"])
            outcome = "rejected"
            child_candidate = None
            mining_retention = None
            repair_handoff = None
            journal_event = {
                "event_type": "repair_feedback_rejected",
                "event_body_sha256": event_body_sha,
                "producer_owned": True,
            }

    release_binding = _mapping(feedback.get("release_binding"))
    hypothesis = _mapping(feedback.get("hypothesis"))
    transform = _mapping(feedback.get("transform_binding"))
    source = _mapping(feedback.get("source_binding"))
    qa_binding = _mapping(feedback.get("qa_binding"))
    policy_binding = _mapping(feedback.get("policy_binding"))
    cert_binding = _mapping(feedback.get("certificate_binding"))
    parent_binding = _mapping(feedback.get("parent_receipt_binding"))

    status = (
        "accepted"
        if outcome in {"candidate_created", "mining_only", "quarantine_and_abstain"}
        else "rejected"
    )

    evidence = {
        "schema_version": "1.0.0",
        "record_type": "feedback_intake_evidence",
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "decided_at": decided_at,
        "status": status,
        "outcome": outcome,
        "rejection_reasons": ordered,
        "feedback_id": feedback.get("feedback_id"),
        "feedback_payload_sha256": body_sha,
        "parent_preservation": {
            "parent_package_sha256_before": package_before,
            "parent_package_sha256_after": package_after,
            "parent_certificate_sha256_before": cert_before,
            "parent_certificate_sha256_after": cert_after,
            "parent_bytes_unchanged": bool(parent_unchanged),
            "truth_created": False,
            "gold_mutated": False,
        },
        "consumed_context": {
            "parent_receipt_id": parent_binding.get("receipt_id")
            or parent_receipt.get("receipt_id"),
            "parent_receipt_payload_sha256": parent_receipt.get("receipt_payload_sha256"),
            "parent_request_id": parent_binding.get("request_id")
            or parent_request.get("request_id"),
            "parent_request_payload_sha256": parent_request.get("request_payload_sha256"),
            "release_id": release_binding.get("release_id"),
            "capability_snapshot_sha256": release_binding.get("capability_snapshot_sha256"),
            "policy_sha256": policy_binding.get("policy_sha256"),
            "certificate_id": cert_binding.get("certificate_id"),
            "certificate_sha256": cert_binding.get("certificate_sha256"),
            "source_decoded_pixel_sha256": source.get("decoded_pixel_sha256"),
            "transform_chain_sha256": transform.get("transform_chain_sha256"),
            "qa_report_sha256": qa_binding.get("qa_report_sha256"),
            "hypothesis_id": hypothesis.get("hypothesis_id"),
            "material_change_sha256": hypothesis.get("material_change_sha256"),
            "ledger_entry_count": len(active_ledger.decisions),
            "journal_head_sha256": journal_head,
        },
        "child_candidate": child_candidate,
        "mining_retention": mining_retention,
        "operational_repair_handoff": repair_handoff,
        "journal_event": journal_event,
        "decision_sha256": "",
    }
    evidence["decision_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("decision_sha256",)
    )
    if "feedback_id_body_collision" not in ordered:
        _commit_ledger(active_ledger, feedback=feedback, body_sha=body_sha, evidence=evidence)
    return evidence


def validate_feedback_intake_evidence(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate evidence schema, policy binding, hash, and outcome coherence."""
    try:
        policy = _policy()
    except FeedbackIntakeError as exc:
        return (str(exc),)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    issues = [
        f"schema:{error.validator}"
        for error in Draft202012Validator(schema).iter_errors(dict(evidence))
    ]
    if (
        evidence.get("policy_id") != policy["policy_id"]
        or evidence.get("policy_sha256") != policy["policy_sha256"]
    ):
        issues.append("policy_drift")
    expected = canonical_document_sha256(evidence, excluded_top_level_fields=("decision_sha256",))
    if evidence.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")
    allowed = set(policy["reason_codes"])
    reasons = set(evidence.get("rejection_reasons") or ())
    if not reasons.issubset(allowed):
        issues.append("reason_code_drift")
    outcomes = set(policy.get("decision_outcomes") or ())
    if evidence.get("outcome") not in outcomes:
        issues.append("outcome_drift")
    if evidence.get("parent_preservation", {}).get("truth_created") is not False:
        issues.append("truth_firewall")
    if evidence.get("parent_preservation", {}).get("gold_mutated") is not False:
        issues.append("gold_firewall")
    accepted_outcomes = {
        "candidate_created",
        "mining_only",
        "quarantine_and_abstain",
        "idempotent_replay",
    }
    if evidence.get("outcome") in accepted_outcomes and evidence.get("status") != "accepted":
        issues.append("decision_status_outcome")
    if evidence.get("outcome") == "rejected" and evidence.get("status") != "rejected":
        issues.append("decision_status_outcome")
    if evidence.get("outcome") == "candidate_created" and not isinstance(
        evidence.get("child_candidate"), Mapping
    ):
        issues.append("candidate_missing")
    if evidence.get("outcome") == "mining_only" and not isinstance(
        evidence.get("mining_retention"), Mapping
    ):
        issues.append("mining_retention_missing")
    return tuple(sorted(set(issues)))


__all__ = [
    "FeedbackIntakeError",
    "FeedbackIntakeLedger",
    "intake_bridge_feedback",
    "validate_feedback_intake_evidence",
]
