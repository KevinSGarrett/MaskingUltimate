from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from maskfactory.vlm.client import parse_part_verdict

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "env" / "qwen3_vl_ollama.lock.json"
EVIDENCE_PATH = ROOT / "qa" / "live_verification" / "qwen3_vl_ollama_runtime_20260714.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_qwen3_vl_registry_and_runtime_lock_bind_exact_installed_variants() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    registry = yaml.safe_load(
        (ROOT / "configs" / "external_sources.yaml").read_text(encoding="utf-8")
    )["providers"]["qwen3_vl"]
    assert registry["lifecycle_state"] == "installed"
    assert registry["verify_license"] is False
    assert registry["source_revision"] == lock["source"]["revision"]
    assert registry["license_snapshot_sha256"] == lock["license"]["ollama_license_layer_sha256"]
    for key, variant in lock["variants"].items():
        assert registry["variants"][key]["model"] == variant["model"]
        assert registry["variants"][key]["manifest_sha256"] == variant["ollama_manifest_sha256"]
        assert registry["variants"][key]["hf_revision"] == variant["hf_revision"]


def test_qwen3_vl_reproduction_files_and_live_evidence_are_hash_bound() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    reproduction = lock["reproduction"]
    assert _sha256(ROOT / reproduction["smoke_script"]) == reproduction["smoke_script_sha256"]
    assert (
        _sha256(ROOT / reproduction["provider_adapter"]) == reproduction["provider_adapter_sha256"]
    )
    assert _sha256(ROOT / reproduction["client"]) == reproduction["client_sha256"]
    assert _sha256(EVIDENCE_PATH) == lock["smoke"]["evidence_file_sha256"]
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    claimed = evidence.pop("sha256")
    assert (
        claimed
        == hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def test_qwen3_vl_live_strict_schema_vram_latency_and_fallback_boundary() -> None:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert evidence["result"] == "pass"
    assert evidence["runtime"]["version"] == "0.32.0"
    assert evidence["incumbent_preserved"]["model"] == "qwen2.5vl:7b"
    assert evidence["incumbent_preserved"]["available"] is True
    assert evidence["failure_behavior"]["http_404"] is True
    for model in evidence["models"].values():
        assert model["post_warmup_cross_request_deterministic"] is True
        assert model["process"]["context_length"] == 4096
        assert model["process"]["size_vram"] < 8 * 1024**3
        assert max(item["elapsed_seconds"] for item in model["warm"]) < 5
        assert parse_part_verdict(json.dumps(model["response"])) == model["response"]
        assert (
            parse_part_verdict(json.dumps(model["provider_adapter_response"]))
            == model["provider_adapter_response"]
        )
    assert (
        evidence["models"]["qwen3_vl_4b"]["warmup_response_sha256"]
        == evidence["models"]["qwen3_vl_4b"]["response_sha256"]
    )
    assert (
        evidence["models"]["qwen3_vl_8b_quantized"]["warmup_response_sha256"]
        != evidence["models"]["qwen3_vl_8b_quantized"]["response_sha256"]
    )
    assert evidence["authority"] == {
        "lifecycle_state": "installed",
        "may_approve_gold": False,
        "may_author_masks": False,
        "may_clear_blocks": False,
        "promotion_claimed": False,
        "shadow_only": True,
    }
