"""DensePose surface referee; it votes and flags but never authors a mask."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
from scipy import ndimage

from ..stages.s08_5_densepose import DensePoseOutput

FRONT_SURFACES = frozenset({1})
BACK_SURFACES = frozenset({2})
LEFT_SURFACES = frozenset({4, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23})
RIGHT_SURFACES = frozenset({3, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24})


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


def surface_vote(mask: np.ndarray, densepose: DensePoseOutput) -> SurfaceVote:
    region, index = _region_index(mask, densepose)
    values = index[region & (index > 0)]
    if not len(values):
        return SurfaceVote(None, None, None)
    front = np.isin(values, tuple(FRONT_SURFACES)).sum()
    back = np.isin(values, tuple(BACK_SURFACES)).sum()
    torso_votes = front + back
    left = np.isin(values, tuple(LEFT_SURFACES)).sum()
    right = np.isin(values, tuple(RIGHT_SURFACES)).sum()
    side = "left" if left > right else "right" if right > left else None
    return SurfaceVote(
        float(front / torso_votes) if torso_votes else None,
        float(back / torso_votes) if torso_votes else None,
        side,
    )


def densepose_back_ratio(torso_mask: np.ndarray, densepose: DensePoseOutput) -> float | None:
    return surface_vote(torso_mask, densepose).back_fraction


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
