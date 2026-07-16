from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.assets import (
    REQUIRED_POOL_IDS,
    AssetPoolError,
    build_asset_compatibility_graph,
    build_asset_pool_report,
    load_asset_pool_policy,
    load_asset_vocabularies,
    publish_asset_pool_report,
    validate_asset_pool_policy,
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
        "scene_categories": ["clothed"],
        "compatibility_bases": [],
        "required_plugins": [],
        "capabilities": [],
        "facets": {},
        "dependencies": [],
    }
    record.update(overrides)
    return record


def _fixture_graph() -> tuple[dict, dict, dict]:
    vocabularies = load_asset_vocabularies(VOCABULARIES)
    policy = load_asset_pool_policy(POOL_POLICY, vocabularies)
    records = [
        _record("a", "figure_base"),
        _record(
            "b",
            "body_morph",
            capabilities=["bounded_sampling", "body_shape_control"],
        ),
        _record("c", "age_morph", capabilities=["age_appearance"]),
        _record("d", "material_skin", facets={"tone_band": "medium"}),
        _record(
            "e",
            "hair_fitted",
            facets={
                "hair_length": "long",
                "hair_texture": "curly",
                "hair_construction": "strand",
            },
        ),
        _record(
            "f",
            "pose_full_body",
            capabilities=["multi_person_pose"],
            facets={"pose_taxonomy": "reciprocal_contact"},
        ),
        _record(
            "1",
            "light_preset",
            character_scope="generation_neutral",
            figure_generations=["generation_neutral"],
            facets={"lighting_profile": "soft_studio"},
        ),
        _record(
            "2",
            "prop_occluder",
            character_scope="generation_neutral",
            figure_generations=["generation_neutral"],
            capabilities=["occlusion_role"],
            facets={"occlusion_support_role": "foreground_occluder"},
        ),
        _record("3", "unknown", figure_generations=["other_or_unknown"]),
    ]
    graph = build_asset_compatibility_graph(records, vocabularies)
    return graph, policy, vocabularies


def test_policy_defines_exact_approved_twelve_queryable_pools() -> None:
    vocabularies = load_asset_vocabularies(VOCABULARIES)
    policy = load_asset_pool_policy(POOL_POLICY, vocabularies)
    assert tuple(row["pool_id"] for row in policy["pools"]) == REQUIRED_POOL_IDS
    assert policy["requires_runtime_qualification_for_generation"] is True


def test_pool_projection_is_deterministic_grouped_and_never_enables_static_candidates(
    tmp_path: Path,
) -> None:
    graph, policy, vocabularies = _fixture_graph()
    first = build_asset_pool_report(graph, policy, vocabularies)
    second = build_asset_pool_report(graph, policy, vocabularies)
    assert first == second
    assert first["summary"]["pool_count"] == 12
    assert first["summary"]["qualified_member_memberships"] == 0
    assert first["summary"]["generation_enabled_pool_count"] == 0
    by_id = {row["pool_id"]: row for row in first["pools"]}
    assert by_id["g9_bounded_body_morphs"]["static_candidate_asset_ids"] == [_id("b")]
    assert by_id["multi_person_pose_templates"]["static_candidate_asset_ids"] == [_id("f")]
    assert by_id["g9_skin_materials_by_tone_band"]["facet_distributions"] == {
        "tone_band": {"medium": 1}
    }
    assert _id("3") not in {
        asset_id for pool in first["pools"] for asset_id in pool["static_candidate_asset_ids"]
    }
    target, published = publish_asset_pool_report(first, tmp_path / "reports")
    assert published is True
    assert publish_asset_pool_report(first, tmp_path / "reports") == (target, False)


def test_versioned_overrides_are_deterministic_and_cannot_include_ineligible_asset() -> None:
    graph, policy, vocabularies = _fixture_graph()
    excluded = deepcopy(policy)
    excluded["overrides"] = [
        {
            "pool_id": "g9_adult_base_figures",
            "asset_id": _id("a"),
            "action": "exclude",
            "reason": "fixture exclusion",
        }
    ]
    report = build_asset_pool_report(graph, excluded, vocabularies)
    pool = next(row for row in report["pools"] if row["pool_id"] == "g9_adult_base_figures")
    assert pool["static_candidate_asset_ids"] == []
    assert pool["applied_overrides"][0]["reason"] == "fixture exclusion"

    invalid = deepcopy(policy)
    invalid["overrides"] = [
        {
            "pool_id": "g9_adult_base_figures",
            "asset_id": _id("3"),
            "action": "include",
            "reason": "must not bypass eligibility",
        }
    ]
    with pytest.raises(AssetPoolError, match="ineligible_include"):
        build_asset_pool_report(graph, invalid, vocabularies)

    scene_filtered = deepcopy(policy)
    scene_filtered["pools"][0]["scene_categories"] = ["unclothed"]
    report = build_asset_pool_report(graph, scene_filtered, vocabularies)
    pool = next(row for row in report["pools"] if row["pool_id"] == "g9_adult_base_figures")
    assert pool["static_candidate_asset_ids"] == []


def test_policy_rejects_missing_reordered_or_unknown_pool_contract() -> None:
    _graph, policy, vocabularies = _fixture_graph()
    missing = deepcopy(policy)
    missing["pools"].pop()
    with pytest.raises(AssetPoolError, match="pool_ids_invalid"):
        validate_asset_pool_policy(missing, vocabularies)
    unknown = deepcopy(policy)
    unknown["pools"][0]["primary_asset_classes"] = ["invented"]
    with pytest.raises(AssetPoolError, match="pool_filter_invalid"):
        validate_asset_pool_policy(unknown, vocabularies)


def test_pool_cli_publishes_idempotently_without_copying_assets(tmp_path: Path) -> None:
    graph, _policy, _vocabularies = _fixture_graph()
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    runner = CliRunner()
    arguments = [
        "daz",
        "assets",
        "pool-report",
        "--graph",
        str(graph_path),
        "--output",
        str(tmp_path / "published"),
    ]
    first = runner.invoke(main, arguments)
    second = runner.invoke(main, arguments)
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    first_report = json.loads(first.output)
    second_report = json.loads(second.output)
    assert first_report["reason"] == "asset_pool_report_complete"
    assert first_report["data"]["publication"]["published"] is True
    assert second_report["data"]["publication"]["published"] is False
