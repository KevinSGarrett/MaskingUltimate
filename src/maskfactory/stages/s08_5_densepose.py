"""S08.5 DensePose IUV artifact contract and provider boundary."""

from __future__ import annotations

import json
import os
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
        local_cuda_python: Path | None = None,
        source_path: Path | None = None,
        dependency_site: Path | None = None,
    ) -> None:
        self.checkpoint = Path(checkpoint)
        self.config_path = config_path
        self.image_path = Path(image_path)
        self.target_bbox_xyxy = target_bbox_xyxy
        self.work_dir = Path(work_dir)
        self.wsl_distribution = wsl_distribution
        self.python_path = python_path
        self.timeout_sec = timeout_sec
        self.local_cuda_python = Path(local_cuda_python) if local_cuda_python is not None else None
        self.source_path = Path(source_path) if source_path is not None else None
        self.dependency_site = Path(dependency_site) if dependency_site is not None else None

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
        arguments = [
            "--checkpoint",
            str(self.checkpoint.resolve()),
            "--config",
            self.config_path,
            "--image",
            str(self.image_path.resolve()),
            "--target-bbox-json",
            json.dumps(self.target_bbox_xyxy),
            "--output",
            str(output_path.resolve()),
        ]
        if self.local_cuda_python is not None:
            if not self.local_cuda_python.is_file():
                raise DensePoseError("configured local CUDA Python is missing")
            if (
                self.source_path is None
                or not (self.source_path / "detectron2/__init__.py").is_file()
            ):
                raise DensePoseError("configured Detectron2 source is missing")
            if self.dependency_site is None or not (self.dependency_site / "cloudpickle").is_dir():
                raise DensePoseError("configured Detectron2 dependency site is missing")
            local_config = (
                self.source_path / "projects/DensePose/configs/densepose_rcnn_R_50_FPN_s1x.yaml"
            )
            if not local_config.is_file():
                raise DensePoseError("configured DensePose model config is missing")
            arguments[3] = str(local_config.resolve())
            command = [
                str(self.local_cuda_python),
                str(root / "tools" / "run_densepose_wsl.py"),
                *arguments,
            ]
            launcher = "local_cuda"
            environment = os.environ.copy()
            existing = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = os.pathsep.join(
                [
                    str(self.source_path.resolve()),
                    str((self.source_path / "projects/DensePose").resolve()),
                    str(self.dependency_site.resolve()),
                    *([existing] if existing else []),
                ]
            )
        else:
            wsl_arguments = [
                _wsl_path(Path(value)) if index in {1, 5, 9} else value
                for index, value in enumerate(arguments)
            ]
            command = [
                "wsl",
                "-d",
                self.wsl_distribution,
                "--",
                self.python_path,
                _wsl_path(root / "tools" / "run_densepose_wsl.py"),
                *wsl_arguments,
            ]
            launcher = "wsl_cuda"
            environment = None
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                check=False,
                **({"env": environment} if environment is not None else {}),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DensePoseError(f"DensePose {launcher} launch failed: {exc}") from exc
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
        expected = {
            "checkpoint_sha256": "b8a7382001b16e453bad95ca9dbc68ae8f2b839b304cf90eaf5c27fbdb4dae91",
            "source_revision": "02b5c4e295e990042a714712c21dc79b731e8833",
            "device_type": "cuda",
            "config": "densepose_rcnn_R_50_FPN_s1x.yaml",
        }
        mismatches = {
            key: (metadata.get(key), value)
            for key, value in expected.items()
            if metadata.get(key) != value
        }
        if mismatches or "+cu128" not in str(metadata.get("torch", "")):
            raise DensePoseError(f"DensePose runtime metadata violates contract: {mismatches}")
        if not isinstance(metadata.get("device"), str) or not metadata["device"].strip():
            raise DensePoseError("DensePose runtime metadata requires CUDA device identity")
        runtime_document = {
            "launcher": launcher,
            "python": str(self.local_cuda_python or self.python_path),
            **metadata,
        }
        (self.work_dir / "runtime.json").write_text(
            json.dumps(runtime_document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
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


def read_densepose_iuv(path: Path) -> DensePoseOutput:
    """Load and validate a governed RGB [I,U,V] artifact."""
    try:
        with Image.open(path) as opened:
            if opened.mode != "RGB":
                raise DensePoseError("DensePose IUV artifact must be RGB")
            iuv = np.asarray(opened).copy()
    except OSError as exc:
        raise DensePoseError(f"cannot read DensePose IUV artifact: {path}") from exc
    output = DensePoseOutput(iuv[:, :, 0], iuv[:, :, 1], iuv[:, :, 2])
    _validate_iuv(output)
    return output


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
