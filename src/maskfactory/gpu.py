"""Atomic ownership lease for MaskFactory's single shared GPU slot."""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GPU_LOCK_PATH = ROOT / "runs" / "gpu.lock"
DEFAULT_STALE_SECONDS = 7200


class GpuLockError(RuntimeError):
    """Base GPU lease error."""


class GpuLockBusyError(GpuLockError):
    """A live or unrecognized owner already holds the GPU slot."""


class GpuLockStaleError(GpuLockError):
    """A dead owner left a lock that requires operator-confirmed removal."""


class GpuLockOwnershipError(GpuLockError):
    """The lock changed owners before release; never delete it blindly."""


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
    """Exclusive context manager with token-checked release semantics."""

    path: Path = DEFAULT_GPU_LOCK_PATH
    purpose: str = "pipeline"
    image_id: str | None = None
    _token: str | None = None

    def acquire(self) -> None:
        if self._token is not None:
            raise GpuLockBusyError("this GPU lock object already owns a lease")
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        owner = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "acquired_at": datetime.now(UTC).isoformat(),
            "purpose": self.purpose,
            "image_id": self.image_id,
            "token": token,
        }
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            state, existing, age = lock_state(self.path)
            detail = json.dumps(existing, sort_keys=True) if existing else "metadata unavailable"
            if state == "stale":
                raise GpuLockStaleError(
                    f"stale GPU lock age={age:.0f}s; confirm no GPU process, then remove "
                    f"{self.path}: {detail}"
                ) from exc
            raise GpuLockBusyError(
                f"GPU slot unavailable ({state}, age={age:.0f}s): {detail}"
            ) from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(owner, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            self.path.unlink(missing_ok=True)
            raise
        self._token = token

    def release(self) -> None:
        if self._token is None:
            return
        owner = read_lock(self.path)
        if not owner or owner.get("token") != self._token:
            raise GpuLockOwnershipError(
                f"GPU lock ownership changed; refusing to remove {self.path}"
            )
        self.path.unlink()
        self._token = None

    def __enter__(self) -> GpuLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()
