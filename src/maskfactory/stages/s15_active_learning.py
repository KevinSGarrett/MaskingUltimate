"""Stable S15 active-learning stage boundary (docs 07/12)."""

from __future__ import annotations

from ..datasets.active_learning import run_active_learning

run_s15 = run_active_learning

__all__ = ["run_active_learning", "run_s15"]
