import json
from pathlib import Path

import pytest

from maskfactory.gpu import (
    GpuLock,
    GpuLockBusyError,
    GpuLockOwnershipError,
    GpuLockStaleError,
    lock_state,
)


def test_gpu_lock_acquires_metadata_refuses_live_owner_and_releases(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    first = GpuLock(path, purpose="pipeline", image_id="img_a3f9c2e17b04")
    with first:
        state, owner, _ = lock_state(path)
        assert state == "active"
        assert owner is not None
        assert owner["purpose"] == "pipeline"
        assert owner["image_id"] == "img_a3f9c2e17b04"
        assert len(owner["token"]) == 32
        with pytest.raises(GpuLockBusyError, match="GPU slot unavailable"):
            GpuLock(path).acquire()
    assert lock_state(path)[0] == "absent"


def test_gpu_lock_reports_dead_owner_as_stale_and_never_auto_deletes(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    path.write_text(json.dumps({"pid": 99999999, "token": "old"}), encoding="utf-8")
    with pytest.raises(GpuLockStaleError, match="confirm no GPU process"):
        GpuLock(path).acquire()
    assert path.is_file()


def test_gpu_lock_releases_when_protected_work_raises(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    with pytest.raises(RuntimeError, match="boom"):
        with GpuLock(path):
            raise RuntimeError("boom")
    assert not path.exists()


def test_gpu_lock_refuses_to_delete_replaced_owner(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    lock = GpuLock(path)
    lock.acquire()
    path.write_text(json.dumps({"pid": 99999999, "token": "replacement"}), encoding="utf-8")
    with pytest.raises(GpuLockOwnershipError, match="ownership changed"):
        lock.release()
    assert path.is_file()
