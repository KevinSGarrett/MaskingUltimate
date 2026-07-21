"""Inactive adult-anatomy v2 drafting, SAM2 routing, and carve-out fusion.

This module is review-draft machinery only.  It never changes the active v1
pipeline, never treats detector boxes or geometry priors as masks, and never
approves gold. Its outputs become eligible for review only after content-lane
compatibility and visible-pixel gates below pass.
"""

from __future__ import annotations

import json
import math
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml
from PIL import Image

from .fusion.mapbuild import priority_argmax
from .io.png_strict import write_binary_mask, write_label_map
from .ontology import load_ontology
from .ontology_v2 import DEFAULT_ONTOLOGY_V2, load_v2_proposal
from .ontology_v2_manifest import V2_NULL_MASK_STATES, V2_REVIEW_STATES
from .stages.s05_geometry import PromptPlan, build_prompt_plan
from .stages.s07_sam2 import RefinedPart, Sam2Provider, refine_part

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "configs" / "anatomy_v2_drafting.yaml"
NEW_LABELS = (
    "left_areola",
    "right_areola",
    "left_nipple",
    "right_nipple",
    "vulva",
    "penis_shaft",
    "glans_penis",
    "left_scrotal_region",
    "right_scrotal_region",
)
PERMITTED_CONTENT_LANES = frozenset({"general", "adult_nonexplicit", "consensual_explicit_adult"})
CHEST_LABELS = NEW_LABELS[:4]
PELVIC_LABELS = NEW_LABELS[4:]
EXPLICIT_NON_CANDIDATE_STATES = frozenset(
    {"occluded_by_clothing", "cropped_out", "not_visible", "not_applicable", "ambiguous_do_not_use"}
)


class AnatomyV2DraftError(ValueError):
    """Inactive v2 draft inputs would assert unsafe or non-canonical anatomy."""


@dataclass(frozen=True)
class AnatomyCropProposal:
    label: str
    bbox_xyxy: tuple[int, int, int, int]
    lane: str
    scale: float
    visibility_state: str
    authority: str = "review_crop_only"
    asserts_positive_anatomy: bool = False


@dataclass(frozen=True)
class AnatomyOpenVocabRequest:
    label: str
    prompt: str
    roi_bbox_xyxy: tuple[int, int, int, int]
    visibility_state: str
    content_lane_decision: str
    authority: str = "proposal_box_only"
    may_write_final_mask: bool = False
    visible_surface_only: bool = True


@dataclass(frozen=True)
class AnatomyBoxProposal:
    label: str
    prompt: str
    bbox_xyxy: tuple[int, int, int, int]
    box_score: float
    text_score: float
    content_lane_decision: str
    authority: str = "proposal_box_only"


@dataclass(frozen=True)
class AnatomySpatialPrior:
    label: str
    roi: np.ndarray
    side: str
    view: str
    authority: str = "spatial_gate_only"
    may_write_final_mask: bool = False


@dataclass(frozen=True)
class AnatomyDraftCandidate:
    label: str
    visibility_state: str
    mask: np.ndarray | None
    confidence: float
    authority: str
    correction_instruction: str
    provenance: dict[str, Any]


@dataclass(frozen=True)
class AnatomyFusionResult:
    part_map: np.ndarray
    atomic_masks: dict[str, np.ndarray]
    ambiguity_ignore: np.ndarray
    confidence_maps: dict[str, np.ndarray]
    audit: dict[str, Any]


def load_anatomy_v2_config(path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise AnatomyV2DraftError(f"cannot load anatomy-v2 drafting config: {exc}") from exc
    if not isinstance(document, dict):
        raise AnatomyV2DraftError("anatomy-v2 drafting config root must be an object")
    exact = {
        "config_version": "1.0.0",
        "ontology_version": "body_parts_v2",
        "activation_status": "approved_design_not_active",
    }
    for key, expected in exact.items():
        if document.get(key) != expected:
            raise AnatomyV2DraftError(f"anatomy-v2 config {key} must equal {expected!r}")
    governance = document.get("governance")
    if not isinstance(governance, dict) or set(
        governance.get("permitted_content_lanes", ())
    ) != set(PERMITTED_CONTENT_LANES):
        raise AnatomyV2DraftError("anatomy-v2 drafting must declare the permitted content lanes")
    for required_true in (
        "visible_surface_only",
        "clothing_owns_covered_pixels",
        "ambiguity_is_ignore_255",
    ):
        if governance.get(required_true) is not True:
            raise AnatomyV2DraftError(f"anatomy-v2 governance must enable {required_true}")
    for required_false in (
        "detector_boxes_may_be_final_masks",
        "geometry_priors_may_be_final_masks",
        "projected_amodal_may_enter_fusion",
    ):
        if governance.get(required_false) is not False:
            raise AnatomyV2DraftError(f"anatomy-v2 governance must disable {required_false}")
    prompts = document.get("prompts")
    if not isinstance(prompts, dict) or tuple(prompts) != NEW_LABELS:
        raise AnatomyV2DraftError("anatomy-v2 prompt keys must be the nine canonical additions")
    if any(
        not isinstance(value, str) or not value.startswith("visible exposed")
        for value in prompts.values()
    ):
        raise AnatomyV2DraftError("anatomy-v2 prompts must request visible exposed surface only")
    aliases = set(load_v2_proposal()["aliases"])
    if aliases & set(prompts):
        raise AnatomyV2DraftError("anatomy-v2 aliases cannot become prompt labels")
    groups = document.get("crop_groups")
    if not isinstance(groups, dict) or set(groups) != {"chest", "pelvic"}:
        raise AnatomyV2DraftError("anatomy-v2 crop groups must be chest and pelvic")
    if (
        tuple(groups["chest"].get("labels", ())) != CHEST_LABELS
        or tuple(groups["pelvic"].get("labels", ())) != PELVIC_LABELS
    ):
        raise AnatomyV2DraftError("anatomy-v2 crop group labels drifted")
    if (
        groups["chest"].get("scale") != 1.35
        or groups["chest"].get("lane") != "anatomy_v2_chest"
        or groups["pelvic"].get("scale") != 1.45
        or groups["pelvic"].get("lane") != "anatomy_v2_pelvic"
    ):
        raise AnatomyV2DraftError("anatomy-v2 crop geometry/lane policy drifted")
    expected_fusion = {
        "nipple_owns_areola_overlap": True,
        "glans_owns_shaft_overlap": True,
        "incompatible_genital_overlap": "ambiguous_do_not_use",
        "unrelated_v1_overlap": "ambiguous_do_not_use",
        "breast_carveouts": list(CHEST_LABELS),
        "pelvic_carveouts": list(PELVIC_LABELS),
        "output_authority": "non_gold_review_draft",
    }
    if document.get("fusion") != expected_fusion:
        raise AnatomyV2DraftError("anatomy-v2 fusion policy drifted")
    return document


def require_permitted_content_lane(content_lane_decision: str) -> None:
    if content_lane_decision not in PERMITTED_CONTENT_LANES:
        raise AnatomyV2DraftError(
            "anatomy-v2 drafting requires a permitted content lane, "
            f"got {content_lane_decision!r}"
        )


def build_anatomy_crop_proposals(
    *,
    image_size: tuple[int, int],
    chest_bbox_xyxy: tuple[int, int, int, int],
    pelvic_bbox_xyxy: tuple[int, int, int, int],
    visibility_states: Mapping[str, str],
    content_lane_decision: str,
    config_path: Path | str = DEFAULT_CONFIG,
) -> tuple[AnatomyCropProposal, ...]:
    """Create review crops only; a crop never asserts that anatomy is present."""
    require_permitted_content_lane(content_lane_decision)
    config = load_anatomy_v2_config(config_path)
    width, height = image_size
    if width < 1 or height < 1:
        raise AnatomyV2DraftError("anatomy-v2 image dimensions must be positive")
    result = []
    for group_name, base_box in (
        ("chest", chest_bbox_xyxy),
        ("pelvic", pelvic_bbox_xyxy),
    ):
        group = config["crop_groups"][group_name]
        box = _expand_box(base_box, image_size, float(group["scale"]))
        for label in group["labels"]:
            state = _state(visibility_states.get(label, "unreviewed_for_v2"))
            result.append(
                AnatomyCropProposal(
                    label,
                    box,
                    str(group["lane"]),
                    float(group["scale"]),
                    state,
                )
            )
    return tuple(result)


def canonical_open_vocab_requests(
    crops: tuple[AnatomyCropProposal, ...],
    *,
    content_lane_decision: str,
    config_path: Path | str = DEFAULT_CONFIG,
) -> tuple[AnatomyOpenVocabRequest, ...]:
    """Route only canonical visible-surface prompts through proposal-box authority."""
    require_permitted_content_lane(content_lane_decision)
    config = load_anatomy_v2_config(config_path)
    seen = set()
    requests = []
    for crop in crops:
        if crop.label in seen or crop.label not in NEW_LABELS:
            raise AnatomyV2DraftError(f"duplicate or unknown anatomy-v2 crop label: {crop.label}")
        seen.add(crop.label)
        if crop.visibility_state in EXPLICIT_NON_CANDIDATE_STATES:
            continue
        requests.append(
            AnatomyOpenVocabRequest(
                crop.label,
                str(config["prompts"][crop.label]),
                crop.bbox_xyxy,
                crop.visibility_state,
                content_lane_decision,
            )
        )
    return tuple(requests)


def same_side_anatomy_priors(
    *,
    silhouette: np.ndarray,
    chest_region: np.ndarray,
    pelvic_region: np.ndarray,
    midline_x: int,
    character_left_is_lower_x: bool,
    view: str,
    clothing: np.ndarray | None = None,
    hair_occlusion: np.ndarray | None = None,
    ambiguity: np.ndarray | None = None,
    left_breast_region: np.ndarray | None = None,
    right_breast_region: np.ndarray | None = None,
) -> dict[str, AnatomySpatialPrior]:
    """Build side-correct spatial gates; these masks are never candidate/final authority."""
    visible = _mask(silhouette, "silhouette")
    chest = _matching_mask(chest_region, visible, "chest_region")
    pelvic = _matching_mask(pelvic_region, visible, "pelvic_region")
    blocked = np.zeros_like(visible)
    for name, value in (
        ("clothing", clothing),
        ("hair_occlusion", hair_occlusion),
        ("ambiguity", ambiguity),
    ):
        if value is not None:
            blocked |= _matching_mask(value, visible, name)
    available = visible & ~blocked
    chest &= available
    pelvic &= available
    if not 0 <= midline_x < visible.shape[1]:
        raise AnatomyV2DraftError("anatomy-v2 midline is outside the frame")
    xx = np.indices(visible.shape)[1]
    lower_x = xx < midline_x
    upper_x = ~lower_x
    left_half, right_half = (lower_x, upper_x) if character_left_is_lower_x else (upper_x, lower_x)
    left_chest = (
        _matching_mask(left_breast_region, visible, "left_breast_region") & chest
        if left_breast_region is not None
        else chest & left_half
    )
    right_chest = (
        _matching_mask(right_breast_region, visible, "right_breast_region") & chest
        if right_breast_region is not None
        else chest & right_half
    )
    if view == "left_profile":
        right_chest[:] = False
    elif view == "right_profile":
        left_chest[:] = False
    elif view == "back":
        left_chest[:] = False
        right_chest[:] = False
    elif view not in {"front", "left_3_4", "right_3_4"}:
        raise AnatomyV2DraftError(f"unsupported anatomy-v2 view: {view}")
    regions = {
        "left_areola": left_chest,
        "right_areola": right_chest,
        "left_nipple": left_chest,
        "right_nipple": right_chest,
        "vulva": pelvic,
        "penis_shaft": pelvic,
        "glans_penis": pelvic,
        "left_scrotal_region": pelvic & left_half,
        "right_scrotal_region": pelvic & right_half,
    }
    sides = {
        "left_areola": "character_left",
        "left_nipple": "character_left",
        "left_scrotal_region": "character_left",
        "right_areola": "character_right",
        "right_nipple": "character_right",
        "right_scrotal_region": "character_right",
    }
    return {
        label: AnatomySpatialPrior(label, region.copy(), sides.get(label, "center"), view)
        for label, region in regions.items()
    }


def proposal_to_sam2_plan(
    proposal: AnatomyBoxProposal,
    spatial_prior: AnatomySpatialPrior,
    *,
    silhouette: np.ndarray,
    neighbor_priors: tuple[np.ndarray, ...] = (),
) -> PromptPlan:
    """Intersect proposal box and geometry gate, then build a SAM2 prompt plan."""
    require_permitted_content_lane(proposal.content_lane_decision)
    if proposal.authority != "proposal_box_only" or proposal.label != spatial_prior.label:
        raise AnatomyV2DraftError("anatomy-v2 proposal/prior authority mismatch")
    if (
        proposal.label not in NEW_LABELS
        or not 0 <= proposal.box_score <= 1
        or not 0 <= proposal.text_score <= 1
    ):
        raise AnatomyV2DraftError("anatomy-v2 detector proposal is invalid")
    visible = _matching_mask(silhouette, spatial_prior.roi, "silhouette")
    box = _box_mask(spatial_prior.roi.shape, proposal.bbox_xyxy)
    seed = spatial_prior.roi.astype(bool) & visible & box
    if not seed.any():
        raise AnatomyV2DraftError(
            f"anatomy-v2 proposal has no defensible visible prior intersection: {proposal.label}"
        )
    points = _sample_points(seed, 5)
    return build_prompt_plan(
        proposal.label,
        seed.astype(np.float32) * max(proposal.box_score, proposal.text_score),
        skeleton_points_xy=points,
        neighbor_priors=neighbor_priors,
        skeleton_samples=5,
        prior_quality="low",
    )


def refine_anatomy_with_sam2(
    provider: Sam2Provider,
    embedding: Any,
    proposal: AnatomyBoxProposal,
    spatial_prior: AnatomySpatialPrior,
    *,
    silhouette: np.ndarray,
    visibility_state: str,
    model: str,
    clothing: np.ndarray | None = None,
    ambiguity: np.ndarray | None = None,
) -> AnatomyDraftCandidate:
    """Require SAM2 multimask output; low confidence never falls back to a prior mask."""
    require_permitted_content_lane(proposal.content_lane_decision)
    if proposal.label not in NEW_LABELS or proposal.label != spatial_prior.label:
        raise AnatomyV2DraftError("anatomy-v2 proposal/prior label mismatch")
    state = _state(visibility_state)
    correction = _correction_instruction(proposal.label, state)
    if state in EXPLICIT_NON_CANDIDATE_STATES:
        return AnatomyDraftCandidate(
            proposal.label,
            state,
            None,
            0.0,
            "suppressed_for_human_review",
            correction,
            {
                "suppressed": True,
                "reason": state,
                "detector_box_used_as_mask": False,
                "geometry_prior_used_as_mask": False,
                "sam2_required": True,
                "content_lane_decision": proposal.content_lane_decision,
            },
        )
    plan = proposal_to_sam2_plan(proposal, spatial_prior, silhouette=silhouette)
    seed = spatial_prior.roi.astype(bool) & _box_mask(spatial_prior.roi.shape, proposal.bbox_xyxy)
    refined: RefinedPart = refine_part(
        provider,
        embedding,
        plan,
        seed,
        model=model,
        skeleton_points_xy=plan.positive_points,
    )
    if refined.sam2_low_conf:
        return AnatomyDraftCandidate(
            proposal.label,
            state,
            None,
            refined.predicted_iou,
            "suppressed_for_human_review",
            correction,
            {
                "suppressed": True,
                "reason": "sam2_low_conf",
                "sam2_model": model,
                "sam2_required": True,
                "detector_box_used_as_mask": False,
                "geometry_prior_used_as_mask": False,
                "content_lane_decision": proposal.content_lane_decision,
            },
        )
    visible = _matching_mask(silhouette, spatial_prior.roi, "silhouette")
    blocked = np.zeros_like(visible)
    if clothing is not None:
        blocked |= _matching_mask(clothing, visible, "clothing")
    if ambiguity is not None:
        blocked |= _matching_mask(ambiguity, visible, "ambiguity")
    raw = np.asarray(refined.mask).astype(bool)
    final = raw & spatial_prior.roi.astype(bool) & visible & ~blocked
    if not final.any():
        return AnatomyDraftCandidate(
            proposal.label,
            state,
            None,
            refined.predicted_iou,
            "suppressed_for_human_review",
            correction,
            {
                "suppressed": True,
                "reason": "no_visible_pixels_after_clothing_ambiguity_clip",
                "sam2_model": model,
                "sam2_required": True,
                "detector_box_used_as_mask": False,
                "geometry_prior_used_as_mask": False,
                "content_lane_decision": proposal.content_lane_decision,
            },
        )
    return AnatomyDraftCandidate(
        proposal.label,
        state,
        final,
        refined.predicted_iou,
        "interactive_segmenter_refined_non_gold_review_draft",
        correction,
        {
            "suppressed": False,
            "prompt": proposal.prompt,
            "detector_box_xyxy": list(proposal.bbox_xyxy),
            "detector_box_score": proposal.box_score,
            "detector_text_score": proposal.text_score,
            "detector_box_used_as_mask": False,
            "spatial_prior_authority": spatial_prior.authority,
            "geometry_prior_used_as_mask": False,
            "sam2_required": True,
            "content_lane_decision": proposal.content_lane_decision,
            "interactive_segmenter_provider": "sam2",
            "sam2_model": model,
            "sam2_predicted_iou": refined.predicted_iou,
            "sam2_selection_score": refined.selection_score,
            "sam2_corrective_iteration": refined.corrective_iteration,
            "pixels_before_visibility_clip": int(np.count_nonzero(raw)),
            "pixels_after_visibility_clip": int(np.count_nonzero(final)),
            "clothing_or_ambiguity_pixels_removed": int(np.count_nonzero(raw & blocked)),
        },
    )


def fuse_anatomy_v2_candidates(
    existing_v1_masks: Mapping[str, np.ndarray],
    candidates: Mapping[str, AnatomyDraftCandidate],
    *,
    silhouette: np.ndarray,
    clothing: np.ndarray | None = None,
    ambiguity: np.ndarray | None = None,
    ontology_path: Path | str = DEFAULT_ONTOLOGY_V2,
) -> AnatomyFusionResult:
    """Fuse SAM2-only drafts and enforce v2 parent carve-outs before map construction."""
    ontology = load_ontology(ontology_path)
    if ontology.version != "body_parts_v2":
        raise AnatomyV2DraftError("anatomy-v2 fusion requires body_parts_v2 ontology")
    visible = _mask(silhouette, "silhouette")
    blocked = np.zeros_like(visible)
    if clothing is not None:
        blocked |= _matching_mask(clothing, visible, "clothing")
    ignore = (
        _matching_mask(ambiguity, visible, "ambiguity").copy()
        if ambiguity is not None
        else np.zeros_like(visible)
    )
    old: dict[str, np.ndarray] = {}
    for name, value in existing_v1_masks.items():
        label = ontology.label(name, require_enabled=True)
        if label.map != "part" or label.id is None or label.id > 55:
            raise AnatomyV2DraftError(f"anatomy-v2 existing mask is not a v1 PART atomic: {name}")
        old[name] = _matching_mask(value, visible, name) & visible
    new: dict[str, np.ndarray] = {}
    confidence_maps: dict[str, np.ndarray] = {}
    provenance: dict[str, Any] = {}
    for name in NEW_LABELS:
        candidate = candidates.get(name)
        if candidate is None or candidate.mask is None:
            new[name] = np.zeros_like(visible)
            confidence_maps[name] = np.zeros(visible.shape, dtype=np.float32)
            provenance[name] = {
                "status": "no_candidate",
                "correction_instruction": (
                    candidate.correction_instruction
                    if candidate is not None
                    else _correction_instruction(name, "unreviewed_for_v2")
                ),
            }
            continue
        if candidate.label != name or candidate.authority not in {
            "interactive_segmenter_refined_non_gold_review_draft",
            "sam2_refined_non_gold_review_draft",
        }:
            raise AnatomyV2DraftError(
                f"anatomy-v2 fusion refuses non-interactive-segmenter candidate authority: {name}"
            )
        state = _state(candidate.visibility_state)
        if state in EXPLICIT_NON_CANDIDATE_STATES:
            raise AnatomyV2DraftError(
                f"anatomy-v2 fusion refuses a mask for null/ambiguous state: {name}/{state}"
            )
        if not math.isfinite(candidate.confidence) or not 0 <= candidate.confidence <= 1:
            raise AnatomyV2DraftError(f"anatomy-v2 candidate confidence is invalid: {name}")
        if (
            candidate.provenance.get("content_lane_decision") not in PERMITTED_CONTENT_LANES
            or candidate.provenance.get("sam2_required") is not True
            or candidate.provenance.get("detector_box_used_as_mask") is not False
            or candidate.provenance.get("geometry_prior_used_as_mask") is not False
        ):
            raise AnatomyV2DraftError(
                "anatomy-v2 fusion refuses incompatible content-lane or unproven "
                f"interactive-segmenter candidate provenance: {name}"
            )
        mask = _matching_mask(candidate.mask, visible, name) & visible & ~blocked & ~ignore
        new[name] = mask
        confidence_maps[name] = mask.astype(np.float32) * float(candidate.confidence)
        provenance[name] = {
            "status": "candidate",
            "confidence": candidate.confidence,
            "authority": candidate.authority,
            "correction_instruction": candidate.correction_instruction,
            "provenance": candidate.provenance,
        }

    # Compatible carve-outs have explicit child ownership.
    new["left_areola"] &= ~new["left_nipple"]
    new["right_areola"] &= ~new["right_nipple"]
    new["penis_shaft"] &= ~new["glans_penis"]

    # Incompatible or side-conflicting overlap becomes ignore, never a guessed class.
    conflict_pairs = (
        ("left_areola", "right_areola"),
        ("left_nipple", "right_nipple"),
        ("vulva", "penis_shaft"),
        ("vulva", "glans_penis"),
        ("vulva", "left_scrotal_region"),
        ("vulva", "right_scrotal_region"),
        ("penis_shaft", "left_scrotal_region"),
        ("penis_shaft", "right_scrotal_region"),
        ("glans_penis", "left_scrotal_region"),
        ("glans_penis", "right_scrotal_region"),
        ("left_scrotal_region", "right_scrotal_region"),
    )
    conflict_pixels = 0
    for first, second in conflict_pairs:
        overlap = new[first] & new[second]
        if overlap.any():
            conflict_pixels += int(overlap.sum())
            ignore |= overlap
            new[first] &= ~overlap
            new[second] &= ~overlap

    parent_for = {
        "left_areola": "left_breast",
        "left_nipple": "left_breast",
        "right_areola": "right_breast",
        "right_nipple": "right_breast",
        **{name: "pelvic_region" for name in PELVIC_LABELS},
    }
    unrelated_pixels = 0
    for name, mask in new.items():
        if not mask.any():
            continue
        allowed_parent = parent_for[name]
        unrelated = np.zeros_like(visible)
        for old_name, old_mask in old.items():
            if old_name != allowed_parent:
                unrelated |= mask & old_mask
        if unrelated.any():
            unrelated_pixels += int(unrelated.sum())
            ignore |= unrelated
            new[name] &= ~unrelated

    carve_counts: dict[str, int] = {}
    for parent, children in (
        ("left_breast", ("left_areola", "left_nipple")),
        ("right_breast", ("right_areola", "right_nipple")),
        ("pelvic_region", PELVIC_LABELS),
    ):
        if parent not in old:
            continue
        carve = np.zeros_like(visible)
        for child in children:
            carve |= new[child]
        before = int(old[parent].sum())
        old[parent] &= ~carve
        carve_counts[parent] = before - int(old[parent].sum())

    atomic = {**old, **new}
    claimed = np.zeros_like(visible)
    for name, mask in atomic.items():
        overlap = claimed & mask
        if overlap.any():
            raise AnatomyV2DraftError(
                f"anatomy-v2 fusion left overlapping atomics: {name}/{int(overlap.sum())}"
            )
        claimed |= mask
    nonempty = {name: mask for name, mask in atomic.items() if mask.any()}
    if not nonempty:
        raise AnatomyV2DraftError("anatomy-v2 fusion has no nonempty atomic candidates")
    part_map = priority_argmax(nonempty, map_name="part", ontology=ontology)
    if np.any((part_map >= 56) & blocked):
        raise AnatomyV2DraftError("anatomy-v2 fusion leaked anatomy into clothing/blocked pixels")
    for name in NEW_LABELS:
        confidence_maps[name] = np.where(new[name], confidence_maps[name], 0).astype(np.float32)
    return AnatomyFusionResult(
        part_map,
        atomic,
        ignore,
        confidence_maps,
        {
            "schema_version": "1.0.0",
            "ontology_version": "body_parts_v2",
            "activation_status": "approved_design_not_active",
            "authority": "non_gold_review_draft",
            "detector_boxes_used_as_masks": False,
            "geometry_priors_used_as_masks": False,
            "sam2_required_for_new_positive_masks": True,
            "carve_pixels": carve_counts,
            "incompatible_overlap_pixels_to_ignore": conflict_pixels,
            "unrelated_v1_overlap_pixels_to_ignore": unrelated_pixels,
            "ambiguity_ignore_pixels": int(ignore.sum()),
            "provenance": provenance,
        },
    )


def write_anatomy_review_bundle(
    source: np.ndarray,
    fusion: AnatomyFusionResult,
    candidates: Mapping[str, AnatomyDraftCandidate],
    output_dir: Path,
) -> tuple[Path, Path, tuple[Path, ...]]:
    """Write non-gold masks, a review panel, and full correction provenance."""
    image = np.asarray(source)
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise AnatomyV2DraftError("anatomy-v2 review source must be uint8 RGB")
    if image.shape[:2] != fusion.part_map.shape:
        raise AnatomyV2DraftError("anatomy-v2 review source and fusion dimensions differ")
    output = Path(output_dir)
    masks_dir = output / "candidate_masks"
    paths = []
    for name in NEW_LABELS:
        mask = fusion.atomic_masks[name].astype(np.uint8) * 255
        paths.append(
            write_binary_mask(
                masks_dir / f"{name}.png", mask, source_size=(image.shape[1], image.shape[0])
            )
        )
    map_path = write_label_map(output / "label_map_part_v2_review.png", fusion.part_map, bits=16)
    overlay = image.copy()
    new_pixels = fusion.part_map >= 56
    overlay[new_pixels] = ((0.45 * overlay[new_pixels]) + (0.55 * np.array([255, 32, 160]))).astype(
        np.uint8
    )
    ignored = image.copy()
    ignored[fusion.ambiguity_ignore] = np.array([255, 220, 0], dtype=np.uint8)
    panel = np.concatenate((image, overlay, ignored), axis=1)
    panel_path = output / "anatomy_v2_review_panel.png"
    output.mkdir(parents=True, exist_ok=True)
    Image.fromarray(panel).save(panel_path, format="PNG")  # png-strict: allow - RGB review panel
    report = {
        **fusion.audit,
        "panel": panel_path.name,
        "panel_tiles": ["source", "v2_candidate_overlay", "ambiguity_ignore"],
        "part_map": map_path.name,
        "labels": {
            name: {
                "mask_file": f"candidate_masks/{name}.png",
                "mask_area_px": int(fusion.atomic_masks[name].sum()),
                "confidence_max": float(fusion.confidence_maps[name].max(initial=0)),
                "correction_instruction": _correction_instruction(
                    name,
                    (
                        candidates[name].visibility_state
                        if name in candidates
                        else "unreviewed_for_v2"
                    ),
                ),
                "provenance": fusion.audit["provenance"][name],
            }
            for name in NEW_LABELS
        },
        "human_review_required": True,
        "gold_approved": False,
    }
    report_path = output / "anatomy_v2_review.json"
    _write_json_atomic(report_path, report)
    return report_path, panel_path, tuple(paths)


def _state(value: str) -> str:
    if value not in V2_REVIEW_STATES:
        raise AnatomyV2DraftError(f"unknown anatomy-v2 visibility state: {value!r}")
    return value


def _mask(value: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != 2:
        raise AnatomyV2DraftError(f"anatomy-v2 {name} must be a 2-D mask")
    return array.astype(bool)


def _matching_mask(value: np.ndarray, reference: np.ndarray, name: str) -> np.ndarray:
    result = _mask(value, name)
    if result.shape != reference.shape:
        raise AnatomyV2DraftError(f"anatomy-v2 {name} dimensions differ")
    return result


def _expand_box(
    bbox: tuple[int, int, int, int], image_size: tuple[int, int], scale: float
) -> tuple[int, int, int, int]:
    if len(bbox) != 4 or scale < 1:
        raise AnatomyV2DraftError("anatomy-v2 crop box/scale is invalid")
    left, top, right, bottom = map(float, bbox)
    width, height = image_size
    if not all(math.isfinite(value) for value in (left, top, right, bottom)) or not (
        left < right and top < bottom
    ):
        raise AnatomyV2DraftError("anatomy-v2 crop box is invalid")
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    half_width, half_height = (right - left) * scale / 2, (bottom - top) * scale / 2
    result = (
        max(0, math.floor(center_x - half_width)),
        max(0, math.floor(center_y - half_height)),
        min(width, math.ceil(center_x + half_width)),
        min(height, math.ceil(center_y + half_height)),
    )
    if result[0] >= result[2] or result[1] >= result[3]:
        raise AnatomyV2DraftError("anatomy-v2 crop is outside the source frame")
    return result


def _box_mask(shape: tuple[int, int], bbox: tuple[int, int, int, int]) -> np.ndarray:
    height, width = shape
    if len(bbox) != 4:
        raise AnatomyV2DraftError("anatomy-v2 proposal bbox requires four values")
    left, top, right, bottom = bbox
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise AnatomyV2DraftError("anatomy-v2 proposal bbox is outside the source")
    output = np.zeros(shape, dtype=bool)
    output[top:bottom, left:right] = True
    return output


def _sample_points(mask: np.ndarray, count: int) -> tuple[tuple[int, int], ...]:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise AnatomyV2DraftError("cannot sample anatomy-v2 points from an empty gate")
    indices = np.linspace(0, len(xs) - 1, count, dtype=int)
    return tuple((int(xs[index]), int(ys[index])) for index in indices)


def _correction_instruction(label: str, state: str) -> str:
    boundaries = {
        "left_areola": "Confirm the character-left visible areolar ring and exclude nipple pixels.",
        "right_areola": "Confirm the character-right visible areolar ring and exclude nipple pixels.",
        "left_nipple": "Confirm only the character-left visible nipple carve-out.",
        "right_nipple": "Confirm only the character-right visible nipple carve-out.",
        "vulva": "Confirm visible external vulvar surface only; never infer an internal canal.",
        "penis_shaft": "Confirm visible shaft or foreskin surface and exclude visible glans.",
        "glans_penis": "Confirm visible glans only and exclude covered extent.",
        "left_scrotal_region": "Confirm character-left external scrotal surface at a defensible midline.",
        "right_scrotal_region": "Confirm character-right external scrotal surface at a defensible midline.",
    }
    suffix = (
        " Keep the mask null and record the state evidence."
        if state in V2_NULL_MASK_STATES
        else " Route unresolved boundary pixels to ambiguous_do_not_use."
    )
    return boundaries[label] + suffix


def _write_json_atomic(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
