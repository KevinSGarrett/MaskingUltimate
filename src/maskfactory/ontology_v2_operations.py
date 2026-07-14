"""Fail-closed restore integrity for inactive ``body_parts_v2`` packages.

The normal package verifier historically assumes the production v1 ontology.
This module supplies the ontology-aware restore checks needed while v2 remains
inactive.  It verifies structure, the exhaustive file hash inventory, strict
mask encoding, and gold authority without granting activation or approval.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml
from PIL import Image

from .ontology_v2_manifest import (
    OntologyV2ManifestError,
    require_v2_supervision_eligible,
    v2_manifest_issues,
)
from .qa.checks import QcResult
from .validation import validate_document

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OPERATIONS_CONFIG = ROOT / "configs" / "ontology_v2_operations.yaml"

EXPECTED_OPERATIONS_POLICY = {
    "backup": {
        "required_layers": ["packages", "qa", "configs", "sqlite_snapshot"],
        "ontology_aware_package_verification": True,
    },
    "restore": {
        "schema": "manifest_v2",
        "require_exhaustive_file_hashes": True,
        "require_strict_binary_masks": True,
        "gold_requires_v2_review_authority": True,
    },
    "gc": {
        "eligible_path_pattern": "masks@vN",
        "protected_roots": [
            "masks",
            "masks_ignore",
            "masks_derived",
            "qa",
            "qa_panels",
            "annotations",
        ],
        "dry_run_required": True,
    },
    "reindex": {
        "schema_by_ontology": {
            "body_parts_v1": "manifest",
            "body_parts_v2": "manifest_v2",
        },
        "packages_are_authority": True,
    },
    "dvc": {
        "dataset_name": "bodyparts",
        "new_version_only": True,
        "rewrite_existing_path_or_tag": False,
    },
    "incident_drills": {
        "required": ["restore_copy", "v2_reindex_copy", "gc_sandbox", "v1_rollback"],
        "production_mutation_allowed": False,
    },
}


class OntologyV2OperationsError(ValueError):
    """The inactive-v2 operations policy or artifact is malformed."""


def load_v2_operations_policy(
    path: Path | str = DEFAULT_OPERATIONS_CONFIG,
) -> dict[str, Any]:
    """Load the exact inactive-v2 recovery policy and reject silent drift."""
    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise OntologyV2OperationsError(
            f"cannot load ontology-v2 operations policy: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise OntologyV2OperationsError("ontology-v2 operations policy root must be an object")
    identity = {
        "schema_version": document.get("schema_version"),
        "ontology_version": document.get("ontology_version"),
        "activation_status": document.get("activation_status"),
    }
    if identity != {
        "schema_version": "1.0.0",
        "ontology_version": "body_parts_v2",
        "activation_status": "approved_design_not_active",
    }:
        raise OntologyV2OperationsError("ontology-v2 operations identity drifted")
    if document.get("operations") != EXPECTED_OPERATIONS_POLICY:
        raise OntologyV2OperationsError("ontology-v2 recovery policy drifted")
    return document


def run_v2_restore_integrity(package_root: Path | str) -> tuple[QcResult, ...]:
    """Verify one restored v2 package without treating it as active production truth."""
    root = Path(package_root)
    manifest_path = root / "manifest.json"
    manifest: Mapping[str, Any] | None
    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = loaded if isinstance(loaded, Mapping) else None
    except (OSError, json.JSONDecodeError) as exc:
        manifest = None
        manifest_detail = str(exc)
    else:
        structural = validate_document(loaded, "manifest_v2")
        semantic = v2_manifest_issues(loaded) if manifest is not None else ("not an object",)
        findings = [str(issue) for issue in structural] + list(semantic)
        manifest_detail = "valid body_parts_v2 manifest" if not findings else "; ".join(findings)

    schema_ok = manifest is not None and manifest_detail == "valid body_parts_v2 manifest"
    hashes_ok, hashes_detail = _verify_hash_inventory(root, manifest)
    masks_ok, masks_detail = _verify_strict_masks(root, manifest)
    authority_ok, authority_detail = _verify_workflow_authority(root, manifest)
    policy_ok = False
    policy_detail = "ontology-v2 operations policy unavailable"
    try:
        policy = load_v2_operations_policy()
        policy_ok = policy["activation_status"] == "approved_design_not_active"
        policy_detail = "inactive-v2 recovery policy current; activation not granted"
    except OntologyV2OperationsError as exc:
        policy_detail = str(exc)
    return (
        QcResult("OPS-V2-001", "manifest_v2_contract", schema_ok, manifest_detail),
        QcResult("OPS-V2-002", "exhaustive_file_hashes", hashes_ok, hashes_detail),
        QcResult("OPS-V2-003", "strict_mask_restore", masks_ok, masks_detail),
        QcResult("OPS-V2-004", "workflow_review_authority", authority_ok, authority_detail),
        QcResult("OPS-V2-005", "inactive_operations_policy", policy_ok, policy_detail),
    )


def _verify_hash_inventory(root: Path, manifest: Mapping[str, Any] | None) -> tuple[bool, str]:
    if manifest is None or not isinstance(manifest.get("files"), Mapping):
        return False, "manifest files mapping unavailable"
    expected = manifest["files"]
    actual = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "manifest.json"
        and not path.relative_to(root).parts[0].startswith("masks@v")
    }
    missing = sorted(set(expected).difference(actual))
    untracked = sorted(set(actual).difference(expected))
    mismatched = sorted(
        relative
        for relative in set(expected).intersection(actual)
        if not isinstance(expected[relative], str)
        or hashlib.sha256(actual[relative].read_bytes()).hexdigest() != expected[relative]
    )
    if missing or untracked or mismatched:
        return False, f"missing={missing}, untracked={untracked}, mismatch={mismatched}"
    return True, f"all {len(actual)} restored file hashes match"


def _verify_strict_masks(root: Path, manifest: Mapping[str, Any] | None) -> tuple[bool, str]:
    if manifest is None:
        return False, "manifest unavailable"
    source = manifest.get("source")
    parts = manifest.get("parts")
    if not isinstance(source, Mapping) or not isinstance(parts, Mapping):
        return False, "source/parts authority unavailable"
    size = (source.get("source_width"), source.get("source_height"))
    if not all(isinstance(value, int) and value > 0 for value in size):
        return False, "source dimensions unavailable"
    relative_paths: set[str] = set()
    for entry in parts.values():
        if not isinstance(entry, Mapping):
            continue
        for field in ("mask_file", "ambiguity_file"):
            value = entry.get(field)
            if isinstance(value, str) and value:
                relative_paths.add(value.replace("\\", "/"))
    failures: list[str] = []
    resolved_root = root.resolve()
    for relative in sorted(relative_paths):
        path = (root / relative).resolve()
        if resolved_root not in path.parents or not path.is_file():
            failures.append(f"{relative}: missing_or_escaped")
            continue
        try:
            with Image.open(path) as opened:
                image_format = opened.format
                mode = opened.mode
                image_size = opened.size
                values = set(np.unique(np.asarray(opened)).tolist())
        except (OSError, ValueError) as exc:
            failures.append(f"{relative}: {exc}")
            continue
        if image_format != "PNG" or mode != "L" or image_size != size or not values <= {0, 255}:
            failures.append(
                f"{relative}: format={image_format} mode={mode} size={image_size} values={sorted(values)}"
            )
    if failures:
        return False, "; ".join(failures)
    return True, f"{len(relative_paths)} referenced masks are full-size strict binary PNGs"


def _verify_workflow_authority(root: Path, manifest: Mapping[str, Any] | None) -> tuple[bool, str]:
    if manifest is None:
        return False, "manifest unavailable"
    workflow = manifest.get("workflow_status")
    if workflow not in {"approved_gold", "exported"}:
        return True, f"non-gold v2 workflow preserved as {workflow}; no approval inferred"
    try:
        require_v2_supervision_eligible(manifest)
    except OntologyV2ManifestError as exc:
        return False, str(exc)
    if not (root / ".maskfactory_frozen.json").is_file():
        return False, "approved/exported v2 package is not frozen"
    qa = manifest.get("qa")
    report_value = qa.get("qa_report_file") if isinstance(qa, Mapping) else None
    if not isinstance(qa, Mapping) or qa.get("qa_overall") != "pass":
        return False, "approved/exported v2 package does not declare passing QA"
    if not isinstance(report_value, str) or not (root / report_value).is_file():
        return False, "approved/exported v2 QA report is missing"
    try:
        report = json.loads((root / report_value).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"cannot read approved/exported v2 QA report: {exc}"
    if not isinstance(report, Mapping) or (
        report.get("ontology_version") != "body_parts_v2" or report.get("overall") != "pass"
    ):
        return False, "approved/exported v2 QA report lacks body_parts_v2 pass authority"
    return True, "fully reviewed v2 gold authority and QA evidence are internally consistent"


__all__ = [
    "DEFAULT_OPERATIONS_CONFIG",
    "EXPECTED_OPERATIONS_POLICY",
    "OntologyV2OperationsError",
    "load_v2_operations_policy",
    "run_v2_restore_integrity",
]
