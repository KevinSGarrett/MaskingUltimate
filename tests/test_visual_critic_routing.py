from __future__ import annotations

from copy import deepcopy

import pytest

from maskfactory.vlm.critic_catalog import CriticCatalogError, canonical_sha256, load_catalog
from maskfactory.vlm.critic_routing import resolve_role_route


def _reseal(catalog: dict) -> None:
    catalog["sha256"] = canonical_sha256(
        {key: value for key, value in catalog.items() if key != "sha256"}
    )


def test_current_multi_gpu_arbiter_route_abstains() -> None:
    result = resolve_role_route(load_catalog(), "senior_arbiter")
    assert result["status"] == "abstain"
    assert result["reason"] == "no_unique_promoted_model"


@pytest.mark.parametrize("lifecycle", ["downloaded", "smoked"])
def test_catalog_or_single_gpu_smoke_never_activates_multi_gpu_arbiter(lifecycle: str) -> None:
    catalog = deepcopy(load_catalog())
    model = catalog["models"][1]
    model["lifecycle"] = lifecycle
    model["artifact_sha256"] = "a" * 64
    _reseal(catalog)

    result = resolve_role_route(catalog, "senior_arbiter")
    assert result["status"] == "abstain"


def test_hardware_telemetry_cannot_block_promoted_model() -> None:
    catalog = deepcopy(load_catalog())
    model = catalog["models"][1]
    model["lifecycle"] = "promoted"
    model["artifact_sha256"] = "a" * 64
    model["calibration"] = {"status": "pass", "report_sha256": "b" * 64}
    model["assigned_roles"] = ["senior_arbiter"]
    model["private_endpoint"] = "http://127.0.0.1:8123"
    _reseal(catalog)

    result = resolve_role_route(
        catalog,
        "senior_arbiter",
        available_hardware_tier="uncataloged_observation",
    )
    assert result["status"] == "selected"
    assert result["model_id"] == model["model_id"]


def test_exact_promoted_calibrated_single_gpu_model_is_hash_bound() -> None:
    catalog = deepcopy(load_catalog())
    model = catalog["models"][5]
    model["lifecycle"] = "promoted"
    model["artifact_sha256"] = "a" * 64
    model["calibration"] = {"status": "pass", "report_sha256": "b" * 64}
    model["assigned_roles"] = ["primary_visual_critic"]
    model["private_endpoint"] = "http://127.0.0.1:8123"
    _reseal(catalog)

    result = resolve_role_route(catalog, "primary_visual_critic")
    assert result["status"] == "selected"
    assert result["model_id"] == "qwen3_6_27b_fp8"
    assert len(result["selection_sha256"]) == 64


def test_unknown_role_fails_instead_of_silently_abstaining() -> None:
    with pytest.raises(CriticCatalogError, match="unknown or non-model"):
        resolve_role_route(load_catalog(), "unknown")
