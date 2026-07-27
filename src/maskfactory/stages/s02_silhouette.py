"""S02 BiRefNet confidence post-processing and full-canvas silhouette placement."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import ndimage

from ..io.png_strict import write_binary_mask, write_grayscale


class SilhouetteError(ValueError):
    """Silhouette confidence or placement violates the S02 contract."""


@dataclass(frozen=True)
class S02Result:
    silhouette_path: Path
    confidence_path: Path
    area_px: int
    bbox_area_px: int
    silhouette_bbox_ratio: float
    qc_passed: bool


def infer_birefnet_confidence(
    image_path: Path,
    *,
    checkpoint: Path,
    output_path: Path,
    wsl_distribution: str = "Ubuntu-22.04",
    python_path: str = "/home/kevin/miniforge3/envs/maskfactory/bin/python",
    timeout_sec: int = 900,
    tile_size: int = 2048,
    tile_overlap: int = 128,
    local_cuda_python: Path | None = None,
    hf_home: Path | None = None,
) -> np.ndarray:
    """Run pinned BiRefNet in an explicit CUDA runtime and validate its confidence."""
    if not Path(image_path).is_file():
        raise SilhouetteError(f"BiRefNet input image does not exist: {image_path}")
    if not Path(checkpoint).is_file():
        raise SilhouetteError(f"BiRefNet checkpoint does not exist: {checkpoint}")
    if tile_size <= 0 or tile_overlap < 0 or tile_overlap >= tile_size:
        raise SilhouetteError("BiRefNet tile contract requires 0 <= overlap < tile size")
    root = Path(__file__).resolve().parents[3]
    local_python = Path(local_cuda_python) if local_cuda_python is not None else None
    if local_python is not None:
        if not local_python.is_file():
            raise SilhouetteError(f"configured local CUDA Python does not exist: {local_python}")
        command = [
            str(local_python),
            str(root / "tools" / "run_birefnet_wsl.py"),
            "--checkpoint",
            str(Path(checkpoint).resolve()),
            "--image",
            str(Path(image_path).resolve()),
            "--output",
            str(Path(output_path).resolve()),
            "--tile-size",
            str(tile_size),
            "--tile-overlap",
            str(tile_overlap),
        ]
        launcher = "local_cuda"
        environment = os.environ.copy()
        if hf_home is not None:
            cache = str(Path(hf_home).resolve())
            environment["HF_HOME"] = cache
            environment["HF_HUB_CACHE"] = str(Path(cache) / "hub")
    else:
        command = [
            "wsl",
            "-d",
            wsl_distribution,
            "--",
            python_path,
            _wsl_path(root / "tools" / "run_birefnet_wsl.py"),
            "--checkpoint",
            _wsl_path(checkpoint),
            "--image",
            _wsl_path(image_path),
            "--output",
            _wsl_path(output_path),
            "--tile-size",
            str(tile_size),
            "--tile-overlap",
            str(tile_overlap),
        ]
        launcher = "wsl_cuda"
        environment = None
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
            **({"env": environment} if environment is not None else {}),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SilhouetteError(f"BiRefNet {launcher} launch failed: {exc}") from exc
    if process.returncode:
        detail = process.stderr.strip()[-2000:] or process.stdout.strip()[-2000:]
        raise SilhouetteError(f"BiRefNet {launcher} inference failed: {detail}")
    try:
        metadata = json.loads(process.stdout.strip().splitlines()[-1])
        confidence = np.load(output_path, allow_pickle=False)
    except (OSError, ValueError, IndexError, json.JSONDecodeError) as exc:
        raise SilhouetteError(f"BiRefNet output invalid: {exc}") from exc
    if confidence.dtype != np.float32 or confidence.ndim != 2:
        raise SilhouetteError("BiRefNet output must be a 2-D float32 confidence map")
    if metadata.get("shape") != list(confidence.shape):
        raise SilhouetteError("BiRefNet metadata/output shape mismatch")
    expected_metadata = {
        "protocol_version": 1,
        "model_revision": "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4",
        "precision": "fp16",
        "tile_size": tile_size,
        "tile_overlap": tile_overlap,
    }
    mismatches = {
        key: (metadata.get(key), expected)
        for key, expected in expected_metadata.items()
        if metadata.get(key) != expected
    }
    if mismatches:
        raise SilhouetteError(f"BiRefNet metadata violates governed contract: {mismatches}")
    if not isinstance(metadata.get("tile_count"), int) or metadata["tile_count"] < 1:
        raise SilhouetteError("BiRefNet metadata requires a positive integer tile_count")
    if not isinstance(metadata.get("device"), str) or not metadata["device"].strip():
        raise SilhouetteError("BiRefNet metadata requires the CUDA device name")
    if "+cu128" not in str(metadata.get("torch", "")):
        raise SilhouetteError("BiRefNet metadata requires the governed cu128 PyTorch runtime")
    if not np.isfinite(confidence).all() or confidence.min() < 0 or confidence.max() > 1:
        raise SilhouetteError("BiRefNet confidence must be finite and in 0..1")
    runtime_document = {
        "launcher": launcher,
        "python": str(local_python or python_path),
        **metadata,
    }
    (Path(output_path).parent / "birefnet_runtime.json").write_text(
        json.dumps(runtime_document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return confidence


def run_s02(
    context_image_path: Path,
    *,
    context_bbox_xyxy: tuple[int, int, int, int],
    person_bbox_xyxy: tuple[int, int, int, int],
    full_size: tuple[int, int],
    output_dir: Path,
    checkpoint: Path,
    tile_size: int = 2048,
    tile_overlap: int = 128,
    threshold: float = 0.5,
    connected_min_person_pct: float = 0.01,
    ratio_range: tuple[float, float] = (0.35, 0.95),
    local_cuda_python: Path | None = None,
    hf_home: Path | None = None,
) -> S02Result:
    """Execute real BiRefNet inference followed by S02 confidence post-processing."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    confidence = infer_birefnet_confidence(
        context_image_path,
        checkpoint=checkpoint,
        output_path=output_dir / "birefnet_confidence.npy",
        tile_size=tile_size,
        tile_overlap=tile_overlap,
        local_cuda_python=local_cuda_python,
        hf_home=hf_home,
    )
    expected_shape = (
        context_bbox_xyxy[3] - context_bbox_xyxy[1],
        context_bbox_xyxy[2] - context_bbox_xyxy[0],
    )
    if confidence.shape != expected_shape:
        raise SilhouetteError(
            f"BiRefNet confidence shape {confidence.shape} != context crop {expected_shape}"
        )
    return build_silhouette(
        confidence,
        context_bbox_xyxy=context_bbox_xyxy,
        person_bbox_xyxy=person_bbox_xyxy,
        full_size=full_size,
        output_dir=output_dir,
        threshold=threshold,
        connected_min_person_pct=connected_min_person_pct,
        ratio_range=ratio_range,
    )


def _wsl_path(path: Path) -> str:
    resolved = Path(path).resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        raise SilhouetteError(f"expected Windows drive path: {resolved}")
    return f"/mnt/{drive}{resolved.as_posix().split(':', 1)[1]}"


def build_silhouette(
    confidence_crop: np.ndarray,
    *,
    context_bbox_xyxy: tuple[int, int, int, int],
    person_bbox_xyxy: tuple[int, int, int, int],
    full_size: tuple[int, int],
    output_dir: Path,
    threshold: float = 0.5,
    connected_min_person_pct: float = 0.01,
    ratio_range: tuple[float, float] = (0.35, 0.95),
) -> S02Result:
    confidence = np.asarray(confidence_crop, dtype=np.float32)
    if confidence.ndim != 2 or not np.isfinite(confidence).all():
        raise SilhouetteError("confidence crop must be finite and 2-D")
    if confidence.min() < 0 or confidence.max() > 1:
        raise SilhouetteError("confidence values must be in 0..1")
    if not 0 <= threshold <= 1:
        raise SilhouetteError("threshold must be in 0..1")
    if not 0 <= connected_min_person_pct <= 1:
        raise SilhouetteError("connected_min_person_pct must be in 0..1")
    if (
        len(ratio_range) != 2
        or not 0 <= ratio_range[0] <= ratio_range[1]
        or not np.isfinite(ratio_range).all()
    ):
        raise SilhouetteError("ratio_range must contain two finite ascending non-negative values")
    left, top, right, bottom = _validated_bbox(
        context_bbox_xyxy, full_size=full_size, name="context"
    )
    person_left, person_top, person_right, person_bottom = _validated_bbox(
        person_bbox_xyxy, full_size=full_size, name="person"
    )
    if not (
        left <= person_left < person_right <= right and top <= person_top < person_bottom <= bottom
    ):
        raise SilhouetteError("person bbox must be fully contained by the context bbox")
    width, height = full_size
    if confidence.shape != (bottom - top, right - left):
        raise SilhouetteError("confidence crop shape does not match context bbox")
    binary = confidence >= threshold
    labels, component_count = ndimage.label(binary, structure=_FOUR_CONNECTED)
    if component_count:
        areas = np.bincount(labels.ravel(), minlength=component_count + 1)
        areas[0] = 0
        largest_label = int(np.argmax(areas))
        keep = labels == largest_label
        person_bbox_area = (person_right - person_left) * (person_bottom - person_top)
        min_area = connected_min_person_pct * person_bbox_area
        for label_id in np.flatnonzero(areas >= min_area):
            if label_id in (0, largest_label):
                continue
            candidate = labels == label_id
            if np.any(ndimage.binary_dilation(candidate, structure=_EIGHT_CONNECTED) & keep):
                keep |= candidate
        binary = keep
    full_mask = np.zeros((height, width), dtype=bool)
    full_confidence = np.zeros((height, width), dtype=np.uint8)
    full_mask[top:bottom, left:right] = binary
    full_confidence[top:bottom, left:right] = np.rint(confidence * 255).astype(np.uint8)
    bbox_area = (person_right - person_left) * (person_bottom - person_top)
    area = int(full_mask.sum())
    ratio = area / bbox_area if bbox_area else 0.0
    output_dir = Path(output_dir)
    silhouette_path = write_binary_mask(
        output_dir / "person_full_visible.png", full_mask, source_size=full_size
    )
    confidence_path = write_grayscale(
        output_dir / "person_full_visible_confidence.png",
        full_confidence,
        source_size=full_size,
    )
    result = S02Result(
        silhouette_path,
        confidence_path,
        area,
        bbox_area,
        ratio,
        ratio_range[0] <= ratio <= ratio_range[1],
    )
    (output_dir / "silhouette_metrics.json").write_text(
        json.dumps(
            {
                "area_px": area,
                "bbox_area_px": bbox_area,
                "silhouette_bbox_ratio": ratio,
                "qc_range": list(ratio_range),
                "qc_passed": result.qc_passed,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


_FOUR_CONNECTED = ndimage.generate_binary_structure(2, 1)
_EIGHT_CONNECTED = ndimage.generate_binary_structure(2, 2)


def _validated_bbox(
    bbox: tuple[int, int, int, int], *, full_size: tuple[int, int], name: str
) -> tuple[int, int, int, int]:
    if len(bbox) != 4 or any(
        isinstance(value, bool) or not isinstance(value, int) for value in bbox
    ):
        raise SilhouetteError(f"{name} bbox must contain four integer coordinates")
    if (
        len(full_size) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in full_size)
        or full_size[0] <= 0
        or full_size[1] <= 0
    ):
        raise SilhouetteError("full_size must contain positive integer width and height")
    left, top, right, bottom = bbox
    width, height = full_size
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise SilhouetteError(f"{name} bbox must be non-empty and inside the full canvas")
    return bbox
