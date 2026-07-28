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
    ConcentrationError,
    build_candidate_batch,
    build_candidate_selection,
    build_concentration_report,
    build_real_deficit_signal_report,
    derive_candidate_history_record,
    load_candidate_generation_policy,
    load_candidate_utility_policy,
    load_concentration_policy,
    load_deficit_adapter_policy,
    publish_concentration_report,
    validate_concentration_policy,
    validate_concentration_report,
)

ROOT = Path(__file__).resolve().parents[1]
VOCABULARY_PATH = ROOT / "qa/reports/daz_coverage_vocabulary/dcvr_f3b4c3927cc77cb389904bfc.json"
CANDIDATE_POLICY = ROOT / "configs/daz/candidate_generation.yaml"
UTILITY_POLICY = ROOT / "configs/daz/candidate_utility.yaml"
DEFICIT_POLICY = ROOT / "configs/daz/deficit_signal_adapter.yaml"
CONCENTRATION_POLICY = ROOT / "configs/daz/concentration_limits.yaml"
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


def _inputs(*, all_feasible: bool = True) -> tuple[dict, dict, dict]:
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
        prefix = (
            "daz_product"
            if axis_id == "asset_product_family"
            else "daz_recipe" if axis_id == "recipe_family_id" else f"daz_asset_{axis_id}"
        )
        pools[axis_id] = [
            {"value": f"{prefix}_{index}", "weight": 1.0, "cap": 100} for index in range(12)
        ]
    registry_content = {"snapshot_id": "registry_concentration_fixture_v1", "pools": pools}
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
    qualification_content = {
        "snapshot_id": "qualification_concentration_fixture_v1",
        "source": "versioned_d3_d5_feasibility_observations",
        "rows": [
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
            for candidate in batch["candidates"]
        ],
    }
    qualifications = {
        **qualification_content,
        "snapshot_sha256": _sha(qualification_content),
    }
    selection = build_candidate_selection(
        candidate_batch=batch,
        vocabulary_report=vocabulary,
        qualification_snapshot=qualifications,
        policy=load_candidate_utility_policy(UTILITY_POLICY),
    )
    return selection, batch, vocabulary


def _history(records: list[dict], *, base_product_ids: list[str] | None = None) -> dict:
    content = {
        "snapshot_id": "accepted_history_fixture_v1",
        "base_product_ids": base_product_ids or [],
        "records": records,
    }
    return {**content, "snapshot_sha256": _sha(content)}


def _unique_record(index: int) -> dict:
    suffix = f"{index:024x}"
    return {
        "candidate_id": f"dc_{suffix}",
        "scene_family_id": f"dfam_{suffix}",
        "contributions": {
            "character_preset_id": f"character_{index}",
            "skin_material_asset_id": f"skin_{index}",
            "hair_asset_id": f"hair_{index}",
            "complete_outfit_signature": f"outfit_{index}",
            "garment_asset_id": f"garment_{index}",
            "pose_asset_id": f"pose_{index}",
            "environment_asset_id": f"environment_{index}",
            "asset_product_family": f"daz_product_history_{index}",
        },
    }


def _ranked_identities(selection: dict, batch: dict, policy: dict) -> list[dict]:
    candidates = {row["candidate_id"]: row for row in batch["candidates"]}
    ranked = sorted(
        (row for row in selection["rows"] if row["feasible"]), key=lambda row: row["rank"]
    )
    return [
        derive_candidate_history_record(candidates[row["candidate_id"]], policy) for row in ranked
    ]


def _build(
    history: dict | None = None, *, all_feasible: bool = True
) -> tuple[dict, dict, dict, dict, dict]:
    selection, batch, vocabulary = _inputs(all_feasible=all_feasible)
    policy = load_concentration_policy(CONCENTRATION_POLICY)
    history = history or _history([])
    report = build_concentration_report(
        selection_report=selection,
        candidate_batch=batch,
        vocabulary_report=vocabulary,
        history_snapshot=history,
        policy=policy,
    )
    return report, selection, batch, vocabulary, policy


def test_policy_freezes_blueprint_caps_and_versioned_initial_windows() -> None:
    policy = load_concentration_policy(CONCENTRATION_POLICY)
    assert list(policy["dominance_caps"].values()) == [
        0.03,
        0.03,
        0.02,
        0.02,
        0.05,
        0.005,
        0.03,
        0.10,
    ]
    assert policy["cooldown_windows"] == {
        "scene_family_id": 32,
        "character_preset_id": 4,
        "hair_asset_id": 4,
        "pose_asset_id": 8,
        "environment_asset_id": 4,
    }
    assert policy["near_duplicate"]["rolling_window"] == 128


def test_empty_history_admits_original_rank_one_deterministically() -> None:
    report, selection, batch, vocabulary, policy = _build()
    replay = build_concentration_report(
        selection_report=selection,
        candidate_batch=batch,
        vocabulary_report=vocabulary,
        history_snapshot=_history([]),
        policy=policy,
    )
    assert report == replay
    assert report["satisfied"] is True
    assert report["admitted_candidate_id"] == next(
        row["candidate_id"] for row in selection["rows"] if row["rank"] == 1
    )
    assert report["summary"]["admitted_count"] == 1
    assert report["authority"]["admission_creates_gold"] is False


def test_pose_dominance_cap_reselects_without_recent_cooldown_overlap() -> None:
    selection, batch, vocabulary = _inputs()
    policy = load_concentration_policy(CONCENTRATION_POLICY)
    identities = _ranked_identities(selection, batch, policy)
    records = [_unique_record(index) for index in range(200)]
    records[0]["contributions"]["pose_asset_id"] = identities[0]["contributions"]["pose_asset_id"]
    history = _history(records)
    report = build_concentration_report(
        selection_report=selection,
        candidate_batch=batch,
        vocabulary_report=vocabulary,
        history_snapshot=history,
        policy=policy,
    )
    assert "pose_asset_id" in report["rows"][0]["dominance_failures"]
    assert "pose_asset_id" not in report["rows"][0]["cooldown_failures"]
    assert report["satisfied"] is True
    assert report["admitted_candidate_id"] != identities[0]["candidate_id"]


def test_recent_family_is_near_duplicate_and_cooldown_limited() -> None:
    selection, batch, vocabulary = _inputs()
    policy = load_concentration_policy(CONCENTRATION_POLICY)
    first = _ranked_identities(selection, batch, policy)[0]
    prior = copy.deepcopy(first)
    prior["candidate_id"] = "dc_eeeeeeeeeeeeeeeeeeeeeeee"
    report = build_concentration_report(
        selection_report=selection,
        candidate_batch=batch,
        vocabulary_report=vocabulary,
        history_snapshot=_history([prior]),
        policy=policy,
    )
    row = report["rows"][0]
    assert row["near_duplicate_count"] == 1
    assert "scene_family_id" in row["cooldown_failures"]
    assert row["passes"] is False
    assert report["admitted_candidate_id"] != first["candidate_id"]


def test_exact_candidate_repeat_is_permanent_beyond_rolling_windows() -> None:
    selection, batch, vocabulary = _inputs()
    policy = load_concentration_policy(CONCENTRATION_POLICY)
    first = _ranked_identities(selection, batch, policy)[0]
    records = [first, *[_unique_record(index + 1000) for index in range(129)]]
    report = build_concentration_report(
        selection_report=selection,
        candidate_batch=batch,
        vocabulary_report=vocabulary,
        history_snapshot=_history(records),
        policy=policy,
    )
    assert report["rows"][0]["exact_repeat"] is True
    assert report["rows"][0]["near_duplicate_count"] == 0
    assert report["admitted_candidate_id"] != first["candidate_id"]


def test_all_limited_and_all_infeasible_are_honestly_unsatisfied() -> None:
    selection, batch, vocabulary = _inputs()
    policy = load_concentration_policy(CONCENTRATION_POLICY)
    records = []
    for index, identity in enumerate(_ranked_identities(selection, batch, policy)):
        prior = copy.deepcopy(identity)
        prior["candidate_id"] = f"dc_{index + 500:024x}"
        records.append(prior)
    limited = build_concentration_report(
        selection_report=selection,
        candidate_batch=batch,
        vocabulary_report=vocabulary,
        history_snapshot=_history(records),
        policy=policy,
    )
    assert limited["satisfied"] is False
    assert limited["admitted_candidate_id"] is None
    assert limited["summary"]["limited_count"] == 10
    infeasible, *_ = _build(all_feasible=False)
    assert infeasible["satisfied"] is False
    assert infeasible["rows"] == []


def test_explicit_base_product_exemption_only_bypasses_product_cap() -> None:
    selection, batch, vocabulary = _inputs()
    policy = load_concentration_policy(CONCENTRATION_POLICY)
    first = _ranked_identities(selection, batch, policy)[0]
    product = first["contributions"]["asset_product_family"]
    records = [_unique_record(index) for index in range(100)]
    for record in records[:10]:
        record["contributions"]["asset_product_family"] = product
    without_exemption = build_concentration_report(
        selection_report=selection,
        candidate_batch=batch,
        vocabulary_report=vocabulary,
        history_snapshot=_history(records),
        policy=policy,
    )
    assert "asset_product_family" in without_exemption["rows"][0]["dominance_failures"]
    with_exemption = build_concentration_report(
        selection_report=selection,
        candidate_batch=batch,
        vocabulary_report=vocabulary,
        history_snapshot=_history(records, base_product_ids=[product]),
        policy=policy,
    )
    product_row = next(
        row
        for row in with_exemption["rows"][0]["contributions"]
        if row["entity_type"] == "asset_product_family"
    )
    assert product_row["base_product_exempt"] is True
    assert product_row["passes"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["dominance_caps"].__setitem__("pose_asset_id", 0.006),
        lambda value: value["cooldown_windows"].__setitem__("scene_family_id", 31),
        lambda value: value["near_duplicate"].__setitem__("maximum_members", 2),
        lambda value: value["authority"].__setitem__("admission_creates_gold", True),
    ],
)
def test_policy_weakening_fails_closed(mutation) -> None:
    policy = load_concentration_policy(CONCENTRATION_POLICY)
    mutation(policy)
    with pytest.raises(ConcentrationError):
        validate_concentration_policy(policy)


def test_semantic_tamper_and_immutable_publication_fail_closed(tmp_path: Path) -> None:
    report, selection, batch, vocabulary, policy = _build()
    tampered = copy.deepcopy(report)
    tampered["rows"][0]["admitted"] = False
    with pytest.raises((ConcentrationError, ValueError)):
        validate_concentration_report(
            tampered,
            selection_report=selection,
            candidate_batch=batch,
            vocabulary_report=vocabulary,
            history_snapshot=_history([]),
            policy=policy,
        )
    target, published = publish_concentration_report(
        report,
        tmp_path,
        selection_report=selection,
        candidate_batch=batch,
        vocabulary_report=vocabulary,
        history_snapshot=_history([]),
        policy=policy,
    )
    assert published is True
    assert publish_concentration_report(
        report,
        tmp_path,
        selection_report=selection,
        candidate_batch=batch,
        vocabulary_report=vocabulary,
        history_snapshot=_history([]),
        policy=policy,
    ) == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ConcentrationError, match="publication_conflict"):
        publish_concentration_report(
            report,
            tmp_path,
            selection_report=selection,
            candidate_batch=batch,
            vocabulary_report=vocabulary,
            history_snapshot=_history([]),
            policy=policy,
        )


def test_cli_applies_concentration_and_replays(tmp_path: Path) -> None:
    selection, batch, _ = _inputs()
    selection_path = tmp_path / "selection.json"
    batch_path = tmp_path / "batch.json"
    history_path = tmp_path / "history.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    batch_path.write_text(json.dumps(batch), encoding="utf-8")
    history_path.write_text(json.dumps(_history([])), encoding="utf-8")
    command = [
        "daz",
        "coverage",
        "apply-concentration",
        "--selection-report",
        str(selection_path),
        "--candidate-batch",
        str(batch_path),
        "--vocabulary-report",
        str(VOCABULARY_PATH),
        "--history-snapshot",
        str(history_path),
        "--policy",
        str(CONCENTRATION_POLICY),
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
