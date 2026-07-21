"""Independent, fail-closed use-eligibility decisions for bridge receipts.

The frozen receipt's ``use_eligibility`` member is retained as a producer
observation only.  This module recomputes an intended-use decision from
normalized request, receipt, and certificate evidence; it never treats that
observation as authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from maskfactory.validation import canonical_document_sha256

POLICY_PATH = Path(__file__).parents[3] / "configs" / "bridge_use_eligibility_policy.yaml"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "bridge_use_eligibility_decision.schema.json"
POLICY_ID = "maskfactory-bridge-use-eligibility-v1"


class UseEligibilityError(ValueError):
    """A closed use-eligibility policy or input cannot be evaluated."""


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise UseEligibilityError("use eligibility policy is unavailable") from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise UseEligibilityError("unexpected use eligibility policy")
    expected_fields = {
        "schema_version",
        "policy_id",
        "policy_version",
        "canonicalization",
        "authority_rank",
        "use_scopes",
        "reason_codes",
        "policy_sha256",
    }
    if set(policy) != expected_fields or policy.get("schema_version") != "1.0.0":
        raise UseEligibilityError("use eligibility policy shape mismatch")
    ranks = policy.get("authority_rank")
    scopes = policy.get("use_scopes")
    codes = policy.get("reason_codes")
    if (
        not isinstance(ranks, Mapping)
        or set(ranks) != {"invalid", "hypothesis", "draft", "qa_passed_noncertified", "certified"}
        or not isinstance(scopes, Mapping)
        or not isinstance(codes, list)
        or not codes
        or len(codes) != len(set(codes))
    ):
        raise UseEligibilityError("use eligibility policy is not closed")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise UseEligibilityError("use eligibility policy hash mismatch")
    return dict(policy)


def _strings(values: object) -> set[str]:
    return (
        {value for value in values if isinstance(value, str)} if isinstance(values, list) else set()
    )


def _ordered_reasons(policy: Mapping[str, Any], reasons: list[str]) -> list[str]:
    return [code for code in policy["reason_codes"] if code in set(reasons)]


def _observation(receipt: Mapping[str, Any]) -> Mapping[str, Any]:
    value = receipt.get("use_eligibility")
    return value if isinstance(value, Mapping) else {}


def validate_bridge_use_eligibility_observation(observation: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate the preserved producer observation without granting it authority."""
    try:
        policy = _policy()
    except UseEligibilityError as exc:
        return (str(exc),)
    required = {
        "policy_id",
        "policy_sha256",
        "required_authority_state",
        "exact_use_scope",
        "eligible",
        "reasons",
    }
    issues: list[str] = []
    if set(observation) != required:
        issues.append("producer_observation_shape")
    if (
        observation.get("policy_id") != policy["policy_id"]
        or observation.get("policy_sha256") != policy["policy_sha256"]
    ):
        issues.append("producer_self_assertion")
    scopes = policy["use_scopes"]
    if observation.get("exact_use_scope") not in scopes:
        issues.append("producer_observation_scope")
    if observation.get("required_authority_state") not in policy["authority_rank"]:
        issues.append("producer_observation_authority")
    if not isinstance(observation.get("eligible"), bool):
        issues.append("producer_observation_eligibility")
    reasons = observation.get("reasons")
    if not isinstance(reasons, list) or not reasons or len(reasons) != len(set(reasons)):
        issues.append("producer_observation_reasons")
    elif not set(reasons).issubset(set(policy["reason_codes"])):
        issues.append("producer_observation_reasons")
    return tuple(sorted(set(issues)))


def _certificate_coverage(
    request: Mapping[str, Any],
    receipt: Mapping[str, Any],
    certificate: Mapping[str, Any] | None,
    scope: str,
    require_certificate: bool,
) -> bool:
    if not require_certificate:
        return True
    if not isinstance(certificate, Mapping):
        return False
    authority = receipt.get("authority") if isinstance(receipt.get("authority"), Mapping) else {}
    if (
        authority.get("certificate_status") != "active"
        or authority.get("certificate_exact_scope_match") is not True
    ):
        return False
    if certificate.get("certificate_payload_sha256") != authority.get("certificate_sha256"):
        return False
    intents = request.get("mask_intents") if isinstance(request.get("mask_intents"), list) else []
    artifacts = receipt.get("artifacts") if isinstance(receipt.get("artifacts"), list) else []
    requested_intents = _strings(
        [row.get("intent_id") for row in intents if isinstance(row, Mapping)]
    )
    requested_labels = _strings([row.get("label") for row in intents if isinstance(row, Mapping)])
    artifact_intents = _strings(
        [row.get("intent_id") for row in artifacts if isinstance(row, Mapping)]
    )
    artifact_labels = _strings([row.get("label") for row in artifacts if isinstance(row, Mapping)])
    subject = request.get("subject") if isinstance(request.get("subject"), Mapping) else {}
    owner_id = subject.get("canonical_person_id")
    region_ids = _strings(
        [
            row.get("region_id")
            for row in request.get("target_regions", [])
            if isinstance(row, Mapping)
        ]
    )
    return (
        scope in _strings(certificate.get("permitted_use_scopes"))
        and requested_intents <= _strings(certificate.get("intent_ids"))
        and requested_labels <= _strings(certificate.get("labels"))
        and requested_intents <= artifact_intents
        and requested_labels <= artifact_labels
        and (not owner_id or owner_id in _strings(certificate.get("owner_ids")))
        and region_ids <= _strings(certificate.get("target_region_ids"))
    )


def evaluate_bridge_use_eligibility(
    request: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    exact_use_scope: str,
    certificate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Independently derive an intended-use decision and reject disagreement.

    ``exact_use_scope`` is caller-owned intent.  It is deliberately required
    rather than inferred from the producer observation or a global certificate
    claim, so a producer cannot self-assert a more permissive intended use.
    """
    policy = _policy()
    scopes = policy["use_scopes"]
    if exact_use_scope not in scopes:
        raise UseEligibilityError("unknown exact use scope")
    requirement = scopes[exact_use_scope]
    authority = receipt.get("authority") if isinstance(receipt.get("authority"), Mapping) else {}
    observed_state = authority.get("authority_state")
    required_state = requirement["required_authority_state"]
    reasons: list[str] = []
    if receipt.get("result") != "succeeded":
        reasons.append("execution_not_succeeded")
    ranks = policy["authority_rank"]
    if observed_state not in ranks or ranks[observed_state] < ranks[required_state]:
        reasons.append("authority_insufficient")
    qa = receipt.get("qa") if isinstance(receipt.get("qa"), Mapping) else {}
    if qa.get("status") != "pass":
        reasons.append("qa_not_passed")
    transform = (
        receipt.get("transform_validation")
        if isinstance(receipt.get("transform_validation"), Mapping)
        else {}
    )
    if transform.get("roundtrip_passed") is not True:
        reasons.append("transform_not_roundtrip_validated")
    if (
        authority.get("revocation_index_sha256") is None
        or authority.get("certificate_status") == "revoked"
    ):
        reasons.append("revocation_not_current")
    if not _certificate_coverage(
        request,
        receipt,
        certificate,
        exact_use_scope,
        requirement["require_active_exact_certificate"],
    ):
        reasons.append("certificate_scope_incomplete")

    observation = _observation(receipt)
    observation_issues = validate_bridge_use_eligibility_observation(observation)
    independent_reasons = _ordered_reasons(policy, reasons) or ["eligible"]
    expected_observation = {
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "required_authority_state": required_state,
        "exact_use_scope": exact_use_scope,
        "eligible": independent_reasons == ["eligible"],
        "reasons": independent_reasons,
    }
    if observation_issues:
        reasons.append("producer_self_assertion")
    if any(observation.get(key) != value for key, value in expected_observation.items()):
        reasons.append("policy_observation_disagrees")
    if (
        "global" in str(observation.get("policy_id", "")).lower()
        or "global" in " ".join(str(value) for value in observation.get("reasons", [])).lower()
    ):
        reasons.append("global_certified_shortcut")

    normalized = {
        "request_payload_sha256": request.get("request_payload_sha256"),
        "receipt_payload_sha256": receipt.get("receipt_payload_sha256"),
        "result": receipt.get("result"),
        "authority_state": observed_state,
        "certificate_status": authority.get("certificate_status"),
        "certificate_sha256": authority.get("certificate_sha256"),
        "qa_status": qa.get("status"),
        "transform_roundtrip_passed": transform.get("roundtrip_passed"),
        "revocation_index_sha256": authority.get("revocation_index_sha256"),
        "certificate_evidence_sha256": (
            certificate.get("certificate_payload_sha256") if certificate else None
        ),
    }
    decision = {
        "schema_version": "1.0.0",
        "record_type": "bridge_use_eligibility_decision",
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "required_authority_state": required_state,
        "exact_use_scope": exact_use_scope,
        "eligible": not reasons,
        "reasons": _ordered_reasons(policy, reasons) or ["eligible"],
        "normalized_facts": normalized,
        "producer_observation": dict(observation),
        "decision_sha256": "",
    }
    decision["decision_sha256"] = canonical_document_sha256(
        decision, excluded_top_level_fields=("decision_sha256",)
    )
    return decision


def derive_main_compatibility_alias(decision: Mapping[str, Any]) -> bool:
    """Expose a compatibility boolean only as a derived alias of the independent decision.

    Main may preserve the producer observation and this alias, but neither may
    replace independent recomputation as decision authority.
    """
    return decision.get("eligible") is True and decision.get("reasons") == ["eligible"]


def validate_bridge_use_eligibility_decision(decision: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate decision shape, current named policy, and canonical hash."""
    issues: list[str] = []
    try:
        policy = _policy()
    except UseEligibilityError as exc:
        return (str(exc),)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    issues.extend(
        f"schema:{error.validator}"
        for error in Draft202012Validator(schema).iter_errors(dict(decision))
    )
    if (
        decision.get("policy_id") != policy["policy_id"]
        or decision.get("policy_sha256") != policy["policy_sha256"]
    ):
        issues.append("policy_drift")
    if not set(decision.get("reasons", [])).issubset(set(policy["reason_codes"])):
        issues.append("decision_reason_code")
    expected = canonical_document_sha256(decision, excluded_top_level_fields=("decision_sha256",))
    if decision.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")
    if decision.get("eligible") != (decision.get("reasons") == ["eligible"]):
        issues.append("decision_eligibility_reasons")
    return tuple(sorted(set(issues)))
