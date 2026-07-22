"""Hash-bound provider execution manifests for adult-corpus canary lanes."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from .nude_corpus_dedup import load_group_evidence
from .nude_corpus_intake import (
    CIVITAI_REFERENCE_METADATA_REF,
    crosswalk_source_labels,
    load_adopted_intake,
    load_records,
    representative_shards,
    validate_civitai_reference_record,
    validate_shard,
)

CANARY_LANES = (
    "bbox_prompt_supervision",
    "bbox_prompt_and_action_tag_supervision",
    "reference_and_tournament_input",
)
PROVIDER_ROUTES = {
    "bbox_prompt_supervision": (
        "sam3_1",
        "maskfactory_core",
        "sam2matting_base_plus",
    ),
    "bbox_prompt_and_action_tag_supervision": (
        "sam3_1",
        "maskfactory_core",
        "sam2matting_base_plus",
    ),
    "reference_and_tournament_input": (
        "sam3_1",
        "sam3_litetext_s0",
        "sam2matting_base_plus",
    ),
}


class NudeProviderCanaryError(ValueError):
    """A canary input, provider identity, or source binding failed closed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _runtime_bindings(runtime_matrix_path: Path) -> dict[str, dict[str, Any]]:
    document = json.loads(Path(runtime_matrix_path).read_text(encoding="utf-8"))
    runtimes = document.get("runtimes")
    if not isinstance(runtimes, list):
        raise NudeProviderCanaryError("provider_runtime_matrix_invalid")
    bindings = {}
    for row in runtimes:
        if not isinstance(row, Mapping) or not isinstance(row.get("provider"), str):
            raise NudeProviderCanaryError("provider_runtime_row_invalid")
        provider = str(row["provider"])
        if provider in bindings:
            raise NudeProviderCanaryError("provider_runtime_duplicate")
        if row.get("checkpoint_status") != "installed" or row.get("may_author_gold") is not False:
            raise NudeProviderCanaryError(f"provider_runtime_authority_invalid:{provider}")
        bindings[provider] = {
            "provider": provider,
            "status": row.get("status"),
            "isolation_boundary": row.get("isolation_boundary"),
            "checkpoint_status": "installed",
            "may_author_gold": False,
            "artifacts": row.get("artifacts"),
        }
    required = {provider for lane in CANARY_LANES for provider in PROVIDER_ROUTES[lane]}
    missing = sorted(required - set(bindings))
    if missing:
        raise NudeProviderCanaryError(f"provider_runtime_missing:{','.join(missing)}")
    return bindings


def _annotations(
    source_root: Path,
    record: Mapping[str, Any],
    cache: dict[str, tuple[dict[int, list[dict[str, Any]]], dict[int, str], str]],
) -> tuple[list[dict[str, Any]], dict[int, str], str]:
    annotation_ref = str(record.get("annotation_ref") or "")
    if not annotation_ref:
        return [], {}, ""
    if annotation_ref not in cache:
        path = (source_root / annotation_ref).resolve(strict=True)
        try:
            path.relative_to(source_root)
        except ValueError as exc:
            raise NudeProviderCanaryError("annotation_path_escaped_source_root") from exc
        raw = path.read_bytes()
        document = json.loads(raw)
        by_image: dict[int, list[dict[str, Any]]] = {}
        for annotation in document.get("annotations", []):
            by_image.setdefault(int(annotation["image_id"]), []).append(annotation)
        categories = {
            int(row["id"]): str(row.get("name", row["id"]))
            for row in document.get("categories", [])
        }
        cache[annotation_ref] = by_image, categories, hashlib.sha256(raw).hexdigest()
    by_image, categories, annotation_sha256 = cache[annotation_ref]
    return (
        by_image.get(int(record["annotation_image_id"]), []),
        categories,
        annotation_sha256,
    )


def _validated_box(annotation: Mapping[str, Any], *, width: int, height: int) -> list[float]:
    bbox = annotation.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise NudeProviderCanaryError("bbox_invalid")
    if any(
        not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in bbox
    ):
        raise NudeProviderCanaryError("bbox_invalid")
    x, y, box_width, box_height = (float(value) for value in bbox)
    if (
        x < 0
        or y < 0
        or box_width <= 0
        or box_height <= 0
        or x + box_width > width
        or y + box_height > height
    ):
        raise NudeProviderCanaryError("bbox_out_of_bounds")
    return [x, y, x + box_width, y + box_height]


def _reference_context(
    source_root: Path,
    record: Mapping[str, Any],
    cache: dict[str, tuple[dict[str, Any], str]],
) -> dict[str, Any]:
    """Join filename metadata while forbidding prompt-to-pixel inference."""

    validate_civitai_reference_record(record)
    metadata_ref = str(record["metadata_ref"])
    if metadata_ref != CIVITAI_REFERENCE_METADATA_REF:
        raise NudeProviderCanaryError("reference_metadata_ref_invalid")
    if metadata_ref not in cache:
        path = (source_root / metadata_ref).resolve(strict=True)
        try:
            path.relative_to(source_root)
        except ValueError as exc:
            raise NudeProviderCanaryError("reference_metadata_path_escaped_source_root") from exc
        raw = path.read_bytes()
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise NudeProviderCanaryError("reference_metadata_catalog_invalid")
        cache[metadata_ref] = document, hashlib.sha256(raw).hexdigest()
    catalog, metadata_sha256 = cache[metadata_ref]
    filename = Path(str(record["source_relative_path"])).name
    entry = catalog.get(filename)
    if not isinstance(entry, Mapping):
        raise NudeProviderCanaryError("reference_metadata_filename_missing")
    prompt = entry.get("prompt")
    nsfw_level = entry.get("nsfwLevel")
    if not isinstance(prompt, str) or not prompt.strip():
        raise NudeProviderCanaryError("reference_metadata_prompt_invalid")
    if nsfw_level != record.get("metadata_nsfw_level"):
        raise NudeProviderCanaryError("reference_metadata_nsfw_level_drift")
    return {
        "schema_version": "maskfactory.civitai_reference_context.v1",
        "metadata_ref": metadata_ref,
        "metadata_file_sha256": metadata_sha256,
        "image_filename": filename,
        "prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "nsfw_level": nsfw_level,
        "authority": "weak_scene_action_retrieval_context_only",
        "may_supply_pixel_truth": False,
        "may_infer_anatomy_labels": False,
        "may_infer_fine_masks": False,
    }


def build_provider_canary_manifest(
    intake_root: Path,
    *,
    split_summary_path: Path,
    split_mapping_path: Path,
    runtime_matrix_path: Path,
    limit_per_lane: int = 8,
) -> dict[str, Any]:
    """Plan exact canary work; this never executes a provider or grants authority."""

    if not 1 <= limit_per_lane <= 64:
        raise NudeProviderCanaryError("limit_per_lane_out_of_bounds")
    intake = load_adopted_intake(intake_root, platform="local")
    records = load_records(intake)
    groups = load_group_evidence(split_summary_path, split_mapping_path)
    provider_bindings = _runtime_bindings(runtime_matrix_path)
    source_root = Path(intake["registry"]["root"]).resolve()
    shards = representative_shards(intake)
    cache: dict[str, tuple[dict[int, list[dict[str, Any]]], dict[int, str], str]] = {}
    reference_metadata_cache: dict[str, tuple[dict[str, Any], str]] = {}
    lane_rows = []
    for lane in CANARY_LANES:
        shard = validate_shard(shards[lane], expected_lane=lane, platform="local")
        selected = []
        used_groups = set()
        for sample in shard["samples"]:
            if len(selected) >= limit_per_lane:
                break
            sample_id = str(sample["sample_id"])
            record = records[sample_id]
            group = groups.get(sample_id)
            if group is None or group.get("source_sha256") != record.get("source_sha256"):
                raise NudeProviderCanaryError("split_group_source_binding_invalid")
            group_id = str(group["split_group_id"])
            if group_id in used_groups:
                continue
            source_path = Path(str(record["source_path_readonly"]))
            if not source_path.is_file() or _sha256(source_path) != record.get("source_sha256"):
                raise NudeProviderCanaryError("source_file_hash_binding_invalid")
            with Image.open(source_path) as source_image:
                source_width, source_height = source_image.size
            if record.get("width") is not None and int(record["width"]) != source_width:
                raise NudeProviderCanaryError("source_width_binding_invalid")
            if record.get("height") is not None and int(record["height"]) != source_height:
                raise NudeProviderCanaryError("source_height_binding_invalid")
            annotations, categories, annotation_sha256 = _annotations(source_root, record, cache)
            prompts = []
            actions = []
            if lane != "reference_and_tournament_input":
                if not annotations:
                    continue
                for annotation in annotations:
                    raw_label = categories.get(int(annotation.get("category_id", -1)))
                    if raw_label is None:
                        raise NudeProviderCanaryError("annotation_category_unknown")
                    mapped, mapped_actions, unmapped = crosswalk_source_labels(
                        (raw_label,), intake["crosswalk"]
                    )
                    actions.extend(mapped_actions)
                    if unmapped:
                        raise NudeProviderCanaryError("annotation_label_unmapped")
                    for candidate in mapped:
                        if str(candidate["kind"]).startswith("context_"):
                            actions.append(candidate)
                            continue
                        prompts.append(
                            {
                                "raw_label": raw_label,
                                "candidate_label": candidate["candidate_label"],
                                "candidate_kind": candidate["kind"],
                                "bbox_xyxy": _validated_box(
                                    annotation,
                                    width=source_width,
                                    height=source_height,
                                ),
                            }
                        )
                if not prompts:
                    continue
            else:
                reference_context = _reference_context(
                    source_root, record, reference_metadata_cache
                )
                prompts = [
                    {
                        "raw_label": None,
                        "candidate_label": "person_instance_discovery",
                        "candidate_kind": "reference_discovery_prompt_no_pixel_truth",
                        "bbox_xyxy": None,
                    }
                ]
            used_groups.add(group_id)
            selected.append(
                {
                    "sample_id": sample_id,
                    "dataset_id": record["dataset_id"],
                    "source_role": lane,
                    "source_sha256": record["source_sha256"],
                    "source_path_runpod": record["source_path_runpod"],
                    "source_geometry": [source_height, source_width],
                    "split_group_id": group_id,
                    "assigned_partition": group["assigned_partition"],
                    "split_assignment_authority": "hash_bound_dedup_group_mapping",
                    "annotation_ref": record.get("annotation_ref"),
                    "annotation_file_sha256": annotation_sha256,
                    "pixel_prompts": prompts,
                    "scene_action_supervision": actions,
                    "reference_context": (
                        reference_context if lane == "reference_and_tournament_input" else None
                    ),
                    "provider_route": list(PROVIDER_ROUTES[lane]),
                    "source_supplies_pixel_truth": False,
                    "candidate_authority": "draft_machine_candidate_only",
                }
            )
        if len(selected) != limit_per_lane:
            raise NudeProviderCanaryError(f"insufficient_canary_records:{lane}")
        lane_rows.append(
            {
                "lane": lane,
                "shard_path": str(shards[lane].resolve()),
                "shard_sha256": shard["self_sha256"],
                "record_count": len(selected),
                "unique_split_group_count": len(used_groups),
                "records": selected,
            }
        )
    manifest = {
        "schema_version": "maskfactory.nude_provider_canary_manifest.v1",
        "artifact_type": "adult_corpus_provider_canary_execution_manifest",
        "status": "READY_PENDING_SHARED_GPU_COORDINATOR",
        "registry_sha256": intake["registry"]["self_sha256"],
        "shard_index_sha256": intake["index"]["self_sha256"],
        "split_mapping_sha256": _sha256(split_mapping_path),
        "provider_runtime_matrix_sha256": _sha256(runtime_matrix_path),
        "provider_bindings": {
            key: provider_bindings[key]
            for key in sorted({p for lane in CANARY_LANES for p in PROVIDER_ROUTES[lane]})
        },
        "lanes": lane_rows,
        "execution_policy": {
            "shared_runpod_coordinator_required": True,
            "provider_microbatch_autotune_required": True,
            "hard_qc_before_strict_vlm": True,
            "strict_vlm_per_record_required": True,
            "contact_sheet_may_approve_records": False,
            "repair_attempt_limit": 3,
            "continue_on_record_failure": True,
        },
        "authority": {
            "human_gold_granted": False,
            "production_mask_authority_granted": False,
            "operational_certificates_issued": False,
            "reference_images_are_pixel_truth": False,
            "reference_prompt_may_infer_pixel_anatomy": False,
        },
    }
    manifest["self_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return manifest


def write_provider_canary_manifest(manifest: Mapping[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


__all__ = [
    "CANARY_LANES",
    "NudeProviderCanaryError",
    "PROVIDER_ROUTES",
    "build_provider_canary_manifest",
    "write_provider_canary_manifest",
]
