"""Conservative CPU boundary refinement for qualified adult-corpus polygons."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .nude_corpus_intake import (
    crosswalk_source_labels,
    load_adopted_intake,
    load_records,
    rasterize_coco_segmentation,
    representative_shards,
    validate_shard,
)

MIN_SOURCE_RETENTION = 0.70
MIN_SOURCE_IOU = 0.65
MIN_AREA_RATIO = 0.50
MAX_AREA_RATIO = 1.50
MAX_EDGE_EXPANSION_PX = 16


class NudePolygonRefinementError(ValueError):
    """A refinement input or boundary-safety invariant failed closed."""


def _mask_sha256(mask: np.ndarray) -> str:
    packed = np.packbits(mask.astype(bool), axis=None, bitorder="little").tobytes()
    return hashlib.sha256(packed).hexdigest()


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise NudePolygonRefinementError("mask_empty")
    return int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)


def refine_polygon_mask(
    image_rgb: np.ndarray, source_mask: np.ndarray, *, iterations: int = 3
) -> tuple[np.ndarray, dict[str, Any]]:
    """Refine one external polygon while rejecting excessive semantic drift."""

    image = np.asarray(image_rgb)
    source = np.asarray(source_mask).astype(bool)
    if image.ndim != 3 or image.shape[2] != 3 or image.shape[:2] != source.shape:
        raise NudePolygonRefinementError("image_mask_shape_mismatch")
    if image.dtype != np.uint8:
        raise NudePolygonRefinementError("image_dtype_must_be_uint8")
    if not isinstance(iterations, int) or isinstance(iterations, bool) or not 1 <= iterations <= 5:
        raise NudePolygonRefinementError("iterations_out_of_bounds")
    source_pixels = int(source.sum())
    if source_pixels < 16:
        raise NudePolygonRefinementError("source_mask_too_small")
    source_box = _bbox(source)
    kernel = np.ones((3, 3), np.uint8)
    eroded = cv2.erode(source.astype(np.uint8), kernel, iterations=1).astype(bool)
    dilated = cv2.dilate(source.astype(np.uint8), kernel, iterations=2).astype(bool)
    grabcut_mask = np.full(source.shape, cv2.GC_BGD, dtype=np.uint8)
    grabcut_mask[dilated] = cv2.GC_PR_BGD
    grabcut_mask[source] = cv2.GC_PR_FGD
    if eroded.any():
        grabcut_mask[eroded] = cv2.GC_FGD
    else:
        y, x = np.argwhere(source)[source_pixels // 2]
        grabcut_mask[y, x] = cv2.GC_FGD
    background_model = np.zeros((1, 65), np.float64)
    foreground_model = np.zeros((1, 65), np.float64)
    cv2.setRNGSeed(1337)
    try:
        cv2.grabCut(
            cv2.cvtColor(image, cv2.COLOR_RGB2BGR),
            grabcut_mask,
            None,
            background_model,
            foreground_model,
            iterations,
            cv2.GC_INIT_WITH_MASK,
        )
    except cv2.error as exc:
        raise NudePolygonRefinementError("grabcut_failed") from exc
    refined = np.isin(grabcut_mask, (cv2.GC_FGD, cv2.GC_PR_FGD))
    refined_pixels = int(refined.sum())
    if refined_pixels == 0:
        raise NudePolygonRefinementError("refined_mask_empty")
    intersection = int(np.logical_and(source, refined).sum())
    union = int(np.logical_or(source, refined).sum())
    retention = intersection / source_pixels
    iou = intersection / union
    area_ratio = refined_pixels / source_pixels
    refined_box = _bbox(refined)
    edge_expansion = max(
        source_box[0] - refined_box[0],
        source_box[1] - refined_box[1],
        refined_box[2] - source_box[2],
        refined_box[3] - source_box[3],
        0,
    )
    reasons = []
    if retention < MIN_SOURCE_RETENTION:
        reasons.append("source_retention_below_floor")
    if iou < MIN_SOURCE_IOU:
        reasons.append("source_iou_below_floor")
    if not MIN_AREA_RATIO <= area_ratio <= MAX_AREA_RATIO:
        reasons.append("area_ratio_out_of_bounds")
    if edge_expansion > MAX_EDGE_EXPANSION_PX:
        reasons.append("edge_expansion_out_of_bounds")
    source_sha256 = _mask_sha256(source)
    refined_sha256 = _mask_sha256(refined)
    report = {
        "schema_version": "maskfactory.nude_polygon_refinement.v1",
        "provider_id": "opencv_grabcut_polygon_seeded",
        "provider_family": "classical_graphcut",
        "provider_revision": cv2.__version__,
        "iterations": iterations,
        "source_mask_sha256": source_sha256,
        "refined_mask_sha256": refined_sha256,
        "source_pixels": source_pixels,
        "refined_pixels": refined_pixels,
        "changed_pixels": int(np.logical_xor(source, refined).sum()),
        "source_retention": retention,
        "source_iou": iou,
        "area_ratio": area_ratio,
        "maximum_edge_expansion_px": edge_expansion,
        "thresholds": {
            "minimum_source_retention": MIN_SOURCE_RETENTION,
            "minimum_source_iou": MIN_SOURCE_IOU,
            "minimum_area_ratio": MIN_AREA_RATIO,
            "maximum_area_ratio": MAX_AREA_RATIO,
            "maximum_edge_expansion_px": MAX_EDGE_EXPANSION_PX,
        },
        "outcome": (
            "rejected_excessive_drift"
            if reasons
            else ("no_progress" if source_sha256 == refined_sha256 else "draft_refined_candidate")
        ),
        "reasons": reasons,
        "authority": "deterministic_refiner_draft_only",
        "independent_provider_comparison_passed": False,
        "strict_visual_review_passed": False,
        "operational_certificate_eligible": False,
    }
    return refined, report


def _save_png(path: Path, image: np.ndarray) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(path, format="PNG")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _render_views(
    image: np.ndarray,
    source_mask: np.ndarray,
    refined_mask: np.ndarray,
    output_dir: Path,
) -> dict[str, dict[str, str]]:
    parent_mask_rgb = np.repeat((source_mask.astype(np.uint8) * 255)[..., None], 3, axis=2)
    mask_rgb = np.repeat((refined_mask.astype(np.uint8) * 255)[..., None], 3, axis=2)
    delta = np.zeros_like(image)
    removed = np.logical_and(source_mask, np.logical_not(refined_mask))
    added = np.logical_and(refined_mask, np.logical_not(source_mask))
    unchanged = np.logical_and(source_mask, refined_mask)
    delta[removed] = np.array([255, 0, 0], dtype=np.uint8)
    delta[added] = np.array([0, 255, 0], dtype=np.uint8)
    delta[unchanged] = np.array([255, 255, 255], dtype=np.uint8)
    overlay = image.copy()
    overlay[refined_mask] = np.clip(
        overlay[refined_mask].astype(np.float32) * 0.55 + np.array([115, 0, 0]), 0, 255
    ).astype(np.uint8)
    contour = image.copy()
    contours, _ = cv2.findContours(
        refined_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(contour, contours, -1, (255, 0, 0), 2)
    ownership_image = Image.fromarray(image.copy())
    draw = ImageDraw.Draw(ownership_image)
    source_box = _bbox(source_mask)
    refined_box = _bbox(refined_mask)
    draw.rectangle(source_box, outline=(255, 255, 0), width=2)
    draw.rectangle(refined_box, outline=(255, 0, 0), width=2)
    views = {
        "source": image,
        "mask": mask_rgb,
        "overlay": overlay,
        "contour": contour,
        "ownership": np.asarray(ownership_image),
    }
    result = {}
    for kind, value in views.items():
        path = output_dir / f"{kind}.png"
        result[kind] = {"path": str(path.resolve()), "sha256": _save_png(path, value)}
    panel = np.concatenate([views[kind] for kind in views], axis=1)
    panel_path = output_dir / "five_view_panel.png"
    result["five_view_panel"] = {
        "path": str(panel_path.resolve()),
        "sha256": _save_png(panel_path, panel),
    }
    for kind, value in {"parent_mask": parent_mask_rgb, "delta": delta}.items():
        path = output_dir / f"{kind}.png"
        result[kind] = {"path": str(path.resolve()), "sha256": _save_png(path, value)}
    comparison = np.concatenate(
        [image, parent_mask_rgb, mask_rgb, overlay, contour, np.asarray(ownership_image), delta],
        axis=1,
    )
    comparison_path = output_dir / "parent_refined_comparison_panel.png"
    result["parent_refined_comparison_panel"] = {
        "path": str(comparison_path.resolve()),
        "sha256": _save_png(comparison_path, comparison),
    }
    return result


def run_polygon_refinement_canary(
    intake_root: Path,
    output_dir: Path,
    *,
    split_mapping_path: Path,
    limit: int = 12,
) -> dict[str, Any]:
    """Run real-image draft refinement on the representative polygon shard."""

    if not 1 <= limit <= 64:
        raise NudePolygonRefinementError("canary_limit_out_of_bounds")
    intake = load_adopted_intake(intake_root, platform="local")
    records = load_records(intake)
    shard_path = representative_shards(intake)["polygon_external_supervision"]
    shard = validate_shard(
        shard_path, expected_lane="polygon_external_supervision", platform="local"
    )
    shard_ids = {str(sample["sample_id"]) for sample in shard["samples"]}
    split_groups = {}
    with Path(split_mapping_path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            split = json.loads(line)
            sample_id = str(split.get("sample_id"))
            if sample_id in shard_ids:
                split_groups[sample_id] = str(split.get("split_group_id"))
    if set(split_groups) != shard_ids:
        raise NudePolygonRefinementError("canary_split_group_bindings_incomplete")
    source_root = Path(intake["registry"]["root"]).resolve()
    annotation_cache: dict[str, tuple[dict[int, list[dict[str, Any]]], dict[int, str]]] = {}
    outcomes: Counter[str] = Counter()
    rows = []
    used_groups = set()
    for sample in shard["samples"]:
        if len(rows) >= limit:
            break
        sample_id = str(sample["sample_id"])
        split_group_id = split_groups[sample_id]
        if split_group_id in used_groups:
            continue
        record = records[sample_id]
        annotation_ref = str(record.get("annotation_ref") or "")
        if not annotation_ref:
            continue
        if annotation_ref not in annotation_cache:
            document = json.loads((source_root / annotation_ref).read_text(encoding="utf-8"))
            by_image: dict[int, list[dict[str, Any]]] = {}
            for annotation in document.get("annotations", []):
                by_image.setdefault(int(annotation["image_id"]), []).append(annotation)
            categories = {
                int(category["id"]): str(category.get("name", category["id"]))
                for category in document.get("categories", [])
            }
            annotation_cache[annotation_ref] = by_image, categories
        by_image, categories = annotation_cache[annotation_ref]
        annotations = by_image.get(int(record["annotation_image_id"]), [])
        image_path = (source_root / str(record["source_relative_path"])).resolve()
        image = np.asarray(Image.open(image_path).convert("RGB"))
        selected = None
        for annotation in annotations:
            raw_label = categories.get(int(annotation.get("category_id", -1)), "")
            mapped, actions, unmapped = crosswalk_source_labels((raw_label,), intake["crosswalk"])
            if (
                actions
                or unmapped
                or len(mapped) != 1
                or str(mapped[0]["kind"]).startswith("context_")
            ):
                continue
            if not annotation.get("segmentation"):
                continue
            source_mask = rasterize_coco_segmentation(
                annotation["segmentation"], width=image.shape[1], height=image.shape[0]
            )
            try:
                refined, refinement = refine_polygon_mask(image, source_mask)
            except NudePolygonRefinementError:
                continue
            selected = (raw_label, mapped[0]["candidate_label"], source_mask, refined, refinement)
            break
        if selected is None:
            continue
        raw_label, candidate_label, source_mask, refined, refinement = selected
        case_dir = output_dir / sample_id
        views = _render_views(image, source_mask, refined, case_dir)
        outcomes[refinement["outcome"]] += 1
        used_groups.add(split_group_id)
        rows.append(
            {
                "sample_id": sample_id,
                "source_sha256": record["source_sha256"],
                "source_path": str(image_path),
                "split_group_id": split_group_id,
                "raw_label": raw_label,
                "candidate_label": candidate_label,
                "refinement": refinement,
                "views": views,
                "ownership_binding": "source_annotation_localization_only_no_person_instance_authority",
            }
        )
    if len(rows) != limit:
        raise NudePolygonRefinementError("insufficient_refinable_canary_records")
    contact_tiles = []
    for row in rows:
        panel_path = Path(row["views"]["parent_refined_comparison_panel"]["path"])
        with Image.open(panel_path) as opened:
            tile = opened.convert("RGB")
            tile.thumbnail((1400, 220), Image.Resampling.LANCZOS)
            contact_tiles.append(tile.copy())
    contact_width = max(tile.width for tile in contact_tiles)
    contact_height = sum(tile.height for tile in contact_tiles)
    contact = Image.new("RGB", (contact_width, contact_height), color=(16, 16, 16))
    y = 0
    for tile in contact_tiles:
        contact.paste(tile, (0, y))
        y += tile.height
    output_dir.mkdir(parents=True, exist_ok=True)
    contact_path = output_dir / "parent_refined_contact_sheet.png"
    contact.save(contact_path, format="PNG")
    contact_sha256 = hashlib.sha256(contact_path.read_bytes()).hexdigest()
    report = {
        "schema_version": "maskfactory.nude_polygon_refinement_canary.v1",
        "artifact_type": "adult_polygon_cpu_boundary_refinement_canary",
        "status": "PASS_BOUNDED_DRAFT_REFINEMENT",
        "registry_sha256": intake["registry"]["self_sha256"],
        "shard_sha256": shard["self_sha256"],
        "record_count": len(rows),
        "unique_split_group_count": len(used_groups),
        "split_mapping_file_sha256": hashlib.sha256(
            Path(split_mapping_path).read_bytes()
        ).hexdigest(),
        "outcome_counts": dict(sorted(outcomes.items())),
        "contact_sheet": {
            "path": str(contact_path.resolve()),
            "sha256": contact_sha256,
            "scheduling_aid_only": True,
            "per_record_review_still_required": True,
        },
        "records": rows,
        "authority": {
            "draft_only": True,
            "external_polygon_overwritten": False,
            "person_instance_ownership_verified": False,
            "independent_provider_comparison_passed": False,
            "strict_visual_review_passed": False,
            "operational_certificates_issued": False,
        },
    }
    report["self_sha256"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


__all__ = [
    "NudePolygonRefinementError",
    "refine_polygon_mask",
    "run_polygon_refinement_canary",
]
