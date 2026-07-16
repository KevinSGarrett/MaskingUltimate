"""Freeze the canonical MaskFactory v1 ontology for DAZ mapping jobs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

import yaml

from ...ontology import OntologyError, load_ontology
from ...validation import require_valid_document

EXPECTED_VERSION = "body_parts_v1"
EXPECTED_PART_IDS = tuple(range(56))
EXPECTED_MATERIAL_IDS = tuple(range(16))


class OntologySnapshotError(ValueError):
    """The canonical ontology cannot be frozen into an exact DAZ mapping input."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def build_v1_ontology_snapshot(
    source: Path,
    *,
    source_locator: str = "configs/ontology.yaml",
) -> dict[str, Any]:
    source = Path(source)
    try:
        source_bytes = source.read_bytes()
        raw = yaml.safe_load(source_bytes)
        ontology = load_ontology(source)
    except (OSError, yaml.YAMLError, OntologyError) as exc:
        raise OntologySnapshotError("ontology_load_failed", type(exc).__name__) from exc
    if not isinstance(raw, dict):
        raise OntologySnapshotError("ontology_shape_invalid", "source root must be a mapping")
    if ontology.version != EXPECTED_VERSION:
        raise OntologySnapshotError(
            "ontology_version_invalid", f"expected {EXPECTED_VERSION}, found {ontology.version}"
        )
    if raw.get("left_right_convention") != "character_perspective":
        raise OntologySnapshotError(
            "left_right_convention_invalid", "v1 must use character_perspective"
        )
    if raw.get("visible_pixel_only") is not True:
        raise OntologySnapshotError(
            "visibility_contract_invalid", "v1 mapping input must be visible-pixel-only"
        )

    part_labels = ontology.labels_for_map("part")
    part_ids = tuple(label.id for label in part_labels)
    if part_ids != EXPECTED_PART_IDS:
        raise OntologySnapshotError(
            "part_id_contract_invalid", "canonical v1 PART IDs must be ordered and contiguous 0..55"
        )
    derived = tuple(label for label in ontology.labels if label.map == "none")
    material_labels = ontology.labels_for_map("material")
    material_ids = tuple(label.id for label in material_labels)
    if material_ids != EXPECTED_MATERIAL_IDS:
        raise OntologySnapshotError(
            "material_id_contract_invalid",
            "canonical v1 MATERIAL IDs must be ordered and contiguous 0..15",
        )
    other_indexed = tuple(
        label
        for label in ontology.labels
        if label.id is not None and label.map not in {"part", "material"}
    )
    if other_indexed:
        raise OntologySnapshotError(
            "unexpected_indexed_map", "v1 DAZ snapshot found an unsupported indexed map"
        )

    loader_path = Path(__file__).resolve().parents[2] / "ontology.py"
    core: dict[str, Any] = {
        "schema_version": "1.0.0",
        "ontology_version": ontology.version,
        "source": {
            "locator": source_locator,
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "loader_locator": "src/maskfactory/ontology.py",
            "loader_sha256": _sha256_file(loader_path),
        },
        "left_right_convention": raw["left_right_convention"],
        "visible_pixel_only": raw["visible_pixel_only"],
        "part_id_min": 0,
        "part_id_max": 55,
        "part_label_count": len(part_labels),
        "enabled_part_label_count": sum(1 for label in part_labels if label.enabled),
        "disabled_part_labels": [label.name for label in part_labels if not label.enabled],
        "part_labels": [_label_record(label, ontology) for label in part_labels],
        "material_id_min": 0,
        "material_id_max": 15,
        "material_label_count": len(material_labels),
        "material_labels": [_label_record(label, ontology) for label in material_labels],
        "derived_labels": [_label_record(label, ontology) for label in derived],
        "protected_classes": list(raw.get("protected_classes", [])),
        "projected_templates": list(raw.get("projected_templates", [])),
    }
    canonical_sha = _canonical_sha(core)
    document = {
        **core,
        "snapshot_id": f"ontology_v1_{canonical_sha[:24]}",
        "canonical_sha256": canonical_sha,
    }
    require_valid_document(document, "daz_ontology_snapshot")
    return document


def publish_ontology_snapshot(snapshot: Mapping[str, Any], output_root: Path) -> tuple[Path, bool]:
    try:
        require_valid_document(snapshot, "daz_ontology_snapshot")
    except ValueError as exc:
        raise OntologySnapshotError("snapshot_schema_invalid", str(exc)) from exc
    snapshot_id = snapshot.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id.startswith("ontology_v1_"):
        raise OntologySnapshotError("snapshot_identity_invalid", "snapshot identity is invalid")
    canonical_sha = snapshot.get("canonical_sha256")
    core = {
        key: value
        for key, value in snapshot.items()
        if key not in {"snapshot_id", "canonical_sha256"}
    }
    computed_sha = _canonical_sha(core)
    if canonical_sha != computed_sha or snapshot_id != f"ontology_v1_{computed_sha[:24]}":
        raise OntologySnapshotError(
            "snapshot_digest_invalid",
            "snapshot identity or canonical digest does not match content",
        )
    payload = (json.dumps(snapshot, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / f"{snapshot_id}.json"
    if target.exists():
        if target.read_bytes() != payload:
            raise OntologySnapshotError(
                "snapshot_immutable_conflict", "existing snapshot bytes differ"
            )
        return target, False
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{snapshot_id}.", suffix=".tmp", dir=output_root
    )
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return target, True


def _label_record(label: Any, ontology: Any) -> dict[str, Any]:
    record = asdict(label)
    record["expected_area_pct_range"] = (
        list(label.expected_area_pct_range) if label.expected_area_pct_range is not None else None
    )
    record["boundary_rule_text"] = ontology.boundary_rule_text(label.boundary_rule)
    return record


def _canonical_sha(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
