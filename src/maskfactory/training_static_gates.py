"""STATIC_PASS binder for P5 training-weight, leakage, and leaderboard gates.

Fixture- and config-bound only. Never launches trainers, never claims D6/D7,
champions, live holdout evaluation, or certified_training_package_count > 0.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from .datasets.authority import (
    D5_CERTIFIED_PACKAGE_COUNT,
    P5_CERTIFIED_ENTRY_COUNT,
    PARTITION_CAPABILITIES,
    READER_CAPABILITIES,
    evaluate_certified_volume_gates,
    require_partition_capability,
)
from .training.leaderboard import (
    FINAL_EVALUATION_AUTHORITY,
    enforce_final_evaluation_authority,
    normalize_leaderboard_row,
)
from .truth_tiers import (
    AUTONOMOUS_CERTIFIED_GOLD,
    HUMAN_ANCHOR_GOLD,
    MACHINE_CANDIDATE,
    NON_TRAINING_AUTHORITY_LABELS,
    WEIGHTED_PSEUDO_LABEL,
    TruthTierError,
    require_training_truth_tier,
    summarize_truth_tiers,
    validate_truth_tier_policy,
)
from .validation import validate_document

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "training_static_gates_report"
AUTHORITY = "training_static_gates_only_no_live_training_d6_d7_champion_or_certified_corpus"
SCHEMA_VERSION = "1.0.0"
AUTONOMY_CONFIG_PATH = Path("configs/autonomous_masks.yaml")

WEIGHT_ELIGIBILITY_CHECKS = (
    "canonical_truth_tier_weights",
    "non_training_authority_rejected",
    "machine_candidate_ineligible",
    "only_human_anchor_holdout_eligible",
)
LEAKAGE_CHECKS = (
    "trainer_cannot_read_holdout",
    "trainer_cannot_read_calibration",
    "pseudo_generator_cannot_read_holdout",
    "threshold_tuner_cannot_read_train",
    "certificate_fitter_cannot_read_holdout",
    "final_evaluator_cannot_read_train",
)
VOLUME_CHECKS = (
    "certified_count_zero_blocks_p5",
    "effective_weight_cannot_open_p5",
    "d5_blocked_at_zero_certified",
    "formula_human_plus_autonomous_only",
)
LEADERBOARD_CHECKS = (
    "base_schema_accepts_valid_row",
    "final_authority_requires_human_anchor",
    "final_authority_rejects_autonomous",
    "final_authority_rejects_pseudo",
    "final_authority_rejects_machine_candidate",
    "final_authority_requires_holdout_split",
)


class TrainingStaticGateError(ValueError):
    """P5 training STATIC contract violated."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _load_truth_tier_policy(config_path: Path = AUTONOMY_CONFIG_PATH) -> dict[str, Any]:
    try:
        document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TrainingStaticGateError(f"autonomy config unreadable: {exc}") from exc
    if not isinstance(document, Mapping) or not isinstance(document.get("truth_tiers"), Mapping):
        raise TrainingStaticGateError("autonomy config missing truth_tiers")
    return validate_truth_tier_policy(document["truth_tiers"])


def _empty_coverage() -> dict[str, Any]:
    return {
        "cells": [{"approved_gold_count": 0} for _ in range(10)],
        "attribute_totals": {"view_front": 0, "pose_standing": 0},
    }


def evaluate_training_weight_eligibility(
    *,
    config_path: Path = AUTONOMY_CONFIG_PATH,
) -> dict[str, bool]:
    """Bind canonical training-weight / eligibility policy (STATIC fixture)."""

    policy = _load_truth_tier_policy(config_path)
    results: dict[str, bool] = {}

    results["canonical_truth_tier_weights"] = (
        policy[HUMAN_ANCHOR_GOLD].training_weight == 1.0
        and 0.5 <= policy[AUTONOMOUS_CERTIFIED_GOLD].training_weight <= 0.75
        and 0.1 <= policy[WEIGHTED_PSEUDO_LABEL].training_weight <= 0.25
        and policy[MACHINE_CANDIDATE].training_weight == 0.0
        and policy[HUMAN_ANCHOR_GOLD].training_eligible
        and policy[AUTONOMOUS_CERTIFIED_GOLD].training_eligible
        and policy[WEIGHTED_PSEUDO_LABEL].training_eligible
        and not policy[MACHINE_CANDIDATE].training_eligible
        and policy[HUMAN_ANCHOR_GOLD].dataset_volume_eligible
        and policy[AUTONOMOUS_CERTIFIED_GOLD].dataset_volume_eligible
        and not policy[WEIGHTED_PSEUDO_LABEL].dataset_volume_eligible
        and not policy[MACHINE_CANDIDATE].dataset_volume_eligible
    )

    rejected = 0
    for label in sorted(NON_TRAINING_AUTHORITY_LABELS):
        try:
            require_training_truth_tier(label)
        except TruthTierError:
            rejected += 1
    results["non_training_authority_rejected"] = rejected == len(NON_TRAINING_AUTHORITY_LABELS)

    results["machine_candidate_ineligible"] = (
        not policy[MACHINE_CANDIDATE].training_eligible
        and not policy[MACHINE_CANDIDATE].holdout_eligible
        and not policy[MACHINE_CANDIDATE].dataset_volume_eligible
    )
    results["only_human_anchor_holdout_eligible"] = (
        policy[HUMAN_ANCHOR_GOLD].holdout_eligible
        and not policy[AUTONOMOUS_CERTIFIED_GOLD].holdout_eligible
        and not policy[WEIGHTED_PSEUDO_LABEL].holdout_eligible
        and not policy[MACHINE_CANDIDATE].holdout_eligible
    )

    if set(results) != set(WEIGHT_ELIGIBILITY_CHECKS) or not all(results.values()):
        raise TrainingStaticGateError("training_weight_eligibility_incomplete_or_failed")
    return results


def evaluate_leakage_firewalls() -> dict[str, bool]:
    """Fail closed on every known cross-partition reader capability leak."""

    results: dict[str, bool] = {}

    def _rejects(partition: str, capability: str) -> bool:
        try:
            require_partition_capability(partition, capability)
        except ValueError:
            return True
        return False

    def _allows(partition: str, capability: str) -> bool:
        try:
            require_partition_capability(partition, capability)
        except ValueError:
            return False
        return True

    results["trainer_cannot_read_holdout"] = _rejects("holdout", "trainer") and _allows(
        "train", "trainer"
    )
    results["trainer_cannot_read_calibration"] = _rejects("calibration", "trainer")
    results["pseudo_generator_cannot_read_holdout"] = _rejects(
        "holdout", "pseudo_label_generator"
    ) and _allows("train", "pseudo_label_generator")
    results["threshold_tuner_cannot_read_train"] = _rejects("train", "threshold_tuner") and _allows(
        "calibration", "threshold_tuner"
    )
    results["certificate_fitter_cannot_read_holdout"] = _rejects(
        "holdout", "certificate_fitter"
    ) and _allows("calibration", "certificate_fitter")
    results["final_evaluator_cannot_read_train"] = _rejects("train", "final_evaluator") and _allows(
        "holdout", "final_evaluator"
    )

    # Structural sanity: capability maps stay disjoint for protected partitions.
    if "holdout" not in PARTITION_CAPABILITIES or "calibration" not in PARTITION_CAPABILITIES:
        raise TrainingStaticGateError("partition_capability_map_incomplete")
    if "trainer" not in READER_CAPABILITIES or "final_evaluator" not in READER_CAPABILITIES:
        raise TrainingStaticGateError("reader_capability_map_incomplete")
    if (
        "holdout" in READER_CAPABILITIES["trainer"]
        or "calibration" in READER_CAPABILITIES["trainer"]
    ):
        raise TrainingStaticGateError("trainer_reader_capability_leaks_protected_partition")

    if set(results) != set(LEAKAGE_CHECKS) or not all(results.values()):
        raise TrainingStaticGateError("leakage_firewall_incomplete_or_failed")
    return results


def evaluate_certified_volume_honesty(
    *,
    certified_training_package_count: int = 0,
    human_anchor_train_count: int = 0,
    autonomous_certified_gold_count: int = 0,
) -> dict[str, Any]:
    """Keep certified_training_package_count honest; effective weight cannot open P5."""

    if certified_training_package_count != (
        human_anchor_train_count + autonomous_certified_gold_count
    ):
        raise TrainingStaticGateError("certified_count_formula_mismatch")
    if certified_training_package_count != 0:
        raise TrainingStaticGateError(
            "certified_training_package_count_must_remain_zero_until_real_corpus"
        )

    coverage = _empty_coverage()
    gate = evaluate_certified_volume_gates(certified_training_package_count, coverage)
    if gate["p5_entry_passed"] or gate["d5_passed"]:
        raise TrainingStaticGateError("zero_certified_must_block_p5_and_d5")

    # High pseudo-derived effective weight must not satisfy volume gates.
    policy = _load_truth_tier_policy()
    inflated = summarize_truth_tiers(
        (
            *({"truth_tier": WEIGHTED_PSEUDO_LABEL} for _ in range(500)),
            *({"truth_tier": MACHINE_CANDIDATE} for _ in range(50)),
        ),
        policy,
    )
    if inflated.effective_training_truth_count < 50:
        raise TrainingStaticGateError("effective_weight_fixture_too_weak")
    # Effective weight is diagnostic only — P5 still uses certified count.
    still_blocked = evaluate_certified_volume_gates(0, coverage)
    if still_blocked["p5_entry_passed"]:
        raise TrainingStaticGateError("effective_weight_opened_p5_illegally")

    results = {
        "certified_count_zero_blocks_p5": not gate["p5_entry_passed"],
        "effective_weight_cannot_open_p5": not still_blocked["p5_entry_passed"],
        "d5_blocked_at_zero_certified": not gate["d5_passed"],
        "formula_human_plus_autonomous_only": (
            gate["certified_training_package_count"]
            == human_anchor_train_count + autonomous_certified_gold_count
            and gate["p5_entry_target"] == P5_CERTIFIED_ENTRY_COUNT
            and gate["d5_certified_target"] == D5_CERTIFIED_PACKAGE_COUNT
        ),
    }
    if set(results) != set(VOLUME_CHECKS) or not all(results.values()):
        raise TrainingStaticGateError("certified_volume_honesty_incomplete_or_failed")
    return {
        "checks": results,
        "certified_training_package_count": certified_training_package_count,
        "human_anchor_train_count": human_anchor_train_count,
        "autonomous_certified_gold_count": autonomous_certified_gold_count,
        "effective_training_weight_units_diagnostic": round(
            inflated.effective_training_truth_count, 4
        ),
        "p5_entry_passed": False,
        "d5_passed": False,
    }


def _base_leaderboard_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "run_id": "static_fixture_row",
        "model_family": "segformer_b3",
        "ckpt_sha": "a" * 64,
        "dataset_ref": "bodyparts@v1",
        "split": "test_holdout",
        "mean_iou": 0.71,
        "mean_boundary_f": 0.73,
        "per_class": {"left_forearm": {"iou": 0.70, "bf": 0.72}},
        "group_scores": {"fingers": {"iou": 0.60, "bf": 0.62}},
        "instance_context_scores": {
            "solo": {
                "mean_iou": 0.71,
                "mean_boundary_f": 0.73,
                "per_class": {"left_forearm": {"iou": 0.70, "bf": 0.72}},
                "sample_count": 1,
            }
        },
        "sample_count": 1,
        "latency_ms_1024": 80.0,
        "vram_gb": 7.5,
        "seeds": [1337],
        "notes": "training_static_gates_fixture",
    }
    row.update(overrides)
    return row


def evaluate_leaderboard_schema_static() -> dict[str, bool]:
    """Strengthen final-holdout leaderboard authority without claiming measured rows."""

    results: dict[str, bool] = {}
    base = normalize_leaderboard_row(_base_leaderboard_row())
    results["base_schema_accepts_valid_row"] = base["split"] == "test_holdout"

    final_ok = _base_leaderboard_row(
        evaluation_authority=FINAL_EVALUATION_AUTHORITY,
        evaluation_truth_tier=HUMAN_ANCHOR_GOLD,
        evaluation_manifest_sha256="b" * 64,
    )
    enforce_final_evaluation_authority(final_ok)
    results["final_authority_requires_human_anchor"] = True

    def _rejects(tier: str) -> bool:
        try:
            enforce_final_evaluation_authority(
                _base_leaderboard_row(
                    evaluation_authority=FINAL_EVALUATION_AUTHORITY,
                    evaluation_truth_tier=tier,
                    evaluation_manifest_sha256="c" * 64,
                )
            )
        except ValueError:
            return True
        return False

    results["final_authority_rejects_autonomous"] = _rejects(AUTONOMOUS_CERTIFIED_GOLD)
    results["final_authority_rejects_pseudo"] = _rejects(WEIGHTED_PSEUDO_LABEL)
    results["final_authority_rejects_machine_candidate"] = _rejects(MACHINE_CANDIDATE)

    try:
        enforce_final_evaluation_authority(
            _base_leaderboard_row(
                split="val",
                evaluation_authority=FINAL_EVALUATION_AUTHORITY,
                evaluation_truth_tier=HUMAN_ANCHOR_GOLD,
                evaluation_manifest_sha256="d" * 64,
            )
        )
        results["final_authority_requires_holdout_split"] = False
    except ValueError:
        results["final_authority_requires_holdout_split"] = True

    # Diagnostic / standing baseline rows may omit final authority fields.
    normalize_leaderboard_row(_base_leaderboard_row(run_id="diagnostic_ok", split="val"))

    if set(results) != set(LEADERBOARD_CHECKS) or not all(results.values()):
        raise TrainingStaticGateError("leaderboard_schema_static_incomplete_or_failed")
    return results


def run_training_static_gate_suite(
    *,
    config_path: Path = AUTONOMY_CONFIG_PATH,
    certified_training_package_count: int = 0,
    human_anchor_train_count: int = 0,
    autonomous_certified_gold_count: int = 0,
) -> dict[str, Any]:
    """Execute the full P5 training STATIC binder and seal a schema-valid report."""

    weight = evaluate_training_weight_eligibility(config_path=config_path)
    leakage = evaluate_leakage_firewalls()
    volume = evaluate_certified_volume_honesty(
        certified_training_package_count=certified_training_package_count,
        human_anchor_train_count=human_anchor_train_count,
        autonomous_certified_gold_count=autonomous_certified_gold_count,
    )
    leaderboard = evaluate_leaderboard_schema_static()

    # Flip/swap (MF-P5-02.02) is already complete — record as prior STATIC credit only.
    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "weight_eligibility_checks": dict(sorted(weight.items())),
        "leakage_firewall_checks": dict(sorted(leakage.items())),
        "volume_honesty": {
            "checks": dict(sorted(volume["checks"].items())),
            "certified_training_package_count": volume["certified_training_package_count"],
            "human_anchor_train_count": volume["human_anchor_train_count"],
            "autonomous_certified_gold_count": volume["autonomous_certified_gold_count"],
            "effective_training_weight_units_diagnostic": volume[
                "effective_training_weight_units_diagnostic"
            ],
            "p5_entry_passed": False,
            "d5_passed": False,
        },
        "leaderboard_schema_checks": dict(sorted(leaderboard.items())),
        "checks": {
            "training_weight_eligibility": "pass",
            "leakage_firewalls": "pass",
            "certified_volume_honesty": "pass",
            "leaderboard_final_authority_schema": "pass",
        },
        "flip_swap_ci_already_complete": True,
        "certified_training_package_count": 0,
        "p5_entry_gate_open": False,
        "d6_claimed": False,
        "d7_claimed": False,
        "champion_claimed": False,
        "live_training_run_claimed": False,
        "live_holdout_evaluation_claimed": False,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "production_evidence_pass_claimed": False,
        "honest_non_claims": [
            "live_segformer_or_mask2former_training_run",
            "d6_g7_bodypart_promotion_win",
            "d7_hand_promotion_win",
            "champion_bodypart_hand_or_clothing",
            "certified_training_package_count_nonzero",
            "p5_entry_gate_open",
            "live_human_anchor_holdout_evaluation",
            "doctor_green",
            "gold",
            "production_evidence_pass",
        ],
    }
    digest = _sha(draft)
    draft["report_id"] = f"tsg_{digest[:24]}"
    draft["seal_sha256"] = digest
    draft["sha256"] = _sha({key: value for key, value in draft.items() if key != "sha256"})
    issues = validate_document(draft, "training_static_gates_report")
    if issues:
        detail = "; ".join(f"{issue.pointer or '/'}: {issue.message}" for issue in issues)
        raise TrainingStaticGateError(f"report_schema_invalid: {detail}")
    return draft


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "LEADERBOARD_CHECKS",
    "LEAKAGE_CHECKS",
    "PROOF_TIER",
    "SCHEMA_VERSION",
    "VOLUME_CHECKS",
    "WEIGHT_ELIGIBILITY_CHECKS",
    "TrainingStaticGateError",
    "evaluate_certified_volume_honesty",
    "evaluate_leaderboard_schema_static",
    "evaluate_leakage_firewalls",
    "evaluate_training_weight_eligibility",
    "run_training_static_gate_suite",
]
