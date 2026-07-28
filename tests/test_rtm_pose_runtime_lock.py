from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from maskfactory.providers.rtm_pose import (
    COCO_WHOLEBODY_NAMES,
    CROWDPOSE_NAMES,
    RTM_RUNTIME_FINGERPRINT,
)

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "env" / "rtm_pose.lock.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_rtm_registry_binds_installed_variants() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    registry = yaml.safe_load(
        (ROOT / "configs" / "external_sources.yaml").read_text(encoding="utf-8")
    )["providers"]
    for provider_key, registry_key in (("rtmw_x", "rtmw_x"), ("rtmo_crowd", "rtmo")):
        variant = lock["variants"][provider_key]
        entry = registry[registry_key]
        assert entry["lifecycle_state"] == "installed"
        assert entry["verify_license"] is False
        assert entry["license_snapshot_sha256"] == lock["sources"]["mmpose"]["license_sha256"]
        assert entry["source_revision"] == lock["sources"]["mmpose"]["commit"]
        assert entry["checkpoint_sha256"] == variant["checkpoint_sha256"]
        assert entry["config_sha256"] == variant["config_sha256"]
        assert entry["local_path"] == variant["checkpoint_path"]
        assert entry["runtime_lock"] == "env/rtm_pose.lock.json"


def test_rtm_runtime_fingerprint_is_reproducible() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    payload = lock["runtime"]["fingerprint_payload"]
    actual = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert actual == lock["runtime"]["runtime_fingerprint"]
    assert actual == RTM_RUNTIME_FINGERPRINT


def test_rtm_lock_hash_binds_reproduction_and_evidence() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    for key in (
        "requirements",
        "setup_script",
        "smoke_script",
        "runner",
        "provider_adapter",
        "integration_script",
        "provider_tests",
    ):
        assert _sha256(ROOT / lock["reproduction"][key]) == lock["reproduction"][f"{key}_sha256"]
    for key in ("installation", "runtime", "provider_integration"):
        assert _sha256(ROOT / lock["evidence"][key]) == lock["evidence"][f"{key}_sha256"]


def test_rtm_live_evidence_is_canonical_exact_vocab_and_shadow_only() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    for key in ("installation", "runtime", "provider_integration"):
        document = json.loads((ROOT / lock["evidence"][key]).read_text(encoding="utf-8"))
        claimed = document.pop("sha256")
        assert (
            claimed
            == hashlib.sha256(
                json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        assert document["result"] == "pass"
    runtime = json.loads((ROOT / lock["evidence"]["runtime"]).read_text(encoding="utf-8"))
    integration = json.loads(
        (ROOT / lock["evidence"]["provider_integration"]).read_text(encoding="utf-8")
    )
    assert runtime["variants"]["rtmw_x"]["joint_vocabulary"] == list(COCO_WHOLEBODY_NAMES)
    assert runtime["variants"]["rtmo_crowd"]["joint_vocabulary"] == list(CROWDPOSE_NAMES)
    assert integration["variants"]["rtmo_crowd"]["joint_vocabulary"] == list(CROWDPOSE_NAMES)
    assert integration["crowd_qualification"]["live_candidate_count"] >= 3
    assert integration["authority"] == {
        "lifecycle_state": "installed",
        "may_author_gold": False,
        "promotion_claimed": False,
        "shadow_only": True,
    }
    assert integration["fallback_selection"]["active"] == "dwpose_133"
    assert integration["fallback_selection"]["rollback"] == "dwpose_133"
    assert integration["fallback_selection"]["independent_vote"] == "mediapipe_hands"
