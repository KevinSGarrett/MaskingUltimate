"""Provider-neutral SAM 3D Body geometry adapter with fail-closed fallback."""

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

from .adapters import provider_contract_metadata
from .contracts import BoxProposal, GeometryProvider, ProviderIdentity

ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = ROOT / "env/sam3d_body_runtime.lock.json"
REQUIRED_ARRAYS = {
    "pred_vertices": 3,
    "pred_keypoints_3d": 3,
    "pred_keypoints_2d": 2,
    "pred_cam_t": 1,
}
SAM3D_BODY_RUNTIME_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "provider",
        "source_commit",
        "source_tree_clean",
        "runtime_lock_sha256",
        "checkpoint_assets",
        "image",
        "requested_bbox_xyxy",
        "inference_type",
        "repeats",
        "deterministic",
        "geometry_output_sha256",
        "output_npz_sha256",
        "array_shapes",
        "cold_latency_ms",
        "warm_latency_ms",
        "model_load_latency_ms",
        "model_vram_bytes",
        "peak_inference_vram_bytes",
        "authority",
        "may_author_gold",
    }
)
V3_HOST_ADAPTER_LOCK_PATH = ROOT / "env/sam3d_body_runtime_v4_warmup.lock.json"
SAM3D_BODY_V3_RUNTIME_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "provider",
        "runner",
        "source_commit",
        "source_tree_clean",
        "runtime_lock_sha256",
        "checkpoint_assets",
        "image",
        "requested_bbox_xyxy",
        "inference_type",
        "source_root_import_injected",
        "warmup",
        "measured_repeats",
        "measured_outputs",
        "measured_latency_ms",
        "model_load_latency_ms",
        "model_vram_bytes",
        "peak_inference_vram_bytes",
        "deterministic",
        "measured_geometry_sha256_by_repeat",
        "repeat_comparison",
        "authority",
        "may_author_gold",
    }
)
V3_MEASURED_OUTPUT_FILENAMES = ("measured_repeat_1.npz", "measured_repeat_2.npz")


class Sam3dBodyGeometryError(ValueError):
    """SAM 3D Body output cannot be tied to the requested person and frame."""


Backend = Callable[..., Sequence[Mapping[str, Any]]]
CommandExecutor = Callable[[Sequence[str], int], subprocess.CompletedProcess[str]]
PathMapper = Callable[[Path], str]


class Sam3dBodyProcessError(RuntimeError):
    """The isolated SAM 3D Body process or its evidence failed closed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def windows_to_wsl_path(path: Path) -> str:
    """Map an exact drive-backed Windows path into WSL without using a shell."""
    resolved = Path(path).resolve(strict=False)
    drive = resolved.drive.rstrip(":")
    if len(drive) != 1 or not drive.isalpha():
        raise Sam3dBodyProcessError(f"SAM 3D Body requires a drive-backed path: {resolved}")
    suffix = resolved.as_posix()[2:].lstrip("/")
    return f"/mnt/{drive.lower()}/{suffix}"


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
    raise Sam3dBodyProcessError("SAM 3D Body process emitted no JSON report")


class Sam3dBodySubprocessBackend:
    """Execute the frozen official runner in an isolated WSL Python runtime."""

    def __init__(
        self,
        *,
        lock_path: Path = LOCK_PATH,
        runtime_python: str = "/home/kevin/mfenvs/sam3d-body-b5c765a/bin/python",
        distro: str = "Ubuntu-22.04",
        timeout_seconds: int = 600,
        executor: CommandExecutor = _run_command,
        path_mapper: PathMapper = windows_to_wsl_path,
        source_root: Path | None = None,
        checkpoint_root: Path | None = None,
    ) -> None:
        if timeout_seconds < 1:
            raise ValueError("SAM 3D Body timeout must be positive")
        self.lock_path = Path(lock_path)
        self.lock = json.loads(self.lock_path.read_text(encoding="utf-8"))
        self.identity = sam3d_body_identity(self.lock_path)
        self.source_root = (
            Path(source_root)
            if source_root is not None
            else ROOT / self.lock["source"]["local_path"]
        )
        self.checkpoint_root = (
            Path(checkpoint_root)
            if checkpoint_root is not None
            else ROOT / self.lock["checkpoint"]["local_root"]
        )
        self.runtime_python = runtime_python
        self.distro = distro
        self.timeout_seconds = timeout_seconds
        self._executor = executor
        self._path_mapper = path_mapper

    def __call__(self, image_path: Path, *, bboxes: np.ndarray) -> Sequence[Mapping[str, Any]]:
        image_path = Path(image_path)
        requested = np.asarray(bboxes, dtype=np.float32)
        if requested.shape != (1, 4) or not np.all(np.isfinite(requested)):
            raise Sam3dBodyProcessError("SAM 3D Body subprocess requires one finite xyxy box")
        checkpoint = self.checkpoint_root / "model.ckpt"
        mhr = self.checkpoint_root / "assets" / "mhr_model.pt"
        required = (image_path, self.source_root, checkpoint, mhr, self.lock_path)
        if not all(path.exists() for path in required):
            raise Sam3dBodyProcessError("one or more governed SAM 3D Body inputs are missing")
        with tempfile.TemporaryDirectory(prefix="maskfactory-sam3d-body-") as directory:
            output_path = Path(directory) / "geometry.npz"
            argv = (
                "wsl.exe",
                "-d",
                self.distro,
                "--",
                self.runtime_python,
                self._path_mapper(ROOT / "tools" / "run_sam3d_body.py"),
                "--source-root",
                self._path_mapper(self.source_root),
                "--checkpoint",
                self._path_mapper(checkpoint),
                "--mhr",
                self._path_mapper(mhr),
                "--runtime-lock",
                self._path_mapper(self.lock_path),
                "--image",
                self._path_mapper(image_path),
                "--bbox",
                *(str(float(value)) for value in requested.reshape(-1)),
                "--output",
                self._path_mapper(output_path),
                "--expected-source-commit",
                self.identity.source_commit,
                "--repeats",
                "2",
                "--inference-type",
                "full",
            )
            try:
                completed = self._executor(argv, self.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                raise Sam3dBodyProcessError(
                    f"SAM 3D Body exceeded {self.timeout_seconds}s timeout"
                ) from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "no process output").strip()
                raise Sam3dBodyProcessError(
                    f"SAM 3D Body process failed with exit {completed.returncode}: {detail[-2000:]}"
                )
            report = _last_json_object(completed.stdout)
            return (
                self._validate_report(
                    report,
                    output_path=output_path,
                    image_path=image_path,
                    requested=requested.reshape(-1),
                ),
            )

    def _validate_report(
        self,
        report: Mapping[str, Any],
        *,
        output_path: Path,
        image_path: Path,
        requested: np.ndarray,
    ) -> Mapping[str, Any]:
        if set(report) != SAM3D_BODY_RUNTIME_REPORT_KEYS:
            raise Sam3dBodyProcessError("SAM 3D Body runtime report fields are not closed")
        expected_assets = {
            asset["filename"]: asset["sha256"] for asset in self.lock["checkpoint"]["assets"]
        }
        if (
            report.get("schema_version") != "1.0.0"
            or report.get("provider") != "sam3d_body"
            or report.get("source_commit") != self.identity.source_commit
            or report.get("source_tree_clean") is not True
            or report.get("runtime_lock_sha256") != self.identity.runtime_fingerprint
            or report.get("checkpoint_assets") != expected_assets
        ):
            raise Sam3dBodyProcessError("SAM 3D Body source/runtime/checkpoint provenance mismatch")
        image = report.get("image")
        if not isinstance(image, Mapping) or image.get("sha256") != _sha256(image_path):
            raise Sam3dBodyProcessError("SAM 3D Body input image SHA-256 mismatch")
        reported_box = report.get("requested_bbox_xyxy")
        if (
            not isinstance(reported_box, list)
            or len(reported_box) != 4
            or not all(
                math.isclose(float(actual), float(expected), abs_tol=1e-6)
                for actual, expected in zip(reported_box, requested, strict=True)
            )
        ):
            raise Sam3dBodyProcessError("SAM 3D Body requested box provenance mismatch")
        if (
            report.get("repeats") != 2
            or report.get("deterministic") is not True
            or report.get("inference_type") != "full"
            or report.get("authority") != "shadow_geometry_challenger_only"
            or report.get("may_author_gold") is not False
        ):
            raise Sam3dBodyProcessError("SAM 3D Body determinism or authority evidence is invalid")
        for metric in (
            "cold_latency_ms",
            "warm_latency_ms",
            "model_load_latency_ms",
            "model_vram_bytes",
            "peak_inference_vram_bytes",
        ):
            value = report.get(metric)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise Sam3dBodyProcessError(f"SAM 3D Body metric is invalid: {metric}")
        if not output_path.is_file() or report.get("output_npz_sha256") != _sha256(output_path):
            raise Sam3dBodyProcessError("SAM 3D Body geometry artifact SHA-256 mismatch")
        try:
            with np.load(output_path, allow_pickle=False) as archive:
                expected_names = {"bbox", "focal_length", *REQUIRED_ARRAYS}
                if set(archive.files) != expected_names:
                    raise Sam3dBodyProcessError("SAM 3D Body artifact fields are not closed")
                output = {name: np.asarray(archive[name]).copy() for name in expected_names}
        except (KeyError, OSError, ValueError) as exc:
            raise Sam3dBodyProcessError("SAM 3D Body geometry artifact is unreadable") from exc
        arrays = {name: output[name] for name in REQUIRED_ARRAYS}
        if report.get("array_shapes") != {
            name: list(value.shape) for name, value in output.items()
        }:
            raise Sam3dBodyProcessError("SAM 3D Body geometry shape evidence mismatch")
        payload_hash = _geometry_sha256(output["bbox"], output["focal_length"], arrays)
        if report.get("geometry_output_sha256") != payload_hash:
            raise Sam3dBodyProcessError("SAM 3D Body geometry payload SHA-256 mismatch")
        output["_runtime_evidence"] = {
            "schema_version": report["schema_version"],
            "source_tree_clean": True,
            "repeats": 2,
            "deterministic": True,
            "inference_type": "full",
            "cold_latency_ms": float(report["cold_latency_ms"]),
            "warm_latency_ms": float(report["warm_latency_ms"]),
            "model_load_latency_ms": float(report["model_load_latency_ms"]),
            "model_vram_bytes": int(report["model_vram_bytes"]),
            "peak_inference_vram_bytes": int(report["peak_inference_vram_bytes"]),
            "geometry_output_sha256": payload_hash,
            "output_npz_sha256": str(report["output_npz_sha256"]),
            "authority": "shadow_geometry_challenger_only",
        }
        return output


class Sam3dBodyV3RunpodBackend:
    """Execute the bounded V3 warm-up contract without changing provider authority."""

    def __init__(
        self,
        *,
        lock_path: Path = V3_HOST_ADAPTER_LOCK_PATH,
        runtime_python: str = "/workspace/maskfactory/runtime_artifacts/sam3d_body_runpod_env/bin/python",
        timeout_seconds: int = 600,
        executor: CommandExecutor = _run_command,
        source_root: Path | None = None,
        checkpoint_root: Path | None = None,
    ) -> None:
        if timeout_seconds < 1:
            raise ValueError("SAM 3D Body timeout must be positive")
        self.lock_path = Path(lock_path)
        self.lock = json.loads(self.lock_path.read_text(encoding="utf-8"))
        self.identity = sam3d_body_identity(self.lock_path)
        runtime = self.lock.get("runtime")
        if not isinstance(runtime, Mapping):
            raise Sam3dBodyProcessError("SAM 3D Body V3 host-adapter runtime binding is missing")
        self.runner_path = ROOT / str(runtime.get("runner", ""))
        self.repeatability_lock_path = ROOT / str(runtime.get("repeatability_runtime_lock", ""))
        self.source_root = (
            Path(source_root)
            if source_root is not None
            else ROOT / self.lock["source"]["local_path"]
        )
        self.checkpoint_root = (
            Path(checkpoint_root)
            if checkpoint_root is not None
            else ROOT / self.lock["checkpoint"]["local_root"]
        )
        self.runtime_python = runtime_python
        self.timeout_seconds = timeout_seconds
        self._executor = executor
        self._validate_host_adapter_bindings()

    def _validate_host_adapter_bindings(self) -> None:
        runtime = self.lock["runtime"]
        authority = self.lock.get("authority")
        if (
            self.lock.get("artifact") != "sam3d_body_v3_host_adapter_activation"
            or self.lock.get("status")
            != "runtime_pass_bounded_v3_host_adapter_static_contract_pending"
            or not isinstance(authority, Mapping)
            or authority.get("lifecycle_state") != "installed_unqualified"
            or authority.get("may_author_gold") is not False
            or authority.get("may_promote_provider") is not False
            or runtime.get("runner") != "tools/run_sam3d_body_repeatability_v3.py"
            or runtime.get("runner_sha256") != _sha256(self.runner_path)
            or runtime.get("repeatability_runtime_lock_sha256")
            != _sha256(self.repeatability_lock_path)
        ):
            raise Sam3dBodyProcessError("SAM 3D Body V3 host-adapter binding mismatch")
        inherited = self.lock.get("inherits")
        if not isinstance(inherited, Mapping):
            raise Sam3dBodyProcessError("SAM 3D Body V3 host-adapter inheritance is missing")
        receipt = inherited.get("v3_runtime_receipt")
        if not isinstance(receipt, Mapping):
            raise Sam3dBodyProcessError("SAM 3D Body V3 runtime receipt binding is missing")
        receipt_path = ROOT / str(receipt.get("path", ""))
        if (
            not receipt_path.is_file()
            or receipt.get("file_sha256") != _sha256(receipt_path)
            or receipt.get("self_sha256")
            != "afe31a4a45f39791df6c7cda352d79acf103885a9221de700a69d01f9841c6ae"
        ):
            raise Sam3dBodyProcessError("SAM 3D Body V3 runtime receipt binding mismatch")

    def __call__(self, image_path: Path, *, bboxes: np.ndarray) -> Sequence[Mapping[str, Any]]:
        image_path = Path(image_path)
        requested = np.asarray(bboxes, dtype=np.float32)
        if requested.shape != (1, 4) or not np.all(np.isfinite(requested)):
            raise Sam3dBodyProcessError("SAM 3D Body V3 requires one finite xyxy box")
        checkpoint = self.checkpoint_root / "model.ckpt"
        config = self.checkpoint_root / "model_config.yaml"
        mhr = self.checkpoint_root / "assets" / "mhr_model.pt"
        required = (
            image_path,
            self.source_root,
            checkpoint,
            config,
            mhr,
            self.lock_path,
            self.repeatability_lock_path,
            self.runner_path,
        )
        if not all(path.exists() for path in required):
            raise Sam3dBodyProcessError("one or more governed SAM 3D Body V3 inputs are missing")
        with tempfile.TemporaryDirectory(prefix="maskfactory-sam3d-body-v3-") as directory:
            output_dir = Path(directory) / "repeatability"
            argv = (
                self.runtime_python,
                str(self.runner_path),
                "--source-root",
                str(self.source_root),
                "--checkpoint",
                str(checkpoint),
                "--mhr",
                str(mhr),
                "--runtime-lock",
                str(self.repeatability_lock_path),
                "--image",
                str(image_path),
                "--bbox",
                *(str(float(value)) for value in requested.reshape(-1)),
                "--output-dir",
                str(output_dir),
                "--expected-source-commit",
                self.identity.source_commit,
                "--repeats",
                "2",
                "--inference-type",
                "full",
            )
            try:
                completed = self._executor(argv, self.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                raise Sam3dBodyProcessError(
                    f"SAM 3D Body V3 exceeded {self.timeout_seconds}s timeout"
                ) from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "no process output").strip()
                raise Sam3dBodyProcessError(
                    f"SAM 3D Body V3 process failed with exit {completed.returncode}: {detail[-2000:]}"
                )
            report = _last_json_object(completed.stdout)
            return (
                self._validate_report(
                    report,
                    output_dir=output_dir,
                    image_path=image_path,
                    requested=requested.reshape(-1),
                ),
            )

    def _validate_report(
        self,
        report: Mapping[str, Any],
        *,
        output_dir: Path,
        image_path: Path,
        requested: np.ndarray,
    ) -> Mapping[str, Any]:
        if set(report) != SAM3D_BODY_V3_RUNTIME_REPORT_KEYS:
            raise Sam3dBodyProcessError("SAM 3D Body V3 runtime report fields are not closed")
        expected_assets = {
            asset["filename"]: asset["sha256"] for asset in self.lock["checkpoint"]["assets"]
        }
        if (
            report.get("schema_version") != "3.0.0"
            or report.get("provider") != "sam3d_body"
            or report.get("runner") != "sam3d_body_repeatability_v3"
            or report.get("source_commit") != self.identity.source_commit
            or report.get("source_tree_clean") is not True
            or report.get("runtime_lock_sha256") != _sha256(self.repeatability_lock_path)
            or report.get("checkpoint_assets") != expected_assets
            or report.get("source_root_import_injected") != str(self.source_root)
        ):
            raise Sam3dBodyProcessError(
                "SAM 3D Body V3 source/runtime/checkpoint provenance mismatch"
            )
        image = report.get("image")
        if not isinstance(image, Mapping) or image.get("sha256") != _sha256(image_path):
            raise Sam3dBodyProcessError("SAM 3D Body V3 input image SHA-256 mismatch")
        reported_box = report.get("requested_bbox_xyxy")
        if (
            not isinstance(reported_box, list)
            or len(reported_box) != 4
            or not all(
                math.isclose(float(actual), float(expected), abs_tol=1e-6)
                for actual, expected in zip(reported_box, requested, strict=True)
            )
        ):
            raise Sam3dBodyProcessError("SAM 3D Body V3 requested box provenance mismatch")
        if (
            report.get("inference_type") != "full"
            or report.get("measured_repeats") != 2
            or report.get("deterministic") is not True
            or report.get("authority") != "shadow_geometry_challenger_only"
            or report.get("may_author_gold") is not False
        ):
            raise Sam3dBodyProcessError(
                "SAM 3D Body V3 determinism or authority evidence is invalid"
            )
        warmup = report.get("warmup")
        if (
            not isinstance(warmup, Mapping)
            or set(warmup)
            != {"evaluated_for_repeatability", "geometry_sha256", "latency_ms", "peak_vram_bytes"}
            or warmup.get("evaluated_for_repeatability") is not False
            or not isinstance(warmup.get("geometry_sha256"), str)
            or len(str(warmup["geometry_sha256"])) != 64
        ):
            raise Sam3dBodyProcessError("SAM 3D Body V3 warm-up evidence is invalid")
        for metric in (
            warmup["latency_ms"],
            warmup["peak_vram_bytes"],
            report.get("model_load_latency_ms"),
            report.get("model_vram_bytes"),
            report.get("peak_inference_vram_bytes"),
        ):
            if not isinstance(metric, (int, float)) or not math.isfinite(metric) or metric < 0:
                raise Sam3dBodyProcessError("SAM 3D Body V3 runtime metric is invalid")
        measured_latency = report.get("measured_latency_ms")
        if (
            not isinstance(measured_latency, list)
            or len(measured_latency) != 2
            or any(
                not isinstance(metric, (int, float)) or not math.isfinite(metric) or metric < 0
                for metric in measured_latency
            )
        ):
            raise Sam3dBodyProcessError("SAM 3D Body V3 measured latency evidence is invalid")
        report_path = output_dir / "repeatability_report.json"
        if (
            not report_path.is_file()
            or json.loads(report_path.read_text(encoding="utf-8")) != report
        ):
            raise Sam3dBodyProcessError("SAM 3D Body V3 persisted report mismatch")
        outputs = report.get("measured_outputs")
        geometry_hashes = report.get("measured_geometry_sha256_by_repeat")
        if not isinstance(outputs, list) or not isinstance(geometry_hashes, list):
            raise Sam3dBodyProcessError("SAM 3D Body V3 measured output evidence is invalid")
        if len(outputs) != 2 or len(geometry_hashes) != 2:
            raise Sam3dBodyProcessError("SAM 3D Body V3 measured output count is invalid")
        loaded: list[dict[str, np.ndarray]] = []
        raw_hashes: list[str] = []
        for entry, expected_name, geometry_hash in zip(
            outputs, V3_MEASURED_OUTPUT_FILENAMES, geometry_hashes, strict=True
        ):
            if not isinstance(entry, Mapping) or set(entry) != {
                "path",
                "npz_sha256",
                "geometry_sha256",
                "array_shapes",
            }:
                raise Sam3dBodyProcessError("SAM 3D Body V3 measured output fields are not closed")
            output_path = output_dir / expected_name
            if entry.get("path") != expected_name or not output_path.is_file():
                raise Sam3dBodyProcessError("SAM 3D Body V3 measured output path mismatch")
            raw_hash = _sha256(output_path)
            if entry.get("npz_sha256") != raw_hash:
                raise Sam3dBodyProcessError("SAM 3D Body V3 measured NPZ SHA-256 mismatch")
            try:
                with np.load(output_path, allow_pickle=False) as archive:
                    expected_names = {"bbox", "focal_length", *REQUIRED_ARRAYS}
                    if set(archive.files) != expected_names:
                        raise Sam3dBodyProcessError(
                            "SAM 3D Body V3 measured artifact fields are not closed"
                        )
                    output = {name: np.asarray(archive[name]).copy() for name in expected_names}
            except (KeyError, OSError, ValueError) as exc:
                raise Sam3dBodyProcessError(
                    "SAM 3D Body V3 measured artifact is unreadable"
                ) from exc
            if entry.get("array_shapes") != {
                name: list(value.shape) for name, value in output.items()
            }:
                raise Sam3dBodyProcessError("SAM 3D Body V3 measured shape evidence mismatch")
            payload_hash = _geometry_sha256(
                output["bbox"],
                output["focal_length"],
                {name: output[name] for name in REQUIRED_ARRAYS},
            )
            if entry.get("geometry_sha256") != payload_hash or geometry_hash != payload_hash:
                raise Sam3dBodyProcessError("SAM 3D Body V3 measured geometry SHA-256 mismatch")
            loaded.append(output)
            raw_hashes.append(raw_hash)
        comparison = report.get("repeat_comparison")
        if not isinstance(comparison, Mapping) or comparison.get("all_arrays_exact") is not True:
            raise Sam3dBodyProcessError("SAM 3D Body V3 repeat comparison is invalid")
        if raw_hashes[0] != raw_hashes[1] or any(
            not np.array_equal(loaded[0][name], loaded[1][name])
            for name in {"bbox", "focal_length", *REQUIRED_ARRAYS}
        ):
            raise Sam3dBodyProcessError("SAM 3D Body V3 measured repeats are not byte-exact")
        output = loaded[0]
        output["_runtime_evidence"] = {
            "schema_version": report["schema_version"],
            "source_tree_clean": True,
            "warmup": dict(warmup),
            "measured_repeats": 2,
            "deterministic": True,
            "inference_type": "full",
            "measured_outputs": [dict(entry) for entry in outputs],
            "measured_latency_ms": [float(value) for value in measured_latency],
            "model_load_latency_ms": float(report["model_load_latency_ms"]),
            "model_vram_bytes": int(report["model_vram_bytes"]),
            "peak_inference_vram_bytes": int(report["peak_inference_vram_bytes"]),
            "geometry_output_sha256": str(geometry_hashes[0]),
            "raw_npz_sha256": raw_hashes[0],
            "repeat_comparison": {"all_arrays_exact": True},
            "authority": "shadow_geometry_challenger_only",
        }
        return output


def sam3d_body_identity(lock_path: Path = LOCK_PATH) -> ProviderIdentity:
    """Build exact provider identity from the governed runtime lock."""
    path = Path(lock_path)
    lock = json.loads(path.read_text(encoding="utf-8"))
    if (
        lock.get("provider") != "sam3d_body"
        or lock.get("checkpoint", {}).get("downloaded") is not True
        or lock.get("authority", {}).get("may_author_gold") is not False
    ):
        raise Sam3dBodyGeometryError("SAM 3D Body runtime lock is not install-ready")
    return ProviderIdentity(
        "sam3d_body",
        "geometry_provider",
        "sam3d_body",
        str(lock["source"]["commit"]),
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )


class Sam3dBodyGeometryProvider:
    """Adapt exact single-box upstream output into the GeometryProvider contract."""

    def __init__(self, backend: Backend, *, identity: ProviderIdentity | None = None) -> None:
        self.identity = identity or sam3d_body_identity()
        if self.identity.provider_key != "sam3d_body" or self.identity.role != "geometry_provider":
            raise Sam3dBodyGeometryError("SAM 3D Body provider identity is invalid")
        self._backend = backend

    def infer_geometry(self, image_path: Path, *, person_box: BoxProposal) -> Mapping[str, Any]:
        path = Path(image_path)
        if not path.is_file():
            raise Sam3dBodyGeometryError("SAM 3D Body input image is missing")
        if not person_box.instance_key:
            raise Sam3dBodyGeometryError("requested person requires an immutable instance key")
        requested = np.asarray(person_box.bbox_xyxy, dtype=np.float32)
        outputs = tuple(self._backend(path, bboxes=requested.reshape(1, 4)))
        if len(outputs) != 1 or not isinstance(outputs[0], Mapping):
            raise Sam3dBodyGeometryError(
                "explicit single-person SAM 3D Body request must return exactly one result"
            )
        raw = outputs[0]
        runtime_evidence = raw.get("_runtime_evidence")
        observed_box = _finite_array(raw.get("bbox"), "bbox", columns=4).reshape(-1)
        if observed_box.shape != (4,) or float(np.max(np.abs(observed_box - requested))) > 1.0:
            raise Sam3dBodyGeometryError("SAM 3D Body result does not own the requested person box")
        focal = np.asarray(raw.get("focal_length"), dtype=np.float64).reshape(-1)
        if focal.size not in {1, 2} or not np.all(np.isfinite(focal)) or np.any(focal <= 0):
            raise Sam3dBodyGeometryError("SAM 3D Body focal length is invalid")
        arrays: dict[str, np.ndarray] = {}
        for name, columns in REQUIRED_ARRAYS.items():
            value = _finite_array(raw.get(name), name, columns=columns)
            if name == "pred_cam_t" and value.reshape(-1).shape != (3,):
                raise Sam3dBodyGeometryError("SAM 3D Body camera translation must have 3 values")
            arrays[name] = value.copy()
        image_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        output_sha256 = _geometry_sha256(observed_box, focal, arrays)
        return {
            "provider": self.identity.provider_key,
            "person_instance_key": person_box.instance_key,
            "requested_bbox_xyxy": tuple(float(value) for value in requested),
            "observed_bbox_xyxy": tuple(float(value) for value in observed_box),
            "focal_length": tuple(float(value) for value in focal),
            **arrays,
            "coordinate_frames": {
                "input_box": "full_image_pixels_xyxy",
                "keypoints_2d": "full_image_pixels_xy_upstream_sam3d_body",
                "vertices_3d": "upstream_sam3d_body_native_camera_frame_unconverted",
                "keypoints_3d": "upstream_sam3d_body_native_camera_frame_unconverted",
                "camera_translation": "upstream_sam3d_body_native_camera_frame_unconverted",
                "implicit_axis_conversion": False,
            },
            "provenance": {
                **provider_contract_metadata(self.identity),
                "image_sha256": image_sha256,
                "selection": "explicit_single_requested_bbox",
                "person_instance_key": person_box.instance_key,
                "output_sha256": output_sha256,
                **(
                    {"runtime_evidence": dict(runtime_evidence)}
                    if isinstance(runtime_evidence, Mapping)
                    else {}
                ),
                "may_author_gold": False,
            },
        }


class GeometryProviderWithOomFallback:
    """Use the challenger only when it succeeds; fallback solely on a real OOM."""

    def __init__(self, challenger: GeometryProvider, fallback: GeometryProvider) -> None:
        self.identity = challenger.identity
        self._challenger = challenger
        self._fallback = fallback

    def infer_geometry(self, image_path: Path, *, person_box: BoxProposal) -> Mapping[str, Any]:
        try:
            result = dict(self._challenger.infer_geometry(Path(image_path), person_box=person_box))
        except Exception as exc:
            if not _is_oom(exc):
                raise
            result = dict(self._fallback.infer_geometry(Path(image_path), person_box=person_box))
            result["routing"] = {
                "attempted_provider": self._challenger.identity.provider_key,
                "used_provider": self._fallback.identity.provider_key,
                "fallback_reason": "out_of_memory",
                "fallback_exception_type": type(exc).__name__,
                "production_route_changed": False,
            }
            return result
        result["routing"] = {
            "attempted_provider": self._challenger.identity.provider_key,
            "used_provider": self._challenger.identity.provider_key,
            "fallback_reason": None,
            "production_route_changed": False,
        }
        return result


def _finite_array(value: Any, name: str, *, columns: int) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise Sam3dBodyGeometryError(f"SAM 3D Body {name} is not numeric") from exc
    if array.size == 0 or not np.all(np.isfinite(array)):
        raise Sam3dBodyGeometryError(f"SAM 3D Body {name} is empty or non-finite")
    if columns == 1:
        return array
    if array.ndim == 1:
        if array.shape != (columns,):
            raise Sam3dBodyGeometryError(f"SAM 3D Body {name} has invalid dimensions")
    elif array.ndim != 2 or array.shape[1] < columns:
        raise Sam3dBodyGeometryError(f"SAM 3D Body {name} has invalid dimensions")
    return array


def _geometry_sha256(bbox: np.ndarray, focal: np.ndarray, arrays: Mapping[str, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for name, value in (("bbox", bbox), ("focal_length", focal), *sorted(arrays.items())):
        array = np.ascontiguousarray(value, dtype=np.float64)
        digest.update(name.encode("utf-8"))
        digest.update(json.dumps(list(array.shape), separators=(",", ":")).encode("utf-8"))
        digest.update(array.tobytes())
    return digest.hexdigest()


def _is_oom(exc: Exception) -> bool:
    if isinstance(exc, MemoryError) or type(exc).__name__ == "OutOfMemoryError":
        return True
    if isinstance(exc, RuntimeError):
        message = str(exc).lower()
        return "out of memory" in message and ("cuda" in message or "gpu" in message)
    return False


__all__ = [
    "GeometryProviderWithOomFallback",
    "Sam3dBodyGeometryError",
    "Sam3dBodyGeometryProvider",
    "Sam3dBodyProcessError",
    "Sam3dBodySubprocessBackend",
    "Sam3dBodyV3RunpodBackend",
    "sam3d_body_identity",
    "windows_to_wsl_path",
]
