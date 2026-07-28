"""Fail-closed Serverless V3 capability decisions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "maskfactory.serverless_v3_runtime_gate.v1"
PREFLIGHT_SCHEMA_VERSION = "maskfactory.serverless_v3_runtime_preflight.v1"
PREFLIGHT_ARTIFACT_TYPE = "maskfactory_serverless_gpu_runtime_preflight"
REQUIRED_INPUTS = ("deferred_queue", "execution", "registry", "runner")
REQUIRED_MODULES = ("torch", "transformers", "vllm")
AUTHORITY_FLAGS = (
    "authority_claimed",
    "critic_role_authority_granted",
    "visual_acceptance_claimed",
    "gold_or_training_authority_granted",
)


class ServerlessV3RuntimeGateError(ValueError):
    """Preflight evidence is incomplete, drifted, or overclaims authority."""


def canonical_sha256(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ServerlessV3RuntimeGateError(f"{field} must be a SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ServerlessV3RuntimeGateError(f"{field} must be a SHA-256") from exc
    return value


def _bindings(value: Any, field: str, allow_none: bool) -> dict[str, str | None]:
    if not isinstance(value, Mapping) or set(value) != set(REQUIRED_INPUTS):
        raise ServerlessV3RuntimeGateError(f"{field} keys are incomplete or unknown")
    result: dict[str, str | None] = {}
    for name in REQUIRED_INPUTS:
        current = value[name]
        result[name] = None if current is None and allow_none else _hash(current, f"{field}.{name}")
    return result


def verify_serverless_v3_runtime_preflight(document: Mapping[str, Any]) -> None:
    """Verify intrinsic preflight integrity without treating CUDA as V3 readiness."""

    if not isinstance(document, Mapping):
        raise ServerlessV3RuntimeGateError("preflight must be an object")
    if (
        document.get("schema_version") != PREFLIGHT_SCHEMA_VERSION
        or document.get("artifact_type") != PREFLIGHT_ARTIFACT_TYPE
    ):
        raise ServerlessV3RuntimeGateError("preflight schema drift")
    if any(document.get(flag) is not False for flag in AUTHORITY_FLAGS):
        raise ServerlessV3RuntimeGateError("preflight authority drift")
    if not isinstance(document.get("cuda_available"), bool):
        raise ServerlessV3RuntimeGateError("preflight CUDA state is invalid")
    modules = document.get("modules")
    if not isinstance(modules, Mapping) or not set(REQUIRED_MODULES).issubset(modules):
        raise ServerlessV3RuntimeGateError("preflight module states are incomplete")
    for name in REQUIRED_MODULES:
        if not isinstance(modules[name], Mapping) or not isinstance(
            modules[name].get("available"), bool
        ):
            raise ServerlessV3RuntimeGateError(f"preflight module state is invalid:{name}")
    _bindings(document.get("v3_input_sha256s"), "preflight.v3_input_sha256s", True)
    sealed = {key: value for key, value in document.items() if key != "self_sha256"}
    if document.get("self_sha256") != canonical_sha256(sealed):
        raise ServerlessV3RuntimeGateError("preflight self hash drift")


def build_serverless_v3_runtime_gate(
    *,
    preflight: Mapping[str, Any],
    expected_input_sha256s: Mapping[str, Any],
    provider_binding_sha256s: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a provider-binding-aware, fail-closed V3 admission decision."""

    verify_serverless_v3_runtime_preflight(preflight)
    expected = _bindings(expected_input_sha256s, "expected_input_sha256s", False)
    provider = _bindings(provider_binding_sha256s, "provider_binding_sha256s", False)
    if provider != expected:
        raise ServerlessV3RuntimeGateError(
            "provider binding receipt does not match expected inputs"
        )
    observed = _bindings(preflight["v3_input_sha256s"], "preflight.v3_input_sha256s", True)
    modules = preflight["modules"]
    missing_modules = [
        name
        for name in REQUIRED_MODULES
        if modules[name]["available"] is not True or modules[name].get("import_error")
    ]
    reasons: list[str] = []
    if observed != expected:
        reasons.append("preflight_internal_binding_report_incomplete")
    if preflight["cuda_available"] is not True:
        reasons.append("cuda_unavailable")
    if missing_modules:
        reasons.append("required_runtime_modules_unavailable")
    allowed = not reasons
    if allowed:
        next_action = "submit_the_hash_bound_protocol_v3_control_screening_job_through_the_broker"
    elif missing_modules:
        next_action = (
            "do_not_submit_protocol_v3_to_this_immutable_serverless_image; "
            "continue_another_cpu_safe_lane_until_explicit_authority_exists_for_an_image_update"
        )
    else:
        next_action = (
            "repair_and_repeat_the_hash_bound_runtime_preflight_before_protocol_v3_submission"
        )
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "maskfactory_serverless_v3_runtime_capability_gate",
        "authority_claimed": False,
        "critic_role_authority_granted": False,
        "visual_acceptance_claimed": False,
        "gold_or_training_authority_granted": False,
        "preflight_self_sha256": preflight["self_sha256"],
        "expected_input_sha256s": dict(expected),
        "provider_binding_sha256s": dict(provider),
        "preflight_input_sha256s": dict(observed),
        "cuda_available": preflight["cuda_available"],
        "missing_required_modules": missing_modules,
        "internal_bindings_complete": observed == expected,
        "v3_submission_allowed": allowed,
        "reason_codes": reasons,
        "next_action": next_action,
        "claim_limits": [
            "Runtime-admission evidence is not visual review or role qualification.",
            "Provider binding evidence cannot substitute for required runtime dependencies.",
            "No gold, training, certification, or promotion authority is granted.",
        ],
    }
    result["self_sha256"] = canonical_sha256(result)
    verify_serverless_v3_runtime_gate(result)
    return result


def verify_serverless_v3_runtime_gate(document: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "artifact_type",
        *AUTHORITY_FLAGS,
        "preflight_self_sha256",
        "expected_input_sha256s",
        "provider_binding_sha256s",
        "preflight_input_sha256s",
        "cuda_available",
        "missing_required_modules",
        "internal_bindings_complete",
        "v3_submission_allowed",
        "reason_codes",
        "next_action",
        "claim_limits",
        "self_sha256",
    }
    if not isinstance(document, Mapping) or set(document) != required:
        raise ServerlessV3RuntimeGateError("runtime gate fields are incomplete or unknown")
    if (
        document["schema_version"] != SCHEMA_VERSION
        or document["artifact_type"] != "maskfactory_serverless_v3_runtime_capability_gate"
    ):
        raise ServerlessV3RuntimeGateError("runtime gate schema drift")
    if any(document[flag] is not False for flag in AUTHORITY_FLAGS):
        raise ServerlessV3RuntimeGateError("runtime gate authority drift")
    _hash(document["preflight_self_sha256"], "preflight_self_sha256")
    expected = _bindings(document["expected_input_sha256s"], "expected_input_sha256s", False)
    provider = _bindings(document["provider_binding_sha256s"], "provider_binding_sha256s", False)
    observed = _bindings(document["preflight_input_sha256s"], "preflight_input_sha256s", True)
    if provider != expected or document["internal_bindings_complete"] is not (observed == expected):
        raise ServerlessV3RuntimeGateError("runtime gate binding state drift")
    if not isinstance(document["cuda_available"], bool):
        raise ServerlessV3RuntimeGateError("runtime gate CUDA state is invalid")
    if not isinstance(document["missing_required_modules"], list) or any(
        name not in REQUIRED_MODULES for name in document["missing_required_modules"]
    ):
        raise ServerlessV3RuntimeGateError("runtime gate module state is invalid")
    if not isinstance(document["reason_codes"], list) or not all(
        isinstance(reason, str) and reason for reason in document["reason_codes"]
    ):
        raise ServerlessV3RuntimeGateError("runtime gate reason codes are invalid")
    if document["v3_submission_allowed"] is not (not document["reason_codes"]):
        raise ServerlessV3RuntimeGateError("runtime gate admission decision drift")
    sealed = {key: value for key, value in document.items() if key != "self_sha256"}
    if document["self_sha256"] != canonical_sha256(sealed):
        raise ServerlessV3RuntimeGateError("runtime gate self hash drift")
