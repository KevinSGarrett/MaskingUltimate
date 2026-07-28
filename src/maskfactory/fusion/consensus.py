"""Stable public boundary for the S09 consensus engine (docs 05/07)."""

from __future__ import annotations

from ..stages.s09_fusion import (
    FusionError,
    FusionResult,
    configure_determinism,
    fuse_consensus,
    make_contact_band,
    make_waist_band,
)

__all__ = [
    "FusionError",
    "FusionResult",
    "configure_determinism",
    "fuse_consensus",
    "make_contact_band",
    "make_waist_band",
]
