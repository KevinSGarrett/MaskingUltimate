"""Certificate-aware serving versus residual/audit routing metadata."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from ..autonomy.calibration import verify_autonomy_certificate
from ..autonomy.lifecycle import certificate_is_revoked, certificate_stratum_is_revoked
from ..datasets.splits import validate_instance_split_integrity
from ..validation import validate_document
from .static_contracts import ServingStaticContractError, enforce_serving_route_static


class ServingRouteError(ValueError):
    """Lifecycle evidence cannot support a safe serving route."""


def build_certificate_aware_serving_route(
    lifecycle: Mapping[str, Any],
    certificate: Mapping[str, Any] | None,
    *,
    expected_pipeline_fingerprint: str,
    selected_for_audit: bool,
    revocations_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Re-evaluate current authority without rewriting historical truth evidence."""
    lifecycle_document = dict(lifecycle)
    issues = validate_document(lifecycle_document, "autonomy_lifecycle")
    if issues:
        raise ServingRouteError(
            "invalid autonomy lifecycle: "
            + "; ".join(f"{issue.pointer or '/'} {issue.message}" for issue in issues)
        )
    if not isinstance(expected_pipeline_fingerprint, str) or not expected_pipeline_fingerprint:
        raise ServingRouteError("expected pipeline fingerprint is empty")
    label = str(lifecycle_document["label"])
    context = str(lifecycle_document["context"])
    lifecycle_fingerprint = str(lifecycle_document["pipeline_fingerprint"])
    risk_bucket = (
        str(certificate.get("risk_bucket"))
        if isinstance(certificate, Mapping) and certificate.get("risk_bucket")
        else context
    )
    instance_context = (
        str(certificate.get("instance_context", context))
        if isinstance(certificate, Mapping)
        else context
    )
    valid, reason = verify_autonomy_certificate(
        dict(certificate) if isinstance(certificate, Mapping) else None,
        label=label,
        context=context,
        instance_context=instance_context,
        risk_bucket=risk_bucket,
        pipeline_fingerprint=expected_pipeline_fingerprint,
        now=now,
    )
    if lifecycle_fingerprint != expected_pipeline_fingerprint:
        valid, reason = False, "lifecycle_pipeline_fingerprint_mismatch"
    if certificate_is_revoked(
        revocations_root,
        label=label,
        context=context,
        pipeline_fingerprint=expected_pipeline_fingerprint,
    ):
        valid, reason = False, "certificate_scope_revoked"
    if instance_context in {"duo", "small_group"} and certificate_stratum_is_revoked(
        revocations_root,
        risk_bucket=risk_bucket,
        instance_context=instance_context,
        pipeline_fingerprint=expected_pipeline_fingerprint,
    ):
        valid, reason = False, "certificate_multi_person_stratum_revoked"
    lifecycle_authority = (
        lifecycle_document["status"] == "calibrated_auto_accepted"
        and lifecycle_document["truth_tier"] == "autonomous_certified_gold"
        and lifecycle_document["certificate_valid"] is True
        and lifecycle_document["serve_eligible"] is True
        and lifecycle_document["authoritative_human_gold"] is False
    )
    if not lifecycle_authority:
        valid, reason = False, f"lifecycle_not_certified:{lifecycle_document['status']}"

    certificate_scope = (
        {
            "risk_bucket": certificate["risk_bucket"],
            "covered_labels": list(certificate["covered_labels"]),
            "covered_contexts": list(certificate["covered_contexts"]),
            "pipeline_fingerprint": certificate["pipeline_fingerprint"],
        }
        if valid and isinstance(certificate, Mapping)
        else None
    )
    certificate_metadata = {
        "status": "valid" if valid else "invalid",
        "reason": reason,
        "sha256": certificate.get("sha256") if isinstance(certificate, Mapping) else None,
        "scope": certificate_scope,
    }
    if valid and selected_for_audit:
        serving_status = "withheld_for_preselected_audit"
        truth_tier = "autonomous_certified_gold"
        routing = {
            "destination": "cvat_preselected_audit",
            "residual_reason": None,
            "audit_reason": "preselected_random_or_risk_audit",
        }
    elif valid:
        serving_status = "certified_output"
        truth_tier = "autonomous_certified_gold"
        routing = {
            "destination": "served_without_routine_review",
            "residual_reason": None,
            "audit_reason": None,
        }
    else:
        serving_status = "withheld_for_residual_review"
        truth_tier = "machine_candidate"
        routing = {
            "destination": "cvat_residual_review",
            "residual_reason": reason,
            "audit_reason": None,
        }
    document = {
        "schema_version": "1.0.0",
        "serving_status": serving_status,
        "truth_tier": truth_tier,
        "historical_truth_tier": lifecycle_document["truth_tier"],
        "authoritative_human_gold": False,
        "certificate": certificate_metadata,
        "routing": routing,
    }
    try:
        return enforce_serving_route_static(document)
    except ServingStaticContractError as exc:
        raise ServingRouteError(f"invalid serving route: {exc}") from exc


def build_multi_person_image_routes(
    lifecycles: Mapping[str, Mapping[str, Any]],
    certificates: Mapping[str, Mapping[str, Any] | None],
    *,
    expected_pipeline_fingerprint: str,
    selected_for_audit: bool,
    revocations_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Route a complete pN group while assigning one truth partition per image."""
    if set(lifecycles) != set(certificates) or len(lifecycles) < 2:
        raise ServingRouteError(
            "multi-person image routing requires matching lifecycle/certificate pN sets"
        )
    instance_ids = tuple(sorted(lifecycles, key=_instance_index))
    if instance_ids != tuple(f"p{index}" for index in range(len(instance_ids))):
        raise ServingRouteError("multi-person image routes require contiguous p0..pN instances")
    image_ids = {str(lifecycles[key].get("image_id")) for key in instance_ids}
    if len(image_ids) != 1:
        raise ServingRouteError("multi-person image routes cannot combine different image IDs")
    image_id = next(iter(image_ids))
    for instance_id in instance_ids:
        if str(lifecycles[instance_id].get("instance_id")) != instance_id:
            raise ServingRouteError("multi-person route key differs from lifecycle instance_id")

    routes = {
        instance_id: build_certificate_aware_serving_route(
            lifecycles[instance_id],
            certificates[instance_id],
            expected_pipeline_fingerprint=expected_pipeline_fingerprint,
            selected_for_audit=selected_for_audit,
            revocations_root=revocations_root,
            now=now,
        )
        for instance_id in instance_ids
    }
    residual = tuple(
        instance_id
        for instance_id, route in routes.items()
        if route["routing"]["destination"] == "cvat_residual_review"
    )
    audits = tuple(
        instance_id
        for instance_id, route in routes.items()
        if route["routing"]["destination"] == "cvat_preselected_audit"
    )
    cvat_instances = tuple(sorted((*residual, *audits), key=_instance_index))
    truth_partition = "residual" if residual else "train"
    instance_partitions = {
        f"{image_id}_{instance_id}": truth_partition for instance_id in instance_ids
    }
    validate_instance_split_integrity(instance_partitions)
    return {
        "schema_version": "1.0.0",
        "image_id": image_id,
        "instance_ids": list(instance_ids),
        "truth_partition": truth_partition,
        "instance_truth_partitions": instance_partitions,
        "selected_for_audit": selected_for_audit,
        "cvat_instance_ids": list(cvat_instances),
        "residual_instance_ids": list(residual),
        "audit_instance_ids": list(audits),
        "routes": routes,
    }


def _instance_index(value: str) -> int:
    if not isinstance(value, str) or not value.startswith("p") or not value[1:].isdigit():
        raise ServingRouteError(f"invalid promoted instance id: {value}")
    return int(value[1:])


__all__ = [
    "ServingRouteError",
    "build_certificate_aware_serving_route",
    "build_multi_person_image_routes",
]
