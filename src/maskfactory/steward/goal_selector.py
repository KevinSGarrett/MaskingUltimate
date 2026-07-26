"""Deterministic Plan-27 pursuing-goal selection.

The selector is deliberately CPU-safe and tracker-driven.  It never infers
completion from chat state, never selects bookkeeping-only work ahead of the
continuous-autonomy dependency chain, and never treats inference
unavailability as permission to idle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping


PLAN27_ITEM_ORDER = tuple(
    f"MF-P6-{cluster}.{item:02d}" for cluster in range(13, 20) for item in range(1, 5)
)

ACTIONABLE_STATUSES = frozenset({"open", "in_progress", "partially_complete", "failed"})
DEPENDENCY_DONE_STATUSES = frozenset({"complete", "not_applicable"})

# These completion units require live model/visual execution.  Their
# implementation prerequisites remain selectable through their earlier
# CPU-safe Plan-27 items.
LIVE_INFERENCE_REQUIRED = frozenset(
    {
        "MF-P6-17.03",
        "MF-P6-19.01",
        "MF-P6-19.03",
        "MF-P6-19.04",
    }
)

CAMPAIGN_KIND_BY_CLUSTER = {
    13: "control_contract",
    14: "supervisor_ledger",
    15: "routing",
    16: "engineering",
    17: "mask",
    18: "adoption_telemetry",
    19: "acceptance",
}

_ITEM_ID_RE = re.compile(r"MF-P\d+-[A-Z0-9]+(?:\.\d+)?")
_RANGE_RE = re.compile(
    r"(MF-P\d+-[A-Z0-9]+\.)"
    r"(?P<start>\d+)\s+through\s+"
    r"(MF-P\d+-[A-Z0-9]+\.)?"
    r"(?P<end>\d+)"
)


class GoalSelectionError(ValueError):
    """Raised when tracker input is malformed or internally contradictory."""


@dataclass(frozen=True)
class GoalSelection:
    """One deterministic pursuing-goal decision."""

    item_id: str
    priority_index: int
    campaign_kind: str
    work_mode: str
    dependency_ids: tuple[str, ...]
    reason: str


def parse_dependency_ids(description: str) -> tuple[str, ...]:
    """Parse exact item IDs and same-prefix ``through`` ranges."""

    clause = (
        description.split("Blocked by:", 1)[1] if "Blocked by:" in description else ""
    )
    dependencies = list(_ITEM_ID_RE.findall(clause))
    for match in _RANGE_RE.finditer(clause):
        start_prefix = match.group(1)
        end_prefix = match.group(3) or start_prefix
        start = int(match.group("start"))
        end = int(match.group("end"))
        if start_prefix != end_prefix or end < start:
            continue
        width = max(len(match.group("start")), len(match.group("end")))
        dependencies.extend(
            f"{start_prefix}{number:0{width}d}" for number in range(start, end + 1)
        )
    return tuple(dict.fromkeys(dependencies))


def _campaign_kind(item_id: str) -> str:
    match = re.fullmatch(r"MF-P6-(?P<cluster>\d+)\.\d+", item_id)
    if not match:
        raise GoalSelectionError(f"invalid Plan-27 item id: {item_id}")
    cluster = int(match.group("cluster"))
    try:
        return CAMPAIGN_KIND_BY_CLUSTER[cluster]
    except KeyError as exc:
        raise GoalSelectionError(f"unsupported Plan-27 cluster: {cluster}") from exc


def _dependency_is_done(
    items: Mapping[str, Mapping[str, object]], item_id: str
) -> bool:
    dependency = items.get(item_id)
    if dependency is None or dependency.get("orphaned"):
        return False
    status = dependency.get("status")
    if status == "not_applicable" and not dependency.get("conditional"):
        return False
    return status in DEPENDENCY_DONE_STATUSES


def select_next_plan27_work(
    tracker_data: Mapping[str, object],
    *,
    inference_available: bool,
    active_item_ids: Iterable[str] = (),
    terminal_item_ids: Iterable[str] = (),
    ambiguous_item_ids: Iterable[str] = (),
    superseded_item_ids: Iterable[str] = (),
) -> GoalSelection | None:
    """Select the highest-priority unblocked Plan-27 unit.

    Durable active, terminal, ambiguous, and superseded identities are supplied
    by the caller's ledger reconstruction.  When inference is unavailable the
    selector skips only completion units that inherently require live
    inference and continues scanning for useful CPU-safe work.
    """

    items = tracker_data.get("items")
    if not isinstance(items, Mapping):
        raise GoalSelectionError("tracker_data.items must be an object")

    exclusions = {
        "active": frozenset(active_item_ids),
        "terminal": frozenset(terminal_item_ids),
        "ambiguous": frozenset(ambiguous_item_ids),
        "superseded": frozenset(superseded_item_ids),
    }
    overlap = set()
    exclusion_sets = list(exclusions.items())
    for index, (left_name, left) in enumerate(exclusion_sets):
        for right_name, right in exclusion_sets[index + 1 :]:
            for item_id in left.intersection(right):
                overlap.add((item_id, left_name, right_name))
    if overlap:
        details = ", ".join(
            f"{item_id}:{left}/{right}" for item_id, left, right in sorted(overlap)
        )
        raise GoalSelectionError(f"contradictory durable item states: {details}")
    excluded = frozenset().union(*exclusions.values())

    for priority_index, item_id in enumerate(PLAN27_ITEM_ORDER):
        item = items.get(item_id)
        if not isinstance(item, Mapping) or item.get("orphaned"):
            continue
        if item.get("status") not in ACTIONABLE_STATUSES:
            continue
        if item_id in excluded:
            continue
        if not inference_available and item_id in LIVE_INFERENCE_REQUIRED:
            continue
        dependencies = parse_dependency_ids(str(item.get("description") or ""))
        if not all(
            _dependency_is_done(items, dependency) for dependency in dependencies
        ):
            continue
        work_mode = (
            "live_inference" if item_id in LIVE_INFERENCE_REQUIRED else "cpu_safe"
        )
        return GoalSelection(
            item_id=item_id,
            priority_index=priority_index,
            campaign_kind=_campaign_kind(item_id),
            work_mode=work_mode,
            dependency_ids=dependencies,
            reason=(
                "highest-priority unblocked Plan-27 dependency; "
                "micro-review and bookkeeping lanes are out of scope"
            ),
        )
    return None


__all__ = [
    "ACTIONABLE_STATUSES",
    "GoalSelection",
    "GoalSelectionError",
    "LIVE_INFERENCE_REQUIRED",
    "PLAN27_ITEM_ORDER",
    "parse_dependency_ids",
    "select_next_plan27_work",
]
