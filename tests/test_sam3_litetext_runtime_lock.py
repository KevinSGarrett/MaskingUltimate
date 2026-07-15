import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from maskfactory.providers.sam3_litetext import (
    Sam3LiteTextLockError,
    verify_sam3_litetext_preinstall_lock,
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


def test_sam3_litetext_preinstall_inputs_are_exact_and_explicitly_unqualified() -> None:
    result = verify_sam3_litetext_preinstall_lock()

    assert result == {
        "status": "pass_inputs_frozen_not_installed_not_qualified",
        "manifest_sha256": ("ca0a362329aec9bda933bf88d0ac352eca2022002366de74455c3219c496eede"),
        "source_commit": "bef17f5c24dc5ef19dc1d8e9663345a2ae7f2f5a",
        "checkpoint_sha256": ("69c86fda4d53492cca2a362dae050f3c2b92afa4faedf44262a6b6d082da9906"),
        "runtime_source": ("transformers==5.13.1@4626421dc6b741a329300682a6408246ee465490"),
        "role_eligibility": "shadow_only_experiment",
        "official_reference": "sam3_1",
    }


def test_sam3_litetext_lock_rejects_manifest_drift(tmp_path: Path) -> None:
    document = json.loads(LOCK.read_text(encoding="utf-8"))
    document["runtime_candidate"]["version"] = "5.13.2"

    with pytest.raises(Sam3LiteTextLockError, match="manifest_hash_mismatch"):
        verify_sam3_litetext_preinstall_lock(_write_json(tmp_path, document))


@pytest.mark.parametrize(
    ("section", "field", "value", "error"),
    [
        ("checkpoint", "downloaded", True, "checkpoint_installation_overclaim"),
        ("runtime_candidate", "environment_path", "/tmp/fake", "runtime_installation_overclaim"),
        ("qualification", "peak_vram_mb", 4096, "qualification_overclaim"),
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
