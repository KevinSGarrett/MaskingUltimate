"""S09 weighted consensus, z-order arbitration, and authoritative map emission."""

from __future__ import annotations

import hashlib
import json
import os
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image
from scipy import ndimage

from ..io.png_strict import write_binary_mask, write_grayscale, write_label_map
from ..models.registry import (
    DEFAULT_MODELS_ROOT,
    DEFAULT_REGISTRY,
    ModelRegistryError,
    resolve_registered_role,
)
from ..ontology import Ontology, OntologyError, get_ontology


class FusionError(ValueError):
    """Fusion evidence cannot satisfy the S09 map contract."""


@dataclass(frozen=True)
class ZOrderDecision:
    winner: str
    loser: str
    reason: str


@dataclass(frozen=True)
class OcclusionRecord:
    occluding_part: str
    occluded_part: str
    reason: str
    contested_pixels: int
    occluded_visibility: str = "partially_visible"


@dataclass(frozen=True)
class FusionResult:
    part_map_path: Path
    material_map_path: Path
    disagreement_path: Path
    region_paths: tuple[Path, ...]
    consensus_scores: dict[str, float]
    review_routes: dict[str, str]
    occlusions: tuple[OcclusionRecord, ...]
    artifact_sha256: dict[str, str]


def configure_determinism(seed: int = 1337) -> dict[str, object]:
    """Apply the fixed seed and strict PyTorch deterministic execution contract."""
    if seed != 1337:
        raise FusionError("MaskFactory pipeline seed must remain 1337")
    os.environ["PYTHONHASHSEED"] = str(seed)
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    random.seed(seed)
    np.random.seed(seed)
    torch_configured = False
    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        torch.use_deterministic_algorithms(True)
        if hasattr(torch.backends, "cudnn"):
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True
        torch_configured = True
    except ImportError:
        pass
    return {
        "seed": seed,
        "pythonhashseed": os.environ["PYTHONHASHSEED"],
        "cublas_workspace_config": os.environ["CUBLAS_WORKSPACE_CONFIG"],
        "torch_configured": torch_configured,
    }


def fuse_consensus(
    *,
    part_evidence: Mapping[str, Mapping[str, np.ndarray]],
    material_evidence: Mapping[str, Mapping[str, np.ndarray]] | None = None,
    s08_material_map: np.ndarray | None = None,
    silhouette: np.ndarray,
    output_dir: Path,
    weights: Mapping[str, float],
    zorder_decisions: tuple[ZOrderDecision, ...] = (),
    region_bands: Mapping[str, np.ndarray] | None = None,
    contested_threshold: float = 0.4,
    quick_pass_min: float = 0.85,
    normal_min: float = 0.60,
    ontology: Ontology | None = None,
) -> FusionResult:
    """Fuse source stacks into exclusive maps and all S09 audit artifacts."""
    configure_determinism()
    authority = ontology or get_ontology()
    visible = np.asarray(silhouette).astype(bool)
    if visible.ndim != 2 or not visible.any():
        raise FusionError("silhouette must be a non-empty 2-D mask")
    _validate_weights(weights)
    part_names, part_stack = _score_labels(part_evidence, weights, visible.shape, authority, "part")
    if (material_evidence is None) == (s08_material_map is None):
        raise FusionError("provide exactly one of material_evidence or s08_material_map")
    part_stack[:, ~visible] = 0
    if s08_material_map is None:
        material_names, material_stack = _score_labels(
            material_evidence, weights, visible.shape, authority, "material"
        )
        material_stack[:, ~visible] = 0
        if np.any(np.max(material_stack, axis=0)[visible] <= 0):
            raise FusionError("material evidence leaves silhouette pixels unassigned")
        material_ids = np.asarray(
            [authority.label(name).id for name in material_names], dtype=np.uint8
        )
        material_map = material_ids[np.argmax(material_stack, axis=0)]
    else:
        material_map = np.asarray(s08_material_map)
        allowed_ids = {
            int(label.id) for label in authority.labels_for_map("material", enabled_only=True)
        }
        if (
            material_map.shape != visible.shape
            or not set(np.unique(material_map).tolist()) <= allowed_ids
        ):
            raise FusionError("S08 material map dimensions or ontology IDs invalid")
        material_map = material_map.astype(np.uint8, copy=True)
        if np.any(material_map[visible] == 0):
            raise FusionError("S08 material map leaves silhouette pixels unassigned")
    if np.any(np.max(part_stack, axis=0)[visible] <= 0):
        raise FusionError("part evidence leaves silhouette pixels unassigned")

    contested = _contested(part_stack, contested_threshold) & visible
    records = _apply_zorder(part_stack, part_names, contested, zorder_decisions, authority)
    part_ids = np.asarray([authority.label(name).id for name in part_names], dtype=np.uint16)
    part_map = part_ids[np.argmax(part_stack, axis=0)]
    part_map[~visible] = 0
    material_map[~visible] = 0
    if np.any(part_map[visible] == 0):
        raise FusionError("background may only be outside the silhouette")

    if part_stack.shape[0] == 1:
        top1, top2 = part_stack[0], np.zeros_like(part_stack[0])
    else:
        top = np.partition(part_stack, -2, axis=0)[-2:]
        top1, top2 = np.max(top, axis=0), np.min(top, axis=0)
    disagreement = np.zeros(visible.shape, dtype=np.float32)
    disagreement[visible] = np.divide(
        top2[visible], top1[visible], out=np.zeros_like(top2[visible]), where=top1[visible] > 0
    )
    disagreement_u8 = np.rint(disagreement * 255).astype(np.uint8)

    consensus_scores, routes = _consensus_summary(
        part_names, part_stack, part_map, authority, quick_pass_min, normal_min
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    part_path = write_label_map(output_dir / "label_map_part.png", part_map, bits=16)
    material_path = write_label_map(output_dir / "label_map_material.png", material_map, bits=8)
    disagreement_path = write_grayscale(
        output_dir / "work" / "s09" / "disagreement.png",
        disagreement_u8,
        source_size=(visible.shape[1], visible.shape[0]),
    )
    bands = dict(region_bands or {})
    bands["overlap_occlusion_boundary"] = _boundary_band(contested, radius=3)
    region_paths = []
    for name, value in sorted(bands.items()):
        mask = np.asarray(value).astype(bool)
        if mask.shape != visible.shape:
            raise FusionError(f"region band {name} dimensions differ")
        region_paths.append(
            write_binary_mask(
                output_dir / "masks_regions" / f"{name}.png",
                mask,
                source_size=(visible.shape[1], visible.shape[0]),
            )
        )
    metrics_path = output_dir / "work" / "s09" / "consensus.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(
        json.dumps(
            {
                "consensus_scores": consensus_scores,
                "sources": sorted(
                    {source for label_sources in part_evidence.values() for source in label_sources}
                ),
                "review_routes": routes,
                "occlusions": [asdict(record) for record in records],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts = (part_path, material_path, disagreement_path, *region_paths, metrics_path)
    hashes = {
        path.relative_to(output_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in artifacts
    }
    return FusionResult(
        part_path,
        material_path,
        disagreement_path,
        tuple(region_paths),
        consensus_scores,
        routes,
        tuple(records),
        hashes,
    )


def make_waist_band(
    silhouette: np.ndarray,
    *,
    shoulder_mid_y: float,
    hip_mid_y: float,
) -> np.ndarray:
    """Doc-02 waist band: 12% shoulder-to-hip distance, centered above iliac line."""
    visible = np.asarray(silhouette).astype(bool)
    height = max(1, round(abs(hip_mid_y - shoulder_mid_y) * 0.12))
    center = round(hip_mid_y - height / 2)
    yy = np.indices(visible.shape)[0]
    return visible & (yy >= center - height // 2) & (yy <= center + height // 2)


def make_contact_band(contact_pixels: np.ndarray, *, reference_width: int = 1024) -> np.ndarray:
    """Doc-02 contact boundary at 8 px on a 1024 reference, scaled by width."""
    contact = np.asarray(contact_pixels).astype(bool)
    radius = max(1, round(8 * contact.shape[1] / reference_width))
    return ndimage.binary_dilation(contact, iterations=radius) & ~ndimage.binary_erosion(
        contact, iterations=radius
    )


def run_s09_production(
    *,
    s03_dir: Path,
    s05_dir: Path,
    s07_dir: Path,
    s08_material_path: Path,
    s08_5_iuv_path: Path,
    silhouette_path: Path,
    pose_path: Path,
    context_bbox_xyxy: tuple[int, int, int, int],
    parsing_maps: Mapping[str, Mapping[int, Mapping[str, Any]]],
    weights: Mapping[str, float],
    output_dir: Path,
    ontology: Ontology | None = None,
    other_person_protected_path: Path | None = None,
    model_registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
) -> FusionResult:
    """Assemble authoritative on-disk evidence into the exclusive S09 master maps."""
    authority = ontology or get_ontology()
    material_map = np.asarray(Image.open(s08_material_path))
    shape = material_map.shape
    left, top, right, bottom = context_bbox_xyxy
    visible = np.asarray(Image.open(silhouette_path).convert("L"))[top:bottom, left:right] > 0
    if visible.shape != shape:
        raise FusionError("S09 projected silhouette and context artifacts differ")
    evidence: dict[str, dict[str, np.ndarray]] = {}

    def add(label: str, source: str, value: np.ndarray) -> None:
        try:
            definition = authority.label(label, require_enabled=True)
        except OntologyError:
            return
        if definition.map != "part" or definition.id == 0:
            return
        array = np.asarray(value)
        if array.shape != shape:
            raise FusionError(f"S09 evidence dimensions differ for {label}/{source}")
        current = evidence.setdefault(label, {}).get(source)
        evidence[label][source] = array if current is None else np.maximum(current, array)

    for path in sorted(Path(s05_dir).glob("prior_*.png")):
        add(path.stem.removeprefix("prior_"), "geometry", np.asarray(Image.open(path)))
    for path in sorted(Path(s07_dir).glob("sam2_*.png")):
        add(path.stem.removeprefix("sam2_"), "sam2", np.asarray(Image.open(path)))
    custom_path = Path(s03_dir) / "custom_bodypart.png"
    if custom_path.is_file():
        provenance_path = Path(s03_dir) / "custom_bodypart_provenance.json"
        if not provenance_path.is_file():
            raise FusionError("custom_bodypart map lacks champion provenance")
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        if provenance.get("role") != "champion_bodypart":
            raise FusionError("custom_bodypart provenance role is not champion_bodypart")
        try:
            checkpoint = resolve_registered_role(
                "champion_bodypart",
                registry_path=model_registry_path,
                models_root=models_root,
            )
        except ModelRegistryError as exc:
            raise FusionError(f"custom_bodypart champion resolution failed: {exc}") from exc
        checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        if provenance.get("checkpoint_sha256") != checkpoint_sha:
            raise FusionError("custom_bodypart provenance checkpoint does not match champion")
        custom = np.asarray(Image.open(custom_path))
        allowed = {
            int(label.id): label.name
            for label in authority.labels_for_map("part", enabled_only=True)
            if label.id is not None
        }
        if custom.shape != shape or set(np.unique(custom).tolist()) - set(allowed):
            raise FusionError("custom_bodypart map dimensions or ontology IDs invalid")
        for label_id, name in allowed.items():
            if label_id and np.any(custom == label_id):
                add(name, "custom_bodypart", custom == label_id)
    if other_person_protected_path is not None and Path(other_person_protected_path).is_file():
        protected_full = np.asarray(Image.open(other_person_protected_path).convert("L"))
        add("other_person", "geometry", protected_full[top:bottom, left:right])
    candidate_labels = frozenset(evidence)
    for stem, source in (("sapiens_28", "sapiens"), ("schp_atr", "schp")):
        indexed_path = Path(s03_dir) / f"{stem}.png"
        if not indexed_path.is_file():
            continue
        indexed = np.asarray(Image.open(indexed_path))
        for class_id, entry in parsing_maps[stem].items():
            confidence_path = Path(s03_dir) / f"{stem}_confidence/class_{int(class_id):02d}.png"
            value = (
                np.asarray(Image.open(confidence_path))
                if confidence_path.is_file()
                else (indexed == int(class_id)).astype(np.uint8) * 255
            )
            for label in entry.get("part_priors", ()):
                # Broad parser classes support body-aware candidates; they cannot instantiate
                # a fine-grained atomic (for example wrist vs forearm) on their own.
                if label in candidate_labels:
                    add(label, source, value)

    iuv = np.asarray(Image.open(s08_5_iuv_path).convert("RGB"))
    if iuv.shape[:2] != shape:
        raise FusionError("S09 DensePose and context artifacts differ")
    surfaces = iuv[:, :, 0]
    left_surfaces = np.isin(surfaces, (4, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23))
    right_surfaces = np.isin(surfaces, (3, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24))
    for label, sources in tuple(evidence.items()):
        seed = np.maximum.reduce([np.asarray(value) for value in sources.values()]) > 0
        side = authority.label(label).side
        support = seed & (
            left_surfaces if side == "left" else right_surfaces if side == "right" else surfaces > 0
        )
        if support.any():
            add(label, "densepose", support.astype(np.uint8) * 255)

    _fill_unassigned_geometry(evidence, visible)
    if np.any(material_map[visible] == 0):
        raise FusionError("S08 material map leaves projected silhouette pixels unassigned")
    pose = json.loads(Path(pose_path).read_text(encoding="utf-8"))
    points = {item["index"]: item for item in pose["keypoints"]}
    region_bands = {}
    if all(points[index]["confidence"] >= 0.3 for index in (5, 6, 11, 12)):
        shoulder_y = ((points[5]["y"] + points[6]["y"]) / 2) - top
        hip_y = ((points[11]["y"] + points[12]["y"]) / 2) - top
        region_bands["waist"] = make_waist_band(visible, shoulder_mid_y=shoulder_y, hip_mid_y=hip_y)
    for path in sorted(Path(s07_dir).glob("*_finger_occlusion_boundary.png")):
        band = np.asarray(Image.open(path).convert("L")) > 0
        if band.shape != shape:
            raise FusionError(f"S07 hand-lane band dimensions differ: {path}")
        region_bands[path.stem] = band
    protection_decisions = (
        tuple(
            ZOrderDecision("other_person", label, "co_subject_protection")
            for label in evidence
            if label != "other_person"
        )
        if "other_person" in evidence
        else ()
    )
    return fuse_consensus(
        part_evidence=evidence,
        s08_material_map=material_map,
        silhouette=visible,
        output_dir=output_dir,
        weights=weights,
        region_bands=region_bands,
        zorder_decisions=protection_decisions,
    )


def _fill_unassigned_geometry(
    evidence: dict[str, dict[str, np.ndarray]], visible: np.ndarray
) -> None:
    """Give uncovered silhouette pixels a weak nearest body-prior vote, never background."""
    seeds = {
        label: np.maximum.reduce([np.asarray(value) for value in sources.values()]) > 0
        for label, sources in evidence.items()
    }
    covered = np.logical_or.reduce(tuple(seeds.values())) if seeds else np.zeros_like(visible)
    missing = visible & ~covered
    seeded = [(label, mask) for label, mask in seeds.items() if mask.any()]
    if missing.any() and not seeded:
        raise FusionError("S09 has no body evidence from which to cover the silhouette")
    if not missing.any():
        return
    distances = np.stack([ndimage.distance_transform_edt(~mask) for _, mask in seeded])
    owners = np.argmin(distances, axis=0)
    for index, (label, _) in enumerate(seeded):
        fallback = missing & (owners == index)
        if fallback.any():
            geometry = evidence[label].setdefault(
                "geometry", np.zeros(visible.shape, dtype=np.float32)
            )
            normalized = (
                geometry.astype(np.float32) / 255
                if np.issubdtype(geometry.dtype, np.integer)
                else geometry.astype(np.float32)
            )
            normalized[fallback] = np.maximum(normalized[fallback], 0.01)
            evidence[label]["geometry"] = normalized


def _validate_weights(weights: Mapping[str, float]) -> None:
    required = {
        "sam2": 0.40,
        "sapiens": 0.25,
        "geometry": 0.15,
        "schp": 0.10,
        "densepose": 0.10,
    }
    permitted = (required, {**required, "custom_bodypart": 0.45})
    if not any(
        set(weights) == set(profile)
        and all(abs(float(weights[key]) - value) <= 1e-9 for key, value in profile.items())
        for profile in permitted
    ):
        raise FusionError(
            "fusion weights must match the base contract with optional custom_bodypart=0.45"
        )


def _score_labels(evidence, weights, shape, authority, map_name):
    if not evidence:
        raise FusionError(f"no {map_name} evidence")
    names = sorted(evidence, key=lambda name: int(authority.label(name).id))
    scores = []
    for name in names:
        label = authority.label(name, require_enabled=True)
        if label.map != map_name or label.id == 0:
            raise FusionError(f"{name} is not a non-background {map_name} label")
        sources = evidence[name]
        unknown = set(sources) - set(weights)
        if unknown or not sources:
            raise FusionError(f"invalid evidence sources for {name}: {sorted(unknown)}")
        denominator = sum(float(weights[source]) for source in sources)
        score = np.zeros(shape, dtype=np.float32)
        for source, raw in sources.items():
            value = np.asarray(raw)
            if value.shape != shape or not np.isfinite(value).all():
                raise FusionError(f"evidence {name}/{source} shape or values invalid")
            normalized = value.astype(np.float32)
            if np.issubdtype(value.dtype, np.integer):
                if value.min() < 0 or value.max() > 255:
                    raise FusionError(f"integer evidence {name}/{source} outside 0..255")
                normalized /= 255
            elif normalized.min() < 0 or normalized.max() > 1:
                raise FusionError(f"float evidence {name}/{source} outside 0..1")
            score += normalized * float(weights[source]) / denominator
        scores.append(score)
    return names, np.stack(scores)


def _contested(stack: np.ndarray, threshold: float) -> np.ndarray:
    return np.count_nonzero(stack > threshold, axis=0) >= 2


def _apply_zorder(stack, names, contested, decisions, authority):
    indexed = {name: index for index, name in enumerate(names)}
    records = []
    # Hair always owns overlap over face/neck/shoulders per configured unconditional rule.
    automatic = tuple(
        ZOrderDecision("hair", loser, "hair_front_overlap")
        for loser in ("head_face", "neck", "left_shoulder", "right_shoulder")
        if "hair" in indexed and loser in indexed
    )
    for decision in (*automatic, *decisions):
        if decision.winner not in indexed or decision.loser not in indexed:
            raise FusionError(f"z-order label missing from evidence: {decision}")
        winner, loser = indexed[decision.winner], indexed[decision.loser]
        pixels = contested & (stack[winner] > 0.4) & (stack[loser] > 0.4)
        count = int(pixels.sum())
        if count:
            stack[winner, pixels] = np.maximum(stack[winner, pixels], 1.0001)
            records.append(OcclusionRecord(decision.winner, decision.loser, decision.reason, count))
    return records


def _consensus_summary(names, stack, part_map, authority, quick, normal):
    scores, routes = {}, {}
    for index, name in enumerate(names):
        owned = part_map == int(authority.label(name).id)
        if not owned.any():
            continue
        score = float(stack[index, owned].mean())
        scores[name] = score
        routes[name] = (
            "quick_pass"
            if score >= quick
            else "normal"
            if score >= normal
            else "model_disagreement_high"
        )
    return scores, routes


def _boundary_band(mask: np.ndarray, radius: int) -> np.ndarray:
    if not mask.any():
        return mask.copy()
    return ndimage.binary_dilation(mask, iterations=radius) & ~ndimage.binary_erosion(
        mask, iterations=radius
    )
