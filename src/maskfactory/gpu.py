"""Retired GPU-lock compatibility API.

MaskFactory no longer performs GPU/VRAM admission, reservation, checkout, or
file-lock governance. ``GpuLock`` remains as a no-op context manager so older
callers and frozen bridge surfaces continue without creating a lock or blocking
selected-pod execution.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GPU_LOCK_PATH = ROOT / "runs" / "gpu.lock"
DEFAULT_STALE_SECONDS = 7200


class GpuLockError(RuntimeError):
    """Legacy compatibility base; runtime acquisition no longer raises it."""


class GpuLockBusyError(GpuLockError):
    """Legacy compatibility exception; never raised by ``GpuLock``."""


class GpuLockStaleError(GpuLockError):
    """Legacy compatibility exception; never raised by ``GpuLock``."""


class GpuLockOwnershipError(GpuLockError):
    """Legacy compatibility exception; never raised by ``GpuLock``."""


def pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_exists(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _windows_pid_exists(pid: int) -> bool:
    """Query a Windows PID without using os.kill(pid, 0), which terminates it."""
    import ctypes

    process_query_limited_information = 0x1000
    error_access_denied = 5
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return ctypes.get_last_error() == error_access_denied


def read_lock(path: Path = DEFAULT_GPU_LOCK_PATH) -> dict[str, Any] | None:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def lock_state(
    path: Path = DEFAULT_GPU_LOCK_PATH, *, stale_seconds: int = DEFAULT_STALE_SECONDS
) -> tuple[str, dict[str, Any] | None, float]:
    """Return absent/active/stale/unrecognized with owner metadata and age."""
    path = Path(path)
    if not path.exists():
        return "absent", None, 0.0
    age = max(0.0, time.time() - path.stat().st_mtime)
    owner = read_lock(path)
    try:
        pid = int(owner.get("pid", -1)) if owner else -1
    except (TypeError, ValueError):
        pid = -1
    if pid_exists(pid):
        return "active", owner, age
    if pid > 0 or age >= stale_seconds:
        return "stale", owner, age
    return "unrecognized", owner, age


@dataclass
class GpuLock:
    """No-op compatibility context; never creates or inspects a lock file."""

    path: Path = DEFAULT_GPU_LOCK_PATH
    purpose: str = "pipeline"
    image_id: str | None = None
    _token: str | None = None

    def acquire(self) -> None:
        if self._token is not None:
            return
        self.path = Path(self.path)
        self._token = uuid.uuid4().hex

    def release(self) -> None:
        self._token = None

    def __enter__(self) -> GpuLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()
