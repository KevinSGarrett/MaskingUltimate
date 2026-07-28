from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from maskfactory.steward.fallback_campaign_producer import (
    FallbackCampaignProducer,
    FallbackCampaignProducerError,
)
from maskfactory.steward.fallback_dispatcher import WORK_ITEM_NAME
from maskfactory.steward.openrouter_advisory import GovernedOpenRouterAdvisory


def _tracker(path: Path) -> None:
    items = {}
    for cluster in range(13, 20):
        for item in range(1, 5):
            item_id = f"MF-P6-{cluster}.{item:02d}"
            items[item_id] = {
                "id": item_id,
                "cluster_id": f"MF-P6-{cluster}",
                "cluster_title": "continuous autonomy",
                "spec_ref": "27",
                "description": "Closed. Blocked by: none",
                "status": "complete",
                "percent_complete": 100,
                "orphaned": False,
            }
    items["MF-P6-15.01"].update(
        status="open",
        percent_complete=0,
        description="Implement local guarded routing. Blocked by: MF-P6-14.02",
    )
    items["MF-P6-15.02"].update(
        status="open",
        percent_complete=0,
        description="Implement Serverless fallback. Blocked by: MF-P6-14.02",
    )
    items["MF-P6-15.03"].update(
        status="open",
        percent_complete=0,
        description="Implement OpenRouter fallback. Blocked by: MF-P6-14.01",
    )
    items["MF-P6-15.04"].update(
        status="open",
        percent_complete=0,
        description=("Prove no dual submit. Blocked by: " "MF-P6-15.01 through MF-P6-15.03"),
    )
    path.write_text(json.dumps({"items": items}, sort_keys=True), encoding="utf-8")


def _policy(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "models": {
                    "routine": {
                        "id": "qwen/qwen3-coder-next",
                        "api_kind": "chat",
                    }
                },
                "work_profiles": {"implementation_review": "routine"},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_produces_one_bounded_unblocked_cluster_and_is_idempotent(tmp_path: Path) -> None:
    tracker = tmp_path / "tracker.json"
    inbox = tmp_path / "inbox"
    manager = tmp_path / "manager.py"
    policy = tmp_path / "policy.json"
    manager.write_text("# manager\n", encoding="utf-8")
    _policy(policy)
    _tracker(tracker)
    producer = FallbackCampaignProducer(
        tracker_path=tracker,
        inbox_root=inbox,
        openrouter_manager_path=manager,
        openrouter_policy_path=policy,
    )

    first = producer.produce()
    second = producer.produce()

    assert len(first) == 1
    assert first[0]["created"] is True
    assert first[0]["item_ids"] == [
        "MF-P6-15.01",
        "MF-P6-15.02",
        "MF-P6-15.03",
    ]
    assert second == [
        {
            "mission_id": first[0]["mission_id"],
            "campaign_id": first[0]["campaign_id"],
            "parent_campaign_id": first[0]["parent_campaign_id"],
            "work_kind": "implementation_review",
            "item_ids": first[0]["item_ids"],
            "created": False,
        }
    ]
    root = inbox / first[0]["mission_id"]
    request = json.loads((root / "request.json").read_text(encoding="utf-8"))
    work_item = json.loads((root / WORK_ITEM_NAME).read_text(encoding="utf-8"))
    prompt = (root / "prompt.txt").read_text(encoding="utf-8")
    assert request["prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
    assert request["authority"]["execute_tools"] is False
    assert request["authority"]["final_acceptance"] is False
    assert request["attachments"] == []
    assert request["parent_campaign_id"] == work_item["parent_campaign_id"]
    assert request["parent_contract_sha256"] == work_item["parent_contract_sha256"]
    assert request["child_role"] == work_item["child_role"]
    assert work_item["tracker_item_ids"] == first[0]["item_ids"]
    assert work_item["parent_campaign_id"] == first[0]["parent_campaign_id"]
    assert len(work_item["parent_campaign_id"]) == 64
    assert work_item["child_role"] == "consolidated_advisory"
    assert work_item["required_child_roles"] == ["consolidated_advisory"]
    route = GovernedOpenRouterAdvisory(
        mission_root=root,
        request_path=root / "request.json",
        prompt_path=root / "prompt.txt",
        manager_path=manager,
        policy_path=policy,
        manager_state_root=tmp_path / "manager-state",
        command_runner=lambda _command, _timeout: {
            "session_id": request["session_id"],
            "route": "continue_cpu",
        },
    )
    assert (
        route.decide(pod_state="unavailable", serverless_state="unavailable")["state"]
        == "cpu_fallback"
    )


def test_new_tracker_snapshot_gets_new_identity_without_reissue(
    tmp_path: Path,
) -> None:
    tracker = tmp_path / "tracker.json"
    inbox = tmp_path / "inbox"
    manager = tmp_path / "manager.py"
    policy = tmp_path / "policy.json"
    manager.write_text("# manager\n", encoding="utf-8")
    policy.write_text("{}\n", encoding="utf-8")
    _tracker(tracker)
    producer = FallbackCampaignProducer(
        tracker_path=tracker,
        inbox_root=inbox,
        openrouter_manager_path=manager,
        openrouter_policy_path=policy,
    )
    first = producer.produce()[0]
    value = json.loads(tracker.read_text(encoding="utf-8"))
    value["items"]["MF-P6-15.01"]["percent_complete"] = 25
    tracker.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

    second = producer.produce()[0]

    assert first["mission_id"] != second["mission_id"]
    assert second["created"] is True


def test_multiple_advisory_modes_are_rejected_before_micro_fanout(
    tmp_path: Path,
) -> None:
    tracker = tmp_path / "tracker.json"
    inbox = tmp_path / "inbox"
    manager = tmp_path / "manager.py"
    policy = tmp_path / "policy.json"
    manager.write_text("# manager\n", encoding="utf-8")
    policy.write_text("{}\n", encoding="utf-8")
    _tracker(tracker)
    with pytest.raises(
        FallbackCampaignProducerError,
        match="exactly one governed consolidated advisory",
    ):
        FallbackCampaignProducer(
            tracker_path=tracker,
            inbox_root=inbox,
            advisory_work_kinds=(
                "implementation_review",
                "test_strategy",
            ),
            openrouter_manager_path=manager,
            openrouter_policy_path=policy,
        )


def test_manager_change_forces_material_successor_identity(tmp_path: Path) -> None:
    tracker = tmp_path / "tracker.json"
    inbox = tmp_path / "inbox"
    manager = tmp_path / "manager.py"
    policy = tmp_path / "policy.json"
    manager.write_text("# manager v1\n", encoding="utf-8")
    policy.write_text("{}\n", encoding="utf-8")
    _tracker(tracker)
    producer = FallbackCampaignProducer(
        tracker_path=tracker,
        inbox_root=inbox,
        openrouter_manager_path=manager,
        openrouter_policy_path=policy,
    )
    first = producer.produce()[0]
    manager.write_text("# manager v2\n", encoding="utf-8")

    second = producer.produce()[0]

    assert first["mission_id"] != second["mission_id"]
    assert second["created"] is True
