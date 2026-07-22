"""Fail-closed static contract for the governed Mode-B Docker serve image."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DOCKERFILE_PATH = REPO_ROOT / "docker" / "Dockerfile.serve"
DEFAULT_COMPOSE_PATH = REPO_ROOT / "docker" / "compose.gpu.yml"

SERVE_SERVICE = "maskfactory-serve"
SERVE_IMAGE_TAG = "maskfactory/serve:cu128"
SERVE_DOCKERFILE_REL = "docker/Dockerfile.serve"
REPO_BIND_TARGET = "/opt/maskfactory"
CONTAINER_RUNTIME = "serve_cu128"
LOOPBACK_PORT = "127.0.0.1:8765:8765"

DOCKERFILE_CHECKS = (
    "python_311_slim_base",
    "torch_pin_and_cu128_index",
    "torchvision_pin",
    "serve_requirements_installed",
    "maskfactory_installed_without_dependency_reresolution",
    "container_runtime_env_declared",
    "serve_port_declared",
    "serve_default_command",
)

COMPOSE_CHECKS = (
    "serve_service_present",
    "image_tag_matches",
    "build_dockerfile_matches",
    "gpus_all_requested",
    "repo_bind_mount_present",
    "loopback_only_port",
    "serve_command",
    "container_runtime_env_declared",
)


class DockerServeContractError(ValueError):
    """The static serving-image contract cannot be parsed or is incoherent."""


@dataclass(frozen=True)
class DockerServeContractReport:
    dockerfile_checks: dict[str, bool]
    compose_checks: dict[str, bool]
    issues: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "dockerfile_checks": dict(sorted(self.dockerfile_checks.items())),
            "compose_checks": dict(sorted(self.compose_checks.items())),
            "issues": list(self.issues),
        }


def evaluate_dockerfile_contract(text: str) -> dict[str, bool]:
    """Evaluate Dockerfile.serve without building or importing GPU libraries."""

    condensed = re.sub(r"\s+", "", text)
    return {
        "python_311_slim_base": bool(
            re.search(r"^FROM\s+python:3\.11-slim(?:\s+AS\s+serve)?\s*$", text, re.MULTILINE)
        ),
        "torch_pin_and_cu128_index": (
            "https://download.pytorch.org/whl/cu128" in text and "torch==2.11.0+cu128" in condensed
        ),
        "torchvision_pin": "torchvision==0.26.0+cu128" in condensed,
        "serve_requirements_installed": (
            "COPYdocker/requirements-serve.txt/tmp/requirements-serve.txt" in condensed
            and "pipinstall-r/tmp/requirements-serve.txt" in condensed
        ),
        "maskfactory_installed_without_dependency_reresolution": (
            "COPYsrc/opt/maskfactory/src" in condensed and "pipinstall--no-deps-e." in condensed
        ),
        "container_runtime_env_declared": (
            f"MASKFACTORY_CONTAINER_RUNTIME={CONTAINER_RUNTIME}" in text
        ),
        "serve_port_declared": bool(re.search(r"^EXPOSE\s+8765\s*$", text, re.MULTILINE)),
        "serve_default_command": all(
            token in condensed
            for token in ('CMD["python","-m","maskfactory","serve","--port","8765"]',)
        ),
    }


def _runtime_environment_matches(value: Any) -> bool:
    if isinstance(value, Mapping):
        return str(value.get("MASKFACTORY_CONTAINER_RUNTIME")) == CONTAINER_RUNTIME
    if isinstance(value, list):
        return f"MASKFACTORY_CONTAINER_RUNTIME={CONTAINER_RUNTIME}" in value
    return False


def evaluate_compose_contract(document: Mapping[str, Any]) -> dict[str, bool]:
    """Evaluate the maskfactory-serve service without contacting Docker."""

    services = document.get("services")
    service = services.get(SERVE_SERVICE) if isinstance(services, Mapping) else None
    if not isinstance(service, Mapping):
        return {name: False for name in COMPOSE_CHECKS}
    build = service.get("build") if isinstance(service.get("build"), Mapping) else {}
    volumes = service.get("volumes") if isinstance(service.get("volumes"), list) else []
    bind_ok = any(
        isinstance(entry, str) and entry.split(":")[-1].rstrip("/") == REPO_BIND_TARGET
        for entry in volumes
    )
    ports = service.get("ports") if isinstance(service.get("ports"), list) else []
    command = json.dumps(service.get("command", []), separators=(",", ":"))
    return {
        "serve_service_present": True,
        "image_tag_matches": service.get("image") == SERVE_IMAGE_TAG,
        "build_dockerfile_matches": build.get("dockerfile") == SERVE_DOCKERFILE_REL,
        "gpus_all_requested": service.get("gpus") == "all",
        "repo_bind_mount_present": bind_ok,
        "loopback_only_port": ports == [LOOPBACK_PORT],
        "serve_command": all(
            token in command for token in ("python", "maskfactory", "serve", "--port", "8765")
        ),
        "container_runtime_env_declared": _runtime_environment_matches(service.get("environment")),
    }


def evaluate_docker_serve_contract(
    *, dockerfile_text: str, compose_document: Mapping[str, Any]
) -> DockerServeContractReport:
    """Collect every static Dockerfile and compose issue."""

    dockerfile_checks = evaluate_dockerfile_contract(dockerfile_text)
    compose_checks = evaluate_compose_contract(compose_document)
    issues = tuple(
        [f"dockerfile:{name}" for name in DOCKERFILE_CHECKS if not dockerfile_checks.get(name)]
        + [f"compose:{name}" for name in COMPOSE_CHECKS if not compose_checks.get(name)]
    )
    return DockerServeContractReport(dockerfile_checks, compose_checks, issues)


def probe_docker_serve_contract(
    *,
    dockerfile_path: Path = DEFAULT_DOCKERFILE_PATH,
    compose_path: Path = DEFAULT_COMPOSE_PATH,
) -> DockerServeContractReport:
    """Load and evaluate the repository's serving container artifacts."""

    try:
        dockerfile_text = Path(dockerfile_path).read_text(encoding="utf-8")
        compose_document = yaml.safe_load(Path(compose_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise DockerServeContractError(f"docker serve contract input is unreadable: {exc}") from exc
    if not isinstance(compose_document, Mapping):
        raise DockerServeContractError("compose.gpu.yml did not parse to a mapping")
    return evaluate_docker_serve_contract(
        dockerfile_text=dockerfile_text,
        compose_document=compose_document,
    )


__all__ = [
    "COMPOSE_CHECKS",
    "DEFAULT_COMPOSE_PATH",
    "DEFAULT_DOCKERFILE_PATH",
    "DOCKERFILE_CHECKS",
    "DockerServeContractError",
    "DockerServeContractReport",
    "evaluate_compose_contract",
    "evaluate_docker_serve_contract",
    "evaluate_dockerfile_contract",
    "probe_docker_serve_contract",
]
