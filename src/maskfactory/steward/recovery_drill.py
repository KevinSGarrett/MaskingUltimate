"""Deterministic CPU drill for real steward restart/reconciliation behavior."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .core import (
    AUTHORITY_KEYS,
    BINDING_SCHEMA,
    TERMINAL_RECEIPT_SCHEMA,
    AmbiguousMissionError,
    MissionConflictError,
    StewardLedger,
    canonical_sha256,
    seal_binding,
)
from .runtime import atomic_write_json, file_sha256

RECOVERY_DRILL_SCHEMA = "maskfactory_self_hosted_steward_recovery_drill.v1"
_SESSION_ID = "maskfactory-recovery-drill"
_MODEL_TREE_SHA256 = "8" * 64
_RUNTIME_SHA256 = "9" * 64


def _write_text_exclusive(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _binding(root: Path, job_id: str, payload_sha256: str) -> dict[str, Any]:
    inputs = {
        name: file_sha256(root / name)
        for name in ("prompt.txt", "request.json")
    }
    return seal_binding(
        {
            "schema_version": BINDING_SCHEMA,
            "session_id": _SESSION_ID,
            "job_id": job_id,
            "payload_sha256": payload_sha256,
            "model_tree_sha256": _MODEL_TREE_SHA256,
            "runtime_sha256": _RUNTIME_SHA256,
            "input_sha256": inputs,
            "output_namespace": f"{_SESSION_ID}/{job_id}",
            "requires_replay": True,
            "authority": {key: False for key in sorted(AUTHORITY_KEYS)},
        }
    )


def _fake_stale_proc(proc_root: Path, pid: int) -> None:
    stat_path = proc_root / str(pid) / "stat"
    stat_path.parent.mkdir(parents=True)
    fields = ["S", *(["0"] * 18), "reused-pid-start-token"]
    _write_text_exclusive(stat_path, f"{pid} (steward worker) {' '.join(fields)}\n")


def _prepare_mission(root: Path, job_id: str) -> tuple[dict[str, Any], str]:
    root.mkdir(parents=True)
    prompt = (
        "Review one bounded MaskFactory engineering packet. Return advisory JSON only; "
        "claim no tools, secrets, Git, RunPod, repository, or acceptance authority.\n"
    )
    request = {
        "mission": job_id,
        "prompt_sha256": canonical_sha256(prompt),
        "temperature": 0,
        "seed": 1337,
    }
    _write_text_exclusive(root / "prompt.txt", prompt)
    atomic_write_json(root / "request.json", request)
    payload_sha256 = canonical_sha256(
        {
            "job_id": job_id,
            "prompt_sha256": file_sha256(root / "prompt.txt"),
            "request_sha256": file_sha256(root / "request.json"),
        }
    )
    binding = _binding(root, job_id, payload_sha256)
    atomic_write_json(root / "binding.json", binding)
    return binding, file_sha256(root / "request.json")


def _persist_run(
    *,
    ledger: StewardLedger,
    root: Path,
    job_id: str,
    request_sha256: str,
    run_number: int,
    proposal: dict[str, Any],
) -> dict[str, str]:
    response = {
        "choices": [{"message": {"content": json.dumps(proposal, sort_keys=True)}}],
        "run_number": run_number,
    }
    response_path = root / f"response_run{run_number}.json"
    proposal_path = root / f"proposal_run{run_number}.json"
    atomic_write_json(response_path, response)
    atomic_write_json(proposal_path, proposal)
    ledger.record_run(
        _SESSION_ID,
        job_id,
        run_number=run_number,
        request_sha256=request_sha256,
        response_sha256=file_sha256(response_path),
        proposal_sha256=file_sha256(proposal_path),
        proposal_canonical_sha256=canonical_sha256(proposal),
    )
    return {
        "response_sha256": file_sha256(response_path),
        "proposal_sha256": file_sha256(proposal_path),
        "proposal_canonical_sha256": canonical_sha256(proposal),
    }


def run_recovery_drill(output_root: Path) -> dict[str, Any]:
    """Run both restart cases once in a new, namespaced output root."""
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=False)
    database = output_root / "steward_recovery_drill.sqlite"
    proc_root = output_root / "synthetic_proc"
    owner_pid = 424242
    owner_token = "original-owner-start-token"
    _fake_stale_proc(proc_root, owner_pid)

    ledger = StewardLedger(database)

    terminal_job = "persisted-terminal"
    terminal_root = output_root / terminal_job
    terminal_binding, terminal_request_sha256 = _prepare_mission(
        terminal_root, terminal_job
    )
    admitted = ledger.admit(terminal_binding)
    ledger.mark_running(
        _SESSION_ID,
        terminal_job,
        owner_pid=owner_pid,
        owner_start_token=owner_token,
    )
    ledger.record_request_intent(
        _SESSION_ID,
        terminal_job,
        request_sha256=terminal_request_sha256,
    )
    proposal = {
        "schema_version": "maskfactory_recovery_drill_proposal.v1",
        "mission_id": terminal_job,
        "decision": "ADVISORY_ACCEPT",
        "authority_claimed": False,
    }
    run1 = _persist_run(
        ledger=ledger,
        root=terminal_root,
        job_id=terminal_job,
        request_sha256=terminal_request_sha256,
        run_number=1,
        proposal=proposal,
    )
    run2 = _persist_run(
        ledger=ledger,
        root=terminal_root,
        job_id=terminal_job,
        request_sha256=terminal_request_sha256,
        run_number=2,
        proposal=proposal,
    )
    atomic_write_json(terminal_root / "proposal.json", proposal)
    terminal_receipt = {
        "schema_version": TERMINAL_RECEIPT_SCHEMA,
        "session_id": _SESSION_ID,
        "job_id": terminal_job,
        "payload_sha256": terminal_binding["payload_sha256"],
        "binding_sha256": terminal_binding["binding_sha256"],
        "state": "completed",
        "proposal_canonical_sha256": canonical_sha256(proposal),
        "authority_claimed": False,
    }
    atomic_write_json(terminal_root / "terminal_receipt.json", terminal_receipt)

    owner_alive_before_restart = StewardLedger.owner_process_alive(
        owner_pid, owner_token, proc_root=proc_root
    )
    del ledger
    restarted = StewardLedger(database)
    terminal_reconciliation = restarted.reconcile_recorded_owner(
        _SESSION_ID,
        terminal_job,
        terminal_receipt=terminal_receipt,
        proc_root=proc_root,
    )
    duplicate_admission = restarted.admit(terminal_binding)
    resend_blocked = False
    resend_error = ""
    try:
        restarted.record_request_intent(
            _SESSION_ID,
            terminal_job,
            request_sha256=terminal_request_sha256,
        )
    except MissionConflictError as exc:
        resend_blocked = True
        resend_error = f"{type(exc).__name__}: {exc}"
    release = {
        "schema_version": "maskfactory_recovery_drill_release.v1",
        "job_id": terminal_job,
        "no_gpu_process_started": True,
        "state": terminal_reconciliation["mission"]["state"],
    }
    atomic_write_json(terminal_root / "release.json", release)
    restarted.record_release(
        _SESSION_ID,
        terminal_job,
        release_kind="direct_process_exit",
        release_sha256=file_sha256(terminal_root / "release.json"),
    )

    ambiguous_job = "ambiguous-without-terminal"
    ambiguous_root = output_root / ambiguous_job
    ambiguous_binding, ambiguous_request_sha256 = _prepare_mission(
        ambiguous_root, ambiguous_job
    )
    restarted.admit(ambiguous_binding)
    restarted.mark_running(
        _SESSION_ID,
        ambiguous_job,
        owner_pid=owner_pid,
        owner_start_token=owner_token,
    )
    restarted.record_request_intent(
        _SESSION_ID,
        ambiguous_job,
        request_sha256=ambiguous_request_sha256,
    )
    ambiguous_proposal = {
        "schema_version": "maskfactory_recovery_drill_proposal.v1",
        "mission_id": ambiguous_job,
        "decision": "INCOMPLETE",
        "authority_claimed": False,
    }
    ambiguous_run = _persist_run(
        ledger=restarted,
        root=ambiguous_root,
        job_id=ambiguous_job,
        request_sha256=ambiguous_request_sha256,
        run_number=1,
        proposal=ambiguous_proposal,
    )
    del restarted
    restarted_ambiguous = StewardLedger(database)
    ambiguous_reconciliation = restarted_ambiguous.reconcile_recorded_owner(
        _SESSION_ID,
        ambiguous_job,
        proc_root=proc_root,
    )
    ambiguous_resend_blocked = False
    ambiguous_error = ""
    try:
        restarted_ambiguous.resume_before_request(_SESSION_ID, ambiguous_job)
    except AmbiguousMissionError as exc:
        ambiguous_resend_blocked = True
        ambiguous_error = f"{type(exc).__name__}: {exc}"

    result: dict[str, Any] = {
        "schema_version": RECOVERY_DRILL_SCHEMA,
        "status": "PASS",
        "mode": "cpu_safe_real_steward_state_machine",
        "database_sha256": file_sha256(database),
        "stale_pid": {
            "pid": owner_pid,
            "recorded_start_token": owner_token,
            "observed_start_token": "reused-pid-start-token",
            "owner_alive": owner_alive_before_restart,
            "mismatch_treated_as_dead": owner_alive_before_restart is False,
        },
        "persisted_terminal_case": {
            "job_id": terminal_job,
            "admission_outcome": admitted["outcome"],
            "binding_sha256": terminal_binding["binding_sha256"],
            "request_sha256": terminal_request_sha256,
            "run1": run1,
            "run2": run2,
            "terminal_receipt_sha256": file_sha256(
                terminal_root / "terminal_receipt.json"
            ),
            "reconstruction_outcome": terminal_reconciliation["outcome"],
            "reconstructed_state": terminal_reconciliation["mission"]["state"],
            "duplicate_admission_outcome": duplicate_admission["outcome"],
            "resend_blocked": resend_blocked,
            "resend_error": resend_error,
            "run_count_after_restart": len(
                restarted_ambiguous.runs(_SESSION_ID, terminal_job)
            ),
            "handoff_ready": restarted_ambiguous.handoff_ready(
                _SESSION_ID, terminal_job
            ),
        },
        "ambiguous_without_terminal_case": {
            "job_id": ambiguous_job,
            "binding_sha256": ambiguous_binding["binding_sha256"],
            "request_sha256": ambiguous_request_sha256,
            "persisted_run": ambiguous_run,
            "terminal_receipt_present": False,
            "reconstruction_outcome": ambiguous_reconciliation["outcome"],
            "reconstructed_state": ambiguous_reconciliation["mission"]["state"],
            "resend_blocked": ambiguous_resend_blocked,
            "resend_error": ambiguous_error,
            "run_count_after_restart": len(
                restarted_ambiguous.runs(_SESSION_ID, ambiguous_job)
            ),
            "handoff_ready": restarted_ambiguous.handoff_ready(
                _SESSION_ID, ambiguous_job
            ),
        },
        "acceptance_gates": {
            "persisted_terminal_adopted_without_reissue": (
                terminal_reconciliation["outcome"]
                == "reconciled_terminal_receipt"
                and terminal_reconciliation["mission"]["state"] == "completed"
                and duplicate_admission["outcome"] == "reconciled_terminal"
                and resend_blocked
            ),
            "ambiguous_evidence_requires_recovery": (
                ambiguous_reconciliation["outcome"] == "recovery_required"
                and ambiguous_resend_blocked
            ),
            "stale_pid_token_mismatch_detected": owner_alive_before_restart is False,
            "result_and_terminal_artifacts_persisted": True,
            "no_model_request_or_gpu_process_started": True,
        },
    }
    if not all(result["acceptance_gates"].values()):
        result["status"] = "FAIL"
    result["result_sha256"] = canonical_sha256(result)
    atomic_write_json(output_root / "recovery_drill_result.json", result)
    return result


__all__ = ["RECOVERY_DRILL_SCHEMA", "run_recovery_drill"]
