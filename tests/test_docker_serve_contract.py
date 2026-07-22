from __future__ import annotations

import yaml

from maskfactory.serve.docker_contract import (
    COMPOSE_CHECKS,
    DEFAULT_COMPOSE_PATH,
    DEFAULT_DOCKERFILE_PATH,
    DOCKERFILE_CHECKS,
    evaluate_compose_contract,
    evaluate_dockerfile_contract,
    probe_docker_serve_contract,
)


def test_real_repo_serve_contract_is_coherent() -> None:
    report = probe_docker_serve_contract()
    assert report.ready, report.issues
    assert set(report.dockerfile_checks) == set(DOCKERFILE_CHECKS)
    assert all(report.dockerfile_checks.values())
    assert set(report.compose_checks) == set(COMPOSE_CHECKS)
    assert all(report.compose_checks.values())


def test_dockerfile_contract_rejects_torch_and_runtime_drift() -> None:
    text = DEFAULT_DOCKERFILE_PATH.read_text(encoding="utf-8")
    checks = evaluate_dockerfile_contract(
        text.replace("torch==2.11.0+cu128", "torch==2.10.0+cu128").replace(
            "MASKFACTORY_CONTAINER_RUNTIME=serve_cu128",
            "MASKFACTORY_CONTAINER_RUNTIME=unknown",
        )
    )
    assert checks["torch_pin_and_cu128_index"] is False
    assert checks["container_runtime_env_declared"] is False


def test_compose_contract_rejects_lan_port_and_missing_gpu() -> None:
    document = yaml.safe_load(DEFAULT_COMPOSE_PATH.read_text(encoding="utf-8"))
    service = document["services"]["maskfactory-serve"]
    service["ports"] = ["8765:8765"]
    service.pop("gpus")
    checks = evaluate_compose_contract(document)
    assert checks["loopback_only_port"] is False
    assert checks["gpus_all_requested"] is False


def test_compose_contract_rejects_missing_service() -> None:
    checks = evaluate_compose_contract({"services": {}})
    assert set(checks) == set(COMPOSE_CHECKS)
    assert not any(checks.values())
