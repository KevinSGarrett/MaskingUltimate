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
        "pixtral_12b_2409",
        "qwen3_vl_30b_a3b_instruct_fp8",
        "minicpm_v_4_5_bf16",
        "glm_4_1v_9b_thinking",
    }
    assert {model_id: model["lifecycle"] for model_id, model in models.items()} == {
        "qwen3_6_35b_a3b_fp8": "downloaded",
        "qwen3_5_122b_a10b_fp8": "planned",
        "qwen3_5_397b_a17b_fp8": "planned",
        "internvl3_5_8b_bf16": "smoked",
        "internvl3_5_241b_a28b_bf16": "planned",
        "qwen3_6_27b_fp8": "smoked",
        "pixtral_12b_2409": "smoked",
        "qwen3_vl_30b_a3b_instruct_fp8": "downloaded",
        "minicpm_v_4_5_bf16": "smoked",
        "glm_4_1v_9b_thinking": "smoked",
    }
    assert all(model["assigned_roles"] == [] for model in models.values())
    assert models["qwen3_6_27b_fp8"]["calibration"]["status"] == "fail"
    assert models["internvl3_5_8b_bf16"]["calibration"]["status"] == "fail"
    assert not models["qwen3_6_35b_a3b_fp8"]["hardware"]["single_gpu_48gb_feasible"]
    assert (
        models["qwen3_6_35b_a3b_fp8"]["artifact_sha256"]
        == "240ee7cfda41472056d80e24fe717035577263e0249f0408fec9762459718aa4"
    )
    assert (
        models["qwen3_6_35b_a3b_fp8"]["infeasibility_evidence_sha256"]
        == "4d487925cc1ae274db864e9764c8ebd1f8706b79f846bfa9325ab38cf3057c8b"
    )
    assert models["qwen3_6_27b_fp8"]["hardware"]["single_gpu_48gb_feasible"]
    assert models["internvl3_5_8b_bf16"]["hardware"]["single_gpu_48gb_feasible"]
    assert models["pixtral_12b_2409"]["hardware"]["single_gpu_48gb_feasible"]
    assert models["pixtral_12b_2409"]["assigned_roles"] == []
    assert models["pixtral_12b_2409"]["calibration"]["status"] == "fail"
    assert (
        models["pixtral_12b_2409"]["artifact_sha256"]
        == "0070c50d26443b0e3204a96220b483480bf95eee34d7e81c9a5c46efa07aea0a"
    )
    assert models["qwen3_vl_30b_a3b_instruct_fp8"]["assigned_roles"] == []
    assert models["qwen3_vl_30b_a3b_instruct_fp8"]["calibration"] is None
    assert (
        models["qwen3_vl_30b_a3b_instruct_fp8"]["artifact_sha256"]
        == "dbb7d33b3ab68a356069bc577692fd347c4103c2c59ead3a65943d664a8c8d4a"
    )
    assert models["minicpm_v_4_5_bf16"]["assigned_roles"] == []
    assert models["minicpm_v_4_5_bf16"]["calibration"]["status"] == "fail"
    assert (
        models["minicpm_v_4_5_bf16"]["artifact_sha256"]
        == "6fca3294df97b0e9fa4bc70bea9907cbb01a27816ee59880bb2aea29bda138a0"
    )
    assert models["glm_4_1v_9b_thinking"]["family_id"] == "glm"
    assert models["glm_4_1v_9b_thinking"]["license"] == "mit"
    assert models["glm_4_1v_9b_thinking"]["assigned_roles"] == []
    assert models["glm_4_1v_9b_thinking"]["calibration"]["status"] == "fail"
    assert (
        models["glm_4_1v_9b_thinking"]["artifact_sha256"]
        == "e62628b04ac0286c137226dc3ff14f3d2d468e488d9e7b752be51f701d2efc32"
    )
    assert (
        models["qwen3_6_27b_fp8"]["artifact_sha256"]
        == "8349ee8e70b8a08bdf1b94c6165dffd6ee57117cfc6b7a9211a45c1abb91ee48"
    )
    assert (
        models["internvl3_5_8b_bf16"]["artifact_sha256"]
        == "e1a117fa9589a7f7bf67ff0eaf1b0c75dfd6ff24bf99142e48aa5d79897eed65"
    )
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
    model["artifact_sha256"] = None
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
    by_id = {model["model_id"]: model for model in models}
    assert independent_families(models[:3]) == frozenset({"qwen"})
    assert independent_families((models[0], models[3])) == frozenset({"qwen", "internvl"})
    assert independent_families(
        (by_id["pixtral_12b_2409"], by_id["qwen3_vl_30b_a3b_instruct_fp8"])
    ) == frozenset({"mistral_pixtral", "qwen"})
    assert independent_families(
        (by_id["qwen3_vl_30b_a3b_instruct_fp8"], by_id["minicpm_v_4_5_bf16"])
    ) == frozenset({"qwen"})
    assert independent_families(
        (by_id["qwen3_vl_30b_a3b_instruct_fp8"], by_id["glm_4_1v_9b_thinking"])
    ) == frozenset({"qwen", "glm"})


def test_schema_rejects_unknown_role_even_if_catalog_is_resealed() -> None:
    catalog = deepcopy(load_catalog())
    catalog["roles"][0]["role_id"] = "unknown_role"
    _reseal(catalog)
    with pytest.raises(CriticCatalogError, match="role_id"):
        validate_catalog(catalog)
