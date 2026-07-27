"""QC-025..029 topology plus QC-031..034 uncertainty/regression checks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import numpy as np
from PIL import Image
from scipy import ndimage

from .checks import QcResult
from .metrics import iou

CHAIN_REQUIREMENTS = {
    "left_wrist": ("left_hand_base", "left_forearm"),
    "right_wrist": ("right_hand_base", "right_forearm"),
    "left_elbow": ("left_upper_arm", "left_forearm"),
    "right_elbow": ("right_upper_arm", "right_forearm"),
    "left_knee": ("left_thigh", "left_calf"),
    "right_knee": ("right_thigh", "right_calf"),
    "left_ankle": ("left_calf", "left_foot_base"),
    "right_ankle": ("right_calf", "right_foot_base"),
    "left_toes": ("left_foot_base",),
    "right_toes": ("right_foot_base",),
    "neck": ("head_face",),
    "left_thumb": ("left_hand_base",),
    "right_thumb": ("right_hand_base",),
    "left_index_finger": ("left_hand_base",),
    "right_index_finger": ("right_hand_base",),
    "left_middle_finger": ("left_hand_base",),
    "right_middle_finger": ("right_hand_base",),
    "left_ring_finger": ("left_hand_base",),
    "right_ring_finger": ("right_hand_base",),
    "left_pinky": ("left_hand_base",),
    "right_pinky": ("right_hand_base",),
}


@dataclass(frozen=True)
class TopologyInputs:
    masks: Mapping[str, np.ndarray]
    occluders: Mapping[tuple[str, str], np.ndarray] = field(default_factory=dict)
    hand_crop_regions: Mapping[str, np.ndarray] = field(default_factory=dict)
    joint_axes: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    joint_expected_heights: Mapping[str, float] = field(default_factory=dict)
    side_reference_x: Mapping[str, float] = field(default_factory=dict)
    anatomical_side_votes: Mapping[str, str] = field(default_factory=dict)
    chest_horizontal_band: np.ndarray | None = None
    view: str = "front"


def run_topology_qc(inputs: TopologyInputs) -> tuple[QcResult, ...]:
    masks = {name: np.asarray(mask).astype(bool) for name, mask in inputs.masks.items()}
    shape = _shape(masks)
    return (
        _qc025(masks, inputs.occluders, shape),
        _qc026(masks, inputs.hand_crop_regions, shape),
        _qc027(masks, inputs.joint_axes, inputs.joint_expected_heights),
        _qc028(masks, inputs.side_reference_x, inputs.anatomical_side_votes),
        _qc029(masks, inputs.chest_horizontal_band, inputs.view, inputs.side_reference_x, shape),
    )


def run_uncertainty_qc(
    *,
    part_masks: Mapping[str, np.ndarray],
    disagreement: np.ndarray,
    sam2_predicted_iou: Mapping[str, float],
    parsing_degraded: bool,
    pose_degraded: bool,
) -> tuple[QcResult, ...]:
    heat = np.asarray(disagreement)
    if heat.ndim != 2:
        raise ValueError("disagreement must be HxW")
    normalized = (
        heat.astype(np.float32) / 255
        if np.issubdtype(heat.dtype, np.integer)
        else heat.astype(np.float32)
    )
    high = {}
    for name, value in part_masks.items():
        mask = np.asarray(value).astype(bool)
        if mask.shape != heat.shape or not mask.any():
            continue
        fraction = np.count_nonzero(mask & (normalized > 0.5)) / np.count_nonzero(mask)
        if fraction > 0.03:
            high[name] = fraction
    low = {name: value for name, value in sam2_predicted_iou.items() if value < 0.5}
    degraded = [
        name
        for name, value in (
            ("parsing_degraded", parsing_degraded),
            ("pose_degraded", pose_degraded),
        )
        if value
    ]
    return (
        QcResult("QC-031", "model_disagreement", not high, f"high_parts={high}", "ROUTE"),
        QcResult("QC-032", "sam2_low_conf", not low, f"below_0.5={low}", "WARN"),
        QcResult("QC-033", "degraded_models", not degraded, f"flags={degraded}", "ROUTE"),
    )


def regression_guard(
    current_part_map: np.ndarray,
    previous_gold_part_map: np.ndarray,
    *,
    output_dir: Path,
    minimum_iou: float = 0.5,
) -> QcResult:
    current, previous = np.asarray(current_part_map), np.asarray(previous_gold_part_map)
    if current.shape != previous.shape or current.ndim != 2:
        return QcResult(
            "QC-034", "previous_gold_regression", False, "map dimensions differ", "BLOCK"
        )
    labels = sorted((set(np.unique(current)) | set(np.unique(previous))) - {0})
    per_label = {str(label): iou(current == label, previous == label) for label in labels}
    overall = iou(current > 0, previous > 0)
    failed = {label: value for label, value in per_label.items() if value < minimum_iou}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    document = {"overall_foreground_iou": overall, "per_label_iou": per_label, "below_0.5": failed}
    (output_dir / "gold_v1_vs_v2_diff.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    rgb = np.zeros((*current.shape, 3), dtype=np.uint8)
    rgb[(previous > 0) & (current == 0)] = (255, 0, 0)
    rgb[(current > 0) & (previous == 0)] = (0, 255, 0)
    rgb[(current != previous) & (current > 0) & (previous > 0)] = (255, 255, 0)
    Image.fromarray(rgb, mode="RGB").save(  # png-strict: allow (RGB regression diff, never mask)
        output_dir / "gold_v1_vs_v2_diff.png", format="PNG"
    )
    passed = overall >= minimum_iou and not failed
    return QcResult(
        "QC-034",
        "previous_gold_regression",
        passed,
        f"overall={overall:.6f}, below={failed}",
        "BLOCK",
    )


def _qc025(masks, occluders, shape):
    failures = []
    radius = max(1, round(3 * shape[1] / 1024))
    for part, neighbors in CHAIN_REQUIREMENTS.items():
        if part not in masks or not masks[part].any():
            continue
        expanded = ndimage.binary_dilation(masks[part], iterations=radius)
        for neighbor in neighbors:
            if neighbor not in masks or not masks[neighbor].any():
                continue
            if np.any(expanded & masks[neighbor]):
                continue
            key = (part, neighbor) if (part, neighbor) in occluders else (neighbor, part)
            occluder = occluders.get(key)
            if occluder is None or not _occluder_covers_gap(masks[part], masks[neighbor], occluder):
                failures.append(f"{part}<->{neighbor}")
    return QcResult("QC-025", "chain_integrity", not failures, f"breaks={failures}", "ROUTE")


def _qc026(masks, hand_regions, shape):
    wrong = []
    radius = max(1, round(10 * shape[1] / 1024))
    for side in ("left", "right"):
        region = hand_regions.get(side)
        base = masks.get(f"{side}_hand_base")
        if region is None or base is None:
            continue
        allowed = ndimage.binary_dilation(np.asarray(region).astype(bool), iterations=radius)
        for suffix in ("thumb", "index_finger", "middle_finger", "ring_finger", "pinky"):
            name = f"{side}_{suffix}"
            finger = masks.get(name)
            if finger is not None and finger.any() and np.any(finger & ~allowed):
                wrong.append(f"{name}:outside")
        thumb = masks.get(f"{side}_thumb")
        if (
            thumb is not None
            and thumb.any()
            and not np.any(ndimage.binary_dilation(thumb, iterations=3) & base)
        ):
            wrong.append(f"{side}_thumb:no_base_adjacency")
    return QcResult("QC-026", "finger_containment", not wrong, f"violations={wrong}", "ROUTE")


def _qc027(masks, axes, expected):
    wrong = []
    joint_neighbors = {
        name: neighbors
        for name, neighbors in CHAIN_REQUIREMENTS.items()
        if any(token in name for token in ("elbow", "knee", "wrist", "ankle"))
    }
    for joint, expected_height in expected.items():
        if joint not in masks or joint not in axes or joint not in joint_neighbors:
            wrong.append(f"{joint}:evidence_missing")
            continue
        band = masks[joint]
        axis = np.asarray(axes[joint], dtype=float)
        norm = np.linalg.norm(axis)
        if norm == 0 or not band.any():
            wrong.append(f"{joint}:invalid_axis_or_band")
            continue
        axis /= norm
        ys, xs = np.nonzero(band)
        projection = xs * axis[0] + ys * axis[1]
        actual = float(projection.max() - projection.min() + 1)
        adjacency = all(
            neighbor in masks
            and np.any(ndimage.binary_dilation(band, iterations=1) & masks[neighbor])
            for neighbor in joint_neighbors[joint]
        )
        if not adjacency or not 0.7 * expected_height <= actual <= 1.3 * expected_height:
            wrong.append(
                f"{joint}:actual={actual:.3f},expected={expected_height:.3f},adj={adjacency}"
            )
    return QcResult("QC-027", "band_geometry", not wrong, f"violations={wrong}", "ROUTE")


def _qc028(masks, references, anatomical_side_votes):
    if not {"left", "right"} <= set(references):
        return QcResult("QC-028", "side_coherence", False, "side references unavailable", "ROUTE")
    wrong = []
    for name, mask in masks.items():
        side = (
            "left" if name.startswith("left_") else "right" if name.startswith("right_") else None
        )
        if side is None or not mask.any():
            continue
        semantic_vote = anatomical_side_votes.get(name)
        if semantic_vote in {"left", "right"}:
            if semantic_vote != side:
                wrong.append(name)
            continue
        x = float(np.nonzero(mask)[1].mean())
        other = "right" if side == "left" else "left"
        if abs(x - references[side]) >= abs(x - references[other]):
            wrong.append(name)
    return QcResult("QC-028", "side_coherence", not wrong, f"flipped={wrong}", "ROUTE")


def _qc029(masks, band, view, references, shape):
    left, right = masks.get("left_breast"), masks.get("right_breast")
    if view in {"back", "left_back_3_4", "right_back_3_4"}:
        wrong = [
            name
            for name, mask in (("left_breast", left), ("right_breast", right))
            if mask is not None and mask.any()
        ]
        return QcResult("QC-029", "breast_position", not wrong, f"back_visible={wrong}", "ROUTE")
    if band is None:
        return QcResult("QC-029", "breast_position", False, "chest band unavailable", "ROUTE")
    chest = np.asarray(band).astype(bool)
    if chest.shape != shape:
        return QcResult("QC-029", "breast_position", False, "chest band dimensions differ", "ROUTE")
    wrong = []
    for name, mask in (("left_breast", left), ("right_breast", right)):
        if mask is not None and mask.any() and not np.all(mask <= chest):
            wrong.append(f"{name}:outside_band")
    if (
        left is not None
        and right is not None
        and left.any()
        and right.any()
        and {"left", "right"} <= set(references)
    ):
        lx, rx = np.nonzero(left)[1].mean(), np.nonzero(right)[1].mean()
        expected_left_greater = references["left"] > references["right"]
        if (lx > rx) != expected_left_greater:
            wrong.append("left_right_order")
    return QcResult("QC-029", "breast_position", not wrong, f"violations={wrong}", "ROUTE")


def _occluder_covers_gap(first, second, occluder):
    a_points, b_points = np.argwhere(first), np.argwhere(second)
    distances = np.sum((a_points[:, None, :] - b_points[None, :, :]) ** 2, axis=2)
    ai, bi = np.unravel_index(np.argmin(distances), distances.shape)
    start, end = a_points[ai], b_points[bi]
    steps = max(abs(end - start)) + 1
    ys = np.rint(np.linspace(start[0], end[0], steps)).astype(int)
    xs = np.rint(np.linspace(start[1], end[1], steps)).astype(int)
    gap = np.zeros(first.shape, bool)
    gap[ys, xs] = True
    gap &= ~(first | second)
    cover = np.asarray(occluder).astype(bool)
    return bool(gap.any() and np.count_nonzero(gap & cover) / np.count_nonzero(gap) >= 0.8)


def _shape(masks):
    if not masks:
        raise ValueError("topology masks unavailable")
    shapes = {mask.shape for mask in masks.values()}
    if len(shapes) != 1:
        raise ValueError("topology mask dimensions differ")
    return next(iter(shapes))
