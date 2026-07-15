import hashlib
import json
from pathlib import Path

import yaml

from maskfactory.governance import (
    provider_activation_issues,
    validate_external_source_registry,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "5dd401d1c5c1d5c3eedff06d41b77af824517619"
CHECKPOINT_REVISION = "daa63191845a41281374e725f4c9e51c7a824460"
CHECKPOINT_SHA256 = "0567debeec80ba4ac6369540c6c248025283cb3ff2b92827509e57e2b3541cb6"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_sam31_registry_and_runtime_lock_freeze_exact_official_artifacts() -> None:
    registry = yaml.safe_load(
        (ROOT / "configs" / "external_sources.yaml").read_text(encoding="utf-8")
    )
    assert validate_external_source_registry(registry) == {
        "schema_version": "2.0.0",
        "legacy": False,
    }
    entry = registry["providers"]["sam3_1"]
    lock = json.loads((ROOT / "env" / "sam31_runtime.lock.json").read_text())

    assert entry["source_revision"] == SOURCE_COMMIT == lock["source"]["commit"]
    assert entry["checkpoint"]["sha256"] == CHECKPOINT_SHA256
    assert lock["checkpoint"] == {
        "repository": "facebook/sam3.1",
        "repository_revision": CHECKPOINT_REVISION,
        "filename": "sam3.1_multiplex.pt",
        "sha256": CHECKPOINT_SHA256,
        "size_bytes": 3502755717,
        "gating": "manual",
        "access_status": "needs_kevin_terms_acceptance",
        "unauthenticated_http_status": 401,
        "downloaded": False,
    }
    requirements = ROOT / lock["runtime"]["requirements_lock"]
    assert _sha256(requirements) == lock["runtime"]["requirements_lock_sha256"]


def test_sam31_source_runtime_evidence_does_not_overclaim_checkpoint_installation() -> None:
    evidence = json.loads(
        (ROOT / "qa" / "live_verification" / "sam31_source_runtime_20260714.json").read_text()
    )
    lock = json.loads((ROOT / "env" / "sam31_runtime.lock.json").read_text())

    assert evidence["result"] == "SOURCE_RUNTIME_PASS_CHECKPOINT_BLOCKED"
    assert evidence["source"]["commit"] == lock["source"]["commit"]
    assert evidence["checkpoint"]["sha256"] == lock["checkpoint"]["sha256"]
    assert evidence["checkpoint"]["downloaded"] is False
    assert evidence["runtime"]["cuda_available"] is True
    assert evidence["runtime"]["compute_capability"] == [12, 0]
    assert evidence["runtime"]["image_builder_import"] is True
    assert evidence["runtime"]["multiplex_builder_import"] is True
    assert "SAM 3.1 inference passed" in evidence["claims_not_made"]


def test_sam31_remains_ineligible_until_checkpoint_terms_and_smoke_are_resolved() -> None:
    registry = yaml.safe_load(
        (ROOT / "configs" / "external_sources.yaml").read_text(encoding="utf-8")
    )
    entry = registry["providers"]["sam3_1"]

    for lane in ("adult_nonexplicit", "consensual_explicit_adult"):
        assert entry["content_compatibility"][lane] == "allowed"
        assert provider_activation_issues(entry, content_lane=lane) == (
            "lifecycle_state='planned' is not activatable",
            "license verification is unresolved",
        )
