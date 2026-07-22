from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_bulk_semantic_review_is_durable_across_session_authorities() -> None:
    standing_orders = _text("Plan/STANDING_ORDERS_AUTONOMOUS_BUILD.md")
    start_here = _text("Plan/Instructions/00_START_HERE.md")
    playbook = _text("Plan/Instructions/03_SESSION_PLAYBOOK.md")
    critic_instruction = _text(
        "Plan/Instructions/14_SELF_HOSTED_VISUAL_AUTHORITY_AND_RUNPOD_MIGRATION.md"
    )
    spec = _text("Plan/25_SELF_HOSTED_VISUAL_AUTHORITY_AND_RUNPOD_MIGRATION_SPEC.md")
    item = _text("Plan/Items/15_ITEMS_P4_AUTONOMY_AND_TEACHERS.md")

    for authority in (standing_orders, start_here, critic_instruction, spec, item):
        assert "C:\\Comfy_UI_Main\\MaskedWarehouse" in authority
        assert "F:\\Reference_Images" in authority

    for authority in (standing_orders, start_here, playbook, critic_instruction, spec):
        normalized = authority.lower()
        assert "bulk" in normalized
        assert "independent-family" in normalized
        assert "exception" in normalized
        assert "human review" in normalized

    assert "MF-P4-11.26" in item
    assert "compact summary/exception reports" in item
