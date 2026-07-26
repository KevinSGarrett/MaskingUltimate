from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from maskfactory.steward.openrouter_advisory import (
    GovernedOpenRouterAdvisory,
    OpenRouterAdvisoryError,
    OpenRouterManagerRejected,
    OpenRouterManagerTimeout,
    OpenRouterOutcomeUnknown,
)


class FakeManager:
    def __init__(self, *results: dict[str, Any] | BaseException) -> None:
        self.results = list(results)
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], _timeout: float) -> dict[str, Any]:
        self.commands.append(list(command))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return copy.deepcopy(result)


def request_body(prompt: str) -> dict[str, Any]:
    return {
        "schema_version": "maskfactory.openrouter_advisory_request.v1",
        "mission_id": "1" * 64,
        "session_id": "019f91d1-ea20-7d81-83ff-03d393eaa1f5",
        "job_id": "mf-p6-15-03-test",
        "work_kind": "coding_advice",
        "model_tier": "routine",
        "materially_difficult": False,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "max_output_tokens": 128,
        "attachments": [],
        "authority": {
            "read_secrets": False,
            "execute_tools": False,
            "git": False,
            "github": False,
            "runpod_lifecycle": False,
            "infrastructure": False,
            "destructive_filesystem": False,
            "final_acceptance": False,
        },
    }


def build(
    tmp_path: Path,
    manager: FakeManager,
    *,
    prompt: str = "Review this bounded implementation and return advice only.",
    request_updates: dict[str, Any] | None = None,
) -> GovernedOpenRouterAdvisory:
    mission = tmp_path / "mission"
    mission.mkdir(parents=True)
    prompt_path = mission / "prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    request = request_body(prompt)
    if request_updates:
        request.update(request_updates)
    request_path = mission / "request.json"
    request_path.write_text(json.dumps(request, sort_keys=True), encoding="utf-8")
    manager_path = tmp_path / "manage_openrouter_reasoning_fallback.py"
    policy_path = tmp_path / "openrouter_reasoning_fallback_policy.json"
    manager_path.write_text("# manager\n", encoding="utf-8")
    policy_path.write_text("{}\n", encoding="utf-8")
    return GovernedOpenRouterAdvisory(
        mission_root=mission,
        request_path=request_path,
        prompt_path=prompt_path,
        manager_path=manager_path,
        policy_path=policy_path,
        manager_state_root=tmp_path / "manager-state",
        command_runner=manager,
        clock=lambda: 1_800_000_000.0,
    )


def openrouter_decision() -> dict[str, Any]:
    return {
        "session_id": "019f91d1-ea20-7d81-83ff-03d393eaa1f5",
        "profile": "maskfactory",
        "route": "openrouter_multimodal",
    }


def reservation(prompt: str) -> dict[str, Any]:
    return {
        "reservation_id": "or-reservation-1",
        "session_id": "019f91d1-ea20-7d81-83ff-03d393eaa1f5",
        "job_id": "mf-p6-15-03-test",
        "work_kind": "coding_advice",
        "model_tier": "routine",
        "model": "qwen/qwen3-coder-next",
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "status": "RESERVED",
    }


def test_ineligible_route_continues_cpu_without_reserve(tmp_path: Path) -> None:
    manager = FakeManager(
        {
            "session_id": "019f91d1-ea20-7d81-83ff-03d393eaa1f5",
            "route": "continue_cpu",
        }
    )
    route = build(tmp_path, manager)

    assert route.decide(
        pod_state="unavailable",
        serverless_state="unavailable",
    )["state"] == "cpu_fallback"
    with pytest.raises(OpenRouterAdvisoryError, match="reserve is not allowed"):
        route.reserve()
    assert [command[6] for command in manager.commands] == ["decide"]


def test_decision_rejection_continues_cpu(tmp_path: Path) -> None:
    route = build(
        tmp_path,
        FakeManager(OpenRouterManagerRejected("session is not authorized")),
    )
    state = route.decide(pod_state="unavailable", serverless_state="rejected")
    assert state["state"] == "cpu_fallback"
    assert state["route"] == "continue_cpu"


@pytest.mark.parametrize(
    "reason",
    [
        "shared UTC-day OpenRouter admission ceiling reached",
        "request exceeds the per-request cost ceiling",
        "a non-terminal reservation already exists for this job",
    ],
)
def test_cap_or_duplicate_rejection_continues_cpu_without_submit(
    tmp_path: Path,
    reason: str,
) -> None:
    manager = FakeManager(
        openrouter_decision(),
        OpenRouterManagerRejected(reason),
    )
    route = build(tmp_path, manager)
    route.decide(pod_state="unavailable", serverless_state="rejected")

    assert route.reserve()["state"] == "cpu_fallback"
    with pytest.raises(OpenRouterAdvisoryError, match="submit is not allowed"):
        route.submit()
    assert [command[6] for command in manager.commands] == ["decide", "reserve"]


def test_secret_and_tool_authority_requests_fail_before_manager(tmp_path: Path) -> None:
    manager = FakeManager()
    with pytest.raises(OpenRouterAdvisoryError, match="secret material"):
        build(tmp_path / "secret", manager, prompt="OPENROUTER_API_KEY=do-not-send")
    with pytest.raises(OpenRouterAdvisoryError, match="authority ceiling"):
        build(
            tmp_path / "tool",
            manager,
            request_updates={
                "authority": {
                    **request_body("x")["authority"],
                    "execute_tools": True,
                }
            },
        )
    assert manager.commands == []


def test_escalation_requires_material_difficulty(tmp_path: Path) -> None:
    with pytest.raises(OpenRouterAdvisoryError, match="materially difficult"):
        build(
            tmp_path,
            FakeManager(),
            request_updates={"model_tier": "escalation"},
        )


def test_success_is_terminal_read_only_advice(tmp_path: Path) -> None:
    prompt = "Review this bounded implementation and return advice only."
    manager = FakeManager(openrouter_decision(), reservation(prompt))
    route = build(tmp_path, manager, prompt=prompt)
    route.decide(pod_state="unavailable", serverless_state="rejected")
    route.reserve()
    output = route.output_path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "status": "COMPLETED",
                "content": "Bounded advisory only.",
                "authority_claimed": False,
            }
        ),
        encoding="utf-8",
    )
    manager.results.append(
        {
            "status": "COMPLETED",
            "reservation_id": "or-reservation-1",
            "output": str(output),
            "content_sha256": "a" * 64,
            "cost_usd": 0.001,
        }
    )

    state = route.submit()
    assert state["state"] == "terminal"
    assert state["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert [command[6] for command in manager.commands] == [
        "decide",
        "reserve",
        "submit",
    ]


def test_submit_timeout_blocks_retry_and_route_change(tmp_path: Path) -> None:
    prompt = "Review this bounded implementation and return advice only."
    manager = FakeManager(
        openrouter_decision(),
        reservation(prompt),
        OpenRouterManagerTimeout("submit timed out"),
    )
    route = build(tmp_path, manager, prompt=prompt)
    route.decide(pod_state="unavailable", serverless_state="rejected")
    route.reserve()

    with pytest.raises(OpenRouterOutcomeUnknown, match="do not retry"):
        route.submit()
    assert route.state["state"] == "outcome_unknown"
    with pytest.raises(OpenRouterAdvisoryError, match="submit is not allowed"):
        route.submit()
    assert [command[6] for command in manager.commands].count("submit") == 1


def test_source_has_no_direct_provider_client() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "maskfactory"
        / "steward"
        / "openrouter_advisory.py"
    ).read_text(encoding="utf-8")
    assert "urllib" not in source
    assert "requests." not in source
    assert "openrouter.ai" not in source
