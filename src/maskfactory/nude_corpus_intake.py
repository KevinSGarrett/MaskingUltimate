"""Fail-closed intake and representative canary checks for the adult corpus.

The external intake package is durable source memory, not production authority.
This module binds its adopted starting seals, validates lane semantics, decodes
real source pixels, rasterizes COCO polygons, and keeps boxes, action tags,
references, and holdout records in their distinct evidence roles.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image, ImageDraw, UnidentifiedImageError

ADOPTED_REGISTRY_SHA256 = "785bfbcca98262a00519b53a360a67d22f23ec9e4b41c9bc38029f402eb9bbcf"
ADOPTED_SHARD_INDEX_SHA256 = "16a958ffdc6c304174fa8ff5b9b656a607e8e8a9e9610dac9be4a8dbff3c994a"
ADOPTED_DATASET_COUNT = 16
ADOPTED_RECORD_COUNT = 81_910
ADOPTED_SHARDS_PER_PLATFORM = 322

LANES = (
    "bbox_evaluation_only",
    "bbox_prompt_and_action_tag_supervision",
    "bbox_prompt_supervision",
    "polygon_external_supervision",
    "reference_and_tournament_input",
)
PIXEL_LANES = frozenset({"polygon_external_supervision"})
BBOX_LANES = frozenset(
    {
        "bbox_evaluation_only",
        "bbox_prompt_and_action_tag_supervision",
        "bbox_prompt_supervision",
    }
)
REFERENCE_LANES = frozenset({"reference_and_tournament_input"})
ACTION_KINDS = frozenset({"scene", "action", "object", "visual_tag"})
FINE_LABELS_NOT_INFERRED_FROM_COARSE = frozenset(
    {
        "left_breast",
        "right_breast",
        "left_areola",
        "right_areola",
        "left_nipple",
        "right_nipple",
        "penis_shaft",
        "penis_glans",
        "left_scrotal_region",
        "right_scrotal_region",
        "left_buttock",
        "right_buttock",
    }
)


class NudeCorpusIntakeError(ValueError):
    """The intake, a source record, or its annotation failed closed."""


def canonical_sha256(document: Mapping[str, Any]) -> str:
    payload = dict(document)
    payload.pop("self_sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NudeCorpusIntakeError(f"json_load_failed:{path.name}:{exc}") from exc
    if not isinstance(document, dict):
        raise NudeCorpusIntakeError(f"json_root_invalid:{path.name}")
    return document


def _safe_relative(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise NudeCorpusIntakeError("relative_path_invalid")
    candidate = (root / Path(relative)).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise NudeCorpusIntakeError(f"relative_path_escape:{relative}") from exc
    if candidate.is_symlink() or not candidate.is_file():
        raise NudeCorpusIntakeError(f"regular_file_required:{relative}")
    return candidate


def load_adopted_intake(intake_root: Path, *, platform: str = "local") -> dict[str, Any]:
    """Load and bind the complete supplied registry/index at the adopted seals."""

    if platform not in {"local", "runpod"}:
        raise NudeCorpusIntakeError("platform_invalid")
    intake = Path(intake_root).resolve(strict=True)
    policy = _load_json(intake / "dataset_policy.json")
    crosswalk = _load_json(intake / "ontology_crosswalk.json")
    batch_policy = _load_json(intake / "batch_policy.json")
    registry = _load_json(intake / "dataset_registry.generated.json")
    index = _load_json(intake / "batch_shards" / "_index.json")
    for document, expected, name in (
        (registry, ADOPTED_REGISTRY_SHA256, "registry"),
        (index, ADOPTED_SHARD_INDEX_SHA256, "shard_index"),
    ):
        if canonical_sha256(document) != document.get("self_sha256"):
            raise NudeCorpusIntakeError(f"{name}_self_hash_mismatch")
        if document["self_sha256"] != expected:
            raise NudeCorpusIntakeError(f"{name}_adopted_lineage_drift")
    if (
        len(registry.get("datasets", [])) != ADOPTED_DATASET_COUNT
        or registry.get("record_count") != ADOPTED_RECORD_COUNT
        or index.get("record_count") != ADOPTED_RECORD_COUNT
    ):
        raise NudeCorpusIntakeError("adopted_count_drift")
    descriptors = index.get("shards")
    if not isinstance(descriptors, list):
        raise NudeCorpusIntakeError("shard_descriptors_invalid")
    platform_descriptors = [row for row in descriptors if row.get("platform") == platform]
    if len(platform_descriptors) != ADOPTED_SHARDS_PER_PLATFORM:
        raise NudeCorpusIntakeError("platform_shard_count_drift")
    if set(policy.get("datasets", {})) != {
        str(row.get("folder_name")) for row in registry["datasets"]
    }:
        raise NudeCorpusIntakeError("dataset_policy_registry_drift")
    return {
        "intake_root": intake,
        "policy": policy,
        "crosswalk": crosswalk,
        "batch_policy": batch_policy,
        "registry": registry,
        "index": index,
        "platform_descriptors": platform_descriptors,
    }


def load_records(intake: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    path = intake["intake_root"] / str(intake["registry"]["records_file"])
    records: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise NudeCorpusIntakeError(f"record_json_invalid:{line_number}") from exc
            sample_id = row.get("sample_id")
            if not isinstance(sample_id, str) or sample_id in records:
                raise NudeCorpusIntakeError(f"record_identity_invalid:{line_number}")
            records[sample_id] = row
    if len(records) != ADOPTED_RECORD_COUNT:
        raise NudeCorpusIntakeError("records_count_drift")
    return records


def build_project_registry_manifest(intake: Mapping[str, Any]) -> dict[str, Any]:
    """Embed every supplied dataset row while binding the governing intake files."""

    root = Path(intake["intake_root"])
    registry = intake["registry"]
    datasets = registry.get("datasets")
    if not isinstance(datasets, list) or len(datasets) != ADOPTED_DATASET_COUNT:
        raise NudeCorpusIntakeError("project_registry_dataset_count_drift")
    required = {
        "dataset_id",
        "path",
        "annotation_format",
        "annotation_files",
        "source_url",
        "license_claim",
        "lineage_group",
        "primary_role",
        "record_count",
        "version_policy",
    }
    for row in datasets:
        if not isinstance(row, dict) or required - set(row):
            raise NudeCorpusIntakeError("project_registry_dataset_fields_missing")
    manifest: dict[str, Any] = {
        "schema_version": "maskfactory.nude_corpus_registry_adoption.v1",
        "artifact_type": "governed_external_corpus_registry",
        "authority": {
            "source_labels_preserved": True,
            "external_annotations_are_human_gold": False,
            "downloaded_masks_are_production_authority": False,
            "reference_images_are_pixel_truth": False,
        },
        "adopted_source": {
            "registry_sha256": registry["self_sha256"],
            "shard_index_sha256": intake["index"]["self_sha256"],
            "dataset_policy_file_sha256": sha256_file(root / "dataset_policy.json"),
            "ontology_crosswalk_file_sha256": sha256_file(root / "ontology_crosswalk.json"),
            "batch_policy_file_sha256": sha256_file(root / "batch_policy.json"),
        },
        "dataset_count": len(datasets),
        "record_count": registry["record_count"],
        "role_counts": registry.get("role_counts"),
        "datasets": sorted(datasets, key=lambda row: str(row["dataset_id"])),
    }
    manifest["self_sha256"] = canonical_sha256(manifest)
    return manifest


def representative_shards(intake: Mapping[str, Any]) -> dict[str, Path]:
    """Return exactly the first deterministic shard from every governed lane."""

    selected: dict[str, Path] = {}
    root = intake["intake_root"] / "batch_shards"
    for descriptor in intake["platform_descriptors"]:
        lane = descriptor.get("lane")
        if lane in LANES and lane not in selected:
            selected[lane] = _safe_relative(root, str(descriptor.get("path")))
    if set(selected) != set(LANES):
        raise NudeCorpusIntakeError("representative_lane_missing")
    return selected


def validate_shard(path: Path, *, expected_lane: str, platform: str) -> dict[str, Any]:
    shard = _load_json(path)
    if (
        shard.get("schema_version") != "maskfactory.nude_batch_shard.v1"
        or shard.get("artifact_type") != "tournament_sample_set"
        or shard.get("batch_lane") != expected_lane
        or shard.get("platform") != platform
        or canonical_sha256(shard) != shard.get("self_sha256")
    ):
        raise NudeCorpusIntakeError(f"shard_contract_invalid:{path.name}")
    samples = shard.get("samples")
    ordered = shard.get("ordered_sample_ids")
    if (
        not isinstance(samples, list)
        or not isinstance(ordered, list)
        or shard.get("sample_count") != len(samples)
        or ordered != [row.get("sample_id") for row in samples]
        or len(ordered) != len(set(ordered))
    ):
        raise NudeCorpusIntakeError(f"shard_coverage_invalid:{path.name}")
    return shard


def rasterize_coco_segmentation(segmentation: Any, *, width: int, height: int) -> np.ndarray:
    """Rasterize COCO polygon arrays without interpreting boxes as masks."""

    if width < 1 or height < 1:
        raise NudeCorpusIntakeError("polygon_canvas_invalid")
    if not isinstance(segmentation, list) or not segmentation:
        raise NudeCorpusIntakeError("polygon_segmentation_required")
    canvas = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(canvas)
    polygon_count = 0
    for polygon in segmentation:
        if (
            not isinstance(polygon, list)
            or len(polygon) < 6
            or len(polygon) % 2
            or any(not isinstance(value, (int, float)) for value in polygon)
            or any(not math.isfinite(float(value)) for value in polygon)
        ):
            raise NudeCorpusIntakeError("polygon_coordinates_invalid")
        points = [(float(polygon[i]), float(polygon[i + 1])) for i in range(0, len(polygon), 2)]
        if any(x < -0.5 or y < -0.5 or x > width + 0.5 or y > height + 0.5 for x, y in points):
            raise NudeCorpusIntakeError("polygon_coordinates_out_of_bounds")
        draw.polygon(points, fill=1)
        polygon_count += 1
    mask = np.asarray(canvas, dtype=bool)
    if polygon_count < 1 or not mask.any():
        raise NudeCorpusIntakeError("polygon_raster_empty")
    return mask


def _valid_bbox(bbox: Any, *, width: int, height: int) -> bool:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return False
    if any(
        not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in bbox
    ):
        return False
    x, y, box_width, box_height = (float(value) for value in bbox)
    return (
        box_width > 0
        and box_height > 0
        and x >= -0.5
        and y >= -0.5
        and x + box_width <= width + 0.5
        and y + box_height <= height + 0.5
    )


def _crosswalk_labels(
    labels: Sequence[str], crosswalk: Mapping[str, Any]
) -> tuple[list[dict[str, str]], list[str], list[str]]:
    anatomy = crosswalk.get("anatomy_aliases", {})
    actions = crosswalk.get("scene_and_action_labels", {})
    mapped: list[dict[str, str]] = []
    action_tags: list[str] = []
    unmapped: list[str] = []
    for raw in labels:
        if raw in anatomy:
            entry = anatomy[raw]
            canonical = str(entry.get("canonical_candidate"))
            if canonical in FINE_LABELS_NOT_INFERRED_FROM_COARSE:
                raise NudeCorpusIntakeError(f"fine_label_invented_from_coarse:{raw}:{canonical}")
            mapped.append(
                {"raw_label": raw, "candidate_label": canonical, "kind": str(entry["kind"])}
            )
        elif raw in actions:
            action_tags.append(str(actions[raw]))
        else:
            unmapped.append(raw)
    return mapped, action_tags, unmapped


def run_representative_canary(
    intake_root: Path,
    *,
    platform: str = "local",
    verify_source_hashes: bool = True,
) -> dict[str, Any]:
    """Validate one complete deterministic shard from each evidence lane."""

    intake = load_adopted_intake(intake_root, platform=platform)
    records = load_records(intake)
    selected = representative_shards(intake)
    source_root = Path(intake["registry"]["root"]).resolve(strict=True)
    annotation_cache: dict[str, tuple[dict[int, list[dict[str, Any]]], dict[int, str]]] = {}
    lane_reports: list[dict[str, Any]] = []
    total_outcomes: Counter[str] = Counter()
    for lane in LANES:
        shard = validate_shard(selected[lane], expected_lane=lane, platform=platform)
        counters: Counter[str] = Counter()
        raw_unmapped: Counter[str] = Counter()
        action_counts: Counter[str] = Counter()
        candidate_labels: Counter[str] = Counter()
        exception_counts: Counter[str] = Counter()
        exceptions: list[dict[str, str]] = []
        for sample in shard["samples"]:
            sample_id = str(sample["sample_id"])
            record = records.get(sample_id)
            if record is None or record.get("source_role") != lane:
                raise NudeCorpusIntakeError(f"sample_record_binding_invalid:{sample_id}")
            if sample.get("source_sha256") != record.get("source_sha256"):
                raise NudeCorpusIntakeError(f"sample_hash_binding_invalid:{sample_id}")
            relative = str(record["source_relative_path"])
            source_path = _safe_relative(source_root, relative)
            if verify_source_hashes and sha256_file(source_path) != record["source_sha256"]:
                raise NudeCorpusIntakeError(f"source_hash_mismatch:{sample_id}")
            try:
                with Image.open(source_path) as opened:
                    opened.verify()
                with Image.open(source_path) as opened:
                    width, height = opened.size
                    opened.convert("RGB").load()
            except (OSError, UnidentifiedImageError) as exc:
                raise NudeCorpusIntakeError(f"source_decode_failed:{sample_id}") from exc
            if record.get("width") not in {None, width} or record.get("height") not in {
                None,
                height,
            }:
                raise NudeCorpusIntakeError(f"source_dimension_mismatch:{sample_id}")
            counters["decoded"] += 1
            mapped, actions, unmapped = _crosswalk_labels(
                tuple(str(value) for value in record.get("source_labels", [])),
                intake["crosswalk"],
            )
            candidate_labels.update(row["candidate_label"] for row in mapped)
            action_counts.update(actions)
            raw_unmapped.update(unmapped)

            annotation_ref = record.get("annotation_ref")
            annotations: list[dict[str, Any]] = []
            categories: dict[int, str] = {}
            if annotation_ref:
                if annotation_ref not in annotation_cache:
                    annotation_path = _safe_relative(source_root, str(annotation_ref))
                    document = _load_json(annotation_path)
                    by_image: dict[int, list[dict[str, Any]]] = {}
                    for annotation in document.get("annotations", []):
                        by_image.setdefault(int(annotation["image_id"]), []).append(annotation)
                    categories = {
                        int(row["id"]): str(row.get("name", row["id"]))
                        for row in document.get("categories", [])
                    }
                    annotation_cache[str(annotation_ref)] = (by_image, categories)
                by_image, categories = annotation_cache[str(annotation_ref)]
                annotations = by_image.get(int(record["annotation_image_id"]), [])
                if len(annotations) != int(record["annotation_count"]):
                    raise NudeCorpusIntakeError(f"annotation_count_mismatch:{sample_id}")

            if lane in PIXEL_LANES:
                if not annotations:
                    reason = "polygon_annotation_missing"
                    counters["quarantined_input"] += 1
                    exception_counts[reason] += 1
                    exceptions.append({"sample_id": sample_id, "reason": reason})
                    total_outcomes["quarantined_input"] += 1
                    continue
                polygons_this_record = 0
                invalid_polygon = False
                for annotation in annotations:
                    segmentation = annotation.get("segmentation")
                    if not segmentation:
                        continue
                    try:
                        mask = rasterize_coco_segmentation(segmentation, width=width, height=height)
                    except NudeCorpusIntakeError as exc:
                        reason = str(exc)
                        exception_counts[reason] += 1
                        exceptions.append({"sample_id": sample_id, "reason": reason})
                        invalid_polygon = True
                        break
                    counters["polygon_annotations"] += 1
                    counters["polygon_pixels"] += int(mask.sum())
                    polygons_this_record += 1
                if invalid_polygon or polygons_this_record < 1:
                    counters["quarantined_input"] += 1
                    if not invalid_polygon:
                        reason = "polygon_annotation_missing"
                        exception_counts[reason] += 1
                        exceptions.append({"sample_id": sample_id, "reason": reason})
                    total_outcomes["quarantined_input"] += 1
                    continue
                outcome = "qualified_input_candidate"
            elif lane in BBOX_LANES:
                invalid_bbox = False
                for annotation in annotations:
                    if not _valid_bbox(annotation.get("bbox"), width=width, height=height):
                        invalid_bbox = True
                        break
                    raw_label = categories.get(int(annotation["category_id"]), "unknown")
                    if raw_label in intake["crosswalk"].get("scene_and_action_labels", {}):
                        counters["action_scene_boxes_not_pixel_masks"] += 1
                    else:
                        counters["bbox_prompts"] += 1
                if invalid_bbox:
                    reason = "bbox_invalid"
                    counters["quarantined_input"] += 1
                    exception_counts[reason] += 1
                    exceptions.append({"sample_id": sample_id, "reason": reason})
                    total_outcomes["quarantined_input"] += 1
                    continue
                outcome = (
                    "holdout_only" if lane == "bbox_evaluation_only" else "prompt_ready_candidate"
                )
            else:
                if annotations or record.get("authority") != "reference_only_no_mask_truth":
                    raise NudeCorpusIntakeError(f"reference_truth_boundary_invalid:{sample_id}")
                outcome = "proposal_ready_candidate"
            counters[outcome] += 1
            total_outcomes[outcome] += 1
        lane_reports.append(
            {
                "lane": lane,
                "shard_path": selected[lane].name,
                "shard_sha256": shard["self_sha256"],
                "sample_count": shard["sample_count"],
                "counters": dict(sorted(counters.items())),
                "candidate_label_counts": dict(sorted(candidate_labels.items())),
                "action_context_counts": dict(sorted(action_counts.items())),
                "unmapped_raw_label_counts": dict(sorted(raw_unmapped.items())),
                "exception_counts": dict(sorted(exception_counts.items())),
                "exceptions": exceptions,
                "mask_authority_granted": False,
                "gold_authority_granted": False,
            }
        )
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "nude_corpus_representative_intake_canary",
        "status": "PASS",
        "proof_tier": "RUNTIME_PASS_BOUNDED",
        "platform": platform,
        "registry_sha256": intake["registry"]["self_sha256"],
        "shard_index_sha256": intake["index"]["self_sha256"],
        "registered_dataset_count": len(intake["registry"]["datasets"]),
        "registered_record_count": intake["registry"]["record_count"],
        "selected_record_count": sum(row["sample_count"] for row in lane_reports),
        "source_hashes_verified": verify_source_hashes,
        "lanes": lane_reports,
        "outcomes": dict(sorted(total_outcomes.items())),
        "authority": {
            "external_masks_promoted": False,
            "boxes_used_as_pixel_masks": False,
            "action_or_scene_tags_used_as_pixel_masks": False,
            "reference_images_used_as_mask_truth": False,
            "holdout_used_for_training": False,
            "operational_certificates_issued": False,
        },
        "next_required_stages": [
            "full_exact_and_near_duplicate_grouping",
            "independent_provider_generation_or_comparison",
            "hard_qc",
            "strict_per_record_visual_qa",
            "bounded_repair_or_abstention",
            "signed_record_outcomes",
        ],
    }
    report["report_sha256"] = canonical_sha256(report)
    return report


__all__ = [
    "ADOPTED_DATASET_COUNT",
    "ADOPTED_RECORD_COUNT",
    "ADOPTED_REGISTRY_SHA256",
    "ADOPTED_SHARD_INDEX_SHA256",
    "ADOPTED_SHARDS_PER_PLATFORM",
    "LANES",
    "NudeCorpusIntakeError",
    "canonical_sha256",
    "load_adopted_intake",
    "load_records",
    "rasterize_coco_segmentation",
    "representative_shards",
    "run_representative_canary",
    "sha256_file",
    "validate_shard",
]
