"""Exact per-record QA-vector verification for autonomous-certified gold."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..io.hashing import sha256_file
from ..io.png_strict import read_mask
from ..validation import ArtifactValidationError, require_valid_document
from ..vlm.target_contract import (
    TargetContractError,
    target_contract_sha256,
    validate_target_contract,
)
from .package_semantic_alignment import final_mask_set_sha256
from .qa_thresholds import REQUIRED_METRICS, QaThresholdRegistryError, require_gold_authority

MANDATORY_METRICS = frozenset(
    {
        "expected_presence",
        "owner_containment",
        "protected_region_overlap",
        "mutually_exclusive_overlap",
        "cross_person_bleed",
        "laterality_consistency",
        "front_back_consistency",
        "atomic_map_exclusivity",
        "transform_roundtrip",
        "duplicate_person",
        "duplicate_mask",
        "complete_map_recomposition",
    }
)
REGISTRY_FIELDS = frozenset(
    {
        "registry_id",
        "registry_file_sha256",
        "resolved_registry_sha256",
        "ontology_sha256",
        "calibration_evidence_sha256",
        "qualification_status",
        "authority_eligible",
        "resolved_label_threshold_sha256s",
    }
)


class PerRecordQaError(ValueError):
    """Per-record QA evidence is incomplete, drifted, or non-authorizing."""


def per_record_qa_vector_sha256(document: Mapping[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "vector_sha256"}
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def decoded_mask_sha256(path: Path) -> str:
    mask = read_mask(Path(path))
    return hashlib.sha256(mask.tobytes(order="C")).hexdigest()


def validate_per_record_qa_vector(
    document: Mapping[str, Any],
    *,
    package_root: Path,
    manifest: Mapping[str, Any],
    target_contracts: Mapping[str, Mapping[str, Any]],
    qualified_registry: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        require_valid_document(dict(document), "autonomous_gold_per_record_qa_vector")
    except ArtifactValidationError as exc:
        raise PerRecordQaError(f"per-record QA vector schema is invalid: {exc}") from exc
    if document.get("vector_sha256") != per_record_qa_vector_sha256(document):
        raise PerRecordQaError("per-record QA vector hash mismatch")
    if set(qualified_registry) != REGISTRY_FIELDS:
        raise PerRecordQaError("qualified QA registry binding is incomplete or unknown")
    try:
        require_gold_authority(qualified_registry)
    except QaThresholdRegistryError as exc:
        raise PerRecordQaError(str(exc)) from exc
    binding = document["registry_binding"]
    for field in REGISTRY_FIELDS - {"resolved_label_threshold_sha256s"}:
        if binding.get(field) != qualified_registry.get(field):
            raise PerRecordQaError(f"per-record QA registry binding mismatch: {field}")
    label_thresholds = qualified_registry["resolved_label_threshold_sha256s"]
    if not isinstance(label_thresholds, Mapping):
        raise PerRecordQaError("qualified QA label-threshold map is invalid")

    active_parts = {
        name: entry
        for name, entry in manifest.get("parts", {}).items()
        if isinstance(entry, Mapping)
        and entry.get("status") != "n/a"
        and entry.get("mask_file") is not None
    }
    rows = document["labels"]
    indexed = {row["label"]: row for row in rows}
    if len(indexed) != len(rows) or set(indexed) != set(active_parts):
        raise PerRecordQaError("per-record QA label inventory differs from final package")
    if set(target_contracts) != set(active_parts):
        raise PerRecordQaError("target-contract inventory differs from final package")
    expected_mask_set = final_mask_set_sha256(Path(package_root), dict(manifest))
    if document["final_mask_set_sha256"] != expected_mask_set:
        raise PerRecordQaError("per-record QA final mask-set hash mismatch")

    identities: set[tuple[Any, ...]] = set()
    for label, part in active_parts.items():
        row = indexed[label]
        contract = target_contracts[label]
        try:
            validate_target_contract(contract)
        except TargetContractError as exc:
            raise PerRecordQaError(f"target contract rejected for {label}: {exc}") from exc
        if contract.get("schema_version") != "2.0.0":
            raise PerRecordQaError("autonomous-gold QA requires target contract v2")
        target = contract["target"]
        owner = contract["owner"]
        package = contract["package"]
        source = contract["source"]
        candidate = contract["candidate"]
        if target["label_id"] != label or row["target_contract_sha256"] != target_contract_sha256(
            contract
        ):
            raise PerRecordQaError(f"target contract label/hash mismatch: {label}")
        identity = (
            source["image_id"],
            owner["person_index"],
            owner["character_instance_id"],
            package["package_id"],
            package["revision"],
            package["parent_revision"],
        )
        identities.add(identity)
        if row["threshold_resolution_sha256"] != label_thresholds.get(label):
            raise PerRecordQaError(f"qualified threshold resolution mismatch: {label}")
        relative = Path(str(part["mask_file"]))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise PerRecordQaError(f"mask path is invalid: {label}")
        mask_path = (Path(package_root) / relative).resolve()
        try:
            mask_path.relative_to(Path(package_root).resolve())
        except ValueError as exc:
            raise PerRecordQaError(f"mask path escaped package: {label}") from exc
        encoded = sha256_file(mask_path)
        decoded = decoded_mask_sha256(mask_path)
        if (
            row["mask_encoded_sha256"] != encoded
            or row["mask_decoded_pixel_sha256"] != decoded
            or candidate["encoded_sha256"] != encoded
            or candidate["decoded_pixel_sha256"] != decoded
        ):
            raise PerRecordQaError(f"mask identity drift: {label}")
        metrics = row["metrics"]
        metric_index = {metric["metric"]: metric for metric in metrics}
        if len(metric_index) != len(metrics) or set(metric_index) != REQUIRED_METRICS:
            raise PerRecordQaError(f"metric coverage is incomplete or duplicated: {label}")
        nonpassing = sorted(
            name for name in MANDATORY_METRICS if metric_index[name]["status"] != "pass"
        )
        if nonpassing:
            raise PerRecordQaError(f"mandatory metrics are not passing for {label}: {nonpassing}")
    if len(identities) != 1:
        raise PerRecordQaError("per-record target contracts disagree on package/owner identity")
    image_id, person_index, character_instance_id, package_id, revision, parent_revision = (
        identities.pop()
    )
    expected_identity = (
        document["image_id"],
        document["person_index"],
        document["character_instance_id"],
        document["package_id"],
        document["package_revision"],
        document["parent_package_revision"],
    )
    if expected_identity != (
        image_id,
        person_index,
        character_instance_id,
        package_id,
        revision,
        parent_revision,
    ):
        raise PerRecordQaError("per-record QA package/owner identity mismatch")
    return {
        "status": "pass",
        "vector_sha256": document["vector_sha256"],
        "registry_file_sha256": binding["registry_file_sha256"],
        "resolved_registry_sha256": binding["resolved_registry_sha256"],
        "calibration_evidence_sha256": binding["calibration_evidence_sha256"],
        "final_mask_set_sha256": expected_mask_set,
        "labels": sorted(active_parts),
    }


__all__ = [
    "MANDATORY_METRICS",
    "PerRecordQaError",
    "decoded_mask_sha256",
    "per_record_qa_vector_sha256",
    "validate_per_record_qa_vector",
]
