from __future__ import annotations

from copy import deepcopy

import pytest

from maskfactory.vlm.critic_catalog import load_catalog
from maskfactory.vlm.runtime_qualification import (
    RuntimeQualificationError,
    validate_single_gpu_runtime_evidence,
)


def _model(model_id: str, family: str, repository: str, revision: str, quantization: str) -> dict:
    run = {
        "status": "pass",
        "pid": 101,
        "cold_latency_ms": 1000.0,
        "warm_latency_ms": 500.0,
        "peak_vram_bytes": 20_000_000_000,
        "response_sha256": "c" * 64,
    }
    return {
        "model_id": model_id,
        "family_id": family,
        "repository": repository,
        "revision": revision,
        "quantization": quantization,
        "artifact_tree_sha256": "a" * 64,
        "prompt_sha256": "b" * 64,
        "downloaded_bytes": 40_000_000_000,
        "image_budget": 3,
        "context_token_budget": 8192,
        "endpoint": "http://127.0.0.1:18001",
        "process_runs": [run, {**run, "pid": 202}],
    }


def _evidence() -> dict:
    catalog = load_catalog()
    registered = {model["model_id"]: model for model in catalog["models"]}
    evidence = {
        "schema_version": "1.0.0",
        "status": "RUNTIME_PASS_BOUNDED",
        "hardware": {
            "tier_id": "runpod_single_gpu_48gb",
            "gpu_name": "NVIDIA RTX 6000 Ada Generation",
            "gpu_count": 1,
            "vram_bytes": 51527024640,
        },
        "models": [
            _model(
                model_id,
                registered[model_id]["family_id"],
                registered[model_id]["repository"],
                registered[model_id]["revision"],
                registered[model_id]["quantization"],
            )
            for model_id in ("qwen3_6_27b_fp8", "internvl3_5_8b_bf16")
        ],
        "authority_claimed": False,
    }
    evidence["models"][1]["endpoint"] = "local-process://isolated"
    return evidence


def test_exact_two_family_restart_evidence_passes() -> None:
    validate_single_gpu_runtime_evidence(_evidence(), load_catalog())


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("models", 0, "image_budget"), 2, "image budget"),
        (("models", 0, "endpoint"), "http://0.0.0.0:18001", "not private"),
        (("models", 0, "process_runs", 1, "pid"), 101, "distinct live PIDs"),
        (("models", 0, "process_runs", 1, "response_sha256"), "d" * 64, "response changed"),
        (("models", 0, "process_runs", 1, "peak_vram_bytes"), 60_000_000_000, "exceeded"),
    ],
)
def test_runtime_evidence_rejects_resource_or_restart_drift(
    path: tuple, value: object, message: str
) -> None:
    evidence = deepcopy(_evidence())
    target = evidence
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(RuntimeQualificationError, match=message):
        validate_single_gpu_runtime_evidence(evidence, load_catalog())


def test_runtime_evidence_rejects_multi_gpu_or_missing_family_substitution() -> None:
    evidence = _evidence()
    evidence["models"][1] = deepcopy(evidence["models"][0])
    with pytest.raises(RuntimeQualificationError, match="model IDs"):
        validate_single_gpu_runtime_evidence(evidence, load_catalog())


def test_runtime_evidence_cannot_claim_authority() -> None:
    evidence = _evidence()
    evidence["authority_claimed"] = True
    with pytest.raises(RuntimeQualificationError, match="cannot claim"):
        validate_single_gpu_runtime_evidence(evidence, load_catalog())
