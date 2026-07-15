"""Machine health checks required by the MaskFactory P0 exit gate."""

from __future__ import annotations

import base64
import contextlib
import ctypes
import getpass
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
import yaml

from .governance import provider_activation_issues, validate_external_source_registry
from .gpu import lock_state
from .io import png_strict
from .models import verify_registered_model_smokes

ROOT = Path(__file__).resolve().parents[2]
CVAT_BASE_URL = "http://localhost:8080"
LOCAL_API_TIMEOUT_SECONDS = 10
LOCAL_INFERENCE_TIMEOUT_SECONDS = 45
Status = Literal["PASS", "WARN", "SKIP", "FAIL"]
PROVIDER_STATE_ORDER = (
    "planned",
    "installed",
    "benchmarked",
    "promoted",
    "reference_only",
    "retired",
)


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


def _clean_wsl_text(value: str) -> str:
    """Normalize WSL's UTF-16-looking redirected diagnostics into readable evidence."""
    return str(value or "").replace("\x00", "").replace("\\x00", "").strip()


def _windows_identity() -> str:
    """Return the process token identity, not merely the shared profile owner."""
    username = getpass.getuser()
    if os.name == "nt":
        size = ctypes.c_ulong(256)
        buffer = ctypes.create_unicode_buffer(size.value)
        if ctypes.windll.advapi32.GetUserNameW(buffer, ctypes.byref(size)):
            username = buffer.value
    domain = os.environ.get("USERDOMAIN", "")
    return f"{domain}\\{username}" if domain and "\\" not in username else username


def _wsl_failure(process: subprocess.CompletedProcess[str]) -> tuple[str, str]:
    detail = _clean_wsl_text(process.stderr) or _clean_wsl_text(process.stdout)
    detail = detail or f"wsl.exe exited {process.returncode} without diagnostics"
    missing = (
        "WSL_E_DISTRO_NOT_FOUND" in detail or "no distribution with the supplied name" in detail
    )
    if missing:
        identity = _windows_identity()
        return (
            f"Windows identity {identity!r} cannot resolve Ubuntu-22.04: {detail}",
            "Run this command in the Windows user session that owns the Ubuntu-22.04 WSL "
            "registration; do not import or attach its VHD while another WSL instance is active.",
        )
    return detail, "Repair the Ubuntu-22.04 WSL runtime and /mnt/c integration."


def _json_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    token: str | None = None,
    timeout: int = LOCAL_API_TIMEOUT_SECONDS,
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
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _result(
            "torch_cuda", "FAIL", str(exc), "Start WSL Ubuntu-22.04 and activate maskfactory."
        )
    if process.returncode:
        detail, hint = _wsl_failure(process)
        return _result("torch_cuda", "FAIL", detail, hint)
    try:
        payload = json.loads(_clean_wsl_text(process.stdout).splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return _result(
            "torch_cuda",
            "FAIL",
            f"WSL torch probe returned invalid JSON: {exc}",
            "Repair the maskfactory Python environment inside Ubuntu-22.04.",
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


def _provider_lifecycle_inventory(
    path: Path = ROOT / "configs" / "external_sources.yaml",
) -> dict[str, tuple[str, ...]]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_external_source_registry(document)
    inventory = {state: [] for state in PROVIDER_STATE_ORDER}
    for name, entry in document["providers"].items():
        state = str(entry["lifecycle_state"])
        inventory[state].append(str(name))
        if state == "promoted":
            issues = {
                lane: provider_activation_issues(entry, content_lane=lane)
                for lane in ("adult_nonexplicit", "consensual_explicit_adult")
            }
            flattened = [f"{lane}: {issue}" for lane, values in issues.items() for issue in values]
            if flattened:
                raise RuntimeError(
                    f"promoted provider {name} is not activation-ready: " + "; ".join(flattened)
                )
    return {state: tuple(sorted(names)) for state, names in inventory.items()}


def check_registered_models() -> CheckResult:
    try:
        providers = _provider_lifecycle_inventory()
        results = verify_registered_model_smokes()
    except Exception as exc:  # noqa: BLE001 - doctor must convert all failures to evidence
        detail = _clean_wsl_text(str(exc))
        if "WSL_E_DISTRO_NOT_FOUND" in detail or "no distribution with the supplied name" in detail:
            return _result(
                "registered_models",
                "FAIL",
                f"Windows identity {_windows_identity()!r} cannot run registered WSL model smokes: "
                + detail,
                "Rerun doctor in the Windows user session that owns Ubuntu-22.04; the registered "
                "checkpoint hashes are not implicated by this identity-scoped failure.",
            )
        return _result(
            "registered_models",
            "FAIL",
            detail,
            "Run `maskfactory models fetch --all`, repair the failing runtime, then rerun doctor.",
        )
    model_states: dict[str, int] = {}
    for result in results:
        state = str(result.get("lifecycle_state", "unknown"))
        model_states[state] = model_states.get(state, 0) + 1
    provider_detail = ", ".join(
        f"{state}={len(providers[state])}" for state in PROVIDER_STATE_ORDER
    )
    model_detail = ", ".join(f"{state}={count}" for state, count in sorted(model_states.items()))
    return _result(
        "registered_models",
        "PASS",
        f"{len(results)} file-backed models loaded; every smoke output hash matched; "
        f"provider lifecycle [{provider_detail}]; model smokes [{model_detail}]",
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
            timeout=LOCAL_INFERENCE_TIMEOUT_SECONDS,
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
            timeout=LOCAL_INFERENCE_TIMEOUT_SECONDS,
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


def _registered_ubuntu_vhd() -> Path | None:
    """Resolve the registered Ubuntu VHD without trying to start the distro."""
    if os.name != "nt":
        return None
    import winreg

    root_path = r"Software\Microsoft\Windows\CurrentVersion\Lxss"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root_path) as root:
            index = 0
            while True:
                try:
                    key_name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                with winreg.OpenKey(root, key_name) as distro:
                    try:
                        name = winreg.QueryValueEx(distro, "DistributionName")[0]
                    except OSError:
                        continue
                    if name != "Ubuntu-22.04":
                        continue
                    base_path = str(winreg.QueryValueEx(distro, "BasePath")[0])
                    try:
                        filename = str(winreg.QueryValueEx(distro, "VhdFileName")[0])
                    except OSError:
                        filename = "ext4.vhdx"
                    if base_path.startswith("\\\\?\\"):
                        base_path = base_path[4:]
                    return Path(base_path) / filename
    except OSError:
        return None
    return None


def check_wsl_backing_store() -> CheckResult:
    """Fail clearly when WSL's registered VHD volume vanished before boot."""
    if os.name != "nt":
        return _result("wsl_backing_store", "SKIP", "Windows-only WSL registration check")
    path = _registered_ubuntu_vhd()
    if path is None:
        return _result(
            "wsl_backing_store",
            "FAIL",
            "Ubuntu-22.04 has no readable per-user WSL registration",
            "Restore the existing Ubuntu-22.04 registration; do not import a second shadow distro.",
        )
    if not path.is_file():
        return _result(
            "wsl_backing_store",
            "FAIL",
            f"registered Ubuntu VHD is unavailable: {path}",
            "Reconnect or remount the backing volume before restarting WSL/Docker; repeated boots "
            "cannot repair a missing VHD path.",
        )
    return _result(
        "wsl_backing_store",
        "PASS",
        f"registered Ubuntu VHD is readable: {path}",
    )


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
        if process.returncode != 0:
            detail, hint = _wsl_failure(process)
            return _result("wsl_roundtrip", "FAIL", detail, hint)
        if path.read_text(encoding="utf-8") != token + "|wsl":
            raise RuntimeError("round-trip content mismatch")
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


def check_gpu_lock(
    path: Path = ROOT / "runs" / "gpu.lock", stale_seconds: int = 7200
) -> CheckResult:
    state, document, age = lock_state(path, stale_seconds=stale_seconds)
    if state == "absent":
        return _result("gpu_lock", "PASS", "no gpu.lock present")
    try:
        pid = int(document.get("pid", -1)) if document else -1
    except (ValueError, TypeError):
        pid = -1
    if state == "active":
        return _result("gpu_lock", "WARN", f"active lock pid={pid}; age={age:.0f}s")
    if state == "stale":
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
    check_wsl_backing_store,
    check_wsl_roundtrip,
    check_png_strict,
    check_sqlite,
    check_gpu_lock,
)

_WSL_DEPENDENT_CHECKS = frozenset(
    {"check_torch_cuda", "check_registered_models", "check_wsl_roundtrip"}
)


def _wsl_preflight_failure() -> tuple[str, str] | None:
    """Return one shared WSL failure so doctor does not repeat an unavailable boundary."""
    try:
        process = subprocess.run(
            ["wsl", "-d", "Ubuntu-22.04", "--", "true"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc), "Start the Ubuntu-22.04 WSL distribution and rerun doctor."
    if process.returncode:
        return _wsl_failure(process)
    return None


def _wsl_short_circuit(check_name: str, detail: str, hint: str) -> CheckResult:
    if check_name == "check_registered_models":
        return _result(
            "registered_models",
            "FAIL",
            f"Registered WSL model smokes not run because the shared WSL preflight failed: {detail}",
            "Rerun doctor in the Windows user session that owns Ubuntu-22.04; the registered "
            "checkpoint hashes are not implicated by this identity-scoped failure.",
        )
    result_name = "torch_cuda" if check_name == "check_torch_cuda" else "wsl_roundtrip"
    return _result(result_name, "FAIL", detail, hint)


def run_doctor(
    checks: Sequence[Callable[[], CheckResult]] = DEFAULT_CHECKS,
    *,
    preflight_wsl: bool | None = None,
    on_result: Callable[[CheckResult], None] | None = None,
) -> list[CheckResult]:
    """Run checks in stable order and convert unexpected exceptions to actionable FAILs."""
    if preflight_wsl is None:
        preflight_wsl = checks is DEFAULT_CHECKS
    wsl_failure = _wsl_preflight_failure() if preflight_wsl else None
    results: list[CheckResult] = []

    def record(result: CheckResult) -> None:
        results.append(result)
        if on_result is not None:
            on_result(result)

    for check in checks:
        if wsl_failure is not None and check.__name__ in _WSL_DEPENDENT_CHECKS:
            record(_wsl_short_circuit(check.__name__, *wsl_failure))
            continue
        try:
            result = check()
        except Exception as exc:  # noqa: BLE001 - never crash without a named doctor result
            result = _result(
                check.__name__, "FAIL", str(exc), "Inspect the failing check traceback."
            )
        record(result)
    return results
