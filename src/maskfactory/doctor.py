"""Machine health checks required by the MaskFactory P0 exit gate."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np

from .io import png_strict
from .models import verify_registered_model_smokes

ROOT = Path(__file__).resolve().parents[2]
CVAT_BASE_URL = "http://localhost:8080"
Status = Literal["PASS", "WARN", "SKIP", "FAIL"]


@dataclass(frozen=True)
class CheckResult:
    """One stable, serializable doctor result."""

    name: str
    status: Status
    detail: str
    hint: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _result(name: str, status: Status, detail: str, hint: str = "") -> CheckResult:
    return CheckResult(name=name, status=status, detail=detail, hint=hint)


def _json_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    token: str | None = None,
    timeout: int = 30,
) -> dict | list:
    headers = {"User-Agent": "MaskFactory/0.0.1"}
    if token:
        headers["Authorization"] = "Token " + token
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    request = Request(url, headers=headers, data=data, method=method)
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed local services
        return json.load(response)


def _env_values() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _p1_started() -> bool:
    tracker_path = ROOT / "Plan" / "Tracker" / "tracker.json"
    try:
        items = json.loads(tracker_path.read_text(encoding="utf-8")).get("items", {})
    except (OSError, json.JSONDecodeError):
        return False
    active = {"in_progress", "partially_complete", "complete"}
    return any(
        item.get("phase") == "P1" and item.get("status") in active for item in items.values()
    )


def check_torch_cuda() -> CheckResult:
    script = (
        "import json,torch; print(json.dumps({'torch':torch.__version__,"
        "'cuda':torch.version.cuda,'available':torch.cuda.is_available(),"
        "'capability':list(torch.cuda.get_device_capability(0)) if torch.cuda.is_available() else []}))"
    )
    command = [
        "wsl",
        "-d",
        "Ubuntu-22.04",
        "--",
        "/home/kevin/miniforge3/envs/maskfactory/bin/python",
        "-c",
        script,
    ]
    try:
        process = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        payload = json.loads(process.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.TimeoutExpired, IndexError, json.JSONDecodeError) as exc:
        return _result(
            "torch_cuda", "FAIL", str(exc), "Start WSL Ubuntu-22.04 and activate maskfactory."
        )
    valid = (
        process.returncode == 0
        and payload.get("available") is True
        and payload.get("cuda") == "12.8"
        and str(payload.get("torch", "")).endswith("+cu128")
        and payload.get("capability") == [12, 0]
    )
    if not valid:
        return _result(
            "torch_cuda",
            "FAIL",
            json.dumps(payload, sort_keys=True),
            "Install the cu128 torch lock and rebuild source extensions for TORCH_CUDA_ARCH_LIST=12.0.",
        )
    return _result("torch_cuda", "PASS", json.dumps(payload, sort_keys=True))


def check_registered_models() -> CheckResult:
    try:
        results = verify_registered_model_smokes()
    except Exception as exc:  # noqa: BLE001 - doctor must convert all failures to evidence
        return _result(
            "registered_models",
            "FAIL",
            str(exc),
            "Run `maskfactory models fetch --all`, repair the failing runtime, then rerun doctor.",
        )
    return _result(
        "registered_models",
        "PASS",
        f"{len(results)} file-backed models loaded; every smoke output hash matched",
    )


def check_cvat_api() -> CheckResult:
    try:
        about = _json_request(CVAT_BASE_URL + "/api/server/about")
    except (OSError, HTTPError, URLError, json.JSONDecodeError) as exc:
        return _result(
            "cvat_api", "FAIL", str(exc), "Start the pinned CVAT Compose stack on localhost:8080."
        )
    return _result("cvat_api", "PASS", f"reachable; version={about.get('version', 'unknown')}")


def check_cvat_project() -> CheckResult:
    token = _env_values().get("CVAT_TOKEN")
    if not token:
        if _p1_started():
            return _result(
                "cvat_project",
                "FAIL",
                "CVAT_TOKEN absent after P1 started",
                "Set CVAT_TOKEN in .env.",
            )
        return _result(
            "cvat_project", "SKIP", "CVAT_TOKEN absent; project gate is skippable before P1"
        )
    try:
        projects = _json_request(CVAT_BASE_URL + "/api/projects?page_size=1", token=token)
    except (OSError, HTTPError, URLError, json.JSONDecodeError) as exc:
        return _result(
            "cvat_project", "FAIL", str(exc), "Refresh CVAT_TOKEN in the ignored root .env."
        )
    count = int(projects.get("count", 0))
    if count == 0:
        if _p1_started():
            return _result(
                "cvat_project",
                "FAIL",
                "no CVAT project after P1 started",
                "Create the governed MaskFactory CVAT project.",
            )
        return _result("cvat_project", "SKIP", "no project yet; allowed before P1 project creation")
    return _result("cvat_project", "PASS", f"project_count={count}")


def check_nuclio_interactor() -> CheckResult:
    token = _env_values().get("CVAT_TOKEN")
    if not token:
        return _result("nuclio_interactor", "FAIL", "CVAT_TOKEN absent", "Set CVAT_TOKEN in .env.")
    base = CVAT_BASE_URL
    try:
        functions = _json_request(base + "/api/lambda/functions", token=token)
        function = next((item for item in functions if item.get("id") == "pth-sam2"), None)
        if not function or function.get("kind") != "interactor":
            raise RuntimeError("CVAT does not expose pth-sam2 as an interactor")
        tasks = _json_request(
            base + "/api/tasks?search=MaskFactory%20SAM2%20synthetic%20smoke", token=token
        )
        task = next((item for item in tasks.get("results", []) if item.get("size") == 1), None)
        if task is None:
            raise RuntimeError("synthetic SAM2 smoke task is missing")
        response = _json_request(
            base + "/api/lambda/functions/pth-sam2",
            method="POST",
            token=token,
            timeout=120,
            payload={
                "task": int(task["id"]),
                "frame": 0,
                "pos_points": [[128, 128]],
                "neg_points": [[16, 16]],
            },
        )
        mask = np.asarray(response["mask"], dtype=np.uint8)
        if mask.shape != (256, 256) or not set(np.unique(mask)).issubset({0, 255}):
            raise RuntimeError(f"invalid SAM2 response: shape={mask.shape}")
    except Exception as exc:  # noqa: BLE001 - service boundary
        return _result(
            "nuclio_interactor",
            "FAIL",
            str(exc),
            "Run tools/smoke_cvat_sam2.py and repair the pth-sam2 Nuclio deployment.",
        )
    return _result(
        "nuclio_interactor", "PASS", f"pth-sam2 answered; foreground={np.count_nonzero(mask)}"
    )


def check_ollama_image() -> CheckResult:
    fixture = ROOT / "qa" / "fixtures" / "smoke" / "ultralytics_bus_adults.jpg"
    try:
        encoded = base64.b64encode(fixture.read_bytes()).decode()
        response = _json_request(
            "http://127.0.0.1:11434/api/chat",
            method="POST",
            timeout=240,
            payload={
                "model": "qwen2.5vl:7b",
                "stream": False,
                "format": "json",
                "messages": [
                    {
                        "role": "user",
                        "content": 'Return JSON exactly as {"image_received": true}.',
                        "images": [encoded],
                    }
                ],
            },
        )
        content = json.loads(response["message"]["content"])
        if content.get("image_received") is not True:
            raise RuntimeError(f"unexpected VLM response: {content}")
    except Exception as exc:  # noqa: BLE001 - service/model boundary
        return _result(
            "ollama_image",
            "FAIL",
            str(exc),
            "Start the Ollama container and verify qwen2.5vl:7b can accept images.",
        )
    return _result("ollama_image", "PASS", "qwen2.5vl:7b returned strict image JSON")


def check_disk_free(path: Path = ROOT / "data") -> CheckResult:
    path.mkdir(parents=True, exist_ok=True)
    free_gib = shutil.disk_usage(path).free / (1024**3)
    detail = f"{free_gib:.1f} GiB free"
    if free_gib < 75:
        return _result(
            "disk_free", "FAIL", detail, "BLOCK new ingest; move data to a larger governed drive."
        )
    if free_gib < 150:
        return _result(
            "disk_free",
            "WARN",
            detail,
            "Disk warning threshold crossed; schedule the junction move.",
        )
    if free_gib < 200:
        return _result(
            "disk_free", "WARN", detail, "Below the 200 GiB doctor target; monitor before ingest."
        )
    return _result("disk_free", "PASS", detail)


def _wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    return f"/mnt/{drive}{resolved.as_posix().split(':', 1)[1]}"


def check_wsl_roundtrip() -> CheckResult:
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=".doctor_roundtrip_", dir=data_dir)
    os.close(handle)
    path = Path(name)
    token = f"maskfactory-{time.time_ns()}"
    try:
        path.write_text(token, encoding="utf-8")
        script = (
            "from pathlib import Path; p=Path("
            + repr(_wsl_path(path))
            + "); p.write_text(p.read_text()+'|wsl')"
        )
        process = subprocess.run(
            ["wsl", "-d", "Ubuntu-22.04", "--", "python3", "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if process.returncode != 0 or path.read_text(encoding="utf-8") != token + "|wsl":
            raise RuntimeError(process.stderr.strip() or "round-trip content mismatch")
    except Exception as exc:  # noqa: BLE001 - OS boundary
        return _result(
            "wsl_roundtrip", "FAIL", str(exc), "Repair WSL /mnt/c integration and permissions."
        )
    finally:
        path.unlink(missing_ok=True)
    return _result("wsl_roundtrip", "PASS", "Windows -> /mnt/c -> Windows content matched")


def check_png_strict() -> CheckResult:
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            passed = png_strict.self_test()
    except Exception as exc:  # noqa: BLE001 - self-test boundary
        return _result(
            "png_strict", "FAIL", str(exc), "Repair maskfactory.io.png_strict invariants."
        )
    if not passed:
        return _result(
            "png_strict",
            "FAIL",
            "self-test returned false",
            "Repair png_strict before writing masks.",
        )
    return _result("png_strict", "PASS", "all built-in writer invariants passed")


def check_sqlite(path: Path = ROOT / "data" / "maskfactory.sqlite") -> CheckResult:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(path, timeout=5) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE IF NOT EXISTS doctor_write_probe (value TEXT)")
            connection.execute("INSERT INTO doctor_write_probe VALUES ('probe')")
            connection.rollback()
    except sqlite3.Error as exc:
        return _result(
            "sqlite_writable",
            "FAIL",
            str(exc),
            "Repair data directory and SQLite write permissions.",
        )
    return _result("sqlite_writable", "PASS", str(path))


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def check_gpu_lock(
    path: Path = ROOT / "runs" / "gpu.lock", stale_seconds: int = 7200
) -> CheckResult:
    if not path.exists():
        return _result("gpu_lock", "PASS", "no gpu.lock present")
    age = max(0.0, time.time() - path.stat().st_mtime)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        pid = int(document.get("pid", -1))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pid = -1
    if _pid_exists(pid):
        return _result("gpu_lock", "WARN", f"active lock pid={pid}; age={age:.0f}s")
    if age >= stale_seconds or pid > 0:
        return _result(
            "gpu_lock",
            "FAIL",
            f"stale lock pid={pid}; age={age:.0f}s",
            "Confirm no GPU process is active, then remove runs/gpu.lock.",
        )
    return _result("gpu_lock", "WARN", f"unrecognized recent lock; age={age:.0f}s")


DEFAULT_CHECKS: tuple[Callable[[], CheckResult], ...] = (
    check_torch_cuda,
    check_registered_models,
    check_cvat_api,
    check_cvat_project,
    check_nuclio_interactor,
    check_ollama_image,
    check_disk_free,
    check_wsl_roundtrip,
    check_png_strict,
    check_sqlite,
    check_gpu_lock,
)


def run_doctor(checks: Sequence[Callable[[], CheckResult]] = DEFAULT_CHECKS) -> list[CheckResult]:
    """Run checks in stable order and convert unexpected exceptions to actionable FAILs."""
    results: list[CheckResult] = []
    for check in checks:
        try:
            results.append(check())
        except Exception as exc:  # noqa: BLE001 - never crash without a named doctor result
            results.append(
                _result(check.__name__, "FAIL", str(exc), "Inspect the failing check traceback.")
            )
    return results
