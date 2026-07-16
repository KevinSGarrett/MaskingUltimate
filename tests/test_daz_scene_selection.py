from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.assets import (
    AssetPoolError,
    build_asset_compatibility_graph,
    build_asset_pool_report,
    load_asset_pool_policy,
    load_asset_vocabularies,
)
from maskfactory.daz.scenes import (
    SceneSelectionError,
    select_character_foundation,
    validate_character_foundation_selection,
)

ROOT = Path(__file__).resolve().parents[1]
VOCABULARIES = ROOT / "configs" / "daz" / "asset_vocabularies.yaml"
POOL_POLICY = ROOT / "configs" / "daz" / "asset_pools.yaml"


def _id(token: str) -> str:
    return "ast_" + token * 24


def _record(token: str, primary_class: str, **overrides) -> dict:
    record = {
        "asset_id": _id(token),
        "asset_sha256": token * 64,
        "primary_asset_class": primary_class,
        "identity_status": "unique",
        "mapping_requirement": "none",
        "character_scope": "adult_human",
        "figure_generations": ["genesis_9"],
        "scene_categories": ["clothed", "unclothed", "neutral"],
        "compatibility_bases": [],
        "required_plugins": [],
        "capabilities": [],
        "facets": {},
        "dependencies": [],
    }
    record.update(overrides)
    return record


def _graph_and_report(*, include_dependency_qualification: bool = True) -> tuple[dict, dict]:
    vocabularies = load_asset_vocabularies(VOCABULARIES)
    policy = load_asset_pool_policy(POOL_POLICY, vocabularies)
    base_a = _record("a", "figure_base")
    base_b = _record("b", "figure_base")
    dependency = _record("f", "compatibility_resource")
    preset_a = _record(
        "c",
        "character_preset",
        compatibility_bases=[base_a["asset_id"]],
        dependencies=[
            {
                "target_asset_id": dependency["asset_id"],
                "relation": "requires",
                "required": True,
            }
        ],
    )
    preset_b = _record("d", "character_preset", compatibility_bases=[base_b["asset_id"]])
    skin_a = _record(
        "e",
        "material_skin",
        compatibility_bases=[base_a["asset_id"]],
        facets={"tone_band": "tone_1"},
    )
    skin_b = _record(
        "1",
        "material_skin",
        compatibility_bases=[base_b["asset_id"]],
        facets={"tone_band": "tone_2"},
    )
    records = [base_a, base_b, dependency, preset_a, preset_b, skin_a, skin_b]
    graph = build_asset_compatibility_graph(records, vocabularies)
    qualified = {record["asset_id"] for record in records}
    if not include_dependency_qualification:
        qualified.remove(dependency["asset_id"])
    report = build_asset_pool_report(
        graph,
        policy,
        vocabularies,
        qualified_asset_ids=qualified,
        qualification_projection_sha256="9" * 64,
    )
    return graph, report


def test_qualified_projection_is_explicit_and_static_candidates_do_not_self_promote() -> None:
    vocabularies = load_asset_vocabularies(VOCABULARIES)
    policy = load_asset_pool_policy(POOL_POLICY, vocabularies)
    base = _record("a", "figure_base")
    graph = build_asset_compatibility_graph([base], vocabularies)
    static_only = build_asset_pool_report(graph, policy, vocabularies)
    base_pool = next(
        pool for pool in static_only["pools"] if pool["pool_id"] == "g9_adult_base_figures"
    )
    assert base_pool["static_candidate_asset_ids"] == [base["asset_id"]]
    assert base_pool["qualified_member_asset_ids"] == []

    with pytest.raises(AssetPoolError, match="pool_qualification_projection_hash_missing"):
        build_asset_pool_report(graph, policy, vocabularies, qualified_asset_ids=[base["asset_id"]])

    projected = build_asset_pool_report(
        graph,
        policy,
        vocabularies,
        qualified_asset_ids=[base["asset_id"]],
        qualification_projection_sha256="9" * 64,
    )
    base_pool = next(
        pool for pool in projected["pools"] if pool["pool_id"] == "g9_adult_base_figures"
    )
    assert base_pool["qualified_member_asset_ids"] == [base["asset_id"]]
    assert projected["qualification_projection"]["qualified_asset_ids"] == [base["asset_id"]]


def test_pool_projection_refuses_missing_or_statically_ineligible_authority() -> None:
    vocabularies = load_asset_vocabularies(VOCABULARIES)
    policy = load_asset_pool_policy(POOL_POLICY, vocabularies)
    unknown = _record(
        "a",
        "unknown",
        figure_generations=["other_or_unknown"],
        character_scope="unknown",
    )
    graph = build_asset_compatibility_graph([unknown], vocabularies)
    with pytest.raises(AssetPoolError, match="pool_qualified_asset_statically_ineligible"):
        build_asset_pool_report(
            graph, policy, vocabularies, qualified_asset_ids=[unknown["asset_id"]]
        )
    with pytest.raises(AssetPoolError, match="pool_qualified_asset_missing"):
        build_asset_pool_report(graph, policy, vocabularies, qualified_asset_ids=[_id("b")])


def test_selection_is_deterministic_qualified_and_jointly_base_compatible() -> None:
    graph, report = _graph_and_report()
    first = select_character_foundation(graph, report, selection_seed=42)
    second = select_character_foundation(graph, report, selection_seed=42)
    assert first == second
    validate_character_foundation_selection(first, graph, report)
    selected = first["selected"]
    assert (
        selected["figure_asset_id"],
        selected["character_preset_asset_id"],
        selected["skin_material_asset_id"],
    ) in {
        (_id("a"), _id("c"), _id("e")),
        (_id("b"), _id("d"), _id("1")),
    }
    assert first["candidate_counts"] == {
        "base_figures": 2,
        "character_presets": 2,
        "skin_materials": 2,
        "compatible_combinations": 2,
    }
    assert first["rejection_counts"] == {"preset_base_mismatch": 4, "skin_base_mismatch": 2}


def test_tone_band_filter_and_required_dependency_qualification_fail_closed() -> None:
    graph, report = _graph_and_report()
    selected = select_character_foundation(graph, report, selection_seed=8, tone_band="tone_1")
    assert selected["selected"] == {
        "figure_asset_id": _id("a"),
        "character_preset_asset_id": _id("c"),
        "skin_material_asset_id": _id("e"),
    }

    graph, report = _graph_and_report(include_dependency_qualification=False)
    selected = select_character_foundation(graph, report, selection_seed=8)
    assert selected["selected"] == {
        "figure_asset_id": _id("b"),
        "character_preset_asset_id": _id("d"),
        "skin_material_asset_id": _id("1"),
    }
    assert selected["rejection_counts"]["required_dependency_not_runtime_qualified"] == 1


def test_empty_qualified_pool_and_replay_tampering_are_rejected() -> None:
    graph, report = _graph_and_report()
    vocabularies = load_asset_vocabularies(VOCABULARIES)
    policy = load_asset_pool_policy(POOL_POLICY, vocabularies)
    without_skin = build_asset_pool_report(
        graph,
        policy,
        vocabularies,
        qualified_asset_ids=[
            asset_id
            for asset_id in report["qualification_projection"]["qualified_asset_ids"]
            if asset_id not in {_id("e"), _id("1")}
        ],
        qualification_projection_sha256="8" * 64,
    )
    with pytest.raises(SceneSelectionError, match="selection_qualified_pool_empty"):
        select_character_foundation(graph, without_skin, selection_seed=1)

    selection = select_character_foundation(graph, report, selection_seed=1)
    tampered = deepcopy(selection)
    tampered["selected"]["figure_asset_id"] = (
        _id("a") if selection["selected"]["figure_asset_id"] == _id("b") else _id("b")
    )
    with pytest.raises(SceneSelectionError, match="selection_replay_mismatch"):
        validate_character_foundation_selection(tampered, graph, report)


def test_foundation_selection_cli_publishes_idempotently(tmp_path: Path) -> None:
    graph, report = _graph_and_report()
    graph_path = tmp_path / "graph.json"
    report_path = tmp_path / "pools.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    output = tmp_path / "selections"
    arguments = [
        "daz",
        "recipes",
        "select-foundation",
        "--graph",
        str(graph_path),
        "--pool-report",
        str(report_path),
        "--selection-seed",
        "42",
        "--output",
        str(output),
    ]
    runner = CliRunner()
    first = runner.invoke(main, arguments)
    second = runner.invoke(main, arguments)
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    first_envelope = json.loads(first.output)
    second_envelope = json.loads(second.output)
    assert first_envelope["data"]["selection_sha256"] == second_envelope["data"]["selection_sha256"]
    assert first_envelope["data"]["publication"]["published"] is True
    assert second_envelope["data"]["publication"]["published"] is False
