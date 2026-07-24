from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from tools.build_visual_corpus_source_deficits import build as build_deficits

from maskfactory.vlm.control_candidate_plan import (
    ControlCandidatePlanError,
    build_visual_control_candidate_plan,
    verify_visual_control_candidate_plan,
)

ROOT = Path(__file__).resolve().parents[1]


def _candidate(*, candidate_id: str, source_kind: str, label: str = "left_hand_base") -> dict:
    draft = source_kind == "shard0001_draft_machine"
    return {
        "candidate_id": candidate_id,
        "canonical_label": label,
        "source_kind": source_kind,
        "source_authority_tier": (
            "draft_machine_candidate" if draft else "external_labeled_reference"
        ),
        "source_sha256": ("a" if draft else "b") * 64,
        "panel_set_sha256": ("c" if draft else "d") * 64,
        "identity_group_id": f"identity-{candidate_id}",
        "partition": "calibration",
        "exact_canonical_semantics": True,
        "deterministic_hard_qc_pass": draft,
        "multi_provider_pixel_consensus": draft,
    }


def test_plan_emits_every_missing_label_and_orders_source_families(tmp_path: Path) -> None:
    deficits = build_deficits(tmp_path / "deficits.json")
    plan = build_visual_control_candidate_plan(
        source_deficit_report=deficits,
        candidate_catalog=[
            _candidate(candidate_id="draft-hand", source_kind="shard0001_draft_machine"),
            _candidate(candidate_id="polygon-hand", source_kind="qualified_polygon_or_rle"),
        ],
    )
    verify_visual_control_candidate_plan(plan, source_deficit_report=deficits)
    assert plan["planned_deficit_label_count"] == 64
    hand = next(batch for batch in plan["batches"] if batch["canonical_label"] == "left_hand_base")
    assert [row["candidate_id"] for row in hand["candidates"]] == ["polygon-hand", "draft-hand"]
    assert all(row["admission_ceiling"] == "calibration_only" for row in hand["candidates"])
    assert all(row["requires_session_agent_screening"] for row in hand["candidates"])
    assert plan["unfilled_deficit_label_count"] == 63


def test_draft_requires_hard_qc_and_consensus_before_screening(tmp_path: Path) -> None:
    deficits = build_deficits(tmp_path / "deficits.json")
    draft = _candidate(candidate_id="draft-hand", source_kind="shard0001_draft_machine")
    draft["multi_provider_pixel_consensus"] = False
    with pytest.raises(ControlCandidatePlanError, match="Amendment-3 prerequisites"):
        build_visual_control_candidate_plan(
            source_deficit_report=deficits, candidate_catalog=[draft]
        )


def test_plan_never_uses_existing_eligible_label_as_a_deficit_candidate(tmp_path: Path) -> None:
    deficits = build_deficits(tmp_path / "deficits.json")
    with pytest.raises(ControlCandidatePlanError, match="current deficit label"):
        build_visual_control_candidate_plan(
            source_deficit_report=deficits,
            candidate_catalog=[
                _candidate(
                    candidate_id="already-covered-hair",
                    source_kind="qualified_polygon_or_rle",
                    label="hair",
                )
            ],
        )


def test_plan_hash_and_authority_drift_fail_closed(tmp_path: Path) -> None:
    deficits = build_deficits(tmp_path / "deficits.json")
    plan = build_visual_control_candidate_plan(source_deficit_report=deficits, candidate_catalog=[])
    drifted = deepcopy(plan)
    drifted["promotion_allowed"] = True
    with pytest.raises(ControlCandidatePlanError, match="authority or hash drift"):
        verify_visual_control_candidate_plan(drifted, source_deficit_report=deficits)
