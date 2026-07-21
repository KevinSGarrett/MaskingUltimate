"""P3 feet/toes crop, geometric split, and footwear material constitution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .common import LaneCrop, create_lane_crop


class FootLaneError(ValueError):
    """Foot-lane pose, geometry, or footwear evidence is invalid."""


FOOT_INDICES = {"left": (17, 18, 19), "right": (20, 21, 22)}
ANKLE_INDEX = {"left": 15, "right": 16}


@dataclass(frozen=True)
class FootSplit:
    foot_base: np.ndarray
    toes: np.ndarray
    mtp_fraction_from_heel: float


@dataclass(frozen=True)
class FootwearResult:
    foot_base: np.ndarray
    toes: np.ndarray
    material_map: np.ndarray
    visibility_states: dict[str, str]
    visible_body_skin: np.ndarray


def create_foot_crop(
    source_path: Path,
    foot_prior: np.ndarray,
    pose133: np.ndarray,
    *,
    side: str,
    output_dir: Path,
    confidence_min: float = 0.3,
) -> LaneCrop:
    """Crop from ankle plus the side's three of six COCO-WholeBody foot keypoints."""
    pose = np.asarray(pose133, dtype=np.float64)
    if pose.shape != (133, 3) or side not in FOOT_INDICES:
        raise FootLaneError("pose must be 133x3 and side left/right")
    indices = (ANKLE_INDEX[side], *FOOT_INDICES[side])
    points = pose[list(indices)]
    points = points[points[:, 2] >= confidence_min]
    if len(points) < 3:
        raise FootLaneError(f"insufficient {side} ankle/foot keypoints")
    minimum, maximum = points[:, :2].min(axis=0), points[:, :2].max(axis=0)
    bbox = (
        int(np.floor(minimum[0])),
        int(np.floor(minimum[1])),
        int(np.ceil(maximum[0])) + 1,
        int(np.ceil(maximum[1])) + 1,
    )
    return create_lane_crop(
        source_path,
        foot_prior,
        part=f"{side}_foot",
        part_bbox_xyxy=bbox,
        output_dir=output_dir,
    )


def split_foot_base_toes(
    foot_mask: np.ndarray,
    *,
    heel_xy: tuple[float, float],
    big_toe_xy: tuple[float, float],
    small_toe_xy: tuple[float, float],
) -> FootSplit:
    """Estimate MTP at the narrowest distal width profile, then split perpendicular to axis."""
    foot = np.asarray(foot_mask).astype(bool)
    if foot.ndim != 2 or not foot.any():
        raise FootLaneError("foot mask must be nonempty 2-D")
    heel = np.asarray(heel_xy, dtype=float)
    toe_center = (np.asarray(big_toe_xy, dtype=float) + np.asarray(small_toe_xy, dtype=float)) / 2
    axis = toe_center - heel
    length = float(np.linalg.norm(axis))
    if length == 0:
        raise FootLaneError("heel-to-toe axis has zero length")
    unit = axis / length
    perpendicular = np.array([-unit[1], unit[0]])
    fractions = np.linspace(0.55, 0.85, 13)
    widths = [_profile_width(foot, heel + axis * fraction, perpendicular) for fraction in fractions]
    valid = [
        (width, fraction) for width, fraction in zip(widths, fractions, strict=True) if width > 0
    ]
    mtp_fraction = min(valid, key=lambda pair: (pair[0], abs(pair[1] - 0.72)))[1] if valid else 0.72
    yy, xx = np.indices(foot.shape)
    projection = ((xx - heel[0]) * unit[0] + (yy - heel[1]) * unit[1]) / length
    toes = foot & (projection >= mtp_fraction)
    base = foot & ~toes
    return FootSplit(base, toes, float(mtp_fraction))


def apply_footwear_logic(
    split: FootSplit,
    *,
    side: str,
    coverage: str,
    visible_skin: np.ndarray,
) -> FootwearResult:
    """Closed shoe/sock keeps foot_base PART, hides toes; bare/sandal follows skin contours."""
    if side not in {"left", "right"} or coverage not in {
        "closed_shoe",
        "sock",
        "barefoot",
        "sandal",
    }:
        raise FootLaneError("invalid side or footwear coverage")
    skin = np.asarray(visible_skin).astype(bool)
    if skin.shape != split.foot_base.shape:
        raise FootLaneError("visible skin dimensions differ")
    material = np.zeros(skin.shape, dtype=np.uint8)
    if coverage in {"closed_shoe", "sock"}:
        foot_base = split.foot_base | split.toes
        toes = np.zeros_like(split.toes)
        material[foot_base] = 8 if coverage == "closed_shoe" else 15
        states = {
            f"{side}_foot_base": "visible",
            f"{side}_toes": "not_visible",
        }
        body_skin = np.zeros_like(skin)
    else:
        foot_base = split.foot_base & skin
        toes = split.toes & skin
        material[foot_base | toes] = 1
        if coverage == "sandal":
            # Sandal fabric can coexist around visible skin, but this lane authors skin contours only.
            material[(split.foot_base | split.toes) & ~skin] = 8
        states = {
            f"{side}_foot_base": "visible" if foot_base.any() else "occluded",
            f"{side}_toes": "visible" if toes.any() else "occluded",
        }
        body_skin = foot_base | toes
    return FootwearResult(foot_base, toes, material, states, body_skin)


def _profile_width(mask: np.ndarray, center: np.ndarray, perpendicular: np.ndarray) -> int:
    width = 0
    for direction in (-perpendicular, perpendicular):
        for distance in range(1, 129):
            x, y = np.rint(center + direction * distance).astype(int)
            if not (0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and mask[y, x]):
                break
            width += 1
    return width + 1 if width else 0
