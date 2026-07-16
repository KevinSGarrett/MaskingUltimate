"""One-process-per-job DAZ launcher with popup, timeout, and GPU safeguards."""

from __future__ import annotations

import contextlib
import csv
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from ..gpu import GpuLock
from .policy import DazPolicyError
from .protocol import DazJobFiles, read_terminal_result, stage_recipe, write_watchdog_evidence
from .runtime import DazRuntimeProfile


@dataclass(frozen=True)
class WindowObservation:
    pid: int
    title: str
    class_name: str


@dataclass(frozen=True)
class DazWorkerOutcome:
    status: str
    reason: str
    exit_code: int | None
    elapsed_seconds: float
    terminal_result: Mapping[str, Any] | None
    dialog: WindowObservation | None = None


class ProcessLike(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...


def build_daz_command(
    executable: Path,
    profile: DazRuntimeProfile,
    files: DazJobFiles,
    *,
    entrypoint: Path,
) -> list[str]:
    if profile.instance_name != "MaskFactoryDAZ":
        raise DazPolicyError("DAZ worker instance name is not isolated")
    return [
        str(executable),
        "-instanceName",
        profile.instance_name,
        "-noDefaultScene",
        "-noPrompt",
        "-logSize",
        str(profile.startup["log_size"]),
        "-scriptArg",
        str(files.recipe),
        "-scriptArg",
        str(files.partial_result),
        "-scriptArg",
        str(files.terminal_result),
        str(entrypoint),
    ]


def operation_timeout(profile: DazRuntimeProfile, operation: str) -> int:
    timeout = profile.timeouts_seconds
    if operation == "runtime_probe":
        return timeout["startup"] + timeout["finalize"]
    if operation == "asset_smoke":
        return (
            timeout["startup"]
            + timeout["asset_load"]
            + timeout["smoke_render"]
            + timeout["finalize"]
        )
    if operation == "render_scene":
        return (
            timeout["startup"]
            + timeout["assembly"]
            + timeout["simulation"]
            + timeout["rgb_render"]
            + timeout["id_render"]
            + timeout["finalize"]
        )
    raise DazPolicyError(f"unsupported DAZ operation: {operation}")


def run_daz_job(
    *,
    executable: Path,
    profile: DazRuntimeProfile,
    files: DazJobFiles,
    recipe: Mapping[str, Any],
    entrypoint: Path,
    expected_executable_sha256: str,
    expected_entrypoint_sha256: str,
    allowed_artifact_roots: tuple[Path, ...],
    popup_detector: Callable[[int, tuple[str, ...]], WindowObservation | None] | None = None,
    process_inventory: Callable[[], tuple[int, ...]] | None = None,
) -> DazWorkerOutcome:
    """Run a prepared recipe without shell, UI input, or persistent DAZ state."""
    executable = Path(executable)
    entrypoint = Path(entrypoint)
    if not executable.is_file() or not entrypoint.is_file():
        raise DazPolicyError("DAZ executable or worker entrypoint is missing")
    if _sha256(executable) != expected_executable_sha256.casefold():
        raise DazPolicyError("DAZ executable hash does not match the pinned runtime")
    if _sha256(entrypoint) != expected_entrypoint_sha256.casefold():
        raise DazPolicyError("DAZ worker entrypoint hash does not match its immutable bundle")
    if recipe.get("job_id") != files.job_directory.name:
        raise DazPolicyError("DAZ recipe does not belong to this job directory")
    requires_gpu = bool(recipe.get("requires_gpu"))
    if recipe.get("operation") == "runtime_probe" and requires_gpu:
        raise DazPolicyError("runtime probe must not acquire the render GPU")
    if recipe.get("operation") != "runtime_probe" and not requires_gpu:
        raise DazPolicyError("DAZ render operation cannot bypass the GPU lease")
    stage_recipe(files, recipe)
    running = (process_inventory or running_daz_processes)()
    if running:
        raise DazPolicyError(
            "refusing parallel or unmanaged DAZ Studio process(es): "
            + ", ".join(str(pid) for pid in running)
        )
    if requires_gpu:
        _assert_render_authorized(profile)

    command = build_daz_command(executable, profile, files, entrypoint=entrypoint)
    timeout = operation_timeout(profile, str(recipe["operation"]))
    detector = popup_detector or detect_daz_dialog
    files.worker_log.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()

    with contextlib.ExitStack() as stack:
        if requires_gpu:
            stack.enter_context(
                GpuLock(
                    Path(profile.gpu_lease["path"]),
                    purpose=str(profile.gpu_lease["purpose"]),
                    image_id=str(recipe["job_id"]),
                )
            )
        log = stack.enter_context(files.worker_log.open("ab", buffering=0))
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            shell=False,
            cwd=files.job_directory,
            **_hidden_process_options(),
        )
        return _watch_process(
            process,
            profile=profile,
            files=files,
            recipe=recipe,
            allowed_artifact_roots=allowed_artifact_roots,
            timeout_seconds=timeout,
            started_monotonic=start,
            popup_detector=detector,
        )


def _watch_process(
    process: ProcessLike,
    *,
    profile: DazRuntimeProfile,
    files: DazJobFiles,
    recipe: Mapping[str, Any],
    allowed_artifact_roots: tuple[Path, ...],
    timeout_seconds: float,
    started_monotonic: float,
    popup_detector: Callable[[int, tuple[str, ...]], WindowObservation | None],
) -> DazWorkerOutcome:
    patterns = tuple(str(value).casefold() for value in profile.watchdog["dialog_title_patterns"])
    poll_seconds = float(profile.watchdog["poll_interval_seconds"])
    while True:
        exit_code = process.poll()
        elapsed = time.monotonic() - started_monotonic
        if exit_code is not None:
            try:
                terminal = read_terminal_result(
                    files, recipe, allowed_artifact_roots=allowed_artifact_roots
                )
            except DazPolicyError as exc:
                return DazWorkerOutcome("failed", str(exc), exit_code, elapsed, None)
            if terminal is None:
                return DazWorkerOutcome(
                    "failed", "process_exited_without_terminal_result", exit_code, elapsed, None
                )
            status = str(terminal["status"])
            return DazWorkerOutcome(status, str(terminal["reason"]), exit_code, elapsed, terminal)

        dialog = popup_detector(process.pid, patterns)
        if dialog is not None:
            _terminate_process_tree(process)
            evidence = _watchdog_document(
                recipe,
                "dialog_detected",
                elapsed,
                dialog={
                    "pid": dialog.pid,
                    "title": dialog.title,
                    "class_name": dialog.class_name,
                },
            )
            write_watchdog_evidence(files.watchdog_evidence, evidence)
            return DazWorkerOutcome(
                "quarantined", "dialog_detected", process.poll(), elapsed, None, dialog
            )
        if elapsed >= timeout_seconds:
            _terminate_process_tree(process)
            write_watchdog_evidence(
                files.watchdog_evidence,
                _watchdog_document(recipe, "timeout", elapsed, dialog=None),
            )
            return DazWorkerOutcome("failed", "timeout", process.poll(), elapsed, None)
        time.sleep(poll_seconds)


def detect_daz_dialog(pid: int, patterns: tuple[str, ...]) -> WindowObservation | None:
    """Observe Windows dialogs belonging to DAZ. This function never sends UI input."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    observations: list[WindowObservation] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        owner_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value != pid:
            return True
        title_length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        title = title_buffer.value
        class_name = class_buffer.value
        folded = title.casefold()
        if class_name == "#32770" or any(pattern in folded for pattern in patterns):
            observations.append(WindowObservation(pid, title, class_name))
        return True

    callback = callback_type(visit)
    user32.EnumWindows(callback, 0)
    return observations[0] if observations else None


def running_daz_processes() -> tuple[int, ...]:
    """Return DAZ Studio PIDs without opening a shell or mutating them."""
    if os.name == "nt":
        completed = subprocess.run(
            [
                "tasklist",
                "/FI",
                "IMAGENAME eq DAZStudio.exe",
                "/FO",
                "CSV",
                "/NH",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        rows = csv.reader(completed.stdout.splitlines())
        return tuple(
            sorted(
                int(row[1])
                for row in rows
                if len(row) >= 2 and row[0].casefold() == "dazstudio.exe"
            )
        )
    completed = subprocess.run(
        ["pgrep", "-x", "DAZStudio"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
        timeout=10,
    )
    return tuple(sorted(int(value) for value in completed.stdout.split() if value.isdigit()))


def _assert_render_authorized(profile: DazRuntimeProfile) -> None:
    try:
        state = json.loads(profile.runtime_paths.control_state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DazPolicyError(f"DAZ render control state is unreadable: {exc}") from exc
    expected = {
        "enabled": True,
        "paused": False,
        "drain": False,
        "stop_requested": False,
    }
    if any(state.get(field) != value for field, value in expected.items()):
        raise DazPolicyError("DAZ render control state is not enabled/runnable")
    free_gib = shutil.disk_usage(profile.runtime_paths.job_partial_root).free / (1024**3)
    minimum = float(profile.safety["minimum_render_free_gib"])
    if free_gib < minimum:
        raise DazPolicyError(
            f"DAZ render refused below {minimum:.0f} GiB soft floor: {free_gib:.3f} GiB"
        )


def _hidden_process_options() -> dict[str, Any]:
    if os.name != "nt":
        return {"start_new_session": True}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {"startupinfo": startup, "creationflags": subprocess.CREATE_NO_WINDOW}


def _terminate_process_tree(process: ProcessLike) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
    else:
        import signal

        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    try:
        process.wait(timeout=15)
    except (subprocess.TimeoutExpired, TimeoutError):
        pass


def _watchdog_document(
    recipe: Mapping[str, Any], reason: str, elapsed: float, *, dialog: Mapping[str, Any] | None
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "job_id": recipe["job_id"],
        "recipe_id": recipe["recipe_id"],
        "timestamp": datetime.now(UTC).isoformat(),
        "reason": reason,
        "elapsed_seconds": round(elapsed, 3),
        "dialog": dict(dialog) if dialog is not None else None,
        "action": "process_tree_terminated_without_ui_input",
    }


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "DazWorkerOutcome",
    "WindowObservation",
    "build_daz_command",
    "detect_daz_dialog",
    "operation_timeout",
    "running_daz_processes",
    "run_daz_job",
]
