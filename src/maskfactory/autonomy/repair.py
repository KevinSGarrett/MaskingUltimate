"""Geometry-bound contracts for autonomous non-gold mask repair.

The repair controller never treats a corrupt draft as spatial truth. It derives a
small anatomy ROI from S05 geometry, confines pixel tools to that ROI, and applies
different change limits to ordinary boundary refinement and explicit reconstruction.
Gold authority remains outside this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from scipy import ndimage

from ..ontology import get_ontology

_POSE_SIDE_CHAINS = {
    "breast": ((5, 11), (6, 12)),
    "shoulder": ((5,), (6,)),
    "upper_arm": ((5, 7), (6, 8)),
    "elbow": ((5, 7, 9), (6, 8, 10)),
    "forearm": ((5, 7, 9), (6, 8, 10)),
    "wrist": ((5, 7, 9), (6, 8, 10)),
    "hand_base": ((5, 7, 9), (6, 8, 10)),
    "thumb": ((5, 7, 9), (6, 8, 10)),
    "index_finger": ((5, 7, 9), (6, 8, 10)),
    "middle_finger": ((5, 7, 9), (6, 8, 10)),
    "ring_finger": ((5, 7, 9), (6, 8, 10)),
    "pinky": ((5, 7, 9), (6, 8, 10)),
    "glute": ((11,), (12,)),
    "hip": ((11,), (12,)),
    "thigh": ((11, 13), (12, 14)),
    "knee": ((11, 13, 15), (12, 14, 16)),
    "calf": ((11, 13, 15), (12, 14, 16)),
    "ankle": ((11, 13, 15), (12, 14, 16)),
    "foot_base": ((11, 13, 15), (12, 14, 16)),
    "toes": ((11, 13, 15), (12, 14, 16)),
}

_HAND_TIP_INDICES = {
    "left": (95, 99, 103, 107, 111),
    "right": (116, 120, 124, 128, 132),
}
_FOOT_POINT_INDICES = {
    # COCO-WholeBody stores big toe, small toe, heel for each side. This tuple is
    # deliberately reordered to the semantic (heel, big toe, small toe) contract.
    "left": (19, 17, 18),
    "right": (22, 20, 21),
}


class AutonomousRepairError(ValueError):
    """Repair geometry or a candidate violates the fail-closed contract."""


@dataclass(frozen=True)
class RepairRegion:
    label: str
    bbox_xyxy: tuple[int, int, int, int]
    source: str
    source_quality: str


@dataclass(frozen=True)
class RepairGuardResult:
    eligible: bool
    reconstruction_mode: bool
    changed_fraction: float
    protected_overlap_fraction: float
    outside_roi_fraction: float
    area_px: int
    area_fraction_of_person: float | None
    component_count: int
    vetoes: tuple[str, ...]


@dataclass(frozen=True)
class BoundedRepairLimits:
    """Per-label limits for a reversible autonomous repair transaction."""

    maximum_attempts: int
    maximum_elapsed_seconds: float
    maximum_resource_units: float
    maximum_no_progress_attempts: int
    minimum_score_improvement_ppm: int


@dataclass(frozen=True)
class RepairAttempt:
    """An immutable, evaluated child hypothesis descended from one parent."""

    accepted_parent_id: str
    hypothesis_id: str
    score_ppm: int
    elapsed_seconds: float
    resource_units: float


@dataclass(frozen=True)
class BoundedRepairDecision:
    """A decision that never creates a human-review queue."""

    outcome: str
    reason: str
    accepted_parent_id: str
    attempt_number: int
    no_progress_count: int
    rollback_required: bool


def repair_limits_from_policy(policy: Mapping[str, Any]) -> BoundedRepairLimits:
    """Extract the finite repair budget from the governed autonomy policy."""
    try:
        limits = BoundedRepairLimits(
            maximum_attempts=int(policy["maximum_attempts_per_label"]),
            maximum_elapsed_seconds=float(policy["maximum_elapsed_seconds_per_label"]),
            maximum_resource_units=float(policy["maximum_resource_units_per_label"]),
            maximum_no_progress_attempts=int(policy["maximum_no_progress_attempts"]),
            minimum_score_improvement_ppm=int(policy["minimum_score_improvement_ppm"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AutonomousRepairError("bounded repair policy limits are invalid") from exc
    if (
        limits.maximum_attempts < 1
        or limits.maximum_elapsed_seconds <= 0
        or limits.maximum_resource_units <= 0
        or limits.maximum_no_progress_attempts < 1
        or not 0 <= limits.minimum_score_improvement_ppm <= 1_000_000
    ):
        raise AutonomousRepairError("bounded repair policy limits are outside their safe range")
    return limits


def decide_bounded_repair(
    *,
    accepted_parent_id: str,
    hypothesis_id: str,
    guard: RepairGuardResult,
    current_score_ppm: int,
    attempt_elapsed_seconds: float,
    attempt_resource_units: float,
    limits: BoundedRepairLimits,
    history: tuple[RepairAttempt, ...] = (),
) -> BoundedRepairDecision:
    """Accept a guarded child, retry with a distinct hypothesis, or abstain.

    Every non-acceptance result requires rollback to ``accepted_parent_id``.  The
    controller deliberately has no human-queue outcome: exhausted, unsafe, or
    non-progressing work becomes a typed autonomous abstention.
    """
    if not isinstance(accepted_parent_id, str) or not accepted_parent_id:
        raise AutonomousRepairError("accepted repair parent identity is required")
    if (
        not isinstance(guard, RepairGuardResult)
        or not isinstance(hypothesis_id, str)
        or not hypothesis_id
        or not isinstance(current_score_ppm, int)
        or isinstance(current_score_ppm, bool)
        or not 0 <= current_score_ppm <= 1_000_000
        or not np.isfinite(attempt_elapsed_seconds)
        or attempt_elapsed_seconds < 0
        or not np.isfinite(attempt_resource_units)
        or attempt_resource_units < 0
    ):
        raise AutonomousRepairError("bounded repair attempt fields are invalid")
    if any(
        not isinstance(attempt, RepairAttempt)
        or attempt.accepted_parent_id != accepted_parent_id
        or not isinstance(attempt.hypothesis_id, str)
        or not attempt.hypothesis_id
        or not isinstance(attempt.score_ppm, int)
        or isinstance(attempt.score_ppm, bool)
        or not 0 <= attempt.score_ppm <= 1_000_000
        or not np.isfinite(attempt.elapsed_seconds)
        or attempt.elapsed_seconds < 0
        or not np.isfinite(attempt.resource_units)
        or attempt.resource_units < 0
        for attempt in history
    ):
        raise AutonomousRepairError("repair history is not bound to the accepted parent")
    if len({attempt.hypothesis_id for attempt in history}) != len(history):
        raise AutonomousRepairError("repair history contains duplicate hypotheses")

    attempt_number = len(history) + 1
    common = {
        "accepted_parent_id": accepted_parent_id,
        "attempt_number": attempt_number,
        "rollback_required": True,
    }
    if attempt_number > limits.maximum_attempts:
        return BoundedRepairDecision(
            "rolled_back_abstain", "attempt_cap_exhausted", no_progress_count=0, **common
        )
    if hypothesis_id in {attempt.hypothesis_id for attempt in history}:
        return BoundedRepairDecision(
            "rolled_back_abstain", "hypothesis_not_distinct", no_progress_count=0, **common
        )
    if (
        sum(attempt.elapsed_seconds for attempt in history) + attempt_elapsed_seconds
        > limits.maximum_elapsed_seconds
    ):
        return BoundedRepairDecision(
            "rolled_back_abstain", "time_cap_exhausted", no_progress_count=0, **common
        )
    if (
        sum(attempt.resource_units for attempt in history) + attempt_resource_units
        > limits.maximum_resource_units
    ):
        return BoundedRepairDecision(
            "rolled_back_abstain", "resource_cap_exhausted", no_progress_count=0, **common
        )

    previous_score = history[-1].score_ppm if history else None
    no_progress_count = (
        0
        if previous_score is None
        or current_score_ppm - previous_score >= limits.minimum_score_improvement_ppm
        else _trailing_no_progress_count(history, limits) + 1
    )
    if no_progress_count >= limits.maximum_no_progress_attempts:
        return BoundedRepairDecision(
            "rolled_back_abstain",
            "no_progress_cap_exhausted",
            no_progress_count=no_progress_count,
            **common,
        )
    if not guard.eligible:
        if attempt_number >= limits.maximum_attempts:
            return BoundedRepairDecision(
                "rolled_back_abstain",
                "unsafe_candidate_at_attempt_cap",
                no_progress_count=no_progress_count,
                **common,
            )
        return BoundedRepairDecision(
            "rolled_back_retry_distinct_hypothesis",
            "candidate_guard_veto:" + ",".join(guard.vetoes),
            no_progress_count=no_progress_count,
            **common,
        )
    return BoundedRepairDecision(
        "accepted_reversible_repair",
        "bounded_guard_passed",
        no_progress_count=no_progress_count,
        rollback_required=False,
        accepted_parent_id=accepted_parent_id,
        attempt_number=attempt_number,
    )


def _trailing_no_progress_count(
    history: tuple[RepairAttempt, ...], limits: BoundedRepairLimits
) -> int:
    if len(history) < 2:
        return 0
    count = 0
    for previous, current in zip(history, history[1:]):
        if current.score_ppm - previous.score_ppm < limits.minimum_score_improvement_ppm:
            count += 1
        else:
            count = 0
    return count


def load_repair_regions(
    prompts_path: Path | None,
    *,
    image_shape: tuple[int, int],
    padding_fraction: float = 0.12,
) -> dict[str, RepairRegion]:
    """Load S05 prompt boxes as side-aware correction ROIs."""
    if prompts_path is None or not Path(prompts_path).is_file():
        return {}
    document = json.loads(Path(prompts_path).read_text(encoding="utf-8"))
    if document.get("schema_version") != "1.0.0" or not isinstance(document.get("plans"), list):
        raise AutonomousRepairError("S05 repair hints require schema 1.0.0 plans")
    boxes: dict[str, list[tuple[int, int, int, int]]] = {}
    qualities: dict[str, list[str]] = {}
    for index, plan in enumerate(document["plans"]):
        if not isinstance(plan, Mapping):
            raise AutonomousRepairError(f"S05 repair plan {index} must be an object")
        label = str(plan.get("label", ""))
        get_ontology().label(label)
        box = _validated_box(plan.get("box_xyxy"), image_shape)
        boxes.setdefault(label, []).append(box)
        qualities.setdefault(label, []).append(str(plan.get("prior_quality", "unknown")))
    return {
        label: RepairRegion(
            label,
            expand_box(_union_boxes(label_boxes), image_shape, padding_fraction),
            "s05_geometry_prompt",
            ",".join(sorted(set(qualities[label]))),
        )
        for label, label_boxes in boxes.items()
    }


def merge_specialist_repair_regions(
    regions: Mapping[str, RepairRegion],
    *,
    label_metadata: Mapping[str, tuple[Mapping[str, Any], ...]],
    image_shape: tuple[int, int],
    padding_fraction: float = 0.12,
    minimum_confidence: float = 0.5,
    oversized_ratio: float = 2.5,
) -> dict[str, RepairRegion]:
    """Replace a pathological S05 ROI with a contained high-confidence specialist box.

    S05 normally wins. A specialist wins only when its center lies inside the S05 ROI and
    the S05 area is grossly larger, which catches broken limb chains without allowing an
    unrelated detection to redirect a sided repair.
    """
    output = dict(regions)
    for label, records in label_metadata.items():
        candidates = []
        for record in records:
            if float(record.get("confidence", 0)) < minimum_confidence:
                continue
            try:
                box = _validated_box(
                    tuple(int(round(float(value))) for value in record.get("bbox_xyxy", ())),
                    image_shape,
                )
            except (AutonomousRepairError, TypeError, ValueError):
                continue
            candidates.append((float(record["confidence"]), box, str(record.get("detector_key"))))
        if not candidates:
            continue
        confidence, specialist_box, detector_key = max(candidates, key=lambda item: item[0])
        existing = output.get(label)
        should_replace = existing is None
        if existing is not None:
            existing_area = _box_area(existing.bbox_xyxy)
            specialist_area = _box_area(specialist_box)
            center_x = (specialist_box[0] + specialist_box[2]) / 2
            center_y = (specialist_box[1] + specialist_box[3]) / 2
            contained_center = (
                existing.bbox_xyxy[0] <= center_x < existing.bbox_xyxy[2]
                and existing.bbox_xyxy[1] <= center_y < existing.bbox_xyxy[3]
            )
            should_replace = contained_center and existing_area > oversized_ratio * specialist_area
        if should_replace:
            output[label] = RepairRegion(
                label,
                expand_box(specialist_box, image_shape, padding_fraction),
                "specialist_box_replaces_oversized_s05" if existing else "specialist_box",
                f"{detector_key}:{confidence:.6f}",
            )
    return output


def expand_box(
    box_xyxy: tuple[int, int, int, int],
    image_shape: tuple[int, int],
    padding_fraction: float,
) -> tuple[int, int, int, int]:
    if not 0 <= padding_fraction <= 1:
        raise AutonomousRepairError("repair ROI padding must be within 0..1")
    left, top, right, bottom = _validated_box(box_xyxy, image_shape)
    height, width = image_shape
    pad_x = max(2, round((right - left) * padding_fraction))
    pad_y = max(2, round((bottom - top) * padding_fraction))
    return (
        max(0, left - pad_x),
        max(0, top - pad_y),
        min(width, right + pad_x),
        min(height, bottom + pad_y),
    )


def normalized_roi_points_to_source(
    points: tuple[tuple[int, int], ...],
    roi_xyxy: tuple[int, int, int, int],
    image_shape: tuple[int, int],
) -> tuple[tuple[int, int], ...]:
    """Map provider 0..1000 ROI coordinates into full-source pixels."""
    left, top, right, bottom = _validated_box(roi_xyxy, image_shape)
    width = right - left
    height = bottom - top
    output = []
    for point in points:
        if (
            len(point) != 2
            or isinstance(point[0], bool)
            or isinstance(point[1], bool)
            or not all(isinstance(value, int) and 0 <= value <= 1000 for value in point)
        ):
            raise AutonomousRepairError("repair points must be integer ROI coordinates 0..1000")
        output.append(
            (
                min(right - 1, left + round(point[0] * max(0, width - 1) / 1000)),
                min(bottom - 1, top + round(point[1] * max(0, height - 1) / 1000)),
            )
        )
    return tuple(output)


def build_pose_side_evidence(
    label: str,
    pose: Mapping[str, Any] | None,
    *,
    context_origin_xy: tuple[int, int],
    candidate_mask: np.ndarray | None = None,
    confidence_min: float = 0.3,
) -> dict[str, Any] | None:
    """Build explicit character-side evidence from COCO semantic joint indices.

    Screen position is deliberately not semantic authority: crossed limbs can put the
    character-right foot on either side of the image. The COCO joint identity chain is
    stable, so reviewers receive both named chains and the candidate-to-chain distances.
    """
    if label.startswith("left_"):
        expected_side, suffix = "left", label.removeprefix("left_")
    elif label.startswith("right_"):
        expected_side, suffix = "right", label.removeprefix("right_")
    else:
        return None
    chains = _POSE_SIDE_CHAINS.get(suffix)
    if pose is None or chains is None:
        return None
    points = {
        int(item.get("index", -1)): item
        for item in pose.get("keypoints", ())
        if isinstance(item, Mapping)
    }
    origin_x, origin_y = context_origin_xy

    def materialize(indices: tuple[int, ...]) -> list[dict[str, Any]] | None:
        output = []
        for index in indices:
            point = points.get(index)
            if point is None or float(point.get("confidence", 0)) < confidence_min:
                return None
            output.append(
                {
                    "coco_index": index,
                    "x": round(float(point["x"]) - origin_x, 3),
                    "y": round(float(point["y"]) - origin_y, 3),
                    "confidence": round(float(point["confidence"]), 6),
                }
            )
        return output

    left_chain = materialize(chains[0])
    right_chain = materialize(chains[1])
    if left_chain is None or right_chain is None:
        return None
    evidence: dict[str, Any] = {
        "authority": "coco_semantic_joint_identity",
        "expected_character_side": expected_side,
        "coordinate_space": "source_context_crop_pixels",
        "left_chain": left_chain,
        "right_chain": right_chain,
        "instruction": (
            "COCO left/right joint identities are semantic evidence. Do not infer character "
            "side from viewer position, especially when limbs cross."
        ),
    }
    if candidate_mask is not None and np.asarray(candidate_mask).astype(bool).any():
        ys, xs = np.nonzero(np.asarray(candidate_mask).astype(bool))
        centroid = np.asarray([float(xs.mean()), float(ys.mean())])

        def distance(chain: list[dict[str, Any]]) -> float:
            array = np.asarray([(item["x"], item["y"]) for item in chain], dtype=np.float64)
            if len(array) == 1:
                return float(np.linalg.norm(centroid - array[0]))
            distances = []
            for start, end in zip(array[:-1], array[1:], strict=True):
                vector = end - start
                denominator = float(np.dot(vector, vector))
                fraction = (
                    float(np.clip(np.dot(centroid - start, vector) / denominator, 0, 1))
                    if denominator
                    else 0.0
                )
                distances.append(float(np.linalg.norm(centroid - (start + fraction * vector))))
            return min(distances)

        distances = {"left": distance(left_chain), "right": distance(right_chain)}
        assigned = min(distances, key=distances.get)
        evidence.update(
            {
                "candidate_centroid_xy": [
                    round(float(centroid[0]), 3),
                    round(float(centroid[1]), 3),
                ],
                "distance_to_chain_px": {
                    side: round(value, 3) for side, value in distances.items()
                },
                "nearest_semantic_chain": assigned,
                "assignment_consistent": assigned == expected_side,
            }
        )
    return evidence


def requires_reconstruction(
    mask: np.ndarray,
    *,
    label: str,
    person_bbox_xyxy: tuple[int, int, int, int] | None = None,
    area_tolerance_multiplier: float = 2.0,
) -> bool:
    """Recognize a draft too corrupt for a relative boundary-change limit."""
    target = np.asarray(mask).astype(bool)
    definition = get_ontology().label(label)
    if int(ndimage.label(target)[1]) > max(1, int(definition.max_components or 1)):
        return True
    expected = definition.expected_area_pct_range
    if person_bbox_xyxy is None or expected is None:
        return not target.any()
    person_area = _box_area(_validated_box(person_bbox_xyxy, target.shape))
    fraction_pct = 100 * int(target.sum()) / max(1, person_area)
    low, high = (float(value) for value in expected)
    return (
        fraction_pct < low / area_tolerance_multiplier
        or fraction_pct > high * area_tolerance_multiplier
    )


def evaluate_repair_candidate(
    candidate_mask: np.ndarray,
    *,
    current_mask: np.ndarray,
    protected_mask: np.ndarray,
    label: str,
    roi_xyxy: tuple[int, int, int, int],
    person_bbox_xyxy: tuple[int, int, int, int] | None,
    ordinary_max_changed_fraction: float,
    reconstruction_max_changed_fraction: float,
    maximum_protected_overlap_fraction: float,
    maximum_outside_roi_fraction: float,
    expected_area_slack: float,
) -> RepairGuardResult:
    """Run local geometry guards before a proposal enters full-map QA."""
    candidate = np.asarray(candidate_mask).astype(bool)
    current = np.asarray(current_mask).astype(bool)
    protected = np.asarray(protected_mask).astype(bool)
    if candidate.shape != current.shape or protected.shape != current.shape:
        raise AutonomousRepairError("repair candidate inputs have different geometry")
    if not candidate.any():
        return RepairGuardResult(False, False, 0, 0, 0, 0, None, 0, ("candidate_empty",))
    if not 0 <= expected_area_slack <= 1:
        raise AutonomousRepairError("expected-area slack must be within 0..1")
    roi = _validated_box(roi_xyxy, candidate.shape)
    roi_mask = np.zeros(candidate.shape, dtype=bool)
    roi_mask[roi[1] : roi[3], roi[0] : roi[2]] = True
    area = int(candidate.sum())
    changed = float(np.count_nonzero(candidate ^ current) / max(1, int(current.sum())))
    protected_overlap = float(np.count_nonzero(candidate & protected) / area)
    outside = float(np.count_nonzero(candidate & ~roi_mask) / area)
    component_count = int(ndimage.label(candidate)[1])
    reconstruction = requires_reconstruction(
        current, label=label, person_bbox_xyxy=person_bbox_xyxy
    )
    limit = reconstruction_max_changed_fraction if reconstruction else ordinary_max_changed_fraction
    vetoes = []
    if changed > limit:
        vetoes.append("candidate_change_limit")
    if protected_overlap > maximum_protected_overlap_fraction:
        vetoes.append("candidate_protected_overlap")
    if outside > maximum_outside_roi_fraction:
        vetoes.append("candidate_outside_repair_roi")
    maximum_components = max(1, int(get_ontology().label(label).max_components or 1))
    if component_count > maximum_components:
        vetoes.append("candidate_component_overflow")
    area_fraction = None
    expected = get_ontology().label(label).expected_area_pct_range
    if person_bbox_xyxy is not None and expected is not None:
        person_area = _box_area(_validated_box(person_bbox_xyxy, candidate.shape))
        area_fraction = area / max(1, person_area)
        low, high = (float(value) / 100 for value in expected)
        if area_fraction < low * (1 - expected_area_slack) or area_fraction > high * (
            1 + expected_area_slack
        ):
            vetoes.append("candidate_area_sanity")
    return RepairGuardResult(
        not vetoes,
        reconstruction,
        changed,
        protected_overlap,
        outside,
        area,
        area_fraction,
        component_count,
        tuple(vetoes),
    )


def atomic_boundary_vetoes(
    candidate_mask: np.ndarray,
    *,
    label: str,
    pose_document: Mapping[str, Any] | None,
    context_origin_xy: tuple[int, int] = (0, 0),
    companion_parts_visible: bool = True,
    confidence_min: float = 0.3,
) -> tuple[str, ...]:
    """Reject parent-union silhouettes that violate MCP/MTP atomic boundaries.

    The check is intentionally pose-gated and only active when companion atomic
    parts are visible in the complete map. That avoids rejecting a closed shoe,
    where toes are legitimately not visible and the footwear contour belongs to
    ``foot_base``.
    """
    candidate = np.asarray(candidate_mask).astype(bool)
    definition = get_ontology().label(label)
    if (
        candidate.ndim != 2
        or not candidate.any()
        or pose_document is None
        or not companion_parts_visible
        or definition.boundary_rule not in {"foot_mtp", "hand_mcp"}
        or definition.side not in {"left", "right"}
    ):
        return ()
    keypoints = {
        int(item["index"]): item
        for item in pose_document.get("keypoints", ())
        if isinstance(item, dict) and "index" in item
    }
    origin_x, origin_y = context_origin_xy

    def point(index: int) -> tuple[float, float] | None:
        item = keypoints.get(index)
        if item is None or float(item.get("confidence", 0.0)) < confidence_min:
            return None
        xy = (float(item.get("x", np.nan)) - origin_x, float(item.get("y", np.nan)) - origin_y)
        return xy if np.isfinite(xy).all() else None

    def hits(xy: tuple[float, float] | None, radius: int) -> bool:
        if xy is None:
            return False
        x, y = xy
        left = max(0, int(np.floor(x)) - radius)
        right = min(candidate.shape[1], int(np.ceil(x)) + radius + 1)
        top = max(0, int(np.floor(y)) - radius)
        bottom = min(candidate.shape[0], int(np.ceil(y)) + radius + 1)
        return left < right and top < bottom and bool(candidate[top:bottom, left:right].any())

    if definition.boundary_rule == "foot_mtp":
        heel_index, big_index, small_index = _FOOT_POINT_INDICES[definition.side]
        heel, big_toe, small_toe = point(heel_index), point(big_index), point(small_index)
        valid = [item for item in (heel, big_toe, small_toe) if item is not None]
        if len(valid) < 3:
            return ()
        length = float(np.linalg.norm(np.asarray(heel) - np.mean([big_toe, small_toe], axis=0)))
        radius = max(2, min(16, int(round(length * 0.035))))
        if label.endswith("foot_base") and hits(big_toe, radius) and hits(small_toe, radius):
            return ("MF-BOUNDARY-foot_mtp-whole_foot_as_foot_base",)
        if label.endswith("toes") and hits(heel, radius):
            return ("MF-BOUNDARY-foot_mtp-toes_include_heel",)
        return ()

    tips = [point(index) for index in _HAND_TIP_INDICES[definition.side]]
    valid_tips = [item for item in tips if item is not None]
    if len(valid_tips) < 2:
        return ()
    radius = 3
    if label.endswith("hand_base") and sum(hits(item, radius) for item in valid_tips) >= 2:
        return ("MF-BOUNDARY-hand_mcp-whole_hand_as_hand_base",)
    return ()


def immutable_protected_union(
    part_map: np.ndarray,
    *,
    auxiliary_protected: np.ndarray | None = None,
) -> np.ndarray:
    """Return pixels a non-gold repair transaction may never claim."""
    indexed = np.asarray(part_map)
    protected = np.zeros(indexed.shape, dtype=bool)
    for name in (
        "other_person",
        "accessory_or_prop",
        "occluding_object",
        "support_surface",
    ):
        try:
            label = get_ontology().label(name)
        except KeyError:
            continue
        if label.id is not None:
            protected |= indexed == int(label.id)
    if auxiliary_protected is not None:
        extra = np.asarray(auxiliary_protected).astype(bool)
        if extra.shape != protected.shape:
            raise AutonomousRepairError("auxiliary protected geometry differs from PART map")
        protected |= extra
    return protected


def _validated_box(value: Any, image_shape: tuple[int, int]) -> tuple[int, int, int, int]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise AutonomousRepairError("repair ROI must contain four integer coordinates")
    left, top, right, bottom = (int(item) for item in value)
    height, width = image_shape
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise AutonomousRepairError("repair ROI is outside image geometry")
    return left, top, right, bottom


def _union_boxes(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _box_area(box: tuple[int, int, int, int]) -> int:
    return (box[2] - box[0]) * (box[3] - box[1])


__all__ = [
    "AutonomousRepairError",
    "BoundedRepairDecision",
    "BoundedRepairLimits",
    "RepairAttempt",
    "RepairGuardResult",
    "RepairRegion",
    "build_pose_side_evidence",
    "atomic_boundary_vetoes",
    "evaluate_repair_candidate",
    "decide_bounded_repair",
    "expand_box",
    "immutable_protected_union",
    "load_repair_regions",
    "merge_specialist_repair_regions",
    "normalized_roi_points_to_source",
    "requires_reconstruction",
    "repair_limits_from_policy",
]
