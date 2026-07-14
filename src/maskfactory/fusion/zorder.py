"""Z-order arbitration for contested S09 consensus pixels (doc 07 S09)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np


@dataclass(frozen=True)
class ZOrderDecision:
    winner: str
    loser: str
    reason: str


@dataclass(frozen=True)
class OcclusionRecord:
    occluding_part: str
    occluded_part: str
    reason: str
    contested_pixels: int
    occluded_visibility: str = "partially_visible"


def apply_zorder(
    stack: np.ndarray,
    names: tuple[str, ...],
    contested: np.ndarray,
    decisions: Iterable[ZOrderDecision],
    authority: Any,
    *,
    error_type: type[Exception] = ValueError,
) -> tuple[OcclusionRecord, ...]:
    """Boost configured winners only where two supported labels contest a pixel."""
    scores = np.asarray(stack)
    conflict = np.asarray(contested).astype(bool)
    if scores.ndim != 3 or conflict.shape != scores.shape[1:] or len(names) != len(scores):
        raise error_type("z-order inputs do not share label/plane geometry")
    indexed = {name: index for index, name in enumerate(names)}
    if len(indexed) != len(names):
        raise error_type("z-order names must be unique")
    records = []
    automatic = tuple(
        ZOrderDecision("hair", loser, "hair_front_overlap")
        for loser in ("head_face", "neck", "left_shoulder", "right_shoulder")
        if "hair" in indexed and loser in indexed
    )
    for decision in (*automatic, *tuple(decisions)):
        if decision.winner not in indexed or decision.loser not in indexed:
            raise error_type(f"z-order label missing from evidence: {decision}")
        authority.label(decision.winner)
        authority.label(decision.loser)
        winner, loser = indexed[decision.winner], indexed[decision.loser]
        pixels = conflict & (scores[winner] > 0.4) & (scores[loser] > 0.4)
        count = int(pixels.sum())
        if count:
            scores[winner, pixels] = np.maximum(scores[winner, pixels], 1.0001)
            records.append(OcclusionRecord(decision.winner, decision.loser, decision.reason, count))
    return tuple(records)


__all__ = ["OcclusionRecord", "ZOrderDecision", "apply_zorder"]
