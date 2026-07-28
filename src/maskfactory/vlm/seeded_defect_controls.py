"""Deterministic, hash-bound seeded defects for calibration-only controls.

The library operates only on an already admitted calibration control.  It
cannot generate a positive control, training truth, gold, package authority, or
certificate.  Every operator is explicit and all ten visual-critic defect
classes are emitted together or the operation fails without a partial set.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import numpy as np

from .calibration_corpus import DEFECT_TYPES
from .critic_catalog import canonical_sha256

SCHEMA_VERSION = "1.0.0"
CALIBRATION_ONLY_AUTHORITY = "calibration_only"
SHA256_LENGTH = 64
RECORD_KEYS = frozenset(
    {
        "record_id",
        "label_id",
        "partition",
        "control_authority",
        "admission_sha256",
        "positive_mask_sha256",
    }
)
RESOURCE_KEYS = frozenset(
    {
        "neighbor_mask",
        "wrong_label_mask",
        "opposite_side_mask",
        "other_owner_mask",
        "protected_region_mask",
    }
)
OPERATOR_TO_DEFECT = {
    "boundary_erode": "boundary",
    "boundary_dilate": "flood",
    "leakage_paste": "leakage",
    "wrong_label_swap": "wrong_label",
    "wrong_side_flip": "wrong_side",
    "hole_punch": "missing_area",
    "component_scatter": "anatomy",
    "owner_swap": "ownership",
    "protected_overlap": "protected_region",
    "transform_shift": "transform",
}
REQUIRED_RESOURCE_BY_OPERATOR = {
    "leakage_paste": "neighbor_mask",
    "wrong_label_swap": "wrong_label_mask",
    "wrong_side_flip": "opposite_side_mask",
    "owner_swap": "other_owner_mask",
    "protected_overlap": "protected_region_mask",
}


class SeededDefectControlError(ValueError):
    """A calibration-only seeded-defect request is unsafe or incomplete."""


def mask_sha256(mask: Any) -> str:
    """Hash one exact binary raster including geometry and bit representation."""

    value = _binary_mask(mask, "mask")
    return hashlib.sha256(
        f"{value.shape[0]}x{value.shape[1]}:".encode("ascii") + value.astype(np.uint8).tobytes()
    ).hexdigest()


def _binary_mask(value: Any, field: str) -> np.ndarray:
    mask = np.asarray(value)
    if mask.ndim != 2 or mask.shape[0] < 3 or mask.shape[1] < 3:
        raise SeededDefectControlError(f"{field} must be a two-dimensional raster at least 3x3")
    if mask.dtype == np.bool_:
        normalized = mask.copy()
    elif np.issubdtype(mask.dtype, np.integer) and np.isin(mask, [0, 255]).all():
        normalized = mask == 255
    else:
        raise SeededDefectControlError(f"{field} must contain only binary 0/255 or boolean pixels")
    if not normalized.any():
        raise SeededDefectControlError(f"{field} is empty")
    return normalized


def _validate_record(record: Mapping[str, Any], positive_mask: np.ndarray) -> None:
    if not isinstance(record, Mapping) or set(record) != RECORD_KEYS:
        raise SeededDefectControlError(
            "seeded-defect control record fields are incomplete or unknown"
        )
    for field in ("record_id", "label_id"):
        if not isinstance(record[field], str) or not record[field].strip():
            raise SeededDefectControlError(f"seeded-defect {field} is invalid")
    if record["partition"] not in {"calibration", "qualification_holdout"}:
        raise SeededDefectControlError("seeded-defect partition is invalid")
    if record["control_authority"] != CALIBRATION_ONLY_AUTHORITY:
        raise SeededDefectControlError("seeded defects require a calibration-only positive control")
    for field in ("admission_sha256", "positive_mask_sha256"):
        value = record[field]
        if (
            not isinstance(value, str)
            or len(value) != SHA256_LENGTH
            or any(char not in "0123456789abcdef" for char in value)
        ):
            raise SeededDefectControlError(f"seeded-defect {field} is not a SHA-256")
    if record["positive_mask_sha256"] != mask_sha256(positive_mask):
        raise SeededDefectControlError("seeded-defect positive mask hash drifted")


def _dilate(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    return np.logical_or.reduce(
        [
            padded[row : row + mask.shape[0], column : column + mask.shape[1]]
            for row in range(3)
            for column in range(3)
        ]
    )


def _erode(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    return np.logical_and.reduce(
        [
            padded[row : row + mask.shape[0], column : column + mask.shape[1]]
            for row in range(3)
            for column in range(3)
        ]
    )


def _shift(mask: np.ndarray, *, x: int, y: int) -> np.ndarray:
    shifted = np.zeros_like(mask)
    source_y0, source_y1 = max(0, -y), min(mask.shape[0], mask.shape[0] - y)
    source_x0, source_x1 = max(0, -x), min(mask.shape[1], mask.shape[1] - x)
    target_y0, target_x0 = max(0, y), max(0, x)
    if source_y0 >= source_y1 or source_x0 >= source_x1:
        raise SeededDefectControlError("seeded-defect transform shift has no retained pixels")
    shifted[
        target_y0 : target_y0 + source_y1 - source_y0,
        target_x0 : target_x0 + source_x1 - source_x0,
    ] = mask[source_y0:source_y1, source_x0:source_x1]
    return shifted


def _hole_punch(mask: np.ndarray) -> np.ndarray:
    rows, columns = np.where(mask)
    center_y = int(round(float(rows.mean())))
    center_x = int(round(float(columns.mean())))
    punched = mask.copy()
    punched[max(0, center_y - 1) : center_y + 2, max(0, center_x - 1) : center_x + 2] = False
    return punched


def _component_scatter(mask: np.ndarray) -> np.ndarray:
    result = mask.copy()
    foreground = np.argwhere(mask)
    background = np.argwhere(~mask)
    if len(foreground) < 2 or not len(background):
        raise SeededDefectControlError(
            "seeded-defect component scatter lacks foreground/background"
        )
    source_y, source_x = foreground[len(foreground) // 2]
    target_y, target_x = background[-1]
    result[source_y, source_x] = False
    result[target_y, target_x] = True
    return result


def _required_resource(resources: Mapping[str, np.ndarray], operator_id: str) -> np.ndarray:
    key = REQUIRED_RESOURCE_BY_OPERATOR[operator_id]
    value = resources.get(key)
    if value is None:
        raise SeededDefectControlError(f"seeded-defect {operator_id} requires {key}")
    return value


def _apply_operator(
    operator_id: str, positive_mask: np.ndarray, resources: Mapping[str, np.ndarray]
) -> np.ndarray:
    if operator_id == "boundary_erode":
        return _erode(positive_mask)
    if operator_id == "boundary_dilate":
        return _dilate(positive_mask)
    if operator_id == "leakage_paste":
        return positive_mask | _required_resource(resources, operator_id)
    if operator_id in {"wrong_label_swap", "wrong_side_flip", "owner_swap"}:
        return _required_resource(resources, operator_id).copy()
    if operator_id == "hole_punch":
        return _hole_punch(positive_mask)
    if operator_id == "component_scatter":
        return _component_scatter(positive_mask)
    if operator_id == "protected_overlap":
        return positive_mask | _required_resource(resources, operator_id)
    if operator_id == "transform_shift":
        return _shift(positive_mask, x=2, y=1)
    raise SeededDefectControlError(f"unknown seeded-defect operator: {operator_id}")


def build_seeded_defect_controls(
    *,
    record: Mapping[str, Any],
    positive_mask: Any,
    resources: Mapping[str, Any],
) -> dict[str, Any]:
    """Generate the full negative taxonomy from one admitted positive control.

    No operation is allowed to degrade into a no-op.  Output files remain the
    caller's responsibility; this pure builder makes their provenance and
    deterministic contents explicit before any panel render or screening.
    """

    normalized_positive = _binary_mask(positive_mask, "positive_mask")
    _validate_record(record, normalized_positive)
    if not isinstance(resources, Mapping) or not set(resources) <= RESOURCE_KEYS:
        raise SeededDefectControlError("seeded-defect resource keys are invalid")
    normalized_resources = {key: _binary_mask(value, key) for key, value in resources.items()}
    for key, value in normalized_resources.items():
        if value.shape != normalized_positive.shape:
            raise SeededDefectControlError(f"seeded-defect {key} geometry drifted")
    rows = []
    for operator_id, defect_type in OPERATOR_TO_DEFECT.items():
        candidate = _apply_operator(operator_id, normalized_positive, normalized_resources)
        candidate = _binary_mask(candidate, f"seeded-defect {operator_id} output")
        changed_pixel_count = int(np.count_nonzero(candidate != normalized_positive))
        if changed_pixel_count == 0:
            raise SeededDefectControlError(f"seeded-defect {operator_id} is a no-op")
        rows.append(
            {
                "operator_id": operator_id,
                "defect_type": defect_type,
                "mask_sha256": mask_sha256(candidate),
                "changed_pixel_count": changed_pixel_count,
                "mask": candidate,
            }
        )
    if {row["defect_type"] for row in rows} != set(DEFECT_TYPES):
        raise SeededDefectControlError("seeded-defect library does not cover the full taxonomy")
    manifest_rows = [{key: value for key, value in row.items() if key != "mask"} for row in rows]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "record_id": record["record_id"],
        "label_id": record["label_id"],
        "partition": record["partition"],
        "control_authority": CALIBRATION_ONLY_AUTHORITY,
        "admission_sha256": record["admission_sha256"],
        "positive_mask_sha256": record["positive_mask_sha256"],
        "resource_mask_sha256": {
            key: mask_sha256(value) for key, value in sorted(normalized_resources.items())
        },
        "negatives": manifest_rows,
        "authority_claimed": False,
        "gold_or_training_truth_allowed": False,
        "certificate_issuance_allowed": False,
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    return {"manifest": manifest, "negatives": rows}
