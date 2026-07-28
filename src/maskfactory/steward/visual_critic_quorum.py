"""Fail-closed visual-critic quorum for governed mask evidence.

This module is deliberately transport-agnostic.  It validates immutable panel,
qualification, and response bindings after a self-hosted visual runtime has
produced them.  It cannot qualify a model, render a mask, clear deterministic
hard QA, or grant final mask/gold/training authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "maskfactory.visual-critic-quorum.v1"
ZERO_SHA256 = "0" * 64
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

PANEL_ROLES = ("source", "mask", "overlay", "contour", "ownership")
CRITIC_ROLES = ("primary", "juror")
RESPONSE_STATUSES = frozenset({"COMPLETE", "UNAVAILABLE", "MALFORMED", "TIMEOUT"})
VERDICTS = frozenset({"PASS", "FAIL", "UNCERTAIN"})
PASSING_HARD_QA = frozenset({"PASS", "PASS_AFTER_REPAIR"})
FORBIDDEN_CLAIMS = (
    "final_mask_acceptance",
    "gold",
    "hard_qa_override",
    "text_only_acceptance",
    "training_truth",
)


class VisualCriticQuorumError(ValueError):
    """An immutable visual-quorum contract failed closed."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(value: Mapping[str, Any]) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    sealed = dict(value)
    sealed[field] = ZERO_SHA256
    sealed[field] = _sha256(sealed)
    return sealed


def _verify_self_hash(
    value: Mapping[str, Any],
    *,
    field: str,
    subject: str,
) -> None:
    actual = value.get(field)
    if not isinstance(actual, str) or SHA256_RE.fullmatch(actual) is None:
        raise VisualCriticQuorumError(f"{subject} has invalid {field}")
    candidate = dict(value)
    candidate[field] = ZERO_SHA256
    if _sha256(candidate) != actual:
        raise VisualCriticQuorumError(f"{subject} self-hash mismatch")


def _identifier(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 160
        or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for character in value)
    ):
        raise VisualCriticQuorumError(f"{field} is invalid")
    return value


def _digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise VisualCriticQuorumError(f"{field} must be lowercase SHA-256")
    return value


def build_panel_bundle(panels: Mapping[str, bytes]) -> dict[str, Any]:
    """Bind the exact required PNG panel bytes without writing or rendering."""

    if not isinstance(panels, Mapping) or set(panels) != set(PANEL_ROLES):
        raise VisualCriticQuorumError("panel roles must match the frozen role set")
    records: list[dict[str, Any]] = []
    for role in PANEL_ROLES:
        payload = panels[role]
        if not isinstance(payload, bytes) or len(payload) <= len(PNG_SIGNATURE):
            raise VisualCriticQuorumError(f"panel {role} must be nonempty bytes")
        if not payload.startswith(PNG_SIGNATURE):
            raise VisualCriticQuorumError(f"panel {role} must be PNG")
        records.append(
            {
                "role": role,
                "bytes": len(payload),
                "sha256": _sha256_bytes(payload),
            }
        )
    return _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "panels": records,
            "panel_bundle_sha256": ZERO_SHA256,
        },
        "panel_bundle_sha256",
    )


def validate_panel_bundle(
    panel_bundle: Mapping[str, Any],
    panels: Mapping[str, bytes],
) -> None:
    """Prove the supplied panel bytes are exactly the sealed quorum inputs."""

    if not isinstance(panel_bundle, Mapping) or set(panel_bundle) != {
        "schema_version",
        "panels",
        "panel_bundle_sha256",
    }:
        raise VisualCriticQuorumError("panel bundle field set mismatch")
    if panel_bundle.get("schema_version") != SCHEMA_VERSION:
        raise VisualCriticQuorumError("panel bundle schema mismatch")
    _verify_self_hash(
        panel_bundle,
        field="panel_bundle_sha256",
        subject="panel bundle",
    )
    expected = build_panel_bundle(panels)
    if dict(panel_bundle) != expected:
        raise VisualCriticQuorumError("panel bytes differ from sealed bundle")


def build_critic_certificate(
    *,
    role: str,
    model_id: str,
    model_sha256: str,
    runtime_sha256: str,
    family_id: str,
    capability_class: str,
    qualification_report_sha256: str,
    positive_calibration_passed: bool,
    negative_calibration_passed: bool,
    qualification_status: str = "QUALIFIED",
) -> dict[str, Any]:
    """Seal an already-issued qualification claim for later verification."""

    certificate = {
        "schema_version": SCHEMA_VERSION,
        "role": role,
        "model_id": model_id,
        "model_sha256": model_sha256,
        "runtime_sha256": runtime_sha256,
        "family_id": family_id,
        "capability_class": capability_class,
        "qualification_status": qualification_status,
        "positive_calibration_passed": positive_calibration_passed,
        "negative_calibration_passed": negative_calibration_passed,
        "qualification_report_sha256": qualification_report_sha256,
        "certificate_sha256": ZERO_SHA256,
    }
    _validate_certificate_fields(certificate, expected_role=role, verify_hash=False)
    return _seal(certificate, "certificate_sha256")


def _validate_certificate_fields(
    certificate: Mapping[str, Any],
    *,
    expected_role: str,
    verify_hash: bool,
) -> None:
    expected_fields = {
        "schema_version",
        "role",
        "model_id",
        "model_sha256",
        "runtime_sha256",
        "family_id",
        "capability_class",
        "qualification_status",
        "positive_calibration_passed",
        "negative_calibration_passed",
        "qualification_report_sha256",
        "certificate_sha256",
    }
    if not isinstance(certificate, Mapping) or set(certificate) != expected_fields:
        raise VisualCriticQuorumError("critic certificate field set mismatch")
    if certificate.get("schema_version") != SCHEMA_VERSION:
        raise VisualCriticQuorumError("critic certificate schema mismatch")
    if expected_role not in CRITIC_ROLES or certificate.get("role") != expected_role:
        raise VisualCriticQuorumError("critic certificate role mismatch")
    _identifier(certificate.get("model_id"), field="model_id")
    _identifier(certificate.get("family_id"), field="family_id")
    _digest(certificate.get("model_sha256"), field="model_sha256")
    _digest(certificate.get("runtime_sha256"), field="runtime_sha256")
    _digest(
        certificate.get("qualification_report_sha256"),
        field="qualification_report_sha256",
    )
    required_capability = (
        "high_end_multimodal"
        if expected_role == "primary"
        else "independent_multimodal_juror"
    )
    if certificate.get("capability_class") != required_capability:
        raise VisualCriticQuorumError("critic capability is not role-qualified")
    if certificate.get("qualification_status") != "QUALIFIED":
        raise VisualCriticQuorumError("critic is not qualified")
    if certificate.get("positive_calibration_passed") is not True:
        raise VisualCriticQuorumError("positive calibration did not pass")
    if certificate.get("negative_calibration_passed") is not True:
        raise VisualCriticQuorumError("negative calibration did not pass")
    if verify_hash:
        _verify_self_hash(
            certificate,
            field="certificate_sha256",
            subject=f"{expected_role} certificate",
        )


def validate_critic_certificate(
    certificate: Mapping[str, Any],
    *,
    expected_role: str,
) -> None:
    _validate_certificate_fields(
        certificate,
        expected_role=expected_role,
        verify_hash=True,
    )


def build_critic_response(
    *,
    certificate: Mapping[str, Any],
    panel_bundle_sha256: str,
    status: str,
    verdict: str | None,
    confidence: float | None,
    raw_response_sha256: str,
    authority_claimed: bool = False,
    completion_claimed: bool = False,
) -> dict[str, Any]:
    """Seal one critic response envelope after transport persistence."""

    role = certificate.get("role")
    if role not in CRITIC_ROLES:
        raise VisualCriticQuorumError("response certificate role is invalid")
    validate_critic_certificate(certificate, expected_role=role)
    response = {
        "schema_version": SCHEMA_VERSION,
        "role": role,
        "model_id": certificate["model_id"],
        "model_sha256": certificate["model_sha256"],
        "runtime_sha256": certificate["runtime_sha256"],
        "family_id": certificate["family_id"],
        "certificate_sha256": certificate["certificate_sha256"],
        "panel_bundle_sha256": panel_bundle_sha256,
        "status": status,
        "verdict": verdict,
        "confidence": confidence,
        "raw_response_sha256": raw_response_sha256,
        "authority_claimed": authority_claimed,
        "completion_claimed": completion_claimed,
        "response_sha256": ZERO_SHA256,
    }
    _validate_response_fields(
        response,
        certificate=certificate,
        panel_bundle_sha256=panel_bundle_sha256,
        verify_hash=False,
    )
    return _seal(response, "response_sha256")


def _validate_response_fields(
    response: Mapping[str, Any],
    *,
    certificate: Mapping[str, Any],
    panel_bundle_sha256: str,
    verify_hash: bool,
) -> None:
    expected_fields = {
        "schema_version",
        "role",
        "model_id",
        "model_sha256",
        "runtime_sha256",
        "family_id",
        "certificate_sha256",
        "panel_bundle_sha256",
        "status",
        "verdict",
        "confidence",
        "raw_response_sha256",
        "authority_claimed",
        "completion_claimed",
        "response_sha256",
    }
    if not isinstance(response, Mapping) or set(response) != expected_fields:
        raise VisualCriticQuorumError("critic response field set mismatch")
    if response.get("schema_version") != SCHEMA_VERSION:
        raise VisualCriticQuorumError("critic response schema mismatch")
    for field in (
        "role",
        "model_id",
        "model_sha256",
        "runtime_sha256",
        "family_id",
        "certificate_sha256",
    ):
        if response.get(field) != certificate.get(field):
            raise VisualCriticQuorumError(f"critic response {field} mismatch")
    if response.get("panel_bundle_sha256") != _digest(
        panel_bundle_sha256,
        field="panel_bundle_sha256",
    ):
        raise VisualCriticQuorumError("critic response panel binding mismatch")
    _digest(response.get("raw_response_sha256"), field="raw_response_sha256")
    status = response.get("status")
    if status not in RESPONSE_STATUSES:
        raise VisualCriticQuorumError("critic response status is invalid")
    if status == "COMPLETE":
        if response.get("verdict") not in VERDICTS:
            raise VisualCriticQuorumError("complete critic response verdict is invalid")
        confidence = response.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, int | float)
            or not 0.0 <= float(confidence) <= 1.0
        ):
            raise VisualCriticQuorumError("critic confidence must be within 0..1")
    elif response.get("verdict") is not None or response.get("confidence") is not None:
        raise VisualCriticQuorumError("non-complete critic response must not claim a verdict")
    if response.get("authority_claimed") is not False:
        raise VisualCriticQuorumError("critic may not claim authority")
    if response.get("completion_claimed") is not False:
        raise VisualCriticQuorumError("critic may not claim completion")
    if verify_hash:
        _verify_self_hash(
            response,
            field="response_sha256",
            subject=f"{certificate['role']} response",
        )


def validate_critic_response(
    response: Mapping[str, Any],
    *,
    certificate: Mapping[str, Any],
    panel_bundle_sha256: str,
) -> None:
    _validate_response_fields(
        response,
        certificate=certificate,
        panel_bundle_sha256=panel_bundle_sha256,
        verify_hash=True,
    )


def _blocked_result(*, reason: str, hard_qa_outcome: str) -> dict[str, Any]:
    return _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "outcome": "VISUAL_CRITIC_BLOCKED",
            "reason": reason,
            "hard_qa_outcome": hard_qa_outcome,
            "panel_bundle_sha256": None,
            "primary_response_sha256": None,
            "juror_response_sha256": None,
            "authority_granted": False,
            "claims_forbidden": list(FORBIDDEN_CLAIMS),
            "quorum_sha256": ZERO_SHA256,
        },
        "quorum_sha256",
    )


def evaluate_visual_quorum(
    *,
    hard_qa_outcome: str,
    panel_bundle: Mapping[str, Any],
    panels: Mapping[str, bytes],
    primary_certificate: Mapping[str, Any],
    juror_certificate: Mapping[str, Any],
    primary_response: Mapping[str, Any],
    juror_response: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a bounded visual verdict; never grant final acceptance authority."""

    try:
        validate_panel_bundle(panel_bundle, panels)
        validate_critic_certificate(primary_certificate, expected_role="primary")
        validate_critic_certificate(juror_certificate, expected_role="juror")
        panel_sha256 = panel_bundle["panel_bundle_sha256"]
        validate_critic_response(
            primary_response,
            certificate=primary_certificate,
            panel_bundle_sha256=panel_sha256,
        )
        validate_critic_response(
            juror_response,
            certificate=juror_certificate,
            panel_bundle_sha256=panel_sha256,
        )
    except VisualCriticQuorumError as exc:
        return _blocked_result(
            reason=f"{type(exc).__name__}: immutable visual binding failed closed",
            hard_qa_outcome=hard_qa_outcome,
        )

    if hard_qa_outcome not in PASSING_HARD_QA:
        outcome = "ABSTAIN_HARD_QA_VETO"
        reason = "deterministic hard QA cannot be overridden"
    elif (
        primary_certificate["family_id"] == juror_certificate["family_id"]
        or primary_certificate["model_id"] == juror_certificate["model_id"]
        or primary_certificate["model_sha256"] == juror_certificate["model_sha256"]
    ):
        outcome = "ABSTAIN_CORRELATED_CRITICS"
        reason = "primary and juror are not independently bound models"
    elif (
        primary_response["status"] != "COMPLETE"
        or juror_response["status"] != "COMPLETE"
    ):
        outcome = "VISUAL_CRITIC_BLOCKED"
        reason = "one or more critics did not produce a complete response"
    elif (
        primary_response["verdict"] == "FAIL"
        or juror_response["verdict"] == "FAIL"
    ):
        outcome = "REJECT_VISUAL"
        reason = "at least one qualified visual role rejected the evidence"
    elif (
        primary_response["verdict"] != "PASS"
        or juror_response["verdict"] != "PASS"
    ):
        outcome = "ABSTAIN_VISUAL_DISAGREEMENT"
        reason = "qualified visual roles did not form a pass quorum"
    else:
        outcome = "VISUAL_QA_PASS_BOUNDED"
        reason = "qualified independent visual roles formed a bounded pass quorum"

    return _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "outcome": outcome,
            "reason": reason,
            "hard_qa_outcome": hard_qa_outcome,
            "panel_bundle_sha256": panel_bundle["panel_bundle_sha256"],
            "primary_response_sha256": primary_response["response_sha256"],
            "juror_response_sha256": juror_response["response_sha256"],
            "authority_granted": False,
            "claims_forbidden": list(FORBIDDEN_CLAIMS),
            "quorum_sha256": ZERO_SHA256,
        },
        "quorum_sha256",
    )


def validate_visual_quorum(
    result: Mapping[str, Any],
    *,
    hard_qa_outcome: str,
    panel_bundle: Mapping[str, Any],
    panels: Mapping[str, bytes],
    primary_certificate: Mapping[str, Any],
    juror_certificate: Mapping[str, Any],
    primary_response: Mapping[str, Any],
    juror_response: Mapping[str, Any],
) -> None:
    """Reject a rehashed quorum whose semantic decision drifted."""

    if not isinstance(result, Mapping):
        raise VisualCriticQuorumError("visual quorum result must be an object")
    _verify_self_hash(result, field="quorum_sha256", subject="visual quorum result")
    expected = evaluate_visual_quorum(
        hard_qa_outcome=hard_qa_outcome,
        panel_bundle=panel_bundle,
        panels=panels,
        primary_certificate=primary_certificate,
        juror_certificate=juror_certificate,
        primary_response=primary_response,
        juror_response=juror_response,
    )
    if dict(result) != expected:
        raise VisualCriticQuorumError("visual quorum deterministic replay mismatch")


__all__ = [
    "CRITIC_ROLES",
    "FORBIDDEN_CLAIMS",
    "PANEL_ROLES",
    "RESPONSE_STATUSES",
    "SCHEMA_VERSION",
    "VERDICTS",
    "VisualCriticQuorumError",
    "build_critic_certificate",
    "build_critic_response",
    "build_panel_bundle",
    "evaluate_visual_quorum",
    "validate_critic_certificate",
    "validate_critic_response",
    "validate_panel_bundle",
    "validate_visual_quorum",
]
