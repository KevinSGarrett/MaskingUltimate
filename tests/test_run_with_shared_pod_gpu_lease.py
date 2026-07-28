from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import time
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "run_with_shared_pod_gpu_lease.py"
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

    def ensure_owner_token_file(self, path: Path) -> str:
        self.calls.append("token")
        token = "test-owner-token-" + "t" * 32
        path.write_text(token, encoding="ascii")
        if os.name != "nt":
            path.chmod(0o600)
        return token

    def enqueue(self, **_: object) -> dict[str, str]:
        self.calls.append("enqueue")
        return {"request_id": "gpu-mask-test", "state": "queued"}

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
        return {
            "released": True,
            "state": _["terminal_state"],
            "released_at": 1234.5,
        }

    def withdraw_queued(self, **_: object) -> dict[str, object]:
        self.calls.append("withdraw")
        return {
            "released": True,
            "state": "released",
            "released_at": 1234.5,
        }


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
        "receipt_root": tmp_path / "mission",
        "gpu_process_probe": lambda: [],
        "preflight_probe": lambda: {"status": "PASS"},
    }


def test_denied_lease_never_starts_local_gpu(tmp_path: Path, monkeypatch) -> None:
    manager = FakeManager(acquired=False)
    monkeypatch.setattr(
        MODULE.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("child must not start")),
    )
    result = MODULE.run_guarded(manager=manager, **run_args(tmp_path))
    assert result == MODULE.FALLBACK_REQUIRED
    assert manager.calls == ["token", "enqueue", "acquire", "withdraw"]
    assert not (tmp_path / "mask-owner.token").exists()
    receipt = json.loads((tmp_path / "mission" / MODULE.RELEASE_RECEIPT_NAME).read_text())
    assert receipt["disposition"] == "withdrawn_before_fallback"
    assert receipt["lease_state"] == "released"


def test_acquired_lease_wraps_child_and_terminally_releases(
    tmp_path: Path,
) -> None:
    manager = FakeManager()
    result = MODULE.run_guarded(manager=manager, **run_args(tmp_path))
    assert result == 0
    assert manager.calls[:3] == ["token", "enqueue", "acquire"]
    assert manager.calls[-1] == "release"
    assert not (tmp_path / "mask-owner.token").exists()
    receipt = json.loads((tmp_path / "mission" / MODULE.RELEASE_RECEIPT_NAME).read_text())
    assert receipt["disposition"] == "completed"
    assert receipt["child_returncode"] == 0


def test_acquired_lease_passes_nonsecret_bound_child_context(tmp_path: Path, monkeypatch) -> None:
    manager = FakeManager()
    observed: dict[str, object] = {}

    class Child:
        pid = 12345

        @staticmethod
        def poll() -> int:
            return 0

    def popen(command, *, start_new_session, env):
        observed["command"] = command
        observed["start_new_session"] = start_new_session
        observed["env"] = env
        return Child()

    monkeypatch.setattr(MODULE.subprocess, "Popen", popen)
    args = run_args(tmp_path)
    assert MODULE.run_guarded(manager=manager, **args) == 0

    environment = observed["env"]
    assert isinstance(environment, dict)
    assert environment["MASKFACTORY_SHARED_GPU_GUARD_ACTIVE"] == "1"
    assert environment["MASKFACTORY_SHARED_GPU_GUARD_JOB_ID"] == "mask-job"
    assert environment["MASKFACTORY_SHARED_GPU_GUARD_PAYLOAD_SHA256"] == "a" * 64
    assert environment["MASKFACTORY_SHARED_GPU_GUARD_REQUEST_ID"] == "gpu-mask-test"
    assert environment["MASKFACTORY_SHARED_GPU_GUARD_RECEIPT_ROOT"] == str(
        (tmp_path / "mission").resolve()
    )
    assert "test-owner-token" not in repr(environment)


def test_release_failure_fails_closed_after_own_child_terminal(
    tmp_path: Path,
) -> None:
    manager = FakeManager(release_fails=True)
    result = MODULE.run_guarded(manager=manager, **run_args(tmp_path))
    assert result == MODULE.COORDINATION_FAILURE
    assert manager.calls[-1] == "release"
    assert (tmp_path / "mask-owner.token").exists()
    assert not (tmp_path / "mission" / MODULE.RELEASE_RECEIPT_NAME).exists()


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
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("child must not start")),
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
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("child must not start")),
    )
    args = run_args(tmp_path)
    args["gpu_process_probe"] = lambda: next(observations)
    result = MODULE.run_guarded(manager=manager, **args)
    assert result == MODULE.FALLBACK_REQUIRED
    assert manager.calls == ["token", "enqueue", "acquire", "release"]
    assert not (tmp_path / "mask-owner.token").exists()
    assert (
        json.loads((tmp_path / "mission" / MODULE.RELEASE_RECEIPT_NAME).read_text())["disposition"]
        == "failed_before_child_start"
    )


def test_failed_preflight_never_enqueues_or_starts_child(tmp_path: Path, monkeypatch) -> None:
    manager = FakeManager()
    monkeypatch.setattr(
        MODULE.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("child must not start")),
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
    assert (
        json.loads((tmp_path / "mission" / MODULE.RELEASE_RECEIPT_NAME).read_text())[
            "child_returncode"
        ]
        == 23
    )


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


def test_atomic_runtime_deadline_stops_owned_child_and_releases(
    tmp_path: Path,
) -> None:
    manager = FakeManager()
    args = run_args(tmp_path)
    args["max_runtime_seconds"] = 1
    args["command"] = [sys.executable, "-c", "import time; time.sleep(30)"]

    started = time.monotonic()
    result = MODULE.run_guarded(manager=manager, **args)

    assert result == MODULE.CHILD_TIMEOUT
    assert time.monotonic() - started < 10
    receipt = json.loads((tmp_path / "mission" / MODULE.RELEASE_RECEIPT_NAME).read_text())
    assert receipt["child_returncode"] == MODULE.CHILD_TIMEOUT
    assert receipt["lease_state"] == "failed"
    assert not (tmp_path / "mask-owner.token").exists()


def test_release_receipt_is_immutable_and_self_hashes(tmp_path: Path) -> None:
    manager = FakeManager()
    assert MODULE.run_guarded(manager=manager, **run_args(tmp_path)) == 0
    path = tmp_path / "mission" / MODULE.RELEASE_RECEIPT_NAME
    receipt = json.loads(path.read_text())
    declared = receipt["self_sha256"]
    receipt["self_sha256"] = "0" * 64

    assert MODULE.canonical_sha256(receipt) == declared
    assert path.stat().st_size > 0


def test_owner_token_requires_exact_private_regular_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    token = "a" * 64
    path = tmp_path / "owner.token"
    path.write_text(token, encoding="ascii")
    owner_uid = path.stat().st_uid

    def metadata(mode: int) -> os.stat_result:
        return os.stat_result((stat.S_IFREG | mode, 0, 0, 1, owner_uid, 0, len(token), 0, 0, 0))

    monkeypatch.setattr(Path, "lstat", lambda _path: metadata(0o600))
    observed = MODULE.validate_owner_token_file(
        path,
        token,
        platform_name="posix",
        current_uid=lambda: owner_uid,
    )

    assert observed == MODULE.hashlib.sha256(token.encode("ascii")).hexdigest()

    monkeypatch.setattr(Path, "lstat", lambda _path: metadata(0o644))
    try:
        MODULE.validate_owner_token_file(
            path,
            token,
            platform_name="posix",
            current_uid=lambda: owner_uid,
        )
    except MODULE.GuardError as exc:
        assert "mode is not 0600" in str(exc)
    else:
        raise AssertionError("group/world-readable owner token must fail closed")


def test_owner_token_rejects_symlink_and_content_drift(tmp_path: Path) -> None:
    token = "b" * 64
    target = tmp_path / "target.token"
    target.write_text(token, encoding="ascii")
    target.chmod(0o600)
    link = tmp_path / "owner.token"
    try:
        link.symlink_to(target)
    except OSError:
        return

    try:
        MODULE.validate_owner_token_file(
            link,
            token,
            platform_name="posix",
            current_uid=lambda: target.stat().st_uid,
        )
    except MODULE.GuardError as exc:
        assert "not a regular file" in str(exc)
    else:
        raise AssertionError("symlinked owner token must fail closed")

    target.write_text("c" * 64, encoding="ascii")
    try:
        MODULE.validate_owner_token_file(
            target,
            token,
            platform_name="posix",
            current_uid=lambda: target.stat().st_uid,
        )
    except MODULE.GuardError as exc:
        assert "content mismatch" in str(exc)
    else:
        raise AssertionError("owner token content drift must fail closed")


def test_workspace_storage_floor_is_enforced(monkeypatch) -> None:
    monkeypatch.setattr(
        MODULE.shutil,
        "disk_usage",
        lambda _path: MODULE.shutil._ntuple_diskusage(
            100 * 1024**3,
            99 * 1024**3 + 1,
            MODULE.MIN_WORKSPACE_FREE_BYTES - 1,
        ),
    )
    try:
        MODULE.query_workspace_storage()
    except MODULE.GuardError as exc:
        assert "below the local GPU floor" in str(exc)
    else:
        raise AssertionError("low shared-volume space must fail closed")


def test_deployed_manager_source_hash_is_pinned() -> None:
    source = SCRIPT.with_name("manage_shared_pod_gpu_lease_v2.py")
    assert MODULE.file_sha256(source) == MODULE.EXPECTED_MANAGER_SHA256
