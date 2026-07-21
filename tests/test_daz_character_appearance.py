from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.assets import (
    build_asset_compatibility_graph,
    build_asset_pool_report,
    load_asset_pool_policy,
    load_asset_vocabularies,
)
from maskfactory.daz.scenes import (
    AppearanceSelectionError,
    load_appearance_selection_policy,
    select_character_appearance,
    select_character_foundation,
    validate_appearance_selection_policy,
    validate_character_appearance_selection,
)

ROOT = Path(__file__).resolve().parents[1]
VOCABULARIES = ROOT / "configs" / "daz" / "asset_vocabularies.yaml"
POOL_POLICY = ROOT / "configs" / "daz" / "asset_pools.yaml"
APPEARANCE_POLICY = ROOT / "configs" / "daz" / "appearance_selection.yaml"

WARDROBE_STATES = (
    "unclothed",
    "underwear_only",
    "swimwear",
    "minimal_clothing",
    "tight_fitted",
    "standard_casual",
    "loose_clothing",
    "layered_clothing",
    "formal",
    "athletic",
    "sleepwear",
    "outerwear",
    "workwear_or_uniform_generic",
    "costume_or_stylized_adult",
)


def _id(index: int) -> str:
    return f"ast_{index:024x}"


def _record(index: int, primary_class: str, **overrides) -> dict:
    record = {
        "asset_id": _id(index),
        "asset_sha256": f"{index:064x}",
        "primary_asset_class": primary_class,
        "identity_status": "unique",
        "mapping_requirement": "none",
        "character_scope": "adult_human",
        "figure_generations": ["genesis_9"],
        "scene_categories": [
            "clothed",
            "partial_clothing",
            "underwear",
            "swimwear",
            "unclothed",
            "neutral",
        ],
        "compatibility_bases": [],
        "required_plugins": [],
        "capabilities": [],
        "facets": {},
        "dependencies": [],
    }
    record.update(overrides)
    return record


def _wardrobe(
    index: int,
    primary_class: str,
    *,
    state: str,
    fit: str,
    layer: str = "base",
    region: str = "full",
    **overrides,
) -> dict:
    return _record(
        index,
        primary_class,
        mapping_requirement="inherited_base",
        facets={
            "wardrobe_state": state,
            "wardrobe_region": region,
            "wardrobe_layer": layer,
            "fit_profile": fit,
            "opacity_class": "opaque",
            "dynamic_behavior": "static",
        },
        **overrides,
    )


def _fixture(
    *, bad_standard_mapping: bool = False, bad_standard_dynamic: bool = False
) -> tuple[dict, dict, dict, dict]:
    vocabularies = load_asset_vocabularies(VOCABULARIES)
    pool_policy = load_asset_pool_policy(POOL_POLICY, vocabularies)
    appearance_policy = load_appearance_selection_policy(APPEARANCE_POLICY)
    base = _record(1, "figure_base")
    preset = _record(2, "character_preset", compatibility_bases=[base["asset_id"]])
    skin = _record(
        3,
        "material_skin",
        compatibility_bases=[base["asset_id"]],
        facets={"tone_band": "tone_3"},
    )
    anatomy_male = _record(
        4,
        "anatomy_geograft",
        mapping_requirement="asset_specific",
        compatibility_bases=[base["asset_id"]],
        facets={"anatomy_configuration": "adult_male_anatomy"},
    )
    anatomy_female = _record(
        5,
        "anatomy_geograft",
        mapping_requirement="asset_specific",
        compatibility_bases=[base["asset_id"]],
        facets={"anatomy_configuration": "adult_female_anatomy"},
    )
    hair = _record(
        6,
        "hair_fitted",
        compatibility_bases=[base["asset_id"]],
        facets={
            "hair_length": "shoulder_length",
            "hair_texture": "curly",
            "hair_construction": "fitted",
            "hair_occlusion": "shoulder",
        },
    )
    wardrobe = [
        _wardrobe(
            10, "wardrobe_underwear", state="underwear_only", fit="fitted", layer="underwear"
        ),
        _wardrobe(11, "wardrobe_swimwear", state="swimwear", fit="fitted"),
        _wardrobe(12, "wardrobe_top", state="minimal_clothing", fit="regular", region="upper"),
        _wardrobe(13, "wardrobe_one_piece", state="tight_fitted", fit="skin_tight"),
        _wardrobe(14, "wardrobe_one_piece", state="standard_casual", fit="regular"),
        _wardrobe(15, "wardrobe_one_piece", state="loose_clothing", fit="loose"),
        _wardrobe(16, "wardrobe_one_piece", state="layered_clothing", fit="regular", layer="base"),
        _wardrobe(17, "wardrobe_outerwear", state="layered_clothing", fit="loose", layer="outer"),
        _wardrobe(18, "wardrobe_one_piece", state="formal", fit="fitted"),
        _wardrobe(19, "wardrobe_one_piece", state="athletic", fit="fitted"),
        _wardrobe(20, "wardrobe_one_piece", state="sleepwear", fit="loose"),
        _wardrobe(21, "wardrobe_one_piece", state="outerwear", fit="regular", layer="base"),
        _wardrobe(22, "wardrobe_outerwear", state="outerwear", fit="loose", layer="outer"),
        _wardrobe(
            23,
            "wardrobe_one_piece",
            state="workwear_or_uniform_generic",
            fit="regular",
        ),
        _wardrobe(
            24,
            "wardrobe_one_piece",
            state="costume_or_stylized_adult",
            fit="fitted",
        ),
    ]
    standard = next(
        record for record in wardrobe if record["facets"]["wardrobe_state"] == "standard_casual"
    )
    if bad_standard_mapping:
        standard["mapping_requirement"] = "none"
    if bad_standard_dynamic:
        standard["facets"]["dynamic_behavior"] = "nondeterministic"
    records = [base, preset, skin, anatomy_male, anatomy_female, hair, *wardrobe]
    graph = build_asset_compatibility_graph(records, vocabularies)
    report = build_asset_pool_report(
        graph,
        pool_policy,
        vocabularies,
        qualified_asset_ids=[record["asset_id"] for record in records],
        qualification_projection_sha256="9" * 64,
    )
    return graph, report, appearance_policy, base


def _foundation(graph: dict, report: dict, state: str) -> dict:
    scene_category = {
        "unclothed": "unclothed",
        "underwear_only": "underwear",
        "swimwear": "swimwear",
        "minimal_clothing": "partial_clothing",
    }.get(state, "clothed")
    return select_character_foundation(
        graph, report, selection_seed=77, scene_category=scene_category
    )


def test_policy_covers_exact_wardrobe_anatomy_hair_and_mapping_contract() -> None:
    policy = load_appearance_selection_policy(APPEARANCE_POLICY)
    assert tuple(policy["wardrobe_states"]) == WARDROBE_STATES
    assert policy["anatomy_configurations"] == [
        "adult_male_anatomy",
        "adult_female_anatomy",
    ]
    assert policy["hair_modes"] == ["none", "required"]
    assert policy["required_anatomy_mapping_requirement"] == "asset_specific"
    assert policy["allowed_dynamic_behaviors"] == ["static", "deterministic_baked"]


@pytest.mark.parametrize("anatomy", ["adult_male_anatomy", "adult_female_anatomy"])
@pytest.mark.parametrize("state", WARDROBE_STATES)
@pytest.mark.parametrize("hair_mode", ["none", "required"])
def test_full_appearance_matrix_selects_exact_configuration_state_and_hair_mode(
    anatomy: str, state: str, hair_mode: str
) -> None:
    graph, report, policy, _base = _fixture()
    foundation = _foundation(graph, report, state)
    selection = select_character_appearance(
        graph,
        report,
        foundation,
        policy,
        selection_seed=100,
        anatomy_configuration=anatomy,
        hair_mode=hair_mode,
        wardrobe_state=state,
    )
    nodes = {node["asset_id"]: node for node in graph["nodes"]}
    assert (
        nodes[selection["selected"]["anatomy_asset_id"]]["facets"]["anatomy_configuration"]
        == anatomy
    )
    assert (selection["selected"]["hair_asset_id"] is not None) == (hair_mode == "required")
    wardrobe = selection["selected"]["wardrobe_items_inner_to_outer"]
    if state == "unclothed":
        assert wardrobe == []
    else:
        assert wardrobe
        assert all(
            nodes[item["asset_id"]]["facets"]["wardrobe_state"] == state for item in wardrobe
        )
    validate_character_appearance_selection(selection, graph, report, foundation, policy)


def test_layered_items_are_ordered_inner_to_outer_and_selection_is_deterministic() -> None:
    graph, report, policy, _base = _fixture()
    foundation = _foundation(graph, report, "layered_clothing")
    first = select_character_appearance(
        graph,
        report,
        foundation,
        policy,
        selection_seed=5,
        anatomy_configuration="adult_female_anatomy",
        hair_mode="required",
        wardrobe_state="layered_clothing",
    )
    second = select_character_appearance(
        graph,
        report,
        foundation,
        policy,
        selection_seed=5,
        anatomy_configuration="adult_female_anatomy",
        hair_mode="required",
        wardrobe_state="layered_clothing",
    )
    assert first == second
    items = first["selected"]["wardrobe_items_inner_to_outer"]
    assert [item["wardrobe_layer"] for item in items] == ["base", "outer"]


def test_unqualified_anatomy_missing_territory_map_and_nondeterministic_cloth_fail_closed() -> None:
    graph, report, policy, _base = _fixture()
    male_id = next(
        node["asset_id"]
        for node in graph["nodes"]
        if node["facets"].get("anatomy_configuration") == "adult_male_anatomy"
    )
    qualified_without_male = [
        asset_id
        for asset_id in report["qualification_projection"]["qualified_asset_ids"]
        if asset_id != male_id
    ]
    vocabularies = load_asset_vocabularies(VOCABULARIES)
    pool_policy = load_asset_pool_policy(POOL_POLICY, vocabularies)
    without_male = build_asset_pool_report(
        graph,
        pool_policy,
        vocabularies,
        qualified_asset_ids=qualified_without_male,
        qualification_projection_sha256="8" * 64,
    )
    foundation_without_male = _foundation(graph, without_male, "standard_casual")
    with pytest.raises(AppearanceSelectionError, match="appearance_anatomy_pool_empty"):
        select_character_appearance(
            graph,
            without_male,
            foundation_without_male,
            policy,
            selection_seed=1,
            anatomy_configuration="adult_male_anatomy",
            hair_mode="none",
            wardrobe_state="standard_casual",
        )

    for fixture_kwargs in (
        {"bad_standard_mapping": True},
        {"bad_standard_dynamic": True},
    ):
        bad_graph, bad_report, bad_policy, _ = _fixture(**fixture_kwargs)
        bad_foundation = _foundation(bad_graph, bad_report, "standard_casual")
        with pytest.raises(AppearanceSelectionError, match="appearance_wardrobe_combination_empty"):
            select_character_appearance(
                bad_graph,
                bad_report,
                bad_foundation,
                bad_policy,
                selection_seed=1,
                anatomy_configuration="adult_female_anatomy",
                hair_mode="none",
                wardrobe_state="standard_casual",
            )


def test_tampered_selection_replay_fails_closed() -> None:
    graph, report, policy, _base = _fixture()
    foundation = _foundation(graph, report, "unclothed")
    selection = select_character_appearance(
        graph,
        report,
        foundation,
        policy,
        selection_seed=5,
        anatomy_configuration="adult_male_anatomy",
        hair_mode="none",
        wardrobe_state="unclothed",
    )
    tampered = deepcopy(selection)
    tampered["selected"]["hair_asset_id"] = _id(6)
    with pytest.raises(AppearanceSelectionError, match="appearance_selection_replay_mismatch"):
        validate_character_appearance_selection(tampered, graph, report, foundation, policy)


def test_policy_rejects_missing_state_or_nondeterministic_behavior() -> None:
    policy = load_appearance_selection_policy(APPEARANCE_POLICY)
    missing = deepcopy(policy)
    missing["wardrobe_states"].pop("unclothed")
    with pytest.raises(AppearanceSelectionError, match="appearance_policy_wardrobe_states_invalid"):
        validate_appearance_selection_policy(missing)

    invalid = deepcopy(policy)
    invalid["allowed_dynamic_behaviors"].append("nondeterministic")
    with pytest.raises(AppearanceSelectionError, match="appearance_policy_dynamic_invalid"):
        validate_appearance_selection_policy(invalid)


def test_appearance_cli_publishes_idempotently(tmp_path: Path) -> None:
    graph, report, _policy, _base = _fixture()
    foundation = _foundation(graph, report, "layered_clothing")
    graph_path = tmp_path / "graph.json"
    report_path = tmp_path / "pools.json"
    foundation_path = tmp_path / "foundation.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    foundation_path.write_text(json.dumps(foundation), encoding="utf-8")
    output = tmp_path / "appearance"
    arguments = [
        "daz",
        "recipes",
        "select-appearance",
        "--graph",
        str(graph_path),
        "--pool-report",
        str(report_path),
        "--foundation-selection",
        str(foundation_path),
        "--selection-seed",
        "5",
        "--anatomy-configuration",
        "adult_female_anatomy",
        "--hair-mode",
        "required",
        "--wardrobe-state",
        "layered_clothing",
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
