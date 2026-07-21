import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from maskfactory.providers.sam3_litetext import (
    Sam3LiteTextLockError,
    verify_sam3_litetext_preinstall_lock,
    verify_sam3_litetext_runtime_lock,
)

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "env" / "sam3_litetext_s0_runtime.lock.json"
REGISTRY = ROOT / "configs" / "external_sources.yaml"


def _rehash(document: dict) -> None:
    payload = {key: value for key, value in document.items() if key != "manifest_sha256"}
    document["manifest_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_json(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "sam3_litetext_s0_runtime.lock.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def test_sam3_litetext_runtime_is_exact_installed_and_shadow_only() -> None:
    result = verify_sam3_litetext_runtime_lock()

    assert result == {
        "status": "pass_installed_shadow_smoke_official_comparison_pending",
        "manifest_sha256": ("f449bf80c44d44b96d198f07540c555276ee92eaadcd5860b9324080c4f53b01"),
        "source_commit": "bef17f5c24dc5ef19dc1d8e9663345a2ae7f2f5a",
        "checkpoint_sha256": ("69c86fda4d53492cca2a362dae050f3c2b92afa4faedf44262a6b6d082da9906"),
        "runtime_source": ("transformers==5.13.1@4626421dc6b741a329300682a6408246ee465490"),
        "role_eligibility": "shadow_only_experiment",
        "official_reference": "sam3_1",
        "peak_allocated_bytes": 1479608320,
        "instance_count": 4,
    }
    assert verify_sam3_litetext_preinstall_lock() == result


def test_sam3_litetext_lock_rejects_manifest_drift(tmp_path: Path) -> None:
    document = json.loads(LOCK.read_text(encoding="utf-8"))
    document["runtime_candidate"]["version"] = "5.13.2"

    with pytest.raises(Sam3LiteTextLockError, match="manifest_hash_mismatch"):
        verify_sam3_litetext_preinstall_lock(_write_json(tmp_path, document))


@pytest.mark.parametrize(
    ("section", "field", "value", "error"),
    [
        ("checkpoint", "downloaded", False, "checkpoint_registry_mismatch"),
        ("runtime_candidate", "environment_path", "/tmp/fake", "runtime_identity_invalid"),
        ("qualification", "peak_allocated_bytes", 4096, "qualification_invalid"),
        ("authority", "substitution_forbidden", False, "authority_invalid"),
    ],
)
def test_sam3_litetext_lock_rejects_unverified_claims_even_when_rehashed(
    tmp_path: Path,
    section: str,
    field: str,
    value: object,
    error: str,
) -> None:
    document = copy.deepcopy(json.loads(LOCK.read_text(encoding="utf-8")))
    document[section][field] = value
    _rehash(document)

    with pytest.raises(Sam3LiteTextLockError, match=error):
        verify_sam3_litetext_preinstall_lock(
            _write_json(tmp_path, document), enforce_locked_hash=False
        )


def test_sam3_litetext_lock_rejects_registry_revision_drift(tmp_path: Path) -> None:
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    registry["providers"]["sam3_litetext_s0"]["checkpoint_revision"] = "f" * 40
    registry_path = tmp_path / "external_sources.yaml"
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

    with pytest.raises(Sam3LiteTextLockError, match="checkpoint_registry_mismatch"):
        verify_sam3_litetext_preinstall_lock(registry_path=registry_path)


def test_sam3_litetext_live_evidence_is_strict_deterministic_and_non_authoritative() -> None:
    evidence = json.loads(
        (ROOT / "qa/live_verification/sam3_litetext_s0_runtime_20260715.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["result"] == "pass_installed_shadow_smoke_official_comparison_pending"
    assert evidence["observations"]["instance_count"] == 4
    assert evidence["observations"]["strict_binary_png"] is True
    assert evidence["observations"]["deterministic_two_run"] is True
    assert evidence["runtime"]["peak_allocated_bytes"] == 1479608320
    assert evidence["authority"] == {
        "gold_authority": False,
        "lifecycle_state": "installed",
        "official_reference": "sam3_1",
        "production_authority": False,
        "promotion_claimed": False,
        "role_eligibility": "shadow_only_experiment",
        "substitution_forbidden": True,
    }
    assert evidence["comparison"] == {
        "human_anchor_benchmark": "pending",
        "lower_memory_than_official_claimed": False,
        "official_sam31_checkpoint_available": False,
        "quality_noninferiority_claimed": False,
    }
