"""S08.5 DensePose IUV artifact contract and provider boundary."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image


class DensePoseError(ValueError):
    """DensePose provider output violates the IUV contract."""


@dataclass(frozen=True)
class DensePoseOutput:
    part_index: np.ndarray
    u: np.ndarray
    v: np.ndarray


class DensePoseProvider(Protocol):
    def infer(self, image: np.ndarray) -> DensePoseOutput: ...


class WslDensePoseProvider:
    """Pinned Detectron2 DensePose R50 provider with instance ownership projection."""

    def __init__(
        self,
        *,
        checkpoint: Path,
        config_path: str,
        image_path: Path,
        target_bbox_xyxy: tuple[float, float, float, float],
        work_dir: Path,
        wsl_distribution: str = "Ubuntu-22.04",
        python_path: str = "/home/kevin/miniforge3/envs/maskfactory/bin/python",
        timeout_sec: int = 900,
    ) -> None:
        self.checkpoint = Path(checkpoint)
        self.config_path = config_path
        self.image_path = Path(image_path)
        self.target_bbox_xyxy = target_bbox_xyxy
        self.work_dir = Path(work_dir)
        self.wsl_distribution = wsl_distribution
        self.python_path = python_path
        self.timeout_sec = timeout_sec

    def infer(self, image: np.ndarray) -> DensePoseOutput:
        source = np.asarray(image)
        if source.ndim != 3 or source.shape[2] not in {3, 4}:
            raise DensePoseError("DensePose input must be HxWx3/4")
        if not self.checkpoint.is_file() or not self.image_path.is_file():
            raise DensePoseError("DensePose checkpoint or source image missing")
        with Image.open(self.image_path) as opened:
            if opened.size != (source.shape[1], source.shape[0]):
                raise DensePoseError("DensePose source path/array geometry mismatch")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.work_dir / "provider_iuv.png"
        root = Path(__file__).resolve().parents[3]
        command = [
            "wsl",
            "-d",
            self.wsl_distribution,
            "--",
            self.python_path,
            _wsl_path(root / "tools" / "run_densepose_wsl.py"),
            "--checkpoint",
            _wsl_path(self.checkpoint),
            "--config",
            self.config_path,
            "--image",
            _wsl_path(self.image_path),
            "--target-bbox-json",
            json.dumps(self.target_bbox_xyxy),
            "--output",
            _wsl_path(output_path),
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
            raise DensePoseError(f"DensePose WSL launch failed: {exc}") from exc
        if process.returncode:
            detail = process.stderr.strip()[-2000:] or process.stdout.strip()[-2000:]
            raise DensePoseError(f"DensePose inference failed: {detail}")
        try:
            metadata = json.loads(process.stdout.strip().splitlines()[-1])
            with Image.open(output_path) as opened:
                if opened.mode != "RGB":
                    raise DensePoseError("DensePose IUV provider output must be RGB")
                iuv = np.asarray(opened).copy()
        except (OSError, ValueError, IndexError, json.JSONDecodeError) as exc:
            raise DensePoseError(f"DensePose provider output invalid: {exc}") from exc
        if iuv.shape != (*source.shape[:2], 3) or metadata.get("shape") != list(source.shape[:2]):
            raise DensePoseError("DensePose provider geometry mismatch")
        output = DensePoseOutput(iuv[:, :, 0], iuv[:, :, 1], iuv[:, :, 2])
        _validate_iuv(output)
        return output


def run_densepose(provider: DensePoseProvider, image: np.ndarray, output_dir: Path) -> Path:
    output = provider.infer(np.asarray(image))
    return write_densepose_iuv(
        output.part_index, output.u, output.v, Path(output_dir) / "densepose_iuv.png"
    )


def write_densepose_iuv(part_index: np.ndarray, u: np.ndarray, v: np.ndarray, path: Path) -> Path:
    """Write RGB channels [I,U,V], where I is 0 background or one of 24 surfaces."""
    output = DensePoseOutput(np.asarray(part_index), np.asarray(u), np.asarray(v))
    _validate_iuv(output)
    index, u_value, v_value = output.part_index, output.u, output.v

    iuv = np.stack((index, u_value, v_value), axis=2).astype(np.uint8)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(iuv, mode="RGB").save(  # png-strict: allow (RGB DensePose evidence, never mask)
        path, format="PNG"
    )
    return path


def _validate_iuv(output: DensePoseOutput) -> None:
    index = np.asarray(output.part_index)
    u_value, v_value = np.asarray(output.u), np.asarray(output.v)
    if index.ndim != 2 or u_value.shape != index.shape or v_value.shape != index.shape:
        raise DensePoseError("I/U/V dimensions differ")
    if not all(np.issubdtype(value.dtype, np.integer) for value in (index, u_value, v_value)):
        raise DensePoseError("I/U/V must be integer arrays")
    if (
        index.min() < 0
        or index.max() > 24
        or u_value.min() < 0
        or u_value.max() > 255
        or v_value.min() < 0
        or v_value.max() > 255
    ):
        raise DensePoseError("I/U/V values outside I=0..24,U/V=0..255")
    if np.any((index == 0) & ((u_value != 0) | (v_value != 0))):
        raise DensePoseError("background I=0 must have U=V=0")


def _wsl_path(path: Path) -> str:
    resolved = Path(path).resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        raise DensePoseError(f"expected Windows drive path: {resolved}")
    return f"/mnt/{drive}{resolved.as_posix().split(':', 1)[1]}"
