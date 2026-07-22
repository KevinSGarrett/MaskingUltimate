"""Exact host contract for the official SAM 3.1 Object Multiplex smoke."""

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

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LOCK = ROOT / "env/sam31_runtime.lock.json"
DEFAULT_IMAGE = ROOT / "qa/fixtures/smoke/ultralytics_bus_adults.jpg"
ARTIFACT_FIELDS = ("masks", "object_ids", "probabilities", "boxes_xywh")
REPORT_FIELDS = frozenset(
    {
        "schema_version",
        "provider",
        "source_commit",
        "source_tree_clean",
        "runtime_lock_sha256",
        "requirements_lock_sha256",
        "checkpoint_sha256",
        "image_sha256",
        "builder",
        "version",
        "adaptation",
        "prompt",
        "repeats",
        "deterministic",
        "mask_payload_sha256",
        "output_npz_sha256",
        "artifact_shapes",
        "model_load_latency_ms",
        "cold_latency_ms",
        "warm_latency_ms",
        "model_vram_bytes",
        "peak_inference_vram_bytes",
        "authority",
        "may_author_gold",
    }
)

CommandExecutor = Callable[[Sequence[str], int], subprocess.CompletedProcess[str]]
PathMapper = Callable[[Path], str]


class Sam31MultiplexError(RuntimeError):
    """The isolated SAM 3.1 multiplex smoke or its evidence failed closed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def multiplex_payload_sha256(arrays: Mapping[str, np.ndarray]) -> str:
    """Hash the exact typed/shape-bound single-frame multiplex output."""
    digest = hashlib.sha256()
    for name in ARTIFACT_FIELDS:
        value = np.ascontiguousarray(arrays[name])
        digest.update(name.encode("utf-8"))
        digest.update(value.dtype.str.encode("ascii"))
        digest.update(json.dumps(list(value.shape), separators=(",", ":")).encode("utf-8"))
        digest.update(value.tobytes())
    return digest.hexdigest()


def windows_to_wsl_path(path: Path) -> str:
    resolved = Path(path).resolve(strict=False)
    drive = resolved.drive.rstrip(":")
    if len(drive) != 1 or not drive.isalpha():
        raise Sam31MultiplexError(f"SAM 3.1 requires a drive-backed path: {resolved}")
    return f"/mnt/{drive.lower()}/{resolved.as_posix()[2:].lstrip('/')}"


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
    raise Sam31MultiplexError("SAM 3.1 process emitted no JSON report")


class Sam31MultiplexSmokeRunner:
    """Run and verify the official checkpoint through its correct multiplex builder."""

    def __init__(
        self,
        *,
        lock_path: Path = DEFAULT_LOCK,
        distro: str = "Ubuntu-22.04",
        timeout_seconds: int = 900,
        executor: CommandExecutor = _run_command,
        path_mapper: PathMapper = windows_to_wsl_path,
    ) -> None:
        if timeout_seconds < 1:
            raise ValueError("SAM 3.1 timeout must be positive")
        self.lock_path = Path(lock_path)
        self.lock = json.loads(self.lock_path.read_text(encoding="utf-8"))
        if (
            self.lock.get("provider") != "sam3_1"
            or self.lock["checkpoint"].get("downloaded") is not True
        ):
            raise Sam31MultiplexError("SAM 3.1 runtime lock is not checkpoint-ready")
        self.source_root = ROOT / self.lock["source"]["local_path"]
        self.checkpoint = ROOT / self.lock["checkpoint"]["local_path"]
        self.requirements_lock = ROOT / self.lock["runtime"]["requirements_lock"]
        self.runtime_python = f"{self.lock['runtime']['environment_path']}/bin/python"
        self.distro = distro
        self.timeout_seconds = timeout_seconds
        self._executor = executor
        self._path_mapper = path_mapper

    def run(self, image_path: Path = DEFAULT_IMAGE) -> Mapping[str, Any]:
        image_path = Path(image_path)
        required = (
            image_path,
            self.source_root,
            self.checkpoint,
            self.requirements_lock,
            self.lock_path,
        )
        if not all(path.exists() for path in required):
            raise Sam31MultiplexError("one or more governed SAM 3.1 smoke inputs are missing")
        with tempfile.TemporaryDirectory(prefix="maskfactory-sam31-multiplex-") as directory:
            output_path = Path(directory) / "sam31_multiplex_smoke.npz"
            argv = (
                "wsl.exe",
                "-d",
                self.distro,
                "--",
                self.runtime_python,
                self._path_mapper(ROOT / "tools/smoke_sam31_multiplex_wsl.py"),
                "--source-root",
                self._path_mapper(self.source_root),
                "--checkpoint",
                self._path_mapper(self.checkpoint),
                "--runtime-lock",
                self._path_mapper(self.lock_path),
                "--requirements-lock",
                self._path_mapper(self.requirements_lock),
                "--image",
                self._path_mapper(image_path),
                "--output",
                self._path_mapper(output_path),
                "--expected-source-commit",
                self.lock["source"]["commit"],
                "--repeats",
                "2",
            )
            try:
                completed = self._executor(argv, self.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                raise Sam31MultiplexError(
                    f"SAM 3.1 multiplex smoke exceeded {self.timeout_seconds}s timeout"
                ) from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "no process output").strip()
                raise Sam31MultiplexError(
                    f"SAM 3.1 multiplex process failed with exit {completed.returncode}: "
                    f"{detail[-2000:]}"
                )
            report = _last_json_object(completed.stdout)
            return self._validate(report, output_path=output_path, image_path=image_path)

    def _validate(
        self, report: Mapping[str, Any], *, output_path: Path, image_path: Path
    ) -> Mapping[str, Any]:
        if set(report) != REPORT_FIELDS:
            raise Sam31MultiplexError("SAM 3.1 runtime report fields are not closed")
        expected = {
            "schema_version": "1.0.0",
            "provider": "sam3_1",
            "source_commit": self.lock["source"]["commit"],
            "source_tree_clean": True,
            "runtime_lock_sha256": _sha256(self.lock_path),
            "requirements_lock_sha256": self.lock["runtime"]["requirements_lock_sha256"],
            "checkpoint_sha256": self.lock["checkpoint"]["sha256"],
            "image_sha256": _sha256(image_path),
            "builder": "build_sam3_predictor",
            "version": "sam3.1",
            "adaptation": "single_frame_directory_via_object_multiplex",
            "prompt": {"type": "text", "concept": "person"},
            "repeats": 2,
            "deterministic": True,
            "authority": "runtime_smoke_only_no_candidate_serving_or_gold_authority",
            "may_author_gold": False,
        }
        if any(report.get(key) != value for key, value in expected.items()):
            raise Sam31MultiplexError("SAM 3.1 runtime identity or authority evidence drifted")
        for metric in (
            "model_load_latency_ms",
            "cold_latency_ms",
            "warm_latency_ms",
            "model_vram_bytes",
            "peak_inference_vram_bytes",
        ):
            value = report.get(metric)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise Sam31MultiplexError(f"SAM 3.1 runtime metric is invalid: {metric}")
        if not output_path.is_file() or report["output_npz_sha256"] != _sha256(output_path):
            raise Sam31MultiplexError("SAM 3.1 smoke artifact SHA-256 mismatch")
        try:
            with np.load(output_path, allow_pickle=False) as archive:
                if set(archive.files) != set(ARTIFACT_FIELDS):
                    raise Sam31MultiplexError("SAM 3.1 smoke artifact fields are not closed")
                arrays = {name: np.asarray(archive[name]).copy() for name in ARTIFACT_FIELDS}
        except (KeyError, OSError, ValueError) as exc:
            raise Sam31MultiplexError("SAM 3.1 smoke artifact is unreadable") from exc
        masks = arrays["masks"]
        object_ids = arrays["object_ids"]
        probabilities = arrays["probabilities"]
        boxes = arrays["boxes_xywh"]
        if (
            masks.dtype != np.bool_
            or masks.ndim != 3
            or masks.shape[0] < 1
            or not masks.any(axis=(1, 2)).all()
            or object_ids.shape != (masks.shape[0],)
            or len(np.unique(object_ids)) != masks.shape[0]
            or probabilities.shape != (masks.shape[0],)
            or boxes.shape != (masks.shape[0], 4)
            or not np.isfinite(probabilities).all()
            or not np.isfinite(boxes).all()
        ):
            raise Sam31MultiplexError("SAM 3.1 smoke artifact geometry is invalid")
        if report["artifact_shapes"] != {name: list(value.shape) for name, value in arrays.items()}:
            raise Sam31MultiplexError("SAM 3.1 smoke shape evidence mismatch")
        payload_hash = multiplex_payload_sha256(arrays)
        if report["mask_payload_sha256"] != payload_hash:
            raise Sam31MultiplexError("SAM 3.1 smoke payload SHA-256 mismatch")
        return {
            **dict(report),
            "object_count": int(masks.shape[0]),
            "mask_pixel_count": int(masks.sum()),
        }


__all__ = [
    "Sam31MultiplexError",
    "Sam31MultiplexSmokeRunner",
    "multiplex_payload_sha256",
    "windows_to_wsl_path",
]
