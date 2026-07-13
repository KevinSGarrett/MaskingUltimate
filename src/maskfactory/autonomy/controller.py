"""Bounded autonomous correction rounds around the hard-vetoed mask tournament."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .tournament import CandidateEvidence, TournamentDecision, run_candidate_tournament


class CorrectionRoundGenerator(Protocol):
    def __call__(
        self,
        *,
        round_number: int,
        prior_candidates: tuple[CandidateEvidence, ...],
        prior_decision: TournamentDecision,
    ) -> tuple[CandidateEvidence, ...]: ...


@dataclass(frozen=True)
class AutonomousLoopResult:
    decision: TournamentDecision
    rounds_executed: int
    candidate_count: int
    stopped_reason: str


def run_autonomous_correction_loop(
    initial_candidates: tuple[CandidateEvidence, ...],
    *,
    label: str,
    context: str,
    pipeline_fingerprint: str,
    config: dict,
    correction_generator: CorrectionRoundGenerator,
    certificate: dict | None = None,
) -> AutonomousLoopResult:
    """Generate and retest isolated candidates until selection or a strict bound is reached."""
    maximum_rounds = int(config["tournament"]["maximum_rounds"])
    maximum_candidates = int(config["tournament"]["maximum_candidates_per_label"])
    candidates = list(initial_candidates)
    if not candidates:
        raise ValueError("autonomous correction loop requires an initial candidate")
    for round_number in range(maximum_rounds + 1):
        decision = run_candidate_tournament(
            tuple(candidates),
            label=label,
            context=context,
            pipeline_fingerprint=pipeline_fingerprint,
            config=config,
            certificate=certificate,
        )
        if decision.status != "residual_human_queue":
            return AutonomousLoopResult(
                decision, round_number, len(candidates), "candidate_selected"
            )
        if round_number >= maximum_rounds:
            return AutonomousLoopResult(
                decision, round_number, len(candidates), "maximum_rounds_exhausted"
            )
        generated = correction_generator(
            round_number=round_number + 1,
            prior_candidates=tuple(candidates),
            prior_decision=decision,
        )
        existing_ids = {candidate.candidate_id for candidate in candidates}
        existing_hashes = {candidate.mask_sha256 for candidate in candidates}
        added = []
        for candidate in generated:
            if candidate.candidate_id in existing_ids or candidate.mask_sha256 in existing_hashes:
                continue
            if len(candidates) + len(added) >= maximum_candidates:
                break
            added.append(candidate)
            existing_ids.add(candidate.candidate_id)
            existing_hashes.add(candidate.mask_sha256)
        if not added:
            return AutonomousLoopResult(
                decision, round_number + 1, len(candidates), "no_novel_safe_candidate"
            )
        candidates.extend(added)
    raise AssertionError("bounded autonomous loop terminated unexpectedly")


__all__ = [
    "AutonomousLoopResult",
    "CorrectionRoundGenerator",
    "run_autonomous_correction_loop",
]
