"""P3 hand-lane crop and MediaPipe landmark/side arbitration."""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.spatial import ConvexHull

from ..io.png_strict import write_binary_mask
from ..models.registry import (
    DEFAULT_MODELS_ROOT,
    DEFAULT_REGISTRY,
    ModelRegistryError,
    resolve_registered_role,
)
from ..qa.failure_mining import append_failure_once, make_failure_record
from ..qa.metrics import boundary_f, iou
from ..stages.s05_geometry import PromptPlan, build_prompt_plan
from ..stages.s07_sam2 import RefinedPart, Sam2Provider, build_embedding, refine_part
from ..training.leaderboard import append_leaderboard_row
from .common import CropTransform, LaneCrop, create_lane_crop, reproject_crop_mask


class HandLaneError(ValueError):
    """Hand-lane pose or landmark evidence violates the lane contract."""


LEFT_HAND_INDICES = tuple(range(91, 112))
RIGHT_HAND_INDICES = tuple(range(112, 133))
WRIST_INDEX = {"left": 9, "right": 10}


@dataclass(frozen=True)
class HandLandmark:
    index: int
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class HandEvidence:
    side: str
    landmarks: tuple[HandLandmark, ...]
    mediapipe_handedness: str
    mediapipe_score: float
    skeleton_side: str
    resolved_side: str
    handedness_mismatch: bool
    qc014_flag: bool
    evidence_path: Path


FINGER_INDICES = {
    "thumb": (1, 2, 3, 4),
    "index_finger": (5, 6, 7, 8),
    "middle_finger": (9, 10, 11, 12),
    "ring_finger": (13, 14, 15, 16),
    "pinky": (17, 18, 19, 20),
}


@dataclass(frozen=True)
class HandGeometry:
    finger_masks: dict[str, np.ndarray]
    hand_base: np.ndarray
    finger_gap_regions: np.ndarray


@dataclass(frozen=True)
class MergeResult:
    finger_masks: dict[str, np.ndarray]
    hand_base: np.ndarray
    visibility_states: dict[str, str]
    fingers_merged_or_ambiguous: bool
    finger_occlusion_boundary: np.ndarray
    failure_queue_record: dict[str, object] | None


@dataclass(frozen=True)
class ChampionHandDraft:
    geometry: HandGeometry
    checkpoint_sha256: str
    role: str = "champion_hand"


HAND_CLASS_IDS = {
    "left_hand_base": 1,
    "right_hand_base": 2,
    "left_thumb": 3,
    "right_thumb": 4,
    "left_index_finger": 5,
    "right_index_finger": 6,
    "left_middle_finger": 7,
    "right_middle_finger": 8,
    "left_ring_finger": 9,
    "right_ring_finger": 10,
    "left_pinky": 11,
    "right_pinky": 12,
}


def draft_hand_with_champion(
    crop_image: np.ndarray,
    *,
    side: str,
    loader,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
) -> ChampionHandDraft:
    """Load exactly the promoted hand checkpoint and convert its crop map to lane geometry."""
    image = np.asarray(crop_image)
    if image.ndim != 3 or image.shape[2] != 3 or side not in {"left", "right"}:
        raise HandLaneError("champion hand drafting requires RGB crop and left/right side")
    try:
        checkpoint = resolve_registered_role(
            "champion_hand", registry_path=registry_path, models_root=models_root
        )
    except ModelRegistryError as exc:
        raise HandLaneError(f"champion hand resolution failed: {exc}") from exc
    provider = loader(checkpoint)
    try:
        indexed = np.asarray(provider(image, side))
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
        del provider
    if indexed.shape != image.shape[:2] or not np.issubdtype(indexed.dtype, np.integer):
        raise HandLaneError("champion hand output must be integer HxW at crop geometry")
    permitted_names = {f"{side}_{name}" for name in FINGER_INDICES} | {f"{side}_hand_base"}
    permitted_ids = {0, 13} | {HAND_CLASS_IDS[name] for name in permitted_names}
    unknown = set(np.unique(indexed).tolist()) - permitted_ids
    if unknown:
        raise HandLaneError(
            f"champion hand output contains opposite-side or unknown IDs: {sorted(unknown)}"
        )
    fingers = {
        name: indexed == HAND_CLASS_IDS[name]
        for name in sorted(permitted_names)
        if name != f"{side}_hand_base"
    }
    hand_base = indexed == HAND_CLASS_IDS[f"{side}_hand_base"]
    if not hand_base.any() or not any(mask.any() for mask in fingers.values()):
        raise HandLaneError("champion hand output lacks hand base or visible finger evidence")
    finger_union = np.logical_or.reduce(tuple(fingers.values()))
    gaps = (indexed == 0) & ndimage.binary_dilation(finger_union, iterations=2)
    checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    return ChampionHandDraft(HandGeometry(fingers, hand_base, gaps), checkpoint_sha)


def evaluate_hand_predictions(
    predicted_crop_masks: dict[str, np.ndarray],
    gold_crop_masks: dict[str, np.ndarray],
    *,
    finger_gap_regions: np.ndarray,
    transform: CropTransform,
    full_gold_masks: dict[str, np.ndarray],
    full_size: tuple[int, int],
    leaderboard_path: Path,
    run_id: str,
    dataset_ref: str,
    ckpt_sha: str,
    model_family: str = "hand_lane_draft",
) -> dict[str, object]:
    """Gate finger gaps/paste-back and append per-finger IoU/BF leaderboard evidence."""
    labels = tuple(sorted(predicted_crop_masks))
    if not labels or set(labels) != set(gold_crop_masks) or set(labels) != set(full_gold_masks):
        raise HandLaneError("hand evaluation requires matching non-empty prediction/gold labels")
    predictions = {name: np.asarray(predicted_crop_masks[name]).astype(bool) for name in labels}
    gold = {name: np.asarray(gold_crop_masks[name]).astype(bool) for name in labels}
    shape = predictions[labels[0]].shape
    if any(mask.shape != shape for mask in (*predictions.values(), *gold.values())):
        raise HandLaneError("hand evaluation crop masks differ in dimensions")
    gaps = np.asarray(finger_gap_regions).astype(bool)
    if gaps.shape != shape:
        raise HandLaneError("finger gap evidence differs from prediction dimensions")
    union = np.logical_or.reduce(tuple(predictions.values()))
    gap_fill_px = int(np.count_nonzero(union & gaps))
    if gap_fill_px:
        raise HandLaneError(f"inter-finger gaps were filled by {gap_fill_px} pixels")
    per_class = {}
    paste_back = {}
    for name in labels:
        per_class[name] = {
            "iou": iou(predictions[name], gold[name]),
            "bf": boundary_f(predictions[name], gold[name], tolerance_px=2),
        }
        projected = reproject_crop_mask(
            predictions[name].astype(np.uint8) * 255, transform, full_size=full_size
        )
        paste_back[name] = iou(projected, full_gold_masks[name])
    minimum_paste = min(paste_back.values())
    if minimum_paste < 0.995:
        raise HandLaneError(f"hand paste-back IoU {minimum_paste:.6f} below 0.995")
    mean_iou = statistics.fmean(value["iou"] for value in per_class.values())
    mean_bf = statistics.fmean(value["bf"] for value in per_class.values())
    row = {
        "run_id": run_id,
        "model_family": model_family,
        "ckpt_sha": ckpt_sha,
        "dataset_ref": dataset_ref,
        "split": "test_holdout",
        "mean_iou": mean_iou,
        "mean_boundary_f": mean_bf,
        "per_class": per_class,
        "group_scores": {"fingers": {"iou": mean_iou, "bf": mean_bf}},
        "latency_ms_1024": 0,
        "vram_gb": 0,
        "seeds": [1337],
        "notes": "Hand-lane seeded acceptance: gaps + QC-018 paste-back.",
        "sample_count": 1,
    }
    append_leaderboard_row(leaderboard_path, row)
    return {
        "gap_fill_px": gap_fill_px,
        "paste_back_iou": paste_back,
        "minimum_paste_back_iou": minimum_paste,
        "per_class": per_class,
    }


def create_hand_crop(
    source_path: Path,
    hand_prior: np.ndarray,
    pose133: np.ndarray,
    *,
    side: str,
    output_dir: Path,
    confidence_min: float = 0.3,
) -> LaneCrop:
    """Build a 1.6x crop bbox from wrist plus the side's 21 DWPose hand points."""
    points = np.asarray(pose133, dtype=np.float64)
    if points.shape != (133, 3) or side not in {"left", "right"}:
        raise HandLaneError("pose must be 133x3 and side left/right")
    indices = LEFT_HAND_INDICES if side == "left" else RIGHT_HAND_INDICES
    selected_indices = (WRIST_INDEX[side], *indices)
    selected = points[list(selected_indices)]
    selected = selected[selected[:, 2] >= confidence_min]
    if len(selected) < 2:
        raise HandLaneError(f"insufficient {side} wrist/hand keypoints")
    minimum, maximum = selected[:, :2].min(axis=0), selected[:, :2].max(axis=0)
    bbox = (
        int(np.floor(minimum[0])),
        int(np.floor(minimum[1])),
        int(np.ceil(maximum[0])) + 1,
        int(np.ceil(maximum[1])) + 1,
    )
    return create_lane_crop(
        source_path,
        hand_prior,
        part=f"{side}_hand",
        part_bbox_xyxy=bbox,
        output_dir=output_dir,
    )


def build_hand_geometry(
    landmarks_xy: np.ndarray,
    parsing_hand: np.ndarray,
    *,
    side: str,
) -> HandGeometry:
    """Build four-point finger strips and palm hull; gaps remain explicitly unclaimed."""
    points = np.asarray(landmarks_xy, dtype=np.float64)
    parsing = np.asarray(parsing_hand).astype(bool)
    if points.shape != (21, 2) or parsing.ndim != 2 or side not in {"left", "right"}:
        raise HandLaneError("hand geometry requires 21x2 points, 2-D parsing, and valid side")
    fingers = {}
    for finger, indices in FINGER_INDICES.items():
        chain = points[list(indices)]
        mask = np.zeros(parsing.shape, dtype=bool)
        for start, end in zip(chain[:-1], chain[1:], strict=True):
            radius_start = _cross_section_radius(parsing, start, end - start)
            radius_end = _cross_section_radius(parsing, end, end - start)
            mask |= _quad_segment(parsing.shape, start, end, radius_start, radius_end)
        fingers[f"{side}_{finger}"] = mask & parsing
    palm_points = points[[0, 5, 9, 13, 17]]
    palm = _convex_mask(parsing.shape, palm_points) & parsing
    finger_union = np.logical_or.reduce(tuple(fingers.values()))
    palm &= ~finger_union
    gaps = _finger_gap_regions(points, parsing, finger_union | palm)
    return HandGeometry(fingers, palm, gaps)


def assign_gap_ownership(gap_regions: np.ndarray, behind_part_map: np.ndarray) -> np.ndarray:
    """Gap pixels inherit the already-fused behind part; zero remains background."""
    gaps = np.asarray(gap_regions).astype(bool)
    behind = np.asarray(behind_part_map)
    if gaps.shape != behind.shape or behind.ndim != 2:
        raise HandLaneError("gap and behind-map dimensions differ")
    owned = np.zeros_like(behind)
    owned[gaps] = behind[gaps]
    return owned


def apply_finger_merge_policy(
    geometry: HandGeometry,
    landmark_confidences: np.ndarray,
    *,
    side: str,
    overlap_threshold: float = 0.30,
    confidence_threshold: float = 0.5,
) -> MergeResult:
    """On overlap/low confidence, merge affected fingers into hand_base and queue failure."""
    confidence = np.asarray(landmark_confidences, dtype=np.float64)
    if confidence.shape != (21,) or side not in {"left", "right"}:
        raise HandLaneError("merge policy requires 21 confidences and valid side")
    ambiguous = set()
    ordered = [f"{side}_{name}" for name in FINGER_INDICES]
    for first, second in zip(ordered[:-1], ordered[1:], strict=True):
        a, b = geometry.finger_masks[first], geometry.finger_masks[second]
        denominator = min(int(a.sum()), int(b.sum()))
        overlap = int(np.count_nonzero(a & b)) / denominator if denominator else 0.0
        if overlap > overlap_threshold:
            ambiguous.update((first, second))
    for finger, indices in FINGER_INDICES.items():
        if np.min(confidence[list(indices)]) < confidence_threshold:
            ambiguous.add(f"{side}_{finger}")
    masks = {name: mask.copy() for name, mask in geometry.finger_masks.items()}
    hand_base = geometry.hand_base.copy()
    merged_region = np.zeros_like(hand_base)
    for name in sorted(ambiguous):
        merged_region |= masks[name]
        hand_base |= masks[name]
        masks[name][:] = False
    boundary = (
        ndimage.binary_dilation(merged_region, iterations=2)
        & ~ndimage.binary_erosion(merged_region, iterations=2)
        if merged_region.any()
        else merged_region
    )
    states = {name: "ambiguous_do_not_use" if name in ambiguous else "visible" for name in masks}
    record = (
        {
            "queue": "failure_queue",
            "reason": "finger_merge",
            "side": side,
            "parts": sorted(ambiguous),
        }
        if ambiguous
        else None
    )
    return MergeResult(masks, hand_base, states, bool(ambiguous), boundary, record)


def apply_and_record_s07_hand_merges(
    results: dict[str, RefinedPart],
    *,
    pose_path: Path,
    output_dir: Path,
    image_id: str,
    instance_id: str,
    model: str,
    failure_queue_path: Path,
) -> dict[str, object]:
    """Apply the no-guess merge rule to live S07 masks before S09 consumes them."""
    if not instance_id.startswith("p") or not instance_id[1:].isdigit():
        raise HandLaneError("S07 hand merge instance must be pN")
    hand_labels = {
        f"{side}_{suffix}"
        for side in ("left", "right")
        for suffix in (*FINGER_INDICES, "hand_base")
    }
    if not set(results) & hand_labels:
        return {"status": "skipped_no_hand_parts", "sides": {}, "failure_record_count": 0}
    pose = json.loads(Path(pose_path).read_text(encoding="utf-8"))
    keypoints = pose.get("keypoints", ())
    if len(keypoints) != 133 or any(
        int(item.get("index", -1)) != index for index, item in enumerate(keypoints)
    ):
        raise HandLaneError("S07 hand merge requires indexed COCO-WholeBody-133 evidence")
    output_dir = Path(output_dir)
    sides = {}
    emitted = 0
    now = datetime.now(UTC)
    for side in ("left", "right"):
        base_label = f"{side}_hand_base"
        finger_labels = tuple(f"{side}_{name}" for name in FINGER_INDICES)
        present = [results[name] for name in (base_label, *finger_labels) if name in results]
        if base_label not in results or not any(name in results for name in finger_labels):
            sides[side] = {"status": "skipped_no_visible_hand", "ambiguous_parts": []}
            continue
        shape = present[0].mask.shape
        if any(item.mask.shape != shape for item in present):
            raise HandLaneError(f"S07 {side} hand masks differ in geometry")
        zeros = np.zeros(shape, dtype=bool)
        geometry = HandGeometry(
            {
                name: np.asarray(results[name].mask).astype(bool)
                if name in results
                else zeros.copy()
                for name in finger_labels
            },
            np.asarray(results[base_label].mask).astype(bool),
            zeros.copy(),
        )
        indices = LEFT_HAND_INDICES if side == "left" else RIGHT_HAND_INDICES
        confidences = np.asarray(
            [float(keypoints[index]["confidence"]) for index in indices], dtype=np.float64
        )
        merged = apply_finger_merge_policy(geometry, confidences, side=side)
        ambiguous = (
            tuple(merged.failure_queue_record["parts"]) if merged.failure_queue_record else ()
        )
        updates = {base_label: merged.hand_base, **merged.finger_masks}
        for label, mask in updates.items():
            if label not in results:
                continue
            flags = results[label].review_flags
            if label in ambiguous:
                flags = tuple(dict.fromkeys((*flags, "finger_merge", "careful_review")))
            results[label] = replace(results[label], mask=mask, review_flags=flags)
            write_binary_mask(
                output_dir / f"sam2_{label}.png",
                mask,
                source_size=(shape[1], shape[0]),
            )
        boundary_path = None
        if merged.finger_occlusion_boundary.any():
            boundary_path = write_binary_mask(
                output_dir / f"{side}_finger_occlusion_boundary.png",
                merged.finger_occlusion_boundary,
                source_size=(shape[1], shape[0]),
            )
        for label in ambiguous:
            error_rate = _finger_merge_error(label, geometry, confidences, side=side)
            record = make_failure_record(
                image_id=image_id,
                body_part=label,
                reason="finger_merge",
                pose=str(pose["view"]),
                model=f"hand_lane_s07:{instance_id}:{model}",
                correction=f"merge_{label}_into_hand_base",
                class_error_rate=error_rate,
                coverage_deficit=1.0,
                use_weight=1.0,
                event_time=now,
                now=now,
            )
            emitted += int(append_failure_once(failure_queue_path, record))
        sides[side] = {
            "status": "merged_ambiguous" if ambiguous else "clean",
            "ambiguous_parts": list(ambiguous),
            "boundary_file": boundary_path.name if boundary_path else None,
        }
    metrics_path = output_dir / "sam2_metrics.json"
    if metrics_path.is_file():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        for side_result in sides.values():
            for label in side_result["ambiguous_parts"]:
                if label in metrics.get("parts", {}):
                    metrics["parts"][label]["visibility_state"] = "ambiguous_do_not_use"
                    metrics["parts"][label]["fingers_merged_or_ambiguous"] = True
        metrics_path.write_text(
            json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    audit = {
        "schema_version": "1.0.0",
        "image_id": image_id,
        "instance_id": instance_id,
        "model": model,
        "sides": sides,
        "failure_record_count": emitted,
    }
    (output_dir / "hand_merge_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return audit


def _finger_merge_error(
    label: str, geometry: HandGeometry, confidences: np.ndarray, *, side: str
) -> float:
    suffix = label.removeprefix(f"{side}_")
    chain = FINGER_INDICES[suffix]
    confidence_error = 1.0 - float(np.min(confidences[list(chain)]))
    ordered = tuple(f"{side}_{name}" for name in FINGER_INDICES)
    position = ordered.index(label)
    overlaps = []
    for neighbor_index in (position - 1, position + 1):
        if not 0 <= neighbor_index < len(ordered):
            continue
        first, second = geometry.finger_masks[label], geometry.finger_masks[ordered[neighbor_index]]
        denominator = min(int(first.sum()), int(second.sum()))
        overlaps.append(int(np.count_nonzero(first & second)) / denominator if denominator else 0.0)
    return min(1.0, max(confidence_error, *overlaps, 0.0))


def apply_hand_contact_zorder(
    hand_mask: np.ndarray, body_mask: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Hand owns every contact pixel; body loses it and an 8px@1024 contact band is emitted."""
    hand, body = np.asarray(hand_mask).astype(bool), np.asarray(body_mask).astype(bool)
    if hand.shape != body.shape:
        raise HandLaneError("hand/body dimensions differ")
    contact = hand & body
    radius = max(1, round(8 * hand.shape[1] / 1024))
    band = ndimage.binary_dilation(contact, iterations=radius) if contact.any() else contact
    return hand, body & ~hand, band


def build_hand_prompt_plans(
    geometry: HandGeometry,
    landmarks_xy: np.ndarray,
    *,
    side: str,
) -> dict[str, PromptPlan]:
    """Finger plans use 3 line positives plus gap/neighbor negatives; base negates fingers."""
    points = np.asarray(landmarks_xy, dtype=np.float64)
    if points.shape != (21, 2) or side not in {"left", "right"}:
        raise HandLaneError("prompt planning requires 21x2 landmarks and valid side")
    plans = {}
    gap_points = tuple(
        (int(x), int(y))
        for y, x in np.argwhere(geometry.finger_gap_regions)[
            :: max(1, int(geometry.finger_gap_regions.sum() / 8) or 1)
        ]
    )[:8]
    for finger, indices in FINGER_INDICES.items():
        label = f"{side}_{finger}"
        neighbors = [mask for name, mask in geometry.finger_masks.items() if name != label]
        plan = build_prompt_plan(
            label,
            geometry.finger_masks[label],
            skeleton_points_xy=[tuple(point) for point in points[list(indices)]],
            neighbor_priors=neighbors,
            skeleton_samples=3,
        )
        plans[label] = replace(
            plan,
            negative_points=tuple(dict.fromkeys((*plan.negative_points, *gap_points))),
        )
    base_skeleton = [tuple(point) for point in points[[0, 5, 9, 13, 17]]]
    plans[f"{side}_hand_base"] = build_prompt_plan(
        f"{side}_hand_base",
        geometry.hand_base,
        skeleton_points_xy=base_skeleton,
        neighbor_priors=geometry.finger_masks.values(),
        skeleton_samples=5,
    )
    return plans


def refine_hand_with_sam2(
    provider: Sam2Provider,
    crop_image: np.ndarray,
    geometry: HandGeometry,
    plans: dict[str, PromptPlan],
) -> tuple[dict[str, RefinedPart], str]:
    """Build one fresh crop embedding and reuse it across all five fingers plus hand_base."""
    embedding, model = build_embedding(provider, crop_image)
    priors = {
        **geometry.finger_masks,
        plans[next(name for name in plans if name.endswith("hand_base"))].label: geometry.hand_base,
    }
    refined = {
        label: refine_part(provider, embedding, plan, priors[label], model=model)
        for label, plan in plans.items()
    }
    return refined, model


def write_hand_evidence(
    landmarks_xyz: np.ndarray,
    *,
    side: str,
    mediapipe_handedness: str,
    mediapipe_score: float,
    skeleton_side: str,
    output_dir: Path,
) -> HandEvidence:
    """Serialize 21 landmarks; a side mismatch flags QC-014 and skeleton wins."""
    points = np.asarray(landmarks_xyz, dtype=np.float64)
    handedness = mediapipe_handedness.lower()
    if points.shape != (21, 3) or not np.isfinite(points).all():
        raise HandLaneError("MediaPipe landmarks must be finite 21x3")
    if side not in {"left", "right"} or skeleton_side not in {"left", "right"}:
        raise HandLaneError("side and skeleton_side must be left/right")
    if handedness not in {"left", "right"} or not 0 <= mediapipe_score <= 1:
        raise HandLaneError("invalid MediaPipe handedness evidence")
    mismatch = handedness != skeleton_side
    landmarks = tuple(
        HandLandmark(index, float(point[0]), float(point[1]), float(point[2]))
        for index, point in enumerate(points)
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{side}_landmarks.json"
    document = {
        "schema_version": "1.0.0",
        "side": side,
        "landmarks": [asdict(point) for point in landmarks],
        "mediapipe": {"handedness": handedness, "score": mediapipe_score},
        "skeleton_side": skeleton_side,
        "resolved_side": skeleton_side,
        "handedness_mismatch": mismatch,
        "qc014_flag": mismatch,
        "arbitration": "skeleton_wins",
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return HandEvidence(
        side,
        landmarks,
        handedness,
        mediapipe_score,
        skeleton_side,
        skeleton_side,
        mismatch,
        mismatch,
        path,
    )


def run_mediapipe_hand_landmarker(
    crop_path: Path,
    model_path: Path,
    *,
    side: str,
    skeleton_side: str,
    output_dir: Path,
) -> HandEvidence:
    """Execute the pinned MediaPipe Tasks model on one specialist crop."""
    import mediapipe as mp

    options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
        num_hands=1,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    image = mp.Image.create_from_file(str(crop_path))
    with mp.tasks.vision.HandLandmarker.create_from_options(options) as landmarker:
        result = landmarker.detect(image)
    if len(result.hand_landmarks) != 1 or len(result.hand_landmarks[0]) != 21:
        raise HandLaneError("MediaPipe did not return exactly one 21-landmark hand")
    points = np.asarray(
        [[point.x, point.y, point.z] for point in result.hand_landmarks[0]], dtype=np.float64
    )
    category = result.handedness[0][0]
    return write_hand_evidence(
        points,
        side=side,
        mediapipe_handedness=category.category_name,
        mediapipe_score=float(category.score),
        skeleton_side=skeleton_side,
        output_dir=output_dir,
    )


def _cross_section_radius(mask: np.ndarray, point: np.ndarray, tangent: np.ndarray) -> float:
    length = float(np.linalg.norm(tangent))
    if length == 0:
        return 1.0
    perpendicular = np.array([-tangent[1], tangent[0]]) / length
    extents = []
    for direction in (-perpendicular, perpendicular):
        extent = 0
        for distance in range(1, 65):
            x, y = np.rint(point + direction * distance).astype(int)
            if not (0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and mask[y, x]):
                break
            extent = distance
        extents.append(extent)
    measured = max(1.0, (extents[0] + extents[1] + 1) / 2)
    return min(measured, max(1.0, length * 0.45))


def _quad_segment(shape, start, end, radius_start, radius_end):
    tangent = end - start
    length = float(np.linalg.norm(tangent))
    if length == 0:
        return np.zeros(shape, dtype=bool)
    perpendicular = np.array([-tangent[1], tangent[0]]) / length
    polygon = [
        tuple(start + perpendicular * radius_start),
        tuple(end + perpendicular * radius_end),
        tuple(end - perpendicular * radius_end),
        tuple(start - perpendicular * radius_start),
    ]
    image = Image.new("1", (shape[1], shape[0]))
    ImageDraw.Draw(image).polygon(polygon, fill=1)
    return np.asarray(image, dtype=bool)


def _convex_mask(shape, points):
    hull = ConvexHull(points)
    polygon = [tuple(points[index]) for index in hull.vertices]
    image = Image.new("1", (shape[1], shape[0]))
    ImageDraw.Draw(image).polygon(polygon, fill=1)
    return np.asarray(image, dtype=bool)


def _finger_gap_regions(points, parsing, claimed):
    gaps = np.zeros_like(parsing)
    adjacent = ((5, 9), (9, 13), (13, 17))
    for first, second in adjacent:
        for offset in range(4):
            center = (points[first + offset] + points[second + offset]) / 2
            x, y = np.rint(center).astype(int)
            if 0 <= y < gaps.shape[0] and 0 <= x < gaps.shape[1]:
                gaps[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2] = True
    return gaps & parsing & ~claimed
