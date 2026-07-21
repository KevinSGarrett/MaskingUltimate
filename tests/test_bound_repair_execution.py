from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from maskfactory.autonomy.operational_repair import DurableRepairExecutor, LiveRepairProposal
from maskfactory.autonomy.repair import BoundedRepairLimits, evaluate_repair_candidate
from maskfactory.autonomy.review_draft import CandidateQaOutcome
from maskfactory.io.hashing import sha256_file
from maskfactory.io.png_strict import write_binary_mask, write_label_map
from maskfactory.ontology import get_ontology
from maskfactory.providers.disagreement import (
    NormalizedCandidate,
    binary_mask_sha256,
    build_pairwise_disagreement,
)
from maskfactory.vlm.repair_execution import (
    RepairExecutionError,
    execute_bound_repair,
    repair_execution_binding,
)
from maskfactory.vlm.repair_intent import parse_repair_intent
from maskfactory.vlm.target_contract import target_contract_sha256


def _fixture(tmp_path: Path, *, hard_fail: bool = False):
    label = "right_foot_base"
    label_id = int(get_ontology().label(label).id)
    parent = np.zeros((10, 10), dtype=np.uint16)
    parent[4:6, 4:6] = label_id
    parent_path = write_label_map(tmp_path / "parent.png", parent, bits=16)
    candidate = np.zeros((10, 10), dtype=np.uint8)
    candidate[5:7, 5:7] = 255
    candidate_path = write_binary_mask(tmp_path / "candidate.png", candidate)
    candidate_file_hash = sha256_file(candidate_path)
    contract = {
        "schema_version": "1.0.0",
        "contract_id": "repair-target",
        "source": {"image_id": "image-1", "sha256": "a" * 64, "width": 10, "height": 10},
        "owner": {
            "person_index": 0,
            "character_instance_id": "c-1",
            "person_mask_sha256": "b" * 64,
        },
        "target": {
            "label_id": label,
            "expected_presence": "visible_nonempty",
            "minimum_area_pixels": 1,
            "maximum_area_pixels": 20,
            "allowed_roi_xyxy": [0, 0, 10, 10],
            "inclusion_rule": "visible_pixels_only",
            "exclusion_rule": "exclude_occluded_outside_owner_and_named_labels",
        },
        "candidate": {
            "mask_sha256": candidate_file_hash,
            "width": 10,
            "height": 10,
            "binary_values": [0, 255],
        },
        "excluded_labels": [],
        "protected_regions": [],
        "transforms": {
            "source_to_candidate": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "candidate_to_source": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        },
        "contract_sha256": "",
    }
    contract["contract_sha256"] = target_contract_sha256(contract)
    left_mask = parent == label_id
    right_mask = candidate != 0
    disagreement = build_pairwise_disagreement(
        NormalizedCandidate(
            "parent",
            "incumbent",
            "a" * 64,
            contract["contract_sha256"],
            binary_mask_sha256(left_mask),
            0,
            left_mask,
        ),
        NormalizedCandidate(
            "repair",
            "challenger",
            "a" * 64,
            contract["contract_sha256"],
            binary_mask_sha256(right_mask),
            0,
            right_mask,
        ),
        normalized_shape=(10, 10),
    ).report
    response = {
        "schema_version": "1.0.0",
        "verdict": "defect",
        "target_contract_sha256": contract["contract_sha256"],
        "panel_set_sha256": "e" * 64,
        "findings": [
            {
                "defect_type": "boundary",
                "bbox_xyxy": [0, 0, 10, 10],
                "evidence_panel_sha256": "f" * 64,
                "confidence": 0.9,
            }
        ],
        "repair_plan": {
            "operations": [
                {
                    "operation": "roi_resegment",
                    "label_id": label,
                    "roi_xyxy": [0, 0, 10, 10],
                    "parameters": {"provider_role": "interactive_segmenter"},
                }
            ],
            "max_rounds": 2,
            "max_seconds": 60,
        },
    }
    intent = parse_repair_intent(
        response,
        target_contract=contract,
        panel_set_sha256="e" * 64,
        allowed_panel_sha256={"f" * 64},
    )
    qa = (
        CandidateQaOutcome(("QC-HARD",), None, "fail", score=0.8, baseline_score=0.7)
        if hard_fail
        else CandidateQaOutcome(
            (), None, "pass", score=0.8, baseline_score=0.7, non_regressing=True
        )
    )
    executor = DurableRepairExecutor(
        state_path=tmp_path / "state.json",
        accepted_map_path=parent_path,
        accepted_parent_id="parent-v1",
        limits=BoundedRepairLimits(2, 60, 5, 2, 1000),
        map_validator=lambda _p, _s: qa,
        output_dir=tmp_path / "out",
    )
    binding = repair_execution_binding(
        accepted_parent_id="parent-v1",
        accepted_parent_map_sha256=sha256_file(parent_path),
        candidate_mask_sha256=candidate_file_hash,
        target_contract_sha256=contract["contract_sha256"],
        repair_intent_sha256=intent["repair_intent_sha256"],
        disagreement_report_sha256=disagreement["report_sha256"],
        operation_index=0,
    )
    guard = evaluate_repair_candidate(
        right_mask,
        current_mask=left_mask,
        protected_mask=np.zeros((10, 10), dtype=bool),
        label=label,
        roi_xyxy=(0, 0, 10, 10),
        person_bbox_xyxy=(0, 0, 10, 10),
        ordinary_max_changed_fraction=2.0,
        reconstruction_max_changed_fraction=2.0,
        maximum_protected_overlap_fraction=0.01,
        maximum_outside_roi_fraction=0.005,
        expected_area_slack=1.0,
    )
    proposal = LiveRepairProposal(
        "parent-v1",
        f"repair-{binding[:24]}",
        label,
        candidate_path,
        candidate_file_hash,
        700000,
        1,
        1,
        guard,
        (0, 0, 10, 10),
    )
    return executor, proposal, intent, disagreement, contract


def test_bound_repair_recomposes_complete_map_and_durably_binds_evidence(tmp_path: Path) -> None:
    executor, proposal, intent, disagreement, contract = _fixture(tmp_path)
    result = execute_bound_repair(
        executor=executor,
        proposal=proposal,
        repair_intent=intent,
        disagreement_report=disagreement,
        target_contract=contract,
        operation_index=0,
    )
    assert result.outcome == "accepted_reversible_repair"
    state = json.loads(result.state_path.read_text())
    assert len(state["attempts"][0]["repair_binding_sha256"]) == 64


def test_hard_qa_failure_rolls_back_without_parent_mutation(tmp_path: Path) -> None:
    executor, proposal, intent, disagreement, contract = _fixture(tmp_path, hard_fail=True)
    parent_hash = sha256_file(executor.accepted_map_path)
    result = execute_bound_repair(
        executor=executor,
        proposal=proposal,
        repair_intent=intent,
        disagreement_report=disagreement,
        target_contract=contract,
        operation_index=0,
    )
    assert result.rollback_performed
    assert sha256_file(executor.accepted_map_path) == parent_hash


@pytest.mark.parametrize("drift", ["label", "roi", "hypothesis", "intent", "disagreement"])
def test_bound_repair_rejects_evidence_or_scope_drift(tmp_path: Path, drift: str) -> None:
    executor, proposal, intent, disagreement, contract = _fixture(tmp_path)
    if drift == "label":
        proposal = replace(proposal, label="left_foot_base")
    elif drift == "roi":
        proposal = replace(proposal, repair_roi_xyxy=(1, 1, 9, 9))
    elif drift == "hypothesis":
        proposal = replace(proposal, hypothesis_id="invented")
    elif drift == "intent":
        intent["repair_intent_sha256"] = "f" * 64
    else:
        disagreement["report_sha256"] = "f" * 64
    with pytest.raises(RepairExecutionError):
        execute_bound_repair(
            executor=executor,
            proposal=proposal,
            repair_intent=intent,
            disagreement_report=disagreement,
            target_contract=contract,
            operation_index=0,
        )
