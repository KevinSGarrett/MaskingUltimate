from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.coverage import (
    PlannerFeedbackError,
    build_candidate_selection,
    build_planner_feedback_report,
    derive_candidate_history_record,
    load_candidate_utility_policy,
    load_concentration_policy,
    load_planner_feedback_policy,
    publish_adapted_qualification_snapshot,
    publish_planner_feedback_report,
    validate_planner_feedback_policy,
    validate_planner_feedback_report,
)
from maskfactory.daz.validation_registry import (
    build_validation_set_report,
    load_validation_registry,
)
from test_daz_concentration import _inputs

ROOT = Path(__file__).resolve().parents[1]
VOCABULARY_PATH = ROOT / "qa/reports/daz_coverage_vocabulary/dcvr_f3b4c3927cc77cb389904bfc.json"
UTILITY_POLICY = ROOT / "configs/daz/candidate_utility.yaml"
CONCENTRATION_POLICY = ROOT / "configs/daz/concentration_limits.yaml"
FEEDBACK_POLICY = ROOT / "configs/daz/planner_feedback.yaml"
VALIDATION_REGISTRY = ROOT / "configs/daz/validation_registry.yaml"


def _sha(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _base(selection: dict) -> dict:
    content = {
        "snapshot_id": selection["qualification_snapshot"]["snapshot_id"],
        "source": selection["qualification_snapshot"]["source"],
        "rows": [
            {
                "candidate_id": row["candidate_id"],
                "features": row["features"],
                "penalties": row["penalties"],
                "hard_constraints": {
                    key: row["hard_constraints"][key]
                    for key in (
                        "mapping_eligible",
                        "compatibility_eligible",
                        "capacity_eligible",
                        "ontology_eligible",
                    )
                },
            }
            for row in selection["rows"]
        ],
    }
    return {**content, "snapshot_sha256": _sha(content)}


def _validation(entity_id: str, *, failure: tuple[str, str, str] | None = None) -> dict:
    registry = load_validation_registry(VALIDATION_REGISTRY)
    results = []
    for validator in registry["validators"][:9]:
        validator_id = validator["validator_id"]
        failed = failure is not None and validator_id == failure[0]
        results.append(
            {
                "validator_id": validator_id,
                "validator_version": validator["validator_version"],
                "entity_id": entity_id,
                "status": "fail" if failed else "pass",
                "reason_code": failure[1] if failed else validator["reason_codes"]["pass"][0],
                "metric": "fixture_measurement",
                "observed": 1 if not failed else 0,
                "expected": 1,
                "evidence_paths": [f"evidence/{entity_id}/{validator_id}.json"],
                "retryability": failure[2] if failed else "none",
                "affected_asset_ids": [],
                "affected_mapping_ids": [],
            }
        )
    return build_validation_set_report(
        results,
        entity_id=entity_id,
        scope="scene",
        registry=registry,
    )


def _observation(
    index: int,
    *,
    demand_id: str,
    family_id: str,
    asset_ids: list[str],
    failure: tuple[str, str, str] | None = None,
    affected_asset_id: str | None = None,
    accepted: bool = False,
    useful: int = 2,
) -> dict:
    report = _validation(f"scene_feedback_{index}", failure=failure)
    if affected_asset_id is not None:
        result = next(row for row in report["results"] if row["status"] == "fail")
        result["affected_asset_ids"] = [affected_asset_id]
        registry = load_validation_registry(VALIDATION_REGISTRY)
        report = build_validation_set_report(
            report["results"],
            entity_id=report["entity_id"],
            scope="scene",
            registry=registry,
        )
    content = {
        "demand_id": demand_id,
        "scene_family_id": family_id,
        "asset_ids": asset_ids,
        "target_cell_ids": ["target_hands_close"],
        "camera_region": "elevation_mid_focal_normal",
        "predicted_visible_labels": 4,
        "useful_visible_labels": useful,
        "gpu_seconds": 600.0,
        "storage_gib": 0.5,
        "acceptance_certificate": (
            {
                "certificate_id": f"dacc_{index:024x}",
                "certificate_sha256": f"{index + 1:064x}",
            }
            if accepted
            else None
        ),
        "validation_report": report,
    }
    return {"observation_id": f"dobs_{_sha(content)[:24]}", **content}


def _outcomes(observations: list[dict]) -> dict:
    content = {
        "snapshot_id": "validation_outcomes_fixture_v1",
        "source": "versioned_d7_validation_outcomes",
        "targets": [
            {
                "target_cell_id": "target_hands_close",
                "required_accepted": 8,
                "current_accepted": 2,
            }
        ],
        "observations": observations,
    }
    return {**content, "snapshot_sha256": _sha(content)}


def _fixture(observations: list[dict]) -> tuple[dict, dict, dict, dict, dict]:
    selection, batch, vocabulary = _inputs()
    base = _base(selection)
    inputs = {
        "candidate_batch": batch,
        "vocabulary_report": vocabulary,
        "base_qualification_snapshot": base,
        "outcome_snapshot": _outcomes(observations),
        "validation_registry": load_validation_registry(VALIDATION_REGISTRY),
        "concentration_policy": load_concentration_policy(CONCENTRATION_POLICY),
        "policy": load_planner_feedback_policy(FEEDBACK_POLICY),
    }
    return build_planner_feedback_report(**inputs), selection, batch, vocabulary, inputs


def _rank_one_context(selection: dict, batch: dict) -> tuple[dict, list[str]]:
    candidate_id = next(row["candidate_id"] for row in selection["rows"] if row["rank"] == 1)
    candidate = next(row for row in batch["candidates"] if row["candidate_id"] == candidate_id)
    identity = derive_candidate_history_record(
        candidate, load_concentration_policy(CONCENTRATION_POLICY)
    )
    return identity, list(identity["contributions"].values())


def test_policy_freezes_adaptation_history_and_authority_boundaries() -> None:
    policy = load_planner_feedback_policy(FEEDBACK_POLICY)
    assert policy["minimum_observations_for_adaptation"] == 2
    assert policy["predicted_rejection_cost"]["failure_rate_weight"] == 0.75
    assert policy["history"] == {
        "historical_recipes_immutable": True,
        "historical_outcomes_immutable": True,
        "accepted_counts_require_certificate_reference": True,
    }
    assert policy["authority"]["feedback_creates_gold"] is False


def test_no_outcomes_preserves_values_and_reports_underfilled_target() -> None:
    report, _, _, _, _ = _fixture([])
    assert report["summary"] == {
        "observation_count": 0,
        "validation_failure_count": 0,
        "accepted_certificate_reference_count": 0,
        "underfilled_target_cell_count": 1,
        "learned_restriction_count": 0,
        "adapted_candidate_count": 0,
    }
    assert all(row["evidence_scope"] == "none" for row in report["candidate_adaptations"])
    assert report["target_cells"][0]["remaining"] == 6


def test_adaptive_simulation_moves_selection_away_from_repeated_failure_family() -> None:
    selection, batch, _ = _inputs()
    identity, assets = _rank_one_context(selection, batch)
    original_selection = copy.deepcopy(selection)
    observations = [
        _observation(
            index,
            demand_id=batch["demand"]["demand_id"],
            family_id=identity["scene_family_id"],
            asset_ids=assets,
            failure=("DAZ-V4-001", "GEOMETRY_PENETRATION_EXCESS", "adjusted_recipe"),
            useful=0,
        )
        for index in range(2)
    ]
    original_outcomes = copy.deepcopy(_outcomes(observations))
    report, _, _, vocabulary, _ = _fixture(observations)
    adaptive = build_candidate_selection(
        candidate_batch=batch,
        vocabulary_report=vocabulary,
        qualification_snapshot=report["adapted_qualification_snapshot"],
        policy=load_candidate_utility_policy(UTILITY_POLICY),
    )
    assert adaptive["selected_candidate_id"] != selection["selected_candidate_id"]
    first = next(
        row
        for row in report["candidate_adaptations"]
        if row["candidate_id"] == selection["selected_candidate_id"]
    )
    assert first["evidence_scope"] == "scene_family"
    assert first["predicted_rejection_cost_after"] > 0.8
    assert first["label_visibility_gain_after"] == 0.0
    assert selection == original_selection
    assert _outcomes(observations) == original_outcomes


def test_certificate_references_alone_update_acceptance_yield_and_target() -> None:
    selection, batch, _ = _inputs()
    identity, assets = _rank_one_context(selection, batch)
    observations = [
        _observation(
            10,
            demand_id=batch["demand"]["demand_id"],
            family_id=identity["scene_family_id"],
            asset_ids=assets,
            accepted=True,
            useful=4,
        ),
        _observation(
            11,
            demand_id=batch["demand"]["demand_id"],
            family_id=identity["scene_family_id"],
            asset_ids=assets,
            useful=4,
        ),
    ]
    report, *_ = _fixture(observations)
    assert report["demand_statistics"][0]["accepted_count"] == 1
    assert report["demand_statistics"][0]["acceptance_yield"] == 0.5
    assert report["target_cells"][0]["new_accepted"] == 1
    assert report["target_cells"][0]["projected_accepted"] == 3


def test_three_independent_asset_failures_create_explicit_compatibility_restriction() -> None:
    selection, batch, _ = _inputs()
    identity, assets = _rank_one_context(selection, batch)
    affected = assets[0]
    observations = [
        _observation(
            index + 20,
            demand_id=batch["demand"]["demand_id"],
            family_id=identity["scene_family_id"],
            asset_ids=assets,
            failure=("DAZ-V1-001", "ASSET_HASH_MISMATCH", "asset_retest"),
            affected_asset_id=affected,
        )
        for index in range(3)
    ]
    report, *_ = _fixture(observations)
    assert report["learned_restrictions"] == [
        {
            "asset_id": affected,
            "independent_failed_report_count": 3,
            "failure_rate": 1.0,
            "reason_counts": {"ASSET_HASH_MISMATCH": 3},
            "effect": "compatibility_eligible_false",
        }
    ]
    row = next(
        row
        for row in report["adapted_qualification_snapshot"]["rows"]
        if row["candidate_id"] == selection["selected_candidate_id"]
    )
    assert row["hard_constraints"]["compatibility_eligible"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.__setitem__("minimum_observations_for_adaptation", 1),
        lambda value: value["restrictions"].__setitem__("minimum_failure_rate", 0.5),
        lambda value: value["history"].__setitem__("historical_recipes_immutable", False),
        lambda value: value["authority"].__setitem__("feedback_creates_gold", True),
    ],
)
def test_policy_weakening_fails_closed(mutation) -> None:
    policy = load_planner_feedback_policy(FEEDBACK_POLICY)
    mutation(policy)
    with pytest.raises(PlannerFeedbackError):
        validate_planner_feedback_policy(policy)


def test_outcome_and_report_tamper_and_publication_conflicts_fail_closed(tmp_path: Path) -> None:
    report, _, _, _, inputs = _fixture([])
    tampered_outcomes = copy.deepcopy(inputs["outcome_snapshot"])
    tampered_outcomes["targets"][0]["current_accepted"] = 3
    with pytest.raises(PlannerFeedbackError, match="snapshot_hash_invalid"):
        build_planner_feedback_report(**{**inputs, "outcome_snapshot": tampered_outcomes})
    tampered_report = copy.deepcopy(report)
    tampered_report["summary"]["adapted_candidate_count"] = 1
    with pytest.raises((PlannerFeedbackError, ValueError)):
        validate_planner_feedback_report(tampered_report, **inputs)
    target, published = publish_planner_feedback_report(report, tmp_path, **inputs)
    assert published is True
    assert publish_planner_feedback_report(report, tmp_path, **inputs) == (target, False)
    qualification, qualification_published = publish_adapted_qualification_snapshot(
        report, tmp_path
    )
    assert qualification_published is True
    assert publish_adapted_qualification_snapshot(report, tmp_path) == (qualification, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(PlannerFeedbackError, match="publication_conflict"):
        publish_planner_feedback_report(report, tmp_path, **inputs)


def test_cli_builds_direct_adaptive_snapshot_and_replays(tmp_path: Path) -> None:
    selection, batch, _ = _inputs()
    base = _base(selection)
    batch_path = tmp_path / "batch.json"
    base_path = tmp_path / "base.json"
    outcomes_path = tmp_path / "outcomes.json"
    batch_path.write_text(json.dumps(batch), encoding="utf-8")
    base_path.write_text(json.dumps(base), encoding="utf-8")
    outcomes_path.write_text(json.dumps(_outcomes([])), encoding="utf-8")
    command = [
        "daz",
        "coverage",
        "apply-feedback",
        "--candidate-batch",
        str(batch_path),
        "--vocabulary-report",
        str(VOCABULARY_PATH),
        "--base-qualification",
        str(base_path),
        "--outcome-snapshot",
        str(outcomes_path),
        "--validation-registry",
        str(VALIDATION_REGISTRY),
        "--concentration-policy",
        str(CONCENTRATION_POLICY),
        "--policy",
        str(FEEDBACK_POLICY),
        "--output",
        str(tmp_path / "out"),
    ]
    runner = CliRunner()
    first = runner.invoke(main, command)
    assert first.exit_code == 0, first.output
    data = json.loads(first.output)["data"]
    assert data["publication"]["report_published"] is True
    assert data["publication"]["qualification_published"] is True
    replay = runner.invoke(main, command)
    assert replay.exit_code == 0, replay.output
    replay_data = json.loads(replay.output)["data"]
    assert replay_data["publication"]["report_published"] is False
    assert replay_data["publication"]["qualification_published"] is False
