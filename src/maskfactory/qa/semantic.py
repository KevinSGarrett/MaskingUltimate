"""QC-011..024 geometric and semantic verdict battery."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import numpy as np
from scipy import ndimage

from ..ontology import Ontology, get_ontology
from .checks import QcResult
from .metrics import component_count, hole_ratio, iou


@dataclass(frozen=True)
class SemanticInputs:
    atomic_parts: Mapping[str, np.ndarray]
    silhouette: np.ndarray
    protected: np.ndarray
    skin_derived: np.ndarray
    clothing: np.ndarray
    person_bbox_area: int
    side_votes: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    pose_absent_parts: frozenset[str] = frozenset()
    crop_roundtrips: Mapping[str, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)
    breast_skin: np.ndarray | None = None
    material_skin: np.ndarray | None = None
    projected: Mapping[str, np.ndarray] = field(default_factory=dict)
    projected_allowed_region: np.ndarray | None = None
    projected_files_in_masks: tuple[str, ...] = ()
    lace_or_sheer_covered: frozenset[str] = frozenset()
    source_gray: np.ndarray | None = None
    visibility_states: Mapping[str, str] = field(default_factory=dict)
    amodal_areas: Mapping[str, int] = field(default_factory=dict)
    densepose_front_fraction: Mapping[str, float] = field(default_factory=dict)


def run_semantic_qc(
    inputs: SemanticInputs, *, ontology: Ontology | None = None
) -> tuple[QcResult, ...]:
    authority = ontology or get_ontology()
    masks = {name: np.asarray(mask).astype(bool) for name, mask in inputs.atomic_parts.items()}
    shape = _common_shape(masks, inputs.silhouette)
    silhouette = _shape_mask(inputs.silhouette, shape, "silhouette")
    protected = _shape_mask(inputs.protected, shape, "protected")
    skin = _shape_mask(inputs.skin_derived, shape, "skin_derived")
    clothing = _shape_mask(inputs.clothing, shape, "clothing")
    return (
        _qc011(masks),
        _qc012(masks, silhouette),
        _qc013(masks, protected, skin, clothing),
        _qc014(masks, inputs.side_votes),
        _qc015(masks, inputs.person_bbox_area, authority),
        _qc016(masks, inputs.pose_absent_parts),
        _qc017(masks, authority),
        _qc018(inputs.crop_roundtrips),
        _qc019(masks, inputs.breast_skin, inputs.material_skin, shape),
        _qc020(
            inputs.projected,
            inputs.projected_allowed_region,
            inputs.projected_files_in_masks,
            shape,
        ),
        _qc021(masks, inputs.lace_or_sheer_covered),
        _qc022(masks, inputs.source_gray, shape),
        _qc023(masks, inputs.visibility_states, inputs.amodal_areas),
        _qc024(masks, inputs.densepose_front_fraction),
    )


def _qc011(masks):
    claimed = np.zeros(next(iter(masks.values())).shape, dtype=np.uint16)
    overlap = 0
    for mask in masks.values():
        overlap += int(np.count_nonzero((claimed > 0) & mask))
        claimed += mask
    return _result(11, "atomic_exclusivity", overlap == 0, f"overlap_px={overlap}", "BLOCK")


def _qc012(masks, silhouette):
    union = np.logical_or.reduce(tuple(masks.values()))
    area = int(union.sum())
    outside = int(np.count_nonzero(union & ~silhouette))
    ratio = outside / area if area else 0.0
    return _result(
        12, "inside_silhouette", ratio <= 0.002, f"outside_fraction={ratio:.8f}", "ROUTE"
    )


def _qc013(masks, protected, skin, clothing):
    violations = {}
    for name, mask in masks.items():
        area = int(mask.sum())
        ratio = int(np.count_nonzero(mask & protected)) / area if area else 0.0
        if ratio > 0.005:
            violations[name] = ratio
    skin_clothing = int(np.count_nonzero(skin & clothing))
    passed = not violations and skin_clothing == 0
    return _result(
        13,
        "protected_overlap",
        passed,
        f"parts={violations}, skin_clothing_px={skin_clothing}",
        "BLOCK",
    )


def _qc014(masks, votes):
    wrong = []
    unavailable = []
    for name, mask in masks.items():
        expected = (
            "left" if name.startswith("left_") else "right" if name.startswith("right_") else None
        )
        if expected is None or not mask.any():
            continue
        label_votes = tuple(vote for vote in votes.get(name, ()) if vote in {"left", "right"})
        if len(label_votes) < 2:
            unavailable.append(name)
        elif sum(vote == expected for vote in label_votes) < 2:
            wrong.append(name)
    return _result(
        14,
        "left_right_consistency",
        not wrong and not unavailable,
        f"wrong={wrong}, insufficient_votes={unavailable}",
        "BLOCK",
    )


def _qc015(masks, bbox_area, ontology):
    if bbox_area <= 0:
        return _result(15, "area_sanity", False, "person bbox area unavailable", "ROUTE")
    wrong = []
    for name, mask in masks.items():
        label = ontology.label(name, require_enabled=True)
        low, high = label.expected_area_pct_range
        percent = 100 * int(mask.sum()) / bbox_area
        if mask.any() and not low <= percent <= high:
            wrong.append(f"{name}={percent:.4f}% not [{low},{high}]")
    return _result(15, "area_sanity", not wrong, "; ".join(wrong) or "all in range", "ROUTE")


def _qc016(masks, absent):
    wrong = sorted(name for name in absent if name in masks and masks[name].any())
    return _result(16, "visibility_vs_frame", not wrong, f"absent_with_mask={wrong}", "BLOCK")


def _qc017(masks, ontology):
    wrong = []
    for name, mask in masks.items():
        maximum = ontology.label(name, require_enabled=True).max_components
        count = component_count(mask)
        if count > maximum:
            wrong.append(f"{name}={count}>{maximum}")
    return _result(17, "components_limit", not wrong, "; ".join(wrong) or "within limits", "ROUTE")


def _qc018(roundtrips):
    wrong = {
        name: iou(crop, full)
        for name, (crop, full) in roundtrips.items()
        if iou(crop, full) < 0.995
    }
    return _result(18, "crop_roundtrip", not wrong, f"below_0.995={wrong}", "BLOCK")


def _qc019(masks, breast_skin, material_skin, shape):
    if breast_skin is None or material_skin is None:
        return _result(
            19,
            "breast_skin_identity",
            False,
            "required breast/material evidence unavailable",
            "BLOCK",
        )
    expected = (
        masks.get("left_breast", np.zeros(shape, bool))
        | masks.get("right_breast", np.zeros(shape, bool))
    ) & _shape_mask(material_skin, shape, "material_skin")
    actual = _shape_mask(breast_skin, shape, "breast_skin")
    mismatch = int(np.count_nonzero(expected ^ actual))
    return _result(19, "breast_skin_identity", mismatch == 0, f"mismatch_px={mismatch}", "BLOCK")


def _qc020(projected, allowed, forbidden_files, shape):
    if projected and allowed is None:
        return _result(
            20, "projected_containment", False, "allowed torso/clothing region unavailable", "BLOCK"
        )
    allowed_mask = (
        np.zeros(shape, bool)
        if allowed is None
        else _shape_mask(allowed, shape, "projected_allowed")
    )
    outside = {
        name: int(np.count_nonzero(_shape_mask(mask, shape, name) & ~allowed_mask))
        for name, mask in projected.items()
    }
    outside = {name: count for name, count in outside.items() if count}
    passed = not outside and not forbidden_files
    return _result(
        20,
        "projected_containment",
        passed,
        f"outside={outside}, in_masks={list(forbidden_files)}",
        "BLOCK",
    )


def _qc021(masks, lace_covered):
    wrong = {
        name: hole_ratio(mask)
        for name, mask in masks.items()
        if name != "hair" and name not in lace_covered and hole_ratio(mask) > 0.01
    }
    return _result(21, "hole_ratio", not wrong, f"above_1pct={wrong}", "WARN")


def _qc022(masks, source, shape):
    if source is None:
        return _result(22, "edge_alignment", False, "source gradient unavailable", "WARN")
    gray = np.asarray(source, dtype=np.float32)
    if gray.shape != shape:
        return _result(22, "edge_alignment", False, "source gradient dimensions differ", "WARN")
    gradient = np.hypot(ndimage.sobel(gray, axis=0), ndimage.sobel(gray, axis=1))
    wrong = []
    for name, mask in masks.items():
        if not mask.any():
            continue
        contour = mask ^ ndimage.binary_erosion(mask)
        band = ndimage.binary_dilation(contour, iterations=3)
        contour_mean = float(gradient[contour].mean())
        band_mean = float(gradient[band].mean())
        ratio = contour_mean / band_mean if band_mean else 1.0
        if ratio < 0.6:
            wrong.append(f"{name}={ratio:.4f}")
    return _result(22, "edge_alignment", not wrong, "; ".join(wrong) or "aligned", "WARN")


def _qc023(masks, states, amodal):
    wrong = []
    for name, state in states.items():
        if name not in masks or name not in amodal or amodal[name] <= 0:
            continue
        fraction = int(masks[name].sum()) / amodal[name]
        if state == "visible" and fraction < 0.9:
            wrong.append(f"{name}:visible={fraction:.4f}")
        elif state == "partially_visible" and not 0.1 <= fraction <= 0.9:
            wrong.append(f"{name}:partial={fraction:.4f}")
    return _result(
        23, "visibility_state_consistency", not wrong, "; ".join(wrong) or "consistent", "ROUTE"
    )


def _qc024(masks, fractions):
    wrong = []
    for name, front_fraction in fractions.items():
        if name not in masks or not masks[name].any() or not 0 <= front_fraction <= 1:
            continue
        expects_back = name in {"back_upper_torso", "back_lower_torso", "left_glute", "right_glute"}
        if (expects_back and front_fraction >= 0.5) or (not expects_back and front_fraction < 0.5):
            wrong.append(f"{name}={front_fraction:.4f}")
    return _result(
        24, "front_back_surface", not wrong, "; ".join(wrong) or "surface majority matches", "ROUTE"
    )


def _common_shape(masks, silhouette):
    shape = np.asarray(silhouette).shape
    if len(shape) != 2 or not masks or any(mask.shape != shape for mask in masks.values()):
        raise ValueError("semantic QC masks must share one 2-D shape")
    return shape


def _shape_mask(value, shape, name):
    mask = np.asarray(value).astype(bool)
    if mask.shape != shape:
        raise ValueError(f"{name} dimensions differ")
    return mask


def _result(number, name, passed, detail, severity):
    return QcResult(f"QC-{number:03d}", name, bool(passed), detail, severity)
