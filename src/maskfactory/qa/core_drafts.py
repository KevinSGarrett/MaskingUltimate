"""P2 core-part draft contract derived from the authoritative S09 PART map."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from ..io.png_strict import write_binary_mask
from ..ontology import Ontology, get_ontology


class CoreDraftError(ValueError):
    """The stable 46-part P2 core draft contract cannot be produced."""


FINGER_IDS = frozenset(range(24, 34))


def core_part_labels(ontology: Ontology | None = None):
    """Return all v1 PART ids except the ten P3-owned per-finger atomics."""
    authority = ontology or get_ontology()
    labels = tuple(
        sorted(
            (
                label
                for label in authority.labels_for_map("part")
                if 0 <= label.id <= 55 and label.id not in FINGER_IDS
            ),
            key=lambda label: label.id,
        )
    )
    if len(labels) != 46 or {label.id for label in labels} != set(range(56)) - FINGER_IDS:
        raise CoreDraftError("ontology no longer yields the stable 46-part P2 core registry")
    return labels


def write_core_draft_contract(
    part_map: np.ndarray,
    output_dir: Path,
    *,
    ontology: Ontology | None = None,
) -> Path:
    """Write one strict binary slot and an explicit state for every core label."""
    authority = ontology or get_ontology()
    labels = core_part_labels(authority)
    value = np.asarray(part_map)
    if value.ndim != 2 or not np.issubdtype(value.dtype, np.integer):
        raise CoreDraftError("PART map must be a 2-D integer array")
    known = {label.id for label in authority.labels_for_map("part")}
    if not set(np.unique(value).tolist()) <= known:
        raise CoreDraftError("PART map contains ids outside the ontology")
    root = Path(output_dir) / "core_drafts"
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for label in labels:
        mask = value == label.id
        path = write_binary_mask(
            root / f"{label.name}.png",
            mask,
            source_size=(value.shape[1], value.shape[0]),
        )
        pixel_count = int(mask.sum())
        state = "disabled" if not label.enabled else "drafted" if pixel_count else "not_visible"
        records.append(
            {
                "id": label.id,
                "label": label.name,
                "state": state,
                "pixel_count": pixel_count,
                "path": path.relative_to(Path(output_dir)).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "producer": "S09 fusion of S06/S07 body-aware drafts",
                "finger_lane_owned_ids": sorted(FINGER_IDS),
                "core_part_count": len(records),
                "records": records,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_core_draft_contract(manifest_path: Path, output_dir: Path) -> dict:
    """Verify exact registry, hashes, binary slots, states, and pixel counts."""
    document = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    records = document.get("records")
    if document.get("core_part_count") != 46 or not isinstance(records, list) or len(records) != 46:
        raise CoreDraftError("core draft manifest must contain exactly 46 records")
    expected = core_part_labels()
    if [(row.get("id"), row.get("label")) for row in records] != [
        (label.id, label.name) for label in expected
    ]:
        raise CoreDraftError("core draft manifest registry/order differs from ontology")
    root = Path(output_dir).resolve()
    for row, label in zip(records, expected, strict=True):
        path = (root / row["path"]).resolve()
        if root not in path.parents or not path.is_file():
            raise CoreDraftError(f"{label.name}: missing or escaping binary slot")
        if hashlib.sha256(path.read_bytes()).hexdigest() != row.get("sha256"):
            raise CoreDraftError(f"{label.name}: binary hash mismatch")
        with Image.open(path) as opened:
            pixels = np.asarray(opened)
            if opened.mode != "L" or not set(np.unique(pixels).tolist()) <= {0, 255}:
                raise CoreDraftError(f"{label.name}: binary slot is not strict mode-L")
        count = int((pixels > 0).sum())
        expected_state = "disabled" if not label.enabled else "drafted" if count else "not_visible"
        if count != row.get("pixel_count") or row.get("state") != expected_state:
            raise CoreDraftError(f"{label.name}: state/pixel count mismatch")
    return document
