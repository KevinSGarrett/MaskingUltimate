"""Host-side shadow-tournament challenger roster and registration verification.

This module freezes the expected modernization challenger wiring for every
provider role and proves host-side shadow tournaments execute installed
challengers while recording planned challengers as skipped. It never launches
WSL GPU inference and cannot mutate active roles or mint promotions.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from .selection import PROVIDER_ROLES, ProviderSelectionError, validate_provider_selection
from .shadow import SHADOW_RUNNABLE_STATES, run_shadow_tournament, validate_shadow_manifest

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PIPELINE = ROOT / "configs" / "pipeline.yaml"
DEFAULT_EXTERNAL_REGISTRY = ROOT / "configs" / "external_sources.yaml"
DEFAULT_MODEL_REGISTRY = ROOT / "models" / "model_registry.json"

AUTHORITY = "host_side_shadow_registration_only_no_wsl_gpu_or_promotion_authority"
PROOF_TIER = "STATIC_PASS"
CURRENCY_REVIEW_PATH = ROOT / "qa" / "governance" / "currency" / "current_review.json"

# Frozen modernization roster. Order matches configs/pipeline.yaml challengers.
EXPECTED_SHADOW_CHALLENGERS: dict[str, tuple[str, ...]] = {
    "person_detector": ("rf_detr_medium", "yolo26_person"),
    "concept_detector": ("sam3_1", "sam3_litetext_s0"),
    "interactive_segmenter": ("sam3_1", "sam3_litetext_s0"),
    "geometry_provider": ("sam3d_body",),
    "pose_provider": ("rtmw_x", "rtmo_crowd"),
    "silhouette_provider": (
        "birefnet_dynamic",
        "birefnet_hr",
        "birefnet_hr_matting",
    ),
    "vlm_reviewer": ("qwen2_5_vl_7b", "qwen3_vl_4b", "qwen3_vl_8b_quantized"),
    "custom_segmenter": ("segformer_b2", "mask2former_swin_t", "eomt_dinov3"),
}

MODERNIZATION_CHALLENGERS: frozenset[str] = frozenset(
    {
        "sam3_1",
        "rf_detr_medium",
        "rtmw_x",
        "rtmo_crowd",
        "sam3d_body",
        "birefnet_dynamic",
        "birefnet_hr",
        "birefnet_hr_matting",
        "qwen3_vl_4b",
        "qwen3_vl_8b_quantized",
        "eomt_dinov3",
    }
)

SAM31_SHADOW_ROLES: frozenset[str] = frozenset({"concept_detector", "interactive_segmenter"})

DEFAULT_HOST_SAMPLE_IDS: tuple[str, ...] = (
    "host-shadow-sample-a",
    "host-shadow-sample-b",
)


class ShadowRegistrationError(ValueError):
    """Shadow tournament registration drifted or overclaims host-side proof."""


def _canonical_sha256(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def expected_shadow_challengers() -> dict[str, tuple[str, ...]]:
    """Return the frozen host-side shadow challenger roster."""
    return {role: tuple(keys) for role, keys in EXPECTED_SHADOW_CHALLENGERS.items()}


def _load_pipeline(path: Path) -> Mapping[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise ShadowRegistrationError("pipeline config must be a mapping")
    return document


def verify_shadow_challenger_roster(
    *,
    pipeline_path: Path = DEFAULT_PIPELINE,
    external_registry_path: Path = DEFAULT_EXTERNAL_REGISTRY,
    model_registry_path: Path = DEFAULT_MODEL_REGISTRY,
) -> dict[str, Any]:
    """Verify live selection matches the frozen modernization challenger roster."""
    pipeline = _load_pipeline(pipeline_path)
    selection = validate_provider_selection(
        pipeline,
        external_registry_path=Path(external_registry_path),
        model_registry_path=Path(model_registry_path),
    )
    observed = {role: tuple(selection["shadow"][role]) for role in sorted(PROVIDER_ROLES)}
    expected = expected_shadow_challengers()
    if set(observed) != set(expected) or set(observed) != PROVIDER_ROLES:
        raise ShadowRegistrationError("shadow_roster_role_coverage_invalid")
    for role in sorted(expected):
        if observed[role] != expected[role]:
            raise ShadowRegistrationError(f"shadow_roster_mismatch:{role}")

    active = selection["active"]
    for role, challengers in expected.items():
        for provider_key in challengers:
            if active.get(role) == provider_key:
                raise ShadowRegistrationError(
                    f"shadow_challenger_owns_active_role:{role}:{provider_key}"
                )

    registered_modern = {
        provider_key
        for challengers in expected.values()
        for provider_key in challengers
        if provider_key in MODERNIZATION_CHALLENGERS
    }
    if registered_modern != MODERNIZATION_CHALLENGERS:
        missing = sorted(MODERNIZATION_CHALLENGERS - registered_modern)
        raise ShadowRegistrationError(f"modernization_challenger_missing:{','.join(missing)}")

    sam31_roles = {role for role, challengers in expected.items() if "sam3_1" in challengers}
    if sam31_roles != SAM31_SHADOW_ROLES:
        raise ShadowRegistrationError("sam31_shadow_role_wiring_invalid")

    lifecycle = {
        provider_key: selection["provider_states"][provider_key]
        for challengers in expected.values()
        for provider_key in challengers
    }
    return {
        "authority": AUTHORITY,
        "expected_challengers": {role: list(keys) for role, keys in expected.items()},
        "observed_challengers": {role: list(keys) for role, keys in observed.items()},
        "active_providers": dict(active),
        "challenger_lifecycle": lifecycle,
        "modernization_challengers": sorted(MODERNIZATION_CHALLENGERS),
        "sam31_shadow_roles": sorted(SAM31_SHADOW_ROLES),
        "result": "pass_roster_matches_pipeline",
    }


def run_host_side_shadow_tournaments(
    *,
    pipeline_path: Path = DEFAULT_PIPELINE,
    external_registry_path: Path = DEFAULT_EXTERNAL_REGISTRY,
    model_registry_path: Path = DEFAULT_MODEL_REGISTRY,
    sample_ids: Sequence[str] = DEFAULT_HOST_SAMPLE_IDS,
) -> dict[str, Any]:
    """Execute evaluation-only shadow tournaments for every role with a host stub.

    The stub executor records calls only. Planned lifecycle challengers must be
    skipped; installed/benchmarked/promoted challengers must receive every sample.
    """
    roster = verify_shadow_challenger_roster(
        pipeline_path=pipeline_path,
        external_registry_path=external_registry_path,
        model_registry_path=model_registry_path,
    )
    pipeline = _load_pipeline(pipeline_path)
    normalized_samples = tuple(str(value) for value in sample_ids)
    role_manifests: dict[str, dict[str, Any]] = {}
    executed_calls: list[tuple[str, str, str]] = []
    planned_skips: dict[str, dict[str, str]] = {}
    runnable_by_role: dict[str, list[str]] = {}

    for role in sorted(EXPECTED_SHADOW_CHALLENGERS):
        calls_for_role: list[tuple[str, str]] = []

        def execute(
            provider_key: str,
            sample_id: str,
            *,
            _role: str = role,
            _calls: list[tuple[str, str]] = calls_for_role,
        ) -> dict[str, Any]:
            _calls.append((provider_key, sample_id))
            executed_calls.append((_role, provider_key, sample_id))
            return {
                "host_side_stub": True,
                "provider_key": provider_key,
                "sample_id": sample_id,
                "output_sha256": hashlib.sha256(
                    f"{_role}:{provider_key}:{sample_id}".encode()
                ).hexdigest(),
            }

        try:
            manifest = run_shadow_tournament(
                pipeline,
                role=role,
                sample_ids=normalized_samples,
                executor=execute,
                external_registry_path=Path(external_registry_path),
                model_registry_path=Path(model_registry_path),
            )
        except ProviderSelectionError as exc:
            raise ShadowRegistrationError(str(exc)) from exc
        validate_shadow_manifest(manifest)
        if manifest["active_provider"] != roster["active_providers"].get(role):
            raise ShadowRegistrationError(f"shadow_active_provider_drift:{role}")

        expected_runnable = [
            provider_key
            for provider_key in EXPECTED_SHADOW_CHALLENGERS[role]
            if roster["challenger_lifecycle"][provider_key] in SHADOW_RUNNABLE_STATES
        ]
        expected_skipped = {
            provider_key: f"lifecycle_state={roster['challenger_lifecycle'][provider_key]}"
            for provider_key in EXPECTED_SHADOW_CHALLENGERS[role]
            if roster["challenger_lifecycle"][provider_key] not in SHADOW_RUNNABLE_STATES
        }
        expected_calls = [
            (provider_key, sample_id)
            for provider_key in expected_runnable
            for sample_id in normalized_samples
        ]
        if calls_for_role != expected_calls:
            raise ShadowRegistrationError(f"shadow_executor_call_order_invalid:{role}")
        if manifest["skipped"] != expected_skipped:
            raise ShadowRegistrationError(f"shadow_skip_set_invalid:{role}")
        if set(manifest["results"]) != set(expected_runnable):
            raise ShadowRegistrationError(f"shadow_result_set_invalid:{role}")

        role_manifests[role] = manifest
        planned_skips[role] = expected_skipped
        runnable_by_role[role] = expected_runnable

    for role in SAM31_SHADOW_ROLES:
        if "sam3_1" not in planned_skips[role]:
            raise ShadowRegistrationError(f"sam31_not_skipped_as_planned:{role}")
        if planned_skips[role]["sam3_1"] != "lifecycle_state=planned":
            raise ShadowRegistrationError(f"sam31_skip_reason_invalid:{role}")

    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "host_side_shadow_tournament_registration",
        "authority": AUTHORITY,
        "proof_tier": PROOF_TIER,
        "runtime_pass_claimed": False,
        "visual_qa_pass_claimed": False,
        "production_evidence_pass_claimed": False,
        "completion_credit": False,
        "wsl_gpu_smoke_claimed": False,
        "promotion_claimed": False,
        "roster": roster,
        "sample_ids": list(normalized_samples),
        "runnable_by_role": runnable_by_role,
        "planned_skips_by_role": planned_skips,
        "executed_call_count": len(executed_calls),
        "executed_calls": [
            {"role": role, "provider_key": provider_key, "sample_id": sample_id}
            for role, provider_key, sample_id in executed_calls
        ],
        "role_manifest_sha256": {
            role: manifest["sha256"] for role, manifest in role_manifests.items()
        },
        "sam31_shadow_wiring": {
            "roles": sorted(SAM31_SHADOW_ROLES),
            "lifecycle_state": roster["challenger_lifecycle"]["sam3_1"],
            "host_side_skip_recorded": True,
            "live_wsl_gpu_smoke": "needs_kevin_ubuntu_ext4_repair",
        },
        "challenger_audit": {
            provider_key: {
                "roles": sorted(
                    role
                    for role, challengers in EXPECTED_SHADOW_CHALLENGERS.items()
                    if provider_key in challengers
                ),
                "lifecycle_state": roster["challenger_lifecycle"][provider_key],
                "shadow_runnable": (
                    roster["challenger_lifecycle"][provider_key] in SHADOW_RUNNABLE_STATES
                ),
            }
            for provider_key in sorted(MODERNIZATION_CHALLENGERS)
        },
        "result": "pass_host_side_shadow_tournaments_no_live_gpu",
    }
    document["sha256"] = _canonical_sha256(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    return document


def validate_host_side_shadow_evidence(document: Mapping[str, Any]) -> None:
    """Verify hash binding and permanent host-side authority boundary."""
    claimed = document.get("sha256")
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if claimed != _canonical_sha256(payload):
        raise ShadowRegistrationError("host_side_shadow_evidence_hash_mismatch")
    if document.get("authority") != AUTHORITY:
        raise ShadowRegistrationError("host_side_shadow_authority_invalid")
    if document.get("proof_tier") != PROOF_TIER:
        raise ShadowRegistrationError("host_side_shadow_proof_tier_invalid")
    if document.get("wsl_gpu_smoke_claimed") is not False:
        raise ShadowRegistrationError("host_side_shadow_overclaims_wsl_gpu")
    if document.get("promotion_claimed") is not False:
        raise ShadowRegistrationError("host_side_shadow_overclaims_promotion")
    if document.get("completion_credit") is not False:
        raise ShadowRegistrationError("host_side_shadow_overclaims_completion")
    if document.get("runtime_pass_claimed") is not False:
        raise ShadowRegistrationError("host_side_shadow_overclaims_runtime_pass")
    if document.get("visual_qa_pass_claimed") is not False:
        raise ShadowRegistrationError("host_side_shadow_overclaims_visual_qa")
    if document.get("production_evidence_pass_claimed") is not False:
        raise ShadowRegistrationError("host_side_shadow_overclaims_production")


def verify_shadow_currency_registry_static(
    *,
    pipeline_path: Path = DEFAULT_PIPELINE,
    external_registry_path: Path = DEFAULT_EXTERNAL_REGISTRY,
    model_registry_path: Path = DEFAULT_MODEL_REGISTRY,
    currency_review_path: Path = CURRENCY_REVIEW_PATH,
) -> dict[str, Any]:
    """STATIC consistency: shadow roster, registry lifecycles, and currency binding.

    Does not verify cryptographic currency pass/fail policy closure and never
    claims RUNTIME_PASS / PRODUCTION_EVIDENCE_PASS.
    """
    roster = verify_shadow_challenger_roster(
        pipeline_path=pipeline_path,
        external_registry_path=external_registry_path,
        model_registry_path=model_registry_path,
    )
    registry = json.loads(Path(model_registry_path).read_text(encoding="utf-8"))
    models_raw = registry.get("models")
    models_by_key: dict[str, Mapping[str, Any]] = {}
    if isinstance(models_raw, Mapping):
        models_by_key = {
            str(key): value for key, value in models_raw.items() if isinstance(value, Mapping)
        }
    elif isinstance(models_raw, list):
        for entry in models_raw:
            if isinstance(entry, Mapping) and isinstance(entry.get("key"), str):
                models_by_key[entry["key"]] = entry
    else:
        raise ShadowRegistrationError("model_registry_models_invalid")

    currency_path = Path(currency_review_path)
    if not currency_path.is_file():
        raise ShadowRegistrationError("currency_review_missing")
    currency = json.loads(currency_path.read_text(encoding="utf-8"))
    if not isinstance(currency, Mapping):
        raise ShadowRegistrationError("currency_review_invalid")
    currency_bytes = currency_path.read_bytes()
    currency_file_sha256 = hashlib.sha256(currency_bytes).hexdigest()

    pipeline = _load_pipeline(pipeline_path)
    catalog = pipeline.get("provider_catalog")
    if not isinstance(catalog, Mapping):
        raise ShadowRegistrationError("provider_catalog_invalid")

    planned_active: list[str] = []
    lifecycle_drift: list[str] = []
    missing_registry: list[str] = []
    for role, challengers in EXPECTED_SHADOW_CHALLENGERS.items():
        active = roster["active_providers"].get(role)
        for provider_key in challengers:
            lifecycle = roster["challenger_lifecycle"][provider_key]
            catalog_entry = catalog.get(provider_key)
            if not isinstance(catalog_entry, Mapping):
                missing_registry.append(provider_key)
                continue
            registry_key = catalog_entry.get("key")
            if catalog_entry.get("registry") == "external_sources":
                # External-source lifecycle is already validated by selection.
                if active == provider_key and lifecycle == "planned":
                    planned_active.append(f"{role}:{provider_key}")
                continue
            if not isinstance(registry_key, str):
                missing_registry.append(provider_key)
                continue
            model_entry = models_by_key.get(registry_key)
            if model_entry is None:
                missing_registry.append(provider_key)
                continue
            registered_lifecycle = model_entry.get("lifecycle_state")
            if registered_lifecycle != lifecycle:
                lifecycle_drift.append(f"{provider_key}:{lifecycle}!={registered_lifecycle}")
            if active == provider_key and lifecycle == "planned":
                planned_active.append(f"{role}:{provider_key}")
    if missing_registry:
        raise ShadowRegistrationError(
            "shadow_challenger_registry_missing:" + ",".join(sorted(set(missing_registry)))
        )

    if planned_active:
        raise ShadowRegistrationError(
            "planned_challenger_owns_active_role:" + ",".join(planned_active)
        )
    if lifecycle_drift:
        raise ShadowRegistrationError(
            "shadow_registry_lifecycle_drift:" + ",".join(sorted(lifecycle_drift))
        )

    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "host_side_shadow_currency_registry_static",
        "authority": AUTHORITY,
        "proof_tier": PROOF_TIER,
        "runtime_pass_claimed": False,
        "production_evidence_pass_claimed": False,
        "promotion_claimed": False,
        "completion_credit": False,
        "roster_result": roster["result"],
        "currency_review_path": (
            currency_path.relative_to(ROOT).as_posix()
            if currency_path.is_relative_to(ROOT)
            else str(currency_path)
        ),
        "currency_review_file_sha256": currency_file_sha256,
        "currency_review_id": currency.get("review_id"),
        "currency_policy_result": currency.get("policy_result")
        or currency.get("result")
        or currency.get("status"),
        "active_providers": dict(roster["active_providers"]),
        "challenger_lifecycle": dict(roster["challenger_lifecycle"]),
        "result": "pass_shadow_currency_registry_static_only",
    }
    document["sha256"] = _canonical_sha256(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    return document


__all__ = [
    "AUTHORITY",
    "CURRENCY_REVIEW_PATH",
    "DEFAULT_HOST_SAMPLE_IDS",
    "EXPECTED_SHADOW_CHALLENGERS",
    "MODERNIZATION_CHALLENGERS",
    "PROOF_TIER",
    "SAM31_SHADOW_ROLES",
    "ShadowRegistrationError",
    "expected_shadow_challengers",
    "run_host_side_shadow_tournaments",
    "validate_host_side_shadow_evidence",
    "verify_shadow_challenger_roster",
    "verify_shadow_currency_registry_static",
]
