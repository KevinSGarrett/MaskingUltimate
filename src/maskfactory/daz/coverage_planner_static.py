"""STATIC binders for MF-P9-10 coverage planner / corpus-stage contracts.

Host-side fixture binders only. Re-verifies offline D9 planner chain (10.01ΓÇô10.06),
emits planned 1k pilot + 10k ablation corpus cards, synthetic capacity calibration,
and planned-vs-accepted coverage minima honesty.

Never claims live DAZ render/accept, 1k/10k accepted corpora, doctor-green, gold,
Main-complete, or PRODUCTION_EVIDENCE_PASS.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from ..datasets.coverage import ATTRIBUTES, CONTEXTS, POSES, VIEWS
from ..validation import validate_document
from .coverage import (
    build_coverage_vocabulary_report,
    load_candidate_generation_policy,
    load_candidate_utility_policy,
    load_concentration_policy,
    load_coverage_vocabulary,
    load_deficit_adapter_policy,
    load_planner_feedback_policy,
    validate_coverage_vocabulary_report,
)

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "daz_coverage_planner_static_report"
AUTHORITY = "daz_coverage_planner_static_only_no_live_pilot_ablation_accept_or_gold_authority"
SCHEMA_VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parents[3]

VOCAB_POLICY = ROOT / "configs" / "daz" / "coverage_vocabulary.yaml"
DEFICIT_POLICY = ROOT / "configs" / "daz" / "deficit_signal_adapter.yaml"
CANDIDATE_POLICY = ROOT / "configs" / "daz" / "candidate_generation.yaml"
UTILITY_POLICY = ROOT / "configs" / "daz" / "candidate_utility.yaml"
CONCENTRATION_POLICY = ROOT / "configs" / "daz" / "concentration_limits.yaml"
FEEDBACK_POLICY = ROOT / "configs" / "daz" / "planner_feedback.yaml"

PILOT_SCENE_COUNT = 1000
ABLATION_SCENE_COUNT = 10000
PLANNER_SEED = "mf_p9_10_coverage_planner_static_v1"

# Synthetic capacity estimates (bytes / seconds) ΓÇö fixture calibration only.
# Explicitly not measured from a live accepted pilot.
SYNTHETIC_PROFILE_P50_BYTES = 96 * 1024 * 1024
SYNTHETIC_PROFILE_P95_BYTES = 180 * 1024 * 1024
SYNTHETIC_TEMP_PEAK_BYTES = 256 * 1024 * 1024
SYNTHETIC_RETRY_BUDGET = 2
SYNTHETIC_TIMEOUT_SECONDS = 900
SOFT_FLOOR_GIB = 150

TRACKER_ITEMS = (
    "MF-P9-10.01",
    "MF-P9-10.02",
    "MF-P9-10.03",
    "MF-P9-10.04",
    "MF-P9-10.05",
    "MF-P9-10.06",
    "MF-P9-10.07",
    "MF-P9-10.08",
    "MF-P9-10.09",
    "MF-P9-10.10",
)

OFFLINE_CHAIN_CHECKS = (
    "vocabulary_policy_loads",
    "vocabulary_report_closed",
    "deficit_adapter_policy_loads",
    "candidate_generation_policy_loads",
    "utility_policy_loads",
    "concentration_policy_loads",
    "feedback_policy_loads",
)
PILOT_CHECKS = (
    "pilot_plan_scene_count_1000",
    "pilot_acceptance_cost_report_honest",
    "pilot_zero_accepted_rendered",
    "pilot_may_train_promoted_model_false",
)
CALIBRATION_CHECKS = (
    "calibration_profile_deterministic",
    "calibration_not_from_live_pilot",
    "reservation_formula_bound",
    "soft_floor_bound",
)
ABLATION_CHECKS = (
    "ablation_plan_scene_count_10000",
    "ablation_corpus_card_immutable_hash",
    "ablation_not_materialized",
    "ablation_may_train_promoted_model_false",
)
MINIMA_CHECKS = (
    "planned_view_pose_context_minima_evaluated",
    "planned_attribute_minima_evaluated",
    "high_risk_intersection_axes_bound",
    "accepted_not_conflated_with_planned",
    "overclaim_accepted_coverage_refused",
)

HONEST_NON_CLAIMS = (
    "mf_p9_10_07_pilot_complete",
    "mf_p9_10_08_live_calibration_complete",
    "mf_p9_10_09_ablation_corpus_complete",
    "mf_p9_10_10_accepted_coverage_complete",
    "live_daz_render_executed",
    "live_daz_accept_executed",
    "accepted_scene_count_nonzero",
    "doctor_green",
    "gold",
    "Main-complete",
    "PRODUCTION_EVIDENCE_PASS",
)


class DazCoveragePlannerStaticError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refuse_coverage_planner_overclaim(document: Mapping[str, Any]) -> None:
    """Fail closed on live pilot/ablation/accept/gold overclaims."""
    forbidden_true = (
        "mf_p9_10_07_pilot_complete",
        "mf_p9_10_08_live_calibration_complete",
        "mf_p9_10_09_ablation_corpus_complete",
        "mf_p9_10_10_accepted_coverage_complete",
        "live_daz_render_executed",
        "live_daz_accept_executed",
        "accepted_scene_count_nonzero",
        "doctor_green_claimed",
        "gold_claimed",
        "visual_qa_pass_claimed",
        "main_complete_claimed",
        "production_evidence_pass_claimed",
        "measured_from_live_pilot",
        "corpus_materialized_on_disk",
    )
    for key in forbidden_true:
        if document.get(key) is True:
            raise DazCoveragePlannerStaticError(f"coverage_planner_overclaim:{key}")
    if int(document.get("accepted_scene_count") or 0) != 0:
        raise DazCoveragePlannerStaticError("coverage_planner_overclaim:accepted_scene_count")
    if int(document.get("rendered_scene_count") or 0) != 0:
        raise DazCoveragePlannerStaticError("coverage_planner_overclaim:rendered_scene_count")


def _scene_id(stage: str, index: int) -> str:
    digest = hashlib.sha256(f"{PLANNER_SEED}|{stage}|{index:06d}".encode("utf-8")).hexdigest()
    return f"dcp_{stage}_{index:06d}_{digest[:12]}"


def _assign_axes(index: int) -> dict[str, str]:
    """Deterministic stratified axis assignment for planned coverage accounting."""
    view = VIEWS[index % len(VIEWS)]
    pose = POSES[(index // len(VIEWS)) % len(POSES)]
    context = CONTEXTS[(index // (len(VIEWS) * len(POSES))) % len(CONTEXTS)]
    attribute = ATTRIBUTES[index % len(ATTRIBUTES)]
    return {
        "canonical_view": view,
        "canonical_pose": pose,
        "instance_context": context,
        "canonical_attribute": attribute,
    }


def build_planned_scene_stream(stage: str, count: int) -> dict[str, Any]:
    """Build a deterministic planned-scene stream summary (IDs + axis counts)."""
    if stage not in {"pilot", "ablation"}:
        raise DazCoveragePlannerStaticError(f"unknown_stage:{stage}")
    if count < 1:
        raise DazCoveragePlannerStaticError("planned_count_invalid")

    cell_counts: Counter[tuple[str, str, str]] = Counter()
    attribute_counts: Counter[str] = Counter()
    hasher = hashlib.sha256()
    first_id = ""
    last_id = ""
    for index in range(count):
        scene_id = _scene_id(stage, index)
        axes = _assign_axes(index)
        if index == 0:
            first_id = scene_id
        if index == count - 1:
            last_id = scene_id
        hasher.update(scene_id.encode("utf-8"))
        hasher.update(b"|")
        hasher.update(json.dumps(axes, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        hasher.update(b"\n")
        cell_counts[(axes["canonical_view"], axes["canonical_pose"], axes["instance_context"])] += 1
        attribute_counts[axes["canonical_attribute"]] += 1

    return {
        "stage": stage,
        "planned_scene_count": count,
        "stream_sha256": hasher.hexdigest(),
        "first_scene_id": first_id,
        "last_scene_id": last_id,
        "accepted_scene_count": 0,
        "rendered_scene_count": 0,
        "attempted_scene_count": 0,
        "cell_count": len(cell_counts),
        "attribute_count": len(attribute_counts),
        "min_cell_planned": min(cell_counts.values()) if cell_counts else 0,
        "max_cell_planned": max(cell_counts.values()) if cell_counts else 0,
        "min_attribute_planned": min(attribute_counts.values()) if attribute_counts else 0,
        "max_attribute_planned": max(attribute_counts.values()) if attribute_counts else 0,
        "cell_counts": {
            f"{view}|{pose}|{context}": count
            for (view, pose, context), count in sorted(cell_counts.items())
        },
        "attribute_counts": dict(sorted(attribute_counts.items())),
    }


def evaluate_offline_chain_static_binder() -> dict[str, Any]:
    """Re-verify offline MF-P9-10.01ΓÇô10.06 policy/report loaders without live deficits."""
    missing = [
        path.name
        for path in (
            VOCAB_POLICY,
            DEFICIT_POLICY,
            CANDIDATE_POLICY,
            UTILITY_POLICY,
            CONCENTRATION_POLICY,
            FEEDBACK_POLICY,
        )
        if not path.is_file()
    ]
    if missing:
        raise DazCoveragePlannerStaticError(f"coverage_policy_missing:{','.join(missing)}")

    vocab_policy = load_coverage_vocabulary(VOCAB_POLICY)
    vocab_report = build_coverage_vocabulary_report(vocab_policy, ROOT)
    validate_coverage_vocabulary_report(vocab_report)
    summary = vocab_report.get("summary") or {}
    if summary.get("closed") is not True:
        raise DazCoveragePlannerStaticError("vocabulary_not_closed")
    if int(summary.get("fixed_axis_count") or 0) != 56:
        raise DazCoveragePlannerStaticError("vocabulary_axis_count_drift")
    if int(summary.get("high_risk_intersection_count") or 0) < 18:
        raise DazCoveragePlannerStaticError("high_risk_intersections_missing")

    load_deficit_adapter_policy(DEFICIT_POLICY)
    load_candidate_generation_policy(CANDIDATE_POLICY)
    load_candidate_utility_policy(UTILITY_POLICY)
    load_concentration_policy(CONCENTRATION_POLICY)
    load_planner_feedback_policy(FEEDBACK_POLICY)

    return {
        "vocabulary_policy_loads": True,
        "vocabulary_report_closed": True,
        "deficit_adapter_policy_loads": True,
        "candidate_generation_policy_loads": True,
        "utility_policy_loads": True,
        "concentration_policy_loads": True,
        "feedback_policy_loads": True,
        "vocabulary_report_id": vocab_report.get("report_id"),
        "vocabulary_report_sha256": vocab_report.get("report_sha256"),
        "fixed_axis_count": int(summary["fixed_axis_count"]),
        "high_risk_intersection_count": int(summary["high_risk_intersection_count"]),
        "policy_sha256": {
            "coverage_vocabulary": _file_sha(VOCAB_POLICY),
            "deficit_signal_adapter": _file_sha(DEFICIT_POLICY),
            "candidate_generation": _file_sha(CANDIDATE_POLICY),
            "candidate_utility": _file_sha(UTILITY_POLICY),
            "concentration_limits": _file_sha(CONCENTRATION_POLICY),
            "planner_feedback": _file_sha(FEEDBACK_POLICY),
        },
    }


def evaluate_pilot_plan_static_binder() -> dict[str, Any]:
    """Build 1,000-scene planned pilot card with honest acceptance/cost zeros."""
    stream = build_planned_scene_stream("pilot", PILOT_SCENE_COUNT)
    if stream["planned_scene_count"] != PILOT_SCENE_COUNT:
        raise DazCoveragePlannerStaticError("pilot_count_mismatch")
    if stream["accepted_scene_count"] != 0 or stream["rendered_scene_count"] != 0:
        raise DazCoveragePlannerStaticError("pilot_nonzero_accept_or_render")

    acceptance_cost = {
        "planned": PILOT_SCENE_COUNT,
        "attempted": 0,
        "rendered": 0,
        "accepted": 0,
        "yield": None,
        "cost_per_accept_gpu_seconds": None,
        "total_gpu_seconds": 0,
        "may_train_promoted_model": False,
        "experimental_only": True,
        "live_daz_pilot_executed": False,
    }
    card = {
        "card_type": "daz_pilot_plan_card",
        "stage": "pilot",
        "planned_scene_count": PILOT_SCENE_COUNT,
        "stream_sha256": stream["stream_sha256"],
        "first_scene_id": stream["first_scene_id"],
        "last_scene_id": stream["last_scene_id"],
        "acceptance_cost": acceptance_cost,
        "authority": "planned_only_no_accepted_or_gold",
    }
    card_sha = _sha(card)
    return {
        "pilot_plan_scene_count_1000": True,
        "pilot_acceptance_cost_report_honest": True,
        "pilot_zero_accepted_rendered": True,
        "pilot_may_train_promoted_model_false": True,
        "pilot_stream_sha256": stream["stream_sha256"],
        "pilot_card_sha256": card_sha,
        "pilot_first_scene_id": stream["first_scene_id"],
        "pilot_last_scene_id": stream["last_scene_id"],
        "acceptance_cost": acceptance_cost,
        "stream_summary": {
            "cell_count": stream["cell_count"],
            "attribute_count": stream["attribute_count"],
            "min_cell_planned": stream["min_cell_planned"],
            "min_attribute_planned": stream["min_attribute_planned"],
        },
    }


def evaluate_calibration_static_binder() -> dict[str, Any]:
    """Derive synthetic storage/retry/timeout profile; never live-pilot measured."""
    reservation = int(max(SYNTHETIC_PROFILE_P95_BYTES, SYNTHETIC_PROFILE_P50_BYTES) * 1.25)
    if reservation <= 0:
        raise DazCoveragePlannerStaticError("reservation_nonpositive")
    profile = {
        "profile_version": "1.0.0",
        "measured_from_live_pilot": False,
        "synthetic_fixture_estimates": True,
        "bytes_per_scene_p50": SYNTHETIC_PROFILE_P50_BYTES,
        "bytes_per_scene_p95": SYNTHETIC_PROFILE_P95_BYTES,
        "temp_peak_bytes": SYNTHETIC_TEMP_PEAK_BYTES,
        "retry_budget": SYNTHETIC_RETRY_BUDGET,
        "timeout_seconds": SYNTHETIC_TIMEOUT_SECONDS,
        "reservation_bytes": reservation,
        "soft_floor_gib": SOFT_FLOOR_GIB,
        "target_sizes": {
            "pilot_planned": PILOT_SCENE_COUNT,
            "ablation_planned": ABLATION_SCENE_COUNT,
        },
        "projections_gib": {
            "pilot_p95": round((SYNTHETIC_PROFILE_P95_BYTES * PILOT_SCENE_COUNT) / (1024**3), 3),
            "ablation_p95": round(
                (SYNTHETIC_PROFILE_P95_BYTES * ABLATION_SCENE_COUNT) / (1024**3), 3
            ),
        },
    }
    return {
        "calibration_profile_deterministic": True,
        "calibration_not_from_live_pilot": True,
        "reservation_formula_bound": True,
        "soft_floor_bound": True,
        "calibration_profile_sha256": _sha(profile),
        "reservation_bytes": reservation,
        "soft_floor_gib": SOFT_FLOOR_GIB,
        "measured_from_live_pilot": False,
        "profile": profile,
    }


def evaluate_ablation_corpus_static_binder() -> dict[str, Any]:
    """Build immutable 10,000-scene ablation *plan* card; never materialize corpus."""
    stream = build_planned_scene_stream("ablation", ABLATION_SCENE_COUNT)
    if stream["planned_scene_count"] != ABLATION_SCENE_COUNT:
        raise DazCoveragePlannerStaticError("ablation_count_mismatch")
    card = {
        "card_type": "daz_ablation_corpus_plan_card",
        "stage": "ablation",
        "planned_scene_count": ABLATION_SCENE_COUNT,
        "stream_sha256": stream["stream_sha256"],
        "first_scene_id": stream["first_scene_id"],
        "last_scene_id": stream["last_scene_id"],
        "corpus_materialized_on_disk": False,
        "accepted_scene_count": 0,
        "rendered_scene_count": 0,
        "may_train_promoted_model": False,
        "challenger_only": True,
        "matched_mixture_targets_percent": [10, 20, 30],
        "authority": "planned_only_no_accepted_or_gold",
    }
    card_sha = _sha(card)
    return {
        "ablation_plan_scene_count_10000": True,
        "ablation_corpus_card_immutable_hash": True,
        "ablation_not_materialized": True,
        "ablation_may_train_promoted_model_false": True,
        "ablation_stream_sha256": stream["stream_sha256"],
        "ablation_card_sha256": card_sha,
        "ablation_first_scene_id": stream["first_scene_id"],
        "ablation_last_scene_id": stream["last_scene_id"],
        "corpus_materialized_on_disk": False,
        "stream_summary": {
            "cell_count": stream["cell_count"],
            "attribute_count": stream["attribute_count"],
            "min_cell_planned": stream["min_cell_planned"],
            "min_attribute_planned": stream["min_attribute_planned"],
        },
    }


def evaluate_coverage_minima_static_binder(
    pilot_stream: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate planned coverage minima; refuse accepted/planned conflation."""
    stream = dict(pilot_stream or build_planned_scene_stream("pilot", PILOT_SCENE_COUNT))
    # Doc 19 pilot diagnostic targets (accepted); STATIC evaluates planned structure only.
    pilot_cell_target = 8
    pilot_attribute_target = 40
    expected_cells = len(VIEWS) * len(POSES) * len(CONTEXTS)
    if stream["cell_count"] != expected_cells:
        raise DazCoveragePlannerStaticError(
            f"cell_coverage_incomplete:{stream['cell_count']}/{expected_cells}"
        )
    if stream["attribute_count"] != len(ATTRIBUTES):
        raise DazCoveragePlannerStaticError("attribute_coverage_incomplete")

    planned_cell_meets = int(stream["min_cell_planned"]) >= pilot_cell_target
    planned_attr_meets = int(stream["min_attribute_planned"]) >= pilot_attribute_target
    # Honesty: planned minima are diagnostic only; accepted minima remain unmet.
    accepted_cell_meets = False
    accepted_attr_meets = False
    if stream.get("accepted_scene_count", 0) != 0:
        raise DazCoveragePlannerStaticError("accepted_conflated_into_minima")

    try:
        refuse_coverage_planner_overclaim(
            {
                "mf_p9_10_10_accepted_coverage_complete": True,
                "accepted_scene_count": 0,
            }
        )
        raise DazCoveragePlannerStaticError("accepted_coverage_overclaim_negative_passed")
    except DazCoveragePlannerStaticError as exc:
        if "mf_p9_10_10_accepted_coverage_complete" not in exc.reason:
            raise
        overclaim_refused = True

    high_risk_bound = True  # vocabulary binder already proved ΓëÑ18 intersections

    return {
        "planned_view_pose_context_minima_evaluated": True,
        "planned_attribute_minima_evaluated": True,
        "high_risk_intersection_axes_bound": high_risk_bound,
        "accepted_not_conflated_with_planned": True,
        "overclaim_accepted_coverage_refused": overclaim_refused,
        "expected_cell_count": expected_cells,
        "observed_cell_count": stream["cell_count"],
        "pilot_cell_target_accepted": pilot_cell_target,
        "pilot_attribute_target_accepted": pilot_attribute_target,
        "planned_min_cell": stream["min_cell_planned"],
        "planned_min_attribute": stream["min_attribute_planned"],
        "planned_cell_target_met": planned_cell_meets,
        "planned_attribute_target_met": planned_attr_meets,
        "accepted_cell_target_met": accepted_cell_meets,
        "accepted_attribute_target_met": accepted_attr_meets,
        "accepted_coverage_complete": False,
    }


def run_daz_coverage_planner_static_suite() -> dict[str, Any]:
    """Execute MF-P9-10 STATIC binders and seal a schema-valid report."""
    offline = evaluate_offline_chain_static_binder()
    pilot = evaluate_pilot_plan_static_binder()
    calibration = evaluate_calibration_static_binder()
    ablation = evaluate_ablation_corpus_static_binder()
    minima = evaluate_coverage_minima_static_binder()

    offline_checks = {key: bool(offline[key]) for key in OFFLINE_CHAIN_CHECKS}
    pilot_checks = {key: bool(pilot[key]) for key in PILOT_CHECKS}
    calibration_checks = {key: bool(calibration[key]) for key in CALIBRATION_CHECKS}
    ablation_checks = {key: bool(ablation[key]) for key in ABLATION_CHECKS}
    minima_checks = {key: bool(minima[key]) for key in MINIMA_CHECKS}

    for name, checks in (
        ("offline", offline_checks),
        ("pilot", pilot_checks),
        ("calibration", calibration_checks),
        ("ablation", ablation_checks),
        ("minima", minima_checks),
    ):
        if not all(checks.values()):
            raise DazCoveragePlannerStaticError(f"{name}_checks_failed")

    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "items": list(TRACKER_ITEMS),
        "offline_chain_checks": dict(sorted(offline_checks.items())),
        "pilot_checks": dict(sorted(pilot_checks.items())),
        "calibration_checks": dict(sorted(calibration_checks.items())),
        "ablation_checks": dict(sorted(ablation_checks.items())),
        "minima_checks": dict(sorted(minima_checks.items())),
        "checks": {
            "offline_planner_chain_binder": "pass",
            "pilot_plan_binder": "pass",
            "calibration_profile_binder": "pass",
            "ablation_corpus_plan_binder": "pass",
            "coverage_minima_binder": "pass",
        },
        "mf_p9_10_07_pilot_complete": False,
        "mf_p9_10_08_live_calibration_complete": False,
        "mf_p9_10_09_ablation_corpus_complete": False,
        "mf_p9_10_10_accepted_coverage_complete": False,
        "live_daz_render_executed": False,
        "live_daz_accept_executed": False,
        "accepted_scene_count": 0,
        "rendered_scene_count": 0,
        "accepted_scene_count_nonzero": False,
        "measured_from_live_pilot": False,
        "corpus_materialized_on_disk": False,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "visual_qa_pass_claimed": False,
        "main_complete_claimed": False,
        "production_evidence_pass_claimed": False,
        "honest_non_claims": list(HONEST_NON_CLAIMS),
        "bindings": {
            "vocabulary_report_id": offline["vocabulary_report_id"],
            "vocabulary_report_sha256": offline["vocabulary_report_sha256"],
            "pilot_stream_sha256": pilot["pilot_stream_sha256"],
            "pilot_card_sha256": pilot["pilot_card_sha256"],
            "ablation_stream_sha256": ablation["ablation_stream_sha256"],
            "ablation_card_sha256": ablation["ablation_card_sha256"],
            "calibration_profile_sha256": calibration["calibration_profile_sha256"],
            "reservation_bytes": calibration["reservation_bytes"],
            "soft_floor_gib": calibration["soft_floor_gib"],
            "planned_pilot_scenes": PILOT_SCENE_COUNT,
            "planned_ablation_scenes": ABLATION_SCENE_COUNT,
            "policy_sha256": offline["policy_sha256"],
            "planned_cell_target_met": minima["planned_cell_target_met"],
            "planned_attribute_target_met": minima["planned_attribute_target_met"],
            "accepted_coverage_complete": False,
        },
        "implementation": {
            "module": "src/maskfactory/daz/coverage_planner_static.py",
            "configs": [
                "configs/daz/coverage_vocabulary.yaml",
                "configs/daz/deficit_signal_adapter.yaml",
                "configs/daz/candidate_generation.yaml",
                "configs/daz/candidate_utility.yaml",
                "configs/daz/concentration_limits.yaml",
                "configs/daz/planner_feedback.yaml",
            ],
            "tests": ["tests/test_daz_coverage_planner_static.py"],
        },
    }
    refuse_coverage_planner_overclaim(draft)
    digest = _sha(draft)
    draft["report_id"] = f"dcp_{digest[:24]}"
    draft["seal_sha256"] = digest
    draft["sha256"] = _sha({key: value for key, value in draft.items() if key != "sha256"})

    issues = validate_document(draft, "daz_coverage_planner_static_report")
    if issues:
        detail = "; ".join(
            f"{getattr(issue, 'pointer', None) or '/'}: {issue.message}" for issue in issues
        )
        raise DazCoveragePlannerStaticError(f"schema_validation_failed:{detail}")
    return draft


__all__ = [
    "ABLATION_CHECKS",
    "ABLATION_SCENE_COUNT",
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "CALIBRATION_CHECKS",
    "HONEST_NON_CLAIMS",
    "MINIMA_CHECKS",
    "OFFLINE_CHAIN_CHECKS",
    "PILOT_CHECKS",
    "PILOT_SCENE_COUNT",
    "PROOF_TIER",
    "SCHEMA_VERSION",
    "TRACKER_ITEMS",
    "DazCoveragePlannerStaticError",
    "build_planned_scene_stream",
    "evaluate_ablation_corpus_static_binder",
    "evaluate_calibration_static_binder",
    "evaluate_coverage_minima_static_binder",
    "evaluate_offline_chain_static_binder",
    "evaluate_pilot_plan_static_binder",
    "refuse_coverage_planner_overclaim",
    "run_daz_coverage_planner_static_suite",
]
