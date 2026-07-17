"""Validation-outcome feedback for future DAZ candidate qualification."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

import yaml

from ...validation import require_valid_document
from ..validation_registry import (
    build_validation_set_report,
    validate_validation_registry,
)
from .candidates import validate_candidate_batch
from .concentration import derive_candidate_history_record, validate_concentration_policy
from .selection import validate_candidate_qualification_snapshot
from .vocabulary import validate_coverage_vocabulary_report

SHA256 = re.compile(r"^[0-9a-f]{64}$")
TOKEN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
ELIGIBLE_REASONS = [
    "ASSET_HASH_MISMATCH",
    "ASSET_DEPENDENCY_MISSING",
    "ASSET_CERTIFICATE_INVALID",
    "ID_UNKNOWN_VALUE",
    "SEMANTIC_MAPPING_INVALID",
]


class PlannerFeedbackError(ValueError):
    """Feedback policy, outcomes, report, or publication is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_planner_feedback_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_planner_feedback_policy(document)
    return document


def validate_planner_feedback_policy(policy: Mapping[str, Any]) -> None:
    if not isinstance(policy, Mapping) or set(policy) != {
        "schema_version",
        "feedback_version",
        "minimum_observations_for_adaptation",
        "smoothing",
        "predicted_rejection_cost",
        "visibility",
        "failure_mining",
        "restrictions",
        "history",
        "authority",
        "publication",
    }:
        raise PlannerFeedbackError("planner_feedback_policy_fields_invalid", str(policy))
    expected = {
        "schema_version": "1.0.0",
        "feedback_version": "1.0.0",
        "minimum_observations_for_adaptation": 2,
        "smoothing": {"prior_attempts": 2, "prior_failures": 1},
        "predicted_rejection_cost": {
            "failure_rate_weight": 0.75,
            "normalized_gpu_cost_weight": 0.25,
            "gpu_seconds_normalizer": 600.0,
            "maximum": 1.0,
        },
        "visibility": {
            "useful_actual_cannot_exceed_predicted": True,
            "empirical_ratio_replaces_base_after_minimum": True,
        },
        "failure_mining": {
            "demand_failure_rate_raises_priority": True,
            "never_lowers_base_priority": True,
        },
        "restrictions": {
            "minimum_independent_failed_reports": 3,
            "minimum_failure_rate": 0.75,
            "eligible_reason_codes": ELIGIBLE_REASONS,
            "only_explicit_affected_asset_ids": True,
            "effect": "compatibility_eligible_false",
        },
        "history": {
            "historical_recipes_immutable": True,
            "historical_outcomes_immutable": True,
            "accepted_counts_require_certificate_reference": True,
        },
        "authority": {
            "stage": "technical_planner_feedback",
            "feedback_creates_recipe": False,
            "feedback_creates_render_authority": False,
            "feedback_creates_gold": False,
            "synthetic_counts_close_real_deficits": False,
        },
        "publication": {"immutable": True, "atomic": True},
    }
    if dict(policy) != expected:
        raise PlannerFeedbackError("planner_feedback_policy_invalid", str(policy))


def build_planner_feedback_report(
    *,
    candidate_batch: Mapping[str, Any],
    vocabulary_report: Mapping[str, Any],
    base_qualification_snapshot: Mapping[str, Any],
    outcome_snapshot: Mapping[str, Any],
    validation_registry: Mapping[str, Any],
    concentration_policy: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    inputs = _validate_inputs(
        candidate_batch,
        vocabulary_report,
        base_qualification_snapshot,
        outcome_snapshot,
        validation_registry,
        concentration_policy,
        policy,
    )
    content = _compute_content(
        candidate_batch,
        base_qualification_snapshot,
        outcome_snapshot,
        inputs,
        concentration_policy,
        policy,
    )
    digest = _sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"dpfr_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    require_valid_document(report, "daz_planner_feedback_report")
    return report


def validate_planner_feedback_report(
    report: Mapping[str, Any],
    *,
    candidate_batch: Mapping[str, Any],
    vocabulary_report: Mapping[str, Any],
    base_qualification_snapshot: Mapping[str, Any],
    outcome_snapshot: Mapping[str, Any],
    validation_registry: Mapping[str, Any],
    concentration_policy: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    require_valid_document(report, "daz_planner_feedback_report")
    expected = build_planner_feedback_report(
        candidate_batch=candidate_batch,
        vocabulary_report=vocabulary_report,
        base_qualification_snapshot=base_qualification_snapshot,
        outcome_snapshot=outcome_snapshot,
        validation_registry=validation_registry,
        concentration_policy=concentration_policy,
        policy=policy,
    )
    if report != expected:
        raise PlannerFeedbackError(
            "planner_feedback_report_semantics_invalid", str(report.get("report_id"))
        )


def publish_planner_feedback_report(
    report: Mapping[str, Any],
    output_root: Path,
    **validation_inputs: Any,
) -> tuple[Path, bool]:
    validate_planner_feedback_report(report, **validation_inputs)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{report['report_id']}.json"
    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise PlannerFeedbackError("planner_feedback_publication_conflict", str(target))
        return target, False
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=root)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target, True


def publish_adapted_qualification_snapshot(
    report: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    """Publish the embedded qualification snapshot as a direct D9-04 input."""

    require_valid_document(report, "daz_planner_feedback_report")
    snapshot = report["adapted_qualification_snapshot"]
    expected_sha = _sha({key: snapshot[key] for key in ("snapshot_id", "source", "rows")})
    if snapshot["snapshot_sha256"] != expected_sha:
        raise PlannerFeedbackError(
            "planner_feedback_adapted_snapshot_hash_invalid", snapshot["snapshot_id"]
        )
    root = Path(output_root) / "adapted_qualifications"
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{snapshot['snapshot_id']}.json"
    payload = json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise PlannerFeedbackError(
                "planner_feedback_qualification_publication_conflict", str(target)
            )
        return target, False
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=root)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target, True


def _validate_inputs(
    batch: Mapping[str, Any],
    vocabulary: Mapping[str, Any],
    base: Mapping[str, Any],
    outcomes: Mapping[str, Any],
    registry: Mapping[str, Any],
    concentration_policy: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    validate_planner_feedback_policy(policy)
    validate_coverage_vocabulary_report(vocabulary)
    validate_candidate_batch(batch, vocabulary_report=vocabulary)
    validate_candidate_qualification_snapshot(base, batch)
    validate_validation_registry(registry)
    validate_concentration_policy(concentration_policy)
    if not isinstance(outcomes, Mapping) or set(outcomes) != {
        "snapshot_id",
        "snapshot_sha256",
        "source",
        "targets",
        "observations",
    }:
        raise PlannerFeedbackError("planner_outcome_snapshot_fields_invalid", str(outcomes))
    if (
        not TOKEN.fullmatch(str(outcomes.get("snapshot_id")))
        or outcomes.get("source") != "versioned_d7_validation_outcomes"
        or not SHA256.fullmatch(str(outcomes.get("snapshot_sha256")))
        or outcomes["snapshot_sha256"]
        != _sha(
            {key: outcomes[key] for key in ("snapshot_id", "source", "targets", "observations")}
        )
    ):
        raise PlannerFeedbackError(
            "planner_outcome_snapshot_hash_invalid", str(outcomes.get("snapshot_id"))
        )
    targets = _validate_targets(outcomes["targets"])
    observations = []
    seen = set()
    for raw in outcomes["observations"]:
        observation = _validate_observation(raw, registry, targets)
        if observation["observation_id"] in seen:
            raise PlannerFeedbackError("planner_outcome_duplicate", observation["observation_id"])
        seen.add(observation["observation_id"])
        observations.append(observation)
    return {"targets": targets, "observations": observations}


def _validate_targets(raw_targets: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(raw_targets, list):
        raise PlannerFeedbackError("planner_outcome_targets_invalid", str(raw_targets))
    targets = {}
    for target in raw_targets:
        if (
            not isinstance(target, Mapping)
            or set(target) != {"target_cell_id", "required_accepted", "current_accepted"}
            or not TOKEN.fullmatch(str(target.get("target_cell_id")))
            or not isinstance(target.get("required_accepted"), int)
            or isinstance(target.get("required_accepted"), bool)
            or target["required_accepted"] < 1
            or not isinstance(target.get("current_accepted"), int)
            or isinstance(target.get("current_accepted"), bool)
            or not 0 <= target["current_accepted"] <= target["required_accepted"]
            or target["target_cell_id"] in targets
        ):
            raise PlannerFeedbackError("planner_outcome_target_invalid", str(target))
        targets[target["target_cell_id"]] = target
    return targets


def _validate_observation(
    raw: Any, registry: Mapping[str, Any], targets: Mapping[str, Any]
) -> dict[str, Any]:
    required = {
        "observation_id",
        "demand_id",
        "scene_family_id",
        "asset_ids",
        "target_cell_ids",
        "camera_region",
        "predicted_visible_labels",
        "useful_visible_labels",
        "gpu_seconds",
        "storage_gib",
        "acceptance_certificate",
        "validation_report",
    }
    if not isinstance(raw, Mapping) or set(raw) != required:
        raise PlannerFeedbackError("planner_outcome_observation_fields_invalid", str(raw))
    content = {key: raw[key] for key in sorted(required - {"observation_id"})}
    expected_id = f"dobs_{_sha(content)[:24]}"
    report = raw["validation_report"]
    if raw["observation_id"] != expected_id:
        raise PlannerFeedbackError(
            "planner_outcome_observation_hash_invalid", str(raw.get("observation_id"))
        )
    try:
        expected_report = build_validation_set_report(
            report["results"],
            entity_id=report["entity_id"],
            scope=report["scope"],
            registry=registry,
            required_validator_ids=report["required_validator_ids"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PlannerFeedbackError("planner_outcome_validation_invalid", str(exc)) from exc
    if report != expected_report or report["scope"] != "scene":
        raise PlannerFeedbackError(
            "planner_outcome_validation_invalid", str(report.get("report_id"))
        )
    certificate = raw["acceptance_certificate"]
    if certificate is not None and (
        not isinstance(certificate, Mapping)
        or set(certificate) != {"certificate_id", "certificate_sha256"}
        or not re.fullmatch(r"dacc_[0-9a-f]{24}", str(certificate.get("certificate_id")))
        or not SHA256.fullmatch(str(certificate.get("certificate_sha256")))
        or not report["summary"]["passed"]
    ):
        raise PlannerFeedbackError("planner_outcome_acceptance_reference_invalid", str(certificate))
    if (
        not re.fullmatch(r"drd_[0-9a-f]{24}", str(raw["demand_id"]))
        or not re.fullmatch(r"dfam_[0-9a-f]{24}", str(raw["scene_family_id"]))
        or not _unique_text(raw["asset_ids"])
        or not _unique_text(raw["target_cell_ids"])
        or any(value not in targets for value in raw["target_cell_ids"])
        or not TOKEN.fullmatch(str(raw["camera_region"]))
        or not _nonnegative_int(raw["predicted_visible_labels"])
        or not _nonnegative_int(raw["useful_visible_labels"])
        or raw["useful_visible_labels"] > raw["predicted_visible_labels"]
        or not _finite_nonnegative(raw["gpu_seconds"])
        or not _finite_nonnegative(raw["storage_gib"])
    ):
        raise PlannerFeedbackError(
            "planner_outcome_observation_invalid", str(raw.get("observation_id"))
        )
    return dict(raw)


def _compute_content(
    batch: Mapping[str, Any],
    base: Mapping[str, Any],
    outcome_snapshot: Mapping[str, Any],
    inputs: Mapping[str, Any],
    concentration_policy: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    observations = inputs["observations"]
    demand_stats = _aggregate(observations, lambda row: row["demand_id"])
    family_stats = _aggregate(observations, lambda row: row["scene_family_id"])
    asset_stats = _aggregate_many(observations, "asset_ids")
    camera_outcomes = [
        row
        for row in observations
        if any(
            result["status"] == "fail"
            and result["reason_code"].startswith(("ASSEMBLY_", "GEOMETRY_", "RENDER_"))
            for result in row["validation_report"]["results"]
        )
    ]
    camera_stats = _aggregate(camera_outcomes, lambda row: row["camera_region"])
    predicted_visibility = sum(row["predicted_visible_labels"] for row in observations)
    useful_visibility = sum(row["useful_visible_labels"] for row in observations)
    target_rows = []
    for target_id, target in inputs["targets"].items():
        accepted = sum(
            row["acceptance_certificate"] is not None and target_id in row["target_cell_ids"]
            for row in observations
        )
        projected = min(target["required_accepted"], target["current_accepted"] + accepted)
        target_rows.append(
            {
                **dict(target),
                "new_accepted": accepted,
                "projected_accepted": projected,
                "remaining": target["required_accepted"] - projected,
                "underfilled": projected < target["required_accepted"],
            }
        )
    restrictions = _restrictions(observations, asset_stats, policy)
    restricted_ids = {row["asset_id"] for row in restrictions}
    base_rows = {row["candidate_id"]: row for row in base["rows"]}
    adapted_rows = []
    adaptation_rows = []
    for candidate in batch["candidates"]:
        identity = derive_candidate_history_record(candidate, concentration_policy)
        asset_ids = set(identity["contributions"].values())
        family_matches = [
            row for row in observations if row["scene_family_id"] == identity["scene_family_id"]
        ]
        asset_matches = [row for row in observations if asset_ids & set(row["asset_ids"])]
        matched = (
            family_matches
            if len(family_matches) >= policy["minimum_observations_for_adaptation"]
            else asset_matches
        )
        evidence_scope = (
            "scene_family"
            if matched is family_matches and matched
            else "asset" if matched else "none"
        )
        original = base_rows[candidate["candidate_id"]]
        features = dict(original["features"])
        penalties = dict(original["penalties"])
        gates = dict(original["hard_constraints"])
        predicted_cost = penalties["predicted_rejection_cost"]
        visibility = features["label_visibility_gain"]
        if len(matched) >= policy["minimum_observations_for_adaptation"]:
            failures = sum(not row["validation_report"]["summary"]["passed"] for row in matched)
            smoothed = (failures + policy["smoothing"]["prior_failures"]) / (
                len(matched) + policy["smoothing"]["prior_attempts"]
            )
            mean_gpu = sum(row["gpu_seconds"] for row in matched) / len(matched)
            normalized_gpu = min(
                1.0, mean_gpu / policy["predicted_rejection_cost"]["gpu_seconds_normalizer"]
            )
            predicted_cost = max(
                predicted_cost,
                _round(
                    policy["predicted_rejection_cost"]["failure_rate_weight"] * smoothed
                    + policy["predicted_rejection_cost"]["normalized_gpu_cost_weight"]
                    * normalized_gpu
                ),
            )
            predicted = sum(row["predicted_visible_labels"] for row in matched)
            useful = sum(row["useful_visible_labels"] for row in matched)
            visibility = _round(useful / predicted) if predicted else 0.0
        demand = demand_stats.get(batch["demand"]["demand_id"])
        if demand is not None:
            features["failure_mining_priority"] = max(
                features["failure_mining_priority"], demand["failure_rate"]
            )
        penalties["predicted_rejection_cost"] = min(
            policy["predicted_rejection_cost"]["maximum"], predicted_cost
        )
        features["label_visibility_gain"] = visibility
        applied_restrictions = sorted(asset_ids & restricted_ids)
        if applied_restrictions:
            gates["compatibility_eligible"] = False
        adapted_rows.append(
            {
                "candidate_id": candidate["candidate_id"],
                "features": features,
                "penalties": penalties,
                "hard_constraints": gates,
            }
        )
        adaptation_rows.append(
            {
                "candidate_id": candidate["candidate_id"],
                "scene_family_id": identity["scene_family_id"],
                "evidence_scope": evidence_scope,
                "matched_observation_count": len(matched),
                "predicted_rejection_cost_before": original["penalties"][
                    "predicted_rejection_cost"
                ],
                "predicted_rejection_cost_after": penalties["predicted_rejection_cost"],
                "label_visibility_gain_before": original["features"]["label_visibility_gain"],
                "label_visibility_gain_after": features["label_visibility_gain"],
                "failure_mining_priority_before": original["features"]["failure_mining_priority"],
                "failure_mining_priority_after": features["failure_mining_priority"],
                "applied_restriction_asset_ids": applied_restrictions,
            }
        )
    adapted_content = {
        "snapshot_id": f"adaptive_{_sha({'base': base['snapshot_sha256'], 'outcomes': outcome_snapshot['snapshot_sha256'], 'batch': batch['batch_sha256'], 'policy': _sha(policy)})[:24]}",
        "source": "versioned_d3_d5_d7_adaptive_observations",
        "rows": adapted_rows,
    }
    adapted = {**adapted_content, "snapshot_sha256": _sha(adapted_content)}
    return {
        "feedback_version": policy["feedback_version"],
        "policy_sha256": _sha(policy),
        "candidate_batch": {
            "batch_id": batch["batch_id"],
            "batch_sha256": batch["batch_sha256"],
            "demand_id": batch["demand"]["demand_id"],
        },
        "base_qualification_snapshot": {
            key: base[key] for key in ("snapshot_id", "snapshot_sha256", "source")
        },
        "outcome_snapshot": {
            "snapshot_id": outcome_snapshot["snapshot_id"],
            "snapshot_sha256": outcome_snapshot["snapshot_sha256"],
            "observation_count": len(observations),
        },
        "demand_statistics": list(demand_stats.values()),
        "scene_family_statistics": list(family_stats.values()),
        "asset_statistics": list(asset_stats.values()),
        "camera_failure_regions": list(camera_stats.values()),
        "visibility_statistics": {
            "predicted_visible_label_count": predicted_visibility,
            "useful_visible_label_count": useful_visibility,
            "achievement_ratio": (
                _round(useful_visibility / predicted_visibility) if predicted_visibility else None
            ),
        },
        "target_cells": target_rows,
        "learned_restrictions": restrictions,
        "candidate_adaptations": adaptation_rows,
        "adapted_qualification_snapshot": adapted,
        "summary": {
            "observation_count": len(observations),
            "validation_failure_count": sum(
                not row["validation_report"]["summary"]["passed"] for row in observations
            ),
            "accepted_certificate_reference_count": sum(
                row["acceptance_certificate"] is not None for row in observations
            ),
            "underfilled_target_cell_count": sum(row["underfilled"] for row in target_rows),
            "learned_restriction_count": len(restrictions),
            "adapted_candidate_count": sum(
                row["matched_observation_count"] >= policy["minimum_observations_for_adaptation"]
                or bool(row["applied_restriction_asset_ids"])
                for row in adaptation_rows
            ),
        },
        "history_guarantees": dict(policy["history"]),
        "authority": dict(policy["authority"]),
        "publication": dict(policy["publication"]),
    }


def _aggregate(observations: list[Mapping[str, Any]], key_fn: Any) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in observations:
        groups[key_fn(row)].append(row)
    return {key: _statistics("group_id", key, rows) for key, rows in sorted(groups.items())}


def _aggregate_many(observations: list[Mapping[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in observations:
        for key in row[field]:
            groups[key].append(row)
    return {key: _statistics("asset_id", key, rows) for key, rows in sorted(groups.items())}


def _statistics(id_field: str, identifier: str, rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    failures = [row for row in rows if not row["validation_report"]["summary"]["passed"]]
    accepted = sum(row["acceptance_certificate"] is not None for row in rows)
    reasons = Counter(
        result["reason_code"]
        for row in failures
        for result in row["validation_report"]["results"]
        if result["status"] == "fail"
    )
    total_gpu = sum(row["gpu_seconds"] for row in rows)
    return {
        id_field: identifier,
        "attempt_count": len(rows),
        "validation_failure_count": len(failures),
        "failure_rate": _round(len(failures) / len(rows)),
        "accepted_count": accepted,
        "acceptance_yield": _round(accepted / len(rows)),
        "total_gpu_seconds": _round(total_gpu),
        "cost_per_accept_gpu_seconds": _round(total_gpu / accepted) if accepted else None,
        "failure_reason_counts": dict(sorted(reasons.items())),
    }


def _restrictions(
    observations: list[Mapping[str, Any]],
    asset_stats: Mapping[str, Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    failed_reports: dict[str, set[str]] = defaultdict(set)
    reasons: dict[str, Counter[str]] = defaultdict(Counter)
    for row in observations:
        for result in row["validation_report"]["results"]:
            if result["status"] != "fail" or result["reason_code"] not in ELIGIBLE_REASONS:
                continue
            for asset_id in result["affected_asset_ids"]:
                failed_reports[asset_id].add(row["validation_report"]["report_id"])
                reasons[asset_id][result["reason_code"]] += 1
    rows = []
    for asset_id, report_ids in sorted(failed_reports.items()):
        statistics = asset_stats.get(asset_id)
        if (
            statistics is not None
            and len(report_ids) >= policy["restrictions"]["minimum_independent_failed_reports"]
            and statistics["failure_rate"] >= policy["restrictions"]["minimum_failure_rate"]
        ):
            rows.append(
                {
                    "asset_id": asset_id,
                    "independent_failed_report_count": len(report_ids),
                    "failure_rate": statistics["failure_rate"],
                    "reason_counts": dict(sorted(reasons[asset_id].items())),
                    "effect": "compatibility_eligible_false",
                }
            )
    return rows


def _unique_text(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and len(value) == len(set(value))
        and all(isinstance(item, str) and item for item in value)
    )


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _finite_nonnegative(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _round(value: float) -> float:
    if not math.isfinite(value):
        raise PlannerFeedbackError("planner_feedback_nonfinite", str(value))
    return round(value, 12)


def _sha(document: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()
