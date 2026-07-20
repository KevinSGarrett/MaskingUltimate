"""STATIC_PASS binder for the governed Docker train-image contract.

Parses ``docker/Dockerfile.train`` and the ``maskfactory-train`` service in
``docker/compose.gpu.yml`` and proves they are *coherent* with the immutable
OpenMMLab runtime selection in ``env/openmmlab_training_stack.lock.json`` --
without building anything, without a GPU, and without importing torch/MMCV.

This is a spec-coherence gate ONLY. It NEVER claims that the train image builds,
that ``mmcv._ext`` compiled for sm_120, that ``training-doctor`` is green inside
a container, that a champion exists, or that any certified training corpus is
non-empty. Those remain live, unproven, and honestly non-claimed here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..validation import validate_document
from .runtime import DEFAULT_LOCK_PATH, load_training_stack_lock

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DOCKERFILE_PATH = REPO_ROOT / "docker" / "Dockerfile.train"
DEFAULT_COMPOSE_PATH = REPO_ROOT / "docker" / "compose.gpu.yml"

TRAIN_SERVICE = "maskfactory-train"
TRAIN_IMAGE_TAG = "maskfactory/train:cu128"
TRAIN_DOCKERFILE_REL = "docker/Dockerfile.train"
REPO_BIND_TARGET = "/opt/maskfactory"
CONTAINER_RUNTIME = "train_cu128"
MIN_SHM_BYTES = 1 * 1024**3  # 1 GiB floor for PyTorch DataLoader workers.

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "docker_train_contract_report"
AUTHORITY = "docker_train_image_spec_coherence_only_no_build_no_doctor_green_no_champion"
SCHEMA_VERSION = "1.0.0"

DOCKERFILE_CHECKS = (
    "base_devel_image_provides_nvcc",
    "base_cuda_matches_lock",
    "torch_pin_matches_lock",
    "torch_cu128_index_used",
    "torch_build_assertion_present",
    "mmcv_cloned_and_checked_out_locked_commit",
    "mmcv_ops_build_env_forced",
    "mmcv_arch_list_matches_compute_capability",
    "mmcv_version_and_ext_asserted",
    "mmengine_pin_matches_lock",
    "mmsegmentation_pin_matches_lock",
    "mmdet_pin_matches_lock",
    "maskfactory_package_installed",
    "training_doctor_default_cmd",
    "container_runtime_env_declared",
)

COMPOSE_CHECKS = (
    "train_service_present",
    "image_tag_matches",
    "build_dockerfile_matches",
    "gpus_all_requested",
    "repo_bind_mount_present",
    "shm_size_sufficient",
    "pull_policy_never",
    "no_lan_exposed_ports",
    "training_doctor_command",
    "container_runtime_env_declared",
)


class DockerTrainContractError(ValueError):
    """The Docker train-image spec is incoherent with the runtime lock."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class DockerTrainContractReport:
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


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _parse_shm_bytes(value: Any) -> int | None:
    """Parse a compose ``shm_size`` (int bytes or a string like ``8gb``/``512m``)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmgt]?)b?\s*", value.strip().lower())
    if not match:
        return None
    scale = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}[match.group(2)]
    return int(float(match.group(1)) * scale)


def evaluate_dockerfile_contract(text: str, lock: Mapping[str, Any]) -> dict[str, bool]:
    """Evaluate the raw Dockerfile.train text against the lock (no build)."""
    runtime = lock["runtime"]
    packages = lock["packages"]
    torch_pin = runtime["torch"]
    cuda_series = str(runtime["cuda"])
    capability = tuple(runtime["compute_capability"])
    arch = f"{capability[0]}.{capability[1]}"
    mmcv_commit = packages["mmcv"]["source_commit"]
    mmcv_version = packages["mmcv"]["version"]

    condensed = text.replace(" ", "")
    base_match = re.search(r"FROM\s+nvidia/cuda:([0-9.]+)-(\w+)-", text)
    base_variant = base_match.group(2) if base_match else ""
    base_cuda = base_match.group(1) if base_match else ""

    return {
        # devel images ship nvcc; runtime/base images do not, so a from-source
        # mmcv._ext build is impossible without a devel base.
        "base_devel_image_provides_nvcc": base_variant == "devel",
        "base_cuda_matches_lock": base_cuda.startswith(cuda_series),
        "torch_pin_matches_lock": f"torch=={torch_pin}" in condensed,
        "torch_cu128_index_used": "https://download.pytorch.org/whl/cu128" in text,
        "torch_build_assertion_present": (
            f"torch.__version__=='{torch_pin}'" in condensed
            or f'torch.__version__=="{torch_pin}"' in condensed
        ),
        "mmcv_cloned_and_checked_out_locked_commit": (
            "github.com/open-mmlab/mmcv" in text and mmcv_commit in text
        ),
        "mmcv_ops_build_env_forced": "MMCV_WITH_OPS=1" in text and "FORCE_CUDA=1" in text,
        "mmcv_arch_list_matches_compute_capability": f"TORCH_CUDA_ARCH_LIST={arch}" in text,
        "mmcv_version_and_ext_asserted": (
            "version('mmcv')" in condensed
            and (f"=='{mmcv_version}'" in condensed or f'=="{mmcv_version}"' in condensed)
            and "importmmcv._ext" in condensed
        ),
        "mmengine_pin_matches_lock": f"mmengine=={packages['mmengine']['version']}" in text,
        "mmsegmentation_pin_matches_lock": (
            f"mmsegmentation=={packages['mmsegmentation']['version']}" in text
        ),
        "mmdet_pin_matches_lock": f"mmdet=={packages['mmdet']['version']}" in text,
        "maskfactory_package_installed": "-e ." in text and "COPY src" in text,
        "training_doctor_default_cmd": bool(
            re.search(r'CMD\s*\[.*"maskfactory".*"training-doctor".*\]', text)
        ),
        "container_runtime_env_declared": (
            f"MASKFACTORY_CONTAINER_RUNTIME={CONTAINER_RUNTIME}" in text
        ),
    }


def evaluate_compose_contract(document: Mapping[str, Any]) -> dict[str, bool]:
    """Evaluate the maskfactory-train compose service (no engine required)."""
    services = document.get("services")
    service = services.get(TRAIN_SERVICE) if isinstance(services, Mapping) else None
    present = isinstance(service, Mapping)
    if not present:
        return {name: name == "train_service_present" and False for name in COMPOSE_CHECKS}

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
    for entry in ports or []:
        text = str(entry)
        # A published port is LAN-exposed unless explicitly bound to loopback.
        if ":" in text and not (text.startswith("127.0.0.1:") or text.startswith("::1:")):
            lan_exposed = True
    shm_bytes = _parse_shm_bytes(service.get("shm_size"))

    return {
        "train_service_present": True,
        "image_tag_matches": service.get("image") == TRAIN_IMAGE_TAG,
        "build_dockerfile_matches": build.get("dockerfile") == TRAIN_DOCKERFILE_REL,
        "gpus_all_requested": service.get("gpus") == "all",
        "repo_bind_mount_present": bind_ok,
        "shm_size_sufficient": shm_bytes is not None and shm_bytes >= MIN_SHM_BYTES,
        "pull_policy_never": service.get("pull_policy") == "never",
        "no_lan_exposed_ports": not lan_exposed,
        "training_doctor_command": "maskfactory" in command_text
        and "training-doctor" in command_text,
        "container_runtime_env_declared": runtime_env_ok,
    }


def evaluate_docker_train_contract(
    *,
    dockerfile_text: str,
    compose_document: Mapping[str, Any],
    lock: Mapping[str, Any],
) -> DockerTrainContractReport:
    """Evaluate both artifacts and collect fail-closed issues."""
    dockerfile_checks = evaluate_dockerfile_contract(dockerfile_text, lock)
    compose_checks = evaluate_compose_contract(compose_document)
    issues: list[str] = []
    for name in DOCKERFILE_CHECKS:
        if not dockerfile_checks.get(name):
            issues.append(f"dockerfile:{name}")
    for name in COMPOSE_CHECKS:
        if not compose_checks.get(name):
            issues.append(f"compose:{name}")
    return DockerTrainContractReport(
        dockerfile_checks=dockerfile_checks,
        compose_checks=compose_checks,
        issues=tuple(issues),
    )


def probe_docker_train_contract(
    *,
    dockerfile_path: Path = DEFAULT_DOCKERFILE_PATH,
    compose_path: Path = DEFAULT_COMPOSE_PATH,
    lock_path: Path = DEFAULT_LOCK_PATH,
) -> DockerTrainContractReport:
    """Load the real repo artifacts and evaluate the train-image contract."""
    lock = load_training_stack_lock(lock_path)
    dockerfile_text = Path(dockerfile_path).read_text(encoding="utf-8")
    try:
        compose_document = yaml.safe_load(Path(compose_path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DockerTrainContractError(f"compose.gpu.yml is not valid YAML: {exc}") from exc
    if not isinstance(compose_document, Mapping):
        raise DockerTrainContractError("compose.gpu.yml did not parse to a mapping")
    return evaluate_docker_train_contract(
        dockerfile_text=dockerfile_text,
        compose_document=compose_document,
        lock=lock,
    )


def run_docker_train_contract_suite(
    *,
    dockerfile_path: Path = DEFAULT_DOCKERFILE_PATH,
    compose_path: Path = DEFAULT_COMPOSE_PATH,
    lock_path: Path = DEFAULT_LOCK_PATH,
) -> dict[str, Any]:
    """Execute the STATIC train-image contract binder and seal a schema-valid report."""
    report = probe_docker_train_contract(
        dockerfile_path=dockerfile_path,
        compose_path=compose_path,
        lock_path=lock_path,
    )
    if not report.ready:
        raise DockerTrainContractError("docker_train_contract_failed: " + "; ".join(report.issues))

    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "lock_ref": "env/openmmlab_training_stack.lock.json",
        "dockerfile_ref": TRAIN_DOCKERFILE_REL,
        "compose_ref": "docker/compose.gpu.yml",
        "compose_service": TRAIN_SERVICE,
        "image_tag": TRAIN_IMAGE_TAG,
        "dockerfile_checks": dict(sorted(report.dockerfile_checks.items())),
        "compose_checks": dict(sorted(report.compose_checks.items())),
        "checks": {
            "dockerfile_spec_coherence": "pass",
            "compose_service_coherence": "pass",
        },
        "build_attempted": False,
        "image_built_claimed": False,
        "mmcv_ext_sm120_compiled_claimed": False,
        "training_doctor_green_claimed": False,
        "champion_claimed": False,
        "certified_training_corpus_claimed": False,
        "gold_claimed": False,
        "honest_non_claims": [
            "train_image_build_success",
            "mmcv_ext_compiled_for_sm_120",
            "training_doctor_all_green_in_container",
            "champion_bodypart_hand_or_clothing",
            "certified_training_package_count_nonzero",
            "live_training_run",
            "gold",
        ],
    }
    digest = _sha(draft)
    draft["report_id"] = f"dtc_{digest[:24]}"
    draft["seal_sha256"] = digest
    draft["sha256"] = _sha({key: value for key, value in draft.items() if key != "sha256"})
    issues = validate_document(draft, ARTIFACT_TYPE)
    if issues:
        detail = "; ".join(f"{issue.pointer or '/'}: {issue.message}" for issue in issues)
        raise DockerTrainContractError(f"report_schema_invalid: {detail}")
    return draft


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "COMPOSE_CHECKS",
    "DOCKERFILE_CHECKS",
    "PROOF_TIER",
    "SCHEMA_VERSION",
    "DockerTrainContractError",
    "DockerTrainContractReport",
    "evaluate_compose_contract",
    "evaluate_docker_train_contract",
    "evaluate_dockerfile_contract",
    "probe_docker_train_contract",
    "run_docker_train_contract_suite",
]
