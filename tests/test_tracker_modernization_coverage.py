from __future__ import annotations

import runpy
from pathlib import Path

from maskfactory.datasets.authority import (
    D5_CERTIFIED_PACKAGE_COUNT,
    P5_CERTIFIED_ENTRY_COUNT,
)

ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "Plan" / "Items"
TRACKER_SOURCE = ROOT / "Plan" / "Tracker" / "tracker.py"
ADDENDUM_FILES = tuple(ITEMS / f"{index:02d}_ITEMS_" for index in range(11, 21))


def _tracker_module() -> dict:
    return runpy.run_path(str(TRACKER_SOURCE))


def test_expanded_tracker_has_exact_authoritative_item_count_and_no_duplicate_ids() -> None:
    module = _tracker_module()
    items = module["parse_items_files"]()
    assert module["EXPECTED_ITEM_COUNT"] == 866
    assert len(items) == 866
    assert len(set(items)) == 866


def test_ontology_v2_checklist_is_imported_one_to_one_as_seventy_items() -> None:
    items = _tracker_module()["parse_items_files"]()
    prefixes = (
        "MF-P0-15.",
        "MF-P1-10.",
        "MF-P1-11.",
        "MF-P1-12.",
        "MF-P2-10.",
        "MF-P4-09.",
        "MF-P5-09.",
        "MF-P6-05.",
        "MF-P7-06.",
    )
    imported = [item_id for item_id in items if item_id.startswith(prefixes)]
    assert len(imported) == 70


def test_every_new_atomic_item_has_explicit_verification_and_blocker_clauses() -> None:
    items = _tracker_module()["parse_items_files"]()
    new_items = [
        item
        for item in items.values()
        if item["source_file"][:2].isdigit() and 11 <= int(item["source_file"][:2]) <= 20
    ]
    assert len(new_items) == 376
    for item in new_items:
        assert "Verify:" in item["description"], item["id"]
        assert "Blocked by:" in item["description"], item["id"]


def test_traceability_covers_every_later_spec_and_sam31_handoff() -> None:
    matrix = (ITEMS / "TRACEABILITY_18_22_SAM31.md").read_text(encoding="utf-8")
    for source in (
        "Doc 18",
        "Doc 19",
        "Doc 20",
        "Doc 21",
        "Doc 22",
        "Doc 25",
        "SAM 3.1",
    ):
        assert source in matrix
    for section in (
        "§1",
        "§2",
        "§3",
        "§4",
        "§5",
        "§6",
        "§7",
        "§8",
        "§9",
    ):
        assert section in matrix
    assert "**Total**" in matrix and "**70**" in matrix


def test_counts_and_owner_override_do_not_drift() -> None:
    master = (ITEMS / "00_ITEMS_MASTER_INDEX.md").read_text(encoding="utf-8")
    readme = (ROOT / "Plan" / "Tracker" / "README.md").read_text(encoding="utf-8")
    assert "Total items: 856" in master
    assert "all 856 action items" in readme


def test_tracker_and_runtime_certified_volume_targets_are_identical() -> None:
    module = _tracker_module()
    assert module["DEFAULT_METRICS"]["target_certified_p5_entry"] == P5_CERTIFIED_ENTRY_COUNT
    assert module["DEFAULT_METRICS"]["target_certified_d5"] == D5_CERTIFIED_PACKAGE_COUNT
