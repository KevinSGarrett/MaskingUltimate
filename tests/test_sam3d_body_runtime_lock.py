from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "env/sam3d_body_runtime.lock.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_sam3d_body_lock_freezes_exact_official_assets_and_source() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    assert lock["provider"] == "sam3d_body"
    assert lock["source"]["commit"] == "b5c765a0d89d789985e186d396315e7590887b94"
    assert lock["checkpoint"]["repository_revision"] == ("11aaa346c7204874a1cbafe3d39a979080b2c55a")
    assert lock["checkpoint"]["total_size_bytes"] == sum(
        asset["size_bytes"] for asset in lock["checkpoint"]["assets"]
    )
    assert {asset["filename"] for asset in lock["checkpoint"]["assets"]} == {
        "model.ckpt",
        "model_config.yaml",
        "assets/mhr_model.pt",
    }
    assert all(len(asset["sha256"]) == 64 for asset in lock["checkpoint"]["assets"])
    source = ROOT / lock["source"]["local_path"]
    assert _sha256(source / "INSTALL.md") == lock["source"]["install_guide_sha256"]
    assert _sha256(source / "README.md") == lock["source"]["readme_sha256"]


def test_sam3d_body_install_evidence_and_registry_remain_non_authoritative() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    evidence = json.loads((ROOT / lock["evidence"]).read_text(encoding="utf-8"))
    registry = yaml.safe_load((ROOT / "configs/external_sources.yaml").read_text(encoding="utf-8"))[
        "providers"
    ]["sam3d_body"]
    assert evidence["result"] == "CHECKPOINT_INSTALL_PASS_RUNTIME_PENDING"
    assert evidence["checkpoint"]["total_size_bytes"] == lock["checkpoint"]["total_size_bytes"]
    assert lock["checkpoint"]["downloaded"] is True
    assert evidence["authority"]["checkpoint_installed"] is True
    assert evidence["authority"]["live_smoke_passed"] is False
    assert lock["authority"]["may_author_gold"] is False
    assert registry["lifecycle_state"] == "planned"
    assert registry["checkpoint_gate"] == "accepted_access_verified"
    assert registry["checkpoint"]["downloaded"] is True


def test_sam3d_body_lock_binds_offline_verified_subprocess_contract() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    contract = lock["runtime"]["subprocess_contract"]
    assert contract["status"] == "offline_verified_live_pending"
    assert contract["invocation"] == "wsl.exe argv only; shell disabled"
    assert contract["person_selection"].startswith("exactly one explicit")
    assert contract["determinism_repeats"] == 2
    assert contract["densepose_fallback"] == "only explicit CUDA/GPU out-of-memory"
    assert _sha256(ROOT / contract["host_adapter"]) == contract["host_adapter_sha256"]
    assert _sha256(ROOT / contract["isolated_runner"]) == contract["isolated_runner_sha256"]
    assert lock["authority"]["live_smoke_passed"] is False
    assert lock["authority"]["may_author_gold"] is False
