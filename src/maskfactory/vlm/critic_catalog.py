"""Versioned, fail-closed catalog for self-hosted visual-critic roles."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from ..validation import ArtifactValidationError, require_valid_document

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CATALOG_PATH = ROOT / "configs" / "visual_critic_catalog.yaml"
ROLE_IDS = (
    "fast_screener",
    "primary_visual_critic",
    "independent_juror",
    "senior_arbiter",
    "deterministic_authority",
)
MODEL_ROLES = frozenset(ROLE_IDS[:-1])
LIFECYCLE_ORDER = {
    "planned": 0,
    "downloaded": 1,
    "smoked": 2,
    "calibrated": 3,
    "promoted": 4,
    "unavailable": -1,
}


class CriticCatalogError(ValueError):
    """The visual-critic catalog or a requested role selection is invalid."""


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _schema(document: Mapping[str, Any]) -> None:
    try:
        require_valid_document(document, "visual_critic_catalog")
    except ArtifactValidationError as exc:
        raise CriticCatalogError(str(exc)) from exc


def _roles_by_id(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = document["roles"]
    roles = {str(row["role_id"]): row for row in rows}
    if len(roles) != len(rows) or tuple(roles) != ROLE_IDS:
        raise CriticCatalogError("visual critic roles are missing, duplicated, or reordered")
    return roles


def _models_by_id(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = document["models"]
    models = {str(row["model_id"]): row for row in rows}
    if len(models) != len(rows):
        raise CriticCatalogError("visual critic model IDs must be unique")
    return models


def validate_catalog(document: Mapping[str, Any]) -> None:
    _schema(document)
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if document["sha256"] != canonical_sha256(payload):
        raise CriticCatalogError("visual critic catalog canonical hash mismatch")

    roles = _roles_by_id(document)
    for role_id, role in roles.items():
        is_model_role = role_id in MODEL_ROLES
        if role["model_assignable"] is not is_model_role:
            raise CriticCatalogError(f"{role_id} model assignment policy is invalid")
        if role["requires_positive_and_negative_calibration"] is not is_model_role:
            raise CriticCatalogError(f"{role_id} calibration policy is invalid")

    gpu_bytes = int(document["current_hardware"]["vram_bytes_per_gpu"])
    models = _models_by_id(document)
    for model_id, model in models.items():
        candidate_roles = set(model["candidate_roles"])
        assigned_roles = set(model["assigned_roles"])
        if not candidate_roles <= MODEL_ROLES or not assigned_roles <= candidate_roles:
            raise CriticCatalogError(f"{model_id} role vocabulary or assignment is invalid")
        minimum_gpu_count = math.ceil(int(model["weight_bytes"]) / gpu_bytes)
        if model["hardware"]["minimum_gpu_count_by_weight_bytes"] != minimum_gpu_count:
            raise CriticCatalogError(f"{model_id} weight-only GPU lower bound is wrong")
        feasible = model["hardware"]["single_gpu_48gb_feasible"]
        tier = model["hardware"]["tier"]
        if feasible != (minimum_gpu_count == 1) or (tier == "single_gpu_candidate") != feasible:
            raise CriticCatalogError(f"{model_id} hardware tier contradicts exact artifact bytes")

        lifecycle = model["lifecycle"]
        artifact_sha256 = model["artifact_sha256"]
        calibration = model["calibration"]
        endpoint = model["private_endpoint"]
        if lifecycle in {"downloaded", "smoked", "calibrated", "promoted"} and not artifact_sha256:
            raise CriticCatalogError(f"{model_id} lifecycle requires an artifact hash")
        if lifecycle in {"calibrated", "promoted"} and (
            not calibration or calibration["status"] != "pass"
        ):
            raise CriticCatalogError(f"{model_id} lifecycle requires passing calibration")
        if lifecycle == "promoted" and (not assigned_roles or endpoint is None):
            raise CriticCatalogError(f"{model_id} promotion requires a role and private endpoint")
        if lifecycle != "promoted" and assigned_roles:
            raise CriticCatalogError(f"{model_id} has assigned authority before promotion")


def load_catalog(path: Path = DEFAULT_CATALOG_PATH) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise CriticCatalogError("visual critic catalog is not an object")
    validate_catalog(document)
    return document


def select_promoted_model(
    document: Mapping[str, Any],
    role_id: str,
    *,
    available_hardware_tier: str = "runpod_single_gpu_48gb",
) -> Mapping[str, Any]:
    """Return the uniquely promoted model for a role or fail closed."""

    validate_catalog(document)
    if role_id not in MODEL_ROLES:
        raise CriticCatalogError(f"unknown or non-model visual critic role: {role_id}")
    if available_hardware_tier != document["current_hardware"]["tier_id"]:
        raise CriticCatalogError("requested visual critic hardware tier is not cataloged")
    matches = [
        model
        for model in document["models"]
        if role_id in model["assigned_roles"]
        and model["lifecycle"] == "promoted"
        and model["hardware"]["single_gpu_48gb_feasible"]
        and model["calibration"]["status"] == "pass"
    ]
    if len(matches) != 1:
        raise CriticCatalogError(f"{role_id} has {len(matches)} promoted feasible models")
    return matches[0]


def independent_families(
    models: Sequence[Mapping[str, Any]],
) -> frozenset[str]:
    """Expose family identity without treating multiple variants as independent votes."""

    return frozenset(str(model["family_id"]) for model in models)
