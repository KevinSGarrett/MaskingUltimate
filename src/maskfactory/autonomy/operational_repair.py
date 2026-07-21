"""Durable, bounded execution for live autonomous repair proposals.

This module is deliberately downstream of proposal generation.  Providers may suggest
many masks, but each proposal is evaluated from an immutable accepted-map snapshot and
can end only in a reversible accepted repair or typed autonomous abstention.  It never
creates a mandatory-human route.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from ..io.hashing import sha256_file
from ..io.png_strict import write_label_map
from .repair import (
    BoundedRepairLimits,
    RepairAttempt,
    RepairGuardResult,
    decide_bounded_repair,
)
from .review_draft import CandidateQaOutcome, compose_candidate_map_transactional


class OperationalRepairError(ValueError):
    """A live repair request or its persisted state is invalid."""


@dataclass(frozen=True)
class LiveRepairProposal:
    """One material child hypothesis proposed against an accepted parent."""

    accepted_parent_id: str
    hypothesis_id: str
    label: str
    candidate_mask_path: Path
    candidate_mask_sha256: str
    score_ppm: int
    elapsed_seconds: float
    resource_units: float
    guard: RepairGuardResult
    repair_roi_xyxy: tuple[int, int, int, int]
    repair_binding_sha256: str | None = None
    immutable_label_ids: tuple[int, ...] = ()
    maximum_displaced_labels: int = 8


@dataclass(frozen=True)
class OperationalRepairResult:
    """One durable terminal response to a live repair proposal."""

    outcome: str
    reason: str
    accepted_parent_id: str
    accepted_map_path: Path
    accepted_map_sha256: str
    attempt_number: int
    rollback_performed: bool
    state_path: Path


MapQaValidator = Callable[[Path, str], CandidateQaOutcome]


class DurableRepairExecutor:
    """Apply one proposal transactionally and persist every attempted hypothesis."""

    def __init__(
        self,
        *,
        state_path: Path,
        accepted_map_path: Path,
        accepted_parent_id: str,
        limits: BoundedRepairLimits,
        map_validator: MapQaValidator,
        output_dir: Path,
    ) -> None:
        self.state_path = Path(state_path)
        self.accepted_map_path = Path(accepted_map_path)
        self.accepted_parent_id = accepted_parent_id
        self.limits = limits
        self.map_validator = map_validator
        self.output_dir = Path(output_dir)

    def execute(self, proposal: LiveRepairProposal) -> OperationalRepairResult:
        """Record and evaluate a child without mutating the accepted parent in place."""
        _validate_proposal(proposal)
        state = self._load_or_initialize()
        if state["accepted_parent_id"] != proposal.accepted_parent_id:
            raise OperationalRepairError("proposal is not bound to the current accepted parent")
        if state["terminal_outcome"] is not None:
            return self._result(
                state,
                outcome=state["terminal_outcome"],
                reason="repair_session_already_terminal",
                rollback_performed=True,
            )
        self.accepted_map_path = Path(state["accepted_map_path"])
        if state["accepted_map_sha256"] != sha256_file(self.accepted_map_path):
            raise OperationalRepairError("accepted parent map drifted after state initialization")

        history = tuple(
            RepairAttempt(
                proposal.accepted_parent_id,
                record["hypothesis_id"],
                record["score_ppm"],
                record["elapsed_seconds"],
                record["resource_units"],
            )
            for record in state["attempts"]
        )
        decision = decide_bounded_repair(
            accepted_parent_id=proposal.accepted_parent_id,
            hypothesis_id=proposal.hypothesis_id,
            guard=proposal.guard,
            current_score_ppm=proposal.score_ppm,
            attempt_elapsed_seconds=proposal.elapsed_seconds,
            attempt_resource_units=proposal.resource_units,
            limits=self.limits,
            history=history,
        )
        if decision.outcome != "accepted_reversible_repair":
            return self._record_rollback(state, proposal, decision.outcome, decision.reason)

        attempt_number = len(state["attempts"]) + 1
        candidate_map_path, qa = self._build_and_validate_candidate(proposal, attempt_number)
        qa_reason = _qa_rejection_reason(qa)
        if qa_reason is not None:
            return self._record_rollback(
                state, proposal, "rolled_back_retry_distinct_hypothesis", qa_reason
            )
        if not _score_improved(qa, self.limits.minimum_score_improvement_ppm):
            return self._record_rollback(
                state,
                proposal,
                "rolled_back_retry_distinct_hypothesis",
                "complete_map_evidence_not_improved",
            )

        accepted_path = (
            self.output_dir / f"accepted_{attempt_number:03d}_{proposal.hypothesis_id}.png"
        )
        accepted_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(candidate_map_path, accepted_path)
        accepted_map_sha256 = sha256_file(accepted_path)
        self._append_attempt(
            state,
            proposal,
            outcome="accepted_reversible_repair",
            reason="complete_map_qa_improved",
            candidate_complete_map_sha256=accepted_map_sha256,
        )
        state["accepted_map_path"] = str(accepted_path)
        state["accepted_map_sha256"] = accepted_map_sha256
        self.accepted_map_path = accepted_path
        self._save(state)
        return self._result(
            state,
            outcome="accepted_reversible_repair",
            reason="complete_map_qa_improved",
            rollback_performed=False,
        )

    def _build_and_validate_candidate(
        self, proposal: LiveRepairProposal, attempt_number: int
    ) -> tuple[Path, CandidateQaOutcome]:
        with Image.open(self.accepted_map_path) as image:
            parent = np.asarray(image)
        candidate, vetoes, _ = compose_candidate_map_transactional(
            parent,
            label=proposal.label,
            candidate_mask_path=proposal.candidate_mask_path,
            repair_roi_xyxy=proposal.repair_roi_xyxy,
            immutable_label_ids=proposal.immutable_label_ids,
            maximum_displaced_labels=proposal.maximum_displaced_labels,
        )
        if vetoes:
            return self.accepted_map_path, CandidateQaOutcome(
                tuple(vetoes), None, "fail", non_regressing=False
            )
        path = write_label_map(
            self.output_dir / "candidates" / f"{attempt_number:03d}_{proposal.hypothesis_id}.png",
            candidate,
            bits=16,
        )
        return path, self.map_validator(path, f"autonomous_repair_{proposal.hypothesis_id}")

    def _record_rollback(
        self, state: dict, proposal: LiveRepairProposal, outcome: str, reason: str
    ) -> OperationalRepairResult:
        attempt_cap_reached = len(state["attempts"]) + 1 >= self.limits.maximum_attempts
        terminal = outcome == "rolled_back_abstain" or attempt_cap_reached
        final_outcome = "rolled_back_autonomous_abstention" if terminal else outcome
        final_reason = reason if not terminal else f"{reason}:attempt_cap_exhausted"
        self._append_attempt(state, proposal, outcome=final_outcome, reason=final_reason)
        if terminal:
            state["terminal_outcome"] = "rolled_back_autonomous_abstention"
        self._save(state)
        return self._result(
            state,
            outcome=final_outcome,
            reason=final_reason,
            rollback_performed=True,
        )

    def _load_or_initialize(self) -> dict:
        if self.state_path.exists():
            try:
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise OperationalRepairError("durable repair state is unreadable") from exc
            _validate_state(state)
            return state
        if not self.accepted_map_path.is_file():
            raise OperationalRepairError("accepted parent map is unavailable")
        state = {
            "schema_version": "1.0.0",
            "accepted_parent_id": self.accepted_parent_id,
            "accepted_map_path": str(self.accepted_map_path),
            "accepted_map_sha256": sha256_file(self.accepted_map_path),
            "attempts": [],
            "terminal_outcome": None,
        }
        self._save(state)
        return state

    def _append_attempt(self, state: dict, proposal: LiveRepairProposal, **outcome: str) -> None:
        state["attempts"].append(
            {
                "accepted_parent_id": state["accepted_parent_id"],
                "accepted_parent_map_sha256": state["accepted_map_sha256"],
                "hypothesis_id": proposal.hypothesis_id,
                "candidate_mask_sha256": proposal.candidate_mask_sha256,
                "repair_binding_sha256": proposal.repair_binding_sha256,
                "score_ppm": proposal.score_ppm,
                "elapsed_seconds": proposal.elapsed_seconds,
                "resource_units": proposal.resource_units,
                **outcome,
            }
        )

    def _save(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.tmp-{uuid.uuid4().hex}")
        try:
            temporary.write_text(
                json.dumps(state, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
            os.replace(temporary, self.state_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _result(
        self, state: dict, *, outcome: str, reason: str, rollback_performed: bool
    ) -> OperationalRepairResult:
        return OperationalRepairResult(
            outcome=outcome,
            reason=reason,
            accepted_parent_id=state["accepted_parent_id"],
            accepted_map_path=Path(state["accepted_map_path"]),
            accepted_map_sha256=state["accepted_map_sha256"],
            attempt_number=len(state["attempts"]),
            rollback_performed=rollback_performed,
            state_path=self.state_path,
        )


def _score_improved(qa: CandidateQaOutcome, minimum_improvement_ppm: int) -> bool:
    if qa.score is None or qa.baseline_score is None:
        return False
    return round((qa.score - qa.baseline_score) * 1_000_000) >= minimum_improvement_ppm


def _qa_rejection_reason(qa: CandidateQaOutcome) -> str | None:
    if qa.block_qc_ids:
        return "complete_map_hard_qa_failed"
    if qa.overall != "pass":
        return "complete_map_qa_not_pass"
    if not qa.non_regressing:
        return "complete_map_regression"
    return None


def _validate_proposal(proposal: LiveRepairProposal) -> None:
    if not isinstance(proposal, LiveRepairProposal):
        raise OperationalRepairError("live repair proposal is invalid")
    if not proposal.accepted_parent_id or not proposal.hypothesis_id or not proposal.label:
        raise OperationalRepairError("proposal identity fields are required")
    if not proposal.candidate_mask_path.is_file():
        raise OperationalRepairError("proposal candidate mask is unavailable")
    if sha256_file(proposal.candidate_mask_path) != proposal.candidate_mask_sha256:
        raise OperationalRepairError("proposal candidate mask hash drifted")
    if proposal.repair_binding_sha256 is not None and (
        len(proposal.repair_binding_sha256) != 64
        or any(character not in "0123456789abcdef" for character in proposal.repair_binding_sha256)
    ):
        raise OperationalRepairError("proposal repair binding hash is invalid")


def _validate_state(state: object) -> None:
    if not isinstance(state, dict) or set(state) != {
        "schema_version",
        "accepted_parent_id",
        "accepted_map_path",
        "accepted_map_sha256",
        "attempts",
        "terminal_outcome",
    }:
        raise OperationalRepairError("durable repair state contract is invalid")
    if state["schema_version"] != "1.0.0" or not isinstance(state["attempts"], list):
        raise OperationalRepairError("durable repair state version is invalid")
    for record in state["attempts"]:
        if not isinstance(record, dict) or not {
            "accepted_parent_id",
            "accepted_parent_map_sha256",
            "hypothesis_id",
            "candidate_mask_sha256",
            "score_ppm",
            "elapsed_seconds",
            "resource_units",
            "outcome",
            "reason",
        } <= set(record):
            raise OperationalRepairError("durable repair attempt history is invalid")


__all__ = [
    "DurableRepairExecutor",
    "LiveRepairProposal",
    "OperationalRepairError",
    "OperationalRepairResult",
]
