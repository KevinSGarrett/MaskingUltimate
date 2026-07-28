"""Stable S12 CVAT review-package handoff boundary (docs 07/11)."""

from __future__ import annotations

from ..cvat_bridge.push import push_images
from ..review_package import (
    assemble_review_package,
    finalize_image_package_index,
    snapshot_draft_baseline,
)

run_s12 = assemble_review_package

__all__ = [
    "assemble_review_package",
    "finalize_image_package_index",
    "push_images",
    "run_s12",
    "snapshot_draft_baseline",
]
