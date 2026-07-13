"""Convert real mask artifacts and provenance into tournament evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from ..io.hashing import sha256_file
from ..qa.metrics import boundary_f, iou
from .tournament import CandidateEvidence


@dataclass(frozen=True)
class MaskCandidateInput:
    candidate_id: str
    mask_path: Path
    independent_sources: tuple[str, ...]
    critic_pass_weight: float
    critic_disagreement: bool
    pose_consistency: float
    block_qc_ids: tuple[str, ...] = ()


def build_mask_candidate_evidence(
    candidates: tuple[MaskCandidateInput, ...],
    *,
    protected_neighbor: np.ndarray,
    mutually_exclusive: np.ndarray,
    ontology_max_components: int,
) -> tuple[CandidateEvidence, ...]:
    if not candidates:
        raise ValueError("mask candidate adapter requires at least one candidate")
    masks = [_read_candidate(candidate.mask_path) for candidate in candidates]
    shape = masks[0].shape
    protected = np.asarray(protected_neighbor).astype(bool)
    exclusive = np.asarray(mutually_exclusive).astype(bool)
    if (
        protected.shape != shape
        or exclusive.shape != shape
        or any(mask.shape != shape for mask in masks)
    ):
        raise ValueError("candidate/protected/exclusive mask dimensions differ")
    output = []
    for index, (candidate, mask) in enumerate(zip(candidates, masks, strict=True)):
        others = [other for other_index, other in enumerate(masks) if other_index != index]
        consensus = float(np.mean([iou(mask, other) for other in others])) if others else 1.0
        boundary = float(np.mean([boundary_f(mask, other) for other in others])) if others else 1.0
        area = max(1, int(mask.sum()))
        output.append(
            CandidateEvidence(
                candidate.candidate_id,
                str(candidate.mask_path),
                sha256_file(candidate.mask_path),
                len(set(candidate.independent_sources)),
                consensus,
                boundary,
                float(candidate.pose_consistency),
                float(candidate.critic_pass_weight),
                bool(candidate.critic_disagreement),
                float(np.count_nonzero(mask & protected) / area),
                float(np.count_nonzero(mask & exclusive) / area),
                int(ndimage.label(mask)[1]),
                int(ontology_max_components),
                _strict_mask_format(candidate.mask_path, expected_shape=shape),
                tuple(candidate.block_qc_ids),
            )
        )
    return tuple(output)


def _read_candidate(path: Path) -> np.ndarray:
    image = Image.open(path)
    array = np.asarray(image)
    if array.ndim != 2:
        raise ValueError(f"candidate mask must be one-channel: {path}")
    return array != 0


def _strict_mask_format(path: Path, *, expected_shape: tuple[int, int]) -> bool:
    image = Image.open(path)
    array = np.asarray(image)
    return (
        image.mode == "L"
        and array.shape == expected_shape
        and set(np.unique(array).tolist()) <= {0, 255}
    )


__all__ = ["MaskCandidateInput", "build_mask_candidate_evidence"]
