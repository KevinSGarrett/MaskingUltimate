"""Closed authority envelopes for advisory self-hosted engineering workers."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any


SCHEMA_VERSION = "maskfactory_worker_authority.v1"
ZERO_SHA256 = "0" * 64
MAX_TASK_BYTES = 64 * 1024
ALLOWED_OPERATIONS = (
    "analyze_packet",
    "diagnose_focused_tests",
    "propose_patch",
    "propose_tests",
)
AUTHORITY_CEILING = {
    "credentials": False,
    "tools": False,
    "git": False,
    "github": False,
    "destructive_actions": False,
    "infrastructure": False,
    "runpod_lifecycle": False,
    "tracker": False,
    "final_adoption": False,
}
SYSTEM_POLICY = (
    "You are an advisory engineering worker. Analyze only the supplied bounded "
    "packet and return a proposal. You have no tools, credentials, Git/GitHub, "
    "destructive-action, infrastructure, RunPod lifecycle, tracker, completion, "
    "or final-adoption authority."
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[opsu]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password)"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{16,}"
    ),
)
_REQUEST_FIELDS = {
    "schema_version",
    "mission_id",
    "packet_sha256",
    "allowed_paths",
    "allowed_operations",
    "worker_tools",
    "authority",
    "system_policy",
    "untrusted_task",
    "request_sha256",
}
_RESPONSE_FIELDS = {
    "schema_version",
    "mission_id",
    "packet_sha256",
    "request_sha256",
    "proposal",
    "tool_requests",
    "authority_claims",
    "completion_claimed",
    "response_sha256",
}


class WorkerAuthorityError(RuntimeError):
    """A worker request or response attempted to exceed its authority."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise WorkerAuthorityError("authority document is not canonical JSON") from exc


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    sealed = deepcopy(dict(value))
    sealed[field] = ZERO_SHA256
    sealed[field] = _canonical_sha256(sealed)
    return sealed


def _verify_self_hash(value: Mapping[str, Any], field: str) -> None:
    declared = value.get(field)
    if not isinstance(declared, str) or not _SHA256_RE.fullmatch(declared):
        raise WorkerAuthorityError(f"{field} is invalid")
    zeroed = deepcopy(dict(value))
    zeroed[field] = ZERO_SHA256
    if _canonical_sha256(zeroed) != declared:
        raise WorkerAuthorityError(f"{field} canonical self-hash mismatch")


def _identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise WorkerAuthorityError(f"{field} is invalid")
    return value


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise WorkerAuthorityError(f"{field} is invalid")
    return value


def _relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise WorkerAuthorityError("allowed path must be non-empty")
    if any(character in value for character in "\r\n\x00"):
        raise WorkerAuthorityError("allowed path contains a prohibited character")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or ":" in path.parts[0]
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise WorkerAuthorityError("allowed path escapes the packet")
    return path.as_posix()


def _safe_text(value: object, *, field: str, maximum_bytes: int) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise WorkerAuthorityError(f"{field} must be non-empty text")
    encoded = value.encode("utf-8")
    if len(encoded) > maximum_bytes:
        raise WorkerAuthorityError(f"{field} exceeds its byte cap")
    for pattern in _SECRET_PATTERNS:
        if pattern.search(value):
            raise WorkerAuthorityError(f"{field} contains possible secret material")
    return value


def _validate_authority(value: object, *, field: str) -> None:
    if value != AUTHORITY_CEILING:
        raise WorkerAuthorityError(f"{field} exceeds the fixed authority ceiling")


def build_worker_request(
    *,
    mission_id: str,
    packet_sha256: str,
    allowed_paths: Sequence[str],
    untrusted_task: str,
) -> dict[str, Any]:
    """Seal an untrusted task beneath the fixed no-tool authority ceiling."""

    if not isinstance(allowed_paths, Sequence) or isinstance(
        allowed_paths, (str, bytes)
    ):
        raise WorkerAuthorityError("allowed paths must be a sequence")
    normalized_paths = tuple(sorted(_relative_path(path) for path in allowed_paths))
    if not normalized_paths or len(normalized_paths) != len(set(normalized_paths)):
        raise WorkerAuthorityError("allowed paths must be non-empty and unique")
    return _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "mission_id": _identifier(mission_id, field="mission_id"),
            "packet_sha256": _sha256(packet_sha256, field="packet_sha256"),
            "allowed_paths": list(normalized_paths),
            "allowed_operations": list(ALLOWED_OPERATIONS),
            "worker_tools": [],
            "authority": dict(AUTHORITY_CEILING),
            "system_policy": SYSTEM_POLICY,
            "untrusted_task": _safe_text(
                untrusted_task,
                field="untrusted_task",
                maximum_bytes=MAX_TASK_BYTES,
            ),
            "request_sha256": ZERO_SHA256,
        },
        "request_sha256",
    )


def validate_worker_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Reject request tampering even when an attacker recomputes the self-hash."""

    if not isinstance(request, Mapping) or set(request) != _REQUEST_FIELDS:
        raise WorkerAuthorityError("worker request field set mismatch")
    _verify_self_hash(request, "request_sha256")
    if request.get("schema_version") != SCHEMA_VERSION:
        raise WorkerAuthorityError("worker request schema mismatch")
    _validate_authority(request.get("authority"), field="request authority")
    if request.get("worker_tools") != []:
        raise WorkerAuthorityError("worker tool contracts are prohibited")
    if request.get("allowed_operations") != list(ALLOWED_OPERATIONS):
        raise WorkerAuthorityError("worker operation set is not the fixed allowlist")
    rebuilt = build_worker_request(
        mission_id=_identifier(request.get("mission_id"), field="mission_id"),
        packet_sha256=_sha256(
            request.get("packet_sha256"),
            field="packet_sha256",
        ),
        allowed_paths=request.get("allowed_paths"),
        untrusted_task=_safe_text(
            request.get("untrusted_task"),
            field="untrusted_task",
            maximum_bytes=MAX_TASK_BYTES,
        ),
    )
    if request.get("system_policy") != SYSTEM_POLICY or rebuilt != dict(request):
        raise WorkerAuthorityError("worker request semantic binding mismatch")
    return rebuilt


def seal_worker_response(
    *,
    request: Mapping[str, Any],
    proposal: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal a model response for deterministic authority validation."""

    validated = validate_worker_request(request)
    if not isinstance(proposal, Mapping):
        raise WorkerAuthorityError("worker proposal must be an object")
    proposal_copy = deepcopy(dict(proposal))
    try:
        serialized = json.dumps(
            proposal_copy,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise WorkerAuthorityError("worker proposal is not canonical JSON") from exc
    _safe_text(serialized, field="worker proposal", maximum_bytes=MAX_TASK_BYTES)
    return _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "mission_id": validated["mission_id"],
            "packet_sha256": validated["packet_sha256"],
            "request_sha256": validated["request_sha256"],
            "proposal": proposal_copy,
            "tool_requests": [],
            "authority_claims": dict(AUTHORITY_CEILING),
            "completion_claimed": False,
            "response_sha256": ZERO_SHA256,
        },
        "response_sha256",
    )


def validate_worker_response(
    response: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate exact identity, no-tool behavior, and all authority refusals."""

    validated_request = validate_worker_request(request)
    if not isinstance(response, Mapping) or set(response) != _RESPONSE_FIELDS:
        raise WorkerAuthorityError("worker response field set mismatch")
    _verify_self_hash(response, "response_sha256")
    if (
        response.get("schema_version") != SCHEMA_VERSION
        or response.get("mission_id") != validated_request["mission_id"]
        or response.get("packet_sha256") != validated_request["packet_sha256"]
        or response.get("request_sha256") != validated_request["request_sha256"]
    ):
        raise WorkerAuthorityError("worker response identity mismatch")
    if response.get("tool_requests") != []:
        raise WorkerAuthorityError("worker requested an unauthorized tool")
    _validate_authority(
        response.get("authority_claims"),
        field="worker response authority",
    )
    if response.get("completion_claimed") is not False:
        raise WorkerAuthorityError("worker claimed completion authority")
    rebuilt = seal_worker_response(
        request=validated_request,
        proposal=response.get("proposal"),
    )
    if rebuilt != dict(response):
        raise WorkerAuthorityError("worker response semantic binding mismatch")
    return rebuilt


__all__ = [
    "ALLOWED_OPERATIONS",
    "AUTHORITY_CEILING",
    "MAX_TASK_BYTES",
    "SCHEMA_VERSION",
    "SYSTEM_POLICY",
    "WorkerAuthorityError",
    "build_worker_request",
    "seal_worker_response",
    "validate_worker_request",
    "validate_worker_response",
]
