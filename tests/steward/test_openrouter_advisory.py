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
        "attachment_sha256": [],
        "system_prompt_file": None,
        "system_prompt_sha256": None,
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


def policy_body() -> dict[str, Any]:
    return {
        "models": {
            "routine": {
                "id": "qwen/qwen3-coder-next",
                "api_kind": "chat",
            },
            "escalation": {
                "id": "qwen/qwen3-coder",
                "api_kind": "chat",
            },
            "multimodal_review": {
                "id": "qwen/qwen3.5-flash-02-23",
                "api_kind": "chat",
            },
            "speech_to_text": {
                "id": "qwen/qwen3-asr-flash-2026-02-10",
                "api_kind": "speech_to_text",
            },
            "text_to_speech": {
                "id": "qwen/qwen-audio-3.0-tts-flash",
                "api_kind": "text_to_speech",
            },
            "image_generation": {
                "id": "black-forest-labs/flux.2-klein-4b",
                "api_kind": "image_generation",
            },
            "video_generation": {
                "id": "alibaba/wan-2.6",
                "api_kind": "video_generation",
            },
        },
        "work_profiles": {
            "coding_advice": "routine",
            "visual_qa": "multimodal_review",
            "audio_transcription": "speech_to_text",
            "speech_generation": "text_to_speech",
            "image_generation": "image_generation",
            "video_generation": "video_generation",
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
    mission.mkdir(parents=True, exist_ok=True)
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
    policy_path.write_text(json.dumps(policy_body()) + "\n", encoding="utf-8")
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

    assert (
        route.decide(
            pod_state="unavailable",
            serverless_state="unavailable",
        )["state"]
        == "cpu_fallback"
    )
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
    assert "--artifact-root" not in manager.commands[-1]
    assert [command[6] for command in manager.commands] == [
        "decide",
        "reserve",
        "submit",
    ]


def test_multimodal_attachment_is_bound_and_forwarded(tmp_path: Path) -> None:
    prompt = "Review the bounded mask overlay and return evidence only."
    attachment = tmp_path / "mission" / "overlay.png"
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"\x89PNG\r\n\x1a\nbounded")
    manager = FakeManager(
        openrouter_decision(),
        {
            **reservation(prompt),
            "work_kind": "visual_qa",
            "model_tier": "multimodal_review",
            "model": "qwen/qwen3.5-flash-02-23",
        },
    )
    route = build(
        tmp_path,
        manager,
        prompt=prompt,
        request_updates={
            "work_kind": "visual_qa",
            "model_tier": "multimodal_review",
            "attachments": ["overlay.png"],
            "attachment_sha256": [hashlib.sha256(attachment.read_bytes()).hexdigest()],
        },
    )

    route.decide(pod_state="unavailable", serverless_state="unavailable")
    route.reserve()

    reserve_command = manager.commands[-1]
    assert reserve_command.count("--attachment") == 1
    assert str(attachment.resolve()) in reserve_command
    assert route.state["attachment_sha256"] == [hashlib.sha256(attachment.read_bytes()).hexdigest()]


def test_async_video_reconciles_without_second_submit(tmp_path: Path) -> None:
    prompt = "Generate a bounded five-second candidate video."
    manager = FakeManager(
        openrouter_decision(),
        {
            **reservation(prompt),
            "work_kind": "video_generation",
            "model_tier": "video_generation",
            "model": "alibaba/wan-2.6",
        },
    )
    route = build(
        tmp_path,
        manager,
        prompt=prompt,
        request_updates={
            "work_kind": "video_generation",
            "model_tier": "video_generation",
            "max_output_tokens": 0,
        },
    )
    route.decide(pod_state="unavailable", serverless_state="unavailable")
    route.reserve()
    route.output_path.write_text(
        json.dumps({"status": "SUBMITTED"}),
        encoding="utf-8",
    )
    manager.results.append(
        {
            "status": "SUBMITTED",
            "reservation_id": "or-reservation-1",
            "output": str(route.output_path),
            "content_sha256": None,
            "cost_usd": None,
        }
    )

    assert route.submit()["state"] == "submitted"
    route.output_path.write_text(
        json.dumps({"status": "COMPLETED"}),
        encoding="utf-8",
    )
    manager.results.append(
        {
            "status": "COMPLETED",
            "reservation_id": "or-reservation-1",
            "output": str(route.output_path),
            "cost_usd": 0.1,
        }
    )

    assert route.reconcile()["state"] == "terminal"
    verbs = [command[6] for command in manager.commands]
    assert verbs == ["decide", "reserve", "submit", "reconcile-video"]


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


def test_unknown_submit_can_resume_only_after_manager_proves_absence(
    tmp_path: Path,
) -> None:
    prompt = "Review this bounded implementation and return advice only."
    manager = FakeManager(
        openrouter_decision(),
        reservation(prompt),
        OpenRouterManagerTimeout("submit timed out"),
        {
            **reservation(prompt),
            "provider_job_id": None,
            "submitted_at": None,
            "actual_cost_usd": None,
            "terminal_at": None,
        },
    )
    route = build(tmp_path, manager, prompt=prompt)
    route.decide(pod_state="unavailable", serverless_state="rejected")
    route.reserve()
    with pytest.raises(OpenRouterOutcomeUnknown):
        route.submit()

    state = route.reconcile_unknown()

    assert state["state"] == "reserved"
    assert state["event"] == "submission_absent_reconciled"
    assert [command[6] for command in manager.commands] == [
        "decide",
        "reserve",
        "submit",
        "inspect-reservation",
    ]


def test_unknown_submit_stays_blocked_when_manager_reports_submitting(
    tmp_path: Path,
) -> None:
    prompt = "Review this bounded implementation and return advice only."
    manager = FakeManager(
        openrouter_decision(),
        reservation(prompt),
        OpenRouterManagerTimeout("submit timed out"),
        {
            **reservation(prompt),
            "status": "SUBMITTING",
            "provider_job_id": None,
            "submitted_at": "2026-07-26T17:00:00+00:00",
            "actual_cost_usd": None,
            "terminal_at": None,
        },
    )
    route = build(tmp_path, manager, prompt=prompt)
    route.decide(pod_state="unavailable", serverless_state="rejected")
    route.reserve()
    with pytest.raises(OpenRouterOutcomeUnknown):
        route.submit()

    with pytest.raises(OpenRouterOutcomeUnknown, match="remains SUBMITTING"):
        route.reconcile_unknown()
    assert route.state["state"] == "outcome_unknown"


def test_source_has_no_direct_provider_client() -> None:
    source = (
        Path(__file__).parents[2] / "src" / "maskfactory" / "steward" / "openrouter_advisory.py"
    ).read_text(encoding="utf-8")
    assert "urllib" not in source
    assert "requests." not in source
    assert "openrouter.ai" not in source
