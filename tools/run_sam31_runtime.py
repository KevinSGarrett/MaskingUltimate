"""Run one governed official SAM 3.1 discovery or refinement request in WSL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

if __package__:
    from tools.sam31_session_compat import start_sam31_session
else:
    from sam31_session_compat import start_sam31_session
from PIL import Image

ARTIFACT_FIELDS = (
    "masks",
    "object_ids",
    "probabilities",
    "boxes_xywh",
    "concept_indices",
)
AUTHORITY = "official_sam31_runtime_draft_candidates_only_no_gold_or_active_map_authority"
_PREDICTOR_CACHE: dict[tuple[str, ...], tuple[Any, float, int, Any]] = {}
_MODEL_LOAD_COUNT = 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _array_sha256(value: np.ndarray) -> str:
    array = np.ascontiguousarray(value)
    digest = hashlib.sha256()
    digest.update(array.dtype.str.encode("ascii"))
    digest.update(json.dumps(list(array.shape), separators=(",", ":")).encode("utf-8"))
    digest.update(array.tobytes())
    return digest.hexdigest()


def _payload_sha256(arrays: Mapping[str, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for name in ARTIFACT_FIELDS:
        value = np.ascontiguousarray(arrays[name])
        digest.update(name.encode("utf-8"))
        digest.update(value.dtype.str.encode("ascii"))
        digest.update(json.dumps(list(value.shape), separators=(",", ":")).encode("utf-8"))
        digest.update(value.tobytes())
    return digest.hexdigest()


def _extract(outputs: Any, *, height: int, width: int) -> dict[str, np.ndarray]:
    if not isinstance(outputs, Mapping):
        raise RuntimeError("official SAM 3.1 output must be a mapping")
    try:
        arrays = {
            "masks": np.asarray(outputs["out_binary_masks"], dtype=bool),
            "object_ids": np.asarray(outputs["out_obj_ids"], dtype=np.int64),
            "probabilities": np.asarray(outputs["out_probs"], dtype=np.float32),
            "boxes_xywh": np.asarray(outputs["out_boxes_xywh"], dtype=np.float32),
        }
    except KeyError as exc:
        raise RuntimeError("official SAM 3.1 output fields are incomplete") from exc
    count = arrays["masks"].shape[0] if arrays["masks"].ndim == 3 else -1
    if (
        arrays["masks"].shape != (count, height, width)
        or arrays["object_ids"].shape != (count,)
        or arrays["probabilities"].shape != (count,)
        or arrays["boxes_xywh"].shape != (count, 4)
        or not np.isfinite(arrays["probabilities"]).all()
        or not np.isfinite(arrays["boxes_xywh"]).all()
    ):
        raise RuntimeError("official SAM 3.1 output geometry is invalid")
    keep = arrays["masks"].any(axis=(1, 2)) if count else np.zeros((0,), dtype=bool)
    return {name: value[keep] for name, value in arrays.items()}


def _box_from_masks(masks: np.ndarray, *, height: int, width: int) -> np.ndarray:
    boxes = np.zeros((masks.shape[0], 4), dtype=np.float32)
    for index, mask in enumerate(masks):
        ys, xs = np.nonzero(mask)
        if not len(xs):
            raise RuntimeError("official SAM 3.1 postprocessed mask is empty")
        x1, x2 = int(xs.min()), int(xs.max()) + 1
        y1, y2 = int(ys.min()), int(ys.max()) + 1
        boxes[index] = (x1 / width, y1 / height, (x2 - x1) / width, (y2 - y1) / height)
    return boxes


def _derived_positive(mask: np.ndarray) -> tuple[int, int]:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise RuntimeError("official SAM 3.1 mask prior is empty")
    center_x = float(xs.mean())
    center_y = float(ys.mean())
    index = int(np.argmin((xs - center_x) ** 2 + (ys - center_y) ** 2))
    return int(xs[index]), int(ys[index])


def _normalize_refinement_box(box: Any, *, width: int, height: int) -> list[float]:
    if (
        not isinstance(box, list)
        or len(box) != 4
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in box)
    ):
        raise RuntimeError("official SAM 3.1 refinement box is invalid")
    x1, y1, x2, y2 = (float(value) for value in box)
    if not all(np.isfinite(value) for value in (x1, y1, x2, y2)) or not (
        0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height
    ):
        raise RuntimeError("official SAM 3.1 refinement box is outside image")
    return [x1 / width, y1 / height, (x2 - x1) / width, (y2 - y1) / height]


def _normalize_visual_exemplars(
    visual_exemplars: Any, *, width: int, height: int
) -> tuple[list[list[float]], list[int]]:
    if not isinstance(visual_exemplars, list):
        raise RuntimeError("official SAM 3.1 visual exemplars must be a list")
    normalized_boxes: list[list[float]] = []
    box_labels: list[int] = []
    identities: list[str] = []
    for exemplar in visual_exemplars:
        if not isinstance(exemplar, Mapping) or set(exemplar) != {
            "bbox_xyxy",
            "polarity",
            "manifest_sha256",
            "manifest_file_sha256",
        }:
            raise RuntimeError("official SAM 3.1 visual exemplar fields are invalid")
        bbox = exemplar["bbox_xyxy"]
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in bbox)
        ):
            raise RuntimeError("official SAM 3.1 visual exemplar bbox is invalid")
        x1, y1, x2, y2 = (float(value) for value in bbox)
        if not all(np.isfinite(value) for value in (x1, y1, x2, y2)) or not (
            0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height
        ):
            raise RuntimeError("official SAM 3.1 visual exemplar bbox is invalid")
        if exemplar["polarity"] not in {"positive", "negative"}:
            raise RuntimeError("official SAM 3.1 visual exemplar polarity is invalid")
        if any(
            not isinstance(exemplar[key], str)
            or len(exemplar[key]) != 64
            or any(character not in "0123456789abcdef" for character in exemplar[key])
            for key in ("manifest_sha256", "manifest_file_sha256")
        ):
            raise RuntimeError("official SAM 3.1 visual exemplar identity is invalid")
        identities.append(exemplar["manifest_sha256"])
        normalized_boxes.append([x1 / width, y1 / height, (x2 - x1) / width, (y2 - y1) / height])
        box_labels.append(1 if exemplar["polarity"] == "positive" else 0)
    if len(identities) != len(set(identities)):
        raise RuntimeError("official SAM 3.1 visual exemplar identities are duplicated")
    return normalized_boxes, box_labels


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--requirements-lock", type=Path, required=True)
    parser.add_argument("--frame-dir", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--prompt-npz", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-source-commit", required=True)
    return parser.parse_args()


def resident_cache_stats() -> dict[str, int]:
    """Return process-local model reuse evidence for the resident wrapper."""

    return {
        "resident_model_count": len(_PREDICTOR_CACHE),
        "model_load_count": _MODEL_LOAD_COUNT,
    }


def execute(args: argparse.Namespace) -> dict[str, Any]:
    """Execute one exact request, reusing a process-local governed predictor."""

    global _MODEL_LOAD_COUNT
    required = (
        args.source_root,
        args.checkpoint,
        args.runtime_lock,
        args.requirements_lock,
        args.frame_dir / "00000.jpg",
        args.request,
        args.prompt_npz,
    )
    if not all(path.exists() for path in required):
        raise FileNotFoundError("one or more governed official SAM 3.1 inputs are missing")
    source_commit = subprocess.check_output(  # noqa: S603 - exact fixed git probe
        ("git", "-C", str(args.source_root), "rev-parse", "HEAD"), text=True, timeout=30
    ).strip()
    source_status = subprocess.check_output(  # noqa: S603 - exact fixed git probe
        (
            "git",
            "-C",
            str(args.source_root),
            "status",
            "--porcelain",
            "--untracked-files=no",
        ),
        text=True,
        timeout=30,
    ).strip()
    if source_commit != args.expected_source_commit or source_status:
        raise RuntimeError("official SAM 3.1 source identity is stale or dirty")
    request = json.loads(args.request.read_text(encoding="utf-8"))
    if set(request) != {
        "schema_version",
        "operation",
        "concepts",
        "prompt",
        "visual_exemplars",
        "image_rgb_sha256",
        "authority",
        "may_author_gold",
    }:
        raise RuntimeError("official SAM 3.1 request fields are not closed")
    if (
        request["schema_version"] != "1.0.0"
        or request["operation"] not in {"discover", "refine"}
        or request["authority"] != AUTHORITY
        or request["may_author_gold"] is not False
    ):
        raise RuntimeError("official SAM 3.1 request identity or authority is invalid")
    with np.load(args.prompt_npz, allow_pickle=False) as archive:
        if set(archive.files) != {"mask_prompt"}:
            raise RuntimeError("official SAM 3.1 prompt artifact fields are not closed")
        mask_prompt = np.asarray(archive["mask_prompt"]).copy()
    if mask_prompt.dtype != np.bool_ or mask_prompt.ndim != 2:
        raise RuntimeError("official SAM 3.1 mask prompt artifact is invalid")
    with Image.open(args.frame_dir / "00000.jpg") as image:
        width, height = image.size

    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(0)
    np.random.seed(0)
    sys.path.insert(0, str(args.source_root))
    import torch
    from sam3.model_builder import build_sam3_predictor

    if not torch.cuda.is_available():
        raise RuntimeError("official SAM 3.1 governed runtime requires CUDA")
    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    cache_key = (
        str(args.source_root.resolve()),
        source_commit,
        _sha256(args.checkpoint),
        _sha256(args.runtime_lock),
        _sha256(args.requirements_lock),
    )
    cached = _PREDICTOR_CACHE.get(cache_key)
    if cached is None:
        load_started = time.perf_counter()
        predictor = build_sam3_predictor(
            checkpoint_path=str(args.checkpoint),
            version="sam3.1",
            compile=False,
            warm_up=False,
            max_num_objects=16,
            multiplex_count=16,
            use_fa3=False,
            use_rope_real=True,
            async_loading_frames=False,
        )
        torch.cuda.synchronize()
        model_load_latency_ms = (time.perf_counter() - load_started) * 1000.0
        model_vram_bytes = int(torch.cuda.memory_allocated())
        _PREDICTOR_CACHE[cache_key] = (
            predictor,
            model_load_latency_ms,
            model_vram_bytes,
            torch,
        )
        _MODEL_LOAD_COUNT += 1
    else:
        predictor, model_load_latency_ms, model_vram_bytes, cached_torch = cached
        if cached_torch is not torch:
            raise RuntimeError("official SAM 3.1 resident torch identity drifted")
    torch.cuda.reset_peak_memory_stats()
    inference_started = time.perf_counter()
    masks: list[np.ndarray] = []
    object_ids: list[np.ndarray] = []
    probabilities: list[np.ndarray] = []
    boxes: list[np.ndarray] = []
    concept_indices: list[np.ndarray] = []
    prompt_translation = "text_prompt_exact"
    session_id = None
    try:
        session_id = start_sam31_session(
            predictor,
            resource_path=str(args.frame_dir),
        )
        if request["operation"] == "discover":
            concepts = request["concepts"]
            visual_exemplars = request["visual_exemplars"]
            if (
                not isinstance(concepts, list)
                or not concepts
                or any(not isinstance(value, str) or not value.strip() for value in concepts)
                or len(concepts) != len(set(concepts))
                or request["prompt"] is not None
                or not isinstance(visual_exemplars, list)
                or mask_prompt.shape != (0, 0)
            ):
                raise RuntimeError("official SAM 3.1 discovery request is invalid")
            normalized_boxes, box_labels = _normalize_visual_exemplars(
                visual_exemplars, width=width, height=height
            )
            if visual_exemplars:
                prompt_translation = "text_plus_same_image_visual_box_exemplars_exact"
            for concept_index, concept in enumerate(concepts):
                if concept_index:
                    predictor.handle_request({"type": "reset_session", "session_id": session_id})
                payload = {
                    "type": "add_prompt",
                    "session_id": session_id,
                    "frame_index": 0,
                    "text": concept,
                }
                if visual_exemplars:
                    payload["bounding_boxes"] = normalized_boxes
                    payload["bounding_box_labels"] = box_labels
                response = predictor.handle_request(payload)
                current = _extract(response["outputs"], height=height, width=width)
                count = current["masks"].shape[0]
                masks.append(current["masks"])
                object_ids.append(current["object_ids"])
                probabilities.append(current["probabilities"])
                boxes.append(current["boxes_xywh"])
                concept_indices.append(np.full((count,), concept_index, dtype=np.int64))
        else:
            if request["visual_exemplars"] != []:
                raise RuntimeError("official SAM 3.1 refinement cannot carry visual exemplars")
            prompt = request["prompt"]
            if not isinstance(prompt, Mapping) or set(prompt) != {
                "positive_points",
                "negative_points",
                "box_xyxy",
                "mask_prompt_sha256",
            }:
                raise RuntimeError("official SAM 3.1 refinement prompt is invalid")
            positives = [tuple(int(axis) for axis in point) for point in prompt["positive_points"]]
            negatives = [tuple(int(axis) for axis in point) for point in prompt["negative_points"]]
            box = prompt["box_xyxy"]
            if mask_prompt.shape != (0, 0):
                if mask_prompt.shape != (height, width):
                    raise RuntimeError("official SAM 3.1 mask prior geometry is invalid")
                if (
                    prompt["mask_prompt_sha256"]
                    != hashlib.sha256(np.ascontiguousarray(mask_prompt).tobytes()).hexdigest()
                ):
                    raise RuntimeError("official SAM 3.1 mask prior identity is stale")
            elif prompt["mask_prompt_sha256"] is not None:
                raise RuntimeError("official SAM 3.1 mask prior artifact is missing")
            for point in (*positives, *negatives):
                if not (0 <= point[0] < width and 0 <= point[1] < height):
                    raise RuntimeError("official SAM 3.1 refinement point is outside image")
            if negatives:
                raise RuntimeError(
                    "official SAM 3.1 multiplex refinement does not support negative points"
                )
            if box is None and mask_prompt.shape != (0, 0):
                ys, xs = np.nonzero(mask_prompt)
                box = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
                prompt_translation = "mask_prior_to_native_visual_box_prompt_exact"
            elif box is not None:
                prompt_translation = (
                    "native_visual_box_prompt_exact_visual_text_center_point_postcondition_only"
                )
            else:
                raise RuntimeError(
                    "official SAM 3.1 multiplex refinement requires a native box prompt"
                )
            normalized_box = _normalize_refinement_box(box, width=width, height=height)
            x1, y1, x2, y2 = (float(value) for value in box)
            if any(not (x1 <= x < x2 and y1 <= y < y2) for x, y in positives):
                raise RuntimeError("official SAM 3.1 positive point is outside refinement box")
            response = predictor.handle_request(
                {
                    "type": "add_prompt",
                    "session_id": session_id,
                    "frame_index": 0,
                    "text": "visual",
                    "bounding_boxes": [normalized_box],
                    "bounding_box_labels": [1],
                }
            )
            current = _extract(response["outputs"], height=height, width=width)
            if current["masks"].shape[0] < 1:
                raise RuntimeError("official SAM 3.1 native box refinement returned no result")
            if box is not None:
                x1, y1, x2, y2 = (
                    int(np.floor(float(box[0]))),
                    int(np.floor(float(box[1]))),
                    int(np.ceil(float(box[2]))),
                    int(np.ceil(float(box[3]))),
                )
                if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                    raise RuntimeError("official SAM 3.1 refinement ROI is outside image")
                allowed = np.zeros((height, width), dtype=bool)
                allowed[y1:y2, x1:x2] = True
                current["masks"] &= allowed[None, :, :]
                if not current["masks"].any():
                    raise RuntimeError("official SAM 3.1 ROI clip removed the refinement")
                current["boxes_xywh"] = _box_from_masks(
                    current["masks"], height=height, width=width
                )
            masks.append(current["masks"])
            object_ids.append(current["object_ids"])
            probabilities.append(current["probabilities"])
            boxes.append(current["boxes_xywh"])
            concept_indices.append(np.full((current["masks"].shape[0],), -1, dtype=np.int64))
    finally:
        if session_id is not None:
            predictor.handle_request({"type": "close_session", "session_id": session_id})
    torch.cuda.synchronize()
    inference_latency_ms = (time.perf_counter() - inference_started) * 1000.0
    peak_inference_vram_bytes = int(torch.cuda.max_memory_allocated())
    arrays = {
        "masks": np.concatenate(masks, axis=0),
        "object_ids": np.concatenate(object_ids, axis=0),
        "probabilities": np.concatenate(probabilities, axis=0),
        "boxes_xywh": np.concatenate(boxes, axis=0),
        "concept_indices": np.concatenate(concept_indices, axis=0),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output, **arrays)
    report = {
        "schema_version": "1.0.0",
        "provider": "sam3_1",
        "operation": request["operation"],
        "source_commit": source_commit,
        "source_tree_clean": True,
        "runtime_lock_sha256": _sha256(args.runtime_lock),
        "requirements_lock_sha256": _sha256(args.requirements_lock),
        "checkpoint_sha256": _sha256(args.checkpoint),
        "request_sha256": _sha256(args.request),
        "image_rgb_sha256": request["image_rgb_sha256"],
        "encoded_frame_sha256": _sha256(args.frame_dir / "00000.jpg"),
        "prompt_npz_sha256": _sha256(args.prompt_npz),
        "builder": "build_sam3_predictor",
        "version": "sam3.1",
        "result_count": int(arrays["masks"].shape[0]),
        "artifact_shapes": {name: list(value.shape) for name, value in arrays.items()},
        "payload_sha256": _payload_sha256(arrays),
        "output_npz_sha256": _sha256(args.output),
        "model_load_latency_ms": model_load_latency_ms,
        "inference_latency_ms": inference_latency_ms,
        "model_vram_bytes": model_vram_bytes,
        "peak_inference_vram_bytes": peak_inference_vram_bytes,
        "prompt_translation": prompt_translation,
        "authority": AUTHORITY,
        "may_author_gold": False,
    }
    return report


def main() -> int:
    report = execute(_args())
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
