"""Fail-closed operating-profile, artifact-license, and lifecycle governance.

Version-1 registries remain readable as historical evidence.  Version-2 live
registries must declare the private, personal, noncommercial operating profile.
Source subject matter is not activation authority.
Sapiens2 is excluded because its exact license cannot support MaskFactory's
required unrestricted input scope; it may be named only in an exclusion record.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

USE_PROFILE = "private_personal_noncommercial"
ACTIVE_REGISTRY_SCHEMA_VERSION = "2.0.0"
HARD_EXCLUDED_MODEL_TOKENS = {"sapiens2", "sapiens_2"}
PROVIDER_LIFECYCLE_STATES = {
    "planned",
    "installed",
    "benchmarked",
    "promoted",
    "reference_only",
    "retired",
}
ACTIVATABLE_PROVIDER_STATES = {"installed", "benchmarked", "promoted"}


class GovernancePolicyError(ValueError):
    """A registry does not satisfy the active operating-profile policy."""


def _major_version(document: Mapping[str, Any], *, registry_name: str) -> int:
    raw_value = document.get("schema_version")
    if raw_value is None:
        raise GovernancePolicyError(f"{registry_name} schema_version is required")
    raw = str(raw_value)
    try:
        return int(raw.split(".", maxsplit=1)[0])
    except ValueError as exc:
        raise GovernancePolicyError(f"invalid registry schema_version: {raw}") from exc


def _validate_active_version(
    document: Mapping[str, Any],
    *,
    registry_name: str,
    allow_legacy: bool,
) -> bool:
    """Return whether a document is legacy and reject implicit active downgrades."""
    major = _major_version(document, registry_name=registry_name)
    if major < 2:
        if allow_legacy:
            return True
        raise GovernancePolicyError(
            f"{registry_name} schema {document['schema_version']} is historical-only; "
            f"active use requires {ACTIVE_REGISTRY_SCHEMA_VERSION}"
        )
    if str(document["schema_version"]) != ACTIVE_REGISTRY_SCHEMA_VERSION:
        raise GovernancePolicyError(
            f"unsupported {registry_name} schema_version {document['schema_version']}; "
            f"expected {ACTIVE_REGISTRY_SCHEMA_VERSION}"
        )
    return False


def _validate_policy_fields(document: Mapping[str, Any], *, registry_name: str) -> None:
    if document.get("use_profile") != USE_PROFILE:
        raise GovernancePolicyError(f"{registry_name} use_profile must be {USE_PROFILE}")
    if document.get("distribution_allowed") is not False:
        raise GovernancePolicyError(f"{registry_name} distribution_allowed must be false")
    if document.get("commercial_deployment") is not False:
        raise GovernancePolicyError(f"{registry_name} commercial_deployment must be false")


def _contains_hard_excluded_token(entry: Mapping[str, Any]) -> bool:
    fields = (
        entry.get("key"),
        entry.get("provider"),
        entry.get("family"),
        entry.get("version"),
        entry.get("version_tag"),
        entry.get("source_url"),
        entry.get("repo"),
        entry.get("file"),
    )
    normalized = " ".join(str(value).lower() for value in fields if value is not None)
    normalized = normalized.replace("-", "_").replace(" ", "_")
    return any(token in normalized for token in HARD_EXCLUDED_MODEL_TOKENS)


def provider_activation_issues(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """Return deterministic blockers for activating one provider.

    Catalog registration and artifact presence do not imply activation.  In
    particular, ``verify_license: true`` is an operational blocker rather than
    an informational reminder.
    """
    issues: list[str] = []
    lifecycle_state = entry.get("lifecycle_state")
    if lifecycle_state not in ACTIVATABLE_PROVIDER_STATES:
        issues.append(f"lifecycle_state={lifecycle_state!r} is not activatable")
    issues.extend(_license_layer_issues(entry))
    if entry.get("verify_license") is True:
        issues.append("license verification is unresolved")
    elif entry.get("verify_license") is not False:
        issues.append("verify_license must be an explicit boolean")
    else:
        source = entry.get("license_source")
        digest = entry.get("license_snapshot_sha256")
        reviewed_at = entry.get("license_reviewed_at")
        if not isinstance(source, str) or not source.startswith("https://"):
            issues.append("license_source is missing or is not HTTPS")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            issues.append("license_snapshot_sha256 is missing or invalid")
        try:
            reviewed = datetime.fromisoformat(str(reviewed_at).replace("Z", "+00:00"))
        except ValueError:
            reviewed = None
        if reviewed is None or reviewed.tzinfo is None:
            issues.append("license_reviewed_at is missing or lacks a timezone")
    return tuple(issues)


def _license_layer_issues(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """Make a checkpoint decision authoritative over any repository-level grant."""
    layers = entry.get("license_layers")
    if layers is None:
        return ()
    if not isinstance(layers, Mapping) or set(layers) != {
        "repository",
        "checkpoint",
        "effective_scope",
        "evidence_bundle_sha256",
    }:
        return ("license_layers must contain exact repository/checkpoint evidence",)
    issues = []
    for scope in ("repository", "checkpoint"):
        evidence = layers.get(scope)
        if not isinstance(evidence, Mapping) or set(evidence) != {
            "decision",
            "source_url",
            "snapshot_sha256",
            "reviewed_at",
        }:
            issues.append(f"license_layers.{scope} evidence is incomplete")
            continue
        if evidence.get("decision") not in {"allowed", "prohibited", "unclear"}:
            issues.append(f"license_layers.{scope}.decision is invalid")
        if not str(evidence.get("source_url", "")).startswith("https://"):
            issues.append(f"license_layers.{scope}.source_url is not HTTPS")
        digest = evidence.get("snapshot_sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            issues.append(f"license_layers.{scope}.snapshot_sha256 is invalid")
        try:
            reviewed = datetime.fromisoformat(
                str(evidence.get("reviewed_at")).replace("Z", "+00:00")
            )
        except ValueError:
            reviewed = None
        if reviewed is None or reviewed.tzinfo is None:
            issues.append(f"license_layers.{scope}.reviewed_at lacks a timezone")
    if layers.get("effective_scope") != "checkpoint":
        issues.append("checkpoint license must be the effective scope")
    canonical = {
        key: layers[key] for key in ("repository", "checkpoint", "effective_scope") if key in layers
    }
    expected_hash = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if layers.get("evidence_bundle_sha256") != expected_hash:
        issues.append("license layer evidence bundle hash mismatch")
    checkpoint = layers.get("checkpoint")
    checkpoint_decision = checkpoint.get("decision") if isinstance(checkpoint, Mapping) else None
    if checkpoint_decision != "allowed":
        issues.append(
            f"checkpoint-specific license decision={checkpoint_decision!r}, expected 'allowed'"
        )
    return tuple(issues)


def validate_external_source_registry(
    document: Mapping[str, Any], *, allow_legacy: bool = False
) -> dict[str, Any]:
    """Validate an active external-source registry.

    Historical registries are readable only when the caller opts in explicitly;
    an active loader must never obtain policy bypass by omitting or downgrading
    ``schema_version``.
    """
    if _validate_active_version(
        document,
        registry_name="external-source registry",
        allow_legacy=allow_legacy,
    ):
        return {"schema_version": str(document.get("schema_version", "1.0.0")), "legacy": True}
    _validate_policy_fields(document, registry_name="external-source registry")
    providers = document.get("providers")
    if not isinstance(providers, Mapping):
        raise GovernancePolicyError("external-source registry providers must be a mapping")
    for name, entry in providers.items():
        if not isinstance(entry, Mapping):
            raise GovernancePolicyError(f"provider {name} must be a mapping")
        if _contains_hard_excluded_token({"provider": name, **entry}):
            raise GovernancePolicyError(f"hard-excluded provider is installable: {name}")
        lifecycle_state = entry.get("lifecycle_state")
        if lifecycle_state not in PROVIDER_LIFECYCLE_STATES:
            raise GovernancePolicyError(
                f"provider {name} lifecycle_state must be one of "
                f"{sorted(PROVIDER_LIFECYCLE_STATES)}"
            )
        if lifecycle_state in ACTIVATABLE_PROVIDER_STATES:
            layer_issues = _license_layer_issues(entry)
            if layer_issues:
                raise GovernancePolicyError(
                    f"provider {name} checkpoint license blocks activation: "
                    + "; ".join(layer_issues)
                )

    exclusions = document.get("hard_exclusions")
    if not isinstance(exclusions, Mapping) or not isinstance(exclusions.get("sapiens2"), Mapping):
        raise GovernancePolicyError("external-source registry must record Sapiens2 hard exclusion")
    sapiens2 = exclusions["sapiens2"]
    if (
        sapiens2.get("install_allowed") is not False
        or sapiens2.get("benchmark_allowed") is not False
    ):
        raise GovernancePolicyError("Sapiens2 exclusion must forbid installation and benchmarking")
    return {"schema_version": str(document["schema_version"]), "legacy": False}


def validate_model_registry(
    document: Mapping[str, Any], *, allow_legacy: bool = False
) -> dict[str, Any]:
    """Validate an active model registry and reject every Sapiens2 artifact."""
    if _validate_active_version(
        document,
        registry_name="model registry",
        allow_legacy=allow_legacy,
    ):
        return {"schema_version": str(document.get("schema_version", "1.0.0")), "legacy": True}
    _validate_policy_fields(document, registry_name="model registry")
    models = document.get("models")
    if not isinstance(models, list):
        raise GovernancePolicyError("model registry models must be a list")
    for entry in models:
        if not isinstance(entry, Mapping):
            raise GovernancePolicyError("model registry entries must be mappings")
        if _contains_hard_excluded_token(entry):
            raise GovernancePolicyError(
                f"hard-excluded Sapiens2 model is registered: {entry.get('key', '(unknown)')}"
            )
        lifecycle_state = entry.get("lifecycle_state")
        if lifecycle_state not in ACTIVATABLE_PROVIDER_STATES | {"retired"}:
            raise GovernancePolicyError(
                f"model {entry.get('key', '(unknown)')} lifecycle_state must be one of "
                f"{sorted(ACTIVATABLE_PROVIDER_STATES | {'retired'})}"
            )
        license_review = entry.get("license_review")
        if not isinstance(license_review, Mapping):
            raise GovernancePolicyError(
                f"model {entry.get('key', '(unknown)')} license_review must be a mapping"
            )
        layer_issues = _license_layer_issues(entry)
        if lifecycle_state in ACTIVATABLE_PROVIDER_STATES and layer_issues:
            raise GovernancePolicyError(
                f"model {entry.get('key', '(unknown)')} checkpoint license blocks activation: "
                + "; ".join(layer_issues)
            )
        if lifecycle_state == "promoted":
            license_is_resolved = license_review.get("status") == "verified" or (
                license_review.get("status") == "not_required"
                and entry.get("license") == "MaskFactory-internal"
            )
            if not license_is_resolved:
                raise GovernancePolicyError(
                    f"promoted model {entry.get('key', '(unknown)')} lacks verified license evidence"
                )
    return {"schema_version": str(document["schema_version"]), "legacy": False}
