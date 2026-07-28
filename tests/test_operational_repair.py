from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np

from maskfactory.autonomy.operational_repair import (
    DurableRepairExecutor,
    LiveRepairProposal,
)
from maskfactory.autonomy.repair import (
    BoundedRepairLimits,
    RepairGuardResult,
    evaluate_repair_candidate,
)
from maskfactory.autonomy.review_draft import CandidateQaOutcome
from maskfactory.io.hashing import sha256_file
from maskfactory.io.png_strict import write_binary_mask, write_label_map
from maskfactory.ontology import get_ontology


def _fixture(
    tmp_path: Path, *, qa: CandidateQaOutcome
) -> tuple[DurableRepairExecutor, LiveRepairProposal]:
    ontology = get_ontology()
    label_id = int(ontology.label("right_foot_base").id)
    parent = np.zeros((10, 10), dtype=np.uint16)
    parent[4:6, 4:6] = label_id
    parent_path = write_label_map(tmp_path / "accepted_parent.png", parent, bits=16)
    candidate = np.zeros((10, 10), dtype=np.uint8)
    candidate[5:7, 5:7] = 255
    candidate_path = write_binary_mask(tmp_path / "candidate.png", candidate)
    guard = evaluate_repair_candidate(
        candidate != 0,
        current_mask=parent == label_id,
        protected_mask=np.zeros((10, 10), dtype=bool),
        label="right_foot_base",
        roi_xyxy=(0, 0, 10, 10),
        person_bbox_xyxy=(0, 0, 10, 10),
        ordinary_max_changed_fraction=2.0,
        reconstruction_max_changed_fraction=2.0,
        maximum_protected_overlap_fraction=0.01,
        maximum_outside_roi_fraction=0.005,
        expected_area_slack=1.0,
    )
    executor = DurableRepairExecutor(
        state_path=tmp_path / "repair-state.json",
        accepted_map_path=parent_path,
        accepted_parent_id="accepted-parent-v1",
        limits=BoundedRepairLimits(2, 60, 5, 2, 1_000),
        map_validator=lambda _path, _scope: qa,
        output_dir=tmp_path / "repair-output",
    )
    proposal = LiveRepairProposal(
        accepted_parent_id="accepted-parent-v1",
        hypothesis_id="shift-foot-boundary",
        label="right_foot_base",
        candidate_mask_path=candidate_path,
        candidate_mask_sha256=sha256_file(candidate_path),
        score_ppm=700_000,
        elapsed_seconds=1,
        resource_units=1,
        guard=guard,
        repair_roi_xyxy=(0, 0, 10, 10),
    )
    return executor, proposal


def test_live_repair_accepts_only_improved_complete_map_and_keeps_parent_immutable(
    tmp_path: Path,
) -> None:
    qa = CandidateQaOutcome((), None, "pass", score=0.80, baseline_score=0.70, non_regressing=True)
    executor, proposal = _fixture(tmp_path, qa=qa)
    original_parent_sha = sha256_file(executor.accepted_map_path)

    result = executor.execute(proposal)

    assert result.outcome == "accepted_reversible_repair"
    assert not result.rollback_performed
    assert sha256_file(tmp_path / "accepted_parent.png") == original_parent_sha
    assert result.accepted_map_path != tmp_path / "accepted_parent.png"
    state = json.loads(result.state_path.read_text(encoding="utf-8"))
    assert state["attempts"][0]["hypothesis_id"] == "shift-foot-boundary"
    assert state["attempts"][0]["accepted_parent_map_sha256"] == original_parent_sha
    assert state["attempts"][0]["outcome"] == "accepted_reversible_repair"


def test_live_repair_rolls_back_failed_qa_then_ends_in_autonomous_abstention(
    tmp_path: Path,
) -> None:
    qa = CandidateQaOutcome(("QC-BLOCK",), None, "fail", score=0.80, baseline_score=0.70)
    executor, proposal = _fixture(tmp_path, qa=qa)
    original_parent_sha = sha256_file(executor.accepted_map_path)

    retry = executor.execute(proposal)
    terminal = executor.execute(replace(proposal, hypothesis_id="alternative-prompt"))

    assert retry.outcome == "rolled_back_retry_distinct_hypothesis"
    assert terminal.outcome == "rolled_back_autonomous_abstention"
    assert terminal.rollback_performed
    assert "human" not in terminal.outcome
    assert sha256_file(tmp_path / "accepted_parent.png") == original_parent_sha
    state = json.loads(terminal.state_path.read_text(encoding="utf-8"))
    assert state["terminal_outcome"] == "rolled_back_autonomous_abstention"
    assert [record["hypothesis_id"] for record in state["attempts"]] == [
        "shift-foot-boundary",
        "alternative-prompt",
    ]


def test_duplicate_hypothesis_is_durably_abstained_without_mutating_parent(tmp_path: Path) -> None:
    qa = CandidateQaOutcome((), None, "pass", score=0.80, baseline_score=0.70, non_regressing=True)
    executor, proposal = _fixture(tmp_path, qa=qa)
    executor.execute(replace(proposal, hypothesis_id="unsafe-first", guard=_unsafe_guard()))

    result = executor.execute(replace(proposal, hypothesis_id="unsafe-first"))

    assert result.outcome == "rolled_back_autonomous_abstention"
    assert "hypothesis_not_distinct" in result.reason
    assert sha256_file(result.accepted_map_path) == sha256_file(tmp_path / "accepted_parent.png")


def _unsafe_guard() -> RepairGuardResult:
    return evaluate_repair_candidate(
        np.ones((10, 10), dtype=bool),
        current_mask=np.zeros((10, 10), dtype=bool),
        protected_mask=np.zeros((10, 10), dtype=bool),
        label="right_foot_base",
        roi_xyxy=(0, 0, 10, 10),
        person_bbox_xyxy=(0, 0, 10, 10),
        ordinary_max_changed_fraction=0.01,
        reconstruction_max_changed_fraction=0.01,
        maximum_protected_overlap_fraction=0.01,
        maximum_outside_roi_fraction=0.005,
        expected_area_slack=0.1,
    )
