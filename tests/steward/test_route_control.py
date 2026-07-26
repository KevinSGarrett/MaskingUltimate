from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from maskfactory.steward.route_control import (
    CanonicalMissionRouteLedger,
    RouteAlreadyActive,
    RouteControlError,
    RouteIdentityMismatch,
    RouteOutcomeUnknown,
)

MISSION = "1" * 64
PAYLOAD = "a" * 64
SESSION = "019f91d1-ea20-7d81-83ff-03d393eaa1f5"
TOKEN = "maskfactory-owner-token-" + "x" * 32


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
