from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from maskfactory.vlm.live_calibration import PROMPT_SHA256

ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def test_unavailable_runpod_visual_authority_abstains_without_assigned_roles() -> None:
    config = _load("configs/vlm.yaml")
    production = config["production_runtime"]

    assert production["platform"] == "runpod"
    assert production["persistent_root"] == "/workspace"
    catalog_path = ROOT / production["catalog"]
    assert (
        hashlib.sha256(catalog_path.read_bytes()).hexdigest() == production["catalog_file_sha256"]
    )
    catalog = _load(production["catalog"])
    assert catalog["sha256"] == production["catalog_sha256"]
    assert production["shared_gpu_coordinator_required"] is True
    assert production["primary_visual_critic"] is None
    assert production["independent_family_juror"] is None
    assert production["authority_status"] == (
        "unavailable_pending_positive_and_negative_qualification"
    )
    assert production["certification_behavior_when_unavailable"] == "abstain"
    assert config["runtime"]["production_authority"] is False
    assert config["governance"]["unavailable_visual_authority_requires_abstention"] is True


def test_current_single_board_protocol_is_exactly_hash_bound() -> None:
    production = _load("configs/vlm.yaml")["production_runtime"]
    protocol = production["qualification_protocol"]
    implementation = ROOT / "src/maskfactory/vlm/live_calibration.py"
    runner = ROOT / "tools/run_visual_critic_calibration.py"

    assert protocol["version"] == (
        "maskfactory-live-critic-calibration-v3-single-board-explicit-checks"
    )
    assert (
        hashlib.sha256(implementation.read_bytes()).hexdigest() == protocol["implementation_sha256"]
    )
    assert hashlib.sha256(runner.read_bytes()).hexdigest() == protocol["runner_sha256"]
    assert PROMPT_SHA256 == protocol["prompt_sha256"]


def test_zero_valid_mask_candidates_remain_failed_and_unassigned() -> None:
    config = _load("configs/vlm.yaml")
    catalog = _load("configs/visual_critic_catalog.yaml")
    catalog_models = {row["model_id"]: row for row in catalog["models"]}

    for model_id in ("qwen3_6_27b_fp8", "internvl3_5_8b_bf16"):
        failed = config["production_runtime"]["failed_candidates"][model_id]
        registered = catalog_models[model_id]
        assert failed["valid_mask_pass_rate"] == 0.0
        assert failed["qualification_status"] == "fail"
        assert registered["assigned_roles"] == []
        assert registered["calibration"]["status"] == "fail"


def test_current_protocol_candidates_are_hash_bound_but_not_promoted() -> None:
    config = _load("configs/vlm.yaml")
    catalog = _load("configs/visual_critic_catalog.yaml")
    catalog_models = {row["model_id"]: row for row in catalog["models"]}
    candidates = config["production_runtime"]["unqualified_candidates"]

    for model_id in ("qwen3_vl_30b_a3b_instruct_fp8", "internvl3_5_8b_bf16"):
        registered = catalog_models[model_id]
        expected = (
            candidates[model_id]["artifact_tree_sha256"]
            if model_id in candidates
            else config["production_runtime"]["failed_candidates"][model_id].get(
                "artifact_tree_sha256", registered["artifact_sha256"]
            )
        )
        assert registered["artifact_sha256"] == expected
        assert registered["assigned_roles"] == []

    requirements = set(config["production_runtime"]["enable_autonomous_approval_only_after"])
    assert {
        "acceptable_valid_mask_pass_rate",
        "acceptable_defect_precision_and_recall",
        "ownership_and_label_accuracy",
        "deterministic_replay",
        "current_role_certificates",
        "independent_model_families",
        "real_adult_anatomy_batch_canary",
    } <= requirements
