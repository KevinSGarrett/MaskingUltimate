"""Explicit truth provenance, training weights, and volume-gate accounting."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

HUMAN_ANCHOR_GOLD = "human_anchor_gold"
AUTONOMOUS_CERTIFIED_GOLD = "autonomous_certified_gold"
WEIGHTED_PSEUDO_LABEL = "weighted_pseudo_label"
MACHINE_CANDIDATE = "machine_candidate"
TRUTH_TIERS = (
    HUMAN_ANCHOR_GOLD,
    AUTONOMOUS_CERTIFIED_GOLD,
    WEIGHTED_PSEUDO_LABEL,
    MACHINE_CANDIDATE,
)

LEGACY_TRUTH_ALIASES = {
    "human_approved_gold": HUMAN_ANCHOR_GOLD,
    "calibrated_auto_accepted": AUTONOMOUS_CERTIFIED_GOLD,
    "machine_verified_candidate": MACHINE_CANDIDATE,
    "residual_human_queue": MACHINE_CANDIDATE,
}


@dataclass(frozen=True)
class TruthTierPolicy:
    tier: str
    training_weight: float
    training_eligible: bool
    holdout_eligible: bool
    dataset_volume_eligible: bool


@dataclass(frozen=True)
class TruthTierCounts:
    human_anchor_gold_count: int
    autonomous_certified_gold_count: int
    weighted_pseudo_label_count: int
    machine_candidate_count: int
    effective_training_truth_count: float

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)


class TruthTierError(ValueError):
    """Truth provenance or weighting is invalid."""


def validate_truth_tier_policy(document: Mapping[str, Any]) -> dict[str, TruthTierPolicy]:
    if set(document) != set(TRUTH_TIERS):
        raise TruthTierError(f"truth-tier policy must define exactly {list(TRUTH_TIERS)}")
    results: dict[str, TruthTierPolicy] = {}
    for tier in TRUTH_TIERS:
        entry = document[tier]
        if not isinstance(entry, Mapping):
            raise TruthTierError(f"truth-tier policy entry must be a mapping: {tier}")
        required = {
            "training_weight",
            "training_eligible",
            "holdout_eligible",
            "dataset_volume_eligible",
        }
        if set(entry) != required:
            raise TruthTierError(f"truth-tier policy has the wrong fields: {tier}")
        weight = float(entry["training_weight"])
        if not 0 <= weight <= 1:
            raise TruthTierError(f"truth-tier weight is outside 0..1: {tier}")
        if tier == HUMAN_ANCHOR_GOLD and weight != 1.0:
            raise TruthTierError("human_anchor_gold training weight must be 1.0")
        if tier == AUTONOMOUS_CERTIFIED_GOLD and not 0.5 <= weight <= 0.75:
            raise TruthTierError("autonomous_certified_gold weight must be 0.5..0.75")
        if tier == WEIGHTED_PSEUDO_LABEL and not 0.1 <= weight <= 0.25:
            raise TruthTierError("weighted_pseudo_label weight must be 0.1..0.25")
        if tier == MACHINE_CANDIDATE and weight != 0:
            raise TruthTierError("machine_candidate training weight must be zero")
        booleans = {
            name: entry[name]
            for name in required - {"training_weight"}
            if not isinstance(entry[name], bool)
        }
        if booleans:
            raise TruthTierError(f"truth-tier eligibility values must be booleans: {tier}")
        results[tier] = TruthTierPolicy(
            tier=tier,
            training_weight=weight,
            training_eligible=entry["training_eligible"],
            holdout_eligible=entry["holdout_eligible"],
            dataset_volume_eligible=entry["dataset_volume_eligible"],
        )
    if any(results[tier].holdout_eligible for tier in TRUTH_TIERS if tier != HUMAN_ANCHOR_GOLD):
        raise TruthTierError("only human_anchor_gold may enter validation/test holdouts")
    if results[MACHINE_CANDIDATE].training_eligible:
        raise TruthTierError("machine_candidate cannot be training eligible")
    return results


def normalize_truth_tier(value: str) -> str:
    normalized = LEGACY_TRUTH_ALIASES.get(value, value)
    if normalized not in TRUTH_TIERS:
        raise TruthTierError(f"unknown truth tier: {value}")
    return normalized


def truth_tier_from_record(record: Mapping[str, Any]) -> str:
    value = record.get("truth_tier")
    if isinstance(value, str):
        return normalize_truth_tier(value)
    for key in ("status", "workflow_status"):
        legacy = record.get(key)
        if isinstance(legacy, str) and legacy in LEGACY_TRUTH_ALIASES:
            return LEGACY_TRUTH_ALIASES[legacy]
    raise TruthTierError("record has no explicit or compatible truth tier")


def summarize_truth_tiers(
    records: Iterable[Mapping[str, Any]], policy: Mapping[str, TruthTierPolicy]
) -> TruthTierCounts:
    counts = {tier: 0 for tier in TRUTH_TIERS}
    effective = 0.0
    for record in records:
        tier = truth_tier_from_record(record)
        counts[tier] += 1
        tier_policy = policy[tier]
        if tier_policy.training_eligible:
            effective += tier_policy.training_weight
    return TruthTierCounts(
        human_anchor_gold_count=counts[HUMAN_ANCHOR_GOLD],
        autonomous_certified_gold_count=counts[AUTONOMOUS_CERTIFIED_GOLD],
        weighted_pseudo_label_count=counts[WEIGHTED_PSEUDO_LABEL],
        machine_candidate_count=counts[MACHINE_CANDIDATE],
        effective_training_truth_count=effective,
    )


__all__ = [
    "AUTONOMOUS_CERTIFIED_GOLD",
    "HUMAN_ANCHOR_GOLD",
    "LEGACY_TRUTH_ALIASES",
    "MACHINE_CANDIDATE",
    "TRUTH_TIERS",
    "TruthTierCounts",
    "TruthTierError",
    "TruthTierPolicy",
    "WEIGHTED_PSEUDO_LABEL",
    "normalize_truth_tier",
    "summarize_truth_tiers",
    "truth_tier_from_record",
    "validate_truth_tier_policy",
]
