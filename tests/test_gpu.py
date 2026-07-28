from pathlib import Path

import pytest

from maskfactory.gpu import GpuLock


def test_gpu_compatibility_context_never_creates_or_checks_out_resource(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    first = GpuLock(path, purpose="pipeline", image_id="img_a3f9c2e17b04")
    with first:
        assert not path.exists()
        second = GpuLock(path)
        second.acquire()
        second.release()
    assert not path.exists()


def test_preexisting_legacy_marker_is_ignored_and_preserved(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    path.write_text('{"pid":99999999,"token":"old"}\n', encoding="utf-8")
    lock = GpuLock(path)
    lock.acquire()
    lock.release()
    assert path.is_file()


def test_gpu_lock_releases_when_protected_work_raises(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    with pytest.raises(RuntimeError, match="boom"):
        with GpuLock(path):
            raise RuntimeError("boom")
    assert not path.exists()


def test_gpu_compatibility_context_does_not_mutate_replaced_legacy_marker(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    lock = GpuLock(path)
    lock.acquire()
    path.write_text('{"pid":99999999,"token":"replacement"}\n', encoding="utf-8")
    lock.release()
    assert "replacement" in path.read_text(encoding="utf-8")
