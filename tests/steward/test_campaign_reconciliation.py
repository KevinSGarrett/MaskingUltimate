from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from maskfactory.steward.campaign_reconciliation import (
    CampaignReconciliationError,
    reconcile_closed_campaign,
    seal_artifact_manifest,
    validate_closed_campaign_reconciliation,
)
from maskfactory.steward.campaign_telemetry import (
    build_telemetry_event,
    reconcile_campaign_telemetry,
)
from maskfactory.steward.continuous_ledger import (
    CONTINUOUS_BINDING_SCHEMA,
    ContinuousWorkLedger,
    seal_continuous_binding,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_ID = "session-reconcile"
CAMPAIGN_ID = "campaign-reconcile-001"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


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
            "session_id": SESSION_ID,
            "work_id": work_id,
            "campaign_id": campaign_id,
            "payload_sha256": payload,
            "policy_sha256": _digest("policy"),
            "tool_sha256": _digest("tool"),
            "runtime_sha256": _digest("runtime"),
            "dependency_ids": [],
            "supersedes_ids": [],
            "allowed_outputs": ["artifacts"],
            "authority_ceiling": {
                "git": False,
                "infrastructure": False,
                "tracker": False,
            },
        }
    )


def _terminalize(
    ledger: ContinuousWorkLedger,
    *,
    work_kind: str,
    work_id: str,
    route: str,
    outcome: str,
) -> None:
    evidence = _digest(f"{work_kind}:{work_id}")
    for state, kwargs in (
        ("intent_persisted", {}),
        ("admitted", {}),
        (
            "running",
            {
                "owner_pid": 101,
                "owner_start_token": f"owner-{work_id}",
                "selected_route": route,
            },
        ),
        ("response_persisted", {}),
        ("validated", {}),
        ("accepted", {}),
        ("released", {}),
        ("terminal", {"terminal_outcome": outcome}),
    ):
        ledger.transition(
            SESSION_ID,
            work_kind,
            work_id,
            to_state=state,
            evidence_sha256=evidence,
            **kwargs,
        )


def _fixture(tmp_path: Path) -> dict:
    database = tmp_path / "ledger.sqlite"
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    ledger = ContinuousWorkLedger(database)
    campaign_payload = _digest("campaign")
    ledger.register(
        _binding(
            work_kind="campaign",
            work_id=CAMPAIGN_ID,
            payload=campaign_payload,
        )
    )
    routes = {"mission-00": "local_pod", "mission-01": "cpu_safe"}
    for mission_id, route in routes.items():
        ledger.register(
            _binding(
                work_kind="mission",
                work_id=mission_id,
                campaign_id=CAMPAIGN_ID,
                payload=_digest(mission_id),
            )
        )
        _terminalize(
            ledger,
            work_kind="mission",
            work_id=mission_id,
            route=route,
            outcome="accepted",
        )
    _terminalize(
        ledger,
        work_kind="campaign",
        work_id=CAMPAIGN_ID,
        route="cpu_safe",
        outcome="accepted",
    )

    events: list[dict] = []

    def add(kind: str, mission_id: str | None = None, **kwargs: object) -> None:
        events.append(
            build_telemetry_event(
                campaign_id=CAMPAIGN_ID,
                sequence=len(events) + 1,
                kind=kind,
                mission_id=mission_id,
                **kwargs,
            )
        )

    artifacts: list[dict] = []
    for index, (mission_id, route) in enumerate(routes.items()):
        subject_id = f"artifact-{index:02d}"
        relative_path = f"{subject_id}.txt"
        content = f"exact artifact {index}\n".encode()
        path = artifact_root / relative_path
        path.write_bytes(content)
        add("planned", mission_id)
        add("eligible", mission_id)
        add("route_selected", mission_id, route=route)
        add("autonomously_prepared", mission_id)
        add("admitted", mission_id)
        if route == "local_pod":
            add("local_gpu_work_cell", mission_id, subject_id="cell-00")
            add("local_gpu_release", mission_id, subject_id="cell-00")
        add("completed", mission_id)
        add("artifact_produced", mission_id, subject_id=subject_id)
        if index == 0:
            add("accepted", mission_id)
            add("artifact_accepted", mission_id, subject_id=subject_id)
        add("terminal_reconciled", mission_id)
        artifacts.append(
            {
                "mission_id": mission_id,
                "subject_id": subject_id,
                "relative_path": relative_path,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "accepted": index == 0,
            }
        )

    source = {
        "schema_version": "maskfactory.campaign-telemetry-source.v1",
        "campaign_id": CAMPAIGN_ID,
        "campaign_kind": "engineering",
        "campaign_payload_sha256": campaign_payload,
        "source_commit_sha256": _digest("commit"),
        "started_at": "2026-07-26T20:00:00Z",
        "ended_at": "2026-07-26T20:05:00Z",
        "baseline_usage_units_per_accepted_artifact": 100.0,
        "limitations": ["Focused reconciliation fixture; no production claim."],
    }
    telemetry = reconcile_campaign_telemetry(
        repo_root=REPO_ROOT,
        source=source,
        events=events,
    )
    manifest = seal_artifact_manifest(
        campaign_id=CAMPAIGN_ID,
        artifacts=artifacts,
    )
    kwargs = {
        "repo_root": REPO_ROOT,
        "source": source,
        "events": events,
        "telemetry": telemetry,
        "ledger_database": database,
        "session_id": SESSION_ID,
        "artifact_root": artifact_root,
        "artifact_manifest": manifest,
    }
    return {"kwargs": kwargs, "ledger": ledger}


def test_closed_campaign_reconciles_ledger_transitions_and_artifact_bytes(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)

    receipt = reconcile_closed_campaign(**fixture["kwargs"])

    assert receipt["counts"] == {
        "planned_missions": 2,
        "terminal_ledger_missions": 2,
        "produced_artifacts": 2,
        "accepted_artifacts": 1,
        "local_work_cells": 1,
        "local_releases": 1,
    }
    assert receipt["authority_claimed"] is False
    assert all(row["transition_event_sha256"] for row in receipt["missions"])
    validate_closed_campaign_reconciliation(receipt, **fixture["kwargs"])


def test_nonterminal_ledger_mission_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    database = fixture["kwargs"]["ledger_database"]
    with fixture["ledger"]._connect() as connection:
        connection.execute(
            """
            UPDATE continuous_work SET state = 'released'
            WHERE session_id = ? AND work_kind = 'mission' AND work_id = 'mission-01'
            """,
            (SESSION_ID,),
        )

    with pytest.raises(
        CampaignReconciliationError,
        match="nonterminal ledger work",
    ):
        reconcile_closed_campaign(**fixture["kwargs"] | {"ledger_database": database})


def test_route_drift_between_ledger_and_telemetry_fails_closed(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    with fixture["ledger"]._connect() as connection:
        connection.execute(
            """
            UPDATE continuous_work SET selected_route = 'serverless_overflow'
            WHERE session_id = ? AND work_kind = 'mission' AND work_id = 'mission-01'
            """,
            (SESSION_ID,),
        )

    with pytest.raises(
        CampaignReconciliationError,
        match="routes differ",
    ):
        reconcile_closed_campaign(**fixture["kwargs"])


def test_artifact_byte_or_path_set_drift_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    artifact_root = fixture["kwargs"]["artifact_root"]
    (artifact_root / "artifact-00.txt").write_text("drifted\n", encoding="utf-8")

    with pytest.raises(
        CampaignReconciliationError,
        match="artifact bytes or event binding drifted",
    ):
        reconcile_closed_campaign(**fixture["kwargs"])

    (artifact_root / "extra.txt").write_text("extra\n", encoding="utf-8")
    with pytest.raises(
        CampaignReconciliationError,
        match="path sets differ",
    ):
        reconcile_closed_campaign(**fixture["kwargs"])


def test_accepted_artifact_flag_must_match_telemetry(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    manifest = copy.deepcopy(fixture["kwargs"]["artifact_manifest"])
    manifest["artifacts"][0]["accepted"] = False
    manifest = seal_artifact_manifest(
        campaign_id=CAMPAIGN_ID,
        artifacts=manifest["artifacts"],
    )

    with pytest.raises(
        CampaignReconciliationError,
        match="artifact bytes or event binding drifted",
    ):
        reconcile_closed_campaign(
            **fixture["kwargs"] | {"artifact_manifest": manifest}
        )


def test_missing_local_release_fails_before_receipt(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    events = [
        event
        for event in fixture["kwargs"]["events"]
        if event["kind"] != "local_gpu_release"
    ]
    for sequence, event in enumerate(events, start=1):
        event["sequence"] = sequence
        event["event_sha256"] = "0" * 64
        event["event_sha256"] = hashlib.sha256(
            json.dumps(
                event,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
    telemetry = reconcile_campaign_telemetry(
        repo_root=REPO_ROOT,
        source=fixture["kwargs"]["source"],
        events=events,
    )

    with pytest.raises(
        CampaignReconciliationError,
        match="work-cell release evidence is incomplete",
    ):
        reconcile_closed_campaign(
            **fixture["kwargs"] | {"events": events, "telemetry": telemetry}
        )
