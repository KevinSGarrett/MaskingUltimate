"""S09.5 cross-instance exclusivity, reciprocal contact bands, and image index."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import ndimage

from ..io.png_strict import write_binary_mask


class InstanceReconciliationError(ValueError):
    """Per-instance evidence cannot satisfy the S09.5 contract."""


@dataclass(frozen=True)
class ReconciliationInstance:
    instance_id: str
    silhouette_full: np.ndarray
    context_bbox_xyxy: tuple[int, int, int, int]
    package_dir: Path


@dataclass(frozen=True)
class ReconciliationResult:
    image_manifest_path: Path
    maximum_pair_iou: float
    qc035_passed: bool
    relationships: tuple[dict[str, object], ...]


def reconcile_instances(
    *,
    image_id: str,
    source_file: str,
    instances: tuple[ReconciliationInstance, ...],
    output_dir: Path,
    background_person_count: int,
    crowd_scene: bool,
    instance_overlap_max: float = 0.30,
) -> ReconciliationResult:
    """Check pair overlap and inject each contact band in that instance's crop coordinates."""
    if not instances or len({item.instance_id for item in instances}) != len(instances):
        raise InstanceReconciliationError("instances must be non-empty with unique IDs")
    shape = np.asarray(instances[0].silhouette_full).shape
    if len(shape) != 2 or any(
        np.asarray(item.silhouette_full).shape != shape for item in instances
    ):
        raise InstanceReconciliationError(
            "all instance silhouettes must share one full-canvas shape"
        )
    if not 0 <= instance_overlap_max <= 1 or background_person_count < 0:
        raise InstanceReconciliationError("invalid overlap threshold or background count")
    relationships: list[dict[str, object]] = []
    maximum_iou = 0.0
    for left_index, a in enumerate(instances):
        a_mask = np.asarray(a.silhouette_full).astype(bool)
        for b in instances[left_index + 1 :]:
            b_mask = np.asarray(b.silhouette_full).astype(bool)
            intersection = a_mask & b_mask
            union = a_mask | b_mask
            iou = float(intersection.sum() / union.sum()) if union.any() else 0.0
            maximum_iou = max(maximum_iou, iou)
            near = ndimage.binary_dilation(a_mask, iterations=1) & ndimage.binary_dilation(
                b_mask, iterations=1
            )
            if not near.any():
                continue
            radius = max(1, round(8 * max(1, shape[1]) / 1024))
            full_band = ndimage.binary_dilation(near, iterations=radius) & union
            files = {}
            for item in (a, b):
                x1, y1, x2, y2 = item.context_bbox_xyxy
                if not (0 <= x1 < x2 <= shape[1] and 0 <= y1 < y2 <= shape[0]):
                    raise InstanceReconciliationError(
                        f"invalid context bbox for {item.instance_id}"
                    )
                relative = (
                    Path("instances")
                    / item.instance_id
                    / "masks_regions/interperson_contact_boundary.png"
                )
                write_binary_mask(
                    Path(item.package_dir) / "masks_regions/interperson_contact_boundary.png",
                    full_band[y1:y2, x1:x2],
                    source_size=(x2 - x1, y2 - y1),
                )
                files[item.instance_id] = relative.as_posix()
            relationships.append(
                {
                    "a": a.instance_id,
                    "b": b.instance_id,
                    "relationship": "contact",
                    "contact_band_file_a": files[a.instance_id],
                    "contact_band_file_b": files[b.instance_id],
                    "silhouette_iou": iou,
                    "qc035_passed": iou <= instance_overlap_max,
                }
            )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": "1.0.0",
        "image_id": image_id,
        "source_file": source_file,
        "promoted_instances": [item.instance_id for item in instances],
        "background_person_count": background_person_count,
        "crowd_scene": crowd_scene,
        "instance_overlap_max": instance_overlap_max,
        "maximum_pair_iou": maximum_iou,
        "qc035_passed": maximum_iou <= instance_overlap_max,
        "interperson_relationships": relationships,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path = output_dir / "image_manifest.json"
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ReconciliationResult(
        path, maximum_iou, maximum_iou <= instance_overlap_max, tuple(relationships)
    )
