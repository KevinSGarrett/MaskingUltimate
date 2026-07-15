"""Fail-closed provider-role selection against authoritative registries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from ..governance import validate_external_source_registry, validate_model_registry
from .adapters import LEGACY_PROVIDER_ALIASES

PROVIDER_ROLES = {
    "person_detector",
    "concept_detector",
    "interactive_segmenter",
    "geometry_provider",
    "pose_provider",
    "silhouette_provider",
    "vlm_reviewer",
    "custom_segmenter",
}


class ProviderSelectionError(ValueError):
    """A pipeline role attempts to bypass lifecycle or offline guarantees."""


def _load_registry(path: Path) -> Mapping[str, Any]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        document = json.loads(path.read_text(encoding="utf-8"))
    else:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise ProviderSelectionError(f"provider registry must be a mapping: {path}")
    return document


def _catalog_entry(
    catalog: Mapping[str, Any], provider_key: str, *, usage: str
) -> tuple[str, Mapping[str, Any]]:
    normalized = provider_key.lower().replace("-", "_")
    canonical_key = LEGACY_PROVIDER_ALIASES.get(normalized, provider_key)
    entry = catalog.get(canonical_key)
    if not isinstance(entry, Mapping):
        raise ProviderSelectionError(
            f"{usage} provider {provider_key!r} has no provider_catalog binding"
        )
    if set(entry) != {"registry", "key", "execution", "billing"}:
        raise ProviderSelectionError(
            f"provider_catalog.{provider_key} must declare registry/key/execution/billing"
        )
    if entry["registry"] not in {"external_sources", "model_registry"}:
        raise ProviderSelectionError(
            f"provider_catalog.{provider_key}.registry is not authoritative"
        )
    if entry["execution"] not in {"local", "hosted"}:
        raise ProviderSelectionError(
            f"provider_catalog.{provider_key}.execution must be local or hosted"
        )
    if entry["billing"] not in {"none", "paid"}:
        raise ProviderSelectionError(
            f"provider_catalog.{provider_key}.billing must be none or paid"
        )
    return canonical_key, entry


def _authority_entry(
    registries: Mapping[str, Mapping[str, Any]],
    binding: Mapping[str, Any],
    *,
    role: str,
    provider_key: str,
    usage: str,
) -> Mapping[str, Any]:
    registry = registries[str(binding["registry"])]
    authority = registry.get(str(binding["key"]))
    if not isinstance(authority, Mapping):
        raise ProviderSelectionError(
            f"{role}.{usage} provider {provider_key!r} is absent from its authoritative registry"
        )
    return authority


def _validate_shadow_only_experiment(
    authority: Mapping[str, Any],
    *,
    role: str,
    provider_key: str,
    usage: str,
    role_config: Mapping[str, Any],
    catalog: Mapping[str, Any],
) -> None:
    """Prevent optional experiments from becoming silent incumbent substitutes."""
    declared = role_config.get("shadow_only_experiments", [])
    if not isinstance(declared, list) or not all(
        isinstance(value, str) and value for value in declared
    ):
        raise ProviderSelectionError(
            f"{role}.shadow_only_experiments must be an array of provider keys"
        )
    declared_shadow_only = provider_key in declared
    authority_shadow_only = authority.get("role_eligibility") == "shadow_only_experiment"
    if declared_shadow_only != authority_shadow_only:
        raise ProviderSelectionError(
            f"{role}.{usage} provider {provider_key!r} shadow-only role declaration "
            "and distinct registry identity must agree"
        )
    if not authority_shadow_only:
        return
    forbidden = authority.get("substitution_forbidden_for")
    if not isinstance(forbidden, str) or not forbidden:
        raise ProviderSelectionError(
            f"{role}.{usage} provider {provider_key!r} is a shadow-only experiment "
            "without substitution_forbidden_for"
        )
    if usage != "challengers":
        raise ProviderSelectionError(
            f"{role}.{usage} provider {provider_key!r} is shadow-only and cannot be "
            "active, fallback, or rollback"
        )
    challengers = role_config.get("challengers", ())
    official_is_active = role_config.get("active") == forbidden
    if forbidden not in challengers and not official_is_active:
        raise ProviderSelectionError(
            f"{role} must retain {forbidden!r} as active or as a challenger when screening "
            f"shadow-only experiment {provider_key!r}"
        )
    if forbidden in challengers and challengers.index(forbidden) > challengers.index(provider_key):
        raise ProviderSelectionError(
            f"{role}.challengers must list official provider {forbidden!r} before "
            f"shadow-only experiment {provider_key!r}"
        )
    _, experiment_binding = _catalog_entry(catalog, provider_key, usage=f"{role}.challengers")
    _, official_binding = _catalog_entry(catalog, forbidden, usage=f"{role}.challengers")
    if (
        experiment_binding["registry"] == official_binding["registry"]
        and experiment_binding["key"] == official_binding["key"]
    ):
        raise ProviderSelectionError(
            f"shadow-only experiment {provider_key!r} must have a distinct registry "
            f"identity from {forbidden!r}"
        )


def validate_provider_selection(
    pipeline: Mapping[str, Any],
    *,
    external_registry_path: Path,
    model_registry_path: Path,
) -> dict[str, Any]:
    """Validate active providers and the mandatory local concept fallback.

    Only a provider whose authoritative lifecycle state is ``promoted`` may
    own an active role. Installed and planned providers remain eligible for
    shadow evaluation, but they cannot become active through config editing.
    """
    external = _load_registry(external_registry_path)
    models = _load_registry(model_registry_path)
    validate_external_source_registry(external)
    validate_model_registry(models)
    external_entries = external.get("providers", {})
    model_entries = {
        str(entry.get("key")): entry
        for entry in models.get("models", ())
        if isinstance(entry, Mapping)
    }
    registries = {
        "external_sources": external_entries,
        "model_registry": model_entries,
    }

    roles = pipeline.get("provider_roles")
    catalog = pipeline.get("provider_catalog")
    if not isinstance(roles, Mapping) or not isinstance(catalog, Mapping):
        raise ProviderSelectionError(
            "pipeline provider_roles and provider_catalog must both be mappings"
        )

    active: dict[str, str] = {}
    fallbacks: dict[str, dict[str, str]] = {}
    rollback: dict[str, str | None] = {}
    shadow: dict[str, tuple[str, ...]] = {}
    provider_states: dict[str, str] = {}
    for role in sorted(PROVIDER_ROLES):
        role_config = roles.get(role)
        if not isinstance(role_config, Mapping):
            raise ProviderSelectionError(f"pipeline provider role {role!r} is missing")
        active_key = role_config.get("active")
        if active_key is not None:
            if not isinstance(active_key, str) or not active_key:
                raise ProviderSelectionError(f"{role}.active must be a provider key or null")
            canonical_key, binding = _catalog_entry(catalog, active_key, usage=f"{role}.active")
            authority = _authority_entry(
                registries,
                binding,
                role=role,
                provider_key=active_key,
                usage="active",
            )
            _validate_shadow_only_experiment(
                authority,
                role=role,
                provider_key=active_key,
                usage="active",
                role_config=role_config,
                catalog=catalog,
            )
            lifecycle = authority.get("lifecycle_state")
            if lifecycle != "promoted":
                raise ProviderSelectionError(
                    f"{role}.active provider {active_key!r} lifecycle_state={lifecycle!r}; "
                    "active roles require promoted"
                )
            active[role] = canonical_key
            provider_states[canonical_key] = str(lifecycle)

        challengers = role_config.get("challengers", ())
        if not isinstance(challengers, list) or not all(
            isinstance(value, str) and value for value in challengers
        ):
            raise ProviderSelectionError(f"{role}.challengers must be an array of provider keys")
        for challenger in challengers:
            canonical_challenger, binding = _catalog_entry(
                catalog, challenger, usage=f"{role}.challengers"
            )
            authority = _authority_entry(
                registries,
                binding,
                role=role,
                provider_key=challenger,
                usage="challengers",
            )
            _validate_shadow_only_experiment(
                authority,
                role=role,
                provider_key=challenger,
                usage="challengers",
                role_config=role_config,
                catalog=catalog,
            )
            lifecycle = authority.get("lifecycle_state")
            if lifecycle not in {"planned", "installed", "benchmarked", "promoted"}:
                raise ProviderSelectionError(
                    f"{role}.challenger provider {challenger!r} "
                    f"lifecycle_state={lifecycle!r} is not shadow-eligible"
                )
            provider_states[canonical_challenger] = str(lifecycle)
            if canonical_challenger == active.get(role):
                raise ProviderSelectionError(
                    f"{role} provider {challenger!r} cannot be active and a shadow challenger"
                )
        shadow[role] = tuple(
            _catalog_entry(catalog, challenger, usage=f"{role}.challengers")[0]
            for challenger in challengers
        )

        rollback_key = role_config.get("rollback")
        if rollback_key is not None:
            if not isinstance(rollback_key, str) or not rollback_key:
                raise ProviderSelectionError(f"{role}.rollback must be a provider key or null")
            canonical_rollback, binding = _catalog_entry(
                catalog, rollback_key, usage=f"{role}.rollback"
            )
            authority = _authority_entry(
                registries,
                binding,
                role=role,
                provider_key=rollback_key,
                usage="rollback",
            )
            _validate_shadow_only_experiment(
                authority,
                role=role,
                provider_key=rollback_key,
                usage="rollback",
                role_config=role_config,
                catalog=catalog,
            )
            lifecycle = authority.get("lifecycle_state")
            if lifecycle not in {"installed", "benchmarked", "promoted"}:
                raise ProviderSelectionError(
                    f"{role}.rollback provider {rollback_key!r} lifecycle_state={lifecycle!r}; "
                    "rollback requires an installed, benchmarked, or promoted artifact"
                )
            rollback[role] = canonical_rollback
            provider_states[canonical_rollback] = str(lifecycle)
        else:
            rollback[role] = None

        fallback_keys: dict[str, str] = {}
        for fallback_name in ("oom_fallback",):
            fallback_key = role_config.get(fallback_name)
            if fallback_key is None:
                continue
            if not isinstance(fallback_key, str) or not fallback_key:
                raise ProviderSelectionError(
                    f"{role}.{fallback_name} must be a provider key or null"
                )
            canonical_fallback, binding = _catalog_entry(
                catalog, fallback_key, usage=f"{role}.{fallback_name}"
            )
            authority = _authority_entry(
                registries,
                binding,
                role=role,
                provider_key=fallback_key,
                usage=fallback_name,
            )
            _validate_shadow_only_experiment(
                authority,
                role=role,
                provider_key=fallback_key,
                usage=fallback_name,
                role_config=role_config,
                catalog=catalog,
            )
            lifecycle = authority.get("lifecycle_state")
            if lifecycle not in {"installed", "benchmarked", "promoted"}:
                raise ProviderSelectionError(
                    f"{role}.{fallback_name} provider {fallback_key!r} "
                    f"lifecycle_state={lifecycle!r}; fallback requires an installed, "
                    "benchmarked, or promoted artifact"
                )
            if binding["execution"] != "local" or binding["billing"] != "none":
                raise ProviderSelectionError(
                    f"{role}.{fallback_name} must be local and non-billable"
                )
            fallback_keys[fallback_name] = canonical_fallback
            provider_states[canonical_fallback] = str(lifecycle)
        if fallback_keys:
            fallbacks[role] = fallback_keys

    concept = roles["concept_detector"]
    fallback_key = concept.get("offline_fallback")
    if not isinstance(fallback_key, str) or not fallback_key:
        raise ProviderSelectionError(
            "concept_detector.offline_fallback must name the reproducible local fallback"
        )
    canonical_fallback, fallback = _catalog_entry(
        catalog, fallback_key, usage="concept_detector.offline_fallback"
    )
    if fallback["execution"] != "local" or fallback["billing"] != "none":
        raise ProviderSelectionError(
            "concept_detector offline fallback must be local and non-billable; hosted-only is forbidden"
        )
    if fallback["registry"] != "model_registry" or fallback["key"] != ("groundingdino_swint_ogc"):
        raise ProviderSelectionError(
            "concept_detector offline fallback must preserve pinned local GroundingDINO"
        )
    fallbacks.setdefault("concept_detector", {})["offline_fallback"] = canonical_fallback

    return {
        "active": active,
        "fallbacks": fallbacks,
        "rollback": rollback,
        "shadow": shadow,
        "provider_states": provider_states,
        "concept_offline_fallback": canonical_fallback,
    }


__all__ = [
    "PROVIDER_ROLES",
    "ProviderSelectionError",
    "validate_provider_selection",
]
