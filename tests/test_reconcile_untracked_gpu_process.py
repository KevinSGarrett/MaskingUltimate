from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "reconcile_untracked_gpu_process.py"
)
SPEC = importlib.util.spec_from_file_location("maskfactory_gpu_reconciler", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeManager(types.SimpleNamespace):
    def __init__(self, *, active: dict | None = None):
        super().__init__()
        self.active = active
        self.calls: list[str] = []

    def status(self, **_: object) -> dict:
        self.calls.append("status")
        return {"active": self.active, "queued": []}

    def ensure_owner_token_file(self, _: Path) -> str:
        self.calls.append("token")
        return "secret"

    def enqueue(self, **_: object) -> dict:
        self.calls.append("enqueue")
        return {"request_id": "gpu-reconciled"}

    def acquire(self, **_: object) -> dict:
        self.calls.append("acquire")
        return {"request_id": "gpu-reconciled", "acquired": True}

    def heartbeat(self, **_: object) -> dict:
        self.calls.append("heartbeat")
        return {"heartbeat": True}

    def release(self, **_: object) -> dict:
        self.calls.append("release")
        return {"released": True}


def test_idle_does_not_create_lease(tmp_path: Path) -> None:
    manager = FakeManager()
    result = MODULE.reconcile(
        manager=manager,
        database=tmp_path / "lease.sqlite",
        interval_seconds=1,
        max_runtime_seconds=60,
        process_probe=lambda: [],
        sleeper=lambda _: None,
    )
    assert result == 0
    assert manager.calls == []


def test_unknown_owner_fails_closed_without_lease(tmp_path: Path) -> None:
    manager = FakeManager()
    result = MODULE.reconcile(
        manager=manager,
        database=tmp_path / "lease.sqlite",
        interval_seconds=1,
        max_runtime_seconds=60,
        process_probe=lambda: [123],
        owner_classifier=lambda _: None,
        sleeper=lambda _: None,
    )
    assert result == MODULE.FALLBACK_REQUIRED
    assert manager.calls == []


def test_existing_lease_is_never_replaced(tmp_path: Path) -> None:
    manager = FakeManager(active={"session_id": "foreign"})
    result = MODULE.reconcile(
        manager=manager,
        database=tmp_path / "lease.sqlite",
        interval_seconds=1,
        max_runtime_seconds=60,
        process_probe=lambda: [123],
        owner_classifier=lambda _: MODULE.MASKFACTORY_SESSION_ID,
        sleeper=lambda _: None,
    )
    assert result == 0
    assert manager.calls == ["status"]


def test_verified_owner_is_heartbeated_then_released(tmp_path: Path) -> None:
    manager = FakeManager()
    observations = iter([[123], [123], []])
    result = MODULE.reconcile(
        manager=manager,
        database=tmp_path / "lease.sqlite",
        interval_seconds=1,
        max_runtime_seconds=60,
        process_probe=lambda: next(observations),
        owner_classifier=lambda _: MODULE.MASKFACTORY_SESSION_ID,
        sleeper=lambda _: None,
    )
    assert result == 0
    assert manager.calls == [
        "status",
        "token",
        "enqueue",
        "acquire",
        "heartbeat",
        "release",
    ]


def test_mixed_owner_releases_failed_without_touching_process(tmp_path: Path) -> None:
    manager = FakeManager()
    observations = iter([[123], [123, 456]])
    owners = {
        123: MODULE.MASKFACTORY_SESSION_ID,
        456: MODULE.COMFYUI_SESSION_ID,
    }
    result = MODULE.reconcile(
        manager=manager,
        database=tmp_path / "lease.sqlite",
        interval_seconds=1,
        max_runtime_seconds=60,
        process_probe=lambda: next(observations),
        owner_classifier=lambda pid: owners[pid],
        sleeper=lambda _: None,
    )
    assert result == MODULE.COORDINATION_FAILURE
    assert manager.calls[-1] == "release"


def test_monitor_rechecks_after_idle_cycle(tmp_path: Path) -> None:
    manager = FakeManager()
    observations = iter([[], []])
    sleeps: list[float] = []
    result = MODULE.monitor(
        manager=manager,
        database=tmp_path / "lease.sqlite",
        interval_seconds=2,
        max_runtime_seconds=60,
        process_probe=lambda: next(observations),
        sleeper=sleeps.append,
        max_cycles=2,
    )
    assert result == 0
    assert sleeps == [2]
