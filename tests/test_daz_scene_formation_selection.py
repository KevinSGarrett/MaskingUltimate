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
    SceneFormationSelectionError,
    load_scene_formation_policy,
    select_character_foundation,
    select_scene_formation,
    validate_formation_descriptor_registry,
    validate_scene_formation_policy,
    validate_scene_formation_selection,
)

ROOT = Path(__file__).resolve().parents[1]
VOCABULARIES = ROOT / "configs" / "daz" / "asset_vocabularies.yaml"
POOL_POLICY = ROOT / "configs" / "daz" / "asset_pools.yaml"
FORMATION_POLICY = ROOT / "configs" / "daz" / "scene_formation_selection.yaml"


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


def _blank_descriptor(index: int, descriptor_type: str) -> dict:
    return {
        "descriptor_id": f"dcfd_{descriptor_type}_{index}",
        "asset_id": _id(index),
        "descriptor_type": descriptor_type,
        "lighting_profile": None,
        "environment_family": None,
        "environment_subfamily": None,
        "context_complexity": None,
        "prop_mode": None,
        "prop_role": None,
        "anchor_types": [],
        "stable_object_id": None,
        "environment_restrictions_satisfied": [],
        "forbidden_mutations": [],
        "final_readback_required": True,
    }


def _environment_context(family: str) -> str:
    return {"controlled": "controlled", "indoor": "furnished", "outdoor": "simple"}[family]


def _fixture(*, unqualified_asset: str | None = None) -> tuple[dict, dict, dict, dict, dict]:
    vocabularies = load_asset_vocabularies(VOCABULARIES)
    pool_policy = load_asset_pool_policy(POOL_POLICY, vocabularies)
    policy = load_scene_formation_policy(FORMATION_POLICY)
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
    for profile in policy["lighting_profiles"]:
        records.append(
            _record(
                index,
                "light_preset",
                character_scope="generation_neutral",
                figure_generations=["generation_neutral"],
                facets={"lighting_profile": profile},
            )
        )
        descriptor = _blank_descriptor(index, "light")
        descriptor["lighting_profile"] = profile
        descriptors.append(descriptor)
        index += 1
    for family, subfamilies in policy["environment_families"].items():
        primary_class = {
            "controlled": "backdrop",
            "indoor": "environment_indoor",
            "outdoor": "environment_outdoor",
        }[family]
        for subfamily in subfamilies:
            context = _environment_context(family)
            records.append(
                _record(
                    index,
                    primary_class,
                    character_scope="generation_neutral",
                    figure_generations=["generation_neutral"],
                    facets={"context_complexity": context},
                )
            )
            descriptor = _blank_descriptor(index, "environment")
            descriptor.update(
                {
                    "environment_family": family,
                    "environment_subfamily": subfamily,
                    "context_complexity": context,
                    "environment_restrictions_satisfied": policy["environment_restrictions"],
                }
            )
            descriptors.append(descriptor)
            index += 1
    controlled_subfamily = policy["environment_families"]["controlled"][0]
    for context in policy["context_complexities"]:
        if context == "controlled":
            continue
        records.append(
            _record(
                index,
                "backdrop",
                character_scope="generation_neutral",
                figure_generations=["generation_neutral"],
                facets={"context_complexity": context},
            )
        )
        descriptor = _blank_descriptor(index, "environment")
        descriptor.update(
            {
                "environment_family": "controlled",
                "environment_subfamily": controlled_subfamily,
                "context_complexity": context,
                "environment_restrictions_satisfied": policy["environment_restrictions"],
            }
        )
        descriptors.append(descriptor)
        index += 1
    for mode, primary_class, role, anchor in (
        ("support_surface", "support_surface", "support_surface", "hip_seat"),
        ("handheld_worn", "prop_handheld", "accessory_or_prop", "hand_grip"),
        ("occluder", "prop_occluder", "occluding_object", "foreground_occluder"),
    ):
        records.append(
            _record(
                index,
                primary_class,
                character_scope="generation_neutral",
                figure_generations=["generation_neutral"],
                facets={"occlusion_support_role": role},
            )
        )
        descriptor = _blank_descriptor(index, "prop")
        descriptor.update(
            {
                "prop_mode": mode,
                "prop_role": role,
                "anchor_types": [anchor],
                "stable_object_id": f"object_{index}",
            }
        )
        descriptors.append(descriptor)
        index += 1
    graph = build_asset_compatibility_graph(records, vocabularies)
    qualified = [record["asset_id"] for record in records]
    if unqualified_asset is not None:
        qualified.remove(unqualified_asset)
    report = build_asset_pool_report(
        graph,
        pool_policy,
        vocabularies,
        qualified_asset_ids=qualified,
        qualification_projection_sha256="7" * 64,
    )
    foundation = select_character_foundation(
        graph, report, selection_seed=31, scene_category="clothed"
    )
    registry = {"schema_version": "1.0.0", "assets": descriptors}
    return graph, report, foundation, registry, policy


def _request(**overrides) -> dict:
    request = {
        "selection_seed": 123,
        "person_count": 1,
        "azimuth_bin": "front",
        "elevation_bin": "eye_level",
        "roll_bin": "level",
        "focal_family": "normal",
        "framing_profile": "full_body_margin",
        "aspect_ratio": "1:1",
        "resolution_profile": "pilot_768",
        "depth_of_field_mode": "off",
        "lighting_profile": "front_soft",
        "exposure_profile": "normal",
        "environment_family": "controlled",
        "environment_subfamily": "transparent_solid_neutral",
        "context_complexity": "controlled",
        "prop_mode": "none",
    }
    request.update(overrides)
    return request


def _select(**overrides) -> dict:
    graph, report, foundation, registry, policy = _fixture()
    return select_scene_formation(
        graph, report, foundation, registry, policy, **_request(**overrides)
    )


def test_policy_covers_exact_camera_light_environment_and_prop_axes() -> None:
    policy = load_scene_formation_policy(FORMATION_POLICY)
    validate_scene_formation_policy(policy)
    assert len(policy["camera"]["azimuth_bins"]) == 8
    assert len(policy["camera"]["elevation_bins"]) == 6
    assert len(policy["camera"]["roll_bins"]) == 4
    assert len(policy["camera"]["focal_families"]) == 7
    assert len(policy["camera"]["framing_profiles"]) == 12
    assert len(policy["lighting_profiles"]) == 22
    assert sum(map(len, policy["environment_families"].values())) == 21
    assert policy["prop_modes"] == ["none", "support_surface", "handheld_worn", "occluder"]


@pytest.mark.parametrize(
    "azimuth_bin", load_scene_formation_policy(FORMATION_POLICY)["camera"]["azimuth_bins"]
)
def test_every_azimuth_bin_resolves_inside_declared_range(azimuth_bin: str) -> None:
    selection = _select(azimuth_bin=azimuth_bin)
    camera = selection["selected"]["camera"]
    lower, upper = load_scene_formation_policy(FORMATION_POLICY)["camera"]["azimuth_bins"][
        azimuth_bin
    ]
    assert lower <= camera["azimuth_degrees"] <= upper


@pytest.mark.parametrize(
    "elevation_bin", load_scene_formation_policy(FORMATION_POLICY)["camera"]["elevation_bins"]
)
def test_every_elevation_bin_resolves_inside_declared_range(elevation_bin: str) -> None:
    selection = _select(elevation_bin=elevation_bin)
    value = selection["selected"]["camera"]["elevation_degrees"]
    lower, upper = load_scene_formation_policy(FORMATION_POLICY)["camera"]["elevation_bins"][
        elevation_bin
    ]
    assert lower <= value <= upper


@pytest.mark.parametrize(
    "roll_bin", load_scene_formation_policy(FORMATION_POLICY)["camera"]["roll_bins"]
)
def test_every_roll_bin_resolves_inside_declared_range(roll_bin: str) -> None:
    selection = _select(roll_bin=roll_bin)
    value = selection["selected"]["camera"]["roll_degrees"]
    lower, upper = load_scene_formation_policy(FORMATION_POLICY)["camera"]["roll_bins"][roll_bin]
    assert lower <= value <= upper


@pytest.mark.parametrize(
    "focal_family", load_scene_formation_policy(FORMATION_POLICY)["camera"]["focal_families"]
)
def test_every_focal_family_resolves_projection_and_numeric_contract(focal_family: str) -> None:
    selection = _select(focal_family=focal_family)
    camera = selection["selected"]["camera"]
    if focal_family == "orthographic":
        assert camera["projection_type"] == "orthographic"
        assert camera["focal_length_mm"] is None
        assert 2 <= camera["orthographic_scale"] <= 4
    else:
        lower, upper = load_scene_formation_policy(FORMATION_POLICY)["camera"]["focal_families"][
            focal_family
        ]
        assert camera["projection_type"] == "perspective"
        assert lower <= camera["focal_length_mm"] <= upper


@pytest.mark.parametrize(
    "framing", load_scene_formation_policy(FORMATION_POLICY)["camera"]["framing_profiles"]
)
def test_every_framing_profile_has_consistent_person_count(framing: str) -> None:
    multi = framing in {"multi_person_group_full", "multi_person_mixed_truncation"}
    selection = _select(framing_profile=framing, person_count=2 if multi else 1)
    assert selection["selected"]["camera"]["framing_profile"] == framing


@pytest.mark.parametrize(
    "aspect_ratio", load_scene_formation_policy(FORMATION_POLICY)["camera"]["aspect_ratios"]
)
def test_every_aspect_ratio_produces_exact_full_frame_crop(aspect_ratio: str) -> None:
    camera = _select(aspect_ratio=aspect_ratio)["selected"]["camera"]
    width, height = camera["resolution"]
    assert camera["crop"] == [0, 0, width, height]
    numerator, denominator = map(int, aspect_ratio.split(":"))
    assert abs(width / height - numerator / denominator) < 0.002


@pytest.mark.parametrize(
    "profile", load_scene_formation_policy(FORMATION_POLICY)["camera"]["resolution_profiles"]
)
def test_every_resolution_profile_preserves_declared_short_side(profile: str) -> None:
    policy = load_scene_formation_policy(FORMATION_POLICY)
    camera = _select(resolution_profile=profile, aspect_ratio="16:9")["selected"]["camera"]
    assert min(camera["resolution"]) == policy["camera"]["resolution_profiles"][profile]


@pytest.mark.parametrize(
    "mode", load_scene_formation_policy(FORMATION_POLICY)["camera"]["depth_of_field_modes"]
)
def test_beauty_dof_varies_but_annotation_effects_remain_off(mode: str) -> None:
    camera = _select(depth_of_field_mode=mode)["selected"]["camera"]
    assert camera["depth_of_field"]["enabled"] == (mode != "off")
    assert camera["motion_blur"] == {"mode": "off", "enabled": False}
    assert camera["annotation_camera_effects_off"] is True


@pytest.mark.parametrize(
    "lighting_profile", load_scene_formation_policy(FORMATION_POLICY)["lighting_profiles"]
)
def test_every_lighting_profile_selects_exact_qualified_asset(lighting_profile: str) -> None:
    selection = _select(lighting_profile=lighting_profile)
    assert selection["selected"]["light"]["lighting_profile"] == lighting_profile


@pytest.mark.parametrize(
    "exposure_profile", load_scene_formation_policy(FORMATION_POLICY)["exposure_profiles"]
)
def test_every_exposure_profile_is_recorded_explicitly(exposure_profile: str) -> None:
    assert (
        _select(exposure_profile=exposure_profile)["selected"]["exposure_profile"]
        == exposure_profile
    )


@pytest.mark.parametrize(
    ("family", "subfamily", "context"),
    [
        (family, subfamily, _environment_context(family))
        for family, subfamilies in load_scene_formation_policy(FORMATION_POLICY)[
            "environment_families"
        ].items()
        for subfamily in subfamilies
    ],
)
def test_every_environment_subfamily_selects_restriction_qualified_asset(
    family: str, subfamily: str, context: str
) -> None:
    environment = _select(
        environment_family=family,
        environment_subfamily=subfamily,
        context_complexity=context,
    )["selected"]["environment"]
    assert environment["environment_family"] == family
    assert environment["environment_subfamily"] == subfamily
    assert environment["context_complexity"] == context


@pytest.mark.parametrize(
    "context", load_scene_formation_policy(FORMATION_POLICY)["context_complexities"]
)
def test_every_context_complexity_is_selectable(context: str) -> None:
    environment = _select(context_complexity=context)["selected"]["environment"]
    assert environment["context_complexity"] == context


@pytest.mark.parametrize("prop_mode", ["none", "support_surface", "handheld_worn", "occluder"])
def test_prop_modes_are_explicit_and_require_stable_object_identity(prop_mode: str) -> None:
    selection = _select(prop_mode=prop_mode)
    prop = selection["selected"]["prop"]
    if prop_mode == "none":
        assert prop is None
        assert (
            selection["evidence_requirements"]["prop_contact_and_occlusion_preflight_required"]
            is False
        )
    else:
        assert prop["prop_mode"] == prop_mode
        assert prop["stable_object_id"].startswith("object_")
        assert prop["anchor_types"]
        assert (
            selection["evidence_requirements"]["prop_contact_and_occlusion_preflight_required"]
            is True
        )


def test_same_seed_replays_and_different_seed_changes_continuous_camera() -> None:
    first = _select(selection_seed=100, azimuth_bin="left_profile", focal_family="portrait")
    replay = _select(selection_seed=100, azimuth_bin="left_profile", focal_family="portrait")
    other = _select(selection_seed=101, azimuth_bin="left_profile", focal_family="portrait")
    assert first == replay
    assert first["selected"]["camera"] != other["selected"]["camera"]


def test_environment_restrictions_forbidden_mutation_and_prop_identity_fail_closed() -> None:
    _graph, _report, _foundation, registry, policy = _fixture()
    environment_index = next(
        index
        for index, descriptor in enumerate(registry["assets"])
        if descriptor["descriptor_type"] == "environment"
    )
    invalid = deepcopy(registry)
    invalid["assets"][environment_index]["environment_restrictions_satisfied"].pop()
    with pytest.raises(SceneFormationSelectionError, match="environment_descriptor"):
        validate_formation_descriptor_registry(invalid, policy)
    invalid = deepcopy(registry)
    invalid["assets"][0]["forbidden_mutations"] = ["camera"]
    with pytest.raises(SceneFormationSelectionError, match="identity_invalid"):
        validate_formation_descriptor_registry(invalid, policy)
    prop_index = next(
        index
        for index, descriptor in enumerate(registry["assets"])
        if descriptor["descriptor_type"] == "prop"
    )
    invalid = deepcopy(registry)
    invalid["assets"][prop_index]["stable_object_id"] = None
    with pytest.raises(SceneFormationSelectionError, match="prop_descriptor"):
        validate_formation_descriptor_registry(invalid, policy)


def test_framing_person_count_and_orthographic_scope_fail_closed() -> None:
    graph, report, foundation, registry, policy = _fixture()
    with pytest.raises(SceneFormationSelectionError, match="framing_person_count"):
        select_scene_formation(
            graph,
            report,
            foundation,
            registry,
            policy,
            **_request(person_count=1, framing_profile="multi_person_group_full"),
        )
    with pytest.raises(SceneFormationSelectionError, match="orthographic_scope"):
        select_scene_formation(
            graph,
            report,
            foundation,
            registry,
            policy,
            **_request(focal_family="orthographic", framing_profile="waist_up"),
        )


def test_unqualified_requested_light_never_enters_selection() -> None:
    graph, report, foundation, registry, policy = _fixture()
    light = next(
        descriptor
        for descriptor in registry["assets"]
        if descriptor["descriptor_type"] == "light"
        and descriptor["lighting_profile"] == "front_soft"
    )
    graph, report, foundation, registry, policy = _fixture(unqualified_asset=light["asset_id"])
    with pytest.raises(SceneFormationSelectionError, match="no_qualified_candidate"):
        select_scene_formation(graph, report, foundation, registry, policy, **_request())


def test_selection_tamper_is_rejected_by_exact_replay() -> None:
    graph, report, foundation, registry, policy = _fixture()
    selection = select_scene_formation(graph, report, foundation, registry, policy, **_request())
    tampered = deepcopy(selection)
    tampered["selected"]["camera"]["azimuth_degrees"] += 1
    with pytest.raises(SceneFormationSelectionError, match="replay_mismatch"):
        validate_scene_formation_selection(tampered, graph, report, foundation, registry, policy)


def test_cli_selects_and_publishes_idempotently(tmp_path: Path) -> None:
    graph, report, foundation, registry, _policy = _fixture()
    paths = {}
    for name, document in (
        ("graph", graph),
        ("pools", report),
        ("foundation", foundation),
        ("formation", registry),
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[name] = path
    output = tmp_path / "out"
    request = _request(prop_mode="support_surface")
    arguments = [
        "daz",
        "recipes",
        "select-formation",
        "--graph",
        str(paths["graph"]),
        "--pool-report",
        str(paths["pools"]),
        "--foundation-selection",
        str(paths["foundation"]),
        "--descriptor-registry",
        str(paths["formation"]),
    ]
    for option, value in request.items():
        arguments.extend(["--" + option.replace("_", "-"), str(value)])
    arguments.extend(["--policy", str(FORMATION_POLICY), "--output", str(output)])
    runner = CliRunner()
    first = runner.invoke(main, arguments)
    assert first.exit_code == 0, first.output
    assert json.loads(first.output)["data"]["publication"]["published"] is True
    replay = runner.invoke(main, arguments)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
