from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from maskfactory.providers.sam2matting import (
    SAM2MATTING_CHECKPOINT_REVISION,
    SAM2MATTING_CHECKPOINT_SHA256,
    SAM2MATTING_RUNTIME_FINGERPRINT,
    SAM2MATTING_SOURCE_REVISION,
)

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "env" / "sam2matting_runtime.lock.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_sam2matting_runtime_lock_binds_provider_and_exact_environment() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert lock["provider"] == "sam2matting_base_plus"
    assert lock["source"]["commit"] == SAM2MATTING_SOURCE_REVISION
    assert lock["checkpoint"]["repository_revision"] == SAM2MATTING_CHECKPOINT_REVISION
    assert lock["checkpoint"]["sha256"] == SAM2MATTING_CHECKPOINT_SHA256
    assert lock["runtime"]["runtime_fingerprint"] == SAM2MATTING_RUNTIME_FINGERPRINT
    requirements = ROOT / lock["runtime"]["requirements_lock"]
    assert _sha256(requirements) == lock["runtime"]["requirements_lock_sha256"]
    runner = ROOT / lock["contract"]["runner"]
    assert _sha256(runner) == lock["contract"]["runner_sha256"]
    assert lock["contract"]["semantic_authority"] is False
    assert lock["live_smoke"]["result"] == "pass"


def test_sam2matting_registry_is_installed_shadow_only_and_hash_bound() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    registry = yaml.safe_load(
        (ROOT / "configs" / "external_sources.yaml").read_text(encoding="utf-8")
    )["providers"]["sam2matting_base_plus"]
    assert registry["lifecycle_state"] == "installed"
    assert registry["role_eligibility"] == "shadow_only"
    assert registry["source_revision"] == lock["source"]["commit"]
    assert registry["checkpoint"]["sha256"] == lock["checkpoint"]["sha256"]
    assert registry["runtime_lock"] == "env/sam2matting_runtime.lock.json"
    assert registry["runtime_evidence"] == lock["live_smoke"]["evidence"]
    assert "never decides semantic labels" in registry["authority_constraints"]


def test_sam2matting_live_evidence_is_non_authoritative_and_geometry_exact() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    evidence = json.loads((ROOT / lock["live_smoke"]["evidence"]).read_text(encoding="utf-8"))
    assert evidence["result"] == "live_smoke_passed_shadow_boundary_challenger"
    assert evidence["smoke"]["deterministic"] is True
    assert evidence["smoke"]["repeats"] == 2
    assert evidence["smoke"]["alpha_shape"] == evidence["fixture"]["shape"]
    assert evidence["smoke"]["fractional_alpha_fraction"] > 0
    assert evidence["authority"] == {
        "semantic_label_authority": False,
        "gold_authority": False,
        "production_mask_authority": False,
        "lifecycle": "installed_shadow_challenger",
        "fallback": "explicit incumbent only",
    }
