from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from maskfactory.serve.docker_contract import (
    ARTIFACT_TYPE,
    AUTHORITY,
    COMPOSE_CHECKS,
    DEFAULT_COMPOSE_PATH,
    DEFAULT_DOCKERFILE_PATH,
    DEFAULT_LOCK_PATH,
    DEFAULT_REQUIREMENTS_PATH,
    DOCKERFILE_CHECKS,
    PROOF_TIER,
    REQUIREMENTS_CHECKS,
    DockerServeContractError,
    evaluate_compose_contract,
    evaluate_dockerfile_contract,
    evaluate_requirements_contract,
    parse_requirements_pins,
    probe_docker_serve_contract,
    run_docker_serve_contract_suite,
    validate_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _lock_pins() -> dict[str, str]:
    return parse_requirements_pins(DEFAULT_LOCK_PATH.read_text(encoding="utf-8"))


def test_real_repo_serve_contract_is_coherent_with_lock() -> None:
    report = probe_docker_serve_contract()
    assert report.ready, report.issues
    assert set(report.dockerfile_checks) == set(DOCKERFILE_CHECKS)
    assert all(report.dockerfile_checks.values())
    assert set(report.requirements_checks) == set(REQUIREMENTS_CHECKS)
    assert all(report.requirements_checks.values())
    assert set(report.compose_checks) == set(COMPOSE_CHECKS)
    assert all(report.compose_checks.values())


def test_static_suite_seals_schema_valid_report_with_honest_non_claims() -> None:
    report = run_docker_serve_contract_suite()
    assert validate_report(report) == ()
    assert report["proof_tier"] == PROOF_TIER
    assert report["authority"] == AUTHORITY
    assert report["artifact_type"] == ARTIFACT_TYPE
    assert report["build_attempted"] is False
    assert report["image_built_claimed"] is False
    assert report["torch_cuda_in_container_claimed"] is False
    assert report["serve_health_green_claimed"] is False
    assert report["champion_claimed"] is False
    assert report["predict_refine_backed_claimed"] is False
    assert report["gold_claimed"] is False
    assert report["report_id"].startswith("dsc_")
    assert len(report["seal_sha256"]) == 64


def test_schema_rejects_build_or_health_overclaim() -> None:
    report = run_docker_serve_contract_suite()
    report["build_attempted"] = True
    assert validate_report(report)
    report = run_docker_serve_contract_suite()
    report["serve_health_green_claimed"] = True
    assert validate_report(report)
    report = run_docker_serve_contract_suite()
    report["champion_claimed"] = True
    assert validate_report(report)


def test_dockerfile_evaluator_detects_cuda_devel_base_bloat() -> None:
    text = DEFAULT_DOCKERFILE_PATH.read_text(encoding="utf-8")
    # Serve must stay on a slim base; a CUDA devel base is bloat (torch cu128
    # already bundles the CUDA runtime).
    broken = text.replace(
        "FROM python:3.11-slim AS serve",
        "FROM nvidia/cuda:12.8.0-devel-ubuntu22.04 AS serve",
    )
    checks = evaluate_dockerfile_contract(broken, _lock_pins())
    assert checks["base_is_slim_python_not_cuda_devel"] is False


def test_dockerfile_evaluator_detects_torch_pin_drift() -> None:
    text = DEFAULT_DOCKERFILE_PATH.read_text(encoding="utf-8")
    drifted = text.replace("torch==2.11.0+cu128", "torch==2.10.0+cu128")
    checks = evaluate_dockerfile_contract(drifted, _lock_pins())
    assert checks["torch_pin_matches_lock"] is False


def test_dockerfile_evaluator_detects_deps_pulled_install() -> None:
    text = DEFAULT_DOCKERFILE_PATH.read_text(encoding="utf-8")
    # Dropping --no-deps would let pyproject's loose extras leak into serve.
    drifted = text.replace("pip install --no-deps -e .", "pip install -e .")
    checks = evaluate_dockerfile_contract(drifted, _lock_pins())
    assert checks["maskfactory_package_installed_no_deps"] is False


def test_requirements_evaluator_detects_pin_drift() -> None:
    text = DEFAULT_REQUIREMENTS_PATH.read_text(encoding="utf-8")
    drifted = text.replace("fastapi==0.139.0", "fastapi==0.100.0")
    checks = evaluate_requirements_contract(drifted, _lock_pins())
    assert checks["no_pin_contradicts_lock"] is False


def test_requirements_evaluator_detects_host_only_dep() -> None:
    text = DEFAULT_REQUIREMENTS_PATH.read_text(encoding="utf-8")
    poisoned = text + "\n-e git+https://example.com/sam2.git#egg=sam2\n"
    checks = evaluate_requirements_contract(poisoned, _lock_pins())
    assert checks["no_wsl_only_editable_git_or_file_deps"] is False


def test_compose_evaluator_flags_lan_exposed_port() -> None:
    document = yaml.safe_load(DEFAULT_COMPOSE_PATH.read_text(encoding="utf-8"))
    document["services"]["maskfactory-serve"]["ports"] = ["8765:8765"]
    checks = evaluate_compose_contract(document)
    assert checks["no_lan_exposed_ports"] is False
    document["services"]["maskfactory-serve"]["ports"] = ["127.0.0.1:8765:8765"]
    checks = evaluate_compose_contract(document)
    assert checks["no_lan_exposed_ports"] is True


def test_compose_evaluator_detects_absent_service() -> None:
    checks = evaluate_compose_contract({"services": {}})
    assert checks["serve_service_present"] is False


def test_suite_raises_on_incoherent_dockerfile(tmp_path: Path) -> None:
    text = DEFAULT_DOCKERFILE_PATH.read_text(encoding="utf-8")
    broken = tmp_path / "Dockerfile.serve"
    broken.write_text(text.replace("torch==2.11.0+cu128", "torch==1.0.0"), encoding="utf-8")
    with pytest.raises(DockerServeContractError, match="docker_serve_contract_failed"):
        run_docker_serve_contract_suite(dockerfile_path=broken)


def test_verify_docker_serve_contract_tool(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    result = subprocess.run(
        [sys.executable, "tools/verify_docker_serve_contract.py", "--output", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["build_attempted"] is False
    assert report["serve_health_green_claimed"] is False
