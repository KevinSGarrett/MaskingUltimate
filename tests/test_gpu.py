from pathlib import Path

import pytest

from maskfactory.gpu import (
    GpuLock,
    GpuLockBusyError,
    GpuLockOwnershipError,
    GpuLockStaleError,
)


def test_gpu_lock_is_exclusive_and_released_by_its_owner(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    first = GpuLock(path, purpose="pipeline", image_id="img_a3f9c2e17b04")
    with first:
        assert path.exists()
        second = GpuLock(path)
        with pytest.raises(GpuLockBusyError):
            second.acquire()
    assert not path.exists()


def test_preexisting_stale_marker_fails_closed_and_is_preserved(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    path.write_text('{"pid":99999999,"token":"old"}\n', encoding="utf-8")
    lock = GpuLock(path)
    with pytest.raises(GpuLockStaleError):
        lock.acquire()
    assert path.is_file()


def test_gpu_lock_releases_when_protected_work_raises(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    with pytest.raises(RuntimeError, match="boom"):
        with GpuLock(path):
            raise RuntimeError("boom")
    assert not path.exists()


def test_gpu_lock_does_not_mutate_replaced_owner_marker(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    lock = GpuLock(path)
    lock.acquire()
    path.write_text('{"pid":99999999,"token":"replacement"}\n', encoding="utf-8")
    with pytest.raises(GpuLockOwnershipError):
        lock.release()
    assert "replacement" in path.read_text(encoding="utf-8")
