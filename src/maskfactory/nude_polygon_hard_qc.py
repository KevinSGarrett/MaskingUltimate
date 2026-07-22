"""Deterministic full-corpus hard QC for external adult-anatomy COCO polygons."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .nude_corpus_dedup import load_group_evidence
from .nude_corpus_intake import (
    NudeCorpusIntakeError,
    crosswalk_source_labels,
    load_adopted_intake,
    load_records,
    rasterize_coco_segmentation,
)
from .providers.disagreement import binary_mask_sha256

MIN_MASK_BBOX_IOU = 0.90
MAX_MASK_BBOX_EDGE_DELTA_PX = 1.5


class NudePolygonQcError(RuntimeError):
    """A corpus-level identity, mapping, or annotation invariant failed closed."""


def _bbox_iou(first: Sequence[float], second: Sequence[float]) -> float:
    left = max(float(first[0]), float(second[0]))
    top = max(float(first[1]), float(second[1]))
    right = min(float(first[2]), float(second[2]))
    bottom = min(float(first[3]), float(second[3]))
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, float(first[2]) - float(first[0])) * max(
        0.0, float(first[3]) - float(first[1])
    )
    second_area = max(0.0, float(second[2]) - float(second[0])) * max(
        0.0, float(second[3]) - float(second[1])
    )
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def evaluate_polygon_annotation(
    annotation: Mapping[str, Any],
    *,
    raw_label: str,
    width: int,
    height: int,
    crosswalk: Mapping[str, Any],
) -> dict[str, Any]:
    """Materialize one mask and retain raw/coarse/fine meaning without promotion."""

    mapped, actions, unmapped = crosswalk_source_labels((raw_label,), crosswalk)
    if actions:
        raise NudePolygonQcError("action_or_scene_label_cannot_be_polygon_truth")
    if unmapped or len(mapped) != 1:
        raise NudePolygonQcError("polygon_label_unmapped")
    if str(mapped[0]["kind"]).startswith("context_"):
        raise NudePolygonQcError("non_anatomy_context_cannot_be_polygon_truth")
    try:
        mask = rasterize_coco_segmentation(
            annotation.get("segmentation"), width=width, height=height
        )
    except NudeCorpusIntakeError as exc:
        raise NudePolygonQcError(str(exc)) from exc
    segmentation_encoding = (
        "coco_rle" if isinstance(annotation.get("segmentation"), dict) else "coco_polygon"
    )
    source_annotation_area: float | None = None
    source_annotation_area_matches: bool | None = None
    if segmentation_encoding == "coco_rle":
        annotated_area = annotation.get("area")
        if isinstance(annotated_area, (int, float)) and not isinstance(annotated_area, bool):
            source_annotation_area = float(annotated_area)
            if math.isfinite(source_annotation_area):
                source_annotation_area_matches = int(mask.sum()) == int(
                    round(source_annotation_area)
                )
    bbox = annotation.get("bbox")
    if (
        not isinstance(bbox, list)
        or len(bbox) != 4
        or any(
            not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in bbox
        )
        or float(bbox[2]) <= 0
        or float(bbox[3]) <= 0
    ):
        raise NudePolygonQcError("annotation_bbox_invalid")
    x, y, box_width, box_height = (float(value) for value in bbox)
    if x < -0.5 or y < -0.5 or x + box_width > width + 0.5 or y + box_height > height + 0.5:
        raise NudePolygonQcError("annotation_bbox_invalid")
    expected = (x, y, x + box_width, y + box_height)
    ys, xs = np.nonzero(mask)
    observed = (float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1))
    bbox_iou = _bbox_iou(expected, observed)
    maximum_edge_delta = max(abs(first - second) for first, second in zip(expected, observed))
    if bbox_iou < MIN_MASK_BBOX_IOU and maximum_edge_delta > MAX_MASK_BBOX_EDGE_DELTA_PX:
        raise NudePolygonQcError("polygon_bbox_alignment_failed")
    return {
        "raw_label": raw_label,
        "candidate_label": mapped[0]["candidate_label"],
        "candidate_kind": mapped[0]["kind"],
        "mask_sha256": binary_mask_sha256(mask),
        "mask_pixels": int(mask.sum()),
        "mask_bbox_xyxy": list(observed),
        "annotation_bbox_xyxy": list(expected),
        "bbox_iou": bbox_iou,
        "maximum_bbox_edge_delta_px": maximum_edge_delta,
        "bbox_alignment_method": (
            "iou" if bbox_iou >= MIN_MASK_BBOX_IOU else "raster_quantization_edge_tolerance"
        ),
        "binary_mask_materialized": True,
        "segmentation_encoding": segmentation_encoding,
        "source_annotation_area": source_annotation_area,
        "source_annotation_area_matches_decoded_mask": source_annotation_area_matches,
        "production_authority": False,
        "gold_authority": False,
    }


def run_full_polygon_hard_qc(
    intake_root: Path,
    *,
    split_summary: Path,
    split_mapping: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    intake = load_adopted_intake(intake_root, platform="local")
    records = load_records(intake)
    split_groups = load_group_evidence(split_summary, split_mapping)
    source_root = Path(intake["registry"]["root"])
    selected = [
        record
        for record in records.values()
        if record.get("source_role") == "polygon_external_supervision"
    ]
    selected.sort(key=lambda record: str(record["sample_id"]))
    annotation_cache: dict[str, tuple[dict[int, list[dict[str, Any]]], dict[int, str], str]] = {}
    output: list[dict[str, Any]] = []
    outcomes: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    encodings: Counter[str] = Counter()
    advisories: Counter[str] = Counter()
    mask_count = 0
    mask_pixels = 0
    minimum_bbox_iou = 1.0
    for record in selected:
        sample_id = str(record["sample_id"])
        split = split_groups.get(sample_id)
        if split is None or split["source_sha256"] != record["source_sha256"]:
            raise NudePolygonQcError(f"split_group_binding_invalid:{sample_id}")
        annotation_ref = str(record.get("annotation_ref") or "")
        if not annotation_ref:
            annotations: list[dict[str, Any]] = []
            categories: dict[int, str] = {}
            annotation_sha = ""
        else:
            if annotation_ref not in annotation_cache:
                path = (source_root / Path(annotation_ref)).resolve(strict=True)
                try:
                    path.relative_to(source_root)
                except ValueError as exc:
                    raise NudePolygonQcError("annotation path escaped source root") from exc
                raw = path.read_bytes()
                document = json.loads(raw)
                by_image: dict[int, list[dict[str, Any]]] = {}
                for annotation in document.get("annotations", []):
                    by_image.setdefault(int(annotation["image_id"]), []).append(annotation)
                categories = {
                    int(row["id"]): str(row.get("name", row["id"]))
                    for row in document.get("categories", [])
                }
                annotation_cache[annotation_ref] = (
                    by_image,
                    categories,
                    hashlib.sha256(raw).hexdigest(),
                )
            by_image, categories, annotation_sha = annotation_cache[annotation_ref]
            annotations = by_image.get(int(record["annotation_image_id"]), [])
        record_reasons: list[str] = []
        masks: list[dict[str, Any]] = []
        if len(annotations) != int(record.get("annotation_count") or 0) or not annotations:
            record_reasons.append("polygon_annotation_missing_or_count_mismatch")
        else:
            for annotation in annotations:
                raw_label = categories.get(int(annotation.get("category_id", -1)))
                if raw_label is None:
                    record_reasons.append("polygon_category_unknown")
                    continue
                try:
                    result = evaluate_polygon_annotation(
                        annotation,
                        raw_label=raw_label,
                        width=int(record["width"]),
                        height=int(record["height"]),
                        crosswalk=intake["crosswalk"],
                    )
                except NudePolygonQcError as exc:
                    record_reasons.append(str(exc))
                    continue
                masks.append(result)
                mask_count += 1
                mask_pixels += int(result["mask_pixels"])
                minimum_bbox_iou = min(minimum_bbox_iou, float(result["bbox_iou"]))
                labels[result["candidate_label"]] += 1
                encodings[result["segmentation_encoding"]] += 1
                if result["source_annotation_area_matches_decoded_mask"] is False:
                    advisories["source_annotation_area_drift"] += 1
        masks_by_hash: dict[str, list[dict[str, Any]]] = {}
        for mask in masks:
            masks_by_hash.setdefault(str(mask["mask_sha256"]), []).append(mask)
        for duplicates in masks_by_hash.values():
            if len(duplicates) < 2:
                continue
            duplicate_labels = {str(mask["candidate_label"]) for mask in duplicates}
            record_reasons.append(
                "cross_label_mask_collapse"
                if len(duplicate_labels) > 1
                else "duplicate_annotation_mask"
            )
        outcome = "hard_qc_pass_candidate" if not record_reasons and masks else "quarantined_input"
        outcomes[outcome] += 1
        reasons.update(record_reasons)
        output.append(
            {
                "sample_id": sample_id,
                "dataset_id": record["dataset_id"],
                "source_role": record["source_role"],
                "source_sha256": record["source_sha256"],
                "annotation_ref": annotation_ref,
                "annotation_file_sha256": annotation_sha,
                "split_group_id": split["split_group_id"],
                "assigned_partition": split["assigned_partition"],
                "outcome": outcome,
                "reasons": sorted(set(record_reasons)),
                "masks": masks,
                "external_mask_authority": "machine_hard_qc_candidate_only",
                "strict_visual_review_passed": False,
                "operational_certificate_eligible": False,
            }
        )
    summary = {
        "schema_version": "maskfactory.nude_polygon_hard_qc.v3",
        "artifact_type": "nude_polygon_full_corpus_hard_qc_summary",
        "status": "PASS_BOUNDED_HARD_QC",
        "registry_sha256": intake["registry"]["self_sha256"],
        "crosswalk_override_sha256": intake["crosswalk_override_sha256"],
        "split_mapping_sha256": hashlib.sha256(Path(split_mapping).read_bytes()).hexdigest(),
        "record_count": len(output),
        "mask_count": mask_count,
        "mask_pixels": mask_pixels,
        "minimum_passing_bbox_iou": minimum_bbox_iou if mask_count else None,
        "outcome_counts": dict(sorted(outcomes.items())),
        "failure_reason_counts": dict(sorted(reasons.items())),
        "candidate_label_counts": dict(sorted(labels.items())),
        "segmentation_encoding_counts": dict(sorted(encodings.items())),
        "advisory_counts": dict(sorted(advisories.items())),
        "hard_qc": {
            "binary_materialization_required": True,
            "decoded_mask_area_recomputed_from_pixels": True,
            "source_annotation_area_is_advisory": True,
            "mask_bbox_iou_minimum": MIN_MASK_BBOX_IOU,
            "mask_bbox_edge_tolerance_px": MAX_MASK_BBOX_EDGE_DELTA_PX,
            "bbox_rule": "iou_at_least_minimum_or_all_edges_within_quantization_tolerance",
            "raw_label_preserved": True,
            "action_scene_as_pixel_mask_rejected": True,
            "unmapped_label_rejected": True,
        },
        "authority": {
            "human_gold_granted": False,
            "production_mask_authority_granted": False,
            "strict_visual_qa_completed": False,
            "operational_certificates_issued": False,
        },
    }
    return output, summary


def write_polygon_qc_evidence(
    records: Sequence[Mapping[str, Any]], summary: Mapping[str, Any], output_dir: Path
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    records_path = output_dir / "records.jsonl"
    with records_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(
                json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
            )
    result = dict(summary)
    result["records_file_sha256"] = hashlib.sha256(records_path.read_bytes()).hexdigest()
    result["records_path"] = str(records_path.resolve())
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    result["self_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    (output_dir / "summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


__all__ = [
    "MIN_MASK_BBOX_IOU",
    "MAX_MASK_BBOX_EDGE_DELTA_PX",
    "NudePolygonQcError",
    "evaluate_polygon_annotation",
    "run_full_polygon_hard_qc",
    "write_polygon_qc_evidence",
]
