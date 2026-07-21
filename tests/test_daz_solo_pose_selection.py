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
    SoloPoseSelectionError,
    compose_partial_pose_descriptors,
    load_solo_pose_policy,
    select_character_foundation,
    select_solo_pose,
    validate_pose_descriptor_registry,
    validate_solo_pose_policy,
    validate_solo_pose_selection,
)

ROOT = Path(__file__).resolve().parents[1]
VOCABULARIES = ROOT / "configs" / "daz" / "asset_vocabularies.yaml"
POOL_POLICY = ROOT / "configs" / "daz" / "asset_pools.yaml"
POSE_POLICY = ROOT / "configs" / "daz" / "solo_pose_selection.yaml"


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


def _support(family: str) -> tuple[str, list[str]]:
    return {
        "neutral_calibration": ("none", []),
        "locomotion": ("standing_feet", ["left_foot", "right_foot"]),
        "seated": ("seat", ["pelvis_support"]),
        "crouching_kneeling": ("standing_feet", ["left_foot", "right_foot"]),
        "lying_reclining": ("floor_body", ["torso_support"]),
        "athletic_dance_flexibility": ("standing_feet", ["left_foot", "right_foot"]),
    }[family]


def _descriptor(asset_id: str, family: str, subfamily: str) -> dict:
    support_mode, contacts = _support(family)
    bones = ["left_upper_arm", "pelvis", "right_upper_arm"]
    rotations = {bone: {"bend": 5.0, "twist": -3.0, "side_side": 2.0} for bone in bones}
    limits = {
        bone: {
            "bend": [-90.0, 90.0],
            "twist": [-60.0, 60.0],
            "side_side": [-45.0, 45.0],
        }
        for bone in bones
    }
    return {
        "descriptor_id": f"dcpd_{family}_{subfamily}",
        "asset_id": asset_id,
        "figure_generation": "genesis_9",
        "primary_asset_class": "pose_full_body",
        "pose_family": family,
        "pose_subfamily": subfamily,
        "root_transform_policy": "preserve_root",
        "root_transform": {
            "translation_cm": [0.0, 0.0, 0.0],
            "rotation_deg": [0.0, 0.0, 0.0],
        },
        "owned_bones": bones,
        "bone_rotations_deg": rotations,
        "joint_limits_deg": limits,
        "support_mode": support_mode,
        "support_contacts": contacts,
        "visibility_expectation": {"hands": "both_visible", "feet": "both_visible"},
        "self_occlusion_tags": [],
        "asymmetry_tag": "symmetric",
        "camera_view_suitability": ["back", "front"],
        "hand_foot_articulation_valid": True,
        "intersection_score": 0.01,
        "conversion": {
            "required": False,
            "dependency_asset_ids": [],
            "validated": True,
        },
        "source_readback_required": True,
    }


def _fixture(*, exclude_pose_asset: str | None = None) -> tuple[dict, dict, dict, dict, dict]:
    vocabularies = load_asset_vocabularies(VOCABULARIES)
    pool_policy = load_asset_pool_policy(POOL_POLICY, vocabularies)
    pose_policy = load_solo_pose_policy(POSE_POLICY)
    base = _record(1, "figure_base")
    preset = _record(2, "character_preset", compatibility_bases=[base["asset_id"]])
    skin = _record(
        3,
        "material_skin",
        compatibility_bases=[base["asset_id"]],
        facets={"tone_band": "tone_3"},
    )
    records = [base, preset, skin]
    descriptors = []
    index = 100
    for family, subfamilies in pose_policy["taxonomy"].items():
        for subfamily in subfamilies:
            asset = _record(
                index,
                "pose_full_body",
                compatibility_bases=[base["asset_id"]],
                facets={"pose_taxonomy": family},
            )
            records.append(asset)
            descriptors.append(_descriptor(asset["asset_id"], family, subfamily))
            index += 1
    graph = build_asset_compatibility_graph(records, vocabularies)
    qualified = [record["asset_id"] for record in records]
    if exclude_pose_asset is not None:
        qualified.remove(exclude_pose_asset)
    report = build_asset_pool_report(
        graph,
        pool_policy,
        vocabularies,
        qualified_asset_ids=qualified,
        qualification_projection_sha256="8" * 64,
    )
    foundation = select_character_foundation(
        graph, report, selection_seed=17, scene_category="clothed"
    )
    registry = {"schema_version": "1.0.0", "poses": descriptors}
    return graph, report, foundation, registry, pose_policy


def _all_taxonomy_cases() -> list[tuple[str, str]]:
    policy = load_solo_pose_policy(POSE_POLICY)
    return [
        (family, subfamily)
        for family, subfamilies in policy["taxonomy"].items()
        for subfamily in subfamilies
    ]


def test_policy_is_closed_and_covers_all_six_blueprint_pose_families() -> None:
    policy = load_solo_pose_policy(POSE_POLICY)
    validate_solo_pose_policy(policy)
    assert tuple(policy["taxonomy"]) == (
        "neutral_calibration",
        "locomotion",
        "seated",
        "crouching_kneeling",
        "lying_reclining",
        "athletic_dance_flexibility",
    )
    assert sum(map(len, policy["taxonomy"].values())) == 49
    assert policy["joint_constraints"]["limit_source"] == "daz_runtime_property_limits"
    assert policy["joint_constraints"]["final_daz_readback_required"] is True


@pytest.mark.parametrize(("family", "subfamily"), _all_taxonomy_cases())
def test_every_pose_subfamily_selects_a_qualified_constrained_solo_fixture(
    family: str, subfamily: str
) -> None:
    graph, report, foundation, registry, policy = _fixture()
    selection = select_solo_pose(
        graph,
        report,
        foundation,
        registry,
        policy,
        selection_seed=991,
        pose_family=family,
        pose_subfamily=subfamily,
    )
    assert selection["selected"]["pose_family"] == family
    assert selection["selected"]["pose_subfamily"] == subfamily
    assert selection["selected"]["joint_metrics"]["passed"] is True
    assert selection["selected"]["joint_metrics"]["axis_value_count"] == 9
    assert selection["compatibility_evidence"]["solo_only"] is True
    validate_solo_pose_selection(selection, graph, report, foundation, registry, policy)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda d: d["bone_rotations_deg"]["pelvis"].__setitem__("bend", 90.0), "Q-POSE-001"),
        (
            lambda d: d["bone_rotations_deg"]["pelvis"].__setitem__("bend", float("nan")),
            "Q-POSE-002",
        ),
        (lambda d: d["root_transform"]["translation_cm"].__setitem__(0, 1.0), "Q-POSE-005"),
        (lambda d: d.__setitem__("hand_foot_articulation_valid", False), "Q-POSE-006"),
        (lambda d: d.__setitem__("intersection_score", 0.06), "Q-POSE-003"),
        (lambda d: d["conversion"].update({"required": True, "validated": False}), "Q-POSE-007"),
    ],
)
def test_joint_root_articulation_intersection_and_conversion_fail_closed(
    mutation, reason: str
) -> None:
    _graph, _report, _foundation, registry, policy = _fixture()
    invalid = deepcopy(registry)
    mutation(invalid["poses"][0])
    with pytest.raises(SoloPoseSelectionError, match=reason):
        validate_pose_descriptor_registry(invalid, policy)


def test_support_visibility_occlusion_and_readback_vocabularies_fail_closed() -> None:
    _graph, _report, _foundation, registry, policy = _fixture()
    invalid = deepcopy(registry)
    invalid["poses"][0]["self_occlusion_tags"] = ["invented_occlusion"]
    with pytest.raises(SoloPoseSelectionError, match="occlusion"):
        validate_pose_descriptor_registry(invalid, policy)
    invalid = deepcopy(registry)
    invalid["poses"][0]["source_readback_required"] = False
    with pytest.raises(SoloPoseSelectionError, match="readback"):
        validate_pose_descriptor_registry(invalid, policy)


def test_unqualified_requested_pose_never_enters_selection() -> None:
    graph, _report, _foundation, registry, policy = _fixture()
    first = registry["poses"][0]
    graph, report, foundation, registry, policy = _fixture(exclude_pose_asset=first["asset_id"])
    with pytest.raises(SoloPoseSelectionError, match="no_qualified_candidate"):
        select_solo_pose(
            graph,
            report,
            foundation,
            registry,
            policy,
            selection_seed=1,
            pose_family=first["pose_family"],
            pose_subfamily=first["pose_subfamily"],
        )


def _partial(
    descriptor: dict, *, descriptor_id: str, asset_class: str, bone: str, bend: float
) -> dict:
    result = deepcopy(descriptor)
    result["descriptor_id"] = descriptor_id
    result["primary_asset_class"] = asset_class
    result["owned_bones"] = [bone]
    result["bone_rotations_deg"] = {bone: {"bend": bend, "twist": 0.0, "side_side": 0.0}}
    result["joint_limits_deg"] = {
        bone: {
            "bend": [-90.0, 90.0],
            "twist": [-60.0, 60.0],
            "side_side": [-45.0, 45.0],
        }
    }
    return result


def test_partial_pose_composition_is_deterministic_and_disjoint() -> None:
    _graph, _report, _foundation, registry, policy = _fixture()
    source = registry["poses"][0]
    upper = _partial(
        source,
        descriptor_id="dcpd_partial_upper_fixture",
        asset_class="pose_partial_upper",
        bone="left_upper_arm",
        bend=20.0,
    )
    lower = _partial(
        source,
        descriptor_id="dcpd_partial_lower_fixture",
        asset_class="pose_partial_lower",
        bone="left_thigh",
        bend=-15.0,
    )
    first = compose_partial_pose_descriptors([(upper, 10), (lower, 20)], policy)
    replay = compose_partial_pose_descriptors([(lower, 20), (upper, 10)], policy)
    assert first == replay
    assert set(first["bone_rotations_deg"]) == {"left_upper_arm", "left_thigh"}


def test_partial_pose_conflict_requires_declared_priority_and_higher_priority_wins() -> None:
    _graph, _report, _foundation, registry, policy = _fixture()
    source = registry["poses"][0]
    one = _partial(
        source,
        descriptor_id="dcpd_partial_one",
        asset_class="pose_partial_upper",
        bone="left_upper_arm",
        bend=10.0,
    )
    two = _partial(
        source,
        descriptor_id="dcpd_partial_two",
        asset_class="pose_partial_upper",
        bone="left_upper_arm",
        bend=30.0,
    )
    with pytest.raises(SoloPoseSelectionError, match="ownership_conflict"):
        compose_partial_pose_descriptors([(one, 10), (two, 10)], policy)
    composed = compose_partial_pose_descriptors([(one, 10), (two, 20)], policy)
    assert composed["bone_rotations_deg"]["left_upper_arm"]["bend"] == 30.0


def test_selection_tamper_is_rejected_by_exact_replay() -> None:
    graph, report, foundation, registry, policy = _fixture()
    selection = select_solo_pose(
        graph,
        report,
        foundation,
        registry,
        policy,
        selection_seed=4,
        pose_family="seated",
        pose_subfamily="upright_chair",
    )
    tampered = deepcopy(selection)
    tampered["selected"]["bone_rotations_deg"]["pelvis"]["bend"] += 1
    with pytest.raises(SoloPoseSelectionError, match="replay_mismatch"):
        validate_solo_pose_selection(tampered, graph, report, foundation, registry, policy)


def test_cli_selects_and_publishes_idempotently(tmp_path: Path) -> None:
    graph, report, foundation, registry, _policy = _fixture()
    paths = {}
    for name, document in (
        ("graph", graph),
        ("pools", report),
        ("foundation", foundation),
        ("poses", registry),
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[name] = path
    output = tmp_path / "out"
    arguments = [
        "daz",
        "recipes",
        "select-solo-pose",
        "--graph",
        str(paths["graph"]),
        "--pool-report",
        str(paths["pools"]),
        "--foundation-selection",
        str(paths["foundation"]),
        "--descriptor-registry",
        str(paths["poses"]),
        "--selection-seed",
        "12",
        "--pose-family",
        "locomotion",
        "--pose-subfamily",
        "walking",
        "--policy",
        str(POSE_POLICY),
        "--output",
        str(output),
    ]
    runner = CliRunner()
    first = runner.invoke(main, arguments)
    assert first.exit_code == 0, first.output
    assert json.loads(first.output)["data"]["publication"]["published"] is True
    replay = runner.invoke(main, arguments)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
