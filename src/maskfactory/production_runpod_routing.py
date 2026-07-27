"""Fail-closed production routing for RunPod masking workloads.

Historical/local SAM2 integrations remain readable for comparison, rollback,
and optional CVAT assistance.  This policy is the active execution authority
for new production masking work and deliberately does not promote any model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

DEFAULT_POLICY_PATH = Path("configs/production_runpod_routing.yaml")
PRODUCTION_WORKLOADS = (
    "provider_inference",
    "strict_visual_review",
    "repair",
    "training",
    "benchmarking",
    "qualification",
    "corpus_processing",
)
SAM2_KEYS = frozenset({"sam2", "sam2_1", "sam2_1_large", "sam2_1_base_plus", "pth-sam2"})


class ProductionRoutingError(ValueError):
    """The active production route is missing or silently falls back locally."""


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionRoutingError(f"{name}_must_be_mapping")
    return value


def _strings(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ProductionRoutingError(f"{name}_must_be_string_array")
    result = tuple(value)
    if not result or any(not isinstance(item, str) or not item for item in result):
        raise ProductionRoutingError(f"{name}_must_be_nonempty_string_array")
    return result


def load_production_routing(path: Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ProductionRoutingError("production_routing_root_invalid")
    validate_production_routing(document)
    return document


def validate_production_routing(document: Mapping[str, Any]) -> None:
    if document.get("schema_version") != "1.0.0":
        raise ProductionRoutingError("production_routing_schema_invalid")
    platform = _mapping(document.get("production_platform"), "production_platform")
    for workload in PRODUCTION_WORKLOADS:
        if platform.get(workload) != "runpod":
            raise ProductionRoutingError(f"production_workload_not_runpod:{workload}")
    if platform.get("persistent_root") != "/workspace":
        raise ProductionRoutingError("persistent_runpod_root_invalid")
    if platform.get("gpu_resource_governance") != "disabled":
        raise ProductionRoutingError("gpu_resource_governance_must_be_disabled")

    local = _mapping(document.get("local_scope"), "local_scope")
    forbidden = set(_strings(local.get("forbidden_as_production_progress"), "local_forbidden"))
    if not set(PRODUCTION_WORKLOADS).issubset(forbidden):
        raise ProductionRoutingError("local_production_workload_not_forbidden")
    if not {
        "local_doctor",
        "local_cvat",
        "local_nuclio",
        "local_ollama",
        "local_sam2_smoke",
    }.issubset(forbidden):
        raise ProductionRoutingError("local_health_progress_firewall_incomplete")
    artifact_boundary = _mapping(local.get("artifact_boundary"), "local_artifact_boundary")
    if (
        artifact_boundary.get("compact_evidence_only") is not True
        or artifact_boundary.get("runtime_artifact_budget_bytes") != 67_108_864
        or artifact_boundary.get("large_artifact_threshold_bytes") != 16_777_216
        or artifact_boundary.get("large_artifact_destination") != "/workspace"
        or artifact_boundary.get("transfer_staging_root") != "system_temp"
        or artifact_boundary.get("delete_transfer_staging_after_remote_hash_verification")
        is not True
    ):
        raise ProductionRoutingError("local_artifact_boundary_invalid")
    forbidden_artifacts = set(
        _strings(
            artifact_boundary.get("forbidden_local_artifact_kinds"),
            "forbidden_local_artifact_kinds",
        )
    )
    if forbidden_artifacts != {
        "model_weights",
        "dataset_copies",
        "generated_mask_batches",
        "visual_panel_batches",
        "training_checkpoints",
        "container_images",
    }:
        raise ProductionRoutingError("forbidden_local_artifact_kinds_invalid")
    docker = _mapping(local.get("docker_mutation"), "local_docker_mutation")
    if (
        docker.get("default") != "forbidden"
        or docker.get("requires_explicit_user_authorization") is not True
        or docker.get("requires_selected_local_integration_item") is not True
        or set(
            _strings(
                docker.get("forbidden_without_both_requirements"),
                "local_docker_forbidden_actions",
            )
        )
        != {"pull", "build", "update", "volume_creation", "cache_growth"}
    ):
        raise ProductionRoutingError("local_docker_mutation_boundary_invalid")

    priorities = _mapping(document.get("provider_priorities"), "provider_priorities")
    interactive = _strings(
        priorities.get("concept_and_interactive_segmentation"), "interactive_priorities"
    )
    if interactive[0] != "sam3_1" or set(interactive).intersection(SAM2_KEYS):
        raise ProductionRoutingError("sam31_must_lead_without_sam2_primary")
    geometry = _strings(priorities.get("geometry"), "geometry_priorities")
    if geometry[0] != "sam3d_body":
        raise ProductionRoutingError("sam3d_body_must_lead_geometry_canaries")
    critics = _strings(priorities.get("strict_visual_review"), "critic_priorities")
    if critics != ("qualified_primary_visual_critic", "qualified_independent_family_juror"):
        raise ProductionRoutingError("qualified_independent_critic_quorum_required")

    legacy = _mapping(document.get("legacy_classification"), "legacy_classification")
    pth = _mapping(legacy.get("pth-sam2"), "pth_sam2")
    if (
        set(_strings(pth.get("allowed_roles"), "pth_sam2_roles"))
        != {"optional_cvat_assistance", "legacy_compatibility"}
        or pth.get("production_authority") is not False
        or pth.get("production_progress_credit") is not False
    ):
        raise ProductionRoutingError("pth_sam2_classification_invalid")
    sam21 = _mapping(legacy.get("sam2_1"), "sam2_1")
    if (
        set(_strings(sam21.get("allowed_roles"), "sam2_1_roles"))
        != {
            "benchmark_baseline",
            "bounded_fallback",
            "rollback_comparison",
            "optional_interactive_editor",
        }
        or sam21.get("production_authority") is not False
        or sam21.get("primary_selection_forbidden") is not True
        or sam21.get("fallback_requires_typed_primary_failure") is not True
    ):
        raise ProductionRoutingError("sam2_1_classification_invalid")

    canary = _mapping(document.get("canary_requirements"), "canary_requirements")
    required = {
        "required_platform": "runpod",
        "required_first_interactive_provider": "sam3_1",
        "require_distinct_provider_families": True,
        "require_persistent_outputs": True,
        "require_hard_qc": True,
        "require_qualified_independent_visual_quorum": True,
        "require_bounded_repair": True,
        "require_terminal_checkpoint": True,
    }
    for key, expected in required.items():
        if canary.get(key) != expected:
            raise ProductionRoutingError(f"canary_requirement_invalid:{key}")


def validate_canary_provider_route(providers: Sequence[str]) -> tuple[str, ...]:
    """Require a modern RunPod route; SAM2.1 is never a primary candidate."""
    route = _strings(providers, "canary_provider_route")
    if route[0] != "sam3_1":
        raise ProductionRoutingError("canary_primary_provider_must_be_sam3_1")
    if route[0] in SAM2_KEYS:
        raise ProductionRoutingError("sam2_primary_forbidden")
    return route


def require_bounded_sam21_fallback(*, enabled: bool, reason: str | None) -> None:
    """Permit SAM2.1 only after a typed modern-primary failure."""
    if not enabled:
        raise ProductionRoutingError("sam2_1_requires_explicit_bounded_fallback")
    if not isinstance(reason, str) or not reason.strip() or ":" not in reason:
        raise ProductionRoutingError("sam2_1_fallback_requires_typed_failure_reason")


__all__ = [
    "DEFAULT_POLICY_PATH",
    "PRODUCTION_WORKLOADS",
    "ProductionRoutingError",
    "load_production_routing",
    "require_bounded_sam21_fallback",
    "validate_canary_provider_route",
    "validate_production_routing",
]
