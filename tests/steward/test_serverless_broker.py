from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from maskfactory.steward.serverless_broker import (
    PROJECT_ROOT,
    BrokerCommandRejected,
    BrokerCommandTimeout,
    BrokerOnlyServerlessRoute,
    ServerlessRouteAmbiguous,
    ServerlessRouteError,
    _default_broker_paths,
)


class FakeBroker:
    def __init__(self, *results: dict[str, Any] | BaseException) -> None:
        self.results = list(results)
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], _timeout: float) -> dict[str, Any]:
        self.commands.append(list(command))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return copy.deepcopy(result)


def payload_sha(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def test_non_windows_defaults_use_committed_manager_and_shared_ledger() -> None:
    manager, config, broker_root = _default_broker_paths(
        is_windows=False,
        environment={},
    )

    assert manager == PROJECT_ROOT / "tools" / "manage_runpod_serverless_overflow.py"
    assert config == PROJECT_ROOT / "configs" / "runpod_serverless_overflow.yaml"
    assert broker_root == Path("/workspace/.maskfactory/serverless_overflow")


def test_broker_paths_allow_explicit_execution_host_mapping() -> None:
    manager, config, broker_root = _default_broker_paths(
        is_windows=False,
        environment={
            "MASKFACTORY_SERVERLESS_MANAGER_PATH": "/mnt/c/Comfy_UI_Main_Masking/tools/manage_runpod_serverless_overflow.py",
            "MASKFACTORY_SERVERLESS_CONFIG_PATH": "/mnt/c/Comfy_UI_Main_Masking/configs/runpod_serverless_overflow.yaml",
            "MASKFACTORY_SERVERLESS_BROKER_ROOT": "/workspace/.maskfactory/serverless_overflow",
        },
    )

    assert manager == Path(
        "/mnt/c/Comfy_UI_Main_Masking/tools/manage_runpod_serverless_overflow.py"
    )
    assert config == Path("/mnt/c/Comfy_UI_Main_Masking/configs/runpod_serverless_overflow.yaml")
    assert broker_root == Path("/workspace/.maskfactory/serverless_overflow")


def build(
    tmp_path: Path,
    runner: FakeBroker,
    *,
    mission_id: str = "1" * 64,
    payload: dict[str, Any] | None = None,
) -> BrokerOnlyServerlessRoute:
    mission = tmp_path / "mission"
    mission.mkdir(exist_ok=True)
    payload_value = payload or {"input": {"prompt": "bounded"}}
    payload_path = mission / "payload.json"
    if not payload_path.exists():
        payload_path.write_text(
            json.dumps(payload_value, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    manager = tmp_path / "manage_runpod_serverless_overflow.py"
    config = tmp_path / "runpod_serverless_overflow.yaml"
    if not manager.exists():
        manager.write_text("# manager\n", encoding="utf-8")
        config.write_text("config: true\n", encoding="utf-8")
    return BrokerOnlyServerlessRoute(
        mission_root=mission,
        mission_id=mission_id,
        session_id="session-maskfactory",
        profile="maskfactory",
        payload_path=payload_path,
        manager_path=manager,
        config_path=config,
        broker_root=tmp_path / "broker",
        command_runner=runner,
        clock=lambda: 1_800_000_000.0,
    )


def decision() -> dict[str, Any]:
    return {
        "session_id": "session-maskfactory",
        "profile": "maskfactory",
        "route": "serverless_overflow",
        "local_gpu": {"available": False},
    }


def reservation(payload: dict[str, Any], job_id: str = "overflow-1") -> dict[str, Any]:
    return {
        "job_id": job_id,
        "session_id": "session-maskfactory",
        "profile": "maskfactory",
        "payload_sha256": payload_sha(payload),
        "reserved_usd": 0.01,
        "state": "reserved",
    }


def submitted(job_id: str = "overflow-1") -> dict[str, Any]:
    return {
        "job_id": job_id,
        "state": "submitted",
        "provider_job_id": "provider-1",
    }


def test_budget_or_concurrency_rejection_never_submits(tmp_path: Path) -> None:
    runner = FakeBroker(
        decision(),
        BrokerCommandRejected("daily Serverless admission limit would be exceeded"),
    )
    route = build(tmp_path, runner)

    route.decide()
    with pytest.raises(BrokerCommandRejected, match="daily Serverless"):
        route.reserve(
            requested_seconds=60,
            observed_provider_spend_usd=0.0,
            observed_provider_hour_spend_usd=0.0,
        )

    assert route.state["state"] == "rejected"
    assert [command[6] for command in runner.commands] == ["decide", "reserve"]
    with pytest.raises(ServerlessRouteError, match="submit is not allowed"):
        route.submit()
    assert len(runner.commands) == 2


@pytest.mark.parametrize(
    "reason",
    [
        "daily Serverless admission limit would be exceeded",
        "rolling-hour Serverless admission limit would be exceeded",
        "Serverless concurrency cap is full",
    ],
)
def test_each_broker_cap_is_terminal_without_submit(
    tmp_path: Path,
    reason: str,
) -> None:
    runner = FakeBroker(decision(), BrokerCommandRejected(reason))
    route = build(tmp_path, runner)

    route.decide()
    with pytest.raises(BrokerCommandRejected, match=reason):
        route.reserve(requested_seconds=60)

    assert route.state["state"] == "rejected"
    assert [command[6] for command in runner.commands] == ["decide", "reserve"]
    with pytest.raises(ServerlessRouteError, match="submit is not allowed"):
        route.submit()
    assert [command[6] for command in runner.commands] == ["decide", "reserve"]


def test_reservation_timeout_reconciles_by_canonical_payload_without_retry(
    tmp_path: Path,
) -> None:
    payload = {"input": {"prompt": "bounded"}}
    reserved = reservation(payload)
    report = {"jobs": [reserved]}
    runner = FakeBroker(
        decision(),
        BrokerCommandTimeout("reserve timed out"),
        report,
    )
    route = build(tmp_path, runner, payload=payload)

    route.decide()
    with pytest.raises(ServerlessRouteAmbiguous, match="reserve outcome"):
        route.reserve(requested_seconds=60)
    assert route.state["state"] == "reservation_unknown"

    adopted = route.reconcile_reservation()
    assert adopted["job_id"] == "overflow-1"
    assert route.state["state"] == "reserved"
    assert [command[6] for command in runner.commands] == [
        "decide",
        "reserve",
        "report",
    ]


def test_absent_reservation_is_proven_before_new_reserve_is_allowed(
    tmp_path: Path,
) -> None:
    payload = {"input": {"prompt": "bounded"}}
    runner = FakeBroker(
        decision(),
        BrokerCommandTimeout("reserve timed out"),
        {"jobs": []},
        reservation(payload, "overflow-2"),
    )
    route = build(tmp_path, runner, payload=payload)

    route.decide()
    with pytest.raises(ServerlessRouteAmbiguous):
        route.reserve(requested_seconds=60)
    resolution = route.reconcile_reservation()
    assert resolution["resolution"] == "reservation_absent"
    assert route.state["state"] == "decided"
    assert route.reserve(requested_seconds=60)["job_id"] == "overflow-2"
    assert [command[6] for command in runner.commands].count("reserve") == 2
    assert runner.commands[2][6] == "report"


def test_duplicate_canonical_reservations_fail_closed_without_submit(
    tmp_path: Path,
) -> None:
    payload = {"input": {"prompt": "bounded"}}
    runner = FakeBroker(
        decision(),
        BrokerCommandTimeout("reserve timed out"),
        {
            "jobs": [
                reservation(payload, "overflow-1"),
                reservation(payload, "overflow-2"),
            ]
        },
    )
    route = build(tmp_path, runner, payload=payload)

    route.decide()
    with pytest.raises(ServerlessRouteAmbiguous, match="reserve outcome"):
        route.reserve(requested_seconds=60)
    with pytest.raises(
        ServerlessRouteAmbiguous,
        match="multiple broker jobs",
    ):
        route.reconcile_reservation()

    assert route.state["state"] == "recovery_required"
    assert [command[6] for command in runner.commands] == [
        "decide",
        "reserve",
        "report",
    ]
    with pytest.raises(ServerlessRouteError, match="submit is not allowed"):
        route.submit()
    assert [command[6] for command in runner.commands] == [
        "decide",
        "reserve",
        "report",
    ]


def test_submit_timeout_blocks_duplicate_and_reconciles_terminal(
    tmp_path: Path,
) -> None:
    payload = {"input": {"prompt": "bounded"}}
    completed = {
        **submitted(),
        "state": "completed",
        "actual_usd": 0.005,
    }
    runner = FakeBroker(
        decision(),
        reservation(payload),
        BrokerCommandTimeout("submit timed out"),
        completed,
    )
    route = build(tmp_path, runner, payload=payload)
    route.decide()
    route.reserve(requested_seconds=60)

    with pytest.raises(ServerlessRouteAmbiguous, match="submit outcome"):
        route.submit()
    assert route.state["state"] == "submitted_unknown"
    command_count = len(runner.commands)
    with pytest.raises(ServerlessRouteError, match="submit is not allowed"):
        route.submit()
    assert len(runner.commands) == command_count

    assert route.reconcile()["state"] == "completed"
    assert route.state["state"] == "terminal"
    assert [command[6] for command in runner.commands].count("submit") == 1


def test_running_then_terminal_reconcile_and_restart_are_idempotent(
    tmp_path: Path,
) -> None:
    payload = {"input": {"prompt": "bounded"}}
    running = {**submitted(), "state": "running"}
    completed = {**submitted(), "state": "completed"}
    runner = FakeBroker(
        decision(),
        reservation(payload),
        submitted(),
        running,
        completed,
    )
    route = build(tmp_path, runner, payload=payload)
    route.decide()
    route.reserve(requested_seconds=60)
    route.submit()
    assert route.reconcile()["state"] == "running"
    assert route.reconcile()["state"] == "completed"
    assert route.state["state"] == "terminal"

    no_calls = FakeBroker()
    restarted = build(tmp_path, no_calls, payload=payload)
    assert restarted.reconcile()["state"] == "completed"
    assert no_calls.commands == []


def test_restart_after_submit_intent_becomes_unknown_and_never_resends(
    tmp_path: Path,
) -> None:
    payload = {"input": {"prompt": "bounded"}}
    runner = FakeBroker(decision(), reservation(payload))
    route = build(tmp_path, runner, payload=payload)
    route.decide()
    route.reserve(requested_seconds=60)
    route._transition("submitting", "simulated_submit_intent")

    no_calls = FakeBroker()
    restarted = build(tmp_path, no_calls, payload=payload)
    assert restarted.state["state"] == "submitted_unknown"
    with pytest.raises(ServerlessRouteError, match="submit is not allowed"):
        restarted.submit()
    assert no_calls.commands == []


def test_duplicate_payload_collision_and_direct_endpoint_bypass_fail_closed(
    tmp_path: Path,
) -> None:
    route = build(tmp_path, FakeBroker(), payload={"input": {"value": 1}})
    assert route.state["payload_sha256"] == payload_sha({"input": {"value": 1}})

    payload_path = tmp_path / "mission" / "payload.json"
    payload_path.write_text(
        json.dumps({"input": {"value": 2}}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ServerlessRouteError, match="identity mismatch"):
        build(tmp_path, FakeBroker(), payload={"input": {"value": 2}})

    source = (
        Path(__file__).parents[2] / "src" / "maskfactory" / "steward" / "serverless_broker.py"
    ).read_text(encoding="utf-8")
    assert "urllib" not in source
    assert "requests." not in source
    assert "https://" not in source


def test_protected_credential_is_injected_without_persistence(tmp_path: Path) -> None:
    mission = tmp_path / "mission"
    mission.mkdir()
    payload_path = mission / "payload.json"
    payload_path.write_text('{"input":{"prompt":"bounded"}}\n', encoding="utf-8")
    manager = tmp_path / "manager.py"
    manager.write_text(
        "\n".join(
            (
                "import json",
                "import os",
                "print(json.dumps({",
                "    'session_id': 'session-maskfactory',",
                "    'profile': 'maskfactory',",
                "    'route': 'serverless_overflow',",
                "    'local_gpu': {'available': False},",
                "    'credential_present': bool(os.environ.get('RUNPOD_API_KEY')),",
                "}))",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text("config: true\n", encoding="utf-8")
    credential = tmp_path / "runpod.token"
    secret = "test-secret-never-persist"
    credential.write_text(secret, encoding="utf-8")
    if os.name != "nt":
        credential.chmod(0o600)

    route = BrokerOnlyServerlessRoute(
        mission_root=mission,
        mission_id="9" * 64,
        session_id="session-maskfactory",
        profile="maskfactory",
        payload_path=payload_path,
        manager_path=manager,
        config_path=config,
        broker_root=tmp_path / "broker",
        python_executable=sys.executable,
        runpod_api_key_file=credential,
    )
    decision_result = route.decide()

    assert decision_result["credential_present"] is True
    assert secret not in route.state_path.read_text(encoding="utf-8")
    assert secret not in json.dumps(route.state)


def test_protected_credential_must_exist_before_broker_reservation(
    tmp_path: Path,
) -> None:
    mission = tmp_path / "mission"
    mission.mkdir()
    payload_path = mission / "payload.json"
    payload_path.write_text('{"input":{"prompt":"bounded"}}\n', encoding="utf-8")
    manager = tmp_path / "manager.py"
    manager.write_text("# manager\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("config: true\n", encoding="utf-8")

    with pytest.raises(ServerlessRouteError, match="credential file is missing"):
        BrokerOnlyServerlessRoute(
            mission_root=mission,
            mission_id="8" * 64,
            session_id="session-maskfactory",
            profile="maskfactory",
            payload_path=payload_path,
            manager_path=manager,
            config_path=config,
            broker_root=tmp_path / "broker",
            runpod_api_key_file=tmp_path / "missing.token",
        )
