"""Pairwise normalized-mask disagreement maps with exact candidate bindings."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import numpy as np

from maskfactory.vlm.critic_catalog import canonical_sha256

SHA256 = re.compile(r"^[a-f0-9]{64}$")


class DisagreementError(ValueError):
    """Candidate geometry, provenance, or binary-mask evidence is invalid."""


def binary_mask_sha256(mask: np.ndarray) -> str:
    array = np.asarray(mask)
    if array.ndim != 2 or array.dtype != np.bool_:
        raise DisagreementError("normalized mask must be a 2D boolean array")
    height, width = array.shape
    digest = hashlib.sha256()
    digest.update(b"MASKFACTORY_BOOL_MASK_V1\0")
    digest.update(height.to_bytes(8, "big"))
    digest.update(width.to_bytes(8, "big"))
    digest.update(np.packbits(array, bitorder="big").tobytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class NormalizedCandidate:
    proposal_id: str
    family_id: str
    source_sha256: str
    target_contract_sha256: str
    normalized_mask_sha256: str
    owner_person_index: int
    mask: np.ndarray


@dataclass(frozen=True)
class PairwiseDisagreement:
    report: dict[str, Any]
    disagreement: np.ndarray
    left_only: np.ndarray
    right_only: np.ndarray
    boundary_disagreement: np.ndarray
    ownership_disagreement: np.ndarray


def _validate_sha256(value: str, field: str) -> None:
    if SHA256.fullmatch(value) is None:
        raise DisagreementError(f"{field} must be a SHA-256")


def _boundary(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1, constant_values=False)
    interior = padded[1:-1, 1:-1]
    eroded = interior & padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    return interior & ~eroded


def _regions(mask: np.ndarray) -> list[dict[str, Any]]:
    visited = np.zeros_like(mask, dtype=np.bool_)
    height, width = mask.shape
    regions = []
    for start_y, start_x in np.argwhere(mask):
        if visited[start_y, start_x]:
            continue
        stack = [(int(start_y), int(start_x))]
        visited[start_y, start_x] = True
        pixels = []
        while stack:
            y, x = stack.pop()
            pixels.append((y, x))
            for next_y, next_x in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if (
                    0 <= next_y < height
                    and 0 <= next_x < width
                    and mask[next_y, next_x]
                    and not visited[next_y, next_x]
                ):
                    visited[next_y, next_x] = True
                    stack.append((next_y, next_x))
        ys = [pixel[0] for pixel in pixels]
        xs = [pixel[1] for pixel in pixels]
        regions.append(
            {
                "region_id": f"region_{len(regions):04d}",
                "bbox_xyxy": [min(xs), min(ys), max(xs) + 1, max(ys) + 1],
                "pixel_count": len(pixels),
            }
        )
    return regions


def _validate_candidate(candidate: NormalizedCandidate, shape: tuple[int, int]) -> None:
    if not candidate.proposal_id or not candidate.family_id:
        raise DisagreementError("candidate identity is empty")
    for value, field in (
        (candidate.source_sha256, "source_sha256"),
        (candidate.target_contract_sha256, "target_contract_sha256"),
        (candidate.normalized_mask_sha256, "normalized_mask_sha256"),
    ):
        _validate_sha256(value, field)
    if isinstance(candidate.owner_person_index, bool) or candidate.owner_person_index < 0:
        raise DisagreementError("candidate owner is invalid")
    if candidate.mask.shape != shape:
        raise DisagreementError("candidate mask geometry is not normalized")
    if candidate.normalized_mask_sha256 != binary_mask_sha256(candidate.mask):
        raise DisagreementError("candidate mask hash differs from normalized pixels")


def build_pairwise_disagreement(
    left: NormalizedCandidate,
    right: NormalizedCandidate,
    *,
    normalized_shape: tuple[int, int],
) -> PairwiseDisagreement:
    """Build exact pairwise maps and finite region metrics after normalization."""

    if len(normalized_shape) != 2 or any(value <= 0 for value in normalized_shape):
        raise DisagreementError("normalized geometry is invalid")
    _validate_candidate(left, normalized_shape)
    _validate_candidate(right, normalized_shape)
    if left.proposal_id == right.proposal_id:
        raise DisagreementError("pairwise candidates are identical")
    if left.source_sha256 != right.source_sha256:
        raise DisagreementError("pairwise source identity differs")
    if left.target_contract_sha256 != right.target_contract_sha256:
        raise DisagreementError("pairwise target identity differs")

    disagreement = np.logical_xor(left.mask, right.mask)
    left_only = left.mask & ~right.mask
    right_only = right.mask & ~left.mask
    boundary_disagreement = np.logical_xor(_boundary(left.mask), _boundary(right.mask))
    ownership_disagreement = (
        np.logical_or(left.mask, right.mask)
        if left.owner_person_index != right.owner_person_index
        else np.zeros(normalized_shape, dtype=np.bool_)
    )
    intersection = int(np.logical_and(left.mask, right.mask).sum())
    union = int(np.logical_or(left.mask, right.mask).sum())
    report = {
        "schema_version": "1.0.0",
        "normalized_shape_hw": list(normalized_shape),
        "source_sha256": left.source_sha256,
        "target_contract_sha256": left.target_contract_sha256,
        "left": {
            "proposal_id": left.proposal_id,
            "family_id": left.family_id,
            "normalized_mask_sha256": left.normalized_mask_sha256,
            "owner_person_index": left.owner_person_index,
        },
        "right": {
            "proposal_id": right.proposal_id,
            "family_id": right.family_id,
            "normalized_mask_sha256": right.normalized_mask_sha256,
            "owner_person_index": right.owner_person_index,
        },
        "metrics": {
            "intersection_pixels": intersection,
            "union_pixels": union,
            "iou": 1.0 if union == 0 else intersection / union,
            "disagreement_pixels": int(disagreement.sum()),
            "left_only_pixels": int(left_only.sum()),
            "right_only_pixels": int(right_only.sum()),
            "boundary_disagreement_pixels": int(boundary_disagreement.sum()),
            "ownership_disagreement_pixels": int(ownership_disagreement.sum()),
        },
        "map_sha256": {
            "disagreement": binary_mask_sha256(disagreement),
            "left_only": binary_mask_sha256(left_only),
            "right_only": binary_mask_sha256(right_only),
            "boundary_disagreement": binary_mask_sha256(boundary_disagreement),
            "ownership_disagreement": binary_mask_sha256(ownership_disagreement),
        },
        "regions": _regions(disagreement),
    }
    if not all(math.isfinite(float(value)) for value in report["metrics"].values()):
        raise DisagreementError("pairwise metrics are not finite")
    report["report_sha256"] = canonical_sha256(report)
    return PairwiseDisagreement(
        report=report,
        disagreement=disagreement,
        left_only=left_only,
        right_only=right_only,
        boundary_disagreement=boundary_disagreement,
        ownership_disagreement=ownership_disagreement,
    )


def build_all_pairwise_disagreements(
    candidates: list[NormalizedCandidate], *, normalized_shape: tuple[int, int]
) -> tuple[PairwiseDisagreement, ...]:
    if len(candidates) < 2:
        raise DisagreementError("at least two candidates are required")
    if len({candidate.proposal_id for candidate in candidates}) != len(candidates):
        raise DisagreementError("candidate proposal IDs are duplicated")
    return tuple(
        build_pairwise_disagreement(left, right, normalized_shape=normalized_shape)
        for left, right in combinations(candidates, 2)
    )
