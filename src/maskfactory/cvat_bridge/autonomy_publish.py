"""Reversibly publish an autonomous non-gold review draft into an existing CVAT task."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image

from ..io.hashing import sha256_file
from ..ontology import get_ontology
from .client import CvatApiError, CvatClient, load_cvat_config
from .labelmap import CvatLabelMap, encode_mask_rle
from .pull import _export_backup
from .push import _load_mapping, _write_json_atomic


def publish_autonomous_review_draft(
    client: CvatClient,
    *,
    task_id: int,
    review_draft_dir: Path,
    audit_dir: Path,
    config_path: Path,
) -> dict[str, Any]:
    """Replace only untouched automatic PART shapes and verify the exact write.

    The operation refuses completed tasks, human-edited target shapes, non-promoted
    drafts, and anything claiming gold authority. Current annotations and a CVAT task
    backup are persisted before the API mutation; verification failure rolls the old
    annotations back immediately.
    """
    task_id = int(task_id)
    if task_id <= 0:
        raise CvatApiError("CVAT task id must be positive")
    review_root = Path(review_draft_dir)
    report_path = review_root / "report.json"
    map_path = review_root / "label_map_part.png"
    if not report_path.is_file() or not map_path.is_file():
        raise CvatApiError("autonomous review draft requires report.json and label_map_part.png")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if (
        report.get("authority") != "machine_generated_review_draft_non_gold"
        or report.get("authoritative_human_gold") is not False
        or report.get("human_gold_approval_required") is not True
        or report.get("promoted_for_human_review") is not True
    ):
        raise CvatApiError("CVAT publication refuses a non-promoted or authoritative draft")
    task = client.request("GET", f"/api/tasks/{task_id}")
    state = (
        str(task.get("state") or task.get("status") or "").lower() if isinstance(task, dict) else ""
    )
    if not state:
        raise CvatApiError("CVAT publication cannot verify the task state")
    if state in {"completed", "validation", "accepted"}:
        raise CvatApiError(f"CVAT publication refuses task state {state!r}")
    annotations = client.request("GET", f"/api/tasks/{task_id}/annotations")
    if not isinstance(annotations, dict) or not isinstance(annotations.get("shapes", []), list):
        raise CvatApiError("CVAT task returned invalid annotations")
    _project_id, mapping = _load_mapping(load_cvat_config(config_path))
    part_names = {
        label.name for label in get_ontology().labels_for_map("part", enabled_only=True) if label.id
    }
    part_cvat_ids = {mapping.cvat_id(name) for name in part_names}
    current_shapes = list(annotations.get("shapes", []))
    target_shapes = [
        shape for shape in current_shapes if int(shape.get("label_id", -1)) in part_cvat_ids
    ]
    human_targets = [
        shape
        for shape in target_shapes
        if str(shape.get("source", "manual")).lower() not in {"auto", "automatic"}
    ]
    if human_targets:
        raise CvatApiError(
            "CVAT publication refuses to overwrite human-edited PART shapes; create a new review task"
        )
    label_map = np.asarray(Image.open(map_path))
    if label_map.ndim != 2:
        raise CvatApiError("autonomous PART draft must be a one-channel label map")
    replacement = _part_shapes(label_map, mapping)
    retained = [
        shape for shape in current_shapes if int(shape.get("label_id", -1)) not in part_cvat_ids
    ]
    proposed = {
        "version": int(annotations.get("version", 0)),
        "tags": list(annotations.get("tags", [])),
        "shapes": [*retained, *replacement],
        "tracks": list(annotations.get("tracks", [])),
    }
    audit_root = Path(audit_dir) / f"task_{task_id}"
    audit_root.mkdir(parents=True, exist_ok=True)
    backup = _export_backup(client, task_id)
    (audit_root / "task_backup_before.zip").write_bytes(backup)
    _write_json_atomic(audit_root / "annotations_before.json", annotations)
    _write_json_atomic(audit_root / "annotations_proposed.json", proposed)
    try:
        client.request("PUT", f"/api/tasks/{task_id}/annotations", payload=proposed, timeout=180)
        observed = client.request("GET", f"/api/tasks/{task_id}/annotations")
        if not isinstance(observed, dict) or _shape_digest(
            observed.get("shapes", [])
        ) != _shape_digest(proposed["shapes"]):
            raise CvatApiError("CVAT did not persist the proposed autonomous draft exactly")
    except Exception:
        client.request("PUT", f"/api/tasks/{task_id}/annotations", payload=annotations, timeout=180)
        raise
    outcome = {
        "schema_version": "1.0.0",
        "task_id": task_id,
        "status": "published_reversible_non_gold_review_draft",
        "review_draft": str(review_root.resolve()),
        "review_map_sha256": sha256_file(map_path),
        "replaced_automatic_part_shape_count": len(target_shapes),
        "published_part_shape_count": len(replacement),
        "retained_nonpart_shape_count": len(retained),
        "backup": "task_backup_before.zip",
        "authoritative_human_gold": False,
        "human_approval_required": True,
    }
    _write_json_atomic(audit_root / "publication.json", outcome)
    return outcome


def _part_shapes(label_map: np.ndarray, mapping: CvatLabelMap) -> list[dict[str, Any]]:
    output = []
    for label in get_ontology().labels_for_map("part", enabled_only=True):
        if not label.id:
            continue
        mask = label_map == int(label.id)
        if not mask.any():
            continue
        output.append(
            {
                "type": "mask",
                "frame": 0,
                "label_id": mapping.cvat_id(label.name),
                "points": encode_mask_rle(mask.astype(np.uint8) * 255),
                "occluded": False,
                "outside": False,
                "z_order": 0,
                "rotation": 0,
                "attributes": [
                    {
                        "spec_id": mapping.attribute_id(label.name, "visibility"),
                        "value": "visible",
                    },
                    {
                        "spec_id": mapping.attribute_id(label.name, "ambiguous"),
                        "value": "false",
                    },
                    {
                        "spec_id": mapping.attribute_id(label.name, "notes"),
                        "value": "machine-repaired non-gold draft; human approval required",
                    },
                ],
                "source": "auto",
            }
        )
    return output


def _shape_digest(shapes: Any) -> str:
    canonical = []
    for raw in shapes if isinstance(shapes, list) else []:
        shape: Mapping[str, Any] = raw
        canonical.append(
            {
                key: shape.get(key)
                for key in (
                    "type",
                    "frame",
                    "label_id",
                    "points",
                    "occluded",
                    "outside",
                    "z_order",
                    "rotation",
                    "attributes",
                    "source",
                )
            }
        )
    canonical.sort(key=lambda item: (int(item.get("frame") or 0), int(item.get("label_id") or 0)))
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"))


__all__ = ["publish_autonomous_review_draft"]
