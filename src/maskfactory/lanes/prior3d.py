"""DensePose surface referee; it votes and flags but never authors a mask."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
from scipy import ndimage

from ..stages.s08_5_densepose import DensePoseOutput

# DensePose's two fine torso charts are ordered back then front.  This is easy
# to invert because both map to the same coarse ``Torso`` class.  The mapping
# below is also fixture-verified against independently reviewed front/back
# sources; do not infer it from the coarse class table.
FRONT_SURFACES = frozenset({2})
BACK_SURFACES = frozenset({1})
LEFT_SURFACES = frozenset({4, 5, 8, 10, 12, 14, 15, 17, 19, 21})
RIGHT_SURFACES = frozenset({3, 6, 7, 9, 11, 13, 16, 18, 20, 22})


@dataclass(frozen=True)
class SurfaceVote:
    front_fraction: float | None
    back_fraction: float | None
    side_vote: str | None


@dataclass(frozen=True)
class ContinuityEvidence:
    occlusion_suspect: bool
    disconnected_components: int
    uv_jump_fraction: float


def surface_vote(
    mask: np.ndarray,
    densepose: DensePoseOutput,
    *,
    min_side_pixels: int = 32,
    min_side_coverage: float = 0.01,
    min_side_margin: float = 0.10,
) -> SurfaceVote:
    """Summarize DensePose evidence without treating trace overlap as a side vote.

    DensePose is a referee, so an isolated/misprojected chart pixel must not count as
    an independent QC-014 signal. Front/back fractions retain their previous behavior;
    only the L/R vote is suppressed when coverage or majority separation is too weak.
    """
    if min_side_pixels < 1:
        raise ValueError("min_side_pixels must be positive")
    if not 0 <= min_side_coverage <= 1 or not 0 <= min_side_margin <= 1:
        raise ValueError("DensePose side reliability fractions must be within 0..1")
    region, index = _region_index(mask, densepose)
    values = index[region & (index > 0)]
    if not len(values):
        return SurfaceVote(None, None, None)
    front = np.isin(values, tuple(FRONT_SURFACES)).sum()
    back = np.isin(values, tuple(BACK_SURFACES)).sum()
    torso_votes = front + back
    left = np.isin(values, tuple(LEFT_SURFACES)).sum()
    right = np.isin(values, tuple(RIGHT_SURFACES)).sum()
    sided = int(left + right)
    coverage = sided / int(region.sum())
    margin = abs(int(left) - int(right)) / sided if sided else 0.0
    reliable = (
        sided >= min_side_pixels and coverage >= min_side_coverage and margin >= min_side_margin
    )
    side = "left" if reliable and left > right else "right" if reliable and right > left else None
    return SurfaceVote(
        float(front / torso_votes) if torso_votes else None,
        float(back / torso_votes) if torso_votes else None,
        side,
    )


def densepose_back_ratio(torso_mask: np.ndarray, densepose: DensePoseOutput) -> float | None:
    return surface_vote(torso_mask, densepose).back_fraction


def paired_torso_uv_side_votes(
    left_mask: np.ndarray,
    right_mask: np.ndarray,
    densepose: DensePoseOutput,
    *,
    min_pixels: int = 64,
    min_mean_u_separation: float = 2 / 255,
) -> tuple[str | None, str | None]:
    """Use torso-chart U ordering as a paired L/R vote when chart IDs are unsided."""
    left_region, index = _region_index(left_mask, densepose)
    right_region, _ = _region_index(right_mask, densepose)
    if min_pixels < 1 or not 0 < min_mean_u_separation <= 1:
        raise ValueError("invalid paired torso UV vote thresholds")
    torso = np.isin(index, tuple(FRONT_SURFACES | BACK_SURFACES))
    left_values = np.asarray(densepose.u, dtype=np.float32)[left_region & torso] / 255
    right_values = np.asarray(densepose.u, dtype=np.float32)[right_region & torso] / 255
    if len(left_values) < min_pixels or len(right_values) < min_pixels:
        return None, None
    delta = float(right_values.mean() - left_values.mean())
    if abs(delta) < min_mean_u_separation:
        return None, None
    return ("left", "right") if delta > 0 else ("right", "left")


def uv_continuity(
    mask: np.ndarray,
    densepose: DensePoseOutput,
    *,
    jump_threshold: float = 0.35,
    suspect_fraction: float = 0.05,
) -> ContinuityEvidence:
    region, index = _region_index(mask, densepose)
    valid = region & (index > 0)
    components = int(ndimage.label(valid)[1])
    u = np.asarray(densepose.u, dtype=np.float32) / 255
    v = np.asarray(densepose.v, dtype=np.float32) / 255
    jumps, comparisons = 0, 0
    for axis in (0, 1):
        pair = valid & np.roll(valid, -1, axis=axis)
        if axis == 0:
            pair[-1, :] = False
        else:
            pair[:, -1] = False
        distance = np.hypot(u - np.roll(u, -1, axis=axis), v - np.roll(v, -1, axis=axis))
        comparisons += int(pair.sum())
        jumps += int(np.count_nonzero(pair & (distance > jump_threshold)))
    fraction = jumps / comparisons if comparisons else 0.0
    return ContinuityEvidence(components > 1 or fraction > suspect_fraction, components, fraction)


def impossible_adjacency_evidence(
    part_masks: Mapping[str, np.ndarray],
    required_neighbors: Mapping[str, tuple[str, ...]],
    *,
    dilation_px: int = 3,
) -> dict[str, tuple[str, ...]]:
    """Report missing required contacts; topology battery consumes this as referee evidence."""
    missing = {}
    for part, neighbors in required_neighbors.items():
        if part not in part_masks or not np.asarray(part_masks[part]).any():
            continue
        expanded = ndimage.binary_dilation(
            np.asarray(part_masks[part]).astype(bool), iterations=dilation_px
        )
        absent = tuple(
            neighbor
            for neighbor in neighbors
            if neighbor not in part_masks
            or not np.any(expanded & np.asarray(part_masks[neighbor]).astype(bool))
        )
        if absent:
            missing[part] = absent
    return missing


class SmplxV2Reservation:
    """Deliberately unimplemented v2 interface; DensePose sufficiency is evaluated first."""

    status = "reserved_v2_not_built"
    replacement_condition = "failure_mining_proves_densepose_insufficient"

    def fit(self, image: np.ndarray):
        raise NotImplementedError("SMPL-X is reserved for ontology/pipeline v2")


def _region_index(mask, densepose):
    region = np.asarray(mask).astype(bool)
    index = np.asarray(densepose.part_index)
    if (
        region.shape != index.shape
        or np.asarray(densepose.u).shape != index.shape
        or np.asarray(densepose.v).shape != index.shape
    ):
        raise ValueError("mask and DensePose IUV dimensions differ")
    return region, index
