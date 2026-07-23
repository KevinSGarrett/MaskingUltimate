"""Bounded recomposition for one person split across complementary proposals.

This module is deliberately narrow.  It can create one new immutable draft
candidate when multiple non-overlapping provider masks are all bound to the
same single-person detector envelope.  It never assigns semantic truth and it
never advances hard-QA, visual-review, certificate, gold, or training authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from .io.hashing import sha256_file
from .io.png_strict import write_binary_mask
from .nude_box_mask_generation import validate_box_prompt_provider_batch
from .providers.contracts import PROVIDER_CONTRACT_VERSION
from .providers.disagreement import binary_mask_sha256

SHA256 = re.compile(r"^[a-f0-9]{64}$")
OPERATION = "union_disjoint_same_owner_proposals_v1"
DEFAULT_POLICY: dict[str, Any] = {
    "minimum_parent_count": 2,
    "maximum_parent_count": 4,
    "maximum_pairwise_iou": 0.05,
    "minimum_parent_detector_containment": 0.98,
    "minimum_union_bbox_iou": 0.90,
    "minimum_union_to_detector_box_ratio": 0.35,
    "maximum_union_to_detector_box_ratio": 0.95,
    "maximum_changed_pixel_fraction": 0.45,
    "maximum_attempts": 1,
}


class SplitPersonRecompositionError(ValueError):
    """A split-person repair precondition or retained artifact failed closed."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _policy(value: Mapping[str, Any] | None) -> dict[str, Any]:
    policy = dict(DEFAULT_POLICY if value is None else value)
    if set(policy) != set(DEFAULT_POLICY):
        raise SplitPersonRecompositionError("split_person_policy_fields_invalid")
    numeric = (
        "maximum_pairwise_iou",
        "minimum_parent_detector_containment",
        "minimum_union_bbox_iou",
        "minimum_union_to_detector_box_ratio",
        "maximum_union_to_detector_box_ratio",
        "maximum_changed_pixel_fraction",
    )
    if any(
        isinstance(policy[key], bool)
        or not isinstance(policy[key], (int, float))
        or not math.isfinite(float(policy[key]))
        or not 0 <= float(policy[key]) <= 1
        for key in numeric
    ):
        raise SplitPersonRecompositionError("split_person_policy_invalid")
    for key in ("minimum_parent_count", "maximum_parent_count", "maximum_attempts"):
        if isinstance(policy[key], bool) or not isinstance(policy[key], int) or policy[key] < 1:
            raise SplitPersonRecompositionError("split_person_policy_invalid")
    if (
        policy["minimum_parent_count"] > policy["maximum_parent_count"]
        or policy["maximum_pairwise_iou"] > DEFAULT_POLICY["maximum_pairwise_iou"]
        or policy["minimum_parent_detector_containment"]
        < DEFAULT_POLICY["minimum_parent_detector_containment"]
        or policy["minimum_union_bbox_iou"] < DEFAULT_POLICY["minimum_union_bbox_iou"]
        or policy["minimum_union_to_detector_box_ratio"]
        < DEFAULT_POLICY["minimum_union_to_detector_box_ratio"]
        or policy["maximum_union_to_detector_box_ratio"]
        > DEFAULT_POLICY["maximum_union_to_detector_box_ratio"]
        or policy["maximum_changed_pixel_fraction"]
        > DEFAULT_POLICY["maximum_changed_pixel_fraction"]
        or policy["maximum_attempts"] != 1
    ):
        raise SplitPersonRecompositionError("split_person_policy_weakened")
    return policy


def _box(value: Sequence[int], *, width: int, height: int, field: str) -> tuple[int, int, int, int]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 4
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise SplitPersonRecompositionError(f"{field}_invalid")
    left, top, right, bottom = value
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise SplitPersonRecompositionError(f"{field}_out_of_bounds")
    return left, top, right, bottom


def _mask_bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    rows, cols = np.where(mask)
    if not len(rows):
        raise SplitPersonRecompositionError("split_person_parent_empty")
    return int(cols.min()), int(rows.min()), int(cols.max() + 1), int(rows.max() + 1)


def _box_iou(left: Sequence[int], right: Sequence[int]) -> float:
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def _mask_iou(left: np.ndarray, right: np.ndarray) -> float:
    union = int(np.count_nonzero(left | right))
    return int(np.count_nonzero(left & right)) / union if union else 0.0


def _load_parent(path: Path, *, width: int, height: int) -> tuple[np.ndarray, str, str]:
    path = Path(path)
    encoded_sha256 = sha256_file(path)
    try:
        with Image.open(path) as image:
            mode = image.mode
            size = image.size
            pixels = np.asarray(image)
    except (OSError, UnidentifiedImageError) as exc:
        raise SplitPersonRecompositionError("split_person_parent_unreadable") from exc
    if (
        mode != "L"
        or size != (width, height)
        or pixels.ndim != 2
        or set(np.unique(pixels).tolist()) - {0, 255}
    ):
        raise SplitPersonRecompositionError("split_person_parent_not_strict_png")
    mask = pixels == 255
    if not mask.any() or mask.all():
        raise SplitPersonRecompositionError("split_person_parent_degenerate")
    return mask, encoded_sha256, binary_mask_sha256(mask)


def _provider_identity(*, source_commit: str, runtime_fingerprint: str) -> dict[str, Any]:
    if not source_commit or not runtime_fingerprint:
        raise SplitPersonRecompositionError("split_person_runtime_identity_invalid")
    return {
        "provider_key": "split_person_recomposition_v1",
        "role": "interactive_segmenter",
        "model_family": "deterministic_proposal_composition",
        "source_commit": source_commit,
        "runtime_fingerprint": runtime_fingerprint,
        "contract_version": PROVIDER_CONTRACT_VERSION,
    }


def build_split_person_recomposition(
    *,
    sample_id: str,
    source_path: Path,
    parent_paths: Sequence[Path],
    parent_confidences: Sequence[float],
    detector_box_xyxy: Sequence[int],
    detector_person_count: int,
    catalog_batch_sha256: str,
    output_root: Path,
    output_relative_path: Path,
    source_commit: str,
    runtime_fingerprint: str,
    policy: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create one draft union candidate and a sealed multi-parent repair report."""

    policy = _policy(policy)
    if not isinstance(sample_id, str) or not sample_id:
        raise SplitPersonRecompositionError("split_person_sample_id_invalid")
    source_path = Path(source_path)
    try:
        with Image.open(source_path) as image:
            width, height = image.size
    except (OSError, UnidentifiedImageError) as exc:
        raise SplitPersonRecompositionError("split_person_source_unreadable") from exc
    if width < 1 or height < 1:
        raise SplitPersonRecompositionError("split_person_source_geometry_invalid")
    source_sha256 = sha256_file(source_path)
    if detector_person_count != 1:
        raise SplitPersonRecompositionError("split_person_requires_exactly_one_detector_owner")
    detector_box = _box(
        detector_box_xyxy, width=width, height=height, field="split_person_detector_box"
    )
    parents = tuple(Path(path) for path in parent_paths)
    if not policy["minimum_parent_count"] <= len(parents) <= policy["maximum_parent_count"]:
        raise SplitPersonRecompositionError("split_person_parent_count_invalid")
    if len(parents) != len(parent_confidences) or len({path.resolve() for path in parents}) != len(
        parents
    ):
        raise SplitPersonRecompositionError("split_person_parent_identity_invalid")
    confidences = tuple(float(value) for value in parent_confidences)
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in confidences):
        raise SplitPersonRecompositionError("split_person_parent_confidence_invalid")
    if not isinstance(catalog_batch_sha256, str) or SHA256.fullmatch(catalog_batch_sha256) is None:
        raise SplitPersonRecompositionError("split_person_catalog_hash_invalid")

    masks: list[np.ndarray] = []
    parent_rows = []
    for index, (path, confidence) in enumerate(zip(parents, confidences, strict=True)):
        mask, encoded_sha256, decoded_sha256 = _load_parent(path, width=width, height=height)
        allowed = np.zeros(mask.shape, dtype=bool)
        left, top, right, bottom = detector_box
        allowed[top:bottom, left:right] = True
        containment = float(np.count_nonzero(mask & allowed) / np.count_nonzero(mask))
        if containment < float(policy["minimum_parent_detector_containment"]):
            raise SplitPersonRecompositionError("split_person_parent_outside_detector_owner")
        masks.append(mask)
        parent_rows.append(
            {
                "parent_index": index,
                "encoded_sha256": encoded_sha256,
                "decoded_pixel_sha256": decoded_sha256,
                "pixel_count": int(np.count_nonzero(mask)),
                "bbox_xyxy": list(_mask_bbox(mask)),
                "detector_containment": containment,
                "provider_confidence_advisory": confidence,
            }
        )

    pairwise = []
    for left_index, left in enumerate(masks):
        for right_index in range(left_index + 1, len(masks)):
            overlap = _mask_iou(left, masks[right_index])
            pairwise.append(
                {"left_parent_index": left_index, "right_parent_index": right_index, "iou": overlap}
            )
            if overlap > float(policy["maximum_pairwise_iou"]):
                raise SplitPersonRecompositionError("split_person_parents_not_complementary")

    union = np.logical_or.reduce(masks)
    union_pixels = int(np.count_nonzero(union))
    detector_area = (detector_box[2] - detector_box[0]) * (detector_box[3] - detector_box[1])
    union_ratio = union_pixels / detector_area
    union_bbox = _mask_bbox(union)
    union_bbox_iou = _box_iou(union_bbox, detector_box)
    if union_bbox_iou < float(policy["minimum_union_bbox_iou"]):
        raise SplitPersonRecompositionError("split_person_union_does_not_span_owner")
    if (
        not float(policy["minimum_union_to_detector_box_ratio"])
        <= union_ratio
        <= float(policy["maximum_union_to_detector_box_ratio"])
    ):
        raise SplitPersonRecompositionError("split_person_union_area_implausible")
    largest_parent = max(int(np.count_nonzero(mask)) for mask in masks)
    changed_pixel_fraction = (union_pixels - largest_parent) / (width * height)
    if changed_pixel_fraction > float(policy["maximum_changed_pixel_fraction"]):
        raise SplitPersonRecompositionError("split_person_changed_pixel_cap_exceeded")

    output_root = Path(output_root).resolve()
    relative = Path(output_relative_path)
    output_path = (output_root / relative).resolve()
    if (
        relative.is_absolute()
        or not relative.parts
        or ".." in relative.parts
        or output_path == output_root
        or output_root not in output_path.parents
    ):
        raise SplitPersonRecompositionError("split_person_output_path_invalid")
    before_hashes = [sha256_file(path) for path in parents]
    write_binary_mask(output_path, union, source_size=(width, height))
    if before_hashes != [sha256_file(path) for path in parents]:
        raise SplitPersonRecompositionError("split_person_parent_bytes_changed")

    prompt_point_rows, prompt_point_cols = np.where(union)
    center_x = (detector_box[0] + detector_box[2] - 1) / 2
    center_y = (detector_box[1] + detector_box[3] - 1) / 2
    nearest = int(
        np.argmin(
            (prompt_point_cols.astype(np.float64) - center_x) ** 2
            + (prompt_point_rows.astype(np.float64) - center_y) ** 2
        )
    )
    prompt_body = {
        "positive_points": [[int(prompt_point_cols[nearest]), int(prompt_point_rows[nearest])]],
        "negative_points": [],
        "box_xyxy": list(detector_box),
        "mask_prompt": None,
    }
    prompt = {**prompt_body, "prompt_sha256": _canonical_sha256(prompt_body)}
    identity = _provider_identity(
        source_commit=source_commit, runtime_fingerprint=runtime_fingerprint
    )
    artifact_sha256 = sha256_file(output_path)
    mask_sha256 = binary_mask_sha256(union)
    plan_body = {
        "operation": OPERATION,
        "source_sha256": source_sha256,
        "catalog_batch_sha256": catalog_batch_sha256,
        "detector_person_count": detector_person_count,
        "detector_box_xyxy": list(detector_box),
        "parent_encoded_sha256s": before_hashes,
        "policy": policy,
    }
    plan_sha256 = _canonical_sha256(plan_body)
    candidate = {
        "person_index": 0,
        "candidate_label": "person",
        "confidence": min(confidences),
        "prompt": prompt,
        "prompt_fingerprint": plan_sha256,
        "mask_sha256": mask_sha256,
        "artifact_relative_path": relative.as_posix(),
        "artifact_sha256": artifact_sha256,
        "pixel_count": union_pixels,
        "authority": "draft_machine_candidate_only",
        "production_mask_authority": False,
        "operational_certificate_eligible": False,
    }
    batch_body = {
        "schema_version": "maskfactory.nude_box_prompt_provider_batch.v1",
        "catalog_batch_sha256": catalog_batch_sha256,
        "provider": identity,
        "record_count": 1,
        "candidate_count": 1,
        "status_counts": {"generated": 1},
        "records": [
            {
                "sample_id": sample_id,
                "source_sha256": source_sha256,
                "status": "generated",
                "reason": [],
                "candidates": [candidate],
            }
        ],
        "authority": "draft_provider_masks_only",
        "source_images_are_pixel_truth": False,
        "boxes_are_pixel_truth": False,
        "production_mask_authority": False,
        "operational_certificates_issued": False,
    }
    batch = {**batch_body, "self_sha256": _canonical_sha256(batch_body)}
    validate_box_prompt_provider_batch(batch, output_root=output_root)
    report_body = {
        "schema_version": "maskfactory.split_person_recomposition_report.v1",
        "sample_id": sample_id,
        "source_sha256": source_sha256,
        "defect_hypothesis": "one_person_split_across_complementary_provider_proposals",
        "operation": OPERATION,
        "attempt_count": 1,
        "policy": policy,
        "policy_sha256": _canonical_sha256(policy),
        "catalog_batch_sha256": catalog_batch_sha256,
        "detector_person_count": detector_person_count,
        "detector_box_xyxy": list(detector_box),
        "parents": parent_rows,
        "pairwise_parent_iou": pairwise,
        "union": {
            "encoded_sha256": artifact_sha256,
            "decoded_pixel_sha256": mask_sha256,
            "pixel_count": union_pixels,
            "bbox_xyxy": list(union_bbox),
            "bbox_iou_with_detector": union_bbox_iou,
            "mask_to_detector_box_ratio": union_ratio,
            "changed_pixel_fraction_from_largest_parent": changed_pixel_fraction,
        },
        "plan_sha256": plan_sha256,
        "provider_batch_sha256": batch["self_sha256"],
        "immutable_parents_preserved": True,
        "hard_qc_complete": False,
        "strict_visual_review_complete": False,
        "production_mask_authority": False,
        "operational_certificates_issued": False,
        "autonomous_certified_gold_created": False,
        "training_truth_created": False,
    }
    report = {**report_body, "self_sha256": _canonical_sha256(report_body)}
    return batch, report


def validate_split_person_recomposition(
    *,
    provider_batch: Mapping[str, Any],
    report: Mapping[str, Any],
    source_path: Path,
    parent_paths: Sequence[Path],
    output_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Revalidate seals, immutable parents, exact union pixels, and claim firewall."""

    batch = validate_box_prompt_provider_batch(provider_batch, output_root=output_root)
    if not isinstance(report, Mapping):
        raise SplitPersonRecompositionError("split_person_report_invalid")
    body = {key: value for key, value in report.items() if key != "self_sha256"}
    if (
        report.get("schema_version") != "maskfactory.split_person_recomposition_report.v1"
        or report.get("self_sha256") != _canonical_sha256(body)
        or report.get("provider_batch_sha256") != batch["self_sha256"]
        or report.get("operation") != OPERATION
    ):
        raise SplitPersonRecompositionError("split_person_report_seal_invalid")
    if report.get("policy") != _policy(report.get("policy")) or report.get(
        "policy_sha256"
    ) != _canonical_sha256(report["policy"]):
        raise SplitPersonRecompositionError("split_person_report_policy_invalid")
    false_fields = (
        "hard_qc_complete",
        "strict_visual_review_complete",
        "production_mask_authority",
        "operational_certificates_issued",
        "autonomous_certified_gold_created",
        "training_truth_created",
    )
    if report.get("immutable_parents_preserved") is not True or any(
        report.get(field) is not False for field in false_fields
    ):
        raise SplitPersonRecompositionError("split_person_report_authority_invalid")
    if sha256_file(Path(source_path)) != report.get("source_sha256"):
        raise SplitPersonRecompositionError("split_person_source_hash_mismatch")
    candidate = batch["records"][0]["candidates"][0]
    with Image.open(Path(output_root) / candidate["artifact_relative_path"]) as image:
        output = np.asarray(image.convert("L")) == 255
    parents = []
    rows = report.get("parents")
    if not isinstance(rows, list) or len(rows) != len(parent_paths):
        raise SplitPersonRecompositionError("split_person_report_parents_invalid")
    for path, row in zip(parent_paths, rows, strict=True):
        parent, encoded, decoded = _load_parent(
            Path(path), width=output.shape[1], height=output.shape[0]
        )
        if encoded != row.get("encoded_sha256") or decoded != row.get("decoded_pixel_sha256"):
            raise SplitPersonRecompositionError("split_person_parent_hash_mismatch")
        parents.append(parent)
    if not np.array_equal(output, np.logical_or.reduce(parents)):
        raise SplitPersonRecompositionError("split_person_union_pixel_mismatch")
    return batch, dict(report)


__all__ = [
    "DEFAULT_POLICY",
    "OPERATION",
    "SplitPersonRecompositionError",
    "build_split_person_recomposition",
    "validate_split_person_recomposition",
]
