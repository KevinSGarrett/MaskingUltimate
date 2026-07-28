"""Governed MatAnyone2 static/temporal alpha challenger with explicit rollback."""

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

from .contracts import (
    AlphaMatteProposal,
    AlphaMatteSequenceProposal,
    MattingRefiner,
    ProviderIdentity,
    TemporalMattingRefiner,
)

ROOT = Path(__file__).resolve().parents[3]
MATANYONE2_SOURCE_REVISION = "d3bb5a1ebedf259a5453c6d168e6840fff85581e"
MATANYONE2_CHECKPOINT_REVISION = "40c894a6f68d1f55c86ab0de838d89dc61587930"
MATANYONE2_CHECKPOINT_SHA256 = "70d3bf1d85d0aaf2020f9ef3577239f4f83b77c2ba47fca1eebaaf872f9ad40f"
MATANYONE2_CONFIG_SHA256 = "48dfbea235039093873586f352f0d05fbfdcbfeda094f2d8b257bc6408e68063"
MATANYONE2_BACKBONE_SHA256S = {
    "resnet50-19c8e357.pth": "19c8e3572231adff6824a2da93fd67b5986919a2e65f8b6007eab4edee220097",
    "resnet18-5c106cde.pth": "5c106cde386e87d4033832f2996f5493238eda96ccf559d1d62760c4de0613f8",
}
MATANYONE2_RUNTIME_FINGERPRINT = "ba4de3d22c40ce3cf0649a35e0f2d439dc1b8fb13f641c076cb71c3c27514b13"
STATIC_ROUTE = "static_first_frame_refinement"
TEMPORAL_ROUTE = "temporal_propagation"
ROUTES = frozenset({STATIC_ROUTE, TEMPORAL_ROUTE})

CommandExecutor = Callable[[Sequence[str], int], subprocess.CompletedProcess[str]]


class MatAnyone2Error(RuntimeError):
    """Base error for the governed MatAnyone2 adapter."""


class MatAnyone2CapabilityError(MatAnyone2Error):
    """The requested route or input geometry is outside the exact provider contract."""


class MatAnyone2RuntimeError(MatAnyone2Error):
    """The isolated process or its output violated runtime/provenance requirements."""


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
    raise MatAnyone2RuntimeError("MatAnyone2 process emitted no JSON report")


class MatAnyone2Provider:
    """Run MatAnyone2 only for one-frame refinement or multi-frame propagation."""

    def __init__(
        self,
        *,
        runtime_python: Path | str,
        source_root: Path | str,
        model_dir: Path | str,
        torch_home: Path | str,
        timeout_seconds: int = 300,
        static_fallback: MattingRefiner | None = None,
        temporal_fallback: TemporalMattingRefiner | None = None,
        executor: CommandExecutor = _run_command,
    ) -> None:
        if timeout_seconds < 1:
            raise ValueError("MatAnyone2 timeout must be positive")
        self.identity = ProviderIdentity(
            provider_key="matanyone2",
            role="temporal_matting_refiner",
            model_family="matanyone2",
            source_commit=MATANYONE2_SOURCE_REVISION,
            runtime_fingerprint=MATANYONE2_RUNTIME_FINGERPRINT,
        )
        self.runtime_python = str(runtime_python)
        self.source_root = str(source_root)
        self.model_dir = str(model_dir)
        self.torch_home = str(torch_home)
        self.timeout_seconds = timeout_seconds
        self.static_fallback = static_fallback
        self.temporal_fallback = temporal_fallback
        self._executor = executor

    def refine_matte(self, image_path: Path, *, prior_mask: np.ndarray) -> AlphaMatteProposal:
        sequence = self.refine_route(
            (Path(image_path),), initial_mask=prior_mask, route=STATIC_ROUTE
        )
        return AlphaMatteProposal(
            sequence.alphas[0], sequence.provider, sequence.prompt_fingerprint
        )

    def refine_sequence(
        self, frame_paths: Sequence[Path], *, initial_mask: np.ndarray
    ) -> AlphaMatteSequenceProposal:
        return self.refine_route(
            tuple(Path(path) for path in frame_paths),
            initial_mask=initial_mask,
            route=TEMPORAL_ROUTE,
        )

    def refine_route(
        self,
        frame_paths: Sequence[Path],
        *,
        initial_mask: np.ndarray,
        route: str,
    ) -> AlphaMatteSequenceProposal:
        frames, mask, shape = self._validate_inputs(frame_paths, initial_mask, route=route)
        try:
            alphas, report = self._infer(frames, mask, shape=shape, route=route)
        except (MatAnyone2RuntimeError, subprocess.TimeoutExpired) as exc:
            try:
                return self._fallback(frames, mask, route=route)
            except MatAnyone2RuntimeError as fallback_error:
                raise fallback_error from exc
        return AlphaMatteSequenceProposal(
            alphas,
            self.identity,
            self._prompt_fingerprint(frames, mask, report),
            route,
        )

    def _validate_inputs(
        self, frame_paths: Sequence[Path], initial_mask: np.ndarray, *, route: str
    ) -> tuple[tuple[Path, ...], np.ndarray, tuple[int, int]]:
        frames = tuple(Path(path) for path in frame_paths)
        if route not in ROUTES:
            raise MatAnyone2CapabilityError(f"MatAnyone2 route is unsupported: {route}")
        if route == STATIC_ROUTE and len(frames) != 1:
            raise MatAnyone2CapabilityError(
                "static_first_frame_refinement requires exactly one frame"
            )
        if route == TEMPORAL_ROUTE and len(frames) < 2:
            raise MatAnyone2CapabilityError("temporal_propagation requires at least two frames")
        shape: tuple[int, int] | None = None
        for frame in frames:
            if not frame.is_file():
                raise MatAnyone2CapabilityError(f"MatAnyone2 frame is missing: {frame}")
            try:
                with Image.open(frame) as image:
                    current = (image.height, image.width)
            except OSError as exc:
                raise MatAnyone2CapabilityError(f"MatAnyone2 frame is unreadable: {frame}") from exc
            if shape is None:
                shape = current
            elif current != shape:
                raise MatAnyone2CapabilityError("MatAnyone2 frame geometry must be identical")
        if shape is None:  # route cardinality checks make this defensive only.
            raise MatAnyone2CapabilityError("MatAnyone2 requires at least one frame")
        mask = np.asarray(initial_mask)
        if mask.ndim != 2 or mask.dtype != np.bool_:
            raise MatAnyone2CapabilityError("MatAnyone2 initial mask must be a 2-D boolean array")
        if mask.shape != shape:
            raise MatAnyone2CapabilityError(
                "MatAnyone2 initial mask geometry must match every frame"
            )
        if not mask.any() or mask.all():
            raise MatAnyone2CapabilityError("MatAnyone2 initial mask must be nondegenerate")
        return frames, mask, shape

    def _infer(
        self,
        frames: tuple[Path, ...],
        mask: np.ndarray,
        *,
        shape: tuple[int, int],
        route: str,
    ) -> tuple[np.ndarray, Mapping[str, Any]]:
        with tempfile.TemporaryDirectory(prefix="maskfactory-matanyone2-") as directory:
            directory_path = Path(directory)
            initial_mask_path = directory_path / "initial_mask.png"
            output_path = directory_path / "alphas.npz"
            Image.fromarray(mask.astype(np.uint8) * 255, mode="L").save(initial_mask_path)
            argv = (
                self.runtime_python,
                str(ROOT / "tools" / "run_matanyone2.py"),
                "--source-root",
                self.source_root,
                "--model-dir",
                self.model_dir,
                "--torch-home",
                self.torch_home,
                "--frames",
                *(str(path.resolve()) for path in frames),
                "--initial-mask",
                str(initial_mask_path),
                "--route",
                route,
                "--output",
                str(output_path),
                "--repeats",
                "2",
            )
            try:
                completed = self._executor(argv, self.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                raise MatAnyone2RuntimeError(
                    f"MatAnyone2 exceeded {self.timeout_seconds}s timeout"
                ) from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "no process output").strip()
                raise MatAnyone2RuntimeError(
                    f"MatAnyone2 process failed with exit {completed.returncode}: {detail[-1000:]}"
                )
            report = _last_json_object(completed.stdout)
            alphas = self._validate_report(
                report,
                output_path=output_path,
                frames=frames,
                mask=mask,
                initial_mask_path=initial_mask_path,
                shape=shape,
                route=route,
            )
        return alphas, report

    def _validate_report(
        self,
        report: Mapping[str, Any],
        *,
        output_path: Path,
        frames: tuple[Path, ...],
        mask: np.ndarray,
        initial_mask_path: Path,
        shape: tuple[int, int],
        route: str,
    ) -> np.ndarray:
        if (
            report.get("provider") != "matanyone2"
            or report.get("source_revision") != MATANYONE2_SOURCE_REVISION
            or report.get("checkpoint_revision") != MATANYONE2_CHECKPOINT_REVISION
        ):
            raise MatAnyone2RuntimeError("MatAnyone2 source provenance mismatch")
        if (
            report.get("checkpoint_sha256") != MATANYONE2_CHECKPOINT_SHA256
            or report.get("config_sha256") != MATANYONE2_CONFIG_SHA256
            or report.get("backbone_sha256s") != MATANYONE2_BACKBONE_SHA256S
        ):
            raise MatAnyone2RuntimeError("MatAnyone2 model artifact provenance mismatch")
        if report.get("route") != route or report.get("frame_count") != len(frames):
            raise MatAnyone2RuntimeError("MatAnyone2 route capability provenance mismatch")
        if report.get("frame_sha256s") != [_sha256(path) for path in frames]:
            raise MatAnyone2RuntimeError("MatAnyone2 frame provenance mismatch")
        if report.get("initial_mask_sha256") != _sha256(initial_mask_path):
            raise MatAnyone2RuntimeError("MatAnyone2 initial-mask provenance mismatch")
        if report.get("semantic_authority") is not False:
            raise MatAnyone2RuntimeError("MatAnyone2 may not claim semantic authority")
        if report.get("deterministic") is not True or report.get("repeats") != 2:
            raise MatAnyone2RuntimeError("MatAnyone2 output lacks two-run determinism proof")
        if not output_path.is_file() or report.get("output_npz_sha256") != _sha256(output_path):
            raise MatAnyone2RuntimeError("MatAnyone2 alpha artifact hash mismatch")
        try:
            with np.load(output_path, allow_pickle=False) as archive:
                if archive.files != ["alphas"]:
                    raise MatAnyone2RuntimeError("MatAnyone2 alpha archive fields are not closed")
                alphas = np.ascontiguousarray(archive["alphas"], dtype=np.float32)
        except (OSError, ValueError) as exc:
            raise MatAnyone2RuntimeError("MatAnyone2 alpha artifact is unreadable") from exc
        expected_shape = (len(frames), *shape)
        if alphas.shape != expected_shape or report.get("alpha_shape") != list(expected_shape):
            raise MatAnyone2RuntimeError("MatAnyone2 alpha sequence geometry mismatch")
        if hashlib.sha256(alphas.tobytes()).hexdigest() != report.get("alpha_sha256"):
            raise MatAnyone2RuntimeError("MatAnyone2 alpha payload hash mismatch")
        if not np.isfinite(alphas).all() or alphas.min() < 0 or alphas.max() > 1:
            raise MatAnyone2RuntimeError("MatAnyone2 alpha sequence violates finite 0..1 contract")
        for alpha in alphas:
            thresholded = alpha >= 0.5
            if not thresholded.any() or thresholded.all():
                raise MatAnyone2RuntimeError("MatAnyone2 produced a degenerate alpha frame")
        return alphas

    def _fallback(
        self, frames: tuple[Path, ...], mask: np.ndarray, *, route: str
    ) -> AlphaMatteSequenceProposal:
        if route == STATIC_ROUTE and self.static_fallback is not None:
            proposal = self.static_fallback.refine_matte(frames[0], prior_mask=mask)
            return AlphaMatteSequenceProposal(
                proposal.alpha[None, ...],
                proposal.provider,
                proposal.prompt_fingerprint,
                route,
            )
        if route == TEMPORAL_ROUTE and self.temporal_fallback is not None:
            proposal = self.temporal_fallback.refine_sequence(frames, initial_mask=mask)
            if proposal.route != route or proposal.alphas.shape[0] != len(frames):
                raise MatAnyone2RuntimeError("MatAnyone2 temporal rollback contract mismatch")
            return proposal
        raise MatAnyone2RuntimeError(f"MatAnyone2 {route} failed and has no explicit fallback")

    def _prompt_fingerprint(
        self, frames: tuple[Path, ...], mask: np.ndarray, report: Mapping[str, Any]
    ) -> str:
        payload = {
            "provider": "matanyone2",
            "route": report["route"],
            "frame_sha256s": [_sha256(path) for path in frames],
            "initial_mask_payload_sha256": hashlib.sha256(
                mask.astype(np.uint8).tobytes()
            ).hexdigest(),
            "alpha_sha256": report["alpha_sha256"],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


__all__ = [
    "MATANYONE2_BACKBONE_SHA256S",
    "MATANYONE2_CHECKPOINT_REVISION",
    "MATANYONE2_CHECKPOINT_SHA256",
    "MATANYONE2_CONFIG_SHA256",
    "MATANYONE2_RUNTIME_FINGERPRINT",
    "MATANYONE2_SOURCE_REVISION",
    "ROUTES",
    "STATIC_ROUTE",
    "TEMPORAL_ROUTE",
    "MatAnyone2CapabilityError",
    "MatAnyone2Error",
    "MatAnyone2Provider",
    "MatAnyone2RuntimeError",
]
