from __future__ import annotations

from copy import deepcopy

import pytest

from maskfactory.steward import (
    AmbiguousMissionError,
    AuthorityCeilingError,
    DeterminismError,
    MissionBindingError,
    MissionConflictError,
    StewardLedger,
    seal_binding,
)
from maskfactory.steward.core import TERMINAL_RECEIPT_SCHEMA

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64
H5 = "5" * 64
H6 = "6" * 64


def binding(*, job_id: str = "job-1", payload_sha256: str = H1) -> dict:
    return seal_binding(
        {
            "schema_version": "maskfactory_self_hosted_steward_binding.v1",
            "session_id": "session-1",
            "job_id": job_id,
            "payload_sha256": payload_sha256,
            "model_tree_sha256": H2,
            "runtime_sha256": H3,
            "input_sha256": {"prompt.txt": H4},
            "output_namespace": f"session-1/{job_id}",
            "requires_replay": True,
            "authority": {
                "repository_mutation": False,
                "git": False,
                "tracker": False,
                "infrastructure": False,
                "runpod_control": False,
                "secret_access": False,
                "tool_invocation": False,
                "final_acceptance": False,
            },
        }
    )


def running(
    ledger: StewardLedger,
    mission_binding: dict | None = None,
    *,
    request_intent: bool = True,
) -> dict:
    mission_binding = mission_binding or binding()
    ledger.admit(mission_binding)
    result = ledger.mark_running(
        mission_binding["session_id"],
        mission_binding["job_id"],
        owner_pid=1234,
        owner_start_token="linux-proc-start-100",
    )
    if request_intent:
        result = ledger.record_request_intent(
            mission_binding["session_id"],
            mission_binding["job_id"],
            request_sha256=H1,
        )
    return result


def record_two_runs(ledger: StewardLedger, job_id: str = "job-1") -> None:
    ledger.record_run(
        "session-1",
        job_id,
        run_number=1,
        request_sha256=H1,
        response_sha256=H2,
        proposal_sha256=H3,
        proposal_canonical_sha256=H4,
    )
    ledger.record_run(
        "session-1",
        job_id,
        run_number=2,
        request_sha256=H1,
        response_sha256=H5,
        proposal_sha256=H6,
        proposal_canonical_sha256=H4,
    )


def test_binding_and_duplicate_suppression(tmp_path) -> None:
    ledger = StewardLedger(tmp_path / "steward.sqlite")
    mission_binding = binding()

    admitted = ledger.admit(mission_binding)
    duplicate = ledger.admit(mission_binding)
    same_payload = ledger.admit(binding(job_id="job-2"))

    assert admitted["outcome"] == "admitted"
    assert duplicate["outcome"] == "duplicate_nonterminal"
    assert same_payload["outcome"] == "duplicate_payload"
    assert same_payload["mission"]["job_id"] == "job-1"

    conflicting = deepcopy(mission_binding)
    conflicting["payload_sha256"] = H6
    conflicting = seal_binding({k: v for k, v in conflicting.items() if k != "binding_sha256"})
    with pytest.raises(MissionConflictError, match="different immutable work"):
        ledger.admit(conflicting)


def test_binding_fails_closed_on_namespace_authority_or_self_hash(tmp_path) -> None:
    ledger = StewardLedger(tmp_path / "steward.sqlite")

    wrong_namespace = binding()
    wrong_namespace["output_namespace"] = "job-1"
    wrong_namespace = seal_binding(
        {k: v for k, v in wrong_namespace.items() if k != "binding_sha256"}
    )
    with pytest.raises(MissionBindingError, match="output_namespace"):
        ledger.admit(wrong_namespace)

    for denied_authority in (
        "secret_access",
        "tool_invocation",
        "git",
        "runpod_control",
    ):
        authority = binding()
        authority["authority"][denied_authority] = True
        authority = seal_binding({k: v for k, v in authority.items() if k != "binding_sha256"})
        with pytest.raises(MissionBindingError, match="authority ceiling"):
            ledger.admit(authority)

    tampered = binding()
    tampered["model_tree_sha256"] = H6
    with pytest.raises(MissionBindingError, match="self-hash"):
        ledger.admit(tampered)


def test_deterministic_replay_allows_raw_envelope_differences(tmp_path) -> None:
    ledger = StewardLedger(tmp_path / "steward.sqlite")
    running(ledger)
    record_two_runs(ledger)

    completed = ledger.complete(
        "session-1",
        "job-1",
        proposal_canonical_sha256=H4,
        authority_claimed=False,
    )
    replay = ledger.admit(binding())

    assert completed["state"] == "completed"
    assert replay["outcome"] == "reconciled_terminal"
    assert not ledger.handoff_ready("session-1", "job-1")

    released = ledger.record_release(
        "session-1",
        "job-1",
        release_kind="direct_process_exit",
        release_sha256=H6,
    )
    assert released["release_sha256"] == H6
    assert ledger.handoff_ready("session-1", "job-1")


def test_replay_drift_is_durably_failed(tmp_path) -> None:
    ledger = StewardLedger(tmp_path / "steward.sqlite")
    running(ledger)
    ledger.record_run(
        "session-1",
        "job-1",
        run_number=1,
        request_sha256=H1,
        response_sha256=H2,
        proposal_sha256=H3,
        proposal_canonical_sha256=H4,
    )

    with pytest.raises(DeterminismError, match="drift"):
        ledger.record_run(
            "session-1",
            "job-1",
            run_number=2,
            request_sha256=H1,
            response_sha256=H5,
            proposal_sha256=H6,
            proposal_canonical_sha256=H5,
        )

    assert ledger.get("session-1", "job-1")["state"] == "failed"
    assert len(ledger.runs("session-1", "job-1")) == 1


def test_dead_owner_recovery_refuses_ambiguous_resubmission(tmp_path) -> None:
    ledger = StewardLedger(tmp_path / "steward.sqlite")
    running(ledger)

    result = ledger.reconcile("session-1", "job-1", owner_alive=False)

    assert result["outcome"] == "recovery_required"
    with pytest.raises(AmbiguousMissionError, match="terminal reconciliation"):
        ledger.resume_before_request("session-1", "job-1")


def test_dead_owner_before_request_can_resume_once(tmp_path) -> None:
    ledger = StewardLedger(tmp_path / "steward.sqlite")
    running(ledger, request_intent=False)
    ledger.reconcile("session-1", "job-1", owner_alive=False)

    resumed = ledger.resume_before_request("session-1", "job-1")

    assert resumed["state"] == "admitted"
    assert ledger.runs("session-1", "job-1") == []


def test_terminal_receipt_reconciles_without_new_model_call(tmp_path) -> None:
    ledger = StewardLedger(tmp_path / "steward.sqlite")
    mission_binding = binding()
    running(ledger, mission_binding)
    record_two_runs(ledger)
    receipt = {
        "schema_version": TERMINAL_RECEIPT_SCHEMA,
        "session_id": "session-1",
        "job_id": "job-1",
        "payload_sha256": mission_binding["payload_sha256"],
        "binding_sha256": mission_binding["binding_sha256"],
        "state": "completed",
        "proposal_canonical_sha256": H4,
        "authority_claimed": False,
    }

    interrupted = ledger.reconcile("session-1", "job-1", owner_alive=False)
    result = ledger.reconcile(
        "session-1",
        "job-1",
        owner_alive=False,
        terminal_receipt=receipt,
    )

    assert interrupted["outcome"] == "recovery_required"
    assert result["outcome"] == "reconciled_terminal_receipt"
    assert result["mission"]["state"] == "completed"
    assert len(ledger.runs("session-1", "job-1")) == 2


def test_authority_claim_is_durably_rejected(tmp_path) -> None:
    ledger = StewardLedger(tmp_path / "steward.sqlite")
    running(ledger)
    record_two_runs(ledger)

    with pytest.raises(AuthorityCeilingError, match="authority ceiling"):
        ledger.complete(
            "session-1",
            "job-1",
            proposal_canonical_sha256=H4,
            authority_claimed=True,
        )

    mission = ledger.get("session-1", "job-1")
    assert mission["state"] == "failed"
    assert not ledger.handoff_ready("session-1", "job-1")


def test_request_intent_is_one_shot_and_cannot_change(tmp_path) -> None:
    ledger = StewardLedger(tmp_path / "steward.sqlite")
    running(ledger, request_intent=False)

    recorded = ledger.record_request_intent(
        "session-1",
        "job-1",
        request_sha256=H1,
    )

    assert recorded["request_sha256"] == H1
    with pytest.raises(AmbiguousMissionError, match="do not reissue"):
        ledger.record_request_intent(
            "session-1",
            "job-1",
            request_sha256=H1,
        )
    with pytest.raises(MissionConflictError, match="different request intent"):
        ledger.record_request_intent(
            "session-1",
            "job-1",
            request_sha256=H2,
        )


def test_run_evidence_requires_prior_matching_request_intent(tmp_path) -> None:
    ledger = StewardLedger(tmp_path / "steward.sqlite")
    running(ledger, request_intent=False)

    with pytest.raises(MissionConflictError, match="request intent"):
        ledger.record_run(
            "session-1",
            "job-1",
            run_number=1,
            request_sha256=H1,
            response_sha256=H2,
            proposal_sha256=H3,
            proposal_canonical_sha256=H4,
        )


def test_stale_reused_pid_does_not_count_as_owned_process(tmp_path) -> None:
    ledger = StewardLedger(tmp_path / "steward.sqlite")
    running(ledger)
    proc_root = tmp_path / "proc"
    stat_path = proc_root / "1234" / "stat"
    stat_path.parent.mkdir(parents=True)
    fields = ["S", *(["0"] * 18), "different-start-token"]
    stat_path.write_text(f"1234 (worker) {' '.join(fields)}\n", encoding="utf-8")

    result = ledger.reconcile_recorded_owner(
        "session-1",
        "job-1",
        proc_root=proc_root,
    )

    assert result["outcome"] == "recovery_required"


def test_exact_pid_start_token_keeps_live_owner(tmp_path) -> None:
    ledger = StewardLedger(tmp_path / "steward.sqlite")
    running(ledger)
    proc_root = tmp_path / "proc"
    stat_path = proc_root / "1234" / "stat"
    stat_path.parent.mkdir(parents=True)
    fields = ["S", *(["0"] * 18), "linux-proc-start-100"]
    stat_path.write_text(f"1234 (worker name) {' '.join(fields)}\n", encoding="utf-8")

    result = ledger.reconcile_recorded_owner(
        "session-1",
        "job-1",
        proc_root=proc_root,
    )

    assert result["outcome"] == "owner_still_running"


def test_zombie_with_exact_pid_start_token_is_not_live_owner(tmp_path) -> None:
    ledger = StewardLedger(tmp_path / "steward.sqlite")
    running(ledger)
    proc_root = tmp_path / "proc"
    stat_path = proc_root / "1234" / "stat"
    stat_path.parent.mkdir(parents=True)
    fields = ["Z", *(["0"] * 18), "linux-proc-start-100"]
    stat_path.write_text(f"1234 (worker name) {' '.join(fields)}\n", encoding="utf-8")

    result = ledger.reconcile_recorded_owner(
        "session-1",
        "job-1",
        proc_root=proc_root,
    )

    assert result["outcome"] == "recovery_required"
