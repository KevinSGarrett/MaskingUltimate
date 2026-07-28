import json
from pathlib import Path


def test_live_p8_cvat_handoff_has_exact_tasks_and_preserves_human_authority() -> None:
    audit = json.loads(
        Path("qa/live_verification/p8_real_cvat_handoff_20260712.json").read_text(encoding="utf-8")
    )
    assert audit["cvat_api_version"] == "2.24.0"
    assert audit["image_ids"] == ["img_7b7a3c7d5dd3", "img_6d6bb33f01a1"]
    assert audit["promoted_instance_count"] == 7
    assert audit["task_ids"] == list(range(9, 18))
    assert audit["task_count"] == len(audit["tasks"]) == 9
    assert audit["instance_review_task_count"] == 7
    assert audit["overview_task_count"] == 2
    assert audit["total_preannotation_shapes"] == 166
    assert audit["overview_shape_count"] == 0
    assert len(audit["packages"]) == 7
    assert all(package["reviewer"] is None for package in audit["packages"])
    assert all(package["approved_at"] is None for package in audit["packages"])
    assert audit["human_correction_completed"] is False
    assert audit["human_approval_completed"] is False
    instance_tasks = [task for task in audit["tasks"] if task["job_type"] == "instance_review"]
    overview_tasks = [task for task in audit["tasks"] if task["job_type"] == "image_overview"]
    assert all(task["shape_count"] > 0 for task in instance_tasks)
    assert all(task["shape_count"] == 0 for task in overview_tasks)
    assert all(task["remote_size"] == 1 for task in audit["tasks"])
