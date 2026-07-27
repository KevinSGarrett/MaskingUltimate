"""STATIC acquisition-plan schema + mining abstention routing (no human anchors)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from maskfactory.qa.failure_mining import make_failure_record, write_acquisition_plan
from maskfactory.qa.failure_mining_static import (
    ACTION_KINDS,
    MINING_ABSTENTION_REASONS,
    PRIORITY_WEIGHTS,
    TOP_ACTION_CAP,
    FailureMiningStaticError,
    action_kind_for_record,
    build_acquisition_plan_document,
    build_failure_mining_static_report,
    refuse_d4_or_vlm_calibration_claim,
    route_mining_abstention,
)
from maskfactory.validation import validate_document


def _record(*, image_id: str, reason: str, priority_error: float = 0.8):
    now = datetime(2026, 7, 19, tzinfo=UTC)
    return make_failure_record(
        image_id=image_id,
        body_part="left_index_finger",
        reason=reason,
        pose="front",
        model="pipeline",
        correction="manual_repaint",
        class_error_rate=priority_error,
        coverage_deficit=0.5,
        use_weight=1.0,
        event_time=now,
        now=now,
    )


def test_acquisition_plan_document_is_schema_valid_and_caps_top20() -> None:
    records = [
        _record(
            image_id=f"img_{index:012x}", reason="finger_merge", priority_error=0.9 - index * 0.01
        )
        for index in range(1, 25)
    ]

    def clusterer(reasons: tuple[str, ...]) -> dict[str, str]:
        return {reason: "hands_edge" for reason in reasons}

    document = build_acquisition_plan_document(
        records,
        report_date="2026-07-19",
        clusterer=clusterer,
        markdown_relative_path="acquisition_plan_2026-07-19.md",
    )
    assert document["weekly_plan_authority"] is True
    assert document["d4_complete"] is False
    assert document["vlm_calibration_complete"] is False
    assert document["human_anchor_authority"] is False
    assert len(document["top_actions"]) == TOP_ACTION_CAP
    assert document["unresolved_failure_count"] == 24
    assert set(document["action_kinds_used"]) <= set(ACTION_KINDS)
    assert not validate_document(document, "acquisition_plan")


def test_write_acquisition_plan_emits_markdown_and_json(tmp_path: Path) -> None:
    records = [
        _record(image_id="img_aaaaaaaaaaaa", reason="hair_edge"),
        _record(image_id="img_bbbbbbbbbbbb", reason="lr_swap"),
    ]
    path = write_acquisition_plan(
        records,
        output_dir=tmp_path,
        clusterer=lambda values: {value: "theme_a" for value in values},
        report_date="2026-07-19",
    )
    json_path = path.with_suffix(".json")
    assert path.is_file()
    assert json_path.is_file()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["weekly_plan_authority"] is True
    assert payload["d4_complete"] is False
    assert len(payload["top_actions"]) == 2
    assert {row["action_kind"] for row in payload["top_actions"]} == {
        "collect_cell_reannotate_holdout",
        "reannotate_skeleton_audit",
    }
    assert "hard_case_holdout" in path.read_text(encoding="utf-8")


def test_empty_queue_and_invalid_clusterer_abstain_without_human_anchors() -> None:
    empty = build_acquisition_plan_document(
        (),
        report_date="2026-07-19",
        clusterer=lambda reasons: {},
    )
    assert empty["weekly_plan_authority"] is False
    assert empty["abstention"]["reason"] == "empty_unresolved_queue"
    assert empty["abstention"]["human_anchor_required"] is False
    assert empty["abstention"]["may_claim_d4"] is False

    records = [_record(image_id="img_cccccccccccc", reason="qc_fail")]
    missing = build_acquisition_plan_document(
        records,
        report_date="2026-07-19",
        clusterer=lambda reasons: {},
    )
    assert missing["abstention"]["reason"] == "clusterer_missing_reasons"

    boom = build_acquisition_plan_document(
        records,
        report_date="2026-07-19",
        clusterer=lambda reasons: (_ for _ in ()).throw(RuntimeError("ollama down")),
    )
    assert boom["abstention"]["reason"] == "text_llm_unavailable"


def test_route_mining_abstention_closed_vocab_and_unknown_fails() -> None:
    for reason in sorted(MINING_ABSTENTION_REASONS):
        route = route_mining_abstention(reason, detail="seed")
        assert route["decision"] == "autonomous_abstention"
        assert route["destination"] == "residual_mining_queue"
        assert route["may_claim_vlm_calibration"] is False
        assert route["human_anchor_required"] is False
    with pytest.raises(FailureMiningStaticError, match="unknown_mining_abstention"):
        route_mining_abstention("not_a_real_reason")


def test_action_kinds_cover_governed_families() -> None:
    assert action_kind_for_record(_record(image_id="img_111111111111", reason="finger_merge")) == (
        "collect_cell_reannotate_holdout"
    )
    assert action_kind_for_record(_record(image_id="img_222222222222", reason="topology")) == (
        "reannotate_skeleton_audit"
    )
    assert action_kind_for_record(_record(image_id="img_333333333333", reason="qc_fail")) == (
        "reannotate_label_proposal"
    )
    assert (
        action_kind_for_record(_record(image_id="img_444444444444", reason="v2_lr_swap"))
        == "v2_governed_acquisition"
    )


def test_static_binder_seals_and_refuses_d4_overclaim() -> None:
    report = build_failure_mining_static_report(
        seeded_fixture_blocks={
            "acquisition_plan_validates": True,
            "invalid_clusterer_abstains": True,
            "empty_queue_abstains": True,
            "overclaim_d4_refused": True,
        }
    )
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["priority_weights"] == PRIORITY_WEIGHTS
    assert report["d4_complete"] is False
    assert report["vlm_calibration_complete"] is False
    assert not validate_document(report, "failure_mining_static_report")
    with pytest.raises(FailureMiningStaticError, match="overclaim"):
        refuse_d4_or_vlm_calibration_claim({"d4_complete": True})
    with pytest.raises(FailureMiningStaticError, match="incomplete"):
        build_failure_mining_static_report(
            seeded_fixture_blocks={"acquisition_plan_validates": True}
        )
    with pytest.raises(FailureMiningStaticError, match="not_blocked"):
        build_failure_mining_static_report(
            seeded_fixture_blocks={
                "acquisition_plan_validates": True,
                "invalid_clusterer_abstains": True,
                "empty_queue_abstains": False,
                "overclaim_d4_refused": True,
            }
        )
