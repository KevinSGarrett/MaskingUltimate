"""P3 hair/face lane with binary authority, optional matting, and face protection."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

import numpy as np
from PIL import Image
from scipy import ndimage

from ..io.png_strict import write_binary_mask, write_grayscale
from ..qa.panels import render_boundary_panel
from ..stages.s05_geometry import PromptPlan, build_prompt_plan
from ..stages.s07_sam2 import RefinedPart, Sam2Provider, refine_part


class HairLaneError(ValueError):
    """Hair-lane inputs violate crop, binary, or protected-region contracts."""


@dataclass(frozen=True)
class HeadCrop:
    path: Path
    bbox_xyxy: tuple[int, int, int, int]
    full_frame_fallback: bool


@dataclass(frozen=True)
class HairFaceDraft:
    hair_binary: np.ndarray
    hair_confidence: np.ndarray
    face: np.ndarray
    scalp_skin: np.ndarray


@dataclass(frozen=True)
class MattingArtifacts:
    triggered: bool
    binary_path: Path | None
    trimap_path: Path | None
    alpha_path: Path | None


class WslVitMatteProvider:
    """Callable alpha provider backed by the pinned ViTMatte-S CUDA checkpoint."""

    def __init__(
        self,
        checkpoint: Path,
        work_dir: Path,
        *,
        revision: str = "6a58ad7646403c1df626fbd746900aec7361ea1d",
        wsl_distribution: str = "Ubuntu-22.04",
        python_path: str = "/home/kevin/miniforge3/envs/maskfactory/bin/python",
        timeout_sec: int = 900,
    ) -> None:
        self.checkpoint = Path(checkpoint)
        self.work_dir = Path(work_dir)
        self.revision = revision
        self.wsl_distribution = wsl_distribution
        self.python_path = python_path
        self.timeout_sec = timeout_sec

    def __call__(self, image: np.ndarray, trimap: np.ndarray) -> np.ndarray:
        source = np.asarray(image)
        guide = np.asarray(trimap)
        if source.ndim != 3 or source.shape[2] != 3 or guide.shape != source.shape[:2]:
            raise HairLaneError("ViTMatte source/trimap geometry invalid")
        if guide.dtype != np.uint8 or set(np.unique(guide).tolist()) - {0, 128, 255}:
            raise HairLaneError("ViTMatte trimap must be uint8 0/128/255")
        if not self.checkpoint.is_file():
            raise HairLaneError(f"ViTMatte checkpoint missing: {self.checkpoint}")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        token = "vitmatte_" + hashlib.sha256(source.tobytes() + guide.tobytes()).hexdigest()[:16]
        image_path = self.work_dir / f"{token}_image.png"
        trimap_path = self.work_dir / f"{token}_trimap.png"
        output_path = self.work_dir / f"{token}_alpha.png"
        Image.fromarray(source.astype(np.uint8), mode="RGB").save(image_path, format="PNG")
        Image.fromarray(guide, mode="L").save(trimap_path, format="PNG")
        root = Path(__file__).resolve().parents[3]
        command = [
            "wsl",
            "-d",
            self.wsl_distribution,
            "--",
            self.python_path,
            _wsl_path(root / "tools" / "run_vitmatte_wsl.py"),
            "--checkpoint",
            _wsl_path(self.checkpoint),
            "--image",
            _wsl_path(image_path),
            "--trimap",
            _wsl_path(trimap_path),
            "--output",
            _wsl_path(output_path),
            "--revision",
            self.revision,
        ]
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HairLaneError(f"ViTMatte WSL launch failed: {exc}") from exc
        if process.returncode:
            detail = process.stderr.strip()[-2000:] or process.stdout.strip()[-2000:]
            raise HairLaneError(f"ViTMatte inference failed: {detail}")
        try:
            metadata = json.loads(process.stdout.strip().splitlines()[-1])
            with Image.open(output_path) as opened:
                if opened.mode != "L":
                    raise HairLaneError("ViTMatte alpha must be mode L")
                alpha = np.asarray(opened).copy()
        except (OSError, ValueError, IndexError, json.JSONDecodeError) as exc:
            raise HairLaneError(f"ViTMatte output invalid: {exc}") from exc
        if alpha.shape != guide.shape or metadata.get("shape") != list(guide.shape):
            raise HairLaneError("ViTMatte alpha geometry mismatch")
        if np.any(alpha[guide == 0]) or np.any(alpha[guide == 255] != 255):
            raise HairLaneError("ViTMatte violated known trimap regions")
        return alpha


def create_head_crop(
    source_path: Path,
    *,
    head_bbox_xyxy: tuple[int, int, int, int],
    hair_prior: np.ndarray,
    output_dir: Path,
) -> HeadCrop:
    """Use head bbox x1.8, but fall back to full frame if any hair lies outside it."""
    source_path = Path(source_path)
    with Image.open(source_path) as opened:
        source = opened.convert("RGB")
    hair = np.asarray(hair_prior).astype(bool)
    if hair.shape != (source.height, source.width):
        raise HairLaneError("hair prior dimensions differ from source")
    left, top, right, bottom = head_bbox_xyxy
    if not (0 <= left < right <= source.width and 0 <= top < bottom <= source.height):
        raise HairLaneError("head bbox outside source")
    side = math.ceil(max(right - left, bottom - top) * 1.8)
    if side > min(source.width, source.height):
        fallback = True
        box = (0, 0, source.width, source.height)
    else:
        center_x, center_y = (left + right) / 2, (top + bottom) / 2
        x0 = min(max(0, math.floor(center_x - side / 2)), source.width - side)
        y0 = min(max(0, math.floor(center_y - side / 2)), source.height - side)
        box = (x0, y0, x0 + side, y0 + side)
        inside = np.zeros_like(hair)
        inside[y0 : y0 + side, x0 : x0 + side] = True
        fallback = bool(np.any(hair & ~inside))
        if fallback:
            box = (0, 0, source.width, source.height)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "head_crop.png"
    if fallback:
        source.save(path, format="PNG")  # png-strict: allow (RGB lane source, never mask)
    else:
        source.crop(box).resize((1024, 1024), Image.Resampling.LANCZOS).save(
            path, format="PNG"
        )  # png-strict: allow (RGB head crop, never mask)
    return HeadCrop(path, box, fallback)


def fuse_hair_face(
    *,
    sapiens_hair_probability: np.ndarray,
    sapiens_face: np.ndarray,
    bisenet_hair_probability: np.ndarray,
    bisenet_face: np.ndarray,
    scalp_skin_seed: np.ndarray,
    opacity_threshold: float = 0.5,
) -> HairFaceDraft:
    """Fuse coarse/detail probabilities; binary authority follows the 50% opacity rule."""
    sapiens_hair = _probability(sapiens_hair_probability, "sapiens_hair")
    bisenet_hair = _probability(bisenet_hair_probability, "bisenet_hair")
    if sapiens_hair.shape != bisenet_hair.shape:
        raise HairLaneError("hair probability dimensions differ")
    shape = sapiens_hair.shape
    confidence = np.maximum(sapiens_hair, bisenet_hair)
    hair = confidence >= opacity_threshold
    face = (
        _same(sapiens_face, shape, "sapiens_face") | _same(bisenet_face, shape, "bisenet_face")
    ) & ~hair
    scalp = _same(scalp_skin_seed, shape, "scalp_skin_seed") & ~hair & ~face
    return HairFaceDraft(hair, confidence, face, scalp)


def refine_hair_with_sam2(
    provider: Sam2Provider,
    embedding: object,
    draft: HairFaceDraft,
    *,
    background: np.ndarray,
    model: str,
) -> RefinedPart:
    """Hair prompt includes face/background negatives and retains binary output authority."""
    negative_sources = [draft.face, _same(background, draft.hair_binary.shape, "background")]
    ys, xs = np.nonzero(draft.hair_binary)
    if not len(xs):
        raise HairLaneError("hair prior is empty")
    skeleton = tuple(
        (int(x), int(y))
        for x, y in zip(
            np.linspace(xs.min(), xs.max(), 5), np.linspace(ys.min(), ys.max(), 5), strict=True
        )
    )
    plan: PromptPlan = build_prompt_plan(
        "hair",
        draft.hair_confidence,
        skeleton_points_xy=skeleton,
        neighbor_priors=negative_sources,
        skeleton_samples=5,
    )
    return refine_part(provider, embedding, plan, draft.hair_binary, model=model)


def build_matting_artifacts(
    source_rgb: np.ndarray,
    binary: np.ndarray,
    *,
    person_bbox_area: int,
    output_dir: Path,
    alpha_provider: Callable[[np.ndarray, np.ndarray], np.ndarray],
    prefix: str = "hair",
) -> MattingArtifacts:
    """At >=2% bbox, write binary copy, ±6px@1024 trimap, and provider alpha matte."""
    mask = np.asarray(binary).astype(bool)
    image = np.asarray(source_rgb)
    if image.shape != (*mask.shape, 3) or person_bbox_area <= 0:
        raise HairLaneError("matting image/bbox inputs invalid")
    if int(mask.sum()) / person_bbox_area < 0.02:
        return MattingArtifacts(False, None, None, None)
    radius = max(1, round(6 * mask.shape[1] / 1024))
    eroded = ndimage.binary_erosion(mask, iterations=radius)
    dilated = ndimage.binary_dilation(mask, iterations=radius)
    trimap = np.zeros(mask.shape, dtype=np.uint8)
    trimap[dilated] = 128
    trimap[eroded] = 255
    alpha = np.asarray(alpha_provider(image, trimap))
    if alpha.shape != mask.shape or alpha.dtype != np.uint8:
        raise HairLaneError("alpha provider must return uint8 HxW")
    output_dir = Path(output_dir)
    binary_path = write_binary_mask(
        output_dir / f"{prefix}_binary.png", mask, source_size=(mask.shape[1], mask.shape[0])
    )
    trimap_path = write_grayscale(
        output_dir / f"{prefix}_trimap.png", trimap, source_size=(mask.shape[1], mask.shape[0])
    )
    alpha_path = write_grayscale(
        output_dir / f"{prefix}_alpha_matte.png", alpha, source_size=(mask.shape[1], mask.shape[0])
    )
    return MattingArtifacts(True, binary_path, trimap_path, alpha_path)


def build_face_protected(
    detail_masks: Mapping[str, np.ndarray], *, shape: tuple[int, int]
) -> np.ndarray:
    """Union eyes, mouth, nose, brows, and jawline band as the QC-013 face protection mask."""
    required = {"left_eye", "right_eye", "mouth", "nose", "left_brow", "right_brow", "jawline"}
    if set(detail_masks) != required:
        raise HairLaneError(f"face protection requires exactly {sorted(required)}")
    output = np.zeros(shape, dtype=bool)
    for name, value in detail_masks.items():
        mask = _same(value, shape, name)
        output |= ndimage.binary_dilation(mask, iterations=2) if name == "jawline" else mask
    return output


def apply_hair_shoulder_zorder(
    hair: np.ndarray,
    shoulder_masks: Mapping[str, np.ndarray],
) -> tuple[dict[str, np.ndarray], dict[str, str]]:
    """Hair owns overlap; affected shoulders become partially_visible."""
    hair_mask = np.asarray(hair).astype(bool)
    output, states = {}, {}
    for name, value in shoulder_masks.items():
        shoulder = _same(value, hair_mask.shape, name)
        overlap = shoulder & hair_mask
        output[name] = shoulder & ~hair_mask
        states[name] = "partially_visible" if overlap.any() else "visible"
    return output, states


def render_hairline_panel(
    source: Image.Image,
    hair: np.ndarray,
    face_protected: np.ndarray,
    output_path: Path,
) -> Path:
    return render_boundary_panel(source, hair, face_protected, output_path)


def _probability(value, name):
    array = np.asarray(value, dtype=np.float32)
    if array.ndim != 2 or not np.isfinite(array).all() or array.min() < 0 or array.max() > 1:
        raise HairLaneError(f"{name} must be finite probability HxW")
    return array


def _same(value, shape, name):
    mask = np.asarray(value).astype(bool)
    if mask.shape != shape:
        raise HairLaneError(f"{name} dimensions differ")
    return mask


def _wsl_path(path: Path) -> str:
    resolved = Path(path).resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        raise HairLaneError(f"expected Windows drive path: {resolved}")
    return f"/mnt/{drive}{resolved.as_posix().split(':', 1)[1]}"
