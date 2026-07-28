from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from tools.run_self_hosted_supervisor import (
    _inbox_totals,
    _validate_fallback_admission,
    build_parser,
)

from maskfactory.steward.supervisor import (
    CpuSafeSupervisor,
    SupervisorAlreadyRunning,
    SupervisorStateError,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_standalone_launcher_defaults_to_one_bounded_advisory_mode() -> None:
    args = build_parser().parse_args(
        [
            "--state-root",
            "state",
            "--supervisor-id",
            "maskfactory-test",
        ]
    )

    assert args.openrouter_work_kinds == "implementation_review"
    assert args.max_openrouter_workers == 1
    assert args.max_serverless_workers == 1


def test_supervisor_rejects_fallback_worker_fanout() -> None:
    args = build_parser().parse_args(
        [
            "--state-root",
            "state",
            "--supervisor-id",
            "maskfactory-test",
            "--no-auto-produce-serverless",
            "--max-openrouter-workers",
            "4",
        ]
    )

    with pytest.raises(SystemExit, match="max-openrouter-workers must be exactly 1"):
        _validate_fallback_admission(args)


def test_supervisor_rejects_openrouter_mode_micro_fanout() -> None:
    args = build_parser().parse_args(
        [
            "--state-root",
            "state",
            "--supervisor-id",
            "maskfactory-test",
            "--no-auto-produce-serverless",
            "--openrouter-work-kinds",
            "implementation_review,test_strategy",
        ]
    )

    with pytest.raises(
        SystemExit,
        match="exactly one consolidated advisory mode",
    ):
        _validate_fallback_admission(args)


def test_supervisor_rejects_stale_serverless_manager_path() -> None:
    args = build_parser().parse_args(
        [
            "--state-root",
            "state",
            "--supervisor-id",
            "maskfactory-test",
            "--no-auto-produce-serverless",
            "--serverless-manager",
            "C:/stale/manage_runpod_serverless_overflow.py",
        ]
    )

    with pytest.raises(SystemExit, match="non-canonical Serverless manager"):
        _validate_fallback_admission(args)


def test_local_campaign_preparation_arguments_are_explicit() -> None:
    args = build_parser().parse_args(
        [
            "--state-root",
            "state",
            "--supervisor-id",
            "maskfactory-test",
            "--local-campaign-source",
            "source.json",
            "--local-packet-parent",
            "packets",
        ]
    )

    assert args.local_campaign_source == Path("source.json")
    assert args.local_packet_parent == Path("packets")


class Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        self.value += 1.0
        return self.value


def test_clean_start_heartbeat_snapshot_and_shutdown(tmp_path: Path) -> None:
    clock = Clock()
    supervisor = CpuSafeSupervisor(
        tmp_path,
        supervisor_id="maskfactory-main",
        process_identity_probe=lambda pid: f"start-{pid}",
        clock=clock,
    )

    started = supervisor.start()
    health = supervisor.heartbeat()
    snapshot = supervisor.snapshot()
    shutdown = supervisor.shutdown(reason="test_complete")

    assert started["state"] == "running"
    assert "owner_token_sha256" not in started
    assert health["cpu_safe"] is True and health["gpu_held"] is False
    assert snapshot["queue"]["count"] == 0
    assert snapshot["campaign"]["state"] == "idle"
    assert shutdown["reason"] == "test_complete"
    assert not supervisor.token_path.exists()
    assert json.loads(supervisor.owner_path.read_text())["state"] == "stopped"


def test_protected_token_is_mode_0600_and_never_in_safe_state(tmp_path: Path) -> None:
    supervisor = CpuSafeSupervisor(
        tmp_path,
        supervisor_id="maskfactory-main",
        process_identity_probe=lambda pid: f"start-{pid}",
    )
    safe_owner = supervisor.start()
    raw_token = supervisor.token_path.read_bytes()

    if os.name != "nt":
        assert stat.S_IMODE(supervisor.token_path.stat().st_mode) == 0o600
    assert raw_token
    assert raw_token not in json.dumps(safe_owner).encode()
    assert hashlib.sha256(raw_token).hexdigest() not in json.dumps(safe_owner)
    supervisor.shutdown()


def test_matching_live_owner_blocks_duplicate_supervisor(tmp_path: Path) -> None:
    def identity(pid: int) -> str:
        return f"start-{pid}"

    first = CpuSafeSupervisor(
        tmp_path,
        supervisor_id="maskfactory-main",
        process_identity_probe=identity,
    )
    first.start()
    duplicate = CpuSafeSupervisor(
        tmp_path,
        supervisor_id="maskfactory-main",
        process_identity_probe=identity,
    )

    with pytest.raises(SupervisorAlreadyRunning):
        duplicate.start()
    first.shutdown()


def test_stale_pid_token_is_recovered_without_process_action(tmp_path: Path) -> None:
    first = CpuSafeSupervisor(
        tmp_path,
        supervisor_id="maskfactory-main",
        process_identity_probe=lambda pid: f"old-{pid}",
    )
    first.start()
    second = CpuSafeSupervisor(
        tmp_path,
        supervisor_id="maskfactory-main",
        process_identity_probe=lambda pid: f"new-{pid}",
    )

    started = second.start()

    assert started["generation"] == 2
    receipt = json.loads((tmp_path / "stale_owner_000001.json").read_text())
    assert receipt["expected_process_start_token"].startswith("old-")
    assert receipt["observed_process_start_token"].startswith("new-")
    second.shutdown()


def test_clean_restart_increments_generation(tmp_path: Path) -> None:
    def identity(pid: int) -> str:
        return f"start-{pid}"

    first = CpuSafeSupervisor(
        tmp_path,
        supervisor_id="maskfactory-main",
        process_identity_probe=identity,
    )
    first.start()
    first.shutdown()
    second = CpuSafeSupervisor(
        tmp_path,
        supervisor_id="maskfactory-main",
        process_identity_probe=identity,
    )

    started = second.start()

    assert started["generation"] == 2
    second.shutdown()


def test_queue_campaign_and_hash_chained_exception_contracts(tmp_path: Path) -> None:
    supervisor = CpuSafeSupervisor(
        tmp_path,
        supervisor_id="maskfactory-main",
        process_identity_probe=lambda pid: f"start-{pid}",
    )
    supervisor.start()

    queue = supervisor.update_queue(["MF-P6-14.02", "MF-P6-14.03"])
    campaign = supervisor.update_campaign("engineering-001", state="planned")
    first = supervisor.record_exception("queue", "one item deferred")
    second = supervisor.record_exception("recovery", "reconciled stale state")

    assert queue["count"] == 2
    assert campaign["campaign_id"] == "engineering-001"
    assert second["previous_sha256"] == first["event_sha256"]
    supervisor.shutdown()


def test_malformed_queue_and_ownership_drift_fail_closed(tmp_path: Path) -> None:
    identities = {os.getpid(): f"start-{os.getpid()}"}
    supervisor = CpuSafeSupervisor(
        tmp_path,
        supervisor_id="maskfactory-main",
        process_identity_probe=lambda pid: identities.get(pid),
    )
    supervisor.start()

    with pytest.raises(SupervisorStateError, match="unique"):
        supervisor.update_queue(["MF-P6-14.02", "MF-P6-14.02"])
    identities[os.getpid()] = "reused-pid"
    with pytest.raises(SupervisorStateError, match="start token changed"):
        supervisor.heartbeat()


def test_standalone_launcher_resolves_src_outside_repository(tmp_path: Path) -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "run_self_hosted_supervisor.py"),
            "--help",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--state-root" in result.stdout


def test_standalone_launcher_once_writes_terminal_state(tmp_path: Path) -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    state_root = tmp_path / "state"

    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "run_self_hosted_supervisor.py"),
            "--state-root",
            str(state_root),
            "--supervisor-id",
            "maskfactory-test",
            "--no-auto-produce-openrouter",
            "--no-auto-produce-serverless",
            "--once",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    owner = json.loads((state_root / "owner.json").read_text())
    shutdown = json.loads((state_root / "shutdown_000001.json").read_text())
    throughput = json.loads((state_root / "fallback_throughput.json").read_text())
    events = [
        json.loads(line)
        for line in (state_root / "fallback_throughput_events.jsonl").read_text().splitlines()
    ]
    assert owner["state"] == "stopped"
    assert shutdown["reason"] == "signal_or_clean_exit"
    assert throughput["tracker_path"] == str(
        (PROJECT_ROOT / "Plan" / "Tracker" / "tracker.json").resolve()
    )
    assert throughput["cumulative"]["dispatch_cycles"] == 1
    assert throughput["inbox_totals"] == {
        "openrouter_missions": 0,
        "openrouter_completed": 0,
        "openrouter_duplicate_blocked": 0,
        "serverless_missions": 0,
        "serverless_completed": 0,
        "serverless_failed": 0,
    }
    assert len(events) == 1
    assert events[0]["cycle"]["dispatch_results"] == 0
    assert not (state_root / "owner.token").exists()


def test_inbox_totals_reports_serverless_semantic_false_as_failed(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "inbox"
    failed = inbox / ("a" * 64)
    passed = inbox / ("b" * 64)
    for mission_root, native_ready in ((failed, False), (passed, True)):
        mission_root.mkdir(parents=True)
        (mission_root / "fallback_work_item.json").write_text(
            json.dumps({"route": "serverless_overflow"}),
            encoding="utf-8",
        )
        (mission_root / "fallback_terminal_receipt.json").write_text(
            json.dumps({"disposition": "completed"}),
            encoding="utf-8",
        )
        (mission_root / "serverless_route_state.json").write_text(
            json.dumps(
                {
                    "last_result": {
                        "provider_status_json": json.dumps(
                            {
                                "output": {
                                    "stdout_tail": json.dumps(
                                        {
                                            "native_box_runtime_ready": native_ready,
                                        }
                                    )
                                }
                            }
                        )
                    }
                }
            ),
            encoding="utf-8",
        )

    assert _inbox_totals(inbox) == {
        "openrouter_missions": 0,
        "openrouter_completed": 0,
        "openrouter_duplicate_blocked": 0,
        "serverless_missions": 2,
        "serverless_completed": 1,
        "serverless_failed": 1,
    }


def test_standalone_launcher_refuses_stale_tracker_path(tmp_path: Path) -> None:
    stale = tmp_path / "tracker.json"
    stale.write_text('{"items":{}}\n', encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "run_self_hosted_supervisor.py"),
            "--state-root",
            str(tmp_path / "state"),
            "--supervisor-id",
            "maskfactory-test",
            "--tracker-path",
            str(stale),
            "--once",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "non-authoritative tracker" in result.stderr
