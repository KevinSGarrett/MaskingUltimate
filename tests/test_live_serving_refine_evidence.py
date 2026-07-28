import json
from pathlib import Path


def test_live_serving_refine_evidence_is_valid_and_proves_warm_latency_pass() -> None:
    audit = json.loads(
        Path("qa/live_verification/serve_refine_cuda_20260712.json").read_text(encoding="utf-8")
    )
    assert audit["http_status"] == 200
    assert audit["endpoint"] == "http://127.0.0.1:8765/refine"
    assert audit["health"]["status"] == "ok"
    assert audit["health"]["vram"]["gpus"][0]["name"] == ("NVIDIA GeForce RTX 5060 Laptop GPU")
    assert audit["health"]["configured_models"] == []
    assert audit["health"]["loaded_models"] == []
    assert audit["response_status"] == "draft_model_generated"
    assert audit["provenance"] == {"source": "sam2_interactive_refine"}
    assert audit["mask_mode"] == "L"
    assert audit["mask_size"] == [810, 1080]
    assert audit["mask_values"] == [0, 255]
    assert audit["area_px"] > 0
    assert audit["cold_start_seconds"] > audit["elapsed_seconds"]
    assert audit["latency_target_seconds"] == 1.2
    assert audit["latency_target_met"] is True
    assert audit["elapsed_seconds"] <= audit["latency_target_seconds"]
