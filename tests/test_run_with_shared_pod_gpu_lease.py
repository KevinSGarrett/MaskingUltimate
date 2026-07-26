from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "run_with_shared_pod_gpu_lease.py"
)
SPEC = importlib.util.spec_from_file_location("maskfactory_gpu_guard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeManager(types.SimpleNamespace):
    def __init__(self, *, acquired: bool = True, release_fails: bool = False):
        super().__init__()
        self.acquired = acquired
        self.release_fails = release_fails
        self.calls: list[str] = []

    def ensure_owner_token_file(self, _: Path) -> str:
        self.calls.append("token")
        return "test-owner-token"

    def enqueue(self, **_: object) -> dict[str, str]:
        self.calls.append("enqueue")
        return {"request_id": "gpu-mask-test"}

    def acquire(self, **_: object) -> dict[str, object]:
        self.calls.append("acquire")
        return {
            "request_id": "gpu-mask-test",
            "acquired": self.acquired,
            "reason": "ACTIVE_LEASE_EXISTS" if not self.acquired else "ACQUIRED",
        }

    def heartbeat(self, **_: object) -> dict[str, object]:
        self.calls.append("heartbeat")
        return {"heartbeat": True}

    def release(self, **_: object) -> dict[str, object]:
        self.calls.append("release")
        if self.release_fails:
            raise RuntimeError("release failed")
        return {"released": True}


def run_args(tmp_path: Path) -> dict[str, object]:
    return {
        "database": tmp_path / "shared.sqlite",
        "token_file": tmp_path / "mask-owner.token",
        "job_id": "mask-job",
        "payload_sha256": "a" * 64,
        "work_kind": "maskfactory_test",
        "max_runtime_seconds": 60,
        "heartbeat_seconds": 0.01,
        "command": [sys.executable, "-c", "raise SystemExit(0)"],
        "gpu_process_probe": lambda: [],
        "preflight_probe": lambda: {"status": "PASS"},
    }


def test_denied_lease_never_starts_local_gpu(
    tmp_path: Path, monkeypatch
) -> None:
    manager = FakeManager(acquired=False)
    monkeypatch.setattr(
        MODULE.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("child must not start")
        ),
    )
    result = MODULE.run_guarded(manager=manager, **run_args(tmp_path))
    assert result == MODULE.FALLBACK_REQUIRED
    assert manager.calls == ["token", "enqueue", "acquire"]


def test_acquired_lease_wraps_child_and_terminally_releases(
    tmp_path: Path,
) -> None:
    manager = FakeManager()
    result = MODULE.run_guarded(manager=manager, **run_args(tmp_path))
    assert result == 0
    assert manager.calls[:3] == ["token", "enqueue", "acquire"]
    assert manager.calls[-1] == "release"


def test_release_failure_fails_closed_after_own_child_terminal(
    tmp_path: Path,
) -> None:
    manager = FakeManager(release_fails=True)
    result = MODULE.run_guarded(manager=manager, **run_args(tmp_path))
    assert result == MODULE.COORDINATION_FAILURE
    assert manager.calls[-1] == "release"


def test_missing_command_fails_before_child_start(tmp_path: Path) -> None:
    manager = FakeManager()
    args = run_args(tmp_path)
    args["command"] = []
    try:
        MODULE.run_guarded(manager=manager, **args)
    except MODULE.GuardError as exc:
        assert "child command is required" in str(exc)
    else:
        raise AssertionError("missing command must fail")
    assert manager.calls == []


def test_existing_gpu_process_routes_to_fallback_before_enqueue(
    tmp_path: Path, monkeypatch
) -> None:
    manager = FakeManager()
    monkeypatch.setattr(
        MODULE.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("child must not start")
        ),
    )
    args = run_args(tmp_path)
    args["gpu_process_probe"] = lambda: ["69508"]
    result = MODULE.run_guarded(manager=manager, **args)
    assert result == MODULE.FALLBACK_REQUIRED
    assert manager.calls == []


def test_gpu_process_race_releases_lease_without_starting_child(
    tmp_path: Path, monkeypatch
) -> None:
    manager = FakeManager()
    observations = iter([[], ["71000"]])
    monkeypatch.setattr(
        MODULE.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("child must not start")
        ),
    )
    args = run_args(tmp_path)
    args["gpu_process_probe"] = lambda: next(observations)
    result = MODULE.run_guarded(manager=manager, **args)
    assert result == MODULE.FALLBACK_REQUIRED
    assert manager.calls == ["token", "enqueue", "acquire", "release"]


def test_failed_preflight_never_enqueues_or_starts_child(
    tmp_path: Path, monkeypatch
) -> None:
    manager = FakeManager()
    monkeypatch.setattr(
        MODULE.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("child must not start")
        ),
    )
    args = run_args(tmp_path)
    args["preflight_probe"] = lambda: {"status": "FAIL"}
    try:
        MODULE.run_guarded(manager=manager, **args)
    except MODULE.GuardError as exc:
        assert "preflight did not pass" in str(exc)
    else:
        raise AssertionError("failed preflight must fail closed")
    assert manager.calls == []


def test_child_crash_terminally_releases_failed(tmp_path: Path) -> None:
    manager = FakeManager()
    args = run_args(tmp_path)
    args["command"] = [sys.executable, "-c", "raise SystemExit(23)"]

    result = MODULE.run_guarded(manager=manager, **args)

    assert result == 23
    assert manager.calls[-1] == "release"


def test_invalid_payload_identity_fails_before_preflight(tmp_path: Path) -> None:
    manager = FakeManager()
    args = run_args(tmp_path)
    args["payload_sha256"] = "NOT-A-DIGEST"
    preflight_called = False

    def preflight() -> dict[str, str]:
        nonlocal preflight_called
        preflight_called = True
        return {"status": "PASS"}

    args["preflight_probe"] = preflight
    try:
        MODULE.run_guarded(manager=manager, **args)
    except MODULE.GuardError as exc:
        assert "lowercase SHA-256" in str(exc)
    else:
        raise AssertionError("invalid payload must fail closed")
    assert preflight_called is False
    assert manager.calls == []
