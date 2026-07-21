from __future__ import annotations

from copy import deepcopy

import pytest

from maskfactory.vlm.critic_catalog import (
    CriticCatalogError,
    canonical_sha256,
    independent_families,
    load_catalog,
    select_promoted_model,
    validate_catalog,
)


def _reseal(document: dict) -> dict:
    document["sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    return document


def test_catalog_binds_exact_models_lifecycle_and_hardware_without_authority() -> None:
    catalog = load_catalog()
    models = {model["model_id"]: model for model in catalog["models"]}

    assert set(models) == {
        "qwen3_6_35b_a3b_fp8",
        "qwen3_5_122b_a10b_fp8",
        "qwen3_5_397b_a17b_fp8",
        "internvl3_5_8b_bf16",
        "internvl3_5_241b_a28b_bf16",
        "qwen3_6_27b_fp8",
    }
    assert all(model["lifecycle"] == "planned" for model in models.values())
    assert all(model["assigned_roles"] == [] for model in models.values())
    assert not models["qwen3_6_35b_a3b_fp8"]["hardware"]["single_gpu_48gb_feasible"]
    assert (
        models["qwen3_6_35b_a3b_fp8"]["infeasibility_evidence_sha256"]
        == "4d487925cc1ae274db864e9764c8ebd1f8706b79f846bfa9325ab38cf3057c8b"
    )
    assert models["qwen3_6_27b_fp8"]["hardware"]["single_gpu_48gb_feasible"]
    assert models["internvl3_5_8b_bf16"]["hardware"]["single_gpu_48gb_feasible"]
    assert not models["qwen3_5_122b_a10b_fp8"]["hardware"]["single_gpu_48gb_feasible"]
    assert models["qwen3_5_397b_a17b_fp8"]["hardware"]["minimum_gpu_count_by_weight_bytes"] == 8
    assert (
        models["internvl3_5_241b_a28b_bf16"]["hardware"]["minimum_gpu_count_by_weight_bytes"] == 10
    )


def test_catalog_rejects_unknown_roles_and_name_only_selection() -> None:
    catalog = load_catalog()
    with pytest.raises(CriticCatalogError, match="unknown or non-model"):
        select_promoted_model(catalog, "famous_model_name")
    with pytest.raises(CriticCatalogError, match="0 promoted feasible models"):
        select_promoted_model(catalog, "primary_visual_critic")


def test_catalog_rejects_role_assignment_before_promotion() -> None:
    catalog = deepcopy(load_catalog())
    catalog["models"][0]["assigned_roles"] = ["primary_visual_critic"]
    _reseal(catalog)
    with pytest.raises(CriticCatalogError, match="assigned authority before promotion"):
        validate_catalog(catalog)


def test_catalog_rejects_promotion_without_calibration_artifact_or_private_endpoint() -> None:
    catalog = deepcopy(load_catalog())
    model = catalog["models"][0]
    model["lifecycle"] = "promoted"
    model["assigned_roles"] = ["primary_visual_critic"]
    _reseal(catalog)
    with pytest.raises(CriticCatalogError, match="requires an artifact hash"):
        validate_catalog(catalog)


def test_catalog_rejects_single_gpu_claim_for_multi_gpu_weights() -> None:
    catalog = deepcopy(load_catalog())
    model = catalog["models"][1]
    model["hardware"]["single_gpu_48gb_feasible"] = True
    model["hardware"]["tier"] = "single_gpu_candidate"
    _reseal(catalog)
    with pytest.raises(CriticCatalogError, match="hardware tier contradicts"):
        validate_catalog(catalog)


def test_family_identity_does_not_count_variants_as_independent() -> None:
    catalog = load_catalog()
    models = catalog["models"]
    assert independent_families(models[:3]) == frozenset({"qwen"})
    assert independent_families((models[0], models[3])) == frozenset({"qwen", "internvl"})


def test_schema_rejects_unknown_role_even_if_catalog_is_resealed() -> None:
    catalog = deepcopy(load_catalog())
    catalog["roles"][0]["role_id"] = "unknown_role"
    _reseal(catalog)
    with pytest.raises(CriticCatalogError, match="role_id"):
        validate_catalog(catalog)
