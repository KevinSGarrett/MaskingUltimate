"""Provider-neutral, evaluation-only shadow tournament execution."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .selection import PROVIDER_ROLES, ProviderSelectionError, validate_provider_selection

SHADOW_RUNNABLE_STATES = {"installed", "benchmarked", "promoted"}


def _canonical_sha256(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def run_shadow_tournament(
    pipeline: Mapping[str, Any],
    *,
    role: str,
    sample_ids: Sequence[str],
    executor: Callable[[str, str], Mapping[str, Any]],
    external_registry_path: Path,
    model_registry_path: Path,
) -> dict[str, Any]:
    """Run installed challengers without granting output or promotion authority.

    The executor is a provider-dispatch boundary. Every runnable challenger gets
    the identical ordered sample list. Planned challengers remain explicitly in
    the immutable manifest as skipped rather than being mistaken for installed.
    This function cannot select a winner or edit any active role.
    """
    if role not in PROVIDER_ROLES:
        raise ProviderSelectionError(f"unknown provider role for shadow tournament: {role!r}")
    normalized_samples = tuple(str(value) for value in sample_ids)
    if (
        not normalized_samples
        or any(not value for value in normalized_samples)
        or len(normalized_samples) != len(set(normalized_samples))
    ):
        raise ProviderSelectionError("shadow tournament sample_ids must be non-empty and unique")
    selection = validate_provider_selection(
        pipeline,
        external_registry_path=external_registry_path,
        model_registry_path=model_registry_path,
    )
    challengers = selection["shadow"][role]
    provider_states = selection["provider_states"]
    results: dict[str, dict[str, Any]] = {}
    skipped: dict[str, str] = {}
    for provider_key in challengers:
        lifecycle = provider_states[provider_key]
        if lifecycle not in SHADOW_RUNNABLE_STATES:
            skipped[provider_key] = f"lifecycle_state={lifecycle}"
            continue
        provider_results: dict[str, Any] = {}
        for sample_id in normalized_samples:
            result = executor(provider_key, sample_id)
            if not isinstance(result, Mapping):
                raise ProviderSelectionError(
                    f"shadow executor for {provider_key!r} returned a non-mapping result"
                )
            provider_results[sample_id] = dict(result)
        results[provider_key] = provider_results

    manifest: dict[str, Any] = {
        "schema_version": "1.0.0",
        "role": role,
        "authority": "evaluation_only_no_runtime_or_promotion_authority",
        "active_provider": selection["active"].get(role),
        "sample_ids": list(normalized_samples),
        "challenger_lifecycle": {
            provider_key: provider_states[provider_key] for provider_key in challengers
        },
        "results": results,
        "skipped": skipped,
    }
    manifest["sha256"] = _canonical_sha256(manifest)
    return manifest


def validate_shadow_manifest(document: Mapping[str, Any]) -> None:
    """Verify hash binding and the permanent evaluation-only authority boundary."""
    claimed = document.get("sha256")
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if claimed != _canonical_sha256(payload):
        raise ProviderSelectionError("shadow tournament manifest hash mismatch")
    if document.get("authority") != "evaluation_only_no_runtime_or_promotion_authority":
        raise ProviderSelectionError("shadow tournament authority boundary is invalid")


__all__ = [
    "SHADOW_RUNNABLE_STATES",
    "run_shadow_tournament",
    "validate_shadow_manifest",
]
