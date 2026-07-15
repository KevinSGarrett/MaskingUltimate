"""Fail-closed verification for the optional SAM3-LiteText runtime lock."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

DEFAULT_REGISTRY = Path("configs/external_sources.yaml")
DEFAULT_LOCK = Path("env/sam3_litetext_s0_runtime.lock.json")
LOCKED_MANIFEST_SHA256 = "f449bf80c44d44b96d198f07540c555276ee92eaadcd5860b9324080c4f53b01"


class Sam3LiteTextLockError(ValueError):
    """The optional experiment lock drifted or overclaims qualification."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sam3_litetext_runtime_lock(
    lock_path: Path = DEFAULT_LOCK,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    enforce_locked_hash: bool = True,
) -> dict[str, Any]:
    """Verify installed artifacts, live evidence, and shadow-only authority."""
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
        lock.get("schema_version") != "1.1.0"
        or lock.get("provider") != "sam3_litetext_s0"
        or lock.get("status") != "installed_live_smoke_official_comparison_pending"
    ):
        raise Sam3LiteTextLockError("sam3_litetext_lock_identity_invalid")

    source = lock.get("source", {})
    checkpoint = lock.get("checkpoint", {})
    runtime = lock.get("runtime_candidate", {})
    if entry.get("lifecycle_state") != "installed":
        raise Sam3LiteTextLockError("sam3_litetext_registry_must_be_installed")
    if entry.get("runtime_lock") != DEFAULT_LOCK.as_posix():
        raise Sam3LiteTextLockError("sam3_litetext_registry_lock_path_mismatch")
    if source != {
        "repository": entry.get("repo"),
        "commit": entry.get("source_revision"),
    }:
        raise Sam3LiteTextLockError("sam3_litetext_source_registry_mismatch")
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

    expected_runtime = {
        "package": "transformers",
        "version": "5.13.1",
        "source_repository": "https://github.com/huggingface/transformers",
        "source_commit": "4626421dc6b741a329300682a6408246ee465490",
        "wheel_sha256": "53f0ea8aa397e29244c2377ba981bcaf0c87adcf44fbdd447ef6306522afcacd",
        "platform_target": "WSL Ubuntu-22.04 linux-64",
        "environment_status": "installed_verified",
        "environment_path": "/home/kevin/mfenvs/sam3-litetext-b09766e5",
        "python": "3.12.13",
        "torch": "2.10.0+cu128",
        "torchvision": "0.25.0+cu128",
        "cuda": "12.8",
        "requirements_lock": "env/sam3_litetext_s0_runtime.requirements.lock.txt",
        "requirements_lock_sha256": (
            "511ba2864defea1b3858587c040d8bd66e8e7a3ee02d30af173541846cad0dbd"
        ),
    }
    if runtime != expected_runtime:
        raise Sam3LiteTextLockError("sam3_litetext_runtime_identity_invalid")
    requirements_path = Path(runtime["requirements_lock"])
    if (
        not requirements_path.is_file()
        or _file_sha256(requirements_path) != runtime["requirements_lock_sha256"]
    ):
        raise Sam3LiteTextLockError("sam3_litetext_requirements_lock_hash_mismatch")
    qualification = lock.get("qualification")
    if not isinstance(qualification, dict) or qualification != {
        "installation_verified": True,
        "import_verified": True,
        "checkpoint_inference_verified": True,
        "peak_allocated_bytes": 1479608320,
        "peak_reserved_bytes": 1660944384,
        "inference_seconds": [2.148611, 0.323472],
        "instance_count": 4,
        "output_sha256": "dc6dc62a2c3bf9d47396a61970cb2ac0896f40c065a0ee67dceac48a9ecd0733",
        "determinism_verified": True,
        "failure_behavior": "local_missing_checkpoint_refused_without_network_fallback",
        "live_smoke_evidence": ("qa/live_verification/sam3_litetext_s0_runtime_20260715.json"),
        "live_smoke_evidence_sha256": (
            "f3711cac810781ad02b2cd8ec4ec538d82f580b129c9999ed6dcb2b2717cae12"
        ),
        "quality_benchmark": None,
        "claims_not_made": [
            "SAM3-LiteText uses less VRAM than official SAM 3.1",
            "SAM3-LiteText is non-inferior to official SAM 3.1",
        ],
    }:
        raise Sam3LiteTextLockError("sam3_litetext_qualification_invalid")
    evidence_path = Path(qualification["live_smoke_evidence"])
    if (
        not evidence_path.is_file()
        or _file_sha256(evidence_path) != qualification["live_smoke_evidence_sha256"]
    ):
        raise Sam3LiteTextLockError("sam3_litetext_live_evidence_hash_mismatch")

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
        "status": "pass_installed_shadow_smoke_official_comparison_pending",
        "manifest_sha256": expected_hash,
        "source_commit": source["commit"],
        "checkpoint_sha256": checkpoint["sha256"],
        "runtime_source": entry["runtime_source"],
        "role_eligibility": authority["role_eligibility"],
        "official_reference": authority["official_reference"],
        "peak_allocated_bytes": qualification["peak_allocated_bytes"],
        "instance_count": qualification["instance_count"],
    }


def verify_sam3_litetext_preinstall_lock(
    lock_path: Path = DEFAULT_LOCK,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    enforce_locked_hash: bool = True,
) -> dict[str, Any]:
    """Backward-compatible alias for callers created before live installation."""
    return verify_sam3_litetext_runtime_lock(
        lock_path,
        registry_path=registry_path,
        enforce_locked_hash=enforce_locked_hash,
    )


__all__ = [
    "DEFAULT_LOCK",
    "DEFAULT_REGISTRY",
    "Sam3LiteTextLockError",
    "verify_sam3_litetext_preinstall_lock",
    "verify_sam3_litetext_runtime_lock",
]
