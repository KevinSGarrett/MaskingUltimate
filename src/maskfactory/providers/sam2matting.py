"""Governed SAM2Matting boundary challenger with no semantic-label authority."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .contracts import AlphaMatteProposal, MaskProposal, MattingRefiner, ProviderIdentity

ROOT = Path(__file__).resolve().parents[3]
SAM2MATTING_SOURCE_REVISION = "73dd721d77b56749248aefe5e8824d7f61b9d13c"
SAM2MATTING_CHECKPOINT_REVISION = "4315db9c60d27fde396b09765748a0ca6c97bed5"
SAM2MATTING_CHECKPOINT_SHA256 = "1f0eb2eda3e8bc9101eafc0b30b8b8fcae1ff83d8fd3adc18e2f3b410fdaae60"
SAM2MATTING_RUNTIME_FINGERPRINT = "270da4b540d8bb8a033e380c913c9f59ceb78f5715c8d919dec145f65d39a5a5"

CommandExecutor = Callable[[Sequence[str], int], subprocess.CompletedProcess[str]]


class SAM2MattingError(RuntimeError):
    """SAM2Matting violated its geometry, provenance, or output contract."""


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
    raise SAM2MattingError("SAM2Matting process emitted no JSON report")


class SAM2MattingProvider:
    """Refine an upstream binary prior into alpha/binary boundary proposals only."""

    def __init__(
        self,
        *,
        runtime_python: Path | str,
        source_root: Path | str,
        checkpoint_path: Path | str,
        threshold: float = 0.5,
        timeout_seconds: int = 300,
        fallback: MattingRefiner | None = None,
        executor: CommandExecutor = _run_command,
    ) -> None:
        if not 0 < threshold < 1:
            raise ValueError("SAM2Matting threshold must be within 0..1")
        if timeout_seconds < 1:
            raise ValueError("SAM2Matting timeout must be positive")
        self.identity = ProviderIdentity(
            provider_key="sam2matting_base_plus",
            role="boundary_refiner",
            model_family="sam2matting",
            source_commit=SAM2MATTING_SOURCE_REVISION,
            runtime_fingerprint=SAM2MATTING_RUNTIME_FINGERPRINT,
        )
        self.runtime_python = str(runtime_python)
        self.source_root = str(source_root)
        self.checkpoint_path = str(checkpoint_path)
        self.threshold = threshold
        self.timeout_seconds = timeout_seconds
        self.fallback = fallback
        self._executor = executor

    def refine_matte(self, image_path: Path, *, prior_mask: np.ndarray) -> AlphaMatteProposal:
        try:
            alpha, report = self._infer(image_path, prior_mask=prior_mask)
        except (SAM2MattingError, subprocess.TimeoutExpired):
            if self.fallback is None:
                raise
            return self.fallback.refine_matte(Path(image_path), prior_mask=prior_mask)
        return AlphaMatteProposal(
            alpha,
            self.identity,
            self._prompt_fingerprint(image_path, prior_mask, report),
        )

    def refine_mask(self, image_path: Path, *, prior_mask: np.ndarray) -> MaskProposal:
        proposal = self.refine_matte(image_path, prior_mask=prior_mask)
        mask = np.asarray(proposal.alpha >= self.threshold, dtype=np.bool_)
        confidence = float(proposal.alpha[mask].mean()) if mask.any() else 0.0
        return MaskProposal(mask, confidence, proposal.provider, proposal.prompt_fingerprint)

    def _infer(
        self, image_path: Path, *, prior_mask: np.ndarray
    ) -> tuple[np.ndarray, Mapping[str, Any]]:
        image_path = Path(image_path)
        if not image_path.is_file():
            raise SAM2MattingError(f"SAM2Matting input image is missing: {image_path}")
        prior = np.asarray(prior_mask)
        if prior.ndim != 2 or prior.dtype != np.bool_:
            raise SAM2MattingError("SAM2Matting prior must be a 2-D boolean array")
        with Image.open(image_path) as image:
            expected_shape = (image.height, image.width)
        if prior.shape != expected_shape:
            raise SAM2MattingError("SAM2Matting prior geometry must match the source image")
        if not prior.any() or prior.all():
            raise SAM2MattingError("SAM2Matting prior must be nondegenerate")

        with tempfile.TemporaryDirectory(prefix="maskfactory-sam2matting-") as directory:
            directory_path = Path(directory)
            prior_path = directory_path / "prior.png"
            output_path = directory_path / "alpha.npy"
            Image.fromarray(prior.astype(np.uint8) * 255, mode="L").save(prior_path)
            argv = (
                self.runtime_python,
                str(ROOT / "tools" / "run_sam2matting.py"),
                "--source-root",
                self.source_root,
                "--checkpoint",
                self.checkpoint_path,
                "--image",
                str(image_path.resolve()),
                "--prior-mask",
                str(prior_path),
                "--output",
                str(output_path),
                "--threshold",
                str(self.threshold),
                "--repeats",
                "2",
            )
            try:
                completed = self._executor(argv, self.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                raise SAM2MattingError(
                    f"SAM2Matting exceeded {self.timeout_seconds}s timeout"
                ) from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "no process output").strip()
                raise SAM2MattingError(
                    f"SAM2Matting process failed with exit {completed.returncode}: {detail[-1000:]}"
                )
            report = _last_json_object(completed.stdout)
            alpha = self._validate_report(
                report,
                output_path=output_path,
                image_path=image_path,
                prior=prior,
                prior_path=prior_path,
            )
        return alpha, report

    def _validate_report(
        self,
        report: Mapping[str, Any],
        *,
        output_path: Path,
        image_path: Path,
        prior: np.ndarray,
        prior_path: Path,
    ) -> np.ndarray:
        checkpoint = report.get("checkpoint")
        image = report.get("image")
        reported_prior = report.get("prior_mask")
        if (
            report.get("provider") != "sam2matting_base_plus"
            or report.get("source_revision") != SAM2MATTING_SOURCE_REVISION
            or report.get("checkpoint_revision") != SAM2MATTING_CHECKPOINT_REVISION
        ):
            raise SAM2MattingError("SAM2Matting source provenance mismatch")
        if (
            not isinstance(checkpoint, Mapping)
            or checkpoint.get("sha256") != SAM2MATTING_CHECKPOINT_SHA256
        ):
            raise SAM2MattingError("SAM2Matting checkpoint SHA-256 mismatch")
        if not isinstance(image, Mapping) or image.get("sha256") != _sha256(image_path):
            raise SAM2MattingError("SAM2Matting input image SHA-256 mismatch")
        if (
            not isinstance(reported_prior, Mapping)
            or reported_prior.get("sha256") != _sha256(prior_path)
            or reported_prior.get("payload_sha256")
            != hashlib.sha256(prior.astype(np.uint8).tobytes()).hexdigest()
        ):
            raise SAM2MattingError("SAM2Matting prior provenance mismatch")
        if report.get("semantic_authority") is not False:
            raise SAM2MattingError("SAM2Matting may not claim semantic authority")
        if report.get("deterministic") is not True or report.get("repeats") != 2:
            raise SAM2MattingError("SAM2Matting output lacks two-run determinism proof")
        if report.get("threshold") != self.threshold:
            raise SAM2MattingError("SAM2Matting threshold provenance mismatch")
        if not output_path.is_file() or report.get("output_npy_sha256") != _sha256(output_path):
            raise SAM2MattingError("SAM2Matting alpha artifact hash mismatch")
        try:
            alpha = np.asarray(np.load(output_path, allow_pickle=False), dtype=np.float32)
        except (OSError, ValueError) as exc:
            raise SAM2MattingError("SAM2Matting alpha artifact is unreadable") from exc
        if alpha.shape != prior.shape or report.get("alpha_shape") != list(alpha.shape):
            raise SAM2MattingError("SAM2Matting alpha geometry mismatch")
        if hashlib.sha256(alpha.tobytes()).hexdigest() != report.get("alpha_sha256"):
            raise SAM2MattingError("SAM2Matting alpha payload hash mismatch")
        if not np.isfinite(alpha).all() or alpha.min() < 0 or alpha.max() > 1:
            raise SAM2MattingError("SAM2Matting alpha violates finite 0..1 contract")
        mask = alpha >= self.threshold
        if not mask.any() or mask.all():
            raise SAM2MattingError("SAM2Matting thresholded mask is degenerate")
        return alpha

    def _prompt_fingerprint(
        self, image_path: Path, prior_mask: np.ndarray, report: Mapping[str, Any]
    ) -> str:
        payload = {
            "provider": "sam2matting_base_plus",
            "image_sha256": _sha256(Path(image_path)),
            "prior_payload_sha256": hashlib.sha256(
                np.asarray(prior_mask, dtype=np.uint8).tobytes()
            ).hexdigest(),
            "threshold": self.threshold,
            "alpha_sha256": report["alpha_sha256"],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


__all__ = [
    "SAM2MATTING_CHECKPOINT_REVISION",
    "SAM2MATTING_CHECKPOINT_SHA256",
    "SAM2MATTING_RUNTIME_FINGERPRINT",
    "SAM2MATTING_SOURCE_REVISION",
    "SAM2MattingError",
    "SAM2MattingProvider",
]
