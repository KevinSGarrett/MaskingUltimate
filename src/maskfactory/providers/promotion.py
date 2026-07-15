"""Fail-closed promotion gate for externally sourced specialist providers.

Download, model-card, installation, and smoke evidence may qualify a provider
for shadow execution, but never for a production role.  This module validates
the immutable packet required immediately before a specialist role mutation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from maskfactory.governance import CONTENT_COMPATIBILITY_KEYS

from .benchmark_policy import (
    SpecialistBenchmarkPolicyError,
    load_specialist_margin_manifest,
    validate_specialist_benchmark_results,
)

LOCAL_GPU_BUDGET_BYTES = 8 * 1024**3
PROMOTION_AUTHORITY = "specialist_role_promotion_gate"
REQUIRED_IDENTITY_HASHES = {
    "source_tree_sha256",
    "checkpoint_sha256",
    "runtime_lock_sha256",
    "license_evidence_sha256",
    "content_decision_sha256",
}


class SpecialistPromotionError(ValueError):
    """A specialist packet lacks one or more non-negotiable prerequisites."""


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SpecialistPromotionError(f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise SpecialistPromotionError(f"{field} must include a timezone")
    return parsed


def _validate_identity_hashes(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != REQUIRED_IDENTITY_HASHES:
        raise SpecialistPromotionError("promotion identity hashes are incomplete")
    if any(not _is_sha256(digest) for digest in value.values()):
        raise SpecialistPromotionError("promotion identity hash is invalid")


def _validate_content_and_license(packet: Mapping[str, Any]) -> None:
    compatibility = packet.get("content_compatibility")
    if not isinstance(compatibility, Mapping) or set(compatibility) != set(
        CONTENT_COMPATIBILITY_KEYS
    ):
        raise SpecialistPromotionError("promotion content decisions are incomplete")
    if any(compatibility[lane] != "allowed" for lane in CONTENT_COMPATIBILITY_KEYS):
        raise SpecialistPromotionError("promotion content decision is not allowed")
    license_gate = packet.get("license_gate")
    if not isinstance(license_gate, Mapping) or set(license_gate) != {
        "verify_license",
        "checkpoint_decision",
    }:
        raise SpecialistPromotionError("promotion license gate is incomplete")
    if (
        license_gate["verify_license"] is not False
        or license_gate["checkpoint_decision"] != "allowed"
    ):
        raise SpecialistPromotionError("promotion license gate is unresolved")


def _validate_runtime_reliability(value: Any) -> None:
    required = {
        "mode",
        "hardware_profile_sha256",
        "peak_reserved_bytes",
        "repetitions",
        "deterministic",
        "oom_count",
        "crash_count",
        "alternate_runtime_approval",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise SpecialistPromotionError("promotion runtime reliability evidence is incomplete")
    if not _is_sha256(value["hardware_profile_sha256"]):
        raise SpecialistPromotionError("promotion hardware profile hash is invalid")
    repetitions = value["repetitions"]
    peak = value["peak_reserved_bytes"]
    if (
        isinstance(repetitions, bool)
        or not isinstance(repetitions, int)
        or repetitions < 2
        or isinstance(peak, bool)
        or not isinstance(peak, int)
        or peak < 0
        or value["deterministic"] is not True
        or value["oom_count"] != 0
        or value["crash_count"] != 0
    ):
        raise SpecialistPromotionError("promotion runtime is not reliable")

    mode = value["mode"]
    approval = value["alternate_runtime_approval"]
    if mode == "local_8gb":
        if peak > LOCAL_GPU_BUDGET_BYTES:
            raise SpecialistPromotionError("promotion exceeds the local 8 GB GPU budget")
        if approval is not None:
            raise SpecialistPromotionError(
                "local 8 GB promotion cannot carry alternate-runtime approval"
            )
        return
    if mode != "approved_alternate":
        raise SpecialistPromotionError("promotion runtime mode is invalid")
    if not isinstance(approval, Mapping) or set(approval) != {
        "approved_by",
        "approved_at",
        "runtime_key",
        "reason",
        "evidence_sha256",
    }:
        raise SpecialistPromotionError("alternate runtime approval is incomplete")
    if (
        approval["approved_by"] != "Kevin"
        or not isinstance(approval["runtime_key"], str)
        or not approval["runtime_key"]
        or not isinstance(approval["reason"], str)
        or not approval["reason"]
        or not _is_sha256(approval["evidence_sha256"])
    ):
        raise SpecialistPromotionError("alternate runtime approval is invalid")
    _timestamp(approval["approved_at"], "alternate_runtime_approval.approved_at")


def _validate_rollback(
    value: Any,
    *,
    candidate_key: str,
    target_role: str,
) -> None:
    required = {
        "candidate_provider",
        "incumbent_provider",
        "target_role",
        "one_command",
        "rollback_observed",
        "restore_observed",
        "result",
        "tested_at",
        "evidence_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise SpecialistPromotionError("promotion rollback evidence is incomplete")
    incumbent = value["incumbent_provider"]
    if (
        value["candidate_provider"] != candidate_key
        or value["target_role"] != target_role
        or not isinstance(incumbent, str)
        or not incumbent
        or incumbent == candidate_key
        or not isinstance(value["one_command"], str)
        or not value["one_command"]
        or value["rollback_observed"] is not True
        or value["restore_observed"] is not True
        or value["result"] != "pass"
        or not _is_sha256(value["evidence_sha256"])
    ):
        raise SpecialistPromotionError("promotion rollback evidence did not pass")
    _timestamp(value["tested_at"], "rollback_evidence.tested_at")


def validate_specialist_promotion_packet(
    packet: Mapping[str, Any],
    *,
    margin_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate every precondition without changing provider roles or lifecycle.

    The returned summary is safe to attach to a subsequent transactional role
    mutation.  This function intentionally grants no role, serving, mask, or
    gold authority by itself.
    """
    required = {
        "schema_version",
        "authority",
        "candidate_key",
        "target_role",
        "lifecycle_state",
        "identity_hashes",
        "content_compatibility",
        "license_gate",
        "benchmark_results",
        "runtime_reliability",
        "rollback_evidence",
        "sha256",
    }
    if not isinstance(packet, Mapping) or set(packet) != required:
        raise SpecialistPromotionError("specialist promotion packet structure is invalid")
    if packet["schema_version"] != "1.0.0" or packet["authority"] != PROMOTION_AUTHORITY:
        raise SpecialistPromotionError("specialist promotion packet identity is invalid")
    candidate_key = packet["candidate_key"]
    target_role = packet["target_role"]
    if (
        not isinstance(candidate_key, str)
        or not candidate_key
        or not isinstance(target_role, str)
        or not target_role
        or packet["lifecycle_state"] != "benchmarked"
    ):
        raise SpecialistPromotionError("promotion requires a benchmarked candidate and role")

    _validate_identity_hashes(packet["identity_hashes"])
    _validate_content_and_license(packet)
    if margin_manifest is None:
        margin_manifest, _ = load_specialist_margin_manifest()
    benchmark_results = packet["benchmark_results"]
    if not isinstance(benchmark_results, Mapping):
        raise SpecialistPromotionError("specialist benchmark results are missing")
    if benchmark_results.get("role") != target_role:
        raise SpecialistPromotionError("specialist benchmark role does not match promotion")
    try:
        validate_specialist_benchmark_results(
            benchmark_results,
            margin_manifest=margin_manifest,
        )
    except SpecialistBenchmarkPolicyError as exc:
        raise SpecialistPromotionError(str(exc)) from exc

    _validate_runtime_reliability(packet["runtime_reliability"])
    _validate_rollback(
        packet["rollback_evidence"],
        candidate_key=candidate_key,
        target_role=target_role,
    )
    payload = {key: value for key, value in packet.items() if key != "sha256"}
    if packet["sha256"] != _canonical_sha256(payload):
        raise SpecialistPromotionError("specialist promotion packet hash mismatch")
    return {
        "candidate_key": candidate_key,
        "target_role": target_role,
        "lifecycle_state": "benchmarked",
        "rollback_provider": packet["rollback_evidence"]["incumbent_provider"],
        "packet_sha256": packet["sha256"],
        "authority": "validated_prerequisites_only_no_role_or_gold_authority",
    }


__all__: Sequence[str] = (
    "LOCAL_GPU_BUDGET_BYTES",
    "PROMOTION_AUTHORITY",
    "SpecialistPromotionError",
    "validate_specialist_promotion_packet",
)
