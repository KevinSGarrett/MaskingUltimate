"""Exact role-certificate and quorum authority for self-hosted visual critics."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from .critic_catalog import MODEL_ROLES, canonical_sha256, validate_catalog

SHA256 = re.compile(r"^[a-f0-9]{64}$")
CERTIFICATE_KEYS = frozenset(
    {
        "schema_version",
        "certificate_id",
        "role_id",
        "model_id",
        "family_id",
        "catalog_sha256",
        "revision",
        "artifact_sha256",
        "calibration_report_sha256",
        "prompt_sha256",
        "runtime_sha256",
        "issued_at",
        "qualified_until",
        "status",
        "certificate_sha256",
    }
)


class CriticAuthorityError(ValueError):
    """A critic role certificate or quorum request is invalid."""


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise CriticAuthorityError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise CriticAuthorityError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC)


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise CriticAuthorityError(f"{field} must be a SHA-256")
    return value


def certificate_sha256(certificate: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {key: value for key, value in certificate.items() if key != "certificate_sha256"}
    )


def validate_role_certificate(
    certificate: Mapping[str, Any],
    catalog: Mapping[str, Any],
    *,
    now: datetime,
) -> Mapping[str, Any]:
    """Bind one current certificate to one promoted catalog assignment."""

    validate_catalog(catalog)
    if set(certificate) != CERTIFICATE_KEYS:
        raise CriticAuthorityError("critic role certificate fields are incomplete or unknown")
    if certificate["schema_version"] != "1.0.0":
        raise CriticAuthorityError("critic role certificate schema is unsupported")
    role_id = str(certificate["role_id"])
    if role_id not in MODEL_ROLES:
        raise CriticAuthorityError("critic role certificate names an unknown role")
    if certificate["status"] != "pass":
        raise CriticAuthorityError("critic role certificate did not pass")
    if certificate["certificate_sha256"] != certificate_sha256(certificate):
        raise CriticAuthorityError("critic role certificate canonical hash mismatch")
    for field in (
        "catalog_sha256",
        "artifact_sha256",
        "calibration_report_sha256",
        "prompt_sha256",
        "runtime_sha256",
    ):
        _require_sha256(certificate[field], field)
    if certificate["catalog_sha256"] != catalog["sha256"]:
        raise CriticAuthorityError("critic role certificate catalog hash drifted")
    issued_at = _timestamp(certificate["issued_at"], "issued_at")
    qualified_until = _timestamp(certificate["qualified_until"], "qualified_until")
    current = now.astimezone(UTC)
    if issued_at > current or qualified_until <= current or qualified_until <= issued_at:
        raise CriticAuthorityError("critic role certificate is not currently qualified")

    models = {str(model["model_id"]): model for model in catalog["models"]}
    model_id = str(certificate["model_id"])
    model = models.get(model_id)
    if model is None:
        raise CriticAuthorityError("critic role certificate model is not cataloged")
    calibration = model["calibration"]
    if (
        model["lifecycle"] != "promoted"
        or role_id not in model["assigned_roles"]
        or model["family_id"] != certificate["family_id"]
        or model["revision"] != certificate["revision"]
        or model["artifact_sha256"] != certificate["artifact_sha256"]
        or calibration is None
        or calibration["status"] != "pass"
        or calibration["report_sha256"] != certificate["calibration_report_sha256"]
    ):
        raise CriticAuthorityError("critic role certificate differs from promoted catalog evidence")
    return model


def evaluate_pass_quorum(
    certificates: Sequence[Mapping[str, Any]],
    catalog: Mapping[str, Any],
    *,
    now: datetime,
    deterministic_hard_veto: bool,
) -> dict[str, Any]:
    """Require current primary and independent-family roles after deterministic QA."""

    validate_catalog(catalog)
    if deterministic_hard_veto:
        return {
            "status": "blocked",
            "reason": "deterministic_hard_veto",
            "catalog_sha256": catalog["sha256"],
        }
    validated: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for certificate in certificates:
        validated.append((certificate, validate_role_certificate(certificate, catalog, now=now)))
    by_role = {
        role: [entry for entry in validated if entry[0]["role_id"] == role]
        for role in ("primary_visual_critic", "independent_juror")
    }
    if any(len(rows) != 1 for rows in by_role.values()):
        return {
            "status": "abstain",
            "reason": "required_role_quorum_unavailable",
            "catalog_sha256": catalog["sha256"],
        }
    primary_family = by_role["primary_visual_critic"][0][1]["family_id"]
    independent_family = by_role["independent_juror"][0][1]["family_id"]
    if primary_family == independent_family:
        return {
            "status": "abstain",
            "reason": "critic_families_not_independent",
            "catalog_sha256": catalog["sha256"],
        }
    certificate_hashes = sorted(
        str(entry[0]["certificate_sha256"]) for rows in by_role.values() for entry in rows
    )
    return {
        "status": "eligible",
        "reason": "exact_current_independent_quorum",
        "catalog_sha256": catalog["sha256"],
        "certificate_sha256s": certificate_hashes,
        "quorum_sha256": canonical_sha256(
            {
                "catalog_sha256": catalog["sha256"],
                "certificate_sha256s": certificate_hashes,
                "deterministic_hard_veto": False,
            }
        ),
    }
