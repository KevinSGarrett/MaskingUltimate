from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from maskfactory.steward.campaign_reconciliation import (
    CampaignReconciliationError,
    evaluate_reconciled_campaign_slo,
    reconcile_closed_campaign,
    seal_artifact_manifest,
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
from maskfactory.steward.engineering_campaign_packet import (
    PACKET_NAME,
    EngineeringCampaignPacketError,
    build_engineering_campaign_packet,
    validate_engineering_campaign_packet,
)
from maskfactory.steward.patch_repair_campaign import (
    CampaignLimits,
    run_patch_repair_campaign,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_ID = "campaign-packet-session"
CAMPAIGN_ID = "engineering-campaign-real-025"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _binding(
    *,
    kind: str,
    work_id: str,
    campaign_id: str | None,
    payload: str,
) -> dict:
    return seal_continuous_binding(
        {
            "schema_version": CONTINUOUS_BINDING_SCHEMA,
            "work_kind": kind,
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
    kind: str,
    work_id: str,
    route: str,
) -> None:
    evidence = _digest(f"{kind}:{work_id}")
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
        ("terminal", {"terminal_outcome": "accepted"}),
    ):
        ledger.transition(
            SESSION_ID,
            kind,
            work_id,
            to_state=state,
            evidence_sha256=evidence,
            **kwargs,
        )


def _fixture(tmp_path: Path) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    ledger_path = tmp_path / "ledger.sqlite"
    artifact_root = tmp_path / "artifacts"
    mission_parent = tmp_path / "missions"
    artifact_root.mkdir()
    mission_parent.mkdir()
    ledger = ContinuousWorkLedger(ledger_path)
    campaign_payload = _digest("real-campaign-payload")
    ledger.register(
        _binding(
            kind="campaign",
            work_id=CAMPAIGN_ID,
            campaign_id=None,
            payload=campaign_payload,
        )
    )

    events: list[dict] = []
    artifacts: list[dict] = []
    mission_roots: list[Path] = []

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

    for index in range(25):
        mission_id = f"mission-{index:02d}"
        payload = _digest(f"packet-{index}")
        route = "local_pod" if index < 20 else "cpu_safe"
        ledger.register(
            _binding(
                kind="mission",
                work_id=mission_id,
                campaign_id=CAMPAIGN_ID,
                payload=payload,
            )
        )
        _terminalize(ledger, kind="mission", work_id=mission_id, route=route)

        mission_root = mission_parent / mission_id
        mission_roots.append(mission_root)
        run_patch_repair_campaign(
            campaign_root=mission_root,
            mission_id=mission_id,
            packet_sha256=payload,
            editable_paths=[f"src/task_{index:02d}.py"],
            limits=CampaignLimits(max_attempts=1, timeout_seconds=60),
            proposal_supplier=lambda attempt, _previous, i=index: {
                "edits": [
                    {
                        "path": f"src/task_{i:02d}.py",
                        "expected_sha256": _digest(f"source-{i}"),
                        "replacement_text": f"value = {i}\n",
                    }
                ],
                "authority_claimed": False,
                "completion_claimed": False,
            },
            attempt_runner=lambda _proposal, _attempt: {
                "passed": True,
                "repairable": False,
                "diagnostic_code": "PASS",
                "diagnostic": "focused test passed",
                "evidence": [
                    {
                        "path": f"tests/task_{index:02d}.txt",
                        "sha256": _digest(f"evidence-{index}"),
                    }
                ],
            },
        )

        artifact = f"accepted project artifact {index}\n".encode()
        relative_path = f"artifact-{index:02d}.txt"
        (artifact_root / relative_path).write_bytes(artifact)
        subject_id = f"artifact-{index:02d}"
        add("planned", mission_id)
        add("eligible", mission_id)
        add("route_selected", mission_id, route=route)
        add("autonomously_prepared", mission_id)
        add("admitted", mission_id)
        if route == "local_pod":
            cell = f"cell-{index:02d}"
            add("local_gpu_work_cell", mission_id, subject_id=cell)
            add("model_startup", mission_id, duration_seconds=1)
            add(
                "inference_submission",
                mission_id,
                subject_id=f"submission-{index:02d}",
            )
            add("inference", mission_id, duration_seconds=2)
            add("local_gpu_release", mission_id, subject_id=cell)
        add("patch_attempt", mission_id)
        add("focused_test_run", mission_id)
        add("completed", mission_id)
        add("artifact_produced", mission_id, subject_id=subject_id)
        add("accepted", mission_id)
        add("artifact_accepted", mission_id, subject_id=subject_id)
        add("terminal_reconciled", mission_id)
        artifacts.append(
            {
                "mission_id": mission_id,
                "subject_id": subject_id,
                "relative_path": relative_path,
                "bytes": len(artifact),
                "sha256": hashlib.sha256(artifact).hexdigest(),
                "accepted": True,
            }
        )

    _terminalize(ledger, kind="campaign", work_id=CAMPAIGN_ID, route="cpu_safe")
    source = {
        "schema_version": "maskfactory.campaign-telemetry-source.v1",
        "campaign_id": CAMPAIGN_ID,
        "campaign_kind": "engineering",
        "campaign_payload_sha256": campaign_payload,
        "source_commit_sha256": _digest("source-commit"),
        "started_at": "2026-07-26T20:00:00Z",
        "ended_at": "2026-07-26T21:00:00Z",
        "baseline_usage_units_per_accepted_artifact": 100.0,
        "limitations": ["Test fixture; not production campaign provenance."],
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
    evidence = {
        "repo_root": REPO_ROOT,
        "source": source,
        "events": events,
        "telemetry": telemetry,
        "ledger_database": ledger_path,
        "session_id": SESSION_ID,
        "artifact_root": artifact_root,
        "artifact_manifest": manifest,
    }
    reconciliation = reconcile_closed_campaign(**evidence)
    gate = evaluate_reconciled_campaign_slo(
        reconciliation=reconciliation,
        **evidence,
    )
    return {
        **evidence,
        "reconciliation": reconciliation,
        "reconciled_slo_gate": gate,
        "mission_roots": mission_roots,
    }


def _build(tmp_path: Path, fixture: dict, **overrides: object) -> dict:
    arguments = {
        **fixture,
        "output_root": tmp_path / "packet",
        "recommendation": "ADOPT",
        "recommendation_reason": "All 25 bounded missions and SLO gates passed.",
        "limitations": ["Codex retains final adoption and tracker authority."],
        "exceptions": [],
        "tracker_proposals": [
            {
                "item_id": "MF-P6-19.01",
                "status": "in_progress",
                "percent": 90,
                "evidence": "One consolidated campaign packet awaits Codex adoption.",
            }
        ],
    }
    arguments.update(overrides)
    return build_engineering_campaign_packet(**arguments)


def test_25_terminal_missions_emit_one_replayable_packet(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    packet = _build(tmp_path, fixture)

    assert packet["mission_count"] == 25
    assert len(packet["mission_order"]) == 25
    assert len(packet["missions"]) == 25
    assert packet["recommendation"] == "ADOPT"
    assert packet["authority"]["final_adoption"] is False
    assert set(path.name for path in (tmp_path / "packet").iterdir()) == {
        PACKET_NAME
    }
    replay = validate_engineering_campaign_packet(
        tmp_path / "packet",
        **fixture,
    )
    assert replay == packet


def test_missing_duplicate_or_reordered_mission_evidence_fails_closed(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    with pytest.raises(
        EngineeringCampaignPacketError,
        match="exactly 25",
    ):
        _build(
            tmp_path,
            fixture,
            mission_roots=fixture["mission_roots"][:-1],
        )

    duplicate = [*fixture["mission_roots"][:-1], fixture["mission_roots"][0]]
    with pytest.raises(
        EngineeringCampaignPacketError,
        match="root names must be unique",
    ):
        _build(tmp_path, fixture, mission_roots=duplicate)

    reordered = list(reversed(fixture["mission_roots"]))
    with pytest.raises(
        EngineeringCampaignPacketError,
        match="ledger order differ",
    ):
        _build(tmp_path, fixture, mission_roots=reordered)


def test_non_success_or_failed_slo_cannot_recommend_adopt(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    mission_terminal = fixture["mission_roots"][0] / "campaign_terminal.json"
    terminal = json.loads(mission_terminal.read_text(encoding="utf-8"))
    terminal["outcome"] = "FAILED_DETERMINISTIC"
    terminal["terminal_sha256"] = "0" * 64
    terminal["terminal_sha256"] = hashlib.sha256(
        json.dumps(
            terminal,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    mission_terminal.write_text(
        json.dumps(terminal, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        EngineeringCampaignPacketError,
        match="ADOPT requires",
    ):
        _build(tmp_path, fixture)

    fixture = _fixture(tmp_path / "second")
    failed_gate = copy.deepcopy(fixture["reconciled_slo_gate"])
    failed_gate["passed"] = False
    failed_gate["gate_sha256"] = "0" * 64
    failed_gate["gate_sha256"] = hashlib.sha256(
        json.dumps(
            failed_gate,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    with pytest.raises(CampaignReconciliationError, match="replay mismatch"):
        _build(tmp_path / "second", fixture, reconciled_slo_gate=failed_gate)


def test_source_or_packet_drift_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _build(tmp_path, fixture)
    packet_path = tmp_path / "packet" / PACKET_NAME
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["recommendation_reason"] = "Invented stronger claim."
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    with pytest.raises(
        EngineeringCampaignPacketError,
        match="self-hash mismatch",
    ):
        validate_engineering_campaign_packet(
            tmp_path / "packet",
            **fixture,
        )
