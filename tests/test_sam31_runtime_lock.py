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
        "access_status": "accepted_access_verified",
        "unauthenticated_http_status": 401,
        "downloaded": True,
        "local_path": "models/runtime_cache/sam31_checkpoint_daa63191/sam3.1_multiplex.pt",
        "installed_at": "2026-07-17T09:04:00Z",
        "access_probe_sha256": "975d6a345b36f042fb92611c629bbd08a4c856cdf4d33724c5bb2e8a2d4bdc1d",
    }
    requirements = ROOT / lock["runtime"]["requirements_lock"]
    assert _sha256(requirements) == lock["runtime"]["requirements_lock_sha256"]


def test_sam31_checkpoint_install_evidence_does_not_overclaim_runtime_smoke() -> None:
    evidence = json.loads(
        (ROOT / "qa" / "live_verification" / "sam31_checkpoint_install_20260717.json").read_text()
    )
    lock = json.loads((ROOT / "env" / "sam31_runtime.lock.json").read_text())

    assert evidence["result"] == "CHECKPOINT_INSTALL_PASS_RUNTIME_SMOKE_PENDING"
    assert evidence["source"]["commit"] == lock["source"]["commit"]
    assert evidence["installation"]["sha256"] == lock["checkpoint"]["sha256"]
    assert evidence["installation"]["expected_size_match"] is True
    assert evidence["installation"]["atomic_promotion"] is True
    assert evidence["runtime"]["checkpoint_inference"] == "not_run_wsl_filesystem_io_error"
    assert "SAM 3.1 inference passed" in evidence["claims_not_made"]


def test_sam31_remains_ineligible_until_smoke_and_benchmark_are_resolved() -> None:
    registry = yaml.safe_load(
        (ROOT / "configs" / "external_sources.yaml").read_text(encoding="utf-8")
    )
    entry = registry["providers"]["sam3_1"]

    assert provider_activation_issues(entry) == ("lifecycle_state='planned' is not activatable",)


def test_sam31_lock_binds_correct_multiplex_checkpoint_smoke_contract() -> None:
    lock = json.loads((ROOT / "env/sam31_runtime.lock.json").read_text(encoding="utf-8"))
    contract = lock["live_smoke"]["subprocess_contract"]
    assert lock["source"]["local_path"] == "models/runtime_cache/sam3_source_5dd401d1"
    assert contract["status"] == "runtime_pass_bounded_text_discovery"
    assert contract["correct_builder"].startswith("build_sam3_predictor")
    assert contract["forbidden_checkpoint_builder"].startswith("build_sam3_image_model")
    assert contract["adaptation"] == "single_frame_directory_via_object_multiplex"
    assert contract["determinism_repeats"] == 2
    assert _sha256(ROOT / contract["host_verifier"]) == contract["host_verifier_sha256"]
    assert _sha256(ROOT / contract["isolated_runner"]) == contract["isolated_runner_sha256"]
    assert _sha256(ROOT / contract["session_compat"]) == contract["session_compat_sha256"]
    assert _sha256(ROOT / contract["fixture"]) == contract["fixture_sha256"]
    assert lock["live_smoke"]["checkpoint_inference"] == (
        "text_discovery_pass_point_refinement_empty_output"
    )


def test_sam31_lock_binds_official_production_discovery_and_refinement_contract() -> None:
    lock = json.loads((ROOT / "env/sam31_runtime.lock.json").read_text(encoding="utf-8"))
    contract = lock["live_smoke"]["production_contract"]
    assert contract["status"] == ("discovery_runtime_pass_native_box_refinement_fix_probe_pending")
    assert contract["roles"] == ["concept_detector", "interactive_segmenter"]
    assert contract["builder"].startswith("build_sam3_predictor")
    assert "positive/negative box prompts" in contract["visual_exemplars"]
    assert "rejected fail-closed" in contract["external_image_exemplars"]
    assert "exact native normalized visual box prompt" in contract["box_and_mask_prior_translation"]
    assert "rejected fail-closed" in contract["point_refinement"]
    assert "no active-map" in contract["authority"]
    assert _sha256(ROOT / contract["host_runtime"]) == contract["host_runtime_sha256"]
    assert (
        _sha256(ROOT / contract["visual_exemplar_contract"])
        == contract["visual_exemplar_contract_sha256"]
    )
    assert (
        _sha256(ROOT / contract["visual_exemplar_schema"])
        == contract["visual_exemplar_schema_sha256"]
    )
    assert _sha256(ROOT / contract["isolated_runner"]) == contract["isolated_runner_sha256"]
    assert _sha256(ROOT / contract["session_compat"]) == contract["session_compat_sha256"]
