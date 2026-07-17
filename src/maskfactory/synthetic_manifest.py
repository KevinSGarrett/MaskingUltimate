"""Versioned MaskFactory synthetic manifests without historical schema reinterpretation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .validation import ArtifactValidationError, ValidationIssue, validate_document

SYNTHETIC_SCHEMA_VERSION = "maskfactory_instance_synthetic_1.0.0"
SYNTHETIC_SCHEMA_BY_ONTOLOGY = {
    "body_parts_v1": "manifest_synthetic_v1",
    "body_parts_v2": "manifest_synthetic_v2",
}
FORBIDDEN_HUMAN_AUTHORITY_FIELDS = frozenset(
    {
        "review",
        "reviewer",
        "reviewer_identity",
        "approved_at",
        "manual_edit_timestamp",
        "human_review_complete",
        "human_edit",
        "cvat_task_id",
        "cvat_job_id",
        "calibration_authority",
        "autonomous_certified_real_evidence",
    }
)


class SyntheticManifestError(ValueError):
    """A synthetic manifest draft, schema dispatch, or content hash is invalid."""


def synthetic_manifest_schema_name(document: Mapping[str, Any]) -> str:
    """Select the new synthetic schema explicitly; never reinterpret a historical manifest."""

    if document.get("schema_version") != SYNTHETIC_SCHEMA_VERSION:
        raise SyntheticManifestError("synthetic manifest schema version is missing or unsupported")
    ontology = document.get("ontology")
    name = ontology.get("name") if isinstance(ontology, Mapping) else None
    try:
        return SYNTHETIC_SCHEMA_BY_ONTOLOGY[str(name)]
    except KeyError as exc:
        raise SyntheticManifestError(f"unsupported synthetic manifest ontology: {name!r}") from exc


def build_synthetic_manifest(draft: Mapping[str, Any]) -> dict[str, Any]:
    """Seal a canonical package hash after validating every non-hash field."""

    if not isinstance(draft, Mapping) or "package_sha256" in draft:
        raise SyntheticManifestError("synthetic manifest draft must omit package_sha256")
    document = dict(draft)
    document["package_sha256"] = _canonical_sha(document)
    require_valid_synthetic_manifest(document)
    return document


def validate_synthetic_manifest(document: Mapping[str, Any]) -> tuple[ValidationIssue, ...]:
    """Return deterministic structural and cross-field synthetic-manifest findings."""

    try:
        schema_name = synthetic_manifest_schema_name(document)
    except SyntheticManifestError as exc:
        return (ValidationIssue("/schema_version", "synthetic_schema_dispatch", str(exc)),)
    issues = list(validate_document(document, schema_name))
    forbidden = sorted(_forbidden_paths(document))
    issues.extend(
        ValidationIssue(
            path,
            "synthetic_human_authority_forbidden",
            "human/review authority is forbidden",
        )
        for path in forbidden
    )
    if issues:
        return tuple(sorted(issues))
    lineage = document["synthetic_lineage"]
    authority = document["mask_authority"]
    construction = document["person_construction"]
    mapping = lineage["instance_mapping"]
    comparisons = {
        "/synthetic_lineage/scene_id": (lineage["scene_id"], document["scene_id"]),
        "/synthetic_lineage/scene_family_id": (
            lineage["scene_family_id"],
            document["scene_family_id"],
        ),
        "/synthetic_lineage/variant_group_id": (
            lineage["variant_group_id"],
            document["variant_group_id"],
        ),
        "/synthetic_lineage/instance_mapping/promoted_person_id": (
            mapping["promoted_person_id"],
            document["promoted_person_id"],
        ),
        "/person_construction/person_id": (
            construction["person_id"],
            document["promoted_person_id"],
        ),
        "/synthetic_lineage/mapping_ontology_version": (
            lineage["mapping_ontology_version"],
            document["ontology"]["name"],
        ),
        "/mask_authority/ontology_version": (
            authority["ontology_version"],
            document["ontology"]["name"],
        ),
        "/mask_authority/ontology_sha256": (
            authority["ontology_sha256"],
            document["ontology"]["snapshot_sha256"],
        ),
        "/mask_authority/certificate_id": (
            authority["certificate_id"],
            lineage["scene_certificate_id"],
        ),
        "/mask_authority/certificate_sha256": (
            authority["certificate_sha256"],
            lineage["scene_certificate_sha256"],
        ),
    }
    for pointer, (observed, expected) in comparisons.items():
        if observed != expected:
            issues.append(
                ValidationIssue(
                    pointer, "synthetic_lineage_cross_binding", f"{observed!r} != {expected!r}"
                )
            )
    expected_instance = int(str(document["promoted_person_id"])[1:]) + 1
    if mapping["instance_id"] != expected_instance:
        issues.append(
            ValidationIssue(
                "/synthetic_lineage/instance_mapping/instance_id",
                "synthetic_instance_mapping",
                f"instance_id must be {expected_instance} for {document['promoted_person_id']}",
            )
        )
    expected_hash = _canonical_sha(
        {key: value for key, value in document.items() if key != "package_sha256"}
    )
    if document["package_sha256"] != expected_hash:
        issues.append(
            ValidationIssue(
                "/package_sha256",
                "synthetic_package_hash",
                "package_sha256 does not match canonical manifest content",
            )
        )
    return tuple(sorted(issues))


def require_valid_synthetic_manifest(document: Mapping[str, Any]) -> None:
    """Raise unless the selected synthetic version and every invariant pass."""

    issues = validate_synthetic_manifest(document)
    if issues:
        raise ArtifactValidationError(issues)


def _forbidden_paths(value: Any, path: str = "") -> set[str]:
    findings: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            pointer = f"{path}/{str(key).replace('~', '~0').replace('/', '~1')}"
            if key in FORBIDDEN_HUMAN_AUTHORITY_FIELDS:
                findings.add(pointer)
            findings.update(_forbidden_paths(child, pointer))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.update(_forbidden_paths(child, f"{path}/{index}"))
    return findings


def _canonical_sha(document: Any) -> str:
    try:
        payload = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SyntheticManifestError(f"synthetic manifest is not canonical JSON: {exc}") from exc
    return hashlib.sha256(payload).hexdigest()
