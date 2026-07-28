"""Governed BiRefNet Dynamic/HR/HR-matting shadow providers."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .contracts import (
    AlphaMatteProposal,
    BoxProposal,
    MaskProposal,
    ProviderIdentity,
    SilhouetteProvider,
)

ROOT = Path(__file__).resolve().parents[3]
BIREFNET_RUNTIME_FINGERPRINT = "5b6d1c9cddec6e897d7ba9f16d40e0986ab66c677bef3ac830564f5553e16d1a"
BIREFNET_VARIANTS = {
    "birefnet_dynamic": {
        "revision": "280306042f57b7a33854319da62fd86aaa89ec4c",
        "checkpoint_sha256": "e3d2e4884e51ff30f0cd630edc6b1e41b06b7f23a0a2a5169f7b7cb33a711c2d",
        "resolution": 0,
        "matting": True,
    },
    "birefnet_hr": {
        "revision": "a7a562f6fd16021180f2f4348f4de003a2d3d1e1",
        "checkpoint_sha256": "9d678bafec0b0019fbb073b7fd02f05ede25dc4b15254f23b2fb0be333200c0d",
        "resolution": 1024,
        "matting": False,
    },
    "birefnet_hr_matting": {
        "revision": "5d6b6f8adcb5b417c871b1d84ceaae9871355b7f",
        "checkpoint_sha256": "a5a4de698739ea5e0e8bbab28e1b293dde95092b87a442d566cbc585c53cef55",
        "resolution": 1024,
        "matting": True,
    },
}

CommandExecutor = Callable[[Sequence[str], int], subprocess.CompletedProcess[str]]


class BiRefNetVariantError(RuntimeError):
    """A BiRefNet challenger violated runtime, provenance, or output contracts."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_command(argv: Sequence[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - exact governed argv, never shell=True
        list(argv),
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )


def _last_json_object(stdout: str) -> Mapping[str, Any]:
    for line in reversed(stdout.splitlines()):
        if not line.lstrip().startswith("{"):
            continue
        try:
            document = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(document, Mapping):
            return document
    raise BiRefNetVariantError("BiRefNet process emitted no JSON report")


class BiRefNetVariantProvider:
    """Run one frozen BiRefNet challenger without granting production authority.

    HR variants default to the model card's measured 1024 evaluation mode because
    native 2048 inference exceeded the available 8 GB promotion budget. The
    incumbent may be supplied as an explicit failure fallback; the returned
    proposal then retains the incumbent's identity and provenance.
    """

    def __init__(
        self,
        variant: str,
        *,
        runtime_python: Path | str = Path("C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe"),
        resolution: int | None = None,
        threshold: float = 0.5,
        context_scale: float = 1.25,
        timeout_seconds: int = 180,
        fallback: SilhouetteProvider | None = None,
        executor: CommandExecutor = _run_command,
    ) -> None:
        if variant not in BIREFNET_VARIANTS:
            raise ValueError(f"unknown governed BiRefNet variant: {variant}")
        config = BIREFNET_VARIANTS[variant]
        self.variant = variant
        self.identity = ProviderIdentity(
            provider_key=variant,
            role="silhouette_provider",
            model_family="birefnet",
            source_commit=str(config["revision"]),
            runtime_fingerprint=BIREFNET_RUNTIME_FINGERPRINT,
        )
        self.runtime_python = str(runtime_python)
        self.resolution = int(config["resolution"] if resolution is None else resolution)
        if self.resolution not in {0, 1024, 2048}:
            raise ValueError("BiRefNet resolution must be native, 1024, or 2048")
        if variant == "birefnet_dynamic" and self.resolution:
            raise ValueError("BiRefNet Dynamic must retain native dynamic resolution")
        if not 0 < threshold < 1:
            raise ValueError("BiRefNet threshold must be within 0..1")
        if context_scale < 1:
            raise ValueError("BiRefNet context scale must be at least one")
        if timeout_seconds < 1:
            raise ValueError("BiRefNet timeout must be positive")
        self.threshold = threshold
        self.context_scale = context_scale
        self.timeout_seconds = timeout_seconds
        self.fallback = fallback
        self._executor = executor

    def infer_silhouette(self, image_path: Path, *, person_box: BoxProposal) -> MaskProposal:
        try:
            alpha, report = self._infer(image_path, person_box=person_box)
        except (BiRefNetVariantError, subprocess.TimeoutExpired):
            if self.fallback is None:
                raise
            return self.fallback.infer_silhouette(Path(image_path), person_box=person_box)
        mask = np.asarray(alpha >= self.threshold, dtype=np.bool_)
        confidence = float(alpha[mask].mean()) if mask.any() else 0.0
        return MaskProposal(
            mask,
            confidence,
            self.identity,
            self._prompt_fingerprint(image_path, person_box, report),
        )

    def infer_matte(self, image_path: Path, *, person_box: BoxProposal) -> AlphaMatteProposal:
        if not BIREFNET_VARIANTS[self.variant]["matting"]:
            raise BiRefNetVariantError(f"{self.variant} has no governed matting output")
        alpha, report = self._infer(image_path, person_box=person_box)
        return AlphaMatteProposal(
            alpha,
            self.identity,
            self._prompt_fingerprint(image_path, person_box, report),
        )

    def _infer(
        self, image_path: Path, *, person_box: BoxProposal
    ) -> tuple[np.ndarray, Mapping[str, Any]]:
        image_path = Path(image_path)
        if not image_path.is_file():
            raise BiRefNetVariantError(f"BiRefNet input image is missing: {image_path}")
        with tempfile.TemporaryDirectory(prefix="maskfactory-birefnet-") as directory:
            output_path = Path(directory) / "confidence.npy"
            argv = (
                self.runtime_python,
                str(ROOT / "tools" / "run_birefnet_variant.py"),
                "--variant",
                self.variant,
                "--image",
                str(image_path.resolve()),
                "--person-box",
                *(str(value) for value in person_box.bbox_xyxy),
                "--output",
                str(output_path),
                "--resolution",
                str(self.resolution),
                "--context-scale",
                str(self.context_scale),
                "--repeats",
                "2",
            )
            try:
                completed = self._executor(argv, self.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                raise BiRefNetVariantError(
                    f"BiRefNet exceeded {self.timeout_seconds}s timeout"
                ) from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "no process output").strip()
                raise BiRefNetVariantError(
                    f"BiRefNet process failed with exit {completed.returncode}: {detail[-1000:]}"
                )
            report = _last_json_object(completed.stdout)
            alpha = self._validate_report(
                report,
                output_path=output_path,
                image_path=image_path,
                person_box=person_box,
            )
        return alpha, report

    def _validate_report(
        self,
        report: Mapping[str, Any],
        *,
        output_path: Path,
        image_path: Path,
        person_box: BoxProposal,
    ) -> np.ndarray:
        expected = BIREFNET_VARIANTS[self.variant]
        checkpoint = report.get("checkpoint")
        image = report.get("image")
        if (
            report.get("variant") != self.variant
            or report.get("repo_revision") != expected["revision"]
        ):
            raise BiRefNetVariantError("BiRefNet variant revision mismatch")
        if (
            not isinstance(checkpoint, Mapping)
            or checkpoint.get("sha256") != expected["checkpoint_sha256"]
        ):
            raise BiRefNetVariantError("BiRefNet checkpoint SHA-256 mismatch")
        if not isinstance(image, Mapping) or image.get("sha256") != _sha256(image_path):
            raise BiRefNetVariantError("BiRefNet input image SHA-256 mismatch")
        if report.get("deterministic") is not True or report.get("repeats") != 2:
            raise BiRefNetVariantError("BiRefNet output lacks two-run determinism proof")
        expected_resolution: int | str = self.resolution or "native_divisible_by_32"
        if report.get("resolution") != expected_resolution:
            raise BiRefNetVariantError("BiRefNet resolution provenance mismatch")
        reported_box = report.get("person_box_xyxy")
        if (
            not isinstance(reported_box, list)
            or len(reported_box) != 4
            or not all(
                math.isclose(float(actual), expected_value, abs_tol=1e-9)
                for actual, expected_value in zip(reported_box, person_box.bbox_xyxy, strict=True)
            )
        ):
            raise BiRefNetVariantError("BiRefNet person box provenance mismatch")
        if not output_path.is_file() or report.get("output_npy_sha256") != _sha256(output_path):
            raise BiRefNetVariantError("BiRefNet confidence artifact hash mismatch")
        try:
            alpha = np.asarray(np.load(output_path, allow_pickle=False), dtype=np.float32)
        except (OSError, ValueError) as exc:
            raise BiRefNetVariantError("BiRefNet confidence artifact is unreadable") from exc
        if alpha.ndim != 2 or report.get("confidence_shape") != list(alpha.shape):
            raise BiRefNetVariantError("BiRefNet confidence shape mismatch")
        if hashlib.sha256(alpha.tobytes()).hexdigest() != report.get("confidence_sha256"):
            raise BiRefNetVariantError("BiRefNet confidence payload hash mismatch")
        if not np.isfinite(alpha).all() or alpha.min() < 0 or alpha.max() > 1:
            raise BiRefNetVariantError("BiRefNet confidence violates finite 0..1 contract")
        mask = alpha >= self.threshold
        if not mask.any() or mask.all():
            raise BiRefNetVariantError("BiRefNet strict silhouette is degenerate")
        return alpha

    def _prompt_fingerprint(
        self,
        image_path: Path,
        person_box: BoxProposal,
        report: Mapping[str, Any],
    ) -> str:
        payload = {
            "variant": self.variant,
            "image_sha256": _sha256(Path(image_path)),
            "person_box_xyxy": list(person_box.bbox_xyxy),
            "context_scale": self.context_scale,
            "resolution": self.resolution or "native_divisible_by_32",
            "threshold": self.threshold,
            "confidence_sha256": report["confidence_sha256"],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


__all__ = [
    "AlphaMatteProposal",
    "BIREFNET_RUNTIME_FINGERPRINT",
    "BIREFNET_VARIANTS",
    "BiRefNetVariantError",
    "BiRefNetVariantProvider",
]
