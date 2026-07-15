"""Hard-vetoed candidate tournament for progressive autonomous mask selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .calibration import verify_autonomy_certificate
from .multi_person_gate import MultiPersonCandidateGateResult
from .multi_person_scope import MultiPersonCertificationScopeResult


class AutonomyTournamentError(RuntimeError):
    """Candidate evidence or policy cannot support a tournament."""


@dataclass(frozen=True)
class CandidateEvidence:
    candidate_id: str
    mask_path: str
    mask_sha256: str
    independent_sources: int
    consensus_iou: float
    boundary_agreement: float
    pose_consistency: float
    critic_pass_weight: float
    critic_disagreement: bool
    protected_overlap: float
    exclusive_overlap: float
    component_count: int
    ontology_max_components: int
    format_valid: bool
    block_qc_ids: tuple[str, ...]
    source_provider_keys: tuple[str, ...] = ()
    source_model_families: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoredCandidate:
    candidate_id: str
    score: float
    eligible: bool
    vetoes: tuple[str, ...]
    evidence: CandidateEvidence


@dataclass(frozen=True)
class TournamentDecision:
    label: str
    context: str
    status: str
    winner_id: str | None
    winner_score: float | None
    runner_up_score: float | None
    certificate_valid: bool
    certificate_reason: str
    human_audit_required: bool
    authoritative_gold: bool
    reason: str
    ranking: tuple[ScoredCandidate, ...]
    truth_tier: str = "machine_candidate"
    training_loss_weight: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_candidate_tournament(
    candidates: tuple[CandidateEvidence, ...],
    *,
    label: str,
    context: str,
    pipeline_fingerprint: str,
    config: dict[str, Any],
    certificate: dict[str, Any] | None = None,
    instance_context: str = "solo",
    multi_person_gate: MultiPersonCandidateGateResult | None = None,
    multi_person_scope: MultiPersonCertificationScopeResult | None = None,
) -> TournamentDecision:
    if not candidates:
        raise AutonomyTournamentError("candidate tournament requires at least one candidate")
    tournament = config["tournament"]
    if len(candidates) > int(tournament["maximum_candidates_per_label"]):
        raise AutonomyTournamentError("candidate count exceeds the bounded tournament maximum")
    if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
        raise AutonomyTournamentError("candidate IDs must be unique")
    for candidate in candidates:
        _validate_source_provenance(candidate)
    if instance_context not in {"solo", "duo", "small_group"}:
        raise AutonomyTournamentError("instance context must be solo, duo, or small_group")
    if instance_context == "solo" and (
        multi_person_gate is not None or multi_person_scope is not None
    ):
        raise AutonomyTournamentError("solo candidate cannot carry multi-person evidence")
    multi_person_vetoes: tuple[str, ...] = ()
    if instance_context != "solo":
        if multi_person_gate is None:
            multi_person_vetoes = ("multi_person_gate_missing",)
        elif multi_person_gate.instance_context != instance_context:
            raise AutonomyTournamentError("multi-person gate context differs from tournament")
        elif not multi_person_gate.passed:
            multi_person_vetoes = tuple(
                f"multi_person_gate:{check_id}" for check_id in multi_person_gate.blockers
            )
        if multi_person_scope is None:
            multi_person_vetoes = (*multi_person_vetoes, "multi_person_scope_missing")
        elif multi_person_scope.instance_context != instance_context:
            raise AutonomyTournamentError("multi-person scope context differs from tournament")
        elif not multi_person_scope.passed:
            multi_person_vetoes = (
                *multi_person_vetoes,
                *(f"multi_person_scope:{reason}" for reason in multi_person_scope.blockers),
            )
    ranking = tuple(
        sorted(
            (_score(candidate, tournament, multi_person_vetoes) for candidate in candidates),
            key=lambda item: (-item.eligible, -item.score, item.candidate_id),
        )
    )
    eligible = [candidate for candidate in ranking if candidate.eligible]
    certificate_valid, certificate_reason = verify_autonomy_certificate(
        certificate,
        label=label,
        context=context,
        instance_context=instance_context,
        pipeline_fingerprint=pipeline_fingerprint,
        risk_bucket=(multi_person_scope.risk_bucket if multi_person_scope is not None else None),
    )
    if not eligible:
        return _decision(
            label,
            context,
            ranking,
            certificate_valid,
            certificate_reason,
            "residual_human_queue",
            "every candidate received a hard veto",
        )
    if instance_context != "solo" and not certificate_valid:
        return _decision(
            label,
            context,
            ranking,
            certificate_valid,
            certificate_reason,
            "residual_human_queue",
            "multi-person candidate lacks an exact current certificate",
        )
    winner = eligible[0]
    runner_up = eligible[1].score if len(eligible) > 1 else None
    if winner.score < float(tournament["minimum_score"]):
        return _decision(
            label,
            context,
            ranking,
            certificate_valid,
            certificate_reason,
            "residual_human_queue",
            "best candidate is below the tournament score threshold",
        )
    if runner_up is not None and winner.score - runner_up < float(
        tournament["minimum_winner_margin"]
    ):
        return _decision(
            label,
            context,
            ranking,
            certificate_valid,
            certificate_reason,
            "residual_human_queue",
            "candidate winner margin is too small",
        )
    if (
        winner.evidence.critic_disagreement
        and config["operations"]["cloud_disagreement_forces_residual_queue"]
    ):
        return _decision(
            label,
            context,
            ranking,
            certificate_valid,
            certificate_reason,
            "residual_human_queue",
            "independent critics disagree",
        )
    status = (
        config["operations"]["calibrated_status"]
        if certificate_valid
        else config["operations"]["uncalibrated_status"]
    )
    truth_tier = (
        config["operations"]["calibrated_truth_tier"]
        if certificate_valid
        else config["operations"]["uncalibrated_truth_tier"]
    )
    return _decision(
        label,
        context,
        ranking,
        certificate_valid,
        certificate_reason,
        status,
        "winner passed all hard vetoes and tournament margins",
        truth_tier=truth_tier,
        training_loss_weight=float(config["truth_tiers"][truth_tier]["training_weight"]),
    )


def _score(
    candidate: CandidateEvidence,
    policy: dict[str, Any],
    image_vetoes: tuple[str, ...] = (),
) -> ScoredCandidate:
    for value in (
        candidate.consensus_iou,
        candidate.boundary_agreement,
        candidate.pose_consistency,
        candidate.critic_pass_weight,
        candidate.protected_overlap,
        candidate.exclusive_overlap,
    ):
        if not 0 <= value <= 1:
            raise AutonomyTournamentError("candidate metric is outside 0..1")
    hard = policy["hard_veto"]
    vetoes = list(image_vetoes)
    if hard["require_format_valid"] and not candidate.format_valid:
        vetoes.append("invalid_mask_format")
    if hard["reject_any_block_qc"] and candidate.block_qc_ids:
        vetoes.append("block_qc")
    if candidate.protected_overlap > float(hard["maximum_protected_overlap"]):
        vetoes.append("protected_overlap")
    if candidate.exclusive_overlap > float(hard["maximum_exclusive_overlap"]):
        vetoes.append("exclusive_overlap")
    if hard["reject_component_overflow"] and (
        candidate.component_count > candidate.ontology_max_components
    ):
        vetoes.append("component_overflow")
    if candidate.independent_sources < int(policy["minimum_independent_sources"]):
        vetoes.append("insufficient_independent_sources")
    diversity = min(1.0, candidate.independent_sources / 5)
    weights = policy["weights"]
    score = (
        candidate.consensus_iou * float(weights["consensus_iou"])
        + candidate.boundary_agreement * float(weights["boundary_agreement"])
        + candidate.pose_consistency * float(weights["pose_consistency"])
        + diversity * float(weights["source_diversity"])
        + candidate.critic_pass_weight * float(weights["critic_support"])
    )
    return ScoredCandidate(
        candidate.candidate_id, float(score), not vetoes, tuple(vetoes), candidate
    )


def _validate_source_provenance(candidate: CandidateEvidence) -> None:
    provider_keys = candidate.source_provider_keys
    families = candidate.source_model_families
    if not provider_keys and not families:
        return
    if not provider_keys or not families:
        raise AutonomyTournamentError(
            "candidate source provenance requires provider keys and model families"
        )
    if len(provider_keys) != len(set(provider_keys)):
        raise AutonomyTournamentError("candidate source provider keys must be unique")
    if len(families) != len(set(families)):
        raise AutonomyTournamentError("candidate source model families must be unique")
    if candidate.independent_sources != len(families):
        raise AutonomyTournamentError(
            "candidate independent-source count differs from provenance model families"
        )


def _decision(
    label: str,
    context: str,
    ranking: tuple[ScoredCandidate, ...],
    certificate_valid: bool,
    certificate_reason: str,
    status: str,
    reason: str,
    *,
    truth_tier: str = "machine_candidate",
    training_loss_weight: float = 0.0,
) -> TournamentDecision:
    eligible = [candidate for candidate in ranking if candidate.eligible]
    winner = eligible[0] if eligible else None
    runner = eligible[1] if len(eligible) > 1 else None
    return TournamentDecision(
        label,
        context,
        status,
        winner.candidate_id if winner else None,
        winner.score if winner else None,
        runner.score if runner else None,
        certificate_valid,
        certificate_reason,
        status != "calibrated_auto_accepted",
        truth_tier == "autonomous_certified_gold",
        reason,
        ranking,
        truth_tier,
        training_loss_weight,
    )


__all__ = [
    "AutonomyTournamentError",
    "CandidateEvidence",
    "ScoredCandidate",
    "TournamentDecision",
    "run_candidate_tournament",
]
