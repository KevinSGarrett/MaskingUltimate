"""S02 BiRefNet confidence post-processing and full-canvas silhouette placement."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

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
) -> np.ndarray:
    """Run pinned BiRefNet in WSL and validate its geometry-preserving float confidence."""
    root = Path(__file__).resolve().parents[3]
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
    ]
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SilhouetteError(f"BiRefNet WSL launch failed: {exc}") from exc
    if process.returncode:
        detail = process.stderr.strip()[-2000:] or process.stdout.strip()[-2000:]
        raise SilhouetteError(f"BiRefNet WSL inference failed: {detail}")
    try:
        metadata = json.loads(process.stdout.strip().splitlines()[-1])
        confidence = np.load(output_path, allow_pickle=False)
    except (OSError, ValueError, IndexError, json.JSONDecodeError) as exc:
        raise SilhouetteError(f"BiRefNet output invalid: {exc}") from exc
    if confidence.dtype != np.float32 or confidence.ndim != 2:
        raise SilhouetteError("BiRefNet output must be a 2-D float32 confidence map")
    if metadata.get("shape") != list(confidence.shape):
        raise SilhouetteError("BiRefNet metadata/output shape mismatch")
    return confidence


def run_s02(
    context_image_path: Path,
    *,
    context_bbox_xyxy: tuple[int, int, int, int],
    person_bbox_xyxy: tuple[int, int, int, int],
    full_size: tuple[int, int],
    output_dir: Path,
    checkpoint: Path,
) -> S02Result:
    """Execute real BiRefNet inference followed by S02 confidence post-processing."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    confidence = infer_birefnet_confidence(
        context_image_path,
        checkpoint=checkpoint,
        output_path=output_dir / "birefnet_confidence.npy",
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
    left, top, right, bottom = context_bbox_xyxy
    width, height = full_size
    if confidence.shape != (bottom - top, right - left):
        raise SilhouetteError("confidence crop shape does not match context bbox")
    binary = confidence >= threshold
    components = _components(binary)
    if components:
        components.sort(key=len, reverse=True)
        largest = components[0]
        keep = np.zeros(binary.shape, dtype=bool)
        _paint(keep, largest)
        person_bbox_area = (person_bbox_xyxy[2] - person_bbox_xyxy[0]) * (
            person_bbox_xyxy[3] - person_bbox_xyxy[1]
        )
        min_area = connected_min_person_pct * person_bbox_area
        for component in components[1:]:
            candidate = np.zeros(binary.shape, dtype=bool)
            _paint(candidate, component)
            if len(component) >= min_area and np.any(_dilate(candidate) & keep):
                keep |= candidate
        binary = keep
    full_mask = np.zeros((height, width), dtype=bool)
    full_confidence = np.zeros((height, width), dtype=np.uint8)
    full_mask[top:bottom, left:right] = binary
    full_confidence[top:bottom, left:right] = np.rint(confidence * 255).astype(np.uint8)
    bbox_area = (person_bbox_xyxy[2] - person_bbox_xyxy[0]) * (
        person_bbox_xyxy[3] - person_bbox_xyxy[1]
    )
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


def _components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    visited = np.zeros(mask.shape, dtype=bool)
    height, width = mask.shape
    output = []
    for y, x in zip(*np.nonzero(mask), strict=True):
        if visited[y, x]:
            continue
        stack = [(int(y), int(x))]
        visited[y, x] = True
        component = []
        while stack:
            cy, cx = stack.pop()
            component.append((cy, cx))
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    stack.append((ny, nx))
        output.append(component)
    return output


def _paint(mask: np.ndarray, component: list[tuple[int, int]]) -> None:
    if component:
        ys, xs = zip(*component, strict=True)
        mask[np.asarray(ys), np.asarray(xs)] = True


def _dilate(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1)
    return (
        padded[1:-1, 1:-1]
        | padded[:-2, 1:-1]
        | padded[2:, 1:-1]
        | padded[1:-1, :-2]
        | padded[1:-1, 2:]
    )
