"""Stable S10 automatic-QA stage boundary (doc 07 S10, doc 09)."""

from __future__ import annotations

from ..qa.production import run_s10_production, skeleton_side_vote

run_s10 = run_s10_production

__all__ = ["run_s10", "run_s10_production", "skeleton_side_vote"]
