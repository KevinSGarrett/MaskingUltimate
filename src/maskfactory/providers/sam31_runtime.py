"""Official SAM 3.1 Object Multiplex discovery/refinement subprocess adapters."""

from __future__ import annotations

import hashlib
import json
import math
import queue
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .sam31_exemplars import Sam31VisualExemplarError, load_sam31_visual_exemplar
from .sam31_multiplex import windows_to_wsl_path
from .sam31_shadow import (
    DEFAULT_RUNTIME_LOCK,
    Sam31ConceptDetector,
    Sam31InteractiveSegmenter,
)

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_FIELDS = (
    "masks",
    "object_ids",
    "probabilities",
    "boxes_xywh",
    "concept_indices",
)
REPORT_FIELDS = frozenset(
    {
        "schema_version",
        "provider",
        "operation",
        "source_commit",
        "source_tree_clean",
        "runtime_lock_sha256",
        "requirements_lock_sha256",
        "checkpoint_sha256",
        "request_sha256",
        "image_rgb_sha256",
        "encoded_frame_sha256",
        "prompt_npz_sha256",
        "builder",
        "version",
        "result_count",
        "artifact_shapes",
        "payload_sha256",
        "output_npz_sha256",
        "model_load_latency_ms",
        "inference_latency_ms",
        "model_vram_bytes",
        "peak_inference_vram_bytes",
        "prompt_translation",
        "authority",
        "may_author_gold",
    }
)
AUTHORITY = "official_sam31_runtime_draft_candidates_only_no_gold_or_active_map_authority"

CommandExecutor = Callable[[Sequence[str], int], subprocess.CompletedProcess[str]]
PathMapper = Callable[[Path], str]
RESIDENT_SCHEMA_VERSION = "maskfactory.sam31_resident_protocol.v1"


class Sam31RuntimeError(RuntimeError):
    """The official SAM 3.1 runtime request or its evidence failed closed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _array_sha256(value: np.ndarray) -> str:
    array = np.ascontiguousarray(value)
    digest = hashlib.sha256()
    digest.update(array.dtype.str.encode("ascii"))
    digest.update(json.dumps(list(array.shape), separators=(",", ":")).encode("utf-8"))
    digest.update(array.tobytes())
    return digest.hexdigest()


def sam31_runtime_payload_sha256(arrays: Mapping[str, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for name in ARTIFACT_FIELDS:
        value = np.ascontiguousarray(arrays[name])
        digest.update(name.encode("utf-8"))
        digest.update(value.dtype.str.encode("ascii"))
        digest.update(json.dumps(list(value.shape), separators=(",", ":")).encode("utf-8"))
        digest.update(value.tobytes())
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


class ResidentSam31CommandExecutor:
    """Translate ordinary runtime argv into one persistent native SAM3.1 process."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._common: tuple[str, ...] | None = None
        self._stdout: queue.Queue[str] = queue.Queue()
        self._stderr: list[str] = []
        self._ready: dict[str, Any] | None = None
        self._summary: dict[str, Any] | None = None
        self._responses: list[dict[str, Any]] = []

    @staticmethod
    def _options(argv: Sequence[str]) -> tuple[str, dict[str, str]]:
        if tuple(argv[:4]) != ("wsl.exe", "-d", "Ubuntu-22.04", "--") or len(argv) < 7:
            raise Sam31RuntimeError("resident SAM 3.1 launcher prefix is invalid")
        python_executable = str(argv[4])
        if Path(str(argv[5])).name != "run_sam31_runtime.py":
            raise Sam31RuntimeError("resident SAM 3.1 runner identity is invalid")
        values: dict[str, str] = {}
        tail = list(argv[6:])
        if len(tail) % 2:
            raise Sam31RuntimeError("resident SAM 3.1 argv is malformed")
        for index in range(0, len(tail), 2):
            key, value = str(tail[index]), str(tail[index + 1])
            if not key.startswith("--") or key in values:
                raise Sam31RuntimeError("resident SAM 3.1 argv options are invalid")
            values[key] = value
        expected = {
            "--source-root",
            "--checkpoint",
            "--runtime-lock",
            "--requirements-lock",
            "--frame-dir",
            "--request",
            "--prompt-npz",
            "--output",
            "--expected-source-commit",
        }
        if set(values) != expected:
            raise Sam31RuntimeError("resident SAM 3.1 argv fields drifted")
        return python_executable, values

    @staticmethod
    def _reader(stream: Any, sink: Any) -> None:
        for line in stream:
            sink(line.rstrip("\r\n"))

    def _wait_message(self, timeout_seconds: int) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Sam31RuntimeError("resident SAM 3.1 response timed out")
            try:
                line = self._stdout.get(timeout=remaining)
            except queue.Empty as exc:
                raise Sam31RuntimeError("resident SAM 3.1 response timed out") from exc
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value

    def _start(
        self,
        *,
        python_executable: str,
        common: tuple[str, ...],
        timeout_seconds: int,
    ) -> None:
        server_path = ROOT / "tools" / "run_sam31_resident_runtime.py"
        command = (
            python_executable,
            str(server_path),
            "--source-root",
            common[0],
            "--checkpoint",
            common[1],
            "--runtime-lock",
            common[2],
            "--requirements-lock",
            common[3],
            "--expected-source-commit",
            common[4],
        )
        self._process = subprocess.Popen(  # noqa: S603 - exact governed argv
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        threading.Thread(
            target=self._reader,
            args=(self._process.stdout, self._stdout.put),
            daemon=True,
        ).start()
        threading.Thread(
            target=self._reader,
            args=(self._process.stderr, self._stderr.append),
            daemon=True,
        ).start()
        ready = self._wait_message(timeout_seconds)
        if (
            ready.get("schema_version") != RESIDENT_SCHEMA_VERSION
            or ready.get("status") != "ready"
            or not isinstance(ready.get("process_id"), int)
            or not isinstance(ready.get("common_identity_sha256"), str)
        ):
            self._terminate()
            raise Sam31RuntimeError("resident SAM 3.1 ready identity is invalid")
        self._common = common
        self._ready = ready

    def __call__(
        self, argv: Sequence[str], timeout_seconds: int
    ) -> subprocess.CompletedProcess[str]:
        try:
            python_executable, values = self._options(argv)
            common = (
                values["--source-root"],
                values["--checkpoint"],
                values["--runtime-lock"],
                values["--requirements-lock"],
                values["--expected-source-commit"],
            )
            if self._process is None:
                self._start(
                    python_executable=python_executable,
                    common=common,
                    timeout_seconds=timeout_seconds,
                )
            if self._common != common or self._process is None or self._process.poll() is not None:
                raise Sam31RuntimeError("resident SAM 3.1 process identity drifted or exited")
            request_id = uuid.uuid4().hex
            command = {
                "schema_version": RESIDENT_SCHEMA_VERSION,
                "operation": "execute",
                "request_id": request_id,
                "frame_dir": values["--frame-dir"],
                "request": values["--request"],
                "prompt_npz": values["--prompt-npz"],
                "output": values["--output"],
            }
            assert self._process.stdin is not None
            self._process.stdin.write(
                json.dumps(command, sort_keys=True, separators=(",", ":")) + "\n"
            )
            self._process.stdin.flush()
            response = self._wait_message(timeout_seconds)
            if (
                response.get("schema_version") != RESIDENT_SCHEMA_VERSION
                or response.get("request_id") != request_id
                or response.get("process_id") != self._ready["process_id"]
            ):
                raise Sam31RuntimeError("resident SAM 3.1 response identity drifted")
            self._responses.append(response)
            if response.get("status") != "complete" or not isinstance(response.get("report"), dict):
                detail = f"{response.get('error_type', 'RuntimeError')}:{response.get('error', '')}"
                return subprocess.CompletedProcess(list(argv), 1, "", detail)
            return subprocess.CompletedProcess(
                list(argv),
                0,
                json.dumps(response["report"], sort_keys=True, separators=(",", ":")),
                "\n".join(self._stderr),
            )
        except Exception as exc:
            return subprocess.CompletedProcess(list(argv), 1, "", f"{type(exc).__name__}:{exc}")

    def _terminate(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=10)

    def close(self, *, timeout_seconds: int = 60) -> dict[str, Any]:
        if self._summary is not None:
            return self.evidence()
        if self._process is None:
            self._summary = {
                "schema_version": RESIDENT_SCHEMA_VERSION,
                "status": "not_started",
                "request_count": 0,
                "successful_request_count": 0,
                "failed_request_count": 0,
                "model_load_count": 0,
                "resident_model_count": 0,
            }
            return self.evidence()
        if self._process.poll() is None:
            request_id = uuid.uuid4().hex
            command = {
                "schema_version": RESIDENT_SCHEMA_VERSION,
                "operation": "shutdown",
                "request_id": request_id,
                "frame_dir": None,
                "request": None,
                "prompt_npz": None,
                "output": None,
            }
            assert self._process.stdin is not None
            self._process.stdin.write(
                json.dumps(command, sort_keys=True, separators=(",", ":")) + "\n"
            )
            self._process.stdin.flush()
            summary = self._wait_message(timeout_seconds)
            summary_body = {key: value for key, value in summary.items() if key != "self_sha256"}
            expected_summary_sha256 = hashlib.sha256(
                json.dumps(summary_body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if (
                summary.get("schema_version") != RESIDENT_SCHEMA_VERSION
                or summary.get("status") != "stopped"
                or summary.get("request_id") != request_id
                or summary.get("process_id") != self._ready["process_id"]
                or summary.get("request_count") != len(self._responses)
                or summary.get("successful_request_count")
                != sum(response.get("status") == "complete" for response in self._responses)
                or summary.get("failed_request_count")
                != sum(response.get("status") == "error" for response in self._responses)
                or (
                    summary.get("successful_request_count", 0) > 0
                    and summary.get("model_load_count") != 1
                )
                or summary.get("self_sha256") != expected_summary_sha256
            ):
                self._terminate()
                raise Sam31RuntimeError("resident SAM 3.1 shutdown evidence is invalid")
            self._summary = summary
            self._process.wait(timeout=timeout_seconds)
        else:
            raise Sam31RuntimeError("resident SAM 3.1 process exited before shutdown")
        return self.evidence()

    def evidence(self) -> dict[str, Any]:
        body = {
            "schema_version": "maskfactory.sam31_resident_evidence.v1",
            "ready": self._ready,
            "summary": self._summary,
            "response_count": len(self._responses),
            "response_sequences": [
                response.get("request_sequence")
                for response in self._responses
                if response.get("status") == "complete"
            ],
            "stderr_tail": "\n".join(self._stderr)[-2000:],
            "authority": AUTHORITY,
            "production_mask_authority": False,
        }
        return {
            **body,
            "self_sha256": hashlib.sha256(
                json.dumps(
                    body,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest(),
        }


def _last_json(stdout: str) -> Mapping[str, Any]:
    for line in reversed(stdout.splitlines()):
        if not line.lstrip().startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            return value
    raise Sam31RuntimeError("official SAM 3.1 process emitted no JSON report")


@dataclass(frozen=True)
class Sam31RuntimeImage:
    """Immutable host-side RGB payload used by the provider-neutral embed/refine API."""

    rgb: np.ndarray
    rgb_sha256: str


class OfficialSam31Runtime:
    """Run exact official text discovery and interactive refinement in isolated WSL."""

    def __init__(
        self,
        *,
        lock_path: Path = DEFAULT_RUNTIME_LOCK,
        distro: str = "Ubuntu-22.04",
        timeout_seconds: int = 1200,
        executor: CommandExecutor = _run_command,
        path_mapper: PathMapper = windows_to_wsl_path,
    ) -> None:
        if timeout_seconds < 1:
            raise ValueError("SAM 3.1 runtime timeout must be positive")
        self.lock_path = Path(lock_path)
        self.lock = json.loads(self.lock_path.read_text(encoding="utf-8"))
        if (
            self.lock.get("provider") != "sam3_1"
            or self.lock["checkpoint"].get("downloaded") is not True
        ):
            raise Sam31RuntimeError("official SAM 3.1 runtime lock is not checkpoint-ready")
        self.source_root = ROOT / self.lock["source"]["local_path"]
        self.checkpoint = ROOT / self.lock["checkpoint"]["local_path"]
        self.requirements_lock = ROOT / self.lock["runtime"]["requirements_lock"]
        self.runtime_python = f"{self.lock['runtime']['environment_path']}/bin/python"
        self.distro = distro
        self.timeout_seconds = timeout_seconds
        self._executor = executor
        self._path_mapper = path_mapper

    def embed(self, image: np.ndarray) -> Sam31RuntimeImage:
        value = np.asarray(image)
        if value.dtype != np.uint8 or value.ndim != 3 or value.shape[2] != 3:
            raise Sam31RuntimeError("official SAM 3.1 embedding requires uint8 RGB")
        copied = np.ascontiguousarray(value).copy()
        copied.setflags(write=False)
        return Sam31RuntimeImage(copied, _array_sha256(copied))

    def discover(
        self,
        image_path: Path,
        *,
        concepts: Sequence[str],
        exemplars: Sequence[Path] = (),
    ) -> Sequence[Mapping[str, Any]]:
        normalized = tuple(str(value).strip() for value in concepts)
        if not normalized or any(not value for value in normalized):
            raise Sam31RuntimeError("official SAM 3.1 text concepts must be nonempty")
        path = Path(image_path)
        with Image.open(path) as image:
            rgb = np.asarray(image.convert("RGB"))
        try:
            visual_exemplars = [
                load_sam31_visual_exemplar(exemplar, source_image=path) for exemplar in exemplars
            ]
        except Sam31VisualExemplarError as exc:
            raise Sam31RuntimeError(str(exc)) from exc
        exemplar_identities = [value["manifest_sha256"] for value in visual_exemplars]
        if len(exemplar_identities) != len(set(exemplar_identities)):
            raise Sam31RuntimeError("official SAM 3.1 visual exemplars must be unique")
        request = {
            "schema_version": "1.0.0",
            "operation": "discover",
            "concepts": list(normalized),
            "prompt": None,
            "visual_exemplars": visual_exemplars,
            "image_rgb_sha256": _array_sha256(rgb),
            "authority": AUTHORITY,
            "may_author_gold": False,
        }
        arrays = self._execute(rgb, request=request, mask_prompt=None)
        rows = []
        for index in range(arrays["masks"].shape[0]):
            concept_index = int(arrays["concept_indices"][index])
            if not 0 <= concept_index < len(normalized):
                raise Sam31RuntimeError("official SAM 3.1 concept index is outside the request")
            mask = arrays["masks"][index]
            instance_key = hashlib.sha256(
                (
                    f"{concept_index}:{int(arrays['object_ids'][index])}:" f"{_array_sha256(mask)}"
                ).encode("utf-8")
            ).hexdigest()[:24]
            rows.append(
                {
                    "kind": "mask",
                    "confidence": float(arrays["probabilities"][index]),
                    "label": normalized[concept_index],
                    "instance_key": instance_key,
                    "value": mask,
                }
            )
        return tuple(rows)

    def refine(
        self, embedding: Any, *, prompt: Mapping[str, Any]
    ) -> Sequence[tuple[np.ndarray, float]]:
        if not isinstance(embedding, Sam31RuntimeImage):
            raise Sam31RuntimeError("official SAM 3.1 refinement embedding is foreign")
        if set(prompt) not in (
            {"positive_points", "negative_points", "box_xyxy", "mask_prompt_sha256"},
            {
                "positive_points",
                "negative_points",
                "box_xyxy",
                "mask_prompt_sha256",
                "mask_prompt",
            },
        ):
            raise Sam31RuntimeError("official SAM 3.1 refinement prompt fields drifted")
        mask_prompt = prompt.get("mask_prompt")
        if mask_prompt is not None:
            mask_prompt = np.asarray(mask_prompt)
            if (
                mask_prompt.dtype != np.bool_
                or mask_prompt.shape != embedding.rgb.shape[:2]
                or not mask_prompt.any()
            ):
                raise Sam31RuntimeError("official SAM 3.1 mask prior is invalid")
            if (
                prompt["mask_prompt_sha256"]
                != hashlib.sha256(np.ascontiguousarray(mask_prompt).tobytes()).hexdigest()
            ):
                raise Sam31RuntimeError("official SAM 3.1 mask-prior hash is stale")
        request = {
            "schema_version": "1.0.0",
            "operation": "refine",
            "concepts": [],
            "prompt": {
                "positive_points": [list(value) for value in prompt["positive_points"]],
                "negative_points": [list(value) for value in prompt["negative_points"]],
                "box_xyxy": list(prompt["box_xyxy"]) if prompt["box_xyxy"] is not None else None,
                "mask_prompt_sha256": prompt["mask_prompt_sha256"],
            },
            "visual_exemplars": [],
            "image_rgb_sha256": embedding.rgb_sha256,
            "authority": AUTHORITY,
            "may_author_gold": False,
        }
        arrays = self._execute(embedding.rgb, request=request, mask_prompt=mask_prompt)
        return tuple(
            (arrays["masks"][index], float(arrays["probabilities"][index]))
            for index in range(arrays["masks"].shape[0])
        )

    def _execute(
        self,
        rgb: np.ndarray,
        *,
        request: Mapping[str, Any],
        mask_prompt: np.ndarray | None,
    ) -> dict[str, np.ndarray]:
        required = (
            self.source_root,
            self.checkpoint,
            self.requirements_lock,
            self.lock_path,
            ROOT / "tools/run_sam31_runtime.py",
            ROOT / "tools/run_sam31_resident_runtime.py",
        )
        if not all(path.exists() for path in required):
            raise Sam31RuntimeError("one or more governed SAM 3.1 runtime inputs are missing")
        with tempfile.TemporaryDirectory(prefix="maskfactory-sam31-runtime-") as directory:
            root = Path(directory)
            frames = root / "frames"
            frames.mkdir()
            frame_path = frames / "00000.jpg"
            Image.fromarray(np.asarray(rgb), "RGB").save(
                frame_path, format="JPEG", quality=100, subsampling=0
            )
            request_path = root / "request.json"
            request_path.write_text(
                json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            prompt_path = root / "prompt.npz"
            np.savez_compressed(
                prompt_path,
                mask_prompt=(
                    np.asarray(mask_prompt, dtype=bool)
                    if mask_prompt is not None
                    else np.zeros((0, 0), dtype=bool)
                ),
            )
            output_path = root / "result.npz"
            argv = (
                "wsl.exe",
                "-d",
                self.distro,
                "--",
                self.runtime_python,
                self._path_mapper(ROOT / "tools/run_sam31_runtime.py"),
                "--source-root",
                self._path_mapper(self.source_root),
                "--checkpoint",
                self._path_mapper(self.checkpoint),
                "--runtime-lock",
                self._path_mapper(self.lock_path),
                "--requirements-lock",
                self._path_mapper(self.requirements_lock),
                "--frame-dir",
                self._path_mapper(frames),
                "--request",
                self._path_mapper(request_path),
                "--prompt-npz",
                self._path_mapper(prompt_path),
                "--output",
                self._path_mapper(output_path),
                "--expected-source-commit",
                self.lock["source"]["commit"],
            )
            try:
                completed = self._executor(argv, self.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                raise Sam31RuntimeError(
                    f"official SAM 3.1 runtime exceeded {self.timeout_seconds}s timeout"
                ) from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "no process output").strip()
                raise Sam31RuntimeError(
                    f"official SAM 3.1 process failed with exit {completed.returncode}: "
                    f"{detail[-3000:]}"
                )
            return self._validate(
                _last_json(completed.stdout),
                request=request,
                image_shape=np.asarray(rgb).shape[:2],
                request_path=request_path,
                prompt_path=prompt_path,
                frame_path=frame_path,
                output_path=output_path,
            )

    def _validate(
        self,
        report: Mapping[str, Any],
        *,
        request: Mapping[str, Any],
        image_shape: tuple[int, int],
        request_path: Path,
        prompt_path: Path,
        frame_path: Path,
        output_path: Path,
    ) -> dict[str, np.ndarray]:
        if set(report) != REPORT_FIELDS:
            raise Sam31RuntimeError("official SAM 3.1 runtime report fields are not closed")
        expected = {
            "schema_version": "1.0.0",
            "provider": "sam3_1",
            "operation": request["operation"],
            "source_commit": self.lock["source"]["commit"],
            "source_tree_clean": True,
            "runtime_lock_sha256": _sha256(self.lock_path),
            "requirements_lock_sha256": self.lock["runtime"]["requirements_lock_sha256"],
            "checkpoint_sha256": self.lock["checkpoint"]["sha256"],
            "request_sha256": _sha256(request_path),
            "image_rgb_sha256": request["image_rgb_sha256"],
            "encoded_frame_sha256": _sha256(frame_path),
            "prompt_npz_sha256": _sha256(prompt_path),
            "builder": "build_sam3_predictor",
            "version": "sam3.1",
            "authority": AUTHORITY,
            "may_author_gold": False,
        }
        if any(report.get(key) != value for key, value in expected.items()):
            raise Sam31RuntimeError("official SAM 3.1 runtime identity or authority drifted")
        for metric in (
            "model_load_latency_ms",
            "inference_latency_ms",
            "model_vram_bytes",
            "peak_inference_vram_bytes",
        ):
            value = report.get(metric)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise Sam31RuntimeError(f"official SAM 3.1 runtime metric is invalid: {metric}")
        expected_translation = "text_prompt_exact"
        if request["operation"] == "discover" and request["visual_exemplars"]:
            expected_translation = "text_plus_same_image_visual_box_exemplars_exact"
        elif request["operation"] == "refine":
            expected_translation = (
                "native_visual_box_prompt_exact_visual_text_center_point_postcondition_only"
                if request["prompt"]["box_xyxy"] is not None
                else "mask_prior_to_native_visual_box_prompt_exact"
            )
        if report["prompt_translation"] != expected_translation:
            raise Sam31RuntimeError("official SAM 3.1 prompt translation is invalid")
        if not output_path.is_file() or report["output_npz_sha256"] != _sha256(output_path):
            raise Sam31RuntimeError("official SAM 3.1 result artifact SHA-256 mismatch")
        try:
            with np.load(output_path, allow_pickle=False) as archive:
                if set(archive.files) != set(ARTIFACT_FIELDS):
                    raise Sam31RuntimeError("official SAM 3.1 result fields are not closed")
                arrays = {name: np.asarray(archive[name]).copy() for name in ARTIFACT_FIELDS}
        except (KeyError, OSError, ValueError) as exc:
            raise Sam31RuntimeError("official SAM 3.1 result artifact is unreadable") from exc
        masks = arrays["masks"]
        count = masks.shape[0] if masks.ndim == 3 else -1
        if (
            masks.dtype != np.bool_
            or masks.ndim != 3
            or masks.shape[1:] != image_shape
            or (count and not masks.any(axis=(1, 2)).all())
            or arrays["object_ids"].shape != (count,)
            or arrays["object_ids"].dtype != np.int64
            or arrays["probabilities"].shape != (count,)
            or arrays["probabilities"].dtype != np.float32
            or arrays["boxes_xywh"].shape != (count, 4)
            or arrays["boxes_xywh"].dtype != np.float32
            or arrays["concept_indices"].shape != (count,)
            or arrays["concept_indices"].dtype != np.int64
            or not np.isfinite(arrays["probabilities"]).all()
            or not np.isfinite(arrays["boxes_xywh"]).all()
            or np.any(arrays["probabilities"] < 0)
            or np.any(arrays["probabilities"] > 1)
            or np.any(arrays["boxes_xywh"] < 0)
            or np.any(arrays["boxes_xywh"] > 1)
            or (count and np.any(arrays["boxes_xywh"][:, 2:] <= 0))
        ):
            raise Sam31RuntimeError("official SAM 3.1 result geometry is invalid")
        if request["operation"] == "refine" and count < 1:
            raise Sam31RuntimeError("official SAM 3.1 refinement returned no result")
        if report["result_count"] != count:
            raise Sam31RuntimeError("official SAM 3.1 result count is stale")
        if report["artifact_shapes"] != {name: list(value.shape) for name, value in arrays.items()}:
            raise Sam31RuntimeError("official SAM 3.1 result shape evidence mismatch")
        if report["payload_sha256"] != sam31_runtime_payload_sha256(arrays):
            raise Sam31RuntimeError("official SAM 3.1 result payload SHA-256 mismatch")
        return arrays


def load_official_sam31_concept_detector(
    *, lock_path: Path = DEFAULT_RUNTIME_LOCK
) -> Sam31ConceptDetector:
    runtime = OfficialSam31Runtime(lock_path=lock_path)
    return Sam31ConceptDetector(runtime.discover, lock_path=lock_path)


def load_official_sam31_interactive_segmenter(
    *, lock_path: Path = DEFAULT_RUNTIME_LOCK
) -> Sam31InteractiveSegmenter:
    runtime = OfficialSam31Runtime(lock_path=lock_path)
    return Sam31InteractiveSegmenter(runtime.embed, runtime.refine, lock_path=lock_path)


__all__ = [
    "AUTHORITY",
    "ARTIFACT_FIELDS",
    "OfficialSam31Runtime",
    "ResidentSam31CommandExecutor",
    "Sam31RuntimeError",
    "Sam31RuntimeImage",
    "load_official_sam31_concept_detector",
    "load_official_sam31_interactive_segmenter",
    "sam31_runtime_payload_sha256",
]
