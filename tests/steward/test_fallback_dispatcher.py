from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from maskfactory.steward.fallback_dispatcher import (
    LEGACY_WORK_ITEM_SCHEMA,
    TERMINAL_NAME,
    WORK_ITEM_NAME,
    WORK_ITEM_SCHEMA,
    FallbackWorkDispatcher,
    fallback_child_mission_id,
    seal_fallback_work_item,
)
from maskfactory.steward.openrouter_advisory import OpenRouterOutcomeUnknown

SESSION = "019f91d1-ea20-7d81-83ff-03d393eaa1f5"


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def write_item(
    inbox: Path,
    *,
    route: str,
    parent_campaign_id: str,
    parent_contract_sha256: str = "b" * 64,
    required_child_roles: tuple[str, ...] | None = None,
) -> Path:
    child_role = (
        "serverless_execution"
        if route == "serverless_overflow"
        else "consolidated_advisory"
    )
    required_child_roles = required_child_roles or (child_role,)
    mission_id = fallback_child_mission_id(
        session_id=SESSION,
        parent_campaign_id=parent_campaign_id,
        parent_contract_sha256=parent_contract_sha256,
        required_child_roles=required_child_roles,
        child_role=child_role,
        route=route,
    )
    root = inbox / mission_id
    root.mkdir(parents=True)
    if route == "serverless_overflow":
        payload = {"input": {"prompt": "real bounded mask review"}}
        write_json(root / "payload.json", payload)
        item = {
            "schema_version": WORK_ITEM_SCHEMA,
            "mission_id": mission_id,
            "session_id": SESSION,
            "parent_campaign_id": parent_campaign_id,
            "parent_contract_sha256": parent_contract_sha256,
            "required_child_roles": list(required_child_roles),
            "child_role": child_role,
            "route": route,
            "payload_sha256": canonical_sha(payload),
            "payload_file": "payload.json",
            "requested_seconds": 60,
            "profile": "maskfactory",
        }
    else:
        prompt = "Review the bounded masking change and return advice only."
        (root / "prompt.txt").write_text(prompt, encoding="utf-8")
        request = {"mission": mission_id, "prompt": prompt}
        write_json(root / "request.json", request)
        item = {
            "schema_version": WORK_ITEM_SCHEMA,
            "mission_id": mission_id,
            "session_id": SESSION,
            "parent_campaign_id": parent_campaign_id,
            "parent_contract_sha256": parent_contract_sha256,
            "required_child_roles": list(required_child_roles),
            "child_role": child_role,
            "route": route,
            "payload_sha256": hashlib.sha256((root / "request.json").read_bytes()).hexdigest(),
            "request_file": "request.json",
            "prompt_file": "prompt.txt",
            "pod_state": "busy",
            "serverless_state": "available",
        }
    write_json(root / WORK_ITEM_NAME, seal_fallback_work_item(item))
    return root


class FakeServerless:
    def __init__(self, barrier: threading.Barrier, **kwargs: Any) -> None:
        self.barrier = barrier
        self.state_path = kwargs["mission_root"] / "serverless_route_state.json"
        payload = json.loads(kwargs["payload_path"].read_text())
        self._state = {
            "state": "intent_persisted",
            "payload_sha256": canonical_sha(payload),
            "last_result": None,
        }
        write_json(self.state_path, self._state)

    @property
    def state(self) -> dict[str, Any]:
        return dict(self._state)

    def decide(self) -> None:
        self._state["state"] = "decided"

    def reserve(self, *, requested_seconds: int) -> None:
        assert requested_seconds == 60
        self._state["state"] = "reserved"

    def submit(self) -> None:
        self.barrier.wait(timeout=3)
        self._state.update(
            state="terminal",
            last_result={"state": "completed", "job_id": "overflow-1"},
        )
        write_json(self.state_path, self._state)


class SemanticFalseServerless(FakeServerless):
    def submit(self) -> None:
        self._state.update(
            state="terminal",
            last_result={
                "state": "completed",
                "job_id": "overflow-semantic-failure",
                "provider_status_json": json.dumps(
                    {
                        "output": {
                            "stdout_tail": (
                                '{"native_box_runtime_ready": false, "token": "preflight"}\n'
                            )
                        },
                        "status": "COMPLETED",
                    }
                ),
            },
        )
        write_json(self.state_path, self._state)


class FakeOpenRouter:
    def __init__(self, barrier: threading.Barrier, **kwargs: Any) -> None:
        self.barrier = barrier
        self.output_path = kwargs["mission_root"] / "openrouter_advisory_output.json"
        self._state = {"state": "intent_persisted", "last_error": None}

    @property
    def state(self) -> dict[str, Any]:
        return dict(self._state)

    def decide(self, *, pod_state: str, serverless_state: str) -> None:
        assert pod_state == "busy"
        assert serverless_state == "available"
        self._state["state"] = "decided"

    def reserve(self) -> None:
        self._state["state"] = "reserved"

    def submit(self) -> None:
        self.barrier.wait(timeout=3)
        write_json(self.output_path, {"status": "COMPLETED", "advice": "bounded"})
        self._state["state"] = "terminal"


class CpuFallbackOpenRouter(FakeOpenRouter):
    def decide(self, *, pod_state: str, serverless_state: str) -> None:
        self._state.update(
            state="cpu_fallback",
            last_error="shared UTC-day admission ceiling reached",
        )


class OutcomeUnknownThenFailedOpenRouter:
    def __init__(self, **kwargs: Any) -> None:
        self.state_path = kwargs["mission_root"] / "fake_openrouter_state.json"
        self.output_path = kwargs["mission_root"] / "openrouter_advisory_output.json"
        if self.state_path.is_file():
            self._state = json.loads(self.state_path.read_text(encoding="utf-8"))
        else:
            self._state = {"state": "intent_persisted", "last_error": None}
            write_json(self.state_path, self._state)

    @property
    def state(self) -> dict[str, Any]:
        return dict(self._state)

    def _save(self) -> None:
        write_json(self.state_path, self._state)

    def decide(self, *, pod_state: str, serverless_state: str) -> None:
        self._state["state"] = "decided"
        self._save()

    def reserve(self) -> None:
        self._state["state"] = "reserved"
        self._save()

    def submit(self) -> None:
        self._state.update(
            state="outcome_unknown",
            last_error="provider acknowledgement interrupted",
        )
        self._save()
        raise OpenRouterOutcomeUnknown("provider acknowledgement interrupted")

    def reconcile_unknown(self) -> None:
        self._state.update(
            state="failed",
            last_error="manager proved terminal failure",
        )
        self._save()


def build(
    tmp_path: Path,
    *,
    serverless_factory: Any,
    openrouter_factory: Any,
) -> FallbackWorkDispatcher:
    placeholders = tmp_path / "control"
    for name in ("serverless.py", "serverless.yaml", "openrouter.py", "policy.json"):
        path = placeholders / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")
    return FallbackWorkDispatcher(
        inbox_root=tmp_path / "inbox",
        state_root=tmp_path / "state",
        serverless_manager_path=placeholders / "serverless.py",
        serverless_config_path=placeholders / "serverless.yaml",
        serverless_broker_root=tmp_path / "broker",
        openrouter_manager_path=placeholders / "openrouter.py",
        openrouter_policy_path=placeholders / "policy.json",
        openrouter_manager_state_root=tmp_path / "openrouter-state",
        serverless_factory=serverless_factory,
        openrouter_factory=openrouter_factory,
    )


def test_serverless_and_openrouter_advance_concurrently_and_terminalize(
    tmp_path: Path,
) -> None:
    barrier = threading.Barrier(2)
    dispatcher = build(
        tmp_path,
        serverless_factory=lambda **kwargs: FakeServerless(barrier, **kwargs),
        openrouter_factory=lambda **kwargs: FakeOpenRouter(barrier, **kwargs),
    )
    serverless = write_item(
        dispatcher.inbox_root,
        route="serverless_overflow",
        parent_campaign_id="a" * 64,
        required_child_roles=(
            "consolidated_advisory",
            "serverless_execution",
        ),
    )
    openrouter = write_item(
        dispatcher.inbox_root,
        route="openrouter_advisory",
        parent_campaign_id="a" * 64,
        required_child_roles=(
            "consolidated_advisory",
            "serverless_execution",
        ),
    )

    results = dispatcher.poll_once()

    assert len(results) == 2
    assert (serverless / TERMINAL_NAME).is_file()
    assert (openrouter / TERMINAL_NAME).is_file()
    assert (
        json.loads((serverless / TERMINAL_NAME).read_text(encoding="utf-8"))[
            "disposition"
        ]
        == "completed"
    )
    assert dispatcher.pending_ids() == []
    assert list((dispatcher.state_root / "route_tokens").iterdir()) == []
    parent = dispatcher.parent_ledger.inspect_parent("a" * 64)
    assert parent["state"] == "completed"
    assert [child["child_role"] for child in parent["children"]] == [
        "consolidated_advisory",
        "serverless_execution",
    ]


def test_serverless_semantic_false_is_terminal_failure(tmp_path: Path) -> None:
    dispatcher = build(
        tmp_path,
        serverless_factory=lambda **kwargs: SemanticFalseServerless(
            threading.Barrier(1), **kwargs
        ),
        openrouter_factory=lambda **kwargs: FakeOpenRouter(
            threading.Barrier(1), **kwargs
        ),
    )
    serverless = write_item(
        dispatcher.inbox_root,
        route="serverless_overflow",
        parent_campaign_id="9" * 64,
    )

    results = dispatcher.poll_once()

    assert results[0]["disposition"] == "failed"
    receipt = json.loads((serverless / TERMINAL_NAME).read_text(encoding="utf-8"))
    assert receipt["disposition"] == "failed"
    assert dispatcher.pending_ids() == []


def test_openrouter_cap_rejection_is_not_retried_on_next_poll(tmp_path: Path) -> None:
    calls = 0

    def factory(**kwargs: Any) -> CpuFallbackOpenRouter:
        nonlocal calls
        calls += 1
        return CpuFallbackOpenRouter(threading.Barrier(1), **kwargs)

    dispatcher = build(
        tmp_path,
        serverless_factory=lambda **kwargs: FakeServerless(threading.Barrier(1), **kwargs),
        openrouter_factory=factory,
    )
    write_item(
        dispatcher.inbox_root,
        route="openrouter_advisory",
        parent_campaign_id="3" * 64,
    )

    first = dispatcher.poll_once()
    second = dispatcher.poll_once()

    assert first[0]["state"] == "route_unavailable"
    assert second == []
    assert calls == 1
    assert list((dispatcher.state_root / "route_tokens").iterdir()) == []


def test_work_item_hash_drift_fails_before_route_claim(tmp_path: Path) -> None:
    dispatcher = build(
        tmp_path,
        serverless_factory=lambda **kwargs: FakeServerless(threading.Barrier(1), **kwargs),
        openrouter_factory=lambda **kwargs: FakeOpenRouter(threading.Barrier(1), **kwargs),
    )
    root = write_item(
        dispatcher.inbox_root,
        route="serverless_overflow",
        parent_campaign_id="4" * 64,
    )
    write_json(root / "payload.json", {"input": {"prompt": "drifted"}})

    try:
        dispatcher.poll_once()
    except Exception as exc:
        assert "identity mismatch" in str(exc)
    else:
        raise AssertionError("drifted payload was admitted")

    assert not (dispatcher.state_root / "canonical_routes.sqlite-wal").exists()
    assert list((dispatcher.state_root / "route_tokens").iterdir()) == []


def test_manager_proven_openrouter_failure_is_terminal_and_not_repolled(
    tmp_path: Path,
) -> None:
    dispatcher = build(
        tmp_path,
        serverless_factory=lambda **kwargs: FakeServerless(
            threading.Barrier(1), **kwargs
        ),
        openrouter_factory=OutcomeUnknownThenFailedOpenRouter,
    )
    root = write_item(
        dispatcher.inbox_root,
        route="openrouter_advisory",
        parent_campaign_id="5" * 64,
    )

    first = dispatcher.poll_once()
    second = dispatcher.poll_once()
    third = dispatcher.poll_once()

    assert first[0]["state"] == "outcome_unknown"
    assert second[0]["disposition"] == "failed"
    assert third == []
    assert (root / TERMINAL_NAME).is_file()
    assert not (root / "openrouter_advisory_output.json").exists()
    assert dispatcher.parent_ledger.inspect_parent("5" * 64)["state"] == "failed"
    assert list((dispatcher.state_root / "route_tokens").iterdir()) == []


def test_legacy_unbound_work_item_is_preserved_but_not_dispatched(
    tmp_path: Path,
) -> None:
    dispatcher = build(
        tmp_path,
        serverless_factory=lambda **kwargs: FakeServerless(
            threading.Barrier(1), **kwargs
        ),
        openrouter_factory=lambda **kwargs: FakeOpenRouter(
            threading.Barrier(1), **kwargs
        ),
    )
    root = dispatcher.inbox_root / ("6" * 64)
    root.mkdir(parents=True)
    write_json(
        root / WORK_ITEM_NAME,
        seal_fallback_work_item(
            {
                "schema_version": LEGACY_WORK_ITEM_SCHEMA,
                "mission_id": "6" * 64,
                "session_id": SESSION,
                "route": "serverless_overflow",
                "payload_sha256": "7" * 64,
            }
        ),
    )

    assert dispatcher.poll_once() == []
    assert (root / WORK_ITEM_NAME).is_file()
    assert not (root / TERMINAL_NAME).exists()
