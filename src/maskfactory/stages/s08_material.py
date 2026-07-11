"""S08 evidence-gated clothing/material fusion and specialist refinements."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image
from scipy import ndimage
from skimage.morphology import skeletonize

from ..io.png_strict import write_label_map
from ..models.registry import (
    DEFAULT_MODELS_ROOT,
    DEFAULT_REGISTRY,
    ModelRegistryError,
    resolve_registered_role,
)
from .s05_geometry import PromptPlan, build_prompt_plan
from .s07_sam2 import RefinedPart, Sam2Provider, build_embedding, refine_part


class MaterialError(ValueError):
    """Material evidence violates the S08 contract."""


@dataclass(frozen=True)
class MaterialDraft:
    regions: dict[str, np.ndarray]
    material_map: np.ndarray
    evidence: dict[str, tuple[str, ...]]


MATERIAL_IDS = {
    "skin": 1,
    "hair_material": 2,
    "clothing_generic": 3,
    "bra": 4,
    "underwear_bottom": 5,
    "top_garment": 6,
    "bottom_garment": 7,
    "footwear": 8,
    "accessory": 9,
    "strap": 10,
    "waistband": 11,
    "lace_or_sheer": 12,
    "glove_or_sock": 15,
}


def fuse_material_evidence(
    *,
    sapiens_skin: np.ndarray,
    sapiens_clothing: np.ndarray,
    schp_regions: Mapping[str, np.ndarray],
    gdino_boxes: Mapping[str, tuple[tuple[int, int, int, int], ...]],
    silhouette: np.ndarray,
    sapiens_hair: np.ndarray | None = None,
) -> MaterialDraft:
    """Fuse parsers/boxes; bra and underwear require explicit class/box evidence."""
    skin_seed = _mask(sapiens_skin, "sapiens_skin")
    clothing_seed = _mask(sapiens_clothing, "sapiens_clothing")
    visible = _mask(silhouette, "silhouette")
    shape = visible.shape
    if skin_seed.shape != shape or clothing_seed.shape != shape:
        raise MaterialError("Sapiens/material dimensions differ")
    schp = {name: _shape(mask, shape, name) for name, mask in schp_regions.items()}
    box_masks = {prompt: _boxes(shape, boxes) for prompt, boxes in gdino_boxes.items()}
    top = _union(shape, *(schp.get(name) for name in ("upper_clothes", "dress")))
    bottom = _union(shape, *(schp.get(name) for name in ("pants", "skirt")))
    footwear = _union(shape, schp.get("left_shoe"), schp.get("right_shoe"), box_masks.get("shoe"))
    accessory = _union(
        shape,
        *(schp.get(name) for name in ("hat", "sunglasses", "bag", "scarf")),
        box_masks.get("necklace"),
    )
    bra = _union(shape, schp.get("bra"), box_masks.get("bra"))
    underwear = _union(shape, schp.get("underwear"), box_masks.get("underwear"))
    clothing = (
        _union(
            shape,
            clothing_seed,
            top,
            bottom,
            footwear,
            bra,
            underwear,
            box_masks.get("glove"),
        )
        & visible
    )
    regions = {
        "skin": skin_seed & ~clothing & visible,
        "hair_material": (
            _shape(sapiens_hair, shape, "sapiens_hair") & visible
            if sapiens_hair is not None
            else np.zeros(shape, dtype=bool)
        ),
        "clothing_generic": clothing.copy(),
        "top_garment": top & visible,
        "bottom_garment": bottom & visible,
        "footwear": footwear & visible,
        "accessory": accessory & visible,
        "bra": bra & visible,
        "underwear_bottom": underwear & visible,
    }
    # Specific evidence owns its pixels; generic is only the unclassified clothing remainder.
    specific = _union(
        shape,
        *(
            regions[name]
            for name in ("top_garment", "bottom_garment", "footwear", "bra", "underwear_bottom")
        ),
    )
    regions["clothing_generic"] &= ~specific
    material_map = build_material_map(regions, visible)
    evidence = {
        "skin": ("sapiens_skin", "not_clothing"),
        "hair_material": ("sapiens_hair",),
        "clothing_generic": ("sapiens_clothing", "unclassified_remainder"),
        "top_garment": ("schp_upper_or_dress",),
        "bottom_garment": ("schp_pants_or_skirt",),
        "footwear": ("schp_or_gdino_shoe",),
        "accessory": ("schp_or_gdino_accessory",),
        "bra": ("schp_or_gdino_bra_required",),
        "underwear_bottom": ("schp_or_gdino_underwear_required",),
    }
    return MaterialDraft(regions, material_map, evidence)


def thin_structure_pass(
    clothing: np.ndarray,
    *,
    torso_width: float,
    shoulder_region: np.ndarray,
    iliac_y: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Classify <4%-torso-width skeleton components by orientation/location."""
    garment = _mask(clothing, "clothing")
    shoulder = _shape(shoulder_region, garment.shape, "shoulder_region")
    if torso_width <= 0:
        raise MaterialError("torso_width must be positive")
    centerline = skeletonize(garment)
    local_width = 2 * ndimage.distance_transform_edt(garment)
    thin = centerline & (local_width < 0.04 * torso_width)
    labels, count = ndimage.label(thin)
    strap = np.zeros_like(garment)
    waistband = np.zeros_like(garment)
    for index in range(1, count + 1):
        component = labels == index
        ys, xs = np.nonzero(component)
        if len(xs) < 2:
            continue
        vertical = (ys.max() - ys.min()) > (xs.max() - xs.min())
        expanded = (
            ndimage.binary_dilation(component, iterations=max(1, round(0.02 * torso_width)))
            & garment
        )
        if vertical and np.any(expanded & shoulder):
            strap |= expanded
        elif not vertical and abs(float(ys.mean()) - iliac_y) <= 0.08 * torso_width:
            waistband |= expanded
    return strap, waistband


def detect_sheer(
    source_rgb: np.ndarray,
    clothing: np.ndarray,
    adjacent_skin: np.ndarray,
    *,
    similarity_threshold: float = 0.8,
) -> np.ndarray:
    """Mark clothing whose normalized chroma cosine similarity to adjacent skin exceeds .8."""
    image = np.asarray(source_rgb, dtype=np.float32)
    garment = _mask(clothing, "clothing")
    skin = _shape(adjacent_skin, garment.shape, "adjacent_skin")
    if image.shape != (*garment.shape, 3):
        raise MaterialError("source RGB dimensions differ")
    adjacent = skin & ndimage.binary_dilation(garment, iterations=3)
    if not adjacent.any():
        return np.zeros_like(garment)
    skin_chroma = _chroma(image[adjacent]).mean(axis=0)
    garment_chroma = _chroma(image)
    denominator = np.linalg.norm(garment_chroma, axis=2) * np.linalg.norm(skin_chroma)
    similarity = np.divide(
        np.sum(garment_chroma * skin_chroma, axis=2),
        denominator,
        out=np.zeros(garment.shape, dtype=np.float32),
        where=denominator > 0,
    )
    return garment & (similarity > similarity_threshold)


def refine_material_regions(
    provider: Sam2Provider,
    embedding: object,
    regions: Mapping[str, np.ndarray],
    plans: Mapping[str, PromptPlan],
    *,
    model: str,
    hand_foot_region: np.ndarray,
    clothing_texture: np.ndarray,
) -> dict[str, RefinedPart | np.ndarray]:
    """SAM2-refine every supplied region and add glove/sock material protection."""
    if set(regions) != set(plans):
        raise MaterialError("every material region requires exactly one prompt plan")
    refined: dict[str, RefinedPart | np.ndarray] = {
        name: refine_part(provider, embedding, plans[name], mask, model=model)
        for name, mask in regions.items()
    }
    hand_foot = _mask(hand_foot_region, "hand_foot_region")
    texture = _shape(clothing_texture, hand_foot.shape, "clothing_texture")
    refined["glove_or_sock"] = hand_foot & texture
    return refined


def build_material_map(regions: Mapping[str, np.ndarray], silhouette: np.ndarray) -> np.ndarray:
    visible = _mask(silhouette, "silhouette")
    output = np.zeros(visible.shape, dtype=np.uint8)
    priority = (
        "skin",
        "hair_material",
        "clothing_generic",
        "top_garment",
        "bottom_garment",
        "footwear",
        "accessory",
        "bra",
        "underwear_bottom",
        "strap",
        "waistband",
        "lace_or_sheer",
        "glove_or_sock",
    )
    for name in priority:
        if name in regions:
            output[_shape(regions[name], visible.shape, name) & visible] = MATERIAL_IDS[name]
    return output


def run_s08_production(
    *,
    source_path: Path,
    sapiens_path: Path | None,
    schp_path: Path,
    silhouette_path: Path,
    pose_path: Path,
    gdino_path: Path,
    context_bbox_xyxy: tuple[int, int, int, int],
    sapiens_map: Mapping[int, Mapping[str, Any]],
    schp_map: Mapping[int, Mapping[str, Any]],
    output_dir: Path,
    provider: Sam2Provider | None = None,
    primary_model: str = "sam2.1_hiera_large",
    fallback_model: str = "sam2.1_hiera_base_plus",
    champion_loader=None,
    model_registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
) -> MaterialDraft:
    """Fuse S03/S06 material evidence in the S01 context coordinate system."""
    source = np.asarray(Image.open(source_path).convert("RGB"))
    schp_labels = np.asarray(Image.open(schp_path))
    labels = (
        np.asarray(Image.open(sapiens_path))
        if sapiens_path and Path(sapiens_path).is_file()
        else schp_labels
    )
    active_map = sapiens_map if sapiens_path and Path(sapiens_path).is_file() else schp_map
    left, top, right, bottom = context_bbox_xyxy
    visible = np.asarray(Image.open(silhouette_path).convert("L"))[top:bottom, left:right] > 0
    if (
        source.shape[:2] != labels.shape
        or labels.shape != schp_labels.shape
        or labels.shape != visible.shape
    ):
        raise MaterialError("S08 context-crop evidence dimensions differ")
    registry_document = json.loads(Path(model_registry_path).read_text(encoding="utf-8"))
    champion_entries = [
        entry
        for entry in registry_document.get("models", [])
        if entry.get("role") == "champion_clothing"
    ]
    if champion_entries:
        if len(champion_entries) != 1:
            raise MaterialError("expected exactly one champion_clothing registry entry")
        if champion_loader is None:
            raise MaterialError(
                "champion_clothing is promoted but no production loader is configured"
            )
        try:
            checkpoint = resolve_registered_role(
                "champion_clothing",
                registry_path=model_registry_path,
                models_root=models_root,
            )
        except ModelRegistryError as exc:
            raise MaterialError(f"champion clothing resolution failed: {exc}") from exc
        model = champion_loader(checkpoint)
        try:
            champion_map = np.asarray(model(source))
        finally:
            close = getattr(model, "close", None)
            if callable(close):
                close()
            del model
        if champion_map.shape != visible.shape or not np.issubdtype(champion_map.dtype, np.integer):
            raise MaterialError("champion clothing output must be integer HxW at context geometry")
        unknown = set(np.unique(champion_map).tolist()) - set(range(16))
        if unknown:
            raise MaterialError(f"champion clothing output has unknown IDs: {sorted(unknown)}")
        champion_map = champion_map.astype(np.uint8, copy=True)
        if np.any(champion_map[~visible] != 0) or np.any(champion_map[visible] == 0):
            raise MaterialError("champion clothing map violates silhouette containment/coverage")
        regions = {name: champion_map == material_id for name, material_id in MATERIAL_IDS.items()}
        evidence = {name: ("champion_clothing",) for name in regions}
        output_dir = Path(output_dir)
        write_label_map(output_dir / "material_draft.png", champion_map, bits=8)
        checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        (output_dir / "material_evidence.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "primary": "champion_clothing",
                    "fallback": "schp_plus_s08_heuristics",
                    "checkpoint_sha256": checkpoint_sha,
                    "evidence": evidence,
                    "sam2_refinement": {},
                    "pixel_counts": {name: int(mask.sum()) for name, mask in regions.items()},
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return MaterialDraft(regions, champion_map, evidence)

    def material_mask(mapping, indexed, material: str) -> np.ndarray:
        ids = [
            int(index)
            for index, entry in mapping.items()
            if material in entry.get("material_priors", ())
        ]
        return np.isin(indexed, ids)

    skin = material_mask(active_map, labels, "skin")
    hair = material_mask(active_map, labels, "hair_material")
    clothing = np.zeros(labels.shape, dtype=bool)
    for index, entry in active_map.items():
        priors = set(entry.get("material_priors", ()))
        if priors - {"skin", "hair_material", "none_background"}:
            clothing |= labels == int(index)
    schp_regions = {
        entry["class"]: schp_labels == int(index)
        for index, entry in schp_map.items()
        if entry["class"] != "background"
    }
    gdino = json.loads(Path(gdino_path).read_text(encoding="utf-8"))
    boxes: dict[str, list[tuple[int, int, int, int]]] = {}
    for proposal in gdino["proposals"]:
        boxes.setdefault(proposal["prompt"], []).append(
            tuple(round(float(value)) for value in proposal["bbox_xyxy"])
        )
    draft = fuse_material_evidence(
        sapiens_skin=skin,
        sapiens_clothing=clothing,
        schp_regions=schp_regions,
        gdino_boxes={key: tuple(value) for key, value in boxes.items()},
        silhouette=visible,
        sapiens_hair=hair,
    )
    regions = dict(draft.regions)
    pose = json.loads(Path(pose_path).read_text(encoding="utf-8"))
    keypoints = {item["index"]: item for item in pose["keypoints"]}
    required = [keypoints.get(index) for index in (5, 6, 11, 12)]
    if all(item is not None and item["confidence"] >= 0.3 for item in required):
        points = [(float(item["x"]) - left, float(item["y"]) - top) for item in required]
        torso_width = max(1.0, abs(points[0][0] - points[1][0]))
        shoulder = np.zeros(labels.shape, dtype=bool)
        for x, y in points[:2]:
            yy, xx = np.indices(labels.shape)
            shoulder |= (xx - x) ** 2 + (yy - y) ** 2 <= (0.12 * torso_width) ** 2
        iliac_y = (points[2][1] + points[3][1]) / 2
        strap, waistband = thin_structure_pass(
            clothing, torso_width=torso_width, shoulder_region=shoulder, iliac_y=iliac_y
        )
        regions["strap"], regions["waistband"] = strap, waistband
    regions["lace_or_sheer"] = detect_sheer(source, clothing, regions["skin"])
    refinement_metrics: dict[str, dict[str, Any]] = {}
    if provider is not None:
        embedding = None
        try:
            embedding, model = build_embedding(
                provider, source, primary_model=primary_model, fallback_model=fallback_model
            )
            for name, seed in tuple(regions.items()):
                if not seed.any():
                    continue
                plan = build_prompt_plan(
                    name,
                    seed,
                    skeleton_points_xy=(),
                    skeleton_samples=3,
                    prior_quality="low",
                )
                refined = refine_part(provider, embedding, plan, seed, model=model)
                regions[name] = refined.mask
                refinement_metrics[name] = {
                    "predicted_iou": refined.predicted_iou,
                    "selection_score": refined.selection_score,
                    "corrective_iteration": refined.corrective_iteration,
                    "sam2_low_conf": refined.sam2_low_conf,
                    "review_flags": refined.review_flags,
                    "model": refined.model,
                }
        finally:
            if embedding is not None and hasattr(provider, "close"):
                provider.close(embedding)  # type: ignore[attr-defined]
    material_map = build_material_map(regions, visible)
    output_dir = Path(output_dir)
    write_label_map(output_dir / "material_draft.png", material_map, bits=8)
    evidence = dict(draft.evidence)
    evidence.update(
        {
            "strap": ("thin_structure",),
            "waistband": ("thin_structure",),
            "lace_or_sheer": ("chroma_similarity_gt_0.8",),
        }
    )
    (output_dir / "material_evidence.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "primary": "schp_plus_s08_heuristics",
                "fallback": None,
                "evidence": evidence,
                "sam2_refinement": refinement_metrics,
                "pixel_counts": {name: int(mask.sum()) for name, mask in regions.items()},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return MaterialDraft(regions, material_map, evidence)


def _mask(value, name):
    array = np.asarray(value)
    if array.ndim != 2:
        raise MaterialError(f"{name} must be 2-D")
    return array.astype(bool)


def _shape(value, shape, name):
    mask = _mask(value, name)
    if mask.shape != shape:
        raise MaterialError(f"{name} dimensions differ")
    return mask


def _union(shape, *values):
    output = np.zeros(shape, dtype=bool)
    for value in values:
        if value is not None:
            output |= _shape(value, shape, "material evidence")
    return output


def _boxes(shape, boxes):
    output = np.zeros(shape, dtype=bool)
    for left, top, right, bottom in boxes:
        left, top = max(0, left), max(0, top)
        right, bottom = min(shape[1], right), min(shape[0], bottom)
        if right > left and bottom > top:
            output[top:bottom, left:right] = True
    return output


def _chroma(rgb):
    mean = rgb.mean(axis=-1, keepdims=True)
    return rgb - mean
