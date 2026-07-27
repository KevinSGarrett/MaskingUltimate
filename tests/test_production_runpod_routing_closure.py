from __future__ import annotations

from copy import deepcopy

import pytest

from maskfactory.production_runpod_routing import (
    ProductionRoutingError,
    load_production_routing,
    require_bounded_sam21_fallback,
    validate_canary_provider_route,
    validate_production_routing,
)


def test_exact_full_product_policy_is_closed_and_runpod_first() -> None:
    policy = load_production_routing()
    assert set(policy["production_platform"]).issuperset(
        {"provider_inference", "strict_visual_review", "repair", "qualification"}
    )
    assert policy["production_platform"]["provider_inference"] == "runpod"
    assert policy["provider_priorities"]["concept_and_interactive_segmentation"][0] == "sam3_1"
    assert policy["provider_priorities"]["strict_visual_review"] == [
        "qualified_primary_visual_critic",
        "qualified_independent_family_juror",
    ]
    assert policy["local_scope"]["artifact_boundary"]["large_artifact_destination"] == "/workspace"


def test_local_progress_and_legacy_primary_drift_fail_closed() -> None:
    policy = load_production_routing()
    local = deepcopy(policy)
    local["production_platform"]["provider_inference"] = "local"
    with pytest.raises(ProductionRoutingError, match="production_workload_not_runpod"):
        validate_production_routing(local)

    legacy = deepcopy(policy)
    legacy["provider_priorities"]["concept_and_interactive_segmentation"] = ["sam2_1"]
    with pytest.raises(ProductionRoutingError, match="sam31_must_lead"):
        validate_production_routing(legacy)


def test_sam21_needs_a_typed_modern_primary_failure() -> None:
    with pytest.raises(ProductionRoutingError, match="explicit_bounded"):
        require_bounded_sam21_fallback(enabled=False, reason=None)
    with pytest.raises(ProductionRoutingError, match="typed_failure"):
        require_bounded_sam21_fallback(enabled=True, reason="failed")
    require_bounded_sam21_fallback(
        enabled=True,
        reason="sam3_1_runtime_failure:exact retained evidence path",
    )
    assert validate_canary_provider_route(("sam3_1", "maskfactory_core"))[0] == "sam3_1"
