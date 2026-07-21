from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.training.docker_contract import (
    ARTIFACT_TYPE,
    AUTHORITY,
    COMPOSE_CHECKS,
    DEFAULT_COMPOSE_PATH,
    DEFAULT_DOCKERFILE_PATH,
    DOCKERFILE_CHECKS,
    PROOF_TIER,
    DockerTrainContractError,
    evaluate_compose_contract,
    evaluate_dockerfile_contract,
    probe_docker_train_contract,
    run_docker_train_contract_suite,
)
from maskfactory.training.runtime import load_training_stack_lock
from maskfactory.validation import validate_document


def test_real_repo_train_contract_is_coherent_with_lock() -> None:
    report = probe_docker_train_contract()
    assert report.ready, report.issues
    assert set(report.dockerfile_checks) == set(DOCKERFILE_CHECKS)
    assert all(report.dockerfile_checks.values())
    assert set(report.compose_checks) == set(COMPOSE_CHECKS)
    assert all(report.compose_checks.values())


def test_static_suite_seals_schema_valid_report_with_honest_non_claims() -> None:
    report = run_docker_train_contract_suite()
    assert validate_document(report, ARTIFACT_TYPE) == ()
    assert report["proof_tier"] == PROOF_TIER
    assert report["authority"] == AUTHORITY
    assert report["artifact_type"] == ARTIFACT_TYPE
    assert report["build_attempted"] is False
    assert report["image_built_claimed"] is False
    assert report["mmcv_ext_sm120_compiled_claimed"] is False
    assert report["training_doctor_green_claimed"] is False
    assert report["champion_claimed"] is False
    assert report["certified_training_corpus_claimed"] is False
    assert report["gold_claimed"] is False
    assert report["report_id"].startswith("dtc_")
    assert len(report["seal_sha256"]) == 64


def test_schema_rejects_build_or_doctor_overclaim() -> None:
    report = run_docker_train_contract_suite()
    report["build_attempted"] = True
    assert validate_document(report, ARTIFACT_TYPE)
    report = run_docker_train_contract_suite()
    report["training_doctor_green_claimed"] = True
    assert validate_document(report, ARTIFACT_TYPE)
    report = run_docker_train_contract_suite()
    report["champion_claimed"] = True
    assert validate_document(report, ARTIFACT_TYPE)


def test_dockerfile_evaluator_detects_runtime_base_without_nvcc() -> None:
    lock = load_training_stack_lock()
    text = DEFAULT_DOCKERFILE_PATH.read_text(encoding="utf-8")
    # A runtime base image cannot compile mmcv._ext from source (no nvcc).
    broken = text.replace(
        "nvidia/cuda:12.8.0-devel-ubuntu22.04", "nvidia/cuda:12.8.0-runtime-ubuntu22.04"
    )
    checks = evaluate_dockerfile_contract(broken, lock)
    assert checks["base_devel_image_provides_nvcc"] is False


def test_dockerfile_evaluator_detects_torch_pin_drift() -> None:
    lock = load_training_stack_lock()
    text = DEFAULT_DOCKERFILE_PATH.read_text(encoding="utf-8")
    drifted = text.replace("torch==2.11.0+cu128", "torch==2.10.0+cu128")
    checks = evaluate_dockerfile_contract(drifted, lock)
    assert checks["torch_pin_matches_lock"] is False


def test_dockerfile_evaluator_detects_mmcv_commit_drift() -> None:
    lock = load_training_stack_lock()
    commit = lock["packages"]["mmcv"]["source_commit"]
    text = DEFAULT_DOCKERFILE_PATH.read_text(encoding="utf-8")
    drifted = text.replace(commit, "0" * 40)
    checks = evaluate_dockerfile_contract(drifted, lock)
    assert checks["mmcv_cloned_and_checked_out_locked_commit"] is False


def test_dockerfile_evaluator_detects_arch_list_drift() -> None:
    lock = load_training_stack_lock()
    text = DEFAULT_DOCKERFILE_PATH.read_text(encoding="utf-8")
    drifted = text.replace("TORCH_CUDA_ARCH_LIST=12.0", "TORCH_CUDA_ARCH_LIST=8.9")
    checks = evaluate_dockerfile_contract(drifted, lock)
    assert checks["mmcv_arch_list_matches_compute_capability"] is False


def test_compose_evaluator_detects_missing_shm_and_pull_policy() -> None:
    document = yaml.safe_load(DEFAULT_COMPOSE_PATH.read_text(encoding="utf-8"))
    service = document["services"]["maskfactory-train"]
    service.pop("shm_size", None)
    service.pop("pull_policy", None)
    checks = evaluate_compose_contract(document)
    assert checks["shm_size_sufficient"] is False
    assert checks["pull_policy_never"] is False


def test_compose_evaluator_detects_tiny_shm() -> None:
    document = yaml.safe_load(DEFAULT_COMPOSE_PATH.read_text(encoding="utf-8"))
    document["services"]["maskfactory-train"]["shm_size"] = "64m"
    checks = evaluate_compose_contract(document)
    assert checks["shm_size_sufficient"] is False


def test_compose_evaluator_flags_lan_exposed_port() -> None:
    document = yaml.safe_load(DEFAULT_COMPOSE_PATH.read_text(encoding="utf-8"))
    document["services"]["maskfactory-train"]["ports"] = ["6006:6006"]
    checks = evaluate_compose_contract(document)
    assert checks["no_lan_exposed_ports"] is False
    document["services"]["maskfactory-train"]["ports"] = ["127.0.0.1:6006:6006"]
    checks = evaluate_compose_contract(document)
    assert checks["no_lan_exposed_ports"] is True


def test_compose_evaluator_detects_absent_service() -> None:
    checks = evaluate_compose_contract({"services": {}})
    assert checks["train_service_present"] is False


def test_suite_raises_on_incoherent_dockerfile(tmp_path: Path) -> None:
    text = DEFAULT_DOCKERFILE_PATH.read_text(encoding="utf-8")
    broken = tmp_path / "Dockerfile.train"
    broken.write_text(text.replace("torch==2.11.0+cu128", "torch==1.0.0"), encoding="utf-8")
    with pytest.raises(DockerTrainContractError, match="docker_train_contract_failed"):
        run_docker_train_contract_suite(dockerfile_path=broken)


def test_cli_verify_docker_train_contract(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    result = CliRunner().invoke(main, ["verify-docker-train-contract", "--output", str(out)])
    assert result.exit_code == 0, result.output
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["build_attempted"] is False
    assert report["training_doctor_green_claimed"] is False
