"""Fail-closed verification for the optional SAM3-LiteText pre-install lock."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

DEFAULT_REGISTRY = Path("configs/external_sources.yaml")
DEFAULT_LOCK = Path("env/sam3_litetext_s0_runtime.lock.json")
LOCKED_MANIFEST_SHA256 = "ca0a362329aec9bda933bf88d0ac352eca2022002366de74455c3219c496eede"


class Sam3LiteTextLockError(ValueError):
    """The optional experiment lock drifted or overclaims qualification."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def verify_sam3_litetext_preinstall_lock(
    lock_path: Path = DEFAULT_LOCK,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    enforce_locked_hash: bool = True,
) -> dict[str, Any]:
    """Verify exact frozen inputs and reject installation or authority overclaims."""
    lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    registry = yaml.safe_load(Path(registry_path).read_text(encoding="utf-8"))
    entry = registry["providers"]["sam3_litetext_s0"]

    expected_hash = _canonical_sha256(
        {key: value for key, value in lock.items() if key != "manifest_sha256"}
    )
    if lock.get("manifest_sha256") != expected_hash:
        raise Sam3LiteTextLockError("sam3_litetext_manifest_hash_mismatch")
    if enforce_locked_hash and expected_hash != LOCKED_MANIFEST_SHA256:
        raise Sam3LiteTextLockError("sam3_litetext_locked_hash_mismatch")
    if (
        lock.get("schema_version") != "1.0.0"
        or lock.get("provider") != "sam3_litetext_s0"
        or lock.get("status") != "inputs_frozen_not_installed_not_qualified"
    ):
        raise Sam3LiteTextLockError("sam3_litetext_lock_identity_invalid")

    source = lock.get("source", {})
    checkpoint = lock.get("checkpoint", {})
    runtime = lock.get("runtime_candidate", {})
    if entry.get("lifecycle_state") != "planned":
        raise Sam3LiteTextLockError("sam3_litetext_registry_must_remain_planned")
    if entry.get("runtime_lock") != DEFAULT_LOCK.as_posix():
        raise Sam3LiteTextLockError("sam3_litetext_registry_lock_path_mismatch")
    if source != {
        "repository": entry.get("repo"),
        "commit": entry.get("source_revision"),
    }:
        raise Sam3LiteTextLockError("sam3_litetext_source_registry_mismatch")
    if checkpoint.get("downloaded") is not False:
        raise Sam3LiteTextLockError("sam3_litetext_checkpoint_installation_overclaim")
    if checkpoint != {
        "repository": "vil-uob/sam3-litetext-s0",
        "repository_revision": entry.get("checkpoint_revision"),
        **entry.get("checkpoint", {}),
    }:
        raise Sam3LiteTextLockError("sam3_litetext_checkpoint_registry_mismatch")
    expected_runtime = (
        f"{runtime.get('package')}=={runtime.get('version')}@{runtime.get('source_commit')}"
    )
    if expected_runtime != entry.get("runtime_source") or runtime.get("wheel_sha256") != entry.get(
        "runtime_wheel_sha256"
    ):
        raise Sam3LiteTextLockError("sam3_litetext_runtime_registry_mismatch")

    unresolved_runtime = (
        "environment_path",
        "python",
        "torch",
        "torchvision",
        "cuda",
        "requirements_lock",
    )
    if runtime.get("environment_status") != "not_created" or any(
        runtime.get(field) is not None for field in unresolved_runtime
    ):
        raise Sam3LiteTextLockError("sam3_litetext_runtime_installation_overclaim")
    qualification = lock.get("qualification")
    if not isinstance(qualification, dict) or qualification != {
        "installation_verified": False,
        "import_verified": False,
        "checkpoint_inference_verified": False,
        "peak_vram_mb": None,
        "latency_ms": None,
        "determinism_verified": False,
        "quality_benchmark": None,
        "claims_not_made": [
            "SAM3-LiteText is installed",
            "SAM3-LiteText runs on this machine",
            "SAM3-LiteText uses less VRAM than official SAM 3.1",
            "SAM3-LiteText is non-inferior to official SAM 3.1",
        ],
    }:
        raise Sam3LiteTextLockError("sam3_litetext_qualification_overclaim")

    authority = lock.get("authority")
    if not isinstance(authority, dict) or authority != {
        "role_eligibility": "shadow_only_experiment",
        "official_reference": "sam3_1",
        "substitution_forbidden": True,
        "permitted_use": "frozen_blinded_tournament_after_governed_installation",
        "forbidden_usages": [
            "active",
            "offline_fallback",
            "oom_fallback",
            "rollback",
            "production_authority",
            "gold_authority",
            "semantic_authority",
        ],
    }:
        raise Sam3LiteTextLockError("sam3_litetext_authority_invalid")
    if (
        entry.get("role_eligibility") != authority["role_eligibility"]
        or entry.get("substitution_forbidden_for") != authority["official_reference"]
    ):
        raise Sam3LiteTextLockError("sam3_litetext_authority_registry_mismatch")
    compatibility = lock.get("license_review", {}).get("content_compatibility")
    if compatibility != entry.get("content_compatibility"):
        raise Sam3LiteTextLockError("sam3_litetext_content_compatibility_mismatch")

    return {
        "status": "pass_inputs_frozen_not_installed_not_qualified",
        "manifest_sha256": expected_hash,
        "source_commit": source["commit"],
        "checkpoint_sha256": checkpoint["sha256"],
        "runtime_source": entry["runtime_source"],
        "role_eligibility": authority["role_eligibility"],
        "official_reference": authority["official_reference"],
    }


__all__ = [
    "DEFAULT_LOCK",
    "DEFAULT_REGISTRY",
    "Sam3LiteTextLockError",
    "verify_sam3_litetext_preinstall_lock",
]
