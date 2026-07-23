from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from maskfactory.nude_provider_canary import PROVIDER_ROUTES
from maskfactory.production_runpod_routing import (
    ProductionRoutingError,
    load_production_routing,
    require_bounded_sam21_fallback,
    validate_canary_provider_route,
    validate_production_routing,
)


def test_active_policy_is_runpod_first_and_sam31_first() -> None:
    policy = load_production_routing()
    assert policy["production_platform"]["provider_inference"] == "runpod"
    assert policy["provider_priorities"]["concept_and_interactive_segmentation"][0] == "sam3_1"
    for route in PROVIDER_ROUTES.values():
        assert validate_canary_provider_route(route)[0] == "sam3_1"


def test_local_artifacts_are_compact_and_docker_mutation_is_deny_by_default() -> None:
    policy = load_production_routing()
    local = policy["local_scope"]
    artifacts = local["artifact_boundary"]
    assert artifacts["compact_evidence_only"] is True
    assert artifacts["runtime_artifact_budget_bytes"] == 64 * 1024 * 1024
    assert artifacts["large_artifact_threshold_bytes"] == 16 * 1024 * 1024
    assert artifacts["large_artifact_destination"] == "/workspace"
    assert artifacts["delete_transfer_staging_after_remote_hash_verification"] is True
    assert "model_weights" in artifacts["forbidden_local_artifact_kinds"]
    assert "visual_panel_batches" in artifacts["forbidden_local_artifact_kinds"]
    docker = local["docker_mutation"]
    assert docker["default"] == "forbidden"
    assert docker["requires_explicit_user_authorization"] is True
    assert docker["requires_selected_local_integration_item"] is True


def test_local_artifact_or_docker_boundary_drift_fails_closed() -> None:
    policy = load_production_routing()
    artifact_drift = deepcopy(policy)
    artifact_drift["local_scope"]["artifact_boundary"][
        "large_artifact_destination"
    ] = "C:/Comfy_UI_Main_Masking/runtime_artifacts"
    with pytest.raises(ProductionRoutingError, match="local_artifact_boundary"):
        validate_production_routing(artifact_drift)
    docker_drift = deepcopy(policy)
    docker_drift["local_scope"]["docker_mutation"]["default"] = "allowed"
    with pytest.raises(ProductionRoutingError, match="local_docker_mutation_boundary"):
        validate_production_routing(docker_drift)


def test_legacy_pipeline_sam2_route_cannot_be_mistaken_for_production() -> None:
    pipeline = yaml.safe_load(Path("configs/pipeline.yaml").read_text(encoding="utf-8"))
    assert pipeline["execution_scope"] == "legacy_local_integration_only_no_production_authority"
    assert pipeline["production_routing_config"] == "configs/production_runpod_routing.yaml"
    role = pipeline["provider_roles"]["interactive_segmenter"]
    assert role["active"] == "sam2_1_large"
    assert role["production_primary_forbidden"] is True
    assert pipeline["stages"]["S07"]["production_authority"] is False


def test_local_or_sam2_first_production_routes_fail_closed() -> None:
    policy = load_production_routing()
    drifted = deepcopy(policy)
    drifted["production_platform"]["provider_inference"] = "local"
    with pytest.raises(ProductionRoutingError, match="not_runpod"):
        validate_production_routing(drifted)
    with pytest.raises(ProductionRoutingError, match="sam3_1"):
        validate_canary_provider_route(("sam2_1", "sam3_1"))


def test_sam21_is_only_a_typed_bounded_fallback() -> None:
    with pytest.raises(ProductionRoutingError, match="explicit_bounded"):
        require_bounded_sam21_fallback(enabled=False, reason=None)
    with pytest.raises(ProductionRoutingError, match="typed_failure"):
        require_bounded_sam21_fallback(enabled=True, reason="failed")
    require_bounded_sam21_fallback(
        enabled=True,
        reason="sam3_1_runtime_failure:exact retained evidence path",
    )
