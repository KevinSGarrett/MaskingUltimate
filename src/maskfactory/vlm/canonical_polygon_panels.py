"""Materialize exact per-record evidence for canonical polygon source candidates."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

from ..nude_corpus_intake import (
    load_adopted_intake,
    load_records,
    rasterize_coco_segmentation,
)
from ..providers.disagreement import binary_mask_sha256
from .canonical_polygon_source_candidates import (
    sha256_file,
    verify_canonical_polygon_source_candidates,
)
from .critic_catalog import canonical_sha256

SCHEMA_VERSION = "maskfactory.canonical_polygon_candidate_panels.v1"
PANEL_NAMES = (
    "source",
    "binary_mask",
    "overlay",
    "contour",
    "full_context",
    "target_zoom",
)


class CanonicalPolygonPanelError(ValueError):
    """Candidate evidence cannot be resolved, rendered, or hash-verified."""


def _save_png(path: Path, value: np.ndarray) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "L" if value.ndim == 2 else "RGB"
    Image.fromarray(value, mode=mode).save(path, format="PNG", optimize=False, compress_level=9)
    return sha256_file(path)


def _focus_box(mask: np.ndarray) -> tuple[int, int, int, int]:
    rows, columns = np.nonzero(mask)
    if not len(rows):
        raise CanonicalPolygonPanelError("candidate mask is empty")
    x0, x1 = int(columns.min()), int(columns.max()) + 1
    y0, y1 = int(rows.min()), int(rows.max()) + 1
    extent = max(x1 - x0, y1 - y0)
    padding = max(24, int(round(extent * 0.75)))
    return (
        max(0, x0 - padding),
        max(0, y0 - padding),
        min(mask.shape[1], x1 + padding),
        min(mask.shape[0], y1 + padding),
    )


def render_candidate_panels(
    source_rgb: np.ndarray, mask: np.ndarray, output_dir: Path
) -> dict[str, Any]:
    """Render full-resolution evidence plus a legible target-focused zoom."""

    source = np.asarray(source_rgb)
    binary = np.asarray(mask).astype(bool)
    if (
        source.ndim != 3
        or source.shape[2] != 3
        or source.dtype != np.uint8
        or binary.shape != source.shape[:2]
    ):
        raise CanonicalPolygonPanelError("source and mask geometry are invalid")
    mask_u8 = binary.astype(np.uint8) * 255
    overlay = source.copy()
    overlay[binary] = np.clip(
        overlay[binary].astype(np.float32) * 0.45 + np.array([140, 0, 0]),
        0,
        255,
    ).astype(np.uint8)
    contour = source.copy()
    contours, _ = cv2.findContours(
        binary.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(contour, contours, -1, (255, 0, 0), 2)
    focus = _focus_box(binary)
    context = Image.fromarray(source.copy())
    draw = ImageDraw.Draw(context)
    draw.rectangle(focus, outline=(255, 255, 0), width=max(2, source.shape[1] // 512))
    context_rgb = np.asarray(context)
    x0, y0, x1, y1 = focus
    zoom = np.concatenate(
        (source[y0:y1, x0:x1], overlay[y0:y1, x0:x1], contour[y0:y1, x0:x1]),
        axis=1,
    )
    values = {
        "source": source,
        "binary_mask": mask_u8,
        "overlay": overlay,
        "contour": contour,
        "full_context": context_rgb,
        "target_zoom": zoom,
    }
    files: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for name in PANEL_NAMES:
        relative = Path("panels") / f"{name}.png"
        files[name] = relative.as_posix()
        hashes[name] = _save_png(output_dir / relative, values[name])
    return {
        "panel_files": files,
        "panel_sha256s": hashes,
        "panel_set_sha256": canonical_sha256(hashes),
        "focus_xyxy": list(focus),
    }


def _annotation_cache_entry(
    source_root: Path, annotation_ref: str
) -> tuple[dict[int, list[dict[str, Any]]], dict[int, str], str]:
    path = (source_root / annotation_ref).resolve(strict=True)
    try:
        path.relative_to(source_root)
    except ValueError as exc:
        raise CanonicalPolygonPanelError("annotation path escapes source root") from exc
    raw = path.read_bytes()
    document = json.loads(raw)
    by_image: dict[int, list[dict[str, Any]]] = {}
    for annotation in document.get("annotations", []):
        by_image.setdefault(int(annotation["image_id"]), []).append(annotation)
    categories = {
        int(row["id"]): str(row.get("name", row["id"])) for row in document.get("categories", [])
    }
    return by_image, categories, hashlib.sha256(raw).hexdigest()


def materialize_candidate_panels(
    *,
    intake_root: Path,
    candidate_document: Mapping[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    """Re-rasterize and render every selected source on persistent RunPod storage."""

    verify_canonical_polygon_source_candidates(candidate_document)
    output_root = Path(output_root)
    if output_root.exists():
        raise CanonicalPolygonPanelError("panel output already exists")
    intake = load_adopted_intake(intake_root, platform="runpod")
    records = load_records(intake)
    # The registry records Windows provenance as root; RunPod paths are bound
    # per record and used for source bytes. Annotation files resolve under the
    # persistent MaskedWarehouse mirror.
    runpod_source_root = Path("/workspace/assets/MaskedWarehouse/Nude")
    if not runpod_source_root.is_dir():
        raise CanonicalPolygonPanelError("RunPod MaskedWarehouse root is missing")
    stage = output_root.with_name(f".{output_root.name}.tmp-{uuid.uuid4().hex}")
    annotation_cache: dict[str, tuple[dict[int, list[dict[str, Any]]], dict[int, str], str]] = {}
    rows = []
    try:
        stage.mkdir(parents=True)
        for candidate in candidate_document["selected"]:
            sample_id = str(candidate["sample_id"])
            record = records.get(sample_id)
            if (
                record is None
                or record["source_sha256"] != candidate["source_sha256"]
                or record["annotation_ref"] != candidate["annotation_ref"]
            ):
                raise CanonicalPolygonPanelError(f"candidate source binding drift:{sample_id}")
            source_path = Path(str(record["source_path_runpod"]))
            if not source_path.is_file() or sha256_file(source_path) != candidate["source_sha256"]:
                raise CanonicalPolygonPanelError(f"source hash drift:{sample_id}")
            annotation_ref = str(candidate["annotation_ref"])
            if annotation_ref not in annotation_cache:
                annotation_cache[annotation_ref] = _annotation_cache_entry(
                    runpod_source_root, annotation_ref
                )
            by_image, categories, annotation_sha = annotation_cache[annotation_ref]
            if annotation_sha != candidate["annotation_file_sha256"]:
                raise CanonicalPolygonPanelError(f"annotation hash drift:{sample_id}")
            with Image.open(source_path) as opened:
                source = np.asarray(opened.convert("RGB"), dtype=np.uint8)
            matched = []
            for annotation in by_image.get(int(record["annotation_image_id"]), []):
                raw = categories.get(int(annotation.get("category_id", -1)), "").casefold()
                if raw != candidate["raw_label"]:
                    continue
                mask = rasterize_coco_segmentation(
                    annotation["segmentation"],
                    width=int(record["width"]),
                    height=int(record["height"]),
                )
                if binary_mask_sha256(mask) == candidate["mask_sha256"]:
                    matched.append(mask)
            if len(matched) != 1:
                raise CanonicalPolygonPanelError(
                    f"candidate annotation resolution is not exact:{sample_id}"
                )
            case_dir = stage / sample_id
            panels = render_candidate_panels(source, matched[0], case_dir)
            rows.append(
                {
                    **candidate,
                    "source_path_runpod": source_path.as_posix(),
                    "source_encoded_sha256_verified": True,
                    "annotation_file_sha256_verified": True,
                    "mask_raster_sha256_verified": True,
                    **panels,
                    "visual_alignment_reviewed": False,
                    "critic_positive_control_eligible": False,
                    "gold_or_production_authority": False,
                }
            )
        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": "canonical_polygon_source_visual_evidence",
            "authority_claimed": False,
            "visual_alignment_qualification_complete": False,
            "critic_positive_control_authority_granted": False,
            "candidate_set_sha256": candidate_document["self_sha256"],
            "nude_registry_sha256": intake["registry"]["self_sha256"],
            "record_count": len(rows),
            "panel_count": len(rows) * len(PANEL_NAMES),
            "panels_per_record": list(PANEL_NAMES),
            "records": rows,
            "next_required_stage": (
                "per_record_visual_alignment_review_and_immutable_"
                "positive_seeded_negative_case_construction"
            ),
            "claim_limits": [
                "Exact re-rasterization and panels do not qualify source semantics by themselves.",
                "Every case remains ineligible as a critic positive control until visual alignment is reviewed.",
                "No result is gold, production authority, a certificate, or training truth.",
            ],
        }
        report["self_sha256"] = canonical_sha256(report)
        (stage / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(stage, output_root)
        return report
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


__all__ = [
    "CanonicalPolygonPanelError",
    "materialize_candidate_panels",
    "render_candidate_panels",
]
