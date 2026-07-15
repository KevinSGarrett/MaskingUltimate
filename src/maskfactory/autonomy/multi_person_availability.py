"""Derive multi-person tournament family availability from governed repository evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..io.hashing import sha256_file
from ..validation import ArtifactValidationError, require_valid_document

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY = ROOT / "qa" / "governance" / "multi_person_family_availability_v1.json"
DEFAULT_MODEL_REGISTRY = ROOT / "models" / "model_registry.json"
DEFAULT_RUNTIME_MATRIX = ROOT / "env" / "provider_runtime_matrix.json"
LOCKED_POLICY_SHA256 = "860d1e1300737102b9c4f954d06112e74c45d79a805c2cbbda1a1a1a4827fa8d"


class MultiPersonAvailabilityError(ValueError):
    """The governed family inventory is stale, incomplete, or internally inconsistent."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_json(path: Path, name: str) -> dict[str, Any]:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MultiPersonAvailabilityError(f"{name} is missing or invalid") from exc
    if not isinstance(document, dict):
        raise MultiPersonAvailabilityError(f"{name} must be an object")
    return document


def _policy(path: Path) -> dict[str, Any]:
    document = _load_json(path, "multi-person family availability policy")
    try:
        require_valid_document(document, "multi_person_family_availability_policy")
    except ArtifactValidationError as exc:
        raise MultiPersonAvailabilityError(str(exc)) from exc
    payload = {key: value for key, value in document.items() if key != "sha256"}
    digest = _canonical_sha256(payload)
    if document["sha256"] != digest or digest != LOCKED_POLICY_SHA256:
        raise MultiPersonAvailabilityError("multi-person family availability policy hash drifted")
    return document


def _registry_models(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    models = document.get("models")
    if not isinstance(models, list):
        raise MultiPersonAvailabilityError("model registry models are missing")
    output = {}
    for model in models:
        if not isinstance(model, dict) or not isinstance(model.get("key"), str):
            raise MultiPersonAvailabilityError("model registry entry identity is invalid")
        if model["key"] in output:
            raise MultiPersonAvailabilityError("model registry provider key is duplicated")
        output[model["key"]] = model
    return output


def _runtime_entries(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    payload = {key: value for key, value in document.items() if key != "manifest_sha256"}
    if document.get("manifest_sha256") != _canonical_sha256(payload):
        raise MultiPersonAvailabilityError("provider runtime matrix manifest hash drifted")
    runtimes = document.get("runtimes")
    if not isinstance(runtimes, list):
        raise MultiPersonAvailabilityError("provider runtime matrix entries are missing")
    output = {}
    for runtime in runtimes:
        if not isinstance(runtime, dict) or not isinstance(runtime.get("provider"), str):
            raise MultiPersonAvailabilityError("provider runtime identity is invalid")
        if runtime["provider"] in output:
            raise MultiPersonAvailabilityError("provider runtime identity is duplicated")
        for artifact in runtime.get("artifacts", []):
            relative = artifact.get("path")
            digest = artifact.get("sha256")
            if not isinstance(relative, str) or not isinstance(digest, str):
                raise MultiPersonAvailabilityError("provider runtime artifact identity is invalid")
            path = (ROOT / relative).resolve()
            try:
                path.relative_to(ROOT.resolve())
            except ValueError as exc:
                raise MultiPersonAvailabilityError(
                    "provider runtime artifact escapes repository"
                ) from exc
            if not path.is_file() or sha256_file(path) != digest:
                raise MultiPersonAvailabilityError(
                    f"provider runtime artifact is missing or stale: {relative}"
                )
        output[runtime["provider"]] = runtime
    return output


def _registry_clause(
    keys: list[str], models: dict[str, dict[str, Any]], eligible_lifecycles: set[str]
) -> tuple[bool, list[dict[str, Any]]]:
    evidence = []
    eligible = False
    for key in keys:
        model = models.get(key)
        if model is None:
            evidence.append({"key": key, "status": "missing", "identity_sha256": None})
            continue
        content = model.get("content_compatibility", {})
        license_review = model.get("license_review", {})
        qualified = (
            model.get("lifecycle_state") in eligible_lifecycles
            and model.get("verified") is True
            and license_review.get("status") == "verified"
            and content.get("adult_nonexplicit") == "allowed"
            and content.get("consensual_explicit_adult") == "allowed"
            and isinstance(model.get("sha256") or model.get("digest"), str)
        )
        evidence.append(
            {
                "key": key,
                "status": "eligible" if qualified else "ineligible",
                "identity_sha256": _canonical_sha256(model),
            }
        )
        eligible = eligible or qualified
    return eligible, evidence


def _runtime_clause(
    keys: list[str], runtimes: dict[str, dict[str, Any]], eligible_statuses: set[str]
) -> tuple[bool, list[dict[str, Any]]]:
    evidence = []
    eligible = False
    for key in keys:
        runtime = runtimes.get(key)
        if runtime is None:
            evidence.append({"key": key, "status": "missing", "identity_sha256": None})
            continue
        qualified = (
            runtime.get("status") in eligible_statuses
            and runtime.get("checkpoint_status") == "installed"
            and runtime.get("smoke_status") == "pass"
            and runtime.get("may_author_gold") is False
        )
        evidence.append(
            {
                "key": key,
                "status": "eligible" if qualified else "ineligible",
                "identity_sha256": _canonical_sha256(runtime),
            }
        )
        eligible = eligible or qualified
    return eligible, evidence


def _internal_clause(keys: list[str]) -> tuple[bool, list[dict[str, Any]]]:
    evidence = []
    eligible = True
    for key in keys:
        path = (ROOT / key).resolve()
        try:
            path.relative_to(ROOT.resolve())
        except ValueError as exc:
            raise MultiPersonAvailabilityError("internal family source escapes repository") from exc
        present = path.is_file()
        evidence.append(
            {
                "key": key,
                "status": "eligible" if present else "missing",
                "identity_sha256": sha256_file(path) if present else None,
            }
        )
        eligible = eligible and present
    return eligible, evidence


def build_multi_person_availability_snapshot(
    *,
    policy_path: Path = DEFAULT_POLICY,
    model_registry_path: Path = DEFAULT_MODEL_REGISTRY,
    runtime_matrix_path: Path = DEFAULT_RUNTIME_MATRIX,
) -> dict[str, Any]:
    """Build a deterministic snapshot; no caller may self-assert provider availability."""
    policy = _policy(policy_path)
    registry = _load_json(model_registry_path, "model registry")
    runtime_matrix = _load_json(runtime_matrix_path, "provider runtime matrix")
    models = _registry_models(registry)
    runtimes = _runtime_entries(runtime_matrix)
    eligible_lifecycles = set(policy["eligible_registry_lifecycles"])
    eligible_statuses = set(policy["eligible_runtime_statuses"])
    families = {}
    for family, family_policy in sorted(policy["families"].items()):
        clause_rows = []
        family_available = False
        for clause in family_policy["clauses"]:
            source_kind = clause["source_kind"]
            keys = clause["keys"]
            if source_kind == "registry_any":
                eligible, evidence = _registry_clause(keys, models, eligible_lifecycles)
            elif source_kind == "runtime_any":
                eligible, evidence = _runtime_clause(keys, runtimes, eligible_statuses)
            else:
                eligible, evidence = _internal_clause(keys)
            clause_rows.append(
                {
                    "source_kind": source_kind,
                    "keys": keys,
                    "eligible": eligible,
                    "evidence": evidence,
                }
            )
            family_available = family_available or eligible
        families[family] = {
            "available": family_available,
            "reason_code": (
                "governed_source_eligible" if family_available else "no_governed_source_eligible"
            ),
            "clauses": clause_rows,
        }
    snapshot: dict[str, Any] = {
        "policy_sha256": policy["sha256"],
        "model_registry_sha256": sha256_file(Path(model_registry_path)),
        "runtime_matrix_sha256": sha256_file(Path(runtime_matrix_path)),
        "families": families,
    }
    snapshot["sha256"] = _canonical_sha256(snapshot)
    return snapshot


__all__ = [
    "DEFAULT_MODEL_REGISTRY",
    "DEFAULT_POLICY",
    "DEFAULT_RUNTIME_MATRIX",
    "LOCKED_POLICY_SHA256",
    "MultiPersonAvailabilityError",
    "build_multi_person_availability_snapshot",
]
