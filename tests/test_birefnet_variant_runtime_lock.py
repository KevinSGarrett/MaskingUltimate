from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "env" / "birefnet_variants.lock.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_birefnet_registry_binds_installed_variants_and_adult_lanes() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    registry = yaml.safe_load(
        (ROOT / "configs" / "external_sources.yaml").read_text(encoding="utf-8")
    )["providers"]
    for key, variant in lock["variants"].items():
        entry = registry[key]
        assert entry["lifecycle_state"] == "installed"
        assert entry["verify_license"] is False
        assert entry["license_snapshot_sha256"] == lock["source"]["license_snapshot_sha256"]
        assert entry["source_revision"] == variant["hf_revision"]
        assert entry["checkpoint_sha256"] == variant["checkpoint_sha256"]
        assert entry["local_path"] == variant["local_path"]
        assert entry["runtime_lock"] == "env/birefnet_variants.lock.json"
        assert entry["content_compatibility"] == {
            "adult_nonexplicit": "allowed",
            "consensual_explicit_adult": "allowed",
        }


def test_birefnet_lock_hash_binds_reproduction_and_evidence() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    reproduction = lock["reproduction"]
    for key in (
        "setup_script",
        "smoke_script",
        "runner",
        "provider_adapter",
        "integration_script",
        "contract_tests",
    ):
        assert _sha256(ROOT / reproduction[key]) == reproduction[f"{key}_sha256"]
    evidence = lock["evidence"]
    for key in ("installation", "runtime", "provider_integration"):
        assert _sha256(ROOT / evidence[key]) == evidence[f"{key}_sha256"]


def test_birefnet_live_evidence_is_canonical_and_shadow_only() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    for evidence_key in ("installation", "runtime", "provider_integration"):
        evidence = json.loads((ROOT / lock["evidence"][evidence_key]).read_text(encoding="utf-8"))
        claimed = evidence.pop("sha256")
        assert (
            claimed
            == hashlib.sha256(
                json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        assert evidence["result"] == "pass"
    integration = json.loads(
        (ROOT / lock["evidence"]["provider_integration"]).read_text(encoding="utf-8")
    )
    assert integration["authority"] == {
        "lifecycle_state": "installed",
        "may_author_gold": False,
        "promotion_claimed": False,
        "shadow_only": True,
    }
    assert integration["fallback_selection"]["active"] == "birefnet_general"
    assert integration["fallback_selection"]["rollback"] == "birefnet_general"
    assert integration["variants"]["birefnet_hr"]["resolution"] == 1024
    assert (
        integration["variants"]["birefnet_hr_matting"]["matting"]["fractional_alpha_fraction"]
        > 0.001
    )


def test_birefnet_2048_memory_result_cannot_claim_8gb_promotion() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    policy = lock["memory_policy"]
    assert policy["hr_2048_peak_allocated_bytes"] > policy["available_dedicated_gpu_bytes"]
    assert policy["hr_matting_2048_peak_allocated_bytes"] > policy["available_dedicated_gpu_bytes"]
    assert lock["variants"]["birefnet_hr"]["governed_resolution"] == 1024
    assert lock["variants"]["birefnet_hr_matting"]["governed_resolution"] == 1024
    assert lock["authority"]["promotion_claimed"] is False
