"""STATIC_PASS binder for the governed Docker serve-image contract.

Parses ``docker/Dockerfile.serve``, the curated ``docker/requirements-serve.txt``
subset, and the ``maskfactory-serve`` service in ``docker/compose.gpu.yml`` and
proves they are *coherent* with the authoritative pins in
``env/requirements.lock.txt`` -- without building anything, without a GPU, and
without importing torch or starting the FastAPI service.

This is a spec-coherence gate ONLY. It NEVER claims that the serve image builds,
that torch reports CUDA inside a container, that ``maskfactory serve`` answered
``/health`` / ``/models``, that a champion exists, or that Mode-B
``/predict`` / ``/refine`` are backed. Those remain live, unproven, and
honestly non-claimed here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator, FormatChecker

# Self-contained schema validation: load this artifact's bundled Draft 2020-12
# schema by path rather than through maskfactory.validation's global registry.
# This keeps the STATIC serve-contract binder functional as an additive,
# untracked-file feature even if a concurrent worker on the branch has not (yet)
# registered the schema name in validation.SCHEMA_NAMES.
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DOCKERFILE_PATH = REPO_ROOT / "docker" / "Dockerfile.serve"
DEFAULT_REQUIREMENTS_PATH = REPO_ROOT / "docker" / "requirements-serve.txt"
DEFAULT_COMPOSE_PATH = REPO_ROOT / "docker" / "compose.gpu.yml"
DEFAULT_LOCK_PATH = REPO_ROOT / "env" / "requirements.lock.txt"

SERVE_SERVICE = "maskfactory-serve"
SERVE_IMAGE_TAG = "maskfactory/serve:cu128"
SERVE_DOCKERFILE_REL = "docker/Dockerfile.serve"
REPO_BIND_TARGET = "/opt/maskfactory"
CONTAINER_RUNTIME = "serve_cu128"
SERVE_PORT = 8765
TORCH_CU128_INDEX = "https://download.pytorch.org/whl/cu128"

# Packages that MUST appear (at the locked version) in the curated serve subset.
FASTAPI_STACK = ("fastapi", "starlette", "uvicorn", "pydantic")
SERVE_CORE_RUNTIME = ("numpy", "pillow", "scipy", "scikit-image")

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "docker_serve_contract_report"
AUTHORITY = "docker_serve_image_spec_coherence_only_no_build_no_health_green_no_champion"
SCHEMA_VERSION = "1.0.0"

DOCKERFILE_CHECKS = (
    "base_is_slim_python_not_cuda_devel",
    "torch_pin_matches_lock",
    "torchvision_pin_matches_lock",
    "torch_cu128_index_used",
    "libgomp_runtime_dep_present",
    "requirements_serve_copied_and_installed",
    "maskfactory_package_installed_no_deps",
    "serve_default_cmd",
    "loopback_serve_port_exposed",
    "container_runtime_env_declared",
)

REQUIREMENTS_CHECKS = (
    "no_pin_contradicts_lock",
    "fastapi_uvicorn_stack_present",
    "serve_core_runtime_present",
    "no_wsl_only_editable_git_or_file_deps",
)

COMPOSE_CHECKS = (
    "serve_service_present",
    "image_tag_matches",
    "build_dockerfile_matches",
    "gpus_all_requested",
    "repo_bind_mount_present",
    "no_lan_exposed_ports",
    "serve_command",
    "container_runtime_env_declared",
)


class DockerServeContractError(ValueError):
    """The Docker serve-image spec is incoherent with the requirements lock."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class DockerServeContractReport:
    dockerfile_checks: dict[str, bool]
    requirements_checks: dict[str, bool]
    compose_checks: dict[str, bool]
    issues: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "dockerfile_checks": dict(sorted(self.dockerfile_checks.items())),
            "requirements_checks": dict(sorted(self.requirements_checks.items())),
            "compose_checks": dict(sorted(self.compose_checks.items())),
            "issues": list(self.issues),
        }


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _schema_validator() -> Draft202012Validator:
    schema_path = SCHEMA_DIR / f"{ARTIFACT_TYPE}.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_report(report: Mapping[str, Any]) -> tuple[str, ...]:
    """Return sorted schema error messages for a sealed serve-contract report."""
    errors = _schema_validator().iter_errors(report)
    return tuple(
        sorted(
            f"{'/'.join(str(part) for part in error.absolute_path) or '/'}: {error.message}"
            for error in errors
        )
    )


def parse_requirements_pins(text: str) -> dict[str, str]:
    """Return a ``{normalized_name: version}`` map from a ``name==version`` file.

    Comments, blank lines, and non-pinned/editable/URL lines are ignored here;
    the ``no_wsl_only_*`` requirements check separately proves the curated serve
    subset contains no such lines.
    """
    pins: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or "==" not in line:
            continue
        name, _, version = line.partition("==")
        name = name.strip().lower().replace("_", "-")
        version = version.strip()
        if name and version:
            pins[name] = version
    return pins


def evaluate_dockerfile_contract(text: str, lock_pins: Mapping[str, str]) -> dict[str, bool]:
    """Evaluate the raw Dockerfile.serve text against the lock (no build)."""
    condensed = text.replace(" ", "")
    torch_pin = lock_pins.get("torch", "")
    torchvision_pin = lock_pins.get("torchvision", "")

    from_matches = re.findall(r"(?im)^\s*FROM\s+([^\s]+)", text)
    uses_cuda_base = any("nvidia/cuda" in ref.lower() for ref in from_matches)
    uses_slim_python = any(
        re.match(r"python:[\w.]+-slim", ref.strip(), re.IGNORECASE) for ref in from_matches
    )

    return {
        # Serve intentionally uses a slim base: torch cu128 wheels bundle the
        # CUDA runtime, so only the host driver (via --gpus all) is needed. A
        # CUDA devel base would only bloat the serve image.
        "base_is_slim_python_not_cuda_devel": uses_slim_python and not uses_cuda_base,
        "torch_pin_matches_lock": bool(torch_pin) and f"torch=={torch_pin}" in condensed,
        "torchvision_pin_matches_lock": (
            bool(torchvision_pin) and f"torchvision=={torchvision_pin}" in condensed
        ),
        "torch_cu128_index_used": TORCH_CU128_INDEX in text,
        # libgomp1 provides OpenMP for numpy/scipy/scikit-image/torch.
        "libgomp_runtime_dep_present": "libgomp1" in text,
        "requirements_serve_copied_and_installed": (
            "requirements-serve.txt" in text and "pipinstall-r" in condensed
        ),
        # --no-deps keeps pyproject's loose extras (mediapipe/ultralytics/...)
        # from being pulled into the Mode-B serve runtime.
        "maskfactory_package_installed_no_deps": (
            "pipinstall--no-deps-e." in condensed and "COPY src" in text
        ),
        "serve_default_cmd": bool(re.search(r'CMD\s*\[.*"maskfactory".*"serve".*\]', text)),
        "loopback_serve_port_exposed": f"EXPOSE {SERVE_PORT}" in text,
        "container_runtime_env_declared": (
            f"MASKFACTORY_CONTAINER_RUNTIME={CONTAINER_RUNTIME}" in text
        ),
    }


def evaluate_requirements_contract(
    requirements_text: str, lock_pins: Mapping[str, str]
) -> dict[str, bool]:
    """Prove the curated serve subset does not drift from the lock and is host-clean.

    ``no_pin_contradicts_lock`` requires that every serve pin the authoritative
    lock also pins matches its locked version exactly. Transitive dependencies
    the lock does not pin at all (e.g. ``sniffio``) are permitted but must not
    contradict; this keeps the check honest rather than forcing edits to the
    generated lock.
    """
    serve_pins = parse_requirements_pins(requirements_text)
    contradictions = [
        name
        for name, version in serve_pins.items()
        if name in lock_pins and lock_pins[name] != version
    ]
    no_contradiction = bool(serve_pins) and not contradictions
    # Scan only real dependency lines; the header comment intentionally mentions
    # file:// / git+ to explain why they are excluded from the curated subset.
    dep_lines = [
        line.split("#", 1)[0].strip().lower()
        for line in requirements_text.splitlines()
        if line.split("#", 1)[0].strip()
    ]
    no_host_only = not any(
        any(token in line for token in ("-e ", "git+", "file://", "@ file", ".whl"))
        for line in dep_lines
    )
    return {
        "no_pin_contradicts_lock": no_contradiction,
        "fastapi_uvicorn_stack_present": all(pkg in serve_pins for pkg in FASTAPI_STACK),
        "serve_core_runtime_present": all(pkg in serve_pins for pkg in SERVE_CORE_RUNTIME),
        "no_wsl_only_editable_git_or_file_deps": no_host_only,
    }


def evaluate_compose_contract(document: Mapping[str, Any]) -> dict[str, bool]:
    """Evaluate the maskfactory-serve compose service (no engine required)."""
    services = document.get("services")
    service = services.get(SERVE_SERVICE) if isinstance(services, Mapping) else None
    present = isinstance(service, Mapping)
    if not present:
        return {name: name == "serve_service_present" and False for name in COMPOSE_CHECKS}

    build = service.get("build") if isinstance(service.get("build"), Mapping) else {}
    volumes = service.get("volumes") if isinstance(service.get("volumes"), list) else []
    bind_ok = any(
        isinstance(entry, str) and entry.split(":")[-1].rstrip("/") == REPO_BIND_TARGET
        for entry in volumes
    )
    command = service.get("command")
    command_text = json.dumps(command) if command is not None else ""
    environment = service.get("environment")
    if isinstance(environment, Mapping):
        runtime_env_ok = str(environment.get("MASKFACTORY_CONTAINER_RUNTIME")) == CONTAINER_RUNTIME
    elif isinstance(environment, list):
        runtime_env_ok = f"MASKFACTORY_CONTAINER_RUNTIME={CONTAINER_RUNTIME}" in environment
    else:
        runtime_env_ok = False
    ports = service.get("ports")
    lan_exposed = False
    loopback_serve_bound = False
    for entry in ports or []:
        text = str(entry)
        # A published port is LAN-exposed unless explicitly bound to loopback.
        if ":" in text and not (text.startswith("127.0.0.1:") or text.startswith("::1:")):
            lan_exposed = True
        if text.startswith("127.0.0.1:") and text.rstrip().endswith(f":{SERVE_PORT}"):
            loopback_serve_bound = True

    return {
        "serve_service_present": True,
        "image_tag_matches": service.get("image") == SERVE_IMAGE_TAG,
        "build_dockerfile_matches": build.get("dockerfile") == SERVE_DOCKERFILE_REL,
        "gpus_all_requested": service.get("gpus") == "all",
        "repo_bind_mount_present": bind_ok,
        "no_lan_exposed_ports": (not lan_exposed) and loopback_serve_bound,
        "serve_command": "maskfactory" in command_text and "serve" in command_text,
        "container_runtime_env_declared": runtime_env_ok,
    }


def evaluate_docker_serve_contract(
    *,
    dockerfile_text: str,
    requirements_text: str,
    compose_document: Mapping[str, Any],
    lock_pins: Mapping[str, str],
) -> DockerServeContractReport:
    """Evaluate all three artifacts and collect fail-closed issues."""
    dockerfile_checks = evaluate_dockerfile_contract(dockerfile_text, lock_pins)
    requirements_checks = evaluate_requirements_contract(requirements_text, lock_pins)
    compose_checks = evaluate_compose_contract(compose_document)
    issues: list[str] = []
    for name in DOCKERFILE_CHECKS:
        if not dockerfile_checks.get(name):
            issues.append(f"dockerfile:{name}")
    for name in REQUIREMENTS_CHECKS:
        if not requirements_checks.get(name):
            issues.append(f"requirements:{name}")
    for name in COMPOSE_CHECKS:
        if not compose_checks.get(name):
            issues.append(f"compose:{name}")
    return DockerServeContractReport(
        dockerfile_checks=dockerfile_checks,
        requirements_checks=requirements_checks,
        compose_checks=compose_checks,
        issues=tuple(issues),
    )


def probe_docker_serve_contract(
    *,
    dockerfile_path: Path = DEFAULT_DOCKERFILE_PATH,
    requirements_path: Path = DEFAULT_REQUIREMENTS_PATH,
    compose_path: Path = DEFAULT_COMPOSE_PATH,
    lock_path: Path = DEFAULT_LOCK_PATH,
) -> DockerServeContractReport:
    """Load the real repo artifacts and evaluate the serve-image contract."""
    lock_pins = parse_requirements_pins(Path(lock_path).read_text(encoding="utf-8"))
    dockerfile_text = Path(dockerfile_path).read_text(encoding="utf-8")
    requirements_text = Path(requirements_path).read_text(encoding="utf-8")
    try:
        compose_document = yaml.safe_load(Path(compose_path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DockerServeContractError(f"compose.gpu.yml is not valid YAML: {exc}") from exc
    if not isinstance(compose_document, Mapping):
        raise DockerServeContractError("compose.gpu.yml did not parse to a mapping")
    return evaluate_docker_serve_contract(
        dockerfile_text=dockerfile_text,
        requirements_text=requirements_text,
        compose_document=compose_document,
        lock_pins=lock_pins,
    )


def run_docker_serve_contract_suite(
    *,
    dockerfile_path: Path = DEFAULT_DOCKERFILE_PATH,
    requirements_path: Path = DEFAULT_REQUIREMENTS_PATH,
    compose_path: Path = DEFAULT_COMPOSE_PATH,
    lock_path: Path = DEFAULT_LOCK_PATH,
) -> dict[str, Any]:
    """Execute the STATIC serve-image contract binder and seal a schema-valid report."""
    report = probe_docker_serve_contract(
        dockerfile_path=dockerfile_path,
        requirements_path=requirements_path,
        compose_path=compose_path,
        lock_path=lock_path,
    )
    if not report.ready:
        raise DockerServeContractError("docker_serve_contract_failed: " + "; ".join(report.issues))

    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "lock_ref": "env/requirements.lock.txt",
        "dockerfile_ref": SERVE_DOCKERFILE_REL,
        "requirements_ref": "docker/requirements-serve.txt",
        "compose_ref": "docker/compose.gpu.yml",
        "compose_service": SERVE_SERVICE,
        "image_tag": SERVE_IMAGE_TAG,
        "dockerfile_checks": dict(sorted(report.dockerfile_checks.items())),
        "requirements_checks": dict(sorted(report.requirements_checks.items())),
        "compose_checks": dict(sorted(report.compose_checks.items())),
        "checks": {
            "dockerfile_spec_coherence": "pass",
            "requirements_subset_coherence": "pass",
            "compose_service_coherence": "pass",
        },
        "build_attempted": False,
        "image_built_claimed": False,
        "torch_cuda_in_container_claimed": False,
        "serve_health_green_claimed": False,
        "champion_claimed": False,
        "predict_refine_backed_claimed": False,
        "gold_claimed": False,
        "honest_non_claims": [
            "serve_image_build_success",
            "torch_cuda_available_in_container",
            "serve_health_models_answered_in_container",
            "champion_bodypart_hand_or_clothing",
            "mode_b_predict_or_refine_backed",
            "gold",
        ],
    }
    digest = _sha(draft)
    draft["report_id"] = f"dsc_{digest[:24]}"
    draft["seal_sha256"] = digest
    draft["sha256"] = _sha({key: value for key, value in draft.items() if key != "sha256"})
    issues = validate_report(draft)
    if issues:
        raise DockerServeContractError("report_schema_invalid: " + "; ".join(issues))
    return draft


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "COMPOSE_CHECKS",
    "DOCKERFILE_CHECKS",
    "PROOF_TIER",
    "REQUIREMENTS_CHECKS",
    "SCHEMA_VERSION",
    "DockerServeContractError",
    "DockerServeContractReport",
    "evaluate_compose_contract",
    "evaluate_docker_serve_contract",
    "evaluate_dockerfile_contract",
    "evaluate_requirements_contract",
    "parse_requirements_pins",
    "probe_docker_serve_contract",
    "run_docker_serve_contract_suite",
    "validate_report",
]
