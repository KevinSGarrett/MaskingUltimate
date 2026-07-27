"""Governed runtime for Civitai auxiliary detector proposal sources.

The external checkpoints in this lane are never gold or semantic authority.  Raw
outputs are preserved, segmentation masks are normalized through ``png_strict``,
and only explicitly configured ``assist``/``vote`` records can affect downstream
prompts or material seeds.  A future ``vote`` promotion additionally requires a
gold-backed certificate; this module deliberately does not mint certificates.
"""

from __future__ import annotations

import gc
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml
from PIL import Image, ImageDraw
from scipy import ndimage

from ..io.png_strict import write_binary_mask, write_grayscale
from ..lanes.feet import FOOT_INDICES, FootLaneError, split_foot_base_toes
from ..ontology import get_ontology

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = ROOT / "configs" / "civitai_auxiliary_detectors.yaml"
DEFAULT_RUNTIME = ROOT / "configs" / "civitai_auxiliary_runtime.yaml"
VALID_MODES = frozenset({"disabled", "shadow", "assist", "vote"})
VALID_KINDS = frozenset(
    {
        "support",
        "part_candidate",
        "material_candidate",
        "protected",
        "region",
        "box_prompt",
        "protected_box",
        "qa_only",
    }
)
FOOT_LANDMARK_INDICES = {
    "left": {"big_toe": 17, "small_toe": 18, "heel": 19},
    "right": {"big_toe": 20, "small_toe": 21, "heel": 22},
}


class AuxiliaryProviderError(ValueError):
    """Auxiliary registry, output, or authority contract is invalid."""


@dataclass(frozen=True)
class AuxiliaryDetector:
    key: str
    payload_path: Path
    payload_sha256: str
    mode: str
    priority: int
    expected_task: str
    expected_classes: tuple[str, ...]
    outputs: Mapping[str, Mapping[str, str]]
    roi_priors: tuple[str, ...] = ()
    roi_crop_labels: tuple[str, ...] = ()
    roi_scale: float = 1.0
    requires_any_prior: tuple[str, ...] = ()
    requires_any_crop: tuple[str, ...] = ()
    requires_any_pose_tag: tuple[str, ...] = ()
    allowed_views: tuple[str, ...] = ()
    allowed_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuxiliaryRunResult:
    summary_path: Path
    selected_keys: tuple[str, ...]
    successful_keys: tuple[str, ...]
    failed_keys: tuple[str, ...]
    detection_count: int
    normalized_paths: tuple[Path, ...]


@dataclass(frozen=True)
class AuxiliaryS11Evidence:
    """Validated specialist evidence consumed by the non-authoritative S11 committee."""

    part_candidates: Mapping[str, np.ndarray]
    part_candidate_paths: Mapping[str, Path]
    support_candidates: Mapping[str, np.ndarray]
    protected_union: np.ndarray
    label_metadata: Mapping[str, tuple[Mapping[str, Any], ...]]
    support_metadata: Mapping[str, tuple[Mapping[str, Any], ...]]
    summary_path: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, yaml.YAMLError) as exc:
        raise AuxiliaryProviderError(f"cannot load auxiliary config {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise AuxiliaryProviderError(f"auxiliary config must be a mapping: {path}")
    return document


def _certified_vote_keys(
    policy: Mapping[str, Any], detectors: tuple[AuxiliaryDetector, ...], runtime_sha256: str
) -> frozenset[str]:
    if not bool(policy.get("vote_requires_promotion_certificate", True)):
        raise AuxiliaryProviderError("auxiliary votes must require promotion certificates")
    path = ROOT / str(
        policy.get("promotion_certificate_path", "qa/auxiliary/promotion_certificates.json")
    )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuxiliaryProviderError(
            f"cannot load auxiliary promotion certificates: {exc}"
        ) from exc
    if document.get("schema_version") != "1.0.0" or not isinstance(
        document.get("certificates"), list
    ):
        raise AuxiliaryProviderError("auxiliary promotion certificate schema invalid")
    by_key = {detector.key: detector for detector in detectors}
    certified = set()
    for record in document["certificates"]:
        if not isinstance(record, dict):
            raise AuxiliaryProviderError("auxiliary certificate entries must be mappings")
        key = str(record.get("detector_key", ""))
        detector = by_key.get(key)
        if detector is None:
            raise AuxiliaryProviderError(f"certificate references unknown detector {key!r}")
        if record.get("checkpoint_sha256") != detector.payload_sha256:
            raise AuxiliaryProviderError(f"{key}: certificate checkpoint SHA-256 drift")
        if record.get("runtime_config_sha256") != runtime_sha256:
            raise AuxiliaryProviderError(f"{key}: certificate runtime SHA-256 drift")
        if int(record.get("gold_instance_count", 0)) < int(
            policy.get("minimum_gold_benchmark_instances", 30)
        ):
            raise AuxiliaryProviderError(f"{key}: certificate has too few gold instances")
        if float(record.get("mean_iou_gain", -1.0)) < float(
            policy.get("minimum_mean_iou_gain", 0.01)
        ):
            raise AuxiliaryProviderError(f"{key}: certificate mean-IoU gain is below threshold")
        if float(record.get("boundary_f_gain", -1.0)) < float(
            policy.get("minimum_boundary_f_gain", 0.01)
        ):
            raise AuxiliaryProviderError(f"{key}: certificate boundary-F gain is below threshold")
        if bool(policy.get("require_no_hard_class_regression", True)) and not bool(
            record.get("no_hard_class_regression", False)
        ):
            raise AuxiliaryProviderError(f"{key}: certificate reports a hard-class regression")
        if not str(record.get("gold_dataset_version", "")).strip():
            raise AuxiliaryProviderError(f"{key}: certificate lacks gold dataset identity")
        certified.add(key)
    return frozenset(certified)


def load_auxiliary_detectors(
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    runtime_path: Path = DEFAULT_RUNTIME,
    verify_payload_hashes: bool = True,
) -> tuple[dict[str, Any], tuple[AuxiliaryDetector, ...]]:
    """Load and cross-check the intake registry and explicit runtime policy."""
    registry = _load_yaml(registry_path)
    runtime = _load_yaml(runtime_path)
    if str(runtime.get("schema_version")) != "1.0.0":
        raise AuxiliaryProviderError("unsupported auxiliary runtime schema")
    policy = runtime.get("policy")
    if not isinstance(policy, dict):
        raise AuxiliaryProviderError("auxiliary runtime policy must be a mapping")
    configured = runtime.get("detectors")
    if not isinstance(configured, dict):
        raise AuxiliaryProviderError("auxiliary runtime detectors must be a mapping")
    registered = {str(item["key"]): item for item in registry.get("detectors", [])}
    if set(configured) != set(registered):
        missing = sorted(set(registered) - set(configured))
        unknown = sorted(set(configured) - set(registered))
        raise AuxiliaryProviderError(
            f"runtime/registry detector mismatch; missing={missing}, unknown={unknown}"
        )

    detectors: list[AuxiliaryDetector] = []
    for key, settings in configured.items():
        if not isinstance(settings, dict):
            raise AuxiliaryProviderError(f"runtime detector {key} must be a mapping")
        record = registered[key]
        mode = str(settings.get("mode", policy.get("default_mode", "shadow")))
        if mode not in VALID_MODES:
            raise AuxiliaryProviderError(f"{key}: invalid mode {mode!r}")
        outputs = settings.get("outputs")
        if not isinstance(outputs, dict) or not outputs:
            raise AuxiliaryProviderError(f"{key}: explicit class outputs are required")
        expected_classes = tuple(str(value) for value in settings.get("expected_classes", ()))
        if set(outputs) != set(expected_classes):
            raise AuxiliaryProviderError(f"{key}: outputs must cover expected_classes exactly")
        for class_name, output in outputs.items():
            if not isinstance(output, dict) or output.get("kind") not in VALID_KINDS:
                raise AuxiliaryProviderError(f"{key}/{class_name}: invalid output mapping")
            if not str(output.get("target", "")).strip():
                raise AuxiliaryProviderError(f"{key}/{class_name}: target is required")
        payload = ROOT / str(record["payload_path"])
        if not payload.is_file():
            raise AuxiliaryProviderError(f"{key}: payload missing: {payload}")
        expected_hash = str(record["payload_sha256"])
        if verify_payload_hashes and _sha256(payload) != expected_hash:
            raise AuxiliaryProviderError(f"{key}: payload SHA-256 mismatch")
        detectors.append(
            AuxiliaryDetector(
                key=key,
                payload_path=payload,
                payload_sha256=expected_hash,
                mode=mode,
                priority=int(settings.get("priority", 0)),
                expected_task=str(settings["expected_task"]),
                expected_classes=expected_classes,
                outputs=outputs,
                roi_priors=tuple(str(value) for value in settings.get("roi_priors", ())),
                roi_crop_labels=tuple(str(value) for value in settings.get("roi_crop_labels", ())),
                roi_scale=float(settings.get("roi_scale", 1.0)),
                requires_any_prior=tuple(
                    str(value) for value in settings.get("requires_any_prior", ())
                ),
                requires_any_crop=tuple(
                    str(value) for value in settings.get("requires_any_crop", ())
                ),
                requires_any_pose_tag=tuple(
                    str(value) for value in settings.get("requires_any_pose_tag", ())
                ),
                allowed_views=tuple(str(value) for value in settings.get("allowed_views", ())),
                allowed_domains=tuple(str(value) for value in settings.get("allowed_domains", ())),
            )
        )
    return policy, tuple(sorted(detectors, key=lambda item: (-item.priority, item.key)))


def _prior_exists(priors_dir: Path, label: str) -> bool:
    path = Path(priors_dir) / f"prior_{label}.png"
    return path.is_file() and bool(np.asarray(Image.open(path).convert("L")).any())


def select_auxiliary_detectors(
    detectors: tuple[AuxiliaryDetector, ...],
    *,
    priors_dir: Path,
    view: str,
    pose_tags: tuple[str, ...],
    crop_labels: tuple[str, ...] = (),
    domain: str = "photo",
    maximum: int = 14,
) -> tuple[AuxiliaryDetector, ...]:
    """Select deterministic, context-relevant specialists for one person instance."""
    tags = set(pose_tags)
    crops = set(crop_labels)
    selected = []
    for detector in detectors:
        if detector.mode == "disabled":
            continue
        if detector.allowed_views and view not in detector.allowed_views:
            continue
        if detector.allowed_domains and domain not in detector.allowed_domains:
            continue
        if detector.requires_any_pose_tag and not tags.intersection(detector.requires_any_pose_tag):
            continue
        if detector.requires_any_prior and not any(
            _prior_exists(priors_dir, label) for label in detector.requires_any_prior
        ):
            continue
        if detector.requires_any_crop and not crops.intersection(detector.requires_any_crop):
            continue
        selected.append(detector)
    return tuple(selected[:maximum])


def _roi_for_detector(
    detector: AuxiliaryDetector,
    priors_dir: Path,
    crop_requests: Mapping[str, tuple[int, int, int, int]],
    shape: tuple[int, int],
) -> tuple[int, int, int, int]:
    masks = []
    for label in detector.roi_priors:
        path = Path(priors_dir) / f"prior_{label}.png"
        if path.is_file():
            value = np.asarray(Image.open(path).convert("L")) > 0
            if value.shape == shape and value.any():
                masks.append(value)
    for label in detector.roi_crop_labels:
        box = crop_requests.get(label)
        if box is None:
            continue
        left, top, right, bottom = box
        value = np.zeros(shape, dtype=bool)
        value[max(0, top) : min(shape[0], bottom), max(0, left) : min(shape[1], right)] = True
        if value.any():
            masks.append(value)
    if not masks:
        return (0, 0, shape[1], shape[0])
    union = np.logical_or.reduce(masks)
    ys, xs = np.nonzero(union)
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    width = max(8.0, (x1 - x0) * detector.roi_scale)
    height = max(8.0, (y1 - y0) * detector.roi_scale)
    left = max(0, int(round(cx - width / 2)))
    top = max(0, int(round(cy - height / 2)))
    right = min(shape[1], int(round(cx + width / 2)))
    bottom = min(shape[0], int(round(cy + height / 2)))
    return (left, top, max(left + 1, right), max(top + 1, bottom))


def _resize_mask(mask: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    array = np.asarray(mask) > 0.5
    if array.shape == shape:
        return array
    resized = Image.fromarray(array.astype(np.uint8) * 255, mode="L").resize(
        (shape[1], shape[0]), Image.Resampling.NEAREST
    )
    return np.asarray(resized) > 0


def _resolve_support_union(
    target: str,
    mask: np.ndarray,
    crop_requests: Mapping[str, tuple[int, int, int, int]],
) -> str | None:
    crop_names = {
        "hands": ("left_hand", "right_hand"),
        "feet": ("left_foot", "right_foot"),
    }.get(target)
    if crop_names is None:
        return None
    overlaps = []
    for name in crop_names:
        box = crop_requests.get(name)
        if box is None:
            overlaps.append((0, name))
            continue
        left, top, right, bottom = box
        overlap = int(
            np.asarray(mask)[
                max(0, top) : min(mask.shape[0], bottom),
                max(0, left) : min(mask.shape[1], right),
            ].sum()
        )
        overlaps.append((overlap, name))
    overlap, winner = max(overlaps)
    if overlap <= 0:
        return None
    return winner


def derive_foot_atomic_candidates(
    foot_support: np.ndarray,
    *,
    side: str,
    pose_document: Mapping[str, Any],
    confidence_min: float = 0.3,
) -> dict[str, np.ndarray]:
    """Split union-level foot support into ontology-valid MTP atomic proposals.

    A specialist's ``foot`` class describes the whole visible foot and is therefore
    not itself a valid ``foot_base`` candidate. Atomic proposals are emitted only
    when the side's heel, big-toe, and small-toe semantic keypoints are all usable.
    """
    support = np.asarray(foot_support).astype(bool)
    if support.ndim != 2 or not support.any() or side not in FOOT_INDICES:
        return {}
    keypoints = {
        int(item["index"]): item
        for item in pose_document.get("keypoints", ())
        if isinstance(item, dict) and "index" in item
    }
    indices = FOOT_LANDMARK_INDICES[side]
    points = [keypoints.get(indices[name]) for name in ("heel", "big_toe", "small_toe")]
    if any(
        point is None
        or float(point.get("confidence", 0.0)) < confidence_min
        or not np.isfinite([float(point.get("x", np.nan)), float(point.get("y", np.nan))]).all()
        for point in points
    ):
        return {}
    heel, big_toe, small_toe = points
    try:
        split = split_foot_base_toes(
            support,
            heel_xy=(float(heel["x"]), float(heel["y"])),
            big_toe_xy=(float(big_toe["x"]), float(big_toe["y"])),
            small_toe_xy=(float(small_toe["x"]), float(small_toe["y"])),
        )
    except FootLaneError:
        return {}
    if not split.foot_base.any() or not split.toes.any():
        return {}
    return {
        f"{side}_foot_base": split.foot_base,
        f"{side}_toes": split.toes,
    }


def run_auxiliary_providers(
    *,
    image_path: Path,
    priors_dir: Path,
    pose_path: Path,
    output_dir: Path,
    registry_path: Path = DEFAULT_REGISTRY,
    runtime_path: Path = DEFAULT_RUNTIME,
    domain: str = "photo",
) -> AuxiliaryRunResult:
    """Run selected checkpoints sequentially and write proposal-only evidence."""
    policy, detectors = load_auxiliary_detectors(
        registry_path=registry_path, runtime_path=runtime_path
    )
    runtime_sha256 = _sha256(runtime_path)
    certified_vote_keys = _certified_vote_keys(policy, detectors, runtime_sha256)
    pose = json.loads(Path(pose_path).read_text(encoding="utf-8"))
    prompt_document = json.loads((Path(priors_dir) / "prompts.json").read_text(encoding="utf-8"))
    crop_requests = {
        str(item["label"]): tuple(int(round(value)) for value in item["bbox_xyxy"])
        for item in prompt_document.get("crop_requests", ())
    }
    selected = select_auxiliary_detectors(
        detectors,
        priors_dir=priors_dir,
        view=str(pose.get("view", "front")),
        pose_tags=tuple(str(value) for value in pose.get("pose_tags", ())),
        crop_labels=tuple(crop_requests),
        domain=domain,
        maximum=int(policy.get("max_models_per_instance", 14)),
    )
    source = np.asarray(Image.open(image_path).convert("RGB"))
    source_hash = _sha256(image_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized: dict[tuple[str, str], np.ndarray] = {}
    records: list[dict[str, Any]] = []
    successful: list[str] = []
    failed: list[str] = []
    detection_count = 0

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise AuxiliaryProviderError("ultralytics is required for auxiliary inference") from exc

    for detector in selected:
        roi = _roi_for_detector(detector, priors_dir, crop_requests, source.shape[:2])
        left, top, right, bottom = roi
        crop = source[top:bottom, left:right]
        detector_record: dict[str, Any] = {
            "key": detector.key,
            "requested_mode": detector.mode,
            "effective_mode": (
                detector.mode
                if detector.mode != "vote" or detector.key in certified_vote_keys
                else "shadow"
            ),
            "checkpoint_sha256": detector.payload_sha256,
            "roi_xyxy": list(roi),
            "detections": [],
        }
        model = None
        try:
            model = YOLO(str(detector.payload_path), verbose=False)
            names = tuple(str(value) for _, value in sorted(model.names.items()))
            if str(model.task) != detector.expected_task or names != detector.expected_classes:
                raise AuxiliaryProviderError(
                    f"embedded task/classes drifted: task={model.task}, classes={names}"
                )
            results = model.predict(
                source=crop,
                device=str(policy.get("device", "cpu")),
                imgsz=int(policy.get("image_size", 640)),
                conf=float(policy.get("confidence", 0.25)),
                iou=float(policy.get("iou", 0.45)),
                max_det=int(policy.get("max_detections", 32)),
                retina_masks=True,
                verbose=False,
            )
            if len(results) != 1:
                raise AuxiliaryProviderError("provider must return exactly one image result")
            result = results[0]
            boxes = result.boxes
            mask_data = None if result.masks is None else result.masks.data.cpu().numpy()
            count = 0 if boxes is None else len(boxes)
            for index in range(count):
                class_id = int(boxes.cls[index].item())
                class_name = str(model.names[class_id])
                confidence = float(boxes.conf[index].item())
                local_box = [float(value) for value in boxes.xyxy[index].cpu().tolist()]
                full_box = [
                    local_box[0] + left,
                    local_box[1] + top,
                    local_box[2] + left,
                    local_box[3] + top,
                ]
                mapping = detector.outputs[class_name]
                item: dict[str, Any] = {
                    "class_id": class_id,
                    "class_name": class_name,
                    "confidence": confidence,
                    "bbox_xyxy": full_box,
                    "kind": mapping["kind"],
                    "target": mapping["target"],
                }
                if mask_data is not None:
                    local_mask = _resize_mask(mask_data[index], crop.shape[:2])
                    full_mask = np.zeros(source.shape[:2], dtype=bool)
                    full_mask[top:bottom, left:right] = local_mask
                    raw_path = output_dir / "raw" / detector.key / f"detection_{index:03d}.png"
                    write_binary_mask(
                        raw_path,
                        full_mask,
                        source_size=(source.shape[1], source.shape[0]),
                    )
                    item["mask_path"] = raw_path.relative_to(output_dir).as_posix()
                    effective_mode = str(detector_record["effective_mode"])
                    if effective_mode in {"assist", "vote"}:
                        key = (str(mapping["kind"]), str(mapping["target"]))
                        normalized[key] = (
                            normalized.get(key, np.zeros(source.shape[:2], dtype=bool)) | full_mask
                        )
                        if mapping["kind"] == "support":
                            resolved = _resolve_support_union(
                                str(mapping["target"]), full_mask, crop_requests
                            )
                            if resolved is not None:
                                item["resolved_union_target"] = resolved
                                if mapping["target"] == "feet":
                                    side = resolved.split("_", 1)[0]
                                    derived = derive_foot_atomic_candidates(
                                        full_mask, side=side, pose_document=pose
                                    )
                                    for label, atomic_mask in derived.items():
                                        part_key = ("part_candidate", label)
                                        normalized[part_key] = normalized.get(
                                            part_key, np.zeros(source.shape[:2], dtype=bool)
                                        ) | np.asarray(atomic_mask).astype(bool)
                                    if derived:
                                        item["derived_part_targets"] = sorted(derived)
                                        item["derivation"] = {
                                            "method": "pose_backed_foot_mtp_split",
                                            "source_authority": "union_support_only",
                                        }
                        if effective_mode == "vote" and mapping["kind"] == "part_candidate":
                            vote_key = ("vote_part_candidate", str(mapping["target"]))
                            normalized[vote_key] = (
                                normalized.get(vote_key, np.zeros(source.shape[:2], dtype=bool))
                                | full_mask
                            )
                detector_record["detections"].append(item)
                detection_count += 1
            successful.append(detector.key)
        except Exception as exc:  # noqa: BLE001 - optional provider failure is evidence
            detector_record["error"] = f"{type(exc).__name__}: {exc}"
            failed.append(detector.key)
            if bool(policy.get("fail_pipeline_on_provider_error", False)):
                raise AuxiliaryProviderError(
                    f"auxiliary provider {detector.key} failed: {exc}"
                ) from exc
        finally:
            if model is not None:
                del model
            gc.collect()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
        records.append(detector_record)

    normalized_paths = []
    for (kind, target), mask in sorted(normalized.items()):
        path = output_dir / "normalized" / kind / f"{target}.png"
        normalized_paths.append(
            write_binary_mask(path, mask, source_size=(source.shape[1], source.shape[0]))
        )
    summary = {
        "schema_version": "1.0.0",
        "authority": "proposal_only",
        "may_write_final_maps": False,
        "allowed_consumers": ["sam2_prompting", "material_seeding", "qa", "certified_fusion"],
        "source_image_sha256": source_hash,
        "source_size": [source.shape[1], source.shape[0]],
        "runtime_config_sha256": runtime_sha256,
        "registry_sha256": _sha256(registry_path),
        "selected_keys": [item.key for item in selected],
        "successful_keys": successful,
        "failed_keys": failed,
        "detectors": records,
        "normalized": [path.relative_to(output_dir).as_posix() for path in normalized_paths],
    }
    summary_path = output_dir / "auxiliary_predictions.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return AuxiliaryRunResult(
        summary_path=summary_path,
        selected_keys=tuple(item.key for item in selected),
        successful_keys=tuple(successful),
        failed_keys=tuple(failed),
        detection_count=detection_count,
        normalized_paths=tuple(normalized_paths),
    )


def render_auxiliary_review_overlay(
    *, image_path: Path, auxiliary_dir: Path, output_path: Path
) -> Path:
    """Render proposal evidence for human review without creating mask authority."""
    auxiliary_dir = Path(auxiliary_dir)
    document = json.loads(
        (auxiliary_dir / "auxiliary_predictions.json").read_text(encoding="utf-8")
    )
    image = Image.open(image_path).convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    palette = ((0, 220, 255), (255, 180, 0), (255, 70, 150), (80, 255, 120))
    for detector_index, detector in enumerate(document.get("detectors", ())):
        color = palette[detector_index % len(palette)]
        for detection in detector.get("detections", ()):
            mask_name = detection.get("mask_path")
            if mask_name:
                mask = Image.open(auxiliary_dir / str(mask_name)).convert("L")
                tint = Image.new("RGBA", image.size, (*color, 72))
                overlay.alpha_composite(Image.composite(tint, Image.new("RGBA", image.size), mask))
            box = detection.get("bbox_xyxy")
            if isinstance(box, list) and len(box) == 4:
                draw.rectangle(
                    tuple(round(float(value)) for value in box), outline=(*color, 255), width=2
                )
                label = (
                    f"{detector.get('key', 'provider')}:{detection.get('class_name', '?')} "
                    f"{float(detection.get('confidence', 0.0)):.2f}"
                )
                draw.text(
                    (round(float(box[0])) + 2, round(float(box[1])) + 2), label, fill=(*color, 255)
                )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.alpha_composite(image, overlay).convert("RGB").save(output_path, format="PNG")
    return output_path


def _mask_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(np.asarray(mask))
    if not len(xs):
        return None
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def build_assisted_s05(*, priors_dir: Path, auxiliary_dir: Path, output_dir: Path) -> Path:
    """Create S05-compatible priors/prompts augmented by bounded specialist support."""
    priors_dir = Path(priors_dir)
    auxiliary_dir = Path(auxiliary_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in priors_dir.glob("prior_*.png"):
        shutil.copy2(path, output_dir / path.name)
    prompts = json.loads((priors_dir / "prompts.json").read_text(encoding="utf-8"))
    group_targets = {
        "hands": (
            "left_hand_base",
            "left_thumb",
            "left_index_finger",
            "left_middle_finger",
            "left_ring_finger",
            "left_pinky",
            "right_hand_base",
            "right_thumb",
            "right_index_finger",
            "right_middle_finger",
            "right_ring_finger",
            "right_pinky",
        ),
        "feet": ("left_foot_base", "left_toes", "right_foot_base", "right_toes"),
    }
    assists: list[dict[str, Any]] = []

    candidates: list[tuple[np.ndarray, tuple[str, ...], str]] = []
    support_root = auxiliary_dir / "normalized" / "support"
    for group, labels in group_targets.items():
        path = support_root / f"{group}.png"
        if path.is_file():
            candidates.append((np.asarray(Image.open(path).convert("L")) > 0, labels, group))
    part_candidate_root = auxiliary_dir / "normalized" / "part_candidate"
    if part_candidate_root.is_dir():
        for path in sorted(part_candidate_root.glob("*.png")):
            candidates.append(
                (
                    np.asarray(Image.open(path).convert("L")) > 0,
                    (path.stem,),
                    f"part_candidate:{path.stem}",
                )
            )

    plans_by_label = {str(item["label"]): item for item in prompts.get("plans", [])}
    for candidate, labels, source in candidates:
        for label in labels:
            prior_path = output_dir / f"prior_{label}.png"
            if prior_path.is_file():
                prior = np.asarray(Image.open(prior_path).convert("L"))
                if prior.shape != candidate.shape:
                    raise AuxiliaryProviderError(f"assisted prior geometry differs for {label}")
            else:
                prior = np.zeros(candidate.shape, dtype=np.uint8)
            if source.startswith("part_candidate:"):
                bounded = candidate
            elif not prior.any():
                continue
            else:
                radius = max(3, round(0.02 * max(prior.shape)))
                bounded = candidate & ndimage.binary_dilation(prior > 0, iterations=radius)
            if not bounded.any():
                continue
            augmented = np.maximum(prior, bounded.astype(np.uint8) * 255)
            write_grayscale(
                prior_path, augmented.astype(np.uint8), source_size=(prior.shape[1], prior.shape[0])
            )
            plan = plans_by_label.get(label)
            bbox = _mask_bbox(augmented > 0)
            if bbox is not None:
                ys, xs = np.nonzero(bounded)
                positive = [int(round(float(xs.mean()))), int(round(float(ys.mean())))]
                if plan is None:
                    x0, y0, x1, y1 = bbox
                    plan = {
                        "label": label,
                        "box_xyxy": list(bbox),
                        "positive_points": [positive],
                        "negative_points": [
                            [max(0, x0 - 2), max(0, y0 - 2)],
                            [min(prior.shape[1] - 1, x1 + 1), max(0, y0 - 2)],
                            [max(0, x0 - 2), min(prior.shape[0] - 1, y1 + 1)],
                            [
                                min(prior.shape[1] - 1, x1 + 1),
                                min(prior.shape[0] - 1, y1 + 1),
                            ],
                        ],
                        "prior_quality": "low",
                        "multimask_output": True,
                    }
                    prompts.setdefault("plans", []).append(plan)
                    plans_by_label[label] = plan
                else:
                    plan["box_xyxy"] = list(bbox)
                    points = [list(point) for point in plan.get("positive_points", [])]
                    if positive not in points:
                        points.append(positive)
                    plan["positive_points"] = points
            assists.append(
                {"source": source, "label": label, "added_pixel_count": int(bounded.sum())}
            )
    prompts["auxiliary_assists"] = assists
    prompts["auxiliary_authority"] = "proposal_only"
    path = output_dir / "prompts.json"
    path.write_text(json.dumps(prompts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_material_assists(auxiliary_dir: Path, shape: tuple[int, int]) -> dict[str, np.ndarray]:
    """Load explicitly mapped material seeds; unknown names and geometry fail closed."""
    root = Path(auxiliary_dir) / "normalized" / "material_candidate"
    if not root.is_dir():
        return {}
    output = {}
    for path in sorted(root.glob("*.png")):
        mask = np.asarray(Image.open(path).convert("L")) > 0
        if mask.shape != shape:
            raise AuxiliaryProviderError(f"material assist geometry differs: {path}")
        output[path.stem] = mask
    return output


def load_auxiliary_s11_evidence(
    auxiliary_dir: Path, shape: tuple[int, int]
) -> AuxiliaryS11Evidence | None:
    """Load strict proposal masks and provenance for S11 without granting authority."""
    auxiliary_dir = Path(auxiliary_dir)
    summary_path = auxiliary_dir / "auxiliary_predictions.json"
    if not summary_path.is_file():
        return None
    document = json.loads(summary_path.read_text(encoding="utf-8"))
    if (
        document.get("authority") != "proposal_only"
        or document.get("may_write_final_maps") is not False
    ):
        raise AuxiliaryProviderError("S11 auxiliary evidence has invalid authority")
    if document.get("source_size") != [shape[1], shape[0]]:
        raise AuxiliaryProviderError("S11 auxiliary evidence geometry differs from part map")
    declared = {str(value) for value in document.get("normalized", ())}
    part_candidates: dict[str, np.ndarray] = {}
    part_paths: dict[str, Path] = {}
    authority = get_ontology()
    root = auxiliary_dir.resolve()
    for relative in sorted(declared):
        path = (auxiliary_dir / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise AuxiliaryProviderError("S11 auxiliary path escapes its evidence root") from exc
        if not path.is_file():
            raise AuxiliaryProviderError(f"S11 declared auxiliary mask is missing: {relative}")
        with Image.open(path) as opened:
            value = np.asarray(opened)
            if (
                opened.mode != "L"
                or value.shape != shape
                or set(np.unique(value).tolist()) - {0, 255}
            ):
                raise AuxiliaryProviderError(f"S11 auxiliary mask is not strict binary: {relative}")
        parts = Path(relative).parts
        if len(parts) == 3 and parts[:2] == ("normalized", "part_candidate"):
            label = Path(parts[2]).stem
            definition = authority.label(label, require_enabled=True)
            if definition.map != "part" or definition.id in {None, 0}:
                raise AuxiliaryProviderError(
                    f"S11 auxiliary candidate is not an indexed part: {label}"
                )
            part_candidates[label] = value > 0
            part_paths[label] = path
    protected = np.zeros(shape, dtype=bool)
    protected_root = auxiliary_dir / "normalized" / "protected"
    if protected_root.is_dir():
        for path in sorted(protected_root.glob("*.png")):
            relative = path.relative_to(auxiliary_dir).as_posix()
            if relative not in declared:
                raise AuxiliaryProviderError(f"S11 protected mask is undeclared: {relative}")
            with Image.open(path) as opened:
                value = np.asarray(opened)
                if (
                    opened.mode != "L"
                    or value.shape != shape
                    or set(np.unique(value).tolist()) - {0, 255}
                ):
                    raise AuxiliaryProviderError(f"S11 protected mask is invalid: {relative}")
            protected |= value > 0
    metadata: dict[str, list[Mapping[str, Any]]] = {label: [] for label in part_candidates}
    support_candidates: dict[str, np.ndarray] = {}
    support_metadata: dict[str, list[Mapping[str, Any]]] = {}
    union_labels = {
        f"{side}_hand": tuple(
            f"{side}_{suffix}"
            for suffix in (
                "hand_base",
                "thumb",
                "index_finger",
                "middle_finger",
                "ring_finger",
                "pinky",
            )
        )
        for side in ("left", "right")
    } | {f"{side}_foot": (f"{side}_foot_base", f"{side}_toes") for side in ("left", "right")}
    for detector in document.get("detectors", ()):
        for detection in detector.get("detections", ()):
            if detection.get("kind") == "support" and detection.get("resolved_part_target"):
                raise AuxiliaryProviderError(
                    "legacy union support was relabeled as an atomic part candidate"
                )
            labels = list(detection.get("derived_part_targets", ()))
            if labels and detection.get("derivation", {}).get("method") != (
                "pose_backed_foot_mtp_split"
            ):
                raise AuxiliaryProviderError(
                    "derived auxiliary part candidates lack a recognized atomic split"
                )
            resolved_union = detection.get("resolved_union_target")
            support_labels = union_labels.get(str(resolved_union), ())
            if detection.get("kind") == "support" and support_labels:
                relative = detection.get("mask_path")
                if not isinstance(relative, str):
                    raise AuxiliaryProviderError("union support detection lacks its raw mask")
                support_path = (auxiliary_dir / relative).resolve()
                try:
                    support_path.relative_to(root)
                except ValueError as exc:
                    raise AuxiliaryProviderError("S11 support path escapes evidence root") from exc
                if not support_path.is_file():
                    raise AuxiliaryProviderError("S11 support mask is missing")
                with Image.open(support_path) as opened:
                    support_value = np.asarray(opened)
                    if (
                        opened.mode != "L"
                        or support_value.shape != shape
                        or set(np.unique(support_value).tolist()) - {0, 255}
                    ):
                        raise AuxiliaryProviderError("S11 union support mask is invalid")
                for support_label in support_labels:
                    support_candidates[support_label] = support_candidates.get(
                        support_label, np.zeros(shape, dtype=bool)
                    ) | (support_value > 0)
                    support_metadata.setdefault(support_label, []).append(
                        {
                            "detector_key": str(detector.get("key", "unknown")),
                            "checkpoint_sha256": str(detector.get("checkpoint_sha256", "")),
                            "class_name": str(detection.get("class_name", "")),
                            "confidence": float(detection.get("confidence", 0.0)),
                            "bbox_xyxy": list(detection.get("bbox_xyxy", ())),
                            "effective_mode": str(detector.get("effective_mode", "shadow")),
                            "evidence_scope": str(resolved_union),
                            "authority": "parent_union_support_only_not_atomic_candidate",
                        }
                    )
            if detection.get("kind") == "part_candidate":
                labels.append(detection.get("target"))
            for label in dict.fromkeys(labels):
                if label not in metadata:
                    continue
                metadata[str(label)].append(
                    {
                        "detector_key": str(detector.get("key", "unknown")),
                        "checkpoint_sha256": str(detector.get("checkpoint_sha256", "")),
                        "class_name": str(detection.get("class_name", "")),
                        "confidence": float(detection.get("confidence", 0.0)),
                        "bbox_xyxy": list(detection.get("bbox_xyxy", ())),
                        "effective_mode": str(detector.get("effective_mode", "shadow")),
                        "derivation": dict(detection.get("derivation", {})),
                    }
                )
    return AuxiliaryS11Evidence(
        part_candidates=part_candidates,
        part_candidate_paths=part_paths,
        support_candidates=support_candidates,
        protected_union=protected,
        label_metadata={key: tuple(value) for key, value in metadata.items()},
        support_metadata={key: tuple(value) for key, value in support_metadata.items()},
        summary_path=summary_path,
    )
