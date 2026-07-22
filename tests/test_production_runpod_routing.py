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
