"""S05 deterministic geometry priors, crop requests, and SAM2 prompt plans."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
from PIL import Image, ImageDraw

from ..io.png_strict import write_grayscale


class GeometryError(ValueError):
    """Geometry inputs cannot satisfy the S05 contract."""


@dataclass(frozen=True)
class CropRequest:
    label: str
    bbox_xyxy: tuple[int, int, int, int]
    lane: str
    scale: float


@dataclass(frozen=True)
class PromptPlan:
    label: str
    box_xyxy: tuple[int, int, int, int]
    positive_points: tuple[tuple[int, int], ...]
    negative_points: tuple[tuple[int, int], ...]
    prior_quality: str
    multimask_output: bool = True


def torso_partition_priors(
    torso_parsing: np.ndarray,
    *,
    left_shoulder_xy: tuple[float, float],
    right_shoulder_xy: tuple[float, float],
    left_hip_xy: tuple[float, float],
    right_hip_xy: tuple[float, float],
    view: str,
    densepose_left_scapula: np.ndarray | None = None,
    densepose_right_scapula: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Partition a torso prior using clavicle/fold/iliac/midline and surface view."""
    torso = _binary(torso_parsing, "torso_parsing")
    if not torso.any():
        raise GeometryError("torso parsing prior is empty")
    height, width = torso.shape
    shoulder_y = round((left_shoulder_xy[1] + right_shoulder_xy[1]) / 2)
    iliac_y = round((left_hip_xy[1] + right_hip_xy[1]) / 2)
    if iliac_y <= shoulder_y:
        raise GeometryError("iliac line must be below clavicle line")
    shoulder_y, iliac_y = max(0, shoulder_y), min(height - 1, iliac_y)
    midline_x = round(
        (left_shoulder_xy[0] + right_shoulder_xy[0] + left_hip_xy[0] + right_hip_xy[0]) / 4
    )
    fold_y = _under_breast_fold(torso, shoulder_y, iliac_y)
    yy, xx = np.indices(torso.shape)
    back_views = {"back", "left_back_3_4", "right_back_3_4"}
    if view in back_views:
        waist_y = round(shoulder_y + 0.68 * (iliac_y - shoulder_y))
        upper = torso & (yy >= shoulder_y) & (yy < waist_y)
        lower = torso & (yy >= waist_y)
        shoulder_width = max(1.0, abs(left_shoulder_xy[0] - right_shoulder_xy[0]))
        spine = torso & (np.abs(xx - midline_x) <= 0.05 * shoulder_width)
        output = {
            "back_upper_torso": upper,
            "back_lower_torso": lower,
            "spine_back_center": spine,
        }
        for label, seed in (
            ("left_scapula_back", densepose_left_scapula),
            ("right_scapula_back", densepose_right_scapula),
        ):
            if seed is not None:
                seed_mask = _binary(seed, label)
                if seed_mask.shape != torso.shape:
                    raise GeometryError("DensePose scapula seed dimensions differ")
                output[label] = seed_mask & upper
        return output
    if view not in {"front", "left_profile", "right_profile", "left_3_4", "right_3_4"}:
        raise GeometryError(f"unsupported torso view: {view}")

    chest = torso & (yy >= shoulder_y) & (yy < fold_y)
    abdomen = torso & (yy >= fold_y) & (yy < iliac_y)
    below_iliac = torso & (yy >= iliac_y)
    torso_width = max(
        1,
        int(np.max(np.count_nonzero(torso[max(0, shoulder_y) : iliac_y + 1], axis=1))),
    )
    lateral_width = max(1, round(torso_width * 0.22))
    left_is_lower_x = left_shoulder_xy[0] < right_shoulder_xy[0]
    lower_half = below_iliac & (xx < midline_x) & (xx >= midline_x - lateral_width)
    upper_half = below_iliac & (xx >= midline_x) & (xx < midline_x + lateral_width)
    left_hip, right_hip = (lower_half, upper_half) if left_is_lower_x else (upper_half, lower_half)
    pelvic = below_iliac & ~(left_hip | right_hip)
    navel_y = round(fold_y + 0.58 * (iliac_y - fold_y))
    navel_radius = max(1, min(round(max(height, width) * 20 / 1024), 40))
    belly_button = abdomen & ((xx - midline_x) ** 2 + (yy - navel_y) ** 2 <= navel_radius**2)
    abdomen &= ~belly_button
    output = {
        "chest_upper_torso": chest,
        "abdomen_stomach": abdomen,
        "belly_button": belly_button,
        "pelvic_region": pelvic,
        "left_hip": left_hip,
        "right_hip": right_hip,
    }
    if view in {"front", "left_3_4", "right_3_4"}:
        center_y = shoulder_y + 0.62 * (fold_y - shoulder_y)
        rx, ry = max(1, 0.19 * torso_width), max(1, 0.32 * (fold_y - shoulder_y))
        side_sign = -1 if left_is_lower_x else 1
        for label, center_x in (
            ("left_breast", midline_x + side_sign * 0.19 * torso_width),
            ("right_breast", midline_x - side_sign * 0.19 * torso_width),
        ):
            ellipse = ((xx - center_x) / rx) ** 2 + ((yy - center_y) / ry) ** 2 <= 1
            breast = ellipse & chest
            output[label] = breast
            output["chest_upper_torso"] &= ~breast
    return output


def limb_capsule_prior(
    parsing_superset: np.ndarray,
    silhouette: np.ndarray,
    start_xy: tuple[float, float],
    end_xy: tuple[float, float],
    *,
    stations: int = 5,
    max_radius_fraction: float = 0.35,
) -> tuple[np.ndarray, float, tuple[float, ...]]:
    """Measure five cross-sections, bound pathological widths, rasterize, and clip."""
    parsing = _binary(parsing_superset, "parsing_superset")
    visible = _binary(silhouette, "silhouette")
    if parsing.shape != visible.shape:
        raise GeometryError("parsing and silhouette dimensions differ")
    segment_length = float(np.linalg.norm(np.asarray(end_xy) - np.asarray(start_xy)))
    if not 0 < max_radius_fraction <= 0.5:
        raise GeometryError("limb capsule max radius fraction must be in (0, 0.5]")
    widths = sample_cross_section_half_widths(parsing, start_xy, end_xy, stations=stations)
    valid = [width for width in widths if width > 0]
    if not valid:
        raise GeometryError("no parsing cross-section intersects the limb segment")
    radius = min(float(np.median(valid)), max_radius_fraction * segment_length)
    yy, xx = np.indices(parsing.shape, dtype=np.float64)
    distance = _distance_to_segment(xx, yy, start_xy, end_xy)
    capsule = distance <= radius
    return capsule & parsing & visible, radius, widths


def skeleton_capsule_prior(
    silhouette: np.ndarray,
    start_xy: tuple[float, float],
    end_xy: tuple[float, float],
    *,
    radius_fraction: float,
) -> np.ndarray:
    """Pose-only low-quality fallback when parsing misses a confident limb chain."""
    visible = _binary(silhouette, "silhouette")
    if not 0 < radius_fraction <= 0.5:
        raise GeometryError("skeleton capsule radius fraction must be in (0, 0.5]")
    length = float(np.linalg.norm(np.asarray(end_xy) - np.asarray(start_xy)))
    if length <= 0:
        raise GeometryError("skeleton capsule segment has zero length")
    radius = max(2.0, radius_fraction * length)
    yy, xx = np.indices(visible.shape, dtype=np.float64)
    return (_distance_to_segment(xx, yy, start_xy, end_xy) <= radius) & visible


def sample_cross_section_half_widths(
    mask: np.ndarray,
    start_xy: tuple[float, float],
    end_xy: tuple[float, float],
    *,
    stations: int = 5,
) -> tuple[float, ...]:
    """Measure parsing-mask half-width at equally spaced internal limb stations."""
    binary = _binary(mask, "mask")
    if stations != 5:
        raise GeometryError("S05 requires exactly five cross-section stations")
    direction = np.asarray(end_xy, dtype=float) - np.asarray(start_xy, dtype=float)
    length = float(np.linalg.norm(direction))
    if length == 0:
        raise GeometryError("limb segment has zero length")
    perpendicular = np.array([-direction[1], direction[0]]) / length
    limit = int(math.ceil(math.hypot(*binary.shape)))
    widths = []
    for fraction in np.linspace(1 / 6, 5 / 6, 5):
        center = np.asarray(start_xy) + direction * fraction
        negative = _ray_extent(binary, center, -perpendicular, limit)
        positive = _ray_extent(binary, center, perpendicular, limit)
        widths.append((negative + positive + 1) / 2 if negative + positive else 0.0)
    return tuple(float(width) for width in widths)


def joint_band(
    shape: tuple[int, int],
    center_xy: tuple[float, float],
    segment_start_xy: tuple[float, float],
    segment_end_xy: tuple[float, float],
    local_width: float,
    *,
    joint: str,
) -> np.ndarray:
    """Build the joint-owned perpendicular rectangle (0.6x; wrist 0.5x)."""
    if local_width <= 0 or joint not in {"elbow", "knee", "wrist", "ankle"}:
        raise GeometryError("invalid joint band request")
    factor = 0.5 if joint == "wrist" else 0.6
    band_height = factor * local_width
    direction = np.asarray(segment_end_xy, dtype=float) - np.asarray(segment_start_xy, dtype=float)
    length = float(np.linalg.norm(direction))
    if length == 0:
        raise GeometryError("joint segment has zero length")
    longitudinal = direction / length
    transverse = np.array([-longitudinal[1], longitudinal[0]])
    yy, xx = np.indices(shape, dtype=float)
    dx, dy = xx - center_xy[0], yy - center_xy[1]
    along = np.abs(dx * longitudinal[0] + dy * longitudinal[1])
    across = np.abs(dx * transverse[0] + dy * transverse[1])
    return (along <= band_height / 2) & (across <= local_width / 2)


def carve_joint_band(
    proximal: np.ndarray, distal: np.ndarray, band: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Give band pixels exclusively to the joint, removing them from both neighbors."""
    proximal_mask, distal_mask, joint_mask = map(np.asarray, (proximal, distal, band))
    if proximal_mask.shape != distal_mask.shape or proximal_mask.shape != joint_mask.shape:
        raise GeometryError("joint carve dimensions differ")
    joint_mask = joint_mask.astype(bool) & (proximal_mask.astype(bool) | distal_mask.astype(bool))
    return (
        proximal_mask.astype(bool) & ~joint_mask,
        distal_mask.astype(bool) & ~joint_mask,
        joint_mask,
    )


def crop_request(
    label: str,
    points_xy: Iterable[tuple[float, float]],
    *,
    image_size: tuple[int, int],
    scale: float = 1.6,
    lane: str = "specialist",
) -> CropRequest:
    points = np.asarray(tuple(points_xy), dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or not len(points) or scale < 1:
        raise GeometryError("crop points must be Nx2 and scale >= 1")
    minimum, maximum = points.min(axis=0), points.max(axis=0)
    center = (minimum + maximum) / 2
    size = np.maximum(maximum - minimum, 2) * scale
    width, height = image_size
    box = (
        max(0, math.floor(center[0] - size[0] / 2)),
        max(0, math.floor(center[1] - size[1] / 2)),
        min(width, math.ceil(center[0] + size[0] / 2)),
        min(height, math.ceil(center[1] + size[1] / 2)),
    )
    return CropRequest(label, box, lane, scale)


def hair_prior(
    parsing_hair: np.ndarray, gdino_hair_boxes: Iterable[tuple[int, int, int, int]]
) -> np.ndarray:
    """Union parsing hair with proposal boxes; output remains a prior, never a final mask."""
    prior = _binary(parsing_hair, "parsing_hair").copy()
    height, width = prior.shape
    for left, top, right, bottom in gdino_hair_boxes:
        left, top = max(0, left), max(0, top)
        right, bottom = min(width, right), min(height, bottom)
        if right > left and bottom > top:
            prior[top:bottom, left:right] = True
    return prior


def build_prompt_plan(
    label: str,
    prior: np.ndarray,
    *,
    skeleton_points_xy: Iterable[tuple[float, float]],
    neighbor_priors: Iterable[np.ndarray] = (),
    box_scale: float = 1.1,
    skeleton_samples: int = 5,
    prior_quality: str = "high",
) -> PromptPlan:
    """Emit peak + 3..7 skeleton positives, neighbor peaks + background-ring negatives."""
    soft = np.asarray(prior)
    if soft.ndim != 2 or not np.isfinite(soft).all() or not np.any(soft > 0):
        raise GeometryError("prompt prior must be a non-empty finite 2-D map")
    if not 3 <= skeleton_samples <= 7 or prior_quality not in {"high", "low"}:
        raise GeometryError("invalid prompt recipe")
    peak_ys, peak_xs = np.nonzero(soft == soft.max())
    peak = (int(peak_xs[0]), int(peak_ys[0]))
    skeleton = _sample_points(tuple(skeleton_points_xy), skeleton_samples)
    positives = _dedupe((peak, *skeleton))
    negatives = []
    for neighbor in neighbor_priors:
        array = np.asarray(neighbor)
        if array.shape != soft.shape:
            raise GeometryError("neighbor prior dimensions differ")
        if np.any(array > 0):
            nys, nxs = np.nonzero(array == array.max())
            negatives.append((int(nxs[0]), int(nys[0])))
    support_ys, support_xs = np.nonzero(soft > 0)
    raw_box = (
        int(support_xs.min()),
        int(support_ys.min()),
        int(support_xs.max()) + 1,
        int(support_ys.max()) + 1,
    )
    box = _expand_box(raw_box, soft.shape, box_scale)
    negatives.extend(_background_ring(box, soft.shape))
    return PromptPlan(label, box, positives, _dedupe(negatives), prior_quality)


def write_geometry_artifacts(
    output_dir: Path,
    priors: dict[str, np.ndarray],
    plans: Iterable[PromptPlan],
    crop_requests: Iterable[CropRequest] = (),
) -> Path:
    output_dir = Path(output_dir)
    for label, prior in priors.items():
        array = np.asarray(prior)
        soft = array.astype(np.uint8) * 255 if array.dtype == bool else array.astype(np.uint8)
        write_grayscale(
            output_dir / f"prior_{label}.png", soft, source_size=(soft.shape[1], soft.shape[0])
        )
    path = output_dir / "prompts.json"
    document = {
        "schema_version": "1.0.0",
        "plans": [asdict(plan) for plan in plans],
        "crop_requests": [asdict(request) for request in crop_requests],
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def render_prompt_overlay(source: Image.Image, plan: PromptPlan, output_path: Path) -> Path:
    overlay = source.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    draw.rectangle(plan.box_xyxy, outline=(255, 255, 0), width=2)
    for x, y in plan.positive_points:
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(0, 255, 0))
    for x, y in plan.negative_points:
        draw.line((x - 3, y - 3, x + 3, y + 3), fill=(255, 0, 0), width=2)
        draw.line((x - 3, y + 3, x + 3, y - 3), fill=(255, 0, 0), width=2)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(output_path, format="PNG")  # png-strict: allow (RGB debug overlay, never mask)
    return output_path


def run_s05_production(
    *,
    parsing_path: Path,
    silhouette_path: Path,
    pose_path: Path,
    context_bbox_xyxy: tuple[int, int, int, int],
    parsing_map: Mapping[int, Mapping[str, Any]],
    output_dir: Path,
    confidence_min: float = 0.3,
) -> tuple[dict[str, np.ndarray], tuple[PromptPlan, ...], tuple[CropRequest, ...]]:
    """Build S05 priors in context-crop coordinates from authoritative S02-S04 files."""
    labels = np.asarray(Image.open(parsing_path))
    silhouette_full = np.asarray(Image.open(silhouette_path).convert("L")) > 0
    left, top, right, bottom = context_bbox_xyxy
    silhouette = silhouette_full[top:bottom, left:right]
    if labels.ndim != 2 or labels.shape != silhouette.shape:
        raise GeometryError("S03 parsing and context-projected S02 silhouette dimensions differ")
    pose = json.loads(Path(pose_path).read_text(encoding="utf-8"))
    points = {
        int(item["index"]): (
            float(item["x"]) - left,
            float(item["y"]) - top,
            float(item["confidence"]),
        )
        for item in pose["keypoints"]
    }

    def class_mask(class_name: str) -> np.ndarray:
        ids = [int(index) for index, entry in parsing_map.items() if entry["class"] == class_name]
        return np.isin(labels, ids) if ids else np.zeros(labels.shape, dtype=bool)

    def kp(index: int) -> tuple[float, float] | None:
        point = points.get(index)
        return None if point is None or point[2] < confidence_min else point[:2]

    priors: dict[str, np.ndarray] = {}
    skeletons: dict[str, tuple[tuple[float, float], ...]] = {}
    segment_defs = (
        ("left_upper_arm", "left_upper_arm", "right_upper_arm", 5, 7, 0.16),
        ("left_forearm", "left_lower_arm", "right_lower_arm", 7, 9, 0.14),
        ("right_upper_arm", "right_upper_arm", "left_upper_arm", 6, 8, 0.16),
        ("right_forearm", "right_lower_arm", "left_lower_arm", 8, 10, 0.14),
        ("left_thigh", "left_upper_leg", "right_upper_leg", 11, 13, 0.18),
        ("left_calf", "left_lower_leg", "right_lower_leg", 13, 15, 0.16),
        ("right_thigh", "right_upper_leg", "left_upper_leg", 12, 14, 0.18),
        ("right_calf", "right_lower_leg", "left_lower_leg", 14, 16, 0.16),
    )
    for (
        label,
        parsing_class,
        opposite_class,
        start_index,
        end_index,
        fallback_radius_fraction,
    ) in segment_defs:
        side_parsing = class_mask(parsing_class)
        parsing = side_parsing | class_mask(opposite_class)
        start, end = kp(start_index), kp(end_index)
        quality = "high"
        if start is not None and end is not None and parsing.any():
            try:
                prior, _, _ = limb_capsule_prior(parsing, silhouette, start, end)
            except GeometryError:
                prior = skeleton_capsule_prior(
                    silhouette,
                    start,
                    end,
                    radius_fraction=fallback_radius_fraction,
                )
                quality = "low"
        else:
            prior, quality = side_parsing & silhouette, "low"
        if prior.any():
            priors[label] = prior
            skeletons[label] = (start, end) if quality == "high" else ()

    torso = class_mask("torso") & silhouette
    torso_points = [kp(index) for index in (5, 6, 11, 12)]
    if torso.any() and all(point is not None for point in torso_points):
        ls, rs, lh, rh = torso_points
        assert ls is not None and rs is not None and lh is not None and rh is not None
        try:
            priors.update(
                torso_partition_priors(
                    torso,
                    left_shoulder_xy=ls,
                    right_shoulder_xy=rs,
                    left_hip_xy=lh,
                    right_hip_xy=rh,
                    view=pose["view"],
                )
            )
        except GeometryError:
            priors["chest_upper_torso"] = torso
        for label in tuple(priors):
            if label in {
                "chest_upper_torso",
                "left_breast",
                "right_breast",
                "abdomen_stomach",
                "belly_button",
                "pelvic_region",
                "left_hip",
                "right_hip",
                "back_upper_torso",
                "back_lower_torso",
                "spine_back_center",
            }:
                skeletons[label] = (ls, rs, lh, rh)

    hair = class_mask("hair") & silhouette
    if hair.any():
        priors["hair"] = hair
        skeletons["hair"] = ()

    crop_requests: list[CropRequest] = []
    for label, indices in (
        ("left_hand", (9, *range(91, 112))),
        ("right_hand", (10, *range(112, 133))),
        ("left_foot", (15, 17, 18, 19)),
        ("right_foot", (16, 20, 21, 22)),
    ):
        available = tuple(point for index in indices if (point := kp(index)) is not None)
        if available:
            crop_requests.append(
                crop_request(label, available, image_size=(labels.shape[1], labels.shape[0]))
            )

    plans = tuple(
        build_prompt_plan(
            label,
            prior,
            skeleton_points_xy=skeletons.get(label, ()),
            skeleton_samples=5,
            prior_quality="high" if skeletons.get(label) else "low",
        )
        for label, prior in sorted(priors.items())
        if prior.any()
    )
    write_geometry_artifacts(output_dir, priors, plans, crop_requests)
    source = Image.open(parsing_path).convert("RGB")
    for plan in plans:
        render_prompt_overlay(source, plan, Path(output_dir) / "debug" / f"{plan.label}.png")
    return priors, plans, tuple(crop_requests)


def _binary(array: np.ndarray, name: str) -> np.ndarray:
    value = np.asarray(array)
    if value.ndim != 2:
        raise GeometryError(f"{name} must be 2-D")
    return value.astype(bool)


def _under_breast_fold(torso: np.ndarray, shoulder_y: int, iliac_y: int) -> int:
    """Choose the narrowest horizontal torso profile in the central chest search band."""
    start = max(shoulder_y + 1, round(shoulder_y + 0.35 * (iliac_y - shoulder_y)))
    stop = min(iliac_y, round(shoulder_y + 0.65 * (iliac_y - shoulder_y)) + 1)
    if stop <= start:
        return round((shoulder_y + iliac_y) / 2)
    profile = np.count_nonzero(torso[start:stop], axis=1)
    nonzero = np.flatnonzero(profile)
    if not len(nonzero):
        return round((shoulder_y + iliac_y) / 2)
    local = nonzero[np.argmin(profile[nonzero])]
    return int(start + local)


def _ray_extent(mask: np.ndarray, center: np.ndarray, direction: np.ndarray, limit: int) -> int:
    extent = 0
    height, width = mask.shape
    for distance in range(1, limit + 1):
        x, y = np.rint(center + direction * distance).astype(int)
        if not (0 <= x < width and 0 <= y < height and mask[y, x]):
            break
        extent = distance
    return extent


def _distance_to_segment(xx, yy, start_xy, end_xy):
    start, end = np.asarray(start_xy, dtype=float), np.asarray(end_xy, dtype=float)
    vector = end - start
    denominator = float(np.dot(vector, vector))
    if denominator == 0:
        raise GeometryError("limb segment has zero length")
    projection = np.clip(
        ((xx - start[0]) * vector[0] + (yy - start[1]) * vector[1]) / denominator, 0, 1
    )
    return np.hypot(
        xx - (start[0] + projection * vector[0]), yy - (start[1] + projection * vector[1])
    )


def _sample_points(
    points: tuple[tuple[float, float], ...], count: int
) -> tuple[tuple[int, int], ...]:
    if not points:
        return ()
    indices = np.linspace(0, len(points) - 1, count).round().astype(int)
    return tuple((round(points[index][0]), round(points[index][1])) for index in indices)


def _dedupe(points: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    return tuple(dict.fromkeys(points))


def _expand_box(box, shape, scale):
    left, top, right, bottom = box
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    box_width, box_height = (right - left) * scale, (bottom - top) * scale
    height, width = shape
    return (
        max(0, math.floor(center_x - box_width / 2)),
        max(0, math.floor(center_y - box_height / 2)),
        min(width, math.ceil(center_x + box_width / 2)),
        min(height, math.ceil(center_y + box_height / 2)),
    )


def _background_ring(box, shape):
    left, top, right, bottom = box
    height, width = shape
    offset = 4
    candidates = (
        (left - offset, top - offset),
        ((left + right) // 2, top - offset),
        (right + offset, top - offset),
        (right + offset, (top + bottom) // 2),
        (right + offset, bottom + offset),
        ((left + right) // 2, bottom + offset),
        (left - offset, bottom + offset),
        (left - offset, (top + bottom) // 2),
    )
    return tuple((min(width - 1, max(0, x)), min(height - 1, max(0, y))) for x, y in candidates)
