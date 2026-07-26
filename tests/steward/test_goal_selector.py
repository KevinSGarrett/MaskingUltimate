from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from maskfactory.steward.goal_selector import (
    GoalSelectionError,
    PLAN27_ITEM_ORDER,
    select_next_plan27_work,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRACKER_PATH = PROJECT_ROOT / "Plan" / "Tracker" / "tracker.json"


def _tracker() -> dict:
    return json.loads(TRACKER_PATH.read_text(encoding="utf-8"))


def _set_plan27_statuses(data: dict, default: str = "complete") -> None:
    for item_id in PLAN27_ITEM_ORDER:
        data["items"][item_id]["status"] = default


def test_selects_next_plan27_dependency_ahead_of_micro_bookkeeping():
    data = _tracker()
    _set_plan27_statuses(data)
    data["items"]["MF-P6-13.04"]["status"] = "open"
    data["items"]["MICRO-BOOKKEEPING"] = {
        "id": "MICRO-BOOKKEEPING",
        "status": "in_progress",
        "description": "Write another status-only review.",
        "orphaned": False,
        "conditional": False,
    }

    decision = select_next_plan27_work(data, inference_available=True)

    assert decision is not None
    assert decision.item_id == "MF-P6-13.04"
    assert decision.work_mode == "cpu_safe"
    assert decision.campaign_kind == "control_contract"


def test_dependency_blocks_successor_until_complete():
    data = _tracker()
    _set_plan27_statuses(data)
    data["items"]["MF-P6-14.01"]["status"] = "open"
    data["items"]["MF-P6-14.02"]["status"] = "open"

    first = select_next_plan27_work(data, inference_available=True)
    assert first is not None and first.item_id == "MF-P6-14.01"

    data["items"]["MF-P6-14.01"]["status"] = "complete"
    second = select_next_plan27_work(data, inference_available=True)
    assert second is not None and second.item_id == "MF-P6-14.02"


def test_inference_unavailable_continues_cpu_safe_fault_drill():
    data = _tracker()
    _set_plan27_statuses(data)
    data["items"]["MF-P6-19.01"]["status"] = "open"
    data["items"]["MF-P6-19.02"]["status"] = "open"
    for dependency in ("MF-P6-15.04", "MF-P6-16.04", "MF-P6-18.04"):
        data["items"][dependency]["status"] = "complete"

    decision = select_next_plan27_work(data, inference_available=False)

    assert decision is not None
    assert decision.item_id == "MF-P6-19.02"
    assert decision.work_mode == "cpu_safe"


def test_durable_states_suppress_reissue_and_select_next_safe_unit():
    data = _tracker()
    _set_plan27_statuses(data)
    data["items"]["MF-P6-14.01"]["status"] = "open"
    data["items"]["MF-P6-14.02"]["status"] = "open"
    data["items"]["MF-P6-14.01"]["description"] = "Ready. Blocked by: none"
    data["items"]["MF-P6-14.02"]["description"] = "Ready. Blocked by: none"

    decision = select_next_plan27_work(
        data,
        inference_available=True,
        active_item_ids={"MF-P6-14.01"},
    )

    assert decision is not None
    assert decision.item_id == "MF-P6-14.02"


def test_contradictory_durable_states_fail_closed():
    data = _tracker()

    with pytest.raises(GoalSelectionError, match="contradictory durable item states"):
        select_next_plan27_work(
            data,
            inference_available=True,
            active_item_ids={"MF-P6-14.01"},
            terminal_item_ids={"MF-P6-14.01"},
        )


def test_selection_is_deterministic_for_identical_tracker_state():
    data = _tracker()
    _set_plan27_statuses(data)
    data["items"]["MF-P6-14.01"]["status"] = "open"

    first = select_next_plan27_work(copy.deepcopy(data), inference_available=False)
    second = select_next_plan27_work(copy.deepcopy(data), inference_available=False)

    assert first == second
