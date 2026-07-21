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
    CandidateGenerationError,
    build_candidate_batch,
    build_real_deficit_signal_report,
    load_candidate_generation_policy,
    load_deficit_adapter_policy,
    publish_candidate_batch,
    validate_candidate_batch,
    validate_candidate_generation_policy,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs/daz/candidate_generation.yaml"
DEFICIT_POLICY = ROOT / "configs/daz/deficit_signal_adapter.yaml"
VOCABULARY_PATH = ROOT / "qa/reports/daz_coverage_vocabulary/dcvr_f3b4c3927cc77cb389904bfc.json"


def _sha(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _inputs() -> tuple[dict, dict, str]:
    vocabulary = json.loads(VOCABULARY_PATH.read_text(encoding="utf-8"))
    matrix = build_coverage_matrix(
        [
            {
                "status": "human_approved_gold",
                "view": "front",
                "pose_tags": ["arms_down"],
                "instance_context": "solo",
                "attributes": ["hands_visible"],
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
    demand = next(row for row in demands["demands"] if row["signal_kind"] == "canonical_cell")
    return vocabulary, demands, demand["demand_id"]


def _registry(vocabulary: dict, *, cap: int = 100, weighted: bool = False) -> dict:
    pools = {}
    for axis in vocabulary["registry_axes"]:
        axis_id = axis["axis_id"]
        if axis_id == "asset_product_family":
            values = ["daz_product_a", "daz_product_b"]
        elif axis_id == "recipe_family_id":
            values = ["daz_recipe_a", "daz_recipe_b"]
        else:
            values = [f"daz_asset_{axis_id}_a", f"daz_asset_{axis_id}_b"]
        pools[axis_id] = [
            {"value": values[0], "weight": 100.0 if weighted else 1.0, "cap": cap},
            {"value": values[1], "weight": 1.0, "cap": cap},
        ]
    content = {"snapshot_id": "registry_fixture_v1", "pools": pools}
    return {**content, "snapshot_sha256": _sha(content)}


def _build(*, seed: int = 17, count: int = 32, registry: dict | None = None) -> tuple[dict, dict]:
    vocabulary, demands, demand_id = _inputs()
    report = build_candidate_batch(
        vocabulary_report=vocabulary,
        demand_report=demands,
        demand_id=demand_id,
        policy=load_candidate_generation_policy(POLICY),
        master_seed=seed,
        candidate_count=count,
        registry_snapshot=registry,
    )
    return report, vocabulary


def _rehash(report: dict) -> None:
    content = {
        key: value
        for key, value in report.items()
        if key not in {"schema_version", "batch_id", "batch_sha256"}
    }
    digest = _sha(content)
    report["batch_id"] = f"dcb_{digest[:24]}"
    report["batch_sha256"] = digest


def test_policy_freezes_all_four_sampling_methods_and_authority() -> None:
    policy = load_candidate_generation_policy(POLICY)
    assert policy["candidate_count"] == {"minimum": 10, "default": 32, "maximum": 100}
    assert policy["continuous_sampling"]["bases"] == [2, 3, 5, 7, 11, 13]
    assert policy["registry_sampling"]["unresolved_pool_rejects_candidate"] is True
    assert policy["authority"]["candidates_are_recipes"] is False


def test_balanced_pairwise_halton_batch_is_deterministic_and_locked() -> None:
    vocabulary, _, _ = _inputs()
    registry = _registry(vocabulary)
    first, _ = _build(registry=registry)
    second, _ = _build(registry=registry)
    assert first == second
    assert first["summary"] == {
        "candidate_count": 32,
        "registry_complete_candidate_count": 32,
        "rejected_candidate_count": 0,
        "rejection_reason_counts": {},
        "scored_candidate_count": 0,
        "selected_candidate_count": 0,
    }
    assert first["distribution"]["maximum_unlocked_axis_count_spread"] <= 1
    assert first["distribution"]["covered_selected_pair_count"] > 0
    assert 0 < first["distribution"]["selected_pair_coverage_ratio"] < 1
    locked = {row["axis_id"]: row["value"] for row in first["demand"]["locked_axes"]}
    for candidate in first["candidates"]:
        discrete = {row["axis_id"]: row["value"] for row in candidate["discrete"]}
        assert all(discrete[axis] == value for axis, value in locked.items())
        assert len({row["axis_id"] for row in candidate["continuous"]}) == 6


def test_seed_changes_batch_but_replays_and_halton_values_stay_in_bounds() -> None:
    vocabulary, _, _ = _inputs()
    registry = _registry(vocabulary)
    first, _ = _build(seed=1, registry=registry)
    changed, _ = _build(seed=2, registry=registry)
    assert first["batch_id"] != changed["batch_id"]
    bounds = {
        row["axis_id"]: (row["minimum"], row["maximum"]) for row in vocabulary["continuous_axes"]
    }
    for candidate in changed["candidates"]:
        assert all(
            bounds[row["axis_id"]][0] <= row["value"] <= bounds[row["axis_id"]][1]
            for row in candidate["continuous"]
        )


def test_missing_registry_is_honestly_rejected_without_suppressing_candidates() -> None:
    report, _ = _build(registry=None)
    assert len(report["candidates"]) == 32
    assert report["summary"]["registry_complete_candidate_count"] == 0
    assert report["summary"]["rejected_candidate_count"] == 32
    assert report["summary"]["rejection_reason_counts"] == {"registry_pool_missing": 256}
    assert all(len(row["rejections"]) == 8 for row in report["candidates"])


def test_weighted_reservoir_observes_caps_and_exhaustion() -> None:
    vocabulary, _, _ = _inputs()
    weighted = _registry(vocabulary, weighted=True)
    report, _ = _build(count=100, registry=weighted)
    first_axis = vocabulary["registry_axes"][0]["axis_id"]
    selected = [
        next(row["value"] for row in candidate["registry"] if row["axis_id"] == first_axis)
        for candidate in report["candidates"]
    ]
    assert selected.count("daz_product_a") > selected.count("daz_product_b")
    capped = _registry(vocabulary, cap=5)
    exhausted, _ = _build(count=12, registry=capped)
    assert exhausted["summary"]["registry_complete_candidate_count"] == 10
    assert exhausted["summary"]["rejected_candidate_count"] == 2
    assert exhausted["summary"]["rejection_reason_counts"] == {"registry_pool_exhausted": 16}


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p["candidate_count"].__setitem__("minimum", 9), "count_invalid"),
        (lambda p: p["continuous_sampling"]["bases"].reverse(), "continuous_invalid"),
        (lambda p: p["authority"].__setitem__("candidates_are_recipes", True), "authority_invalid"),
    ],
)
def test_policy_weakening_fails_closed(mutation, reason: str) -> None:
    policy = load_candidate_generation_policy(POLICY)
    mutation(policy)
    with pytest.raises(CandidateGenerationError, match=reason):
        validate_candidate_generation_policy(policy)


def test_rehashed_distribution_and_candidate_tamper_fail_closed(tmp_path: Path) -> None:
    vocabulary, _, _ = _inputs()
    report, _ = _build(registry=_registry(vocabulary))
    tampered = copy.deepcopy(report)
    tampered["distribution"]["covered_selected_pair_count"] -= 1
    _rehash(tampered)
    with pytest.raises(CandidateGenerationError, match="summary_invalid"):
        validate_candidate_batch(tampered, vocabulary_report=vocabulary)
    candidate_tamper = copy.deepcopy(report)
    candidate_tamper["candidates"][0]["continuous"][0]["value"] = float("inf")
    with pytest.raises((CandidateGenerationError, ValueError)):
        validate_candidate_batch(candidate_tamper, vocabulary_report=vocabulary)
    target, published = publish_candidate_batch(report, tmp_path, vocabulary_report=vocabulary)
    assert published is True
    assert publish_candidate_batch(report, tmp_path, vocabulary_report=vocabulary) == (
        target,
        False,
    )
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(CandidateGenerationError, match="publication_conflict"):
        publish_candidate_batch(report, tmp_path, vocabulary_report=vocabulary)


def test_cli_generates_and_replays_batch(tmp_path: Path) -> None:
    vocabulary, demands, demand_id = _inputs()
    demand_path = tmp_path / "demands.json"
    registry_path = tmp_path / "registry.json"
    demand_path.write_text(json.dumps(demands), encoding="utf-8")
    registry_path.write_text(json.dumps(_registry(vocabulary)), encoding="utf-8")
    command = [
        "daz",
        "coverage",
        "generate-candidates",
        "--demand-report",
        str(demand_path),
        "--demand-id",
        demand_id,
        "--vocabulary-report",
        str(VOCABULARY_PATH),
        "--policy",
        str(POLICY),
        "--registry-snapshot",
        str(registry_path),
        "--master-seed",
        "17",
        "--candidate-count",
        "10",
        "--output",
        str(tmp_path / "out"),
    ]
    runner = CliRunner()
    first = runner.invoke(main, command)
    assert first.exit_code == 0, first.output
    assert json.loads(first.output)["reason"] == "daz_candidate_batch_generated"
    replay = runner.invoke(main, command)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
