"""Fail-closed validation for direct visual reference-screening receipts.

Reference-library tags are retrieval metadata only.  A direct visual screen may
confirm or reject a candidate's visible target, but it never supplies mask
truth, critic qualification, a promotion decision, or materialization
authority.  This module makes that boundary machine-checkable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from PIL import Image

from .continuous_contract import canonical_sha256

SCHEMA_VERSION = "maskfactory.visual_reference_direct_screening.v1"
ZERO_SHA256 = "0" * 64
ALLOWED_DECISIONS = {
    "reference_only_visual_target_confirmed",
    "rejected_for_hand_finger_candidate_selection",
}


class VisualReferenceScreeningError(ValueError):
    """A direct screening receipt is not safe to consume."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(value: object, *, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise VisualReferenceScreeningError(f"{field} is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise VisualReferenceScreeningError(f"{field} escapes its root")
    return path


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VisualReferenceScreeningError(f"{field} is invalid")
    return value


def validate_direct_reference_screening(
    receipt: Mapping[str, Any],
    *,
    repository_root: Path,
    materialized_root: Path,
) -> None:
    """Validate one source-bound direct screen without granting any authority."""

    if set(receipt) != {
        "authority_boundary",
        "reference_readiness_binding",
        "review",
        "schema_version",
        "screened_image",
        "self_sha256",
    } or receipt.get("schema_version") != SCHEMA_VERSION:
        raise VisualReferenceScreeningError("screening receipt schema is invalid")
    declared = receipt.get("self_sha256")
    sealed = dict(receipt)
    sealed["self_sha256"] = ZERO_SHA256
    if not isinstance(declared, str) or canonical_sha256(sealed) != declared:
        raise VisualReferenceScreeningError("screening receipt self hash mismatch")

    authority = _mapping(receipt["authority_boundary"], field="authority boundary")
    required_authority = {
        "critic_qualification_allowed",
        "mask_generation_allowed",
        "promotion_allowed",
        "reason",
    }
    candidate_fields = {
        "candidate_materialization_allowed",
        "candidate_selection_allowed",
    }
    if (
        not required_authority.issubset(authority)
        or not (set(authority) & candidate_fields)
        or any(
            authority.get(name) is not False
            for name in set(authority) & candidate_fields
        )
        or any(authority.get(name) is not False for name in required_authority - {"reason"})
        or not isinstance(authority.get("reason"), str)
        or not authority["reason"]
    ):
        raise VisualReferenceScreeningError("screening authority boundary is invalid")

    binding = _mapping(receipt["reference_readiness_binding"], field="readiness binding")
    if set(binding) != {"path", "raw_sha256", "self_sha256"}:
        raise VisualReferenceScreeningError("readiness binding schema is invalid")
    readiness_relative = _relative_path(binding["path"], field="readiness binding path")
    readiness_path = repository_root.resolve(strict=True).joinpath(*readiness_relative.parts)
    if not readiness_path.is_file() or _sha256(readiness_path) != binding["raw_sha256"]:
        raise VisualReferenceScreeningError("readiness binding drifted")
    try:
        readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VisualReferenceScreeningError("readiness receipt is unreadable") from exc
    if (
        readiness.get("self_sha256") != binding["self_sha256"]
        or _mapping(readiness.get("authority_boundary"), field="readiness boundary").get(
            "promotion_allowed"
        )
        is not False
        or _mapping(readiness.get("readiness"), field="readiness state").get(
            "metadata_candidate_selection_requires_direct_visual_confirmation"
        )
        is not True
    ):
        raise VisualReferenceScreeningError("readiness authority is incompatible")

    review = _mapping(receipt["review"], field="review")
    if (
        review.get("decision") not in ALLOWED_DECISIONS
        or review.get("evidence_basis") != "direct_pixel_review"
        or review.get("target_role") != "part_hand_fingers"
        or not isinstance(review.get("metadata_hint"), str)
        or not isinstance(review.get("observed_content"), str)
        or not review["observed_content"]
        or not isinstance(review.get("reviewer"), str)
        or not review["reviewer"]
    ):
        raise VisualReferenceScreeningError("direct review binding is invalid")
    if review["decision"] == "rejected_for_hand_finger_candidate_selection" and review.get(
        "reason"
    ) != "metadata_tag_not_visually_confirmed":
        raise VisualReferenceScreeningError("rejection reason is invalid")

    image = _mapping(receipt["screened_image"], field="screened image")
    if set(image) != {
        "bytes",
        "dimensions",
        "materialized_relative_path",
        "relative_path",
        "sha256",
        "source_group",
    }:
        raise VisualReferenceScreeningError("screened image schema is invalid")
    relative = _relative_path(
        image["materialized_relative_path"], field="materialized image path"
    )
    if (
        not isinstance(image.get("bytes"), int)
        or image["bytes"] < 1
        or not isinstance(image.get("sha256"), str)
        or len(image["sha256"]) != 64
        or not isinstance(image.get("relative_path"), str)
        or not isinstance(image.get("source_group"), str)
    ):
        raise VisualReferenceScreeningError("screened image binding is invalid")
    dimensions = _mapping(image["dimensions"], field="image dimensions")
    if set(dimensions) != {"height", "width"} or any(
        not isinstance(dimensions[name], int) or dimensions[name] < 1
        for name in dimensions
    ):
        raise VisualReferenceScreeningError("screened image dimensions are invalid")
    image_path = materialized_root.resolve(strict=True).joinpath(*relative.parts)
    if (
        not image_path.is_file()
        or image_path.stat().st_size != image["bytes"]
        or _sha256(image_path) != image["sha256"]
    ):
        raise VisualReferenceScreeningError("screened image binding drifted")
    try:
        with Image.open(image_path) as opened:
            actual_dimensions = {"width": opened.width, "height": opened.height}
    except OSError as exc:
        raise VisualReferenceScreeningError("screened image is unreadable") from exc
    if actual_dimensions != dict(dimensions):
        raise VisualReferenceScreeningError("screened image dimensions drifted")


__all__ = [
    "ALLOWED_DECISIONS",
    "SCHEMA_VERSION",
    "VisualReferenceScreeningError",
    "validate_direct_reference_screening",
]
