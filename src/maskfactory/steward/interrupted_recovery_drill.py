"""Actual child-process interruption drill for steward recovery semantics."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .core import (
    TERMINAL_RECEIPT_SCHEMA,
    AmbiguousMissionError,
    MissionConflictError,
    StewardLedger,
    canonical_sha256,
)
from .recovery_drill import (
    _SESSION_ID,
    _persist_run,
    _prepare_mission,
)
from .runtime import atomic_write_json, file_sha256


INTERRUPTED_RECOVERY_DRILL_SCHEMA = (
    "maskfactory_self_hosted_steward_interrupted_recovery_drill.v1"
)
CHILD_READY_SCHEMA = "maskfactory_self_hosted_steward_interrupted_child_ready.v1"
RELEASE_SCHEMA = "maskfactory_self_hosted_steward_interrupted_release.v1"
CHILD_SCENARIOS = frozenset({"persisted_terminal", "ambiguous_without_terminal"})


class InterruptedRecoveryDrillError(RuntimeError):
    """The actual child-process interruption drill failed closed."""


def _write_process_stat(proc_root: Path, pid: int, start_token: str) -> Path:
    """Create a bounded Linux-stat fixture tied to a real child PID."""

    stat_path = proc_root / str(pid) / "stat"
    stat_path.parent.mkdir(parents=True, exist_ok=False)
    fields = ["S", *(["0"] * 18), start_token]
    descriptor = os.open(stat_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(f"{pid} (actual interrupted child) {' '.join(fields)}\n")
        stream.flush()
        os.fsync(stream.fileno())
    return stat_path


def _remove_process_stat(proc_root: Path, pid: int) -> None:
    process_root = proc_root / str(pid)
    stat_path = process_root / "stat"
    if stat_path.exists():
        os.chmod(stat_path, 0o600)
        stat_path.unlink()
    if process_root.exists():
        process_root.rmdir()


def _terminal_receipt(
    binding: dict[str, Any],
    *,
    job_id: str,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": TERMINAL_RECEIPT_SCHEMA,
        "session_id": _SESSION_ID,
        "job_id": job_id,
        "payload_sha256": binding["payload_sha256"],
        "binding_sha256": binding["binding_sha256"],
        "state": "completed",
        "proposal_canonical_sha256": canonical_sha256(proposal),
        "authority_claimed": False,
    }


def _run_child(
    *,
    scenario: str,
    database: Path,
    mission_root: Path,
    proc_root: Path,
    ready_path: Path,
) -> int:
    if scenario not in CHILD_SCENARIOS:
        raise InterruptedRecoveryDrillError(f"unsupported child scenario: {scenario}")
    binding = json.loads((mission_root / "binding.json").read_text(encoding="utf-8"))
    request_sha256 = file_sha256(mission_root / "request.json")
    job_id = binding["job_id"]
    ledger = StewardLedger(database)
    admission = ledger.admit(binding)
    start_token = f"actual-child-start-{os.getpid()}"
    _write_process_stat(proc_root, os.getpid(), start_token)
    ledger.mark_running(
        _SESSION_ID,
        job_id,
        owner_pid=os.getpid(),
        owner_start_token=start_token,
    )
    ledger.record_request_intent(
        _SESSION_ID,
        job_id,
        request_sha256=request_sha256,
    )
    proposal = {
        "schema_version": "maskfactory_interrupted_recovery_proposal.v1",
        "mission_id": job_id,
        "decision": (
            "ADVISORY_ACCEPT"
            if scenario == "persisted_terminal"
            else "INCOMPLETE"
        ),
        "authority_claimed": False,
    }
    run1 = _persist_run(
        ledger=ledger,
        root=mission_root,
        job_id=job_id,
        request_sha256=request_sha256,
        run_number=1,
        proposal=proposal,
    )
    run2: dict[str, str] | None = None
    if scenario == "persisted_terminal":
        run2 = _persist_run(
            ledger=ledger,
            root=mission_root,
            job_id=job_id,
            request_sha256=request_sha256,
            run_number=2,
            proposal=proposal,
        )
        atomic_write_json(mission_root / "proposal.json", proposal)
        atomic_write_json(
            mission_root / "terminal_receipt.json",
            _terminal_receipt(binding, job_id=job_id, proposal=proposal),
        )
    ready = {
        "schema_version": CHILD_READY_SCHEMA,
        "scenario": scenario,
        "job_id": job_id,
        "pid": os.getpid(),
        "process_start_token": start_token,
        "admission_outcome": admission["outcome"],
        "binding_sha256": binding["binding_sha256"],
        "request_sha256": request_sha256,
        "run1": run1,
        "run2": run2,
        "terminal_receipt_present": (mission_root / "terminal_receipt.json").is_file(),
        "ready_sha256": "0" * 64,
    }
    ready["ready_sha256"] = canonical_sha256(ready)
    atomic_write_json(ready_path, ready)
    while True:
        time.sleep(60)


def _wait_for_ready(
    process: subprocess.Popen[str],
    ready_path: Path,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if ready_path.is_file():
            value = json.loads(ready_path.read_text(encoding="utf-8"))
            declared = value.get("ready_sha256")
            zeroed = dict(value)
            zeroed["ready_sha256"] = "0" * 64
            if declared != canonical_sha256(zeroed):
                raise InterruptedRecoveryDrillError("child ready receipt hash drifted")
            return value
        return_code = process.poll()
        if return_code is not None:
            stdout, stderr = process.communicate()
            raise InterruptedRecoveryDrillError(
                "child exited before durable ready receipt: "
                f"code={return_code} stdout={stdout!r} stderr={stderr!r}"
            )
        time.sleep(0.02)
    raise InterruptedRecoveryDrillError("timed out waiting for child ready receipt")


def _spawn_and_interrupt(
    *,
    scenario: str,
    output_root: Path,
    database: Path,
    proc_root: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    job_id = scenario.replace("_", "-")
    mission_root = output_root / job_id
    binding, request_sha256 = _prepare_mission(mission_root, job_id)
    ready_path = mission_root / "child_ready.json"
    environment = dict(os.environ)
    src_root = Path(__file__).resolve().parents[2]
    prior_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(src_root)
        if not prior_pythonpath
        else os.pathsep.join((str(src_root), prior_pythonpath))
    )
    command = [
        sys.executable,
        "-m",
        "maskfactory.steward.interrupted_recovery_drill",
        "child",
        "--scenario",
        scenario,
        "--database",
        str(database),
        "--mission-root",
        str(mission_root),
        "--proc-root",
        str(proc_root),
        "--ready-path",
        str(ready_path),
    ]
    process = subprocess.Popen(
        command,
        cwd=output_root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    ready: dict[str, Any] | None = None
    owner_alive_before_interrupt = False
    try:
        ready = _wait_for_ready(
            process,
            ready_path,
            timeout_seconds=timeout_seconds,
        )
        owner_alive_before_interrupt = StewardLedger.owner_process_alive(
            process.pid,
            str(ready["process_start_token"]),
            proc_root=proc_root,
        )
        if not owner_alive_before_interrupt:
            raise InterruptedRecoveryDrillError(
                "real child was not live at interruption boundary"
            )
        process.kill()
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    finally:
        if process.poll() is None:
            process.kill()
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        _remove_process_stat(proc_root, process.pid)
    if ready is None:
        raise InterruptedRecoveryDrillError("child never became durably ready")
    if process.returncode in (None, 0):
        raise InterruptedRecoveryDrillError("child was not forcibly interrupted")
    owner_alive_after_interrupt = StewardLedger.owner_process_alive(
        process.pid,
        str(ready["process_start_token"]),
        proc_root=proc_root,
    )
    return {
        "scenario": scenario,
        "job_id": job_id,
        "binding": binding,
        "request_sha256": request_sha256,
        "mission_root": mission_root,
        "ready": ready,
        "child_command": command,
        "child_pid": process.pid,
        "child_returncode": process.returncode,
        "child_stdout": stdout,
        "child_stderr": stderr,
        "owner_alive_before_interrupt": owner_alive_before_interrupt,
        "owner_alive_after_interrupt": owner_alive_after_interrupt,
        "actual_child_process_interrupted": (
            owner_alive_before_interrupt
            and not owner_alive_after_interrupt
            and process.returncode not in (None, 0)
        ),
    }


def run_interrupted_recovery_drill(
    output_root: Path,
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Kill two real child owners and verify deterministic reconstruction."""

    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    database = output_root / "interrupted_recovery.sqlite"
    proc_root = output_root / "proc"
    terminal = _spawn_and_interrupt(
        scenario="persisted_terminal",
        output_root=output_root,
        database=database,
        proc_root=proc_root,
        timeout_seconds=timeout_seconds,
    )
    reconstructed = StewardLedger(database)
    terminal_receipt = json.loads(
        (terminal["mission_root"] / "terminal_receipt.json").read_text(
            encoding="utf-8"
        )
    )
    terminal_reconciliation = reconstructed.reconcile_recorded_owner(
        _SESSION_ID,
        terminal["job_id"],
        terminal_receipt=terminal_receipt,
        proc_root=proc_root,
    )
    terminal_runs_before = len(
        reconstructed.runs(_SESSION_ID, terminal["job_id"])
    )
    duplicate_admission = reconstructed.admit(terminal["binding"])
    terminal_resend_blocked = False
    terminal_resend_error = ""
    try:
        reconstructed.record_request_intent(
            _SESSION_ID,
            terminal["job_id"],
            request_sha256=terminal["request_sha256"],
        )
    except MissionConflictError as exc:
        terminal_resend_blocked = True
        terminal_resend_error = f"{type(exc).__name__}: {exc}"
    terminal_runs_after = len(
        reconstructed.runs(_SESSION_ID, terminal["job_id"])
    )
    release = {
        "schema_version": RELEASE_SCHEMA,
        "job_id": terminal["job_id"],
        "child_pid": terminal["child_pid"],
        "child_returncode": terminal["child_returncode"],
        "no_gpu_or_model_process_started": True,
        "released_after_reconstruction": True,
    }
    atomic_write_json(terminal["mission_root"] / "release.json", release)
    reconstructed.record_release(
        _SESSION_ID,
        terminal["job_id"],
        release_kind="direct_process_exit",
        release_sha256=file_sha256(terminal["mission_root"] / "release.json"),
    )

    ambiguous = _spawn_and_interrupt(
        scenario="ambiguous_without_terminal",
        output_root=output_root,
        database=database,
        proc_root=proc_root,
        timeout_seconds=timeout_seconds,
    )
    del reconstructed
    restarted = StewardLedger(database)
    ambiguous_reconciliation = restarted.reconcile_recorded_owner(
        _SESSION_ID,
        ambiguous["job_id"],
        proc_root=proc_root,
    )
    ambiguous_runs_before = len(
        restarted.runs(_SESSION_ID, ambiguous["job_id"])
    )
    ambiguous_resend_blocked = False
    ambiguous_resend_error = ""
    try:
        restarted.resume_before_request(_SESSION_ID, ambiguous["job_id"])
    except AmbiguousMissionError as exc:
        ambiguous_resend_blocked = True
        ambiguous_resend_error = f"{type(exc).__name__}: {exc}"
    ambiguous_runs_after = len(
        restarted.runs(_SESSION_ID, ambiguous["job_id"])
    )

    result: dict[str, Any] = {
        "schema_version": INTERRUPTED_RECOVERY_DRILL_SCHEMA,
        "status": "PASS",
        "mode": "cpu_safe_actual_child_process_interruption",
        "model_requests_issued": 0,
        "gpu_processes_started": 0,
        "database_sha256": file_sha256(database),
        "persisted_terminal_case": {
            "job_id": terminal["job_id"],
            "binding_sha256": terminal["binding"]["binding_sha256"],
            "request_sha256": terminal["request_sha256"],
            "child_pid": terminal["child_pid"],
            "child_returncode": terminal["child_returncode"],
            "ready_receipt_sha256": file_sha256(
                terminal["mission_root"] / "child_ready.json"
            ),
            "terminal_receipt_sha256": file_sha256(
                terminal["mission_root"] / "terminal_receipt.json"
            ),
            "actual_child_process_interrupted": terminal[
                "actual_child_process_interrupted"
            ],
            "reconstruction_outcome": terminal_reconciliation["outcome"],
            "reconstructed_state": terminal_reconciliation["mission"]["state"],
            "duplicate_admission_outcome": duplicate_admission["outcome"],
            "resend_blocked": terminal_resend_blocked,
            "resend_error": terminal_resend_error,
            "run_count_before_reconciliation_attempt": terminal_runs_before,
            "run_count_after_reconciliation_attempt": terminal_runs_after,
            "release_sha256": file_sha256(
                terminal["mission_root"] / "release.json"
            ),
        },
        "ambiguous_without_terminal_case": {
            "job_id": ambiguous["job_id"],
            "binding_sha256": ambiguous["binding"]["binding_sha256"],
            "request_sha256": ambiguous["request_sha256"],
            "child_pid": ambiguous["child_pid"],
            "child_returncode": ambiguous["child_returncode"],
            "ready_receipt_sha256": file_sha256(
                ambiguous["mission_root"] / "child_ready.json"
            ),
            "actual_child_process_interrupted": ambiguous[
                "actual_child_process_interrupted"
            ],
            "terminal_receipt_present": False,
            "reconstruction_outcome": ambiguous_reconciliation["outcome"],
            "reconstructed_state": ambiguous_reconciliation["mission"]["state"],
            "resend_blocked": ambiguous_resend_blocked,
            "resend_error": ambiguous_resend_error,
            "run_count_before_resume_attempt": ambiguous_runs_before,
            "run_count_after_resume_attempt": ambiguous_runs_after,
        },
        "acceptance_gates": {
            "two_real_child_processes_interrupted": (
                terminal["actual_child_process_interrupted"]
                and ambiguous["actual_child_process_interrupted"]
            ),
            "persisted_terminal_adopted_without_reissue": (
                terminal_reconciliation["outcome"]
                == "reconciled_terminal_receipt"
                and terminal_reconciliation["mission"]["state"] == "completed"
                and duplicate_admission["outcome"] == "reconciled_terminal"
                and terminal_resend_blocked
                and terminal_runs_before == terminal_runs_after == 2
            ),
            "ambiguous_evidence_requires_recovery": (
                ambiguous_reconciliation["outcome"] == "recovery_required"
                and ambiguous_reconciliation["mission"]["state"]
                == "recovery_required"
                and ambiguous_resend_blocked
                and ambiguous_runs_before == ambiguous_runs_after == 1
            ),
            "stale_owner_identity_cleared": (
                not terminal["owner_alive_after_interrupt"]
                and not ambiguous["owner_alive_after_interrupt"]
            ),
            "no_model_reissue_or_gpu_process": True,
            "terminal_release_persisted": bool(
                restarted.get(_SESSION_ID, terminal["job_id"])["release_sha256"]
            ),
        },
    }
    if not all(result["acceptance_gates"].values()):
        result["status"] = "FAIL"
    result["result_sha256"] = canonical_sha256(result)
    atomic_write_json(output_root / "interrupted_recovery_result.json", result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    child = subparsers.add_parser("child")
    child.add_argument("--scenario", choices=sorted(CHILD_SCENARIOS), required=True)
    child.add_argument("--database", type=Path, required=True)
    child.add_argument("--mission-root", type=Path, required=True)
    child.add_argument("--proc-root", type=Path, required=True)
    child.add_argument("--ready-path", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "child":
        return _run_child(
            scenario=args.scenario,
            database=args.database,
            mission_root=args.mission_root,
            proc_root=args.proc_root,
            ready_path=args.ready_path,
        )
    raise InterruptedRecoveryDrillError("unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
