from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from maskfactory.steward.route_control import (
    CanonicalMissionRouteLedger,
    CanonicalParentChildLedger,
    ParentChildAlreadyActive,
    ParentChildBindingError,
    RouteAlreadyActive,
    RouteControlError,
    RouteIdentityMismatch,
    RouteOutcomeUnknown,
)

MISSION = "1" * 64
PAYLOAD = "a" * 64
SESSION = "019f91d1-ea20-7d81-83ff-03d393eaa1f5"
TOKEN = "maskfactory-owner-token-" + "x" * 32
PARENT = "b" * 64
PARENT_CONTRACT = "c" * 64
REQUIRED_ROLES = ("consolidated_advisory", "serverless_execution")


def claim(
    ledger: CanonicalMissionRouteLedger,
    route: str,
    *,
    token: str = TOKEN,
    session: str = SESSION,
) -> dict[str, object]:
    return ledger.claim_route(
        mission_id=MISSION,
        session_id=session,
        payload_sha256=PAYLOAD,
        route=route,
        owner_token=token,
    )


def test_local_must_release_before_serverless_route_change(tmp_path: Path) -> None:
    ledger = CanonicalMissionRouteLedger(tmp_path / "routes.sqlite")
    assert claim(ledger, "local_pod")["generation"] == 1
    with pytest.raises(RouteAlreadyActive):
        claim(ledger, "serverless_overflow")

    ledger.release_unavailable(
        mission_id=MISSION,
        owner_token=TOKEN,
        reason="local admission found an active foreign process",
    )
    serverless = claim(ledger, "serverless_overflow")
    assert serverless["generation"] == 2
    assert serverless["route"] == "serverless_overflow"


def test_serverless_unknown_blocks_every_route_until_reconciled(
    tmp_path: Path,
) -> None:
    ledger = CanonicalMissionRouteLedger(tmp_path / "routes.sqlite")
    claim(ledger, "serverless_overflow")
    ledger.mark_outcome_unknown(
        mission_id=MISSION,
        owner_token=TOKEN,
        reason="broker reserve acknowledgement was interrupted",
    )
    with pytest.raises(RouteOutcomeUnknown):
        claim(ledger, "openrouter_advisory")

    ledger.reconcile_unknown(
        mission_id=MISSION,
        owner_token=TOKEN,
        resolution="not_submitted",
        reason="authoritative broker report found no matching canonical payload",
    )
    assert claim(ledger, "openrouter_advisory")["generation"] == 2


def test_openrouter_rejection_releases_to_cpu_without_dual_route(
    tmp_path: Path,
) -> None:
    ledger = CanonicalMissionRouteLedger(tmp_path / "routes.sqlite")
    claim(ledger, "openrouter_advisory")
    state = ledger.release_unavailable(
        mission_id=MISSION,
        owner_token=TOKEN,
        reason="governed manager rejected budget admission",
    )
    assert state["state"] == "available"
    assert [event["event"] for event in ledger.events(MISSION)] == [
        "route_claimed",
        "route_released_unavailable",
    ]


def test_restart_reconstructs_same_claim_without_new_generation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "routes.sqlite"
    first = CanonicalMissionRouteLedger(database)
    original = claim(first, "local_pod")

    restarted = CanonicalMissionRouteLedger(database)
    reconstructed = claim(restarted, "local_pod")
    assert reconstructed == original
    assert len(restarted.events(MISSION)) == 1
    with pytest.raises(RouteAlreadyActive):
        claim(restarted, "local_pod", token="different-token-" + "z" * 32)


def test_terminal_persistence_blocks_route_until_release_and_afterward(
    tmp_path: Path,
) -> None:
    ledger = CanonicalMissionRouteLedger(tmp_path / "routes.sqlite")
    claim(ledger, "local_pod")
    ledger.terminalize(
        mission_id=MISSION,
        owner_token=TOKEN,
        disposition="completed",
        result_sha256="b" * 64,
    )
    with pytest.raises(RouteAlreadyActive):
        claim(ledger, "serverless_overflow")
    assert (
        ledger.release_terminal(
            mission_id=MISSION,
            owner_token=TOKEN,
        )["state"]
        == "completed"
    )
    with pytest.raises(RouteControlError, match="already terminal"):
        claim(ledger, "serverless_overflow")


def test_cross_session_identity_reuse_fails_closed(tmp_path: Path) -> None:
    ledger = CanonicalMissionRouteLedger(tmp_path / "routes.sqlite")
    claim(ledger, "local_pod")
    with pytest.raises(RouteIdentityMismatch):
        claim(
            ledger,
            "local_pod",
            session="019f9200-4805-7632-83d3-ee9ae614c603",
        )


def test_concurrent_session_race_admits_exactly_one_route(
    tmp_path: Path,
) -> None:
    database = tmp_path / "routes.sqlite"
    sessions = [SESSION, "019f9200-4805-7632-83d3-ee9ae614c603"]

    def compete(index: int) -> str:
        ledger = CanonicalMissionRouteLedger(database)
        try:
            claim(
                ledger,
                "local_pod" if index == 0 else "serverless_overflow",
                token=f"race-owner-{index}-" + "r" * 32,
                session=sessions[index],
            )
        except (RouteAlreadyActive, RouteIdentityMismatch):
            return "blocked"
        return "admitted"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(compete, range(2)))
    assert sorted(results) == ["admitted", "blocked"]


def test_reconciled_completed_unknown_never_reopens(tmp_path: Path) -> None:
    ledger = CanonicalMissionRouteLedger(tmp_path / "routes.sqlite")
    claim(ledger, "serverless_overflow")
    ledger.mark_outcome_unknown(
        mission_id=MISSION,
        owner_token=TOKEN,
        reason="submit acknowledgement missing",
    )
    assert (
        ledger.reconcile_unknown(
            mission_id=MISSION,
            owner_token=TOKEN,
            resolution="completed",
            reason="broker terminal response matched the canonical payload",
        )["state"]
        == "completed"
    )
    with pytest.raises(RouteControlError, match="already terminal"):
        claim(ledger, "openrouter_advisory")


def parent_ledger(path: Path) -> CanonicalParentChildLedger:
    CanonicalMissionRouteLedger(path)
    return CanonicalParentChildLedger(path)


def bind_parent_child(
    ledger: CanonicalParentChildLedger,
    *,
    role: str,
    mission_id: str,
    payload_sha256: str,
    token: str = TOKEN,
    parent_contract_sha256: str = PARENT_CONTRACT,
    session_id: str = SESSION,
) -> dict[str, object]:
    return ledger.bind_child(
        parent_campaign_id=PARENT,
        parent_contract_sha256=parent_contract_sha256,
        required_child_roles=REQUIRED_ROLES,
        child_role=role,
        mission_id=mission_id,
        session_id=session_id,
        route=("serverless_overflow" if role == "serverless_execution" else "openrouter_advisory"),
        payload_sha256=payload_sha256,
        owner_token=token,
    )


def test_parent_allows_one_concurrent_child_per_declared_role(
    tmp_path: Path,
) -> None:
    ledger = parent_ledger(tmp_path / "routes.sqlite")
    bind_parent_child(
        ledger,
        role="serverless_execution",
        mission_id="2" * 64,
        payload_sha256="d" * 64,
    )
    bind_parent_child(
        ledger,
        role="consolidated_advisory",
        mission_id="3" * 64,
        payload_sha256="e" * 64,
    )
    ledger.mark_child(
        parent_campaign_id=PARENT,
        child_role="serverless_execution",
        owner_token=TOKEN,
        state="active",
    )
    parent = ledger.mark_child(
        parent_campaign_id=PARENT,
        child_role="consolidated_advisory",
        owner_token=TOKEN,
        state="active",
    )

    assert parent["state"] == "in_progress"
    assert len(parent["children"]) == 2


def test_parent_role_rejects_replacement_mission_payload_or_contract(
    tmp_path: Path,
) -> None:
    ledger = parent_ledger(tmp_path / "routes.sqlite")
    bind_parent_child(
        ledger,
        role="serverless_execution",
        mission_id="2" * 64,
        payload_sha256="d" * 64,
    )
    with pytest.raises(ParentChildAlreadyActive):
        bind_parent_child(
            ledger,
            role="serverless_execution",
            mission_id="4" * 64,
            payload_sha256="f" * 64,
        )
    with pytest.raises(ParentChildAlreadyActive):
        bind_parent_child(
            ledger,
            role="serverless_execution",
            mission_id="2" * 64,
            payload_sha256="f" * 64,
        )
    with pytest.raises(ParentChildBindingError, match="parent campaign identity"):
        bind_parent_child(
            ledger,
            role="consolidated_advisory",
            mission_id="3" * 64,
            payload_sha256="e" * 64,
            parent_contract_sha256="9" * 64,
        )
    with pytest.raises(ParentChildBindingError, match="parent campaign identity"):
        bind_parent_child(
            ledger,
            role="consolidated_advisory",
            mission_id="3" * 64,
            payload_sha256="e" * 64,
            session_id="different-session",
        )


def test_child_mission_cannot_be_reused_for_another_parent_role(
    tmp_path: Path,
) -> None:
    ledger = parent_ledger(tmp_path / "routes.sqlite")
    bind_parent_child(
        ledger,
        role="serverless_execution",
        mission_id="2" * 64,
        payload_sha256="d" * 64,
    )

    with pytest.raises(
        ParentChildBindingError,
        match="already attached to another parent role",
    ):
        bind_parent_child(
            ledger,
            role="consolidated_advisory",
            mission_id="2" * 64,
            payload_sha256="e" * 64,
        )


def test_existing_unbound_canonical_mission_cannot_be_attached(
    tmp_path: Path,
) -> None:
    database = tmp_path / "routes.sqlite"
    route_ledger = CanonicalMissionRouteLedger(database)
    route_ledger.claim_route(
        mission_id="2" * 64,
        session_id=SESSION,
        payload_sha256="d" * 64,
        route="serverless_overflow",
        owner_token=TOKEN,
    )
    ledger = CanonicalParentChildLedger(database)

    with pytest.raises(
        ParentChildBindingError,
        match="cannot be attached retroactively",
    ):
        bind_parent_child(
            ledger,
            role="serverless_execution",
            mission_id="2" * 64,
            payload_sha256="d" * 64,
        )


def test_parent_closes_only_after_all_declared_roles_have_final_results(
    tmp_path: Path,
) -> None:
    ledger = parent_ledger(tmp_path / "routes.sqlite")
    bind_parent_child(
        ledger,
        role="serverless_execution",
        mission_id="2" * 64,
        payload_sha256="d" * 64,
    )
    bind_parent_child(
        ledger,
        role="consolidated_advisory",
        mission_id="3" * 64,
        payload_sha256="e" * 64,
    )
    parent = ledger.mark_child(
        parent_campaign_id=PARENT,
        child_role="serverless_execution",
        owner_token=TOKEN,
        state="terminal_pending_release",
    )
    assert parent["state"] == "in_progress"
    parent = ledger.mark_child(
        parent_campaign_id=PARENT,
        child_role="serverless_execution",
        owner_token=TOKEN,
        state="completed",
        terminal_disposition="completed",
        result_sha256="6" * 64,
    )
    assert parent["state"] == "in_progress"
    parent = ledger.mark_child(
        parent_campaign_id=PARENT,
        child_role="consolidated_advisory",
        owner_token=TOKEN,
        state="unavailable",
        terminal_disposition="unavailable",
        result_sha256="7" * 64,
        reason="governed manager rejected admission",
    )

    assert parent["state"] == "failed"
    assert parent["missing_child_roles"] == []


def test_parent_outcome_unknown_blocks_closure(tmp_path: Path) -> None:
    ledger = parent_ledger(tmp_path / "routes.sqlite")
    bind_parent_child(
        ledger,
        role="serverless_execution",
        mission_id="2" * 64,
        payload_sha256="d" * 64,
    )
    bind_parent_child(
        ledger,
        role="consolidated_advisory",
        mission_id="3" * 64,
        payload_sha256="e" * 64,
    )
    ledger.mark_child(
        parent_campaign_id=PARENT,
        child_role="serverless_execution",
        owner_token=TOKEN,
        state="completed",
        terminal_disposition="completed",
        result_sha256="6" * 64,
    )
    parent = ledger.mark_child(
        parent_campaign_id=PARENT,
        child_role="consolidated_advisory",
        owner_token=TOKEN,
        state="outcome_unknown",
        reason="provider acknowledgement is ambiguous",
    )

    assert parent["state"] == "outcome_unknown"


def test_parent_terminal_reconstruction_is_exact_and_token_independent(
    tmp_path: Path,
) -> None:
    ledger = parent_ledger(tmp_path / "routes.sqlite")
    bind_parent_child(
        ledger,
        role="serverless_execution",
        mission_id="2" * 64,
        payload_sha256="d" * 64,
    )
    ledger.mark_child(
        parent_campaign_id=PARENT,
        child_role="serverless_execution",
        owner_token=TOKEN,
        state="completed",
        terminal_disposition="completed",
        result_sha256="6" * 64,
    )
    reconstructed = ledger.mark_child(
        parent_campaign_id=PARENT,
        child_role="serverless_execution",
        owner_token="reconstructed-owner-" + "x" * 32,
        state="completed",
        terminal_disposition="completed",
        result_sha256="6" * 64,
    )
    assert reconstructed["children"][0]["result_sha256"] == "6" * 64

    with pytest.raises(
        ParentChildBindingError,
        match="cannot be rewritten",
    ):
        ledger.mark_child(
            parent_campaign_id=PARENT,
            child_role="serverless_execution",
            owner_token="reconstructed-owner-" + "x" * 32,
            state="completed",
            terminal_disposition="completed",
            result_sha256="7" * 64,
        )


def test_parent_role_race_admits_exactly_one_child_identity(
    tmp_path: Path,
) -> None:
    database = tmp_path / "routes.sqlite"

    def compete(index: int) -> str:
        CanonicalMissionRouteLedger(database)
        ledger = CanonicalParentChildLedger(database)
        try:
            bind_parent_child(
                ledger,
                role="serverless_execution",
                mission_id=str(index + 2) * 64,
                payload_sha256=str(index + 4) * 64,
                token=f"parent-race-{index}-" + "x" * 32,
            )
        except ParentChildAlreadyActive:
            return "blocked"
        return "admitted"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(compete, range(2)))

    assert sorted(results) == ["admitted", "blocked"]
