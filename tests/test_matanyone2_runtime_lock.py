from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from maskfactory.providers.matanyone2 import (
    MATANYONE2_BACKBONE_SHA256S,
    MATANYONE2_CHECKPOINT_REVISION,
    MATANYONE2_CHECKPOINT_SHA256,
    MATANYONE2_CONFIG_SHA256,
    MATANYONE2_RUNTIME_FINGERPRINT,
    MATANYONE2_SOURCE_REVISION,
    STATIC_ROUTE,
    TEMPORAL_ROUTE,
)

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "env" / "matanyone2_runtime.lock.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_matanyone2_runtime_lock_binds_exact_source_model_backbones_and_environment() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert lock["provider"] == "matanyone2"
    assert lock["source"]["commit"] == MATANYONE2_SOURCE_REVISION
    assert lock["model"]["repository_revision"] == MATANYONE2_CHECKPOINT_REVISION
    assert lock["model"]["checkpoint"]["sha256"] == MATANYONE2_CHECKPOINT_SHA256
    assert lock["model"]["config"]["sha256"] == MATANYONE2_CONFIG_SHA256
    assert {
        name: record["sha256"] for name, record in lock["model"]["backbones"].items()
    } == MATANYONE2_BACKBONE_SHA256S
    assert lock["runtime"]["runtime_fingerprint"] == MATANYONE2_RUNTIME_FINGERPRINT
    requirements = ROOT / lock["runtime"]["requirements_lock"]
    assert _sha256(requirements) == lock["runtime"]["requirements_lock_sha256"]
    runner = ROOT / lock["contract"]["runner"]
    assert _sha256(runner) == lock["contract"]["runner_sha256"]
    assert lock["contract"]["routes"] == {
        STATIC_ROUTE: "exactly_one_frame",
        TEMPORAL_ROUTE: "at_least_two_frames",
    }
    assert lock["contract"]["semantic_authority"] is False
    assert lock["live_smoke"]["static_result"] == "pass"
    assert lock["live_smoke"]["temporal_result"] == "pass"


def test_matanyone2_registry_is_installed_shadow_only_and_hash_bound() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    registry = yaml.safe_load(
        (ROOT / "configs" / "external_sources.yaml").read_text(encoding="utf-8")
    )["providers"]["matanyone2"]
    assert registry["lifecycle_state"] == "installed"
    assert registry["role_eligibility"] == "shadow_only"
    assert registry["source_revision"] == lock["source"]["commit"]
    assert registry["checkpoint"]["sha256"] == lock["model"]["checkpoint"]["sha256"]
    assert registry["runtime_lock"] == "env/matanyone2_runtime.lock.json"
    assert registry["runtime_evidence"] == lock["live_smoke"]["evidence"]
    assert set(registry["capabilities"]) == {STATIC_ROUTE, TEMPORAL_ROUTE}
    assert (
        "never discovers semantic labels or person ownership" in registry["authority_constraints"]
    )


def test_matanyone2_live_evidence_proves_both_routes_without_authority() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    evidence = json.loads((ROOT / lock["live_smoke"]["evidence"]).read_text(encoding="utf-8"))
    assert evidence["result"] == "live_static_and_temporal_capability_passed_shadow_challenger"
    assert evidence["static_smoke"]["route"] == STATIC_ROUTE
    assert evidence["static_smoke"]["frame_count"] == 1
    assert evidence["temporal_smoke"]["route"] == TEMPORAL_ROUTE
    assert evidence["temporal_smoke"]["frame_count"] == 2
    assert evidence["static_smoke"]["deterministic"] is True
    assert evidence["temporal_smoke"]["deterministic"] is True
    assert evidence["static_smoke"]["fractional_alpha_fraction"] > 0
    assert evidence["temporal_smoke"]["fractional_alpha_fraction"] > 0
    contract = evidence["capability_contract"]
    assert contract["semantic_authority"] is False
    assert contract["gold_authority"] is False
    assert contract["production_mask_authority"] is False
    assert evidence["shared_gpu_coordination"] == {
        "coordinator": "SharedRunPodCoordinator v2",
        "adopted_after_existing_live_smokes": True,
        "new_gpu_work_performed_after_adoption": False,
        "cpu_only_freeze_and_validation_requires_lease": False,
    }
