from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "env" / "rfdetr_runtime.lock.json"
REQUIREMENTS_PATH = ROOT / "env" / "rfdetr_runtime.requirements.lock.txt"
EVIDENCE_PATH = ROOT / "qa" / "live_verification" / "rfdetr_medium_runtime_20260714.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_rfdetr_registry_is_exact_installed_shadow_runtime() -> None:
    registry = yaml.safe_load((ROOT / "configs" / "external_sources.yaml").read_text())
    provider = registry["providers"]["rfdetr"]
    lock = json.loads(LOCK_PATH.read_text())
    assert provider["lifecycle_state"] == "installed"
    assert provider["verify_license"] is False
    assert provider["source_revision"] == lock["source"]["revision"]
    assert provider["source_tree"] == lock["source"]["tree"]
    assert provider["license_snapshot_sha256"] == lock["license"]["sha256"]
    assert provider["checkpoint"]["sha256"] == lock["checkpoint"]["sha256"]
    assert lock["activation"] == {
        "lifecycle_state": "installed",
        "shadow_only": True,
        "incumbent": "yolo11",
        "benchmark_required_for_promotion": True,
    }
    assert "plus" not in provider["checkpoint"]["filename"].lower()


def test_rfdetr_runtime_freeze_and_scripts_match_hashes() -> None:
    lock = json.loads(LOCK_PATH.read_text())
    reproduction = lock["reproduction"]
    assert _sha256(REQUIREMENTS_PATH) == reproduction["requirements_sha256"]
    assert _sha256(ROOT / reproduction["setup_script"]) == reproduction["setup_script_sha256"]
    assert _sha256(ROOT / reproduction["smoke_script"]) == reproduction["smoke_script_sha256"]
    requirements = REQUIREMENTS_PATH.read_text()
    for pin in (
        "rfdetr @ file:///mnt/c/Comfy_UI_Main_Masking/models/runtime_cache/rfdetr_source_1.7.1",
        "torch==2.11.0+cu128",
        "torchvision==0.26.0+cu128",
        "transformers==5.13.1",
    ):
        assert pin in requirements


def test_rfdetr_live_evidence_is_deterministic_and_bounded() -> None:
    evidence = json.loads(EVIDENCE_PATH.read_text())
    optimized = evidence["optimized_fp16"]
    assert evidence["result"] == "pass"
    assert optimized["person_count"] == 4
    assert optimized["within_process_deterministic"] is True
    assert optimized["cross_process_deterministic"] is True
    assert optimized["output_sha256"] == optimized["cross_process_replay_output_sha256"]
    assert optimized["peak_reserved_bytes"] < 8 * 1024**3
    assert max(optimized["warm_inference_seconds"]) < 1.0
    assert evidence["failure_behavior"]["exit_code"] != 0
    assert evidence["authority_boundary"]["promotion_claimed"] is False
