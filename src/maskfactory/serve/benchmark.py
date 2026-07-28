"""Reproducible Mode-B latency benchmark for MF-P6-02.05."""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from PIL import Image

from ..ontology import get_ontology

PREDICT_ALL_MAX_SEC = 4.0
PREDICT_SINGLE_MAX_SEC = 2.0
REFINE_CLICK_MAX_SEC = 1.2
COLD_START_MAX_SEC = 60.0
DEFAULT_REPETITIONS = 5


class LatencyBenchmarkError(RuntimeError):
    """The serving benchmark cannot produce trustworthy evidence."""


class ServerProcess(Protocol):
    def poll(self) -> int | None: ...

    def close(self) -> None: ...


JsonGet = Callable[[str, float], dict[str, Any]]
MultipartPost = Callable[[str, Mapping[str, str], bytes, float], dict[str, Any]]
ProcessFactory = Callable[[int, Path], ServerProcess]


@dataclass
class _RunningServer:
    process: subprocess.Popen[bytes]
    log_handle: Any

    def poll(self) -> int | None:
        return self.process.poll()

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.log_handle.close()


def canonical_all_labels() -> tuple[str, ...]:
    """Return every enabled, indexed, non-background label served by champion slots."""
    ontology = get_ontology()
    labels = []
    for map_name in ("part", "material"):
        labels.extend(
            label.name
            for label in ontology.labels_for_map(map_name, enabled_only=True)
            if label.id not in {None, 0}
        )
    if not labels or len(labels) != len(set(labels)):
        raise LatencyBenchmarkError("canonical serving label set is empty or ambiguous")
    return tuple(labels)


def evaluate_latency_samples(
    *,
    cold_start_sec: float,
    predict_all_sec: Sequence[float],
    predict_single_sec: Sequence[float],
    refine_click_sec: Sequence[float],
) -> dict[str, object]:
    """Evaluate exact worst-case latency thresholds from complete repeated samples."""
    samples = {
        "predict_all_warm": _validate_samples(predict_all_sec, "predict all"),
        "predict_single_warm": _validate_samples(predict_single_sec, "predict single"),
        "refine_per_click": _validate_samples(refine_click_sec, "refine per click"),
    }
    cold = _finite_nonnegative(cold_start_sec, "cold start")
    thresholds = {
        "cold_start": COLD_START_MAX_SEC,
        "predict_all_warm": PREDICT_ALL_MAX_SEC,
        "predict_single_warm": PREDICT_SINGLE_MAX_SEC,
        "refine_per_click": REFINE_CLICK_MAX_SEC,
    }
    checks: dict[str, dict[str, object]] = {
        "cold_start": {
            "measured_max_sec": cold,
            "threshold_sec": thresholds["cold_start"],
            "operator": "lte",
            "passed": cold <= thresholds["cold_start"],
        }
    }
    for name, values in samples.items():
        summary = _sample_summary(values)
        checks[name] = {
            **summary,
            "threshold_sec": thresholds[name],
            "operator": "lte",
            "passed": float(summary["max_sec"]) <= thresholds[name],
        }
    return {
        "checks": checks,
        "passed": all(bool(check["passed"]) for check in checks.values()),
    }


def run_latency_benchmark(
    image_path: Path,
    output_path: Path,
    *,
    port: int = 8765,
    repetitions: int = DEFAULT_REPETITIONS,
    single_label: str = "left_forearm",
    startup_timeout_sec: float = 90.0,
    get_json: JsonGet | None = None,
    post_multipart: MultipartPost | None = None,
    process_factory: ProcessFactory | None = None,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Cold-launch the API, warm it, measure all targets, and atomically write evidence."""
    if not 1 <= int(port) <= 65535:
        raise LatencyBenchmarkError("benchmark port must be in [1, 65535]")
    if repetitions < 3:
        raise LatencyBenchmarkError(
            "latency benchmark requires at least three measured repetitions"
        )
    startup_timeout = _finite_nonnegative(startup_timeout_sec, "startup timeout")
    if startup_timeout <= COLD_START_MAX_SEC:
        raise LatencyBenchmarkError("startup timeout must exceed the 60-second cold-start gate")
    ontology = get_ontology()
    try:
        label = ontology.label(single_label, require_enabled=True)
    except Exception as exc:
        raise LatencyBenchmarkError(
            f"invalid single-label benchmark target: {single_label}"
        ) from exc
    if label.map not in {"part", "material"} or label.id in {None, 0}:
        raise LatencyBenchmarkError("single-label target must be a served non-background label")

    image_path = Path(image_path)
    image_bytes = image_path.read_bytes()
    try:
        with Image.open(image_path) as opened:
            opened.load()
            width, height = opened.size
    except (OSError, ValueError) as exc:
        raise LatencyBenchmarkError("benchmark image is not a readable raster") from exc
    if max(width, height) != 1024:
        raise LatencyBenchmarkError(
            "latency evidence requires an image with long side exactly 1024 px"
        )

    base_url = f"http://127.0.0.1:{port}"
    _validate_loopback_url(base_url)
    get = get_json or _get_json
    post = post_multipart or _post_multipart
    launch = process_factory or _launch_server
    try:
        existing = get(base_url + "/health", 0.5)
    except Exception:  # noqa: BLE001 - any refusal means the port is not a live API
        existing = None
    if existing is not None:
        raise LatencyBenchmarkError(
            "cold-start benchmark requires the target port to be unused before launch"
        )

    output_path = Path(output_path)
    if output_path.exists():
        raise FileExistsError(f"latency evidence already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    server_log = output_path.with_suffix(".server.log")
    started = clock()
    process = launch(port, server_log)
    try:
        health = _wait_until_ready(
            process,
            base_url,
            get=get,
            started=started,
            timeout_sec=startup_timeout,
            clock=clock,
            sleep=sleep,
        )
        cold_start_sec = clock() - started
        all_labels = canonical_all_labels()
        all_fields = {
            "labels": ",".join(all_labels),
            "return_mode": "binaries",
            "inpaint": "null",
        }
        single_fields = {
            "labels": single_label,
            "return_mode": "binaries",
            "inpaint": "null",
        }
        refine_fields = {
            "label": single_label,
            "clicks": json.dumps([{"x": width // 2, "y": height // 2, "positive": True}]),
        }

        _validate_predict_response(
            post(base_url + "/predict", all_fields, image_bytes, 120), all_labels
        )
        _validate_predict_response(
            post(base_url + "/predict", single_fields, image_bytes, 120), (single_label,)
        )
        _validate_refine_response(
            post(base_url + "/refine", refine_fields, image_bytes, 120), single_label
        )

        all_samples = _measure_requests(
            repetitions,
            lambda: _validate_predict_response(
                post(base_url + "/predict", all_fields, image_bytes, 120), all_labels
            ),
            clock,
        )
        single_samples = _measure_requests(
            repetitions,
            lambda: _validate_predict_response(
                post(base_url + "/predict", single_fields, image_bytes, 120), (single_label,)
            ),
            clock,
        )
        refine_samples = _measure_requests(
            repetitions,
            lambda: _validate_refine_response(
                post(base_url + "/refine", refine_fields, image_bytes, 120), single_label
            ),
            clock,
        )
        evaluation = evaluate_latency_samples(
            cold_start_sec=cold_start_sec,
            predict_all_sec=all_samples,
            predict_single_sec=single_samples,
            refine_click_sec=refine_samples,
        )
        report = {
            "schema_version": "1.0.0",
            "item_id": "MF-P6-02.05",
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "api_url": base_url,
            "health": health,
            "image": {
                "path": image_path.name,
                "sha256": hashlib.sha256(image_bytes).hexdigest(),
                "width": width,
                "height": height,
            },
            "all_labels": list(all_labels),
            "all_label_count": len(all_labels),
            "single_label": single_label,
            "repetitions": repetitions,
            "warmup_requests_per_case": 1,
            **evaluation,
        }
        return write_latency_report(output_path, report)
    finally:
        process.close()


def write_latency_report(path: Path, report: dict[str, object]) -> Path:
    """Atomically write only complete four-check latency evidence."""
    required_checks = {
        "cold_start",
        "predict_all_warm",
        "predict_single_warm",
        "refine_per_click",
    }
    if report.get("item_id") != "MF-P6-02.05" or set(report.get("checks", {})) != required_checks:
        raise LatencyBenchmarkError("serving latency report is incomplete")
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"latency evidence already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def default_latency_output() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("qa/live_verification") / f"serving_latency_{stamp}.json"


def _measure_requests(
    repetitions: int, request: Callable[[], object], clock: Callable[[], float]
) -> tuple[float, ...]:
    measured = []
    for _ in range(repetitions):
        started = clock()
        request()
        measured.append(clock() - started)
    return tuple(measured)


def _wait_until_ready(
    process: ServerProcess,
    base_url: str,
    *,
    get: JsonGet,
    started: float,
    timeout_sec: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    last_error = "health endpoint not ready"
    while clock() - started <= timeout_sec:
        return_code = process.poll()
        if return_code is not None:
            raise LatencyBenchmarkError(f"serving process exited before readiness: {return_code}")
        try:
            health = get(base_url + "/health", 1.0)
            if health.get("status") == "ok":
                return health
            last_error = f"unexpected health status: {health.get('status')!r}"
        except Exception as exc:  # noqa: BLE001 - transient startup boundary
            last_error = str(exc)
        sleep(0.1)
    raise LatencyBenchmarkError(
        f"serving process did not become ready within {timeout_sec:.1f}s: {last_error}"
    )


def _sample_summary(values: tuple[float, ...]) -> dict[str, object]:
    ordered = sorted(values)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "samples_sec": list(values),
        "min_sec": min(values),
        "median_sec": statistics.median(values),
        "p95_sec": ordered[p95_index],
        "max_sec": max(values),
    }


def _validate_samples(values: Sequence[float], name: str) -> tuple[float, ...]:
    if len(values) < 3:
        raise LatencyBenchmarkError(f"{name} requires at least three measured samples")
    return tuple(_finite_nonnegative(value, name) for value in values)


def _finite_nonnegative(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise LatencyBenchmarkError(f"{name} must be a finite non-negative number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise LatencyBenchmarkError(f"{name} must be a finite non-negative number") from exc
    if not math.isfinite(number) or number < 0:
        raise LatencyBenchmarkError(f"{name} must be a finite non-negative number")
    return number


def _validate_predict_response(response: dict[str, Any], labels: Sequence[str]) -> None:
    if response.get("status") != "draft_model_generated":
        raise LatencyBenchmarkError("predict response lacks draft_model_generated status")
    if response.get("labels") != list(labels):
        raise LatencyBenchmarkError("predict response label order differs from request")
    masks = response.get("masks")
    if not isinstance(masks, dict) or set(masks) != set(labels):
        raise LatencyBenchmarkError("predict response masks differ from request")


def _validate_refine_response(response: dict[str, Any], label: str) -> None:
    if response.get("status") != "draft_model_generated" or response.get("label") != label:
        raise LatencyBenchmarkError("refine response identity/status is invalid")
    if not isinstance(response.get("mask"), str) or not response["mask"]:
        raise LatencyBenchmarkError("refine response has no encoded mask")


def _validate_loopback_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise LatencyBenchmarkError("serving benchmark URL must be loopback HTTP")


def _launch_server(port: int, log_path: Path) -> ServerProcess:
    log_handle = Path(log_path).open("xb")
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "maskfactory.cli", "serve", "--port", str(port)],
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
    except Exception:
        log_handle.close()
        raise
    return _RunningServer(process=process, log_handle=log_handle)


def _get_json(url: str, timeout: float) -> dict[str, Any]:
    _validate_loopback_url(url)
    try:
        with urlopen(Request(url, method="GET"), timeout=timeout) as response:  # noqa: S310
            payload = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise LatencyBenchmarkError(f"GET {url} failed: {exc}") from exc
    return _decode_json(payload, url)


def _post_multipart(
    url: str, fields: Mapping[str, str], image_bytes: bytes, timeout: float
) -> dict[str, Any]:
    _validate_loopback_url(url)
    boundary = f"maskfactory-{uuid.uuid4().hex}"
    body = bytearray()
    for name in sorted(fields):
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(str(fields[name]).encode("utf-8"))
        body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(b'Content-Disposition: form-data; name="image"; filename="benchmark.png"\r\n')
    body.extend(b"Content-Type: image/png\r\n\r\n")
    body.extend(image_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    request = Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-1000:]
        raise LatencyBenchmarkError(f"POST {url} returned {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise LatencyBenchmarkError(f"POST {url} failed: {exc}") from exc
    return _decode_json(payload, url)


def _decode_json(payload: bytes, url: str) -> dict[str, Any]:
    try:
        document = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LatencyBenchmarkError(f"{url} returned invalid JSON") from exc
    if not isinstance(document, dict):
        raise LatencyBenchmarkError(f"{url} returned a non-object JSON response")
    return document
