"""Fail-closed runtime routing for evidence-qualified visual critics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from .critic_authority import validate_role_certificate
from .critic_catalog import (
    MODEL_ROLES,
    CriticCatalogError,
    canonical_sha256,
    validate_catalog,
)
from .target_contract import validate_target_contract

ARBITRATION_KEYS = frozenset(
    {
        "schema_version",
        "target_contract_sha256",
        "allowed_roi_xyxy",
        "primary_certificate_sha256",
        "juror_certificate_sha256",
        "primary_verdict",
        "juror_verdict",
        "disagreement_sha256",
    }
)
CRITIC_VERDICTS = frozenset({"pass", "defect", "abstain"})


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


def arbitration_disagreement_sha256(disagreement: Mapping[str, Any]) -> str:
    """Hash the bounded disagreement without its self-seal."""

    return canonical_sha256(
        {key: value for key, value in disagreement.items() if key != "disagreement_sha256"}
    )


def _roi_inside(inner: Sequence[Any], outer: Sequence[Any]) -> bool:
    if (
        len(inner) != 4
        or any(isinstance(value, bool) or not isinstance(value, int) for value in inner)
        or inner[0] < outer[0]
        or inner[1] < outer[1]
        or inner[2] > outer[2]
        or inner[3] > outer[3]
        or inner[2] <= inner[0]
        or inner[3] <= inner[1]
    ):
        return False
    return True


def resolve_bounded_arbiter_route(
    catalog: Mapping[str, Any],
    target_contract: Mapping[str, Any],
    disagreement: Mapping[str, Any],
    critic_certificates: Sequence[Mapping[str, Any]],
    arbiter_certificate: Mapping[str, Any] | None,
    *,
    now: datetime,
    deterministic_hard_veto: bool,
    available_hardware_tier: str = "runpod_single_gpu_48gb",
) -> dict[str, Any]:
    """Authorize one scope-bound arbiter invocation or abstain without widening authority."""

    validate_catalog(catalog)
    validate_target_contract(target_contract)
    if deterministic_hard_veto:
        return {
            "status": "blocked",
            "reason": "deterministic_hard_veto",
            "catalog_sha256": catalog["sha256"],
            "arbiter_invoked": False,
        }
    if set(disagreement) != ARBITRATION_KEYS or disagreement.get("schema_version") != "1.0.0":
        raise CriticCatalogError("arbiter disagreement fields or schema are invalid")
    if disagreement["disagreement_sha256"] != arbitration_disagreement_sha256(disagreement):
        raise CriticCatalogError("arbiter disagreement hash drifted")
    if disagreement["target_contract_sha256"] != target_contract["contract_sha256"]:
        raise CriticCatalogError("arbiter disagreement target contract drifted")
    roi = disagreement["allowed_roi_xyxy"]
    if (
        not isinstance(roi, Sequence)
        or isinstance(roi, (str, bytes))
        or not _roi_inside(roi, target_contract["target"]["allowed_roi_xyxy"])
    ):
        raise CriticCatalogError("arbiter disagreement widens the allowed target ROI")
    if (
        disagreement["primary_verdict"] not in CRITIC_VERDICTS
        or disagreement["juror_verdict"] not in CRITIC_VERDICTS
    ):
        raise CriticCatalogError("arbiter disagreement verdict is invalid")

    validated = [
        (certificate, validate_role_certificate(certificate, catalog, now=now))
        for certificate in critic_certificates
    ]
    by_role = {
        role: [entry for entry in validated if entry[0]["role_id"] == role]
        for role in ("primary_visual_critic", "independent_juror")
    }
    if any(len(rows) != 1 for rows in by_role.values()):
        return {
            "status": "abstain",
            "reason": "qualified_disagreement_evidence_unavailable",
            "catalog_sha256": catalog["sha256"],
            "arbiter_invoked": False,
        }
    primary_certificate, primary_model = by_role["primary_visual_critic"][0]
    juror_certificate, juror_model = by_role["independent_juror"][0]
    if (
        disagreement["primary_certificate_sha256"] != primary_certificate["certificate_sha256"]
        or disagreement["juror_certificate_sha256"] != juror_certificate["certificate_sha256"]
    ):
        raise CriticCatalogError("arbiter disagreement certificate binding drifted")
    if primary_model["family_id"] == juror_model["family_id"]:
        return {
            "status": "abstain",
            "reason": "critic_families_not_independent",
            "catalog_sha256": catalog["sha256"],
            "arbiter_invoked": False,
        }
    if disagreement["primary_verdict"] == disagreement["juror_verdict"]:
        return {
            "status": "abstain",
            "reason": "bounded_critic_disagreement_absent",
            "catalog_sha256": catalog["sha256"],
            "arbiter_invoked": False,
        }
    if arbiter_certificate is None:
        return {
            "status": "abstain",
            "reason": "qualified_arbiter_certificate_unavailable",
            "catalog_sha256": catalog["sha256"],
            "arbiter_invoked": False,
        }
    arbiter_model = validate_role_certificate(arbiter_certificate, catalog, now=now)
    if arbiter_certificate["role_id"] != "senior_arbiter":
        raise CriticCatalogError("arbiter certificate does not authorize senior arbitration")
    route = resolve_role_route(
        catalog,
        "senior_arbiter",
        available_hardware_tier=available_hardware_tier,
    )
    if route["status"] != "selected":
        return {
            **route,
            "reason": "qualified_arbiter_runtime_unavailable",
            "arbiter_invoked": False,
        }
    if route["model_id"] != arbiter_model["model_id"]:
        raise CriticCatalogError("arbiter route differs from certificate model")
    binding = {
        "catalog_sha256": catalog["sha256"],
        "target_contract_sha256": target_contract["contract_sha256"],
        "allowed_roi_xyxy": list(roi),
        "disagreement_sha256": disagreement["disagreement_sha256"],
        "arbiter_certificate_sha256": arbiter_certificate["certificate_sha256"],
        "selection_sha256": route["selection_sha256"],
    }
    return {
        "status": "selected",
        "reason": "bounded_qualified_disagreement",
        "arbiter_invoked": True,
        "role_id": "senior_arbiter",
        "model_id": route["model_id"],
        "private_endpoint": route["private_endpoint"],
        "allowed_roi_xyxy": list(roi),
        "target_contract_sha256": target_contract["contract_sha256"],
        "invocation_sha256": canonical_sha256(binding),
    }
