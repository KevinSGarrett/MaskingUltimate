from __future__ import annotations

from pathlib import Path

import pytest

from maskfactory.steward.continuous_ledger import (
    CONTINUOUS_BINDING_SCHEMA,
    ContinuousLedgerError,
    ContinuousWorkLedger,
    seal_continuous_binding,
)


def _binding(
    *,
    work_kind: str,
    work_id: str,
    payload: str,
    campaign_id: str | None = None,
) -> dict:
    return seal_continuous_binding(
        {
            "schema_version": CONTINUOUS_BINDING_SCHEMA,
            "work_kind": work_kind,
            "session_id": "session-1",
            "work_id": work_id,
            "campaign_id": campaign_id,
            "payload_sha256": payload,
            "policy_sha256": "b" * 64,
            "tool_sha256": "c" * 64,
            "runtime_sha256": "d" * 64,
            "dependency_ids": [],
            "supersedes_ids": [],
            "allowed_outputs": ["patch.diff", "tests.json"],
            "authority_ceiling": {
                "git": False,
                "infrastructure": False,
                "tracker": False,
            },
        }
    )


def _register_campaign(ledger: ContinuousWorkLedger) -> dict:
    binding = _binding(work_kind="campaign", work_id="campaign-1", payload="a" * 64)
    ledger.register(binding)
    return binding


def test_same_digest_replay_and_different_body_collision(tmp_path: Path) -> None:
    ledger = ContinuousWorkLedger(tmp_path / "ledger.sqlite")
    binding = _register_campaign(ledger)

    assert ledger.register(binding)["outcome"] == "replayed"
    collision = dict(binding)
    collision["payload_sha256"] = "e" * 64
    collision = seal_continuous_binding(collision)
    with pytest.raises(ContinuousLedgerError, match="different immutable bytes"):
        ledger.register(collision)


def test_duplicate_payload_is_suppressed_across_work_ids(tmp_path: Path) -> None:
    ledger = ContinuousWorkLedger(tmp_path / "ledger.sqlite")
    _register_campaign(ledger)
    duplicate = _binding(work_kind="campaign", work_id="campaign-2", payload="a" * 64)

    result = ledger.register(duplicate)

    assert result["outcome"] == "duplicate_payload"
    assert result["work"]["work_id"] == "campaign-1"


def test_mission_requires_registered_nonterminal_campaign(tmp_path: Path) -> None:
    ledger = ContinuousWorkLedger(tmp_path / "ledger.sqlite")
    mission = _binding(
        work_kind="mission",
        work_id="mission-1",
        campaign_id="missing",
        payload="1" * 64,
    )

    with pytest.raises(ContinuousLedgerError, match="nonterminal campaign"):
        ledger.register(mission)


def test_closed_transition_graph_reaches_released_terminal(tmp_path: Path) -> None:
    ledger = ContinuousWorkLedger(tmp_path / "ledger.sqlite")
    _register_campaign(ledger)
    evidence = "f" * 64

    for state, kwargs in (
        ("intent_persisted", {}),
        ("admitted", {}),
        (
            "running",
            {
                "owner_pid": 123,
                "owner_start_token": "start-123",
                "selected_route": "cpu_safe",
            },
        ),
        ("response_persisted", {}),
        ("validated", {}),
        ("accepted", {}),
        ("released", {}),
        ("terminal", {"terminal_outcome": "accepted"}),
    ):
        ledger.transition(
            "session-1",
            "campaign",
            "campaign-1",
            to_state=state,
            evidence_sha256=evidence,
            **kwargs,
        )

    record = ledger.get("session-1", "campaign", "campaign-1")
    events = ledger.transitions("session-1", "campaign", "campaign-1")
    assert record is not None and record["state"] == "terminal"
    assert record["terminal_outcome"] == "accepted"
    assert len(events) == 9
    assert all(
        current["previous_event_sha256"] == previous["event_sha256"]
        for previous, current in zip(events, events[1:])
    )
    with pytest.raises(ContinuousLedgerError, match="illegal"):
        ledger.transition(
            "session-1",
            "campaign",
            "campaign-1",
            to_state="planned",
            evidence_sha256=evidence,
        )


def test_stale_pid_token_enters_recovery_required(tmp_path: Path) -> None:
    ledger = ContinuousWorkLedger(tmp_path / "ledger.sqlite")
    _register_campaign(ledger)
    evidence = "f" * 64
    ledger.transition(
        "session-1",
        "campaign",
        "campaign-1",
        to_state="intent_persisted",
        evidence_sha256=evidence,
    )
    ledger.transition(
        "session-1",
        "campaign",
        "campaign-1",
        to_state="admitted",
        evidence_sha256=evidence,
    )
    ledger.transition(
        "session-1",
        "campaign",
        "campaign-1",
        to_state="running",
        evidence_sha256=evidence,
        owner_pid=123,
        owner_start_token="start-123",
        selected_route="local_pod",
    )

    result = ledger.reconcile_owner(
        "session-1",
        "campaign",
        "campaign-1",
        process_identity_probe=lambda _pid: "reused-123",
        evidence_sha256="9" * 64,
    )

    assert result["outcome"] == "recovery_required"
    assert result["work"]["state"] == "recovery_required"


def test_state_persists_across_ledger_reconstruction(tmp_path: Path) -> None:
    database = tmp_path / "ledger.sqlite"
    first = ContinuousWorkLedger(database)
    binding = _register_campaign(first)
    first.transition(
        "session-1",
        "campaign",
        "campaign-1",
        to_state="intent_persisted",
        evidence_sha256=binding["binding_sha256"],
    )

    reconstructed = ContinuousWorkLedger(database)

    assert reconstructed.get("session-1", "campaign", "campaign-1")["state"] == (
        "intent_persisted"
    )
    assert len(reconstructed.transitions("session-1", "campaign", "campaign-1")) == 2
