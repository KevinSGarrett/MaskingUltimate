"""Fail-closed runtime routing for evidence-qualified visual critics."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .critic_catalog import (
    MODEL_ROLES,
    CriticCatalogError,
    canonical_sha256,
    validate_catalog,
)


def resolve_role_route(
    catalog: Mapping[str, Any],
    role_id: str,
    *,
    available_hardware_tier: str = "runpod_single_gpu_48gb",
) -> dict[str, Any]:
    """Select one promoted feasible model or return a bounded abstention."""

    validate_catalog(catalog)
    if role_id not in MODEL_ROLES:
        raise CriticCatalogError(f"unknown or non-model visual critic role: {role_id}")
    if available_hardware_tier != catalog["current_hardware"]["tier_id"]:
        return {
            "status": "abstain",
            "reason": "hardware_tier_not_qualified",
            "role_id": role_id,
            "catalog_sha256": catalog["sha256"],
        }

    matches = []
    for model in catalog["models"]:
        calibration = model["calibration"]
        if (
            role_id in model["assigned_roles"]
            and model["lifecycle"] == "promoted"
            and model["hardware"]["single_gpu_48gb_feasible"]
            and calibration is not None
            and calibration["status"] == "pass"
            and model["private_endpoint"] is not None
        ):
            matches.append(model)
    if len(matches) != 1:
        return {
            "status": "abstain",
            "reason": "no_unique_promoted_feasible_model",
            "role_id": role_id,
            "catalog_sha256": catalog["sha256"],
        }
    model = matches[0]
    return {
        "status": "selected",
        "role_id": role_id,
        "model_id": model["model_id"],
        "repository": model["repository"],
        "revision": model["revision"],
        "artifact_sha256": model["artifact_sha256"],
        "calibration_report_sha256": model["calibration"]["report_sha256"],
        "private_endpoint": model["private_endpoint"],
        "catalog_sha256": catalog["sha256"],
        "selection_sha256": canonical_sha256(
            {
                "role_id": role_id,
                "model_id": model["model_id"],
                "revision": model["revision"],
                "artifact_sha256": model["artifact_sha256"],
                "calibration_report_sha256": model["calibration"]["report_sha256"],
                "catalog_sha256": catalog["sha256"],
            }
        ),
    }
