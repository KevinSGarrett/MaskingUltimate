"""Controlled import of mask add/subtract edits into a working label map."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path

import numpy as np

from ..io.png_strict import read_mask, write_label_map
from ..ontology import get_ontology


class MaskDeltaError(ValueError):
    """A correction graph attempted an unsafe or ambiguous label-map edit."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _strict_binary(path: Path, shape: tuple[int, int]) -> np.ndarray:
    value = read_mask(path)
    if value.shape != shape or value.dtype != np.uint8:
        raise MaskDeltaError(f"correction mask geometry/type differs: {path}")
    if not set(np.unique(value).tolist()) <= {0, 255}:
        raise MaskDeltaError(f"correction mask is not strict binary: {path}")
    return value > 0


def apply_part_mask_delta(
    *,
    label_map_path: Path,
    target_label: str,
    output_path: Path,
    add_mask_path: Path | None = None,
    subtract_mask_path: Path | None = None,
    subtract_replacement_label: str | None = None,
    silhouette_path: Path | None = None,
) -> Path:
    """Apply explicit additions/removals to a staging map; never write gold directly.

    Subtraction requires a replacement ontology label because a canonical part map
    may not contain unexplained holes inside the person silhouette.
    """
    output_path = Path(output_path).resolve()
    if "work" not in {part.lower() for part in output_path.parts}:
        raise MaskDeltaError("correction output must be staged beneath a work directory")
    if add_mask_path is None and subtract_mask_path is None:
        raise MaskDeltaError("at least one add or subtract mask is required")
    ontology = get_ontology()
    target = ontology.label(target_label, require_enabled=True)
    if target.map != "part" or target.id is None:
        raise MaskDeltaError(f"target is not an indexed part label: {target_label}")
    label_map_path = Path(label_map_path)
    label_map = read_mask(label_map_path).astype(np.uint16)
    if label_map.ndim != 2:
        raise MaskDeltaError("part label map must be two-dimensional")
    known_ids = {int(label.id) for label in ontology.labels_for_map("part") if label.id is not None}
    unknown = set(np.unique(label_map).tolist()) - known_ids
    if unknown:
        raise MaskDeltaError(f"part label map contains unknown IDs: {sorted(unknown)}")
    silhouette = (
        _strict_binary(Path(silhouette_path), label_map.shape)
        if silhouette_path is not None
        else label_map > 0
    )
    operations: list[dict[str, object]] = []
    if add_mask_path is not None:
        add = _strict_binary(Path(add_mask_path), label_map.shape)
        if np.any(add & ~silhouette):
            raise MaskDeltaError("add mask extends outside the governed person silhouette")
        label_map[add] = int(target.id)
        operations.append(
            {
                "operation": "add",
                "mask_sha256": _sha256(Path(add_mask_path)),
                "pixels": int(add.sum()),
            }
        )
    if subtract_mask_path is not None:
        if not subtract_replacement_label:
            raise MaskDeltaError("subtract requires an explicit replacement ontology label")
        replacement = ontology.label(subtract_replacement_label, require_enabled=True)
        if replacement.map != "part" or replacement.id is None:
            raise MaskDeltaError("subtract replacement must be an indexed part label")
        subtract = _strict_binary(Path(subtract_mask_path), label_map.shape)
        changed = subtract & (label_map == int(target.id))
        label_map[changed] = int(replacement.id)
        operations.append(
            {
                "operation": "subtract",
                "replacement_label": replacement.name,
                "mask_sha256": _sha256(Path(subtract_mask_path)),
                "pixels": int(changed.sum()),
            }
        )
    write_label_map(output_path, label_map, bits=16)
    evidence = {
        "schema_version": "1.0.0",
        "authority": "human_review_staging_only",
        "requires_normal_derivation_qa_and_human_approval": True,
        "input_label_map_sha256": _sha256(label_map_path),
        "output_label_map_sha256": _sha256(output_path),
        "target_label": target.name,
        "operations": operations,
    }
    output_path.with_suffix(".mask_delta.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output_path


def apply_review_package_mask_delta(
    *,
    package_root: Path,
    target_label: str,
    add_mask_path: Path | None = None,
    subtract_mask_path: Path | None = None,
    subtract_replacement_label: str | None = None,
    silhouette_path: Path | None = None,
) -> Path:
    """Apply a staged delta to a mutable review package and rerun hard-block QA."""
    from ..qa.checks import run_qc001_010
    from ..review_package import refresh_review_package_derivations

    package_root = Path(package_root).resolve()
    if (package_root / ".maskfactory_frozen.json").is_file():
        raise MaskDeltaError("refusing to edit a frozen gold package")
    manifest = json.loads((package_root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("workflow_status") in {"approved_gold", "exported", "deprecated"}:
        raise MaskDeltaError("mask delta is allowed only on a mutable review package")
    operation_id = uuid.uuid4().hex
    staging = package_root / "work" / "mask_delta" / operation_id / "label_map_part.png"
    output = apply_part_mask_delta(
        label_map_path=package_root / "label_map_part.png",
        target_label=target_label,
        output_path=staging,
        add_mask_path=add_mask_path,
        subtract_mask_path=subtract_mask_path,
        subtract_replacement_label=subtract_replacement_label,
        silhouette_path=silhouette_path,
    )
    shutil.copy2(output, package_root / "label_map_part.png")
    evidence_root = package_root / "annotations" / "mask_delta" / operation_id
    evidence_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output.with_suffix(".mask_delta.json"), evidence_root / "operation.json")
    refresh_review_package_derivations(package_root)
    checks = run_qc001_010(package_root)
    report = {
        "schema_version": "1.0.0",
        "authority": "qa_recheck_not_human_approval",
        "all_passed": all(check.passed for check in checks),
        "checks": [
            {
                "qc_id": check.qc_id,
                "name": check.name,
                "passed": check.passed,
                "detail": check.detail,
                "severity": check.severity,
            }
            for check in checks
        ],
    }
    (evidence_root / "qa_recheck.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    refresh_review_package_derivations(package_root)
    return package_root / "label_map_part.png"
