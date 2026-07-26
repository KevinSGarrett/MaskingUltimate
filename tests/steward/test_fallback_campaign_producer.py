from __future__ import annotations

import hashlib
import json
from pathlib import Path

from maskfactory.steward.fallback_campaign_producer import FallbackCampaignProducer
from maskfactory.steward.fallback_dispatcher import WORK_ITEM_NAME


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


def test_produces_one_bounded_unblocked_cluster_and_is_idempotent(tmp_path: Path) -> None:
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
    assert work_item["tracker_item_ids"] == first[0]["item_ids"]


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


def test_production_modes_create_distinct_useful_advisory_jobs(
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
        advisory_work_kinds=(
            "implementation_review",
            "test_strategy",
            "root_cause_analysis",
            "dependency_analysis",
        ),
        openrouter_manager_path=manager,
        openrouter_policy_path=policy,
    )

    receipts = producer.produce()

    assert {item["work_kind"] for item in receipts} == {
        "implementation_review",
        "test_strategy",
        "root_cause_analysis",
        "dependency_analysis",
    }
    assert len({item["mission_id"] for item in receipts}) == len(receipts)
    assert all(item["created"] is True for item in receipts)
    blocked = [
        item
        for item in receipts
        if item["work_kind"] in {"root_cause_analysis", "dependency_analysis"}
    ]
    assert all("MF-P6-15.04" in item["item_ids"] for item in blocked)


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
