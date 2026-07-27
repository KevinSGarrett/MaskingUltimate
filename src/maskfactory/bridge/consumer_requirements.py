"""Additive, at-use admission checks for signed Main consumer requirements.

This module deliberately consumes the frozen v1 requirements document rather
than extending it.  It is a MaskFactory-side conformance decision only; Main
remains responsible for publishing its signed requirements and adoption state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from jsonschema import Draft202012Validator

from maskfactory.validation import (
    ValidationIssue,
    canonical_document_sha256,
    validate_maskfactory_consumer_requirements,
)

_SCHEMA_PATH = (
    Path(__file__).parents[1]
    / "schemas"
    / "maskfactory_consumer_requirements_admission.schema.json"
)
_REQUIRED_EVIDENCE_KINDS = frozenset({"authority_certificate", "route_benchmark"})


def _issue(pointer: str, validator: str, message: str) -> ValidationIssue:
    return ValidationIssue(pointer=pointer, validator=validator, message=message)


def _at_time(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else None
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError:
        return None


def _schema_issues(admission: Mapping[str, Any]) -> list[ValidationIssue]:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return [
        _issue(
            "/" + "/".join(str(part) for part in error.absolute_path),
            "admission_schema",
            error.message,
        )
        for error in Draft202012Validator(schema).iter_errors(admission)
    ]


def _contains_all(offered: Any, required: Any) -> bool:
    return (
        isinstance(offered, Sequence)
        and not isinstance(offered, str)
        and isinstance(required, Sequence)
        and not isinstance(required, str)
        and set(required).issubset(set(offered))
    )


def _capability_outcome(
    requirement: Mapping[str, Any], offered: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Produce a deterministic capability outcome without treating near matches as valid."""
    capability_id = requirement.get("capability_id")
    unmet: list[str] = []
    if offered is None:
        unmet.append("capability_unavailable")
    else:
        checks = (
            ("access_mode", (offered.get("access_modes") or ()), [requirement.get("access_mode")]),
            ("labels", offered.get("labels"), requirement.get("labels") or ()),
            (
                "artifact_kinds",
                offered.get("artifact_kinds"),
                requirement.get("artifact_kinds") or (),
            ),
            (
                "authority_state",
                offered.get("authority_states"),
                [requirement.get("minimum_authority_state")],
            ),
        )
        for name, actual, expected in checks:
            if not _contains_all(actual, expected):
                unmet.append(name)
        evidence_kinds = {
            evidence.get("kind")
            for evidence in offered.get("evidence") or ()
            if isinstance(evidence, Mapping)
        }
        if not _REQUIRED_EVIDENCE_KINDS.issubset(evidence_kinds):
            unmet.append("evidence")
    return {
        "capability_id": capability_id,
        "status": "met" if not unmet else "unmet",
        "unmet_constraints": tuple(unmet),
    }


def _global_outcomes(
    requirements: Mapping[str, Any], offered: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Check cross-capability constraints that cannot be proven by one route."""

    def values(value: Any) -> set[Any]:
        return set(value) if isinstance(value, Sequence) and not isinstance(value, str) else set()

    def union(field: str) -> set[Any]:
        return {item for row in offered for item in values(row.get(field))}

    def version_union(field: str) -> set[Any]:
        return {
            item
            for row in offered
            if isinstance(row.get("versions"), Mapping)
            for item in values(row["versions"].get(field))
        }

    runtime_rows = [
        row.get("runtime") for row in offered if isinstance(row.get("runtime"), Mapping)
    ]
    runtime = requirements.get("runtime_requirements")
    runtime = runtime if isinstance(runtime, Mapping) else {}
    compatibility = requirements.get("compatibility")
    compatibility = compatibility if isinstance(compatibility, Mapping) else {}
    authority = requirements.get("authority_requirements")
    authority = authority if isinstance(authority, Mapping) else {}
    checks = {
        "access_modes": values(requirements.get("required_access_modes")).issubset(
            union("access_modes")
        ),
        "labels": values(requirements.get("required_labels")).issubset(union("labels")),
        "media_scopes": values(requirements.get("accepted_media_scopes")).issubset(
            union("media_scopes")
        ),
        "transforms": values(requirements.get("required_transform_operations")).issubset(
            union("transform_operations")
        ),
        "person_count": any(
            row.get("maximum_person_count", 0) >= requirements.get("minimum_person_count", 1)
            for row in offered
        ),
        "truth_tiers": values(authority.get("accepted_mode_a_truth_tiers")).issubset(
            union("truth_tiers")
        ),
        "certificate_kinds": values(authority.get("accepted_certificate_kinds")).issubset(
            union("certificate_kinds")
        ),
        "issuer_kinds": values(authority.get("accepted_issuer_kinds")).issubset(
            union("issuer_kinds")
        ),
        "versions": all(
            values(compatibility.get(field)).issubset(version_union(field))
            for field in (
                "api_contracts",
                "package_formats",
                "ontology_versions",
                "node_pack_versions",
            )
        ),
        "latency_resources": bool(runtime_rows)
        and any(
            row.get("maximum_p50_latency_ms", float("inf"))
            <= runtime.get("maximum_p50_latency_ms", -1)
            and row.get("maximum_p95_latency_ms", float("inf"))
            <= runtime.get("maximum_p95_latency_ms", -1)
            and row.get("maximum_ram_mb", float("inf")) <= runtime.get("maximum_ram_mb", -1)
            and row.get("maximum_output_bytes", float("inf"))
            <= runtime.get("maximum_output_bytes", -1)
            and row.get("minimum_concurrency", -1)
            >= runtime.get("minimum_concurrency", float("inf"))
            for row in runtime_rows
        ),
    }
    return [
        {
            "capability_id": f"__global__.{name}",
            "status": "met" if is_met else "unmet",
            "unmet_constraints": () if is_met else (name,),
        }
        for name, is_met in sorted(checks.items())
    ]


def evaluate_consumer_requirements_admission(
    admission: Mapping[str, Any],
    *,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]],
    observed_at: str | datetime,
    replay_ledger: MutableMapping[str, str] | None = None,
) -> tuple[dict[str, Any], tuple[ValidationIssue, ...]]:
    """Fail closed at use time and return separate required/optional outcomes.

    ``replay_ledger`` is an injected durable nonce store.  Callers must commit it
    atomically with their surrounding admission journal; this pure boundary does
    not claim to provide Main's durable controller state.
    """
    issues = _schema_issues(admission)
    requirements = admission.get("requirements")
    offered_raw = admission.get("offered_capabilities")
    offered = [row for row in offered_raw or () if isinstance(row, Mapping)]
    if not isinstance(requirements, Mapping):
        requirements = {}
    issues.extend(
        validate_maskfactory_consumer_requirements(
            requirements, trusted_signing_keys=trusted_signing_keys
        )
    )

    now = _at_time(observed_at)
    authentication = requirements.get("authentication") if isinstance(requirements, Mapping) else {}
    issued = (
        _at_time(authentication.get("issued_at")) if isinstance(authentication, Mapping) else None
    )
    expires = (
        _at_time(authentication.get("expires_at")) if isinstance(authentication, Mapping) else None
    )
    if now is None or issued is None or expires is None or not (issued <= now < expires):
        issues.append(
            _issue(
                "/requirements/authentication",
                "requirements_freshness",
                "requirements are expired or observation time is invalid",
            )
        )

    capability_ids = [row.get("capability_id") for row in offered]
    duplicate_ids = {item for item in capability_ids if capability_ids.count(item) > 1}
    if duplicate_ids or len(offered) != len(offered_raw or ()):
        issues.append(
            _issue(
                "/offered_capabilities",
                "capability_ambiguity",
                "offered capability identities must be unique and complete",
            )
        )
    offered_by_id = {row.get("capability_id"): row for row in offered}
    required = [
        _capability_outcome(row, offered_by_id.get(row.get("capability_id")))
        for row in requirements.get("required_capabilities") or ()
        if isinstance(row, Mapping)
    ]
    optional = [
        _capability_outcome(row, offered_by_id.get(row.get("capability_id")))
        for row in requirements.get("optional_capabilities") or ()
        if isinstance(row, Mapping)
    ]
    required.extend(_global_outcomes(requirements, offered))

    nonce = authentication.get("nonce") if isinstance(authentication, Mapping) else None
    fingerprint = canonical_document_sha256(requirements) if requirements else ""
    if replay_ledger is not None and isinstance(nonce, str):
        prior = replay_ledger.get(nonce)
        if prior is not None:
            issues.append(
                _issue(
                    "/requirements/authentication/nonce",
                    "requirements_replay",
                    "consumer requirements nonce was already admitted",
                )
            )
        elif not issues:
            replay_ledger[nonce] = fingerprint

    failed_required = [row["capability_id"] for row in required if row["status"] != "met"]
    decision = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_consumer_requirements_admission_decision",
        "requirements_id": requirements.get("requirements_id"),
        "requirements_sha256": requirements.get("requirements_sha256"),
        "observed_at": (
            observed_at.isoformat().replace("+00:00", "Z")
            if isinstance(observed_at, datetime)
            else observed_at
        ),
        "status": "accepted" if not issues and not failed_required else "rejected",
        "required_outcomes": tuple(required),
        "optional_outcomes": tuple(optional),
        "rejection_reasons": tuple(
            sorted({issue.validator for issue in issues} | set(failed_required))
        ),
    }
    return decision, tuple(sorted(set(issues)))


__all__ = ["evaluate_consumer_requirements_admission"]
