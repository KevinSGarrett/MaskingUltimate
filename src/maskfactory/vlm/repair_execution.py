"""Bind disagreement and critic intent to durable transactional repair execution."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from maskfactory.autonomy.operational_repair import (
    DurableRepairExecutor,
    LiveRepairProposal,
    OperationalRepairResult,
)
from maskfactory.io.hashing import sha256_file

from .critic_catalog import canonical_sha256
from .target_contract import validate_target_contract


class RepairExecutionError(ValueError):
    """Repair intent, disagreement, proposal, or accepted parent is not exactly bound."""


def _intent_sha256(intent: dict[str, Any]) -> str:
    return canonical_sha256(
        {key: value for key, value in intent.items() if key != "repair_intent_sha256"}
    )


def repair_execution_binding(
    *,
    accepted_parent_id: str,
    accepted_parent_map_sha256: str,
    candidate_mask_sha256: str,
    target_contract_sha256: str,
    repair_intent_sha256: str,
    disagreement_report_sha256: str,
    operation_index: int,
) -> str:
    return canonical_sha256(
        {
            "schema_version": "1.0.0",
            "accepted_parent_id": accepted_parent_id,
            "accepted_parent_map_sha256": accepted_parent_map_sha256,
            "candidate_mask_sha256": candidate_mask_sha256,
            "target_contract_sha256": target_contract_sha256,
            "repair_intent_sha256": repair_intent_sha256,
            "disagreement_report_sha256": disagreement_report_sha256,
            "operation_index": operation_index,
        }
    )


def execute_bound_repair(
    *,
    executor: DurableRepairExecutor,
    proposal: LiveRepairProposal,
    repair_intent: dict[str, Any],
    disagreement_report: dict[str, Any],
    target_contract: dict[str, Any],
    operation_index: int,
) -> OperationalRepairResult:
    """Execute one operation only after all immutable repair evidence agrees."""

    try:
        validate_target_contract(target_contract)
    except Exception as exc:
        raise RepairExecutionError(f"repair target is invalid: {exc}") from exc
    intent_hash = repair_intent.get("repair_intent_sha256")
    if intent_hash != _intent_sha256(repair_intent):
        raise RepairExecutionError("repair intent canonical hash mismatch")
    target_hash = target_contract["contract_sha256"]
    if repair_intent.get("target_contract_sha256") != target_hash:
        raise RepairExecutionError("repair intent target differs from execution target")
    if disagreement_report.get("target_contract_sha256") != target_hash:
        raise RepairExecutionError("disagreement target differs from execution target")
    report_hash = disagreement_report.get("report_sha256")
    if report_hash != canonical_sha256(
        {key: value for key, value in disagreement_report.items() if key != "report_sha256"}
    ):
        raise RepairExecutionError("disagreement report canonical hash mismatch")
    operations = repair_intent.get("repair_plan", {}).get("operations", [])
    if not isinstance(operation_index, int) or not 0 <= operation_index < len(operations):
        raise RepairExecutionError("repair operation index is unavailable")
    operation = operations[operation_index]
    if proposal.label != target_contract["target"]["label_id"] or proposal.label != operation.get(
        "label_id"
    ):
        raise RepairExecutionError("repair proposal label differs from bound intent")
    if list(proposal.repair_roi_xyxy) != operation.get("roi_xyxy"):
        raise RepairExecutionError("repair proposal ROI differs from bound intent")
    if proposal.accepted_parent_id != executor.accepted_parent_id:
        raise RepairExecutionError("repair proposal parent differs from active executor")
    if not executor.accepted_map_path.is_file():
        raise RepairExecutionError("accepted parent map is unavailable")
    parent_hash = sha256_file(executor.accepted_map_path)
    binding = repair_execution_binding(
        accepted_parent_id=proposal.accepted_parent_id,
        accepted_parent_map_sha256=parent_hash,
        candidate_mask_sha256=proposal.candidate_mask_sha256,
        target_contract_sha256=target_hash,
        repair_intent_sha256=intent_hash,
        disagreement_report_sha256=report_hash,
        operation_index=operation_index,
    )
    expected_hypothesis_id = f"repair-{binding[:24]}"
    if proposal.hypothesis_id != expected_hypothesis_id:
        raise RepairExecutionError("repair hypothesis ID is not derived from exact evidence")
    return executor.execute(replace(proposal, repair_binding_sha256=binding))
