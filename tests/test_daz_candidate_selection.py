from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.datasets.coverage import build_coverage_matrix
from maskfactory.daz.coverage import (
    CandidateSelectionError,
    build_candidate_batch,
    build_candidate_selection,
    build_real_deficit_signal_report,
    load_candidate_generation_policy,
    load_candidate_utility_policy,
    load_deficit_adapter_policy,
    publish_candidate_selection,
    validate_candidate_selection,
    validate_candidate_utility_policy,
)

ROOT = Path(__file__).resolve().parents[1]
VOCABULARY_PATH = ROOT / "qa/reports/daz_coverage_vocabulary/dcvr_f3b4c3927cc77cb389904bfc.json"
CANDIDATE_POLICY = ROOT / "configs/daz/candidate_generation.yaml"
UTILITY_POLICY = ROOT / "configs/daz/candidate_utility.yaml"
DEFICIT_POLICY = ROOT / "configs/daz/deficit_signal_adapter.yaml"
FEATURES = (
    "canonical_coverage_deficit_gain",
    "high_risk_intersection_gain",
    "label_visibility_gain",
    "asset_diversity_gain",
    "failure_mining_priority",
    "domain_randomization_gain",
    "multi_person_identity_gain",
    "recency_need",
)
PENALTIES = (
    "incompatibility_penalty",
    "dominance_penalty",
    "recent_repetition_penalty",
    "predicted_rejection_cost",
)


def _sha(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _batch() -> tuple[dict, dict]:
    vocabulary = json.loads(VOCABULARY_PATH.read_text(encoding="utf-8"))
    matrix = build_coverage_matrix(
        [
            {
                "status": "human_approved_gold",
                "view": "front",
                "pose_tags": ["arms_down"],
                "instance_context": "solo",
                "attributes": [],
            }
        ],
        generated_at=datetime(2026, 7, 17, tzinfo=UTC),
    )
    demands = build_real_deficit_signal_report(
        matrix,
        source_id="real_coverage_snapshot",
        source_sha256=_sha(matrix),
        policy=load_deficit_adapter_policy(DEFICIT_POLICY),
        vocabulary_report=vocabulary,
    )
    demand_id = next(
        row["demand_id"] for row in demands["demands"] if row["signal_kind"] == "canonical_cell"
    )
    pools = {}
    for axis in vocabulary["registry_axes"]:
        axis_id = axis["axis_id"]
        value = (
            "daz_product_fixture"
            if axis_id == "asset_product_family"
            else (
                "daz_recipe_fixture"
                if axis_id == "recipe_family_id"
                else f"daz_asset_{axis_id}_fixture"
            )
        )
        pools[axis_id] = [{"value": value, "weight": 1.0, "cap": 100}]
    registry_content = {"snapshot_id": "registry_fixture_v1", "pools": pools}
    registry = {**registry_content, "snapshot_sha256": _sha(registry_content)}
    batch = build_candidate_batch(
        vocabulary_report=vocabulary,
        demand_report=demands,
        demand_id=demand_id,
        policy=load_candidate_generation_policy(CANDIDATE_POLICY),
        master_seed=17,
        candidate_count=10,
        registry_snapshot=registry,
    )
    return batch, vocabulary


def _qualifications(batch: dict, *, all_feasible: bool = True) -> dict:
    rows = []
    for candidate in batch["candidates"]:
        rows.append(
            {
                "candidate_id": candidate["candidate_id"],
                "features": {name: 0.5 for name in FEATURES},
                "penalties": {name: 0.0 for name in PENALTIES},
                "hard_constraints": {
                    "mapping_eligible": all_feasible,
                    "compatibility_eligible": all_feasible,
                    "capacity_eligible": all_feasible,
                    "ontology_eligible": all_feasible,
                },
            }
        )
    content = {
        "snapshot_id": "qualification_fixture_v1",
        "source": "versioned_d3_d5_feasibility_observations",
        "rows": rows,
    }
    return {**content, "snapshot_sha256": _sha(content)}


def _refresh_snapshot(snapshot: dict) -> None:
    snapshot["snapshot_sha256"] = _sha(
        {key: snapshot[key] for key in ("snapshot_id", "source", "rows")}
    )


def _rehash_report(report: dict) -> None:
    content = {
        key: value
        for key, value in report.items()
        if key not in {"schema_version", "selection_id", "selection_sha256"}
    }
    digest = _sha(content)
    report["selection_id"] = f"dcsr_{digest[:24]}"
    report["selection_sha256"] = digest


def _build(snapshot: dict | None = None) -> tuple[dict, dict, dict]:
    batch, vocabulary = _batch()
    qualifications = snapshot or _qualifications(batch)
    report = build_candidate_selection(
        candidate_batch=batch,
        vocabulary_report=vocabulary,
        qualification_snapshot=qualifications,
        policy=load_candidate_utility_policy(UTILITY_POLICY),
    )
    return report, batch, vocabulary


def test_policy_matches_exact_blueprint_formula_and_hard_gate_order() -> None:
    policy = load_candidate_utility_policy(UTILITY_POLICY)
    assert list(policy["positive_weights"].values()) == [
        0.30,
        0.20,
        0.15,
        0.10,
        0.10,
        0.05,
        0.05,
        0.05,
    ]
    assert sum(policy["positive_weights"].values()) == 1.0
    assert policy["hard_constraints"][0] == "registry_complete"
    assert policy["ranking"]["order"] == [
        "utility_desc",
        "asset_diversity_gain_desc",
        "candidate_id_asc",
    ]


def test_exact_utility_ranking_is_deterministic_and_selects_one() -> None:
    report, batch, vocabulary = _build()
    assert report == build_candidate_selection(
        candidate_batch=batch,
        vocabulary_report=vocabulary,
        qualification_snapshot=_qualifications(batch),
        policy=load_candidate_utility_policy(UTILITY_POLICY),
    )
    assert report["satisfied"] is True
    assert report["summary"] == {
        "candidate_count": 10,
        "feasible_count": 10,
        "infeasible_count": 0,
        "scored_count": 10,
        "selected_count": 1,
        "hard_failure_counts": {},
        "maximum_utility": 0.5,
    }
    assert sum(row["selected"] for row in report["rows"]) == 1


def test_t042_injected_canonical_deficit_shifts_selection() -> None:
    batch, _ = _batch()
    qualifications = _qualifications(batch)
    qualifications["rows"][0]["features"]["canonical_coverage_deficit_gain"] = 1.0
    qualifications["rows"][1]["features"]["canonical_coverage_deficit_gain"] = 0.0
    _refresh_snapshot(qualifications)
    first, _, _ = _build(qualifications)
    assert first["selected_candidate_id"] == batch["candidates"][0]["candidate_id"]
    qualifications["rows"][0]["features"]["canonical_coverage_deficit_gain"] = 0.0
    qualifications["rows"][1]["features"]["canonical_coverage_deficit_gain"] = 1.0
    _refresh_snapshot(qualifications)
    shifted, _, _ = _build(qualifications)
    assert shifted["selected_candidate_id"] == batch["candidates"][1]["candidate_id"]


def test_high_utility_cannot_override_hard_compatibility_gate() -> None:
    batch, _ = _batch()
    qualifications = _qualifications(batch)
    qualifications["rows"][0]["features"] = {name: 1.0 for name in FEATURES}
    qualifications["rows"][0]["hard_constraints"]["compatibility_eligible"] = False
    qualifications["rows"][1]["features"] = {name: 0.0 for name in FEATURES}
    _refresh_snapshot(qualifications)
    report, _, _ = _build(qualifications)
    first = report["rows"][0]
    assert first["utility"] is None and first["rank"] is None
    assert "compatibility_eligible" in first["hard_failures"]
    assert report["selected_candidate_id"] != first["candidate_id"]


def test_t043_all_infeasible_is_honest_unsatisfied() -> None:
    batch, _ = _batch()
    report, _, _ = _build(_qualifications(batch, all_feasible=False))
    assert report["satisfied"] is False
    assert report["selected_candidate_id"] is None
    assert report["summary"]["feasible_count"] == 0
    assert report["summary"]["selected_count"] == 0
    assert all(row["utility"] is None and row["rank"] is None for row in report["rows"])


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda p: p["positive_weights"].__setitem__("canonical_coverage_deficit_gain", 0.31),
            "weights_invalid",
        ),
        (lambda p: p["hard_constraints"].reverse(), "terms_invalid"),
        (lambda p: p["authority"].__setitem__("selection_is_recipe", True), "authority_invalid"),
    ],
)
def test_policy_weakening_fails_closed(mutation, reason: str) -> None:
    policy = load_candidate_utility_policy(UTILITY_POLICY)
    mutation(policy)
    with pytest.raises(CandidateSelectionError, match=reason):
        validate_candidate_utility_policy(policy)


def test_report_tamper_and_publication_conflict_fail_closed(tmp_path: Path) -> None:
    report, batch, vocabulary = _build()
    tampered = copy.deepcopy(report)
    tampered["rows"][0]["utility"] += 0.1
    with pytest.raises(CandidateSelectionError, match="hash_invalid"):
        validate_candidate_selection(tampered, candidate_batch=batch, vocabulary_report=vocabulary)
    coherent = copy.deepcopy(report)
    coherent["rows"][0]["features"]["recency_need"] = 0.75
    _rehash_report(coherent)
    with pytest.raises(CandidateSelectionError, match="qualification_hash_invalid"):
        validate_candidate_selection(coherent, candidate_batch=batch, vocabulary_report=vocabulary)
    target, published = publish_candidate_selection(
        report, tmp_path, candidate_batch=batch, vocabulary_report=vocabulary
    )
    assert published is True
    assert publish_candidate_selection(
        report, tmp_path, candidate_batch=batch, vocabulary_report=vocabulary
    ) == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(CandidateSelectionError, match="publication_conflict"):
        publish_candidate_selection(
            report, tmp_path, candidate_batch=batch, vocabulary_report=vocabulary
        )


def test_cli_selects_and_replays(tmp_path: Path) -> None:
    batch, vocabulary = _batch()
    qualifications = _qualifications(batch)
    batch_path = tmp_path / "batch.json"
    qualification_path = tmp_path / "qualifications.json"
    batch_path.write_text(json.dumps(batch), encoding="utf-8")
    qualification_path.write_text(json.dumps(qualifications), encoding="utf-8")
    command = [
        "daz",
        "coverage",
        "select-candidate",
        "--candidate-batch",
        str(batch_path),
        "--vocabulary-report",
        str(VOCABULARY_PATH),
        "--qualification-snapshot",
        str(qualification_path),
        "--policy",
        str(UTILITY_POLICY),
        "--output",
        str(tmp_path / "out"),
    ]
    runner = CliRunner()
    first = runner.invoke(main, command)
    assert first.exit_code == 0, first.output
    assert json.loads(first.output)["data"]["satisfied"] is True
    replay = runner.invoke(main, command)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
