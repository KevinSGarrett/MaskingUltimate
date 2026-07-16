from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.scene_validators import (
    StrictSceneValidationError,
    load_strict_scene_validation_policy,
    validate_assembly_layer,
    validate_geometry_layer,
    validate_recipe_layer,
    validate_strict_scene_validation_policy,
)
from maskfactory.daz.scenes import seal_resolved_scene_recipe
from maskfactory.daz.validation_registry import load_validation_registry
from test_daz_scene_recipe import _draft

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "daz" / "strict_scene_validators.yaml"
REGISTRY_PATH = ROOT / "configs" / "daz" / "validation_registry.yaml"


def _policy() -> dict:
    return load_strict_scene_validation_policy(POLICY_PATH)


def _registry() -> dict:
    return load_validation_registry(REGISTRY_PATH)


def _recipe() -> dict:
    draft = _draft()
    draft["characters"][0]["pose_adjustments"] = {"hip": {"bend": 0.0}}
    return seal_resolved_scene_recipe(draft)


def _character_assets(character: dict) -> set[str]:
    values = {
        character["figure_asset_id"],
        character["character_preset_asset_id"],
        character["skin_material_asset_id"],
        character["hair_asset_id"],
        character["pose_asset_id"],
        *character["anatomy_asset_ids"],
        *character["wardrobe_asset_ids"],
    }
    return {value for value in values if value is not None}


def _authority(recipe: dict) -> dict:
    figure = recipe["characters"][0]["figure_asset_id"]
    assets = _character_assets(recipe["characters"][0]) | {recipe["environment"]["asset_id"]}
    return {
        "schema_version": "1.0.0",
        "registry_snapshot_id": recipe["registry_snapshot_id"],
        "ontology_snapshots": [deepcopy(recipe["ontology"])],
        "render_profile_ids": [recipe["render_profile_id"]],
        "asset_records": [
            {
                "asset_id": asset_id,
                "resolved": True,
                "qualified": True,
                "compatible_figure_asset_ids": [figure] if asset_id != figure else [],
            }
            for asset_id in sorted(assets)
        ],
        "mapping_bundle_records": [
            {
                "mapping_bundle_id": mapping_id,
                "resolved": True,
                "asset_ids": sorted(_character_assets(recipe["characters"][0])),
            }
            for mapping_id in recipe["characters"][0]["mapping_bundle_ids"]
        ],
        "numeric_ranges": [
            *[
                {"key": f"c0:morph:{uri}", "minimum": -1.0, "maximum": 1.0}
                for uri in sorted(recipe["characters"][0]["morph_values"])
            ],
            {"key": "c0:pose/hip/bend", "minimum": -90.0, "maximum": 90.0},
        ],
        "resource_estimate": {"storage_gib": 1.0, "gpu_vram_gib": 8.0},
    }


def _expected_assets(recipe: dict) -> dict[str, str]:
    character = recipe["characters"][0]
    result = {
        "c0:figure": character["figure_asset_id"],
        "c0:character_preset": character["character_preset_asset_id"],
        "c0:skin_material": character["skin_material_asset_id"],
        "c0:hair": character["hair_asset_id"],
        "c0:pose": character["pose_asset_id"],
        "scene:environment": recipe["environment"]["asset_id"],
    }
    result.update(
        {
            f"c0:anatomy:{index:02d}": asset_id
            for index, asset_id in enumerate(character["anatomy_asset_ids"])
        }
    )
    result.update(
        {
            f"c0:wardrobe:{index:02d}": asset_id
            for index, asset_id in enumerate(character["wardrobe_asset_ids"])
        }
    )
    return dict(sorted(result.items()))


def _assembly(recipe: dict) -> dict:
    assets = _expected_assets(recipe)
    identity = [
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    ]
    nodes = [f"node_{index:02d}" for index in range(len(assets))]
    return {
        "schema_version": "1.0.0",
        "scene_id": recipe["scene_id"],
        "recipe_sha256": recipe["recipe_sha256"],
        "default_scene_empty_before_load": True,
        "expected_node_ids": nodes,
        "observed_renderable_node_ids": deepcopy(nodes),
        "asset_readbacks": [
            {
                "key": key,
                "expected_asset_id": asset_id,
                "observed_asset_id": asset_id,
                "count": 1,
            }
            for key, asset_id in assets.items()
        ],
        "property_readbacks": [
            {
                "key": f"c0:morph:{uri}",
                "requested": value,
                "observed": value,
                "minimum": -1.0,
                "maximum": 1.0,
            }
            for uri, value in sorted(recipe["characters"][0]["morph_values"].items())
        ],
        "joint_readbacks": [
            {
                "key": "c0:pose/hip/bend",
                "requested": 0.0,
                "observed": 0.0,
                "minimum": -90.0,
                "maximum": 90.0,
            }
        ],
        "controller_side_effects": [{"uri": "prop://body/corrective", "declared": True}],
        "unresolved_textures": [],
        "world_transforms": {node: deepcopy(identity) for node in nodes},
        "character_transform_readbacks": [
            {
                "construction_id": "c0",
                "requested": deepcopy(recipe["characters"][0]["world_transform"]),
                "observed": deepcopy(recipe["characters"][0]["world_transform"]),
            }
        ],
        "camera_readback": deepcopy(recipe["camera"]),
        "figure_scales": [1.0],
        "world_bounds": [{"minimum_cm": [-50.0, 0.0, -30.0], "maximum_cm": [50.0, 190.0, 30.0]}],
        "support_contacts_plausible": True,
        "camera_sees_intended_people": True,
        "visible_person_count": 1,
        "p_index_prominence": [{"construction_id": "c0", "p_index": 0, "prominence": 0.42}],
        "runtime_messages": [],
    }


def _geometry(recipe: dict) -> dict:
    return {
        "schema_version": "1.0.0",
        "scene_id": recipe["scene_id"],
        "recipe_sha256": recipe["recipe_sha256"],
        "meshes": [
            {
                "node_id": "node_figure",
                "expected_topology_sha256": "a" * 64,
                "observed_topology_sha256": "a" * 64,
                "subdivision_level": 2,
                "smoothing_mode": "subdivision",
                "expected_facet_count": 1000,
                "observed_facet_count": 1000,
                "expected_material_groups": ["skin"],
                "observed_material_groups": ["skin"],
                "vertex_count": 1000,
                "scanned_vertex_count": 1000,
                "nonfinite_vertex_count": 0,
                "topology_modifiers": ["subdivision"],
            }
        ],
        "collisions": [],
        "framing": [
            {
                "construction_id": "c0",
                "visible": True,
                "visible_area_fraction": 0.42,
                "off_frame_fraction": 0.0,
                "camera_clipped": False,
                "visible_regions": ["head", "torso", "left_foot", "right_foot"],
                "required_regions": ["head", "torso"],
            }
        ],
        "support_alignment_plausible": True,
    }


def _collision(
    *,
    pair_id: str = "body:body",
    category: str = "self_body",
    depth: float = 0.0,
    volume: float = 0.0,
    intended: bool = False,
    narrow_phase: bool = True,
) -> dict:
    return {
        "pair_id": pair_id,
        "category": category,
        "maximum_depth_mm": depth,
        "penetration_volume_cc": volume,
        "intended_contact": intended,
        "visible": True,
        "broad_phase_overlap": True,
        "narrow_phase_ran": narrow_phase,
    }


def _v2(recipe: dict, authority: dict) -> dict:
    return validate_recipe_layer(
        recipe,
        authority,
        policy=_policy(),
        registry=_registry(),
        evidence_paths=["fixtures/recipe.json", "fixtures/authority.json"],
    )


def _v3(recipe: dict, observation: dict) -> dict:
    return validate_assembly_layer(
        recipe,
        observation,
        policy=_policy(),
        registry=_registry(),
        evidence_paths=["fixtures/recipe.json", "fixtures/assembly.json"],
    )


def _v4(recipe: dict, observation: dict) -> dict:
    return validate_geometry_layer(
        recipe,
        observation,
        policy=_policy(),
        registry=_registry(),
        evidence_paths=["fixtures/recipe.json", "fixtures/geometry.json"],
    )


def test_policy_and_all_three_positive_layers_are_closed_and_normalized() -> None:
    policy = _policy()
    validate_strict_scene_validation_policy(policy)
    recipe = _recipe()
    results = [
        _v2(recipe, _authority(recipe)),
        _v3(recipe, _assembly(recipe)),
        _v4(recipe, _geometry(recipe)),
    ]
    assert [(row["validator_id"], row["status"], row["reason_code"]) for row in results] == [
        ("DAZ-V2-001", "pass", "RECIPE_VALID"),
        ("DAZ-V3-001", "pass", "ASSEMBLY_VALID"),
        ("DAZ-V4-001", "pass", "GEOMETRY_VALID"),
    ]
    assert all(row["metric"] == "defect_count" and row["expected"]["value"] == 0 for row in results)


@pytest.mark.parametrize(
    ("defect", "reason"),
    [
        ("nondeterministic", "RECIPE_NONDETERMINISTIC"),
        ("asset_unresolved", "RECIPE_UNRESOLVABLE"),
        ("mapping_unresolved", "RECIPE_UNRESOLVABLE"),
        ("ontology_unknown", "RECIPE_UNRESOLVABLE"),
        ("profile_unknown", "RECIPE_UNRESOLVABLE"),
        ("configuration", "RECIPE_RANGE_INVALID"),
        ("numeric_range", "RECIPE_RANGE_INVALID"),
        ("resource", "RECIPE_RANGE_INVALID"),
    ],
)
def test_recipe_seeded_defects_fail(defect: str, reason: str) -> None:
    recipe = _recipe()
    authority = _authority(recipe)
    if defect == "nondeterministic":
        recipe["named_random_streams"]["camera"] += 1
    elif defect == "asset_unresolved":
        authority["asset_records"][0]["resolved"] = False
    elif defect == "mapping_unresolved":
        authority["mapping_bundle_records"][0]["resolved"] = False
    elif defect == "ontology_unknown":
        authority["ontology_snapshots"] = []
    elif defect == "profile_unknown":
        authority["render_profile_ids"] = ["other_profile"]
    elif defect == "configuration":
        draft = _draft()
        draft["characters"][0]["pose_adjustments"] = {"hip": {"bend": 0.0}}
        draft["relationship_template"] = {"type": "contact", "participants": ["c0"]}
        recipe = seal_resolved_scene_recipe(draft)
        authority = _authority(recipe)
    elif defect == "numeric_range":
        authority["numeric_ranges"][0]["maximum"] = 0.0
    else:
        authority["resource_estimate"]["gpu_vram_gib"] = 25.0
    result = _v2(recipe, authority)
    assert result["status"] == "fail"
    assert result["reason_code"] == reason


def test_recipe_near_resource_limit_is_warning_not_pass() -> None:
    recipe = _recipe()
    authority = _authority(recipe)
    authority["resource_estimate"]["gpu_vram_gib"] = 21.0
    result = _v2(recipe, authority)
    assert (result["status"], result["reason_code"]) == ("warn", "RECIPE_COST_WARNING")


@pytest.mark.parametrize(
    ("defect", "reason"),
    [
        ("default_scene", "ASSEMBLY_NODE_MISMATCH"),
        ("node_set", "ASSEMBLY_NODE_MISMATCH"),
        ("asset_count", "ASSEMBLY_NODE_MISMATCH"),
        ("texture", "ASSEMBLY_NODE_MISMATCH"),
        ("transform", "ASSEMBLY_TRANSFORM_INVALID"),
        ("transform_node_set", "ASSEMBLY_TRANSFORM_INVALID"),
        ("character_transform", "ASSEMBLY_TRANSFORM_INVALID"),
        ("camera_readback", "ASSEMBLY_TRANSFORM_INVALID"),
        ("scale", "ASSEMBLY_TRANSFORM_INVALID"),
        ("world_bounds", "ASSEMBLY_TRANSFORM_INVALID"),
        ("property", "ASSEMBLY_FIT_INVALID"),
        ("property_missing", "ASSEMBLY_FIT_INVALID"),
        ("joint", "ASSEMBLY_FIT_INVALID"),
        ("joint_missing", "ASSEMBLY_FIT_INVALID"),
        ("side_effect", "ASSEMBLY_FIT_INVALID"),
        ("support", "ASSEMBLY_FIT_INVALID"),
        ("camera_visibility", "ASSEMBLY_FRAMING_INVALID"),
        ("visible_count", "ASSEMBLY_FRAMING_INVALID"),
        ("runtime_error", "ASSEMBLY_NODE_MISMATCH"),
    ],
)
def test_assembly_seeded_defects_fail(defect: str, reason: str) -> None:
    recipe = _recipe()
    observation = _assembly(recipe)
    if defect == "default_scene":
        observation["default_scene_empty_before_load"] = False
    elif defect == "node_set":
        observation["observed_renderable_node_ids"].pop()
    elif defect == "asset_count":
        observation["asset_readbacks"][0]["count"] = 2
    elif defect == "texture":
        observation["unresolved_textures"] = ["missing.png"]
    elif defect == "transform":
        next(iter(observation["world_transforms"].values()))[0] = float("nan")
    elif defect == "transform_node_set":
        observation["world_transforms"].pop(next(iter(observation["world_transforms"])))
    elif defect == "character_transform":
        observation["character_transform_readbacks"][0]["observed"]["scale"] = 1.1
    elif defect == "camera_readback":
        observation["camera_readback"]["roll_deg"] = 1.0
    elif defect == "scale":
        observation["figure_scales"][0] = 3.0
    elif defect == "world_bounds":
        observation["world_bounds"][0]["minimum_cm"][0] = 200000.0
    elif defect == "property":
        observation["property_readbacks"][0]["observed"] = 0.5
    elif defect == "property_missing":
        observation["property_readbacks"].pop()
    elif defect == "joint":
        observation["joint_readbacks"][0]["observed"] = 5.0
    elif defect == "joint_missing":
        observation["joint_readbacks"].pop()
    elif defect == "side_effect":
        observation["controller_side_effects"][0]["declared"] = False
    elif defect == "support":
        observation["support_contacts_plausible"] = False
    elif defect == "camera_visibility":
        observation["camera_sees_intended_people"] = False
    elif defect == "visible_count":
        observation["visible_person_count"] = 0
    else:
        observation["runtime_messages"] = [{"severity": "error", "code": "DAZ_RUNTIME_ERROR"}]
    result = _v3(recipe, observation)
    assert (result["status"], result["reason_code"]) == ("fail", reason)


def test_accepted_assembly_runtime_warning_remains_warning() -> None:
    recipe = _recipe()
    observation = _assembly(recipe)
    observation["runtime_messages"] = [{"severity": "warning", "code": "AUTO_FOLLOW_APPLIED"}]
    result = _v3(recipe, observation)
    assert (result["status"], result["reason_code"]) == ("warn", "ASSEMBLY_RUNTIME_WARNING")


@pytest.mark.parametrize(
    ("defect", "reason"),
    [
        ("topology_hash", "GEOMETRY_TOPOLOGY_MISMATCH"),
        ("subdivision", "GEOMETRY_TOPOLOGY_MISMATCH"),
        ("facet", "GEOMETRY_TOPOLOGY_MISMATCH"),
        ("material", "GEOMETRY_TOPOLOGY_MISMATCH"),
        ("modifier", "GEOMETRY_TOPOLOGY_MISMATCH"),
        ("nonfinite", "GEOMETRY_NONFINITE"),
        ("vertex_scan_incomplete", "GEOMETRY_NONFINITE"),
        ("penetration", "GEOMETRY_PENETRATION_EXCESS"),
        ("narrow_phase_missing", "GEOMETRY_PENETRATION_EXCESS"),
        ("person_set", "GEOMETRY_VISIBILITY_INVALID"),
        ("visibility", "GEOMETRY_VISIBILITY_INVALID"),
        ("off_frame", "GEOMETRY_VISIBILITY_INVALID"),
        ("camera_clip", "GEOMETRY_VISIBILITY_INVALID"),
        ("required_region", "GEOMETRY_VISIBILITY_INVALID"),
        ("support", "GEOMETRY_VISIBILITY_INVALID"),
    ],
)
def test_geometry_seeded_defects_fail(defect: str, reason: str) -> None:
    recipe = _recipe()
    observation = _geometry(recipe)
    mesh = observation["meshes"][0]
    framing = observation["framing"][0]
    if defect == "topology_hash":
        mesh["observed_topology_sha256"] = "b" * 64
    elif defect == "subdivision":
        mesh["subdivision_level"] = 4
    elif defect == "facet":
        mesh["observed_facet_count"] += 1
    elif defect == "material":
        mesh["observed_material_groups"] = ["wrong"]
    elif defect == "modifier":
        mesh["topology_modifiers"] = ["unrecognized"]
    elif defect == "nonfinite":
        mesh["nonfinite_vertex_count"] = 1
    elif defect == "vertex_scan_incomplete":
        mesh["scanned_vertex_count"] -= 1
    elif defect == "penetration":
        observation["collisions"] = [_collision(depth=5.0, volume=2.0)]
    elif defect == "narrow_phase_missing":
        observation["collisions"] = [_collision(narrow_phase=False)]
    elif defect == "person_set":
        framing["construction_id"] = "c1"
    elif defect == "visibility":
        framing["visible"] = False
    elif defect == "off_frame":
        framing["off_frame_fraction"] = 1.0
    elif defect == "camera_clip":
        framing["camera_clipped"] = True
    elif defect == "required_region":
        framing["required_regions"] = ["head", "left_hand"]
    else:
        observation["support_alignment_plausible"] = False
    result = _v4(recipe, observation)
    assert (result["status"], result["reason_code"]) == ("fail", reason)


def test_tolerated_intentional_contact_remains_warning() -> None:
    recipe = _recipe()
    observation = _geometry(recipe)
    observation["collisions"] = [
        _collision(
            pair_id="hand:prop",
            category="person_prop_support",
            depth=1.0,
            volume=0.25,
            intended=True,
        )
    ]
    result = _v4(recipe, observation)
    assert (result["status"], result["reason_code"]) == ("warn", "GEOMETRY_TOLERATED_CONTACT")


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p.__setitem__("policy_version", "2.0.0"), "policy_identity"),
        (lambda p: p["recipe"]["configuration_matrix"]["1"].append("contact"), "recipe_policy"),
        (lambda p: p["assembly"]["figure_scale_range"].reverse(), "assembly_policy"),
        (lambda p: p["geometry"]["allowed_subdivision_levels"].append(4), "geometry_policy"),
    ],
)
def test_policy_drift_fails_closed(mutation, reason: str) -> None:
    policy = _policy()
    mutation(policy)
    with pytest.raises(StrictSceneValidationError, match=f"strict_validator_{reason}_invalid"):
        validate_strict_scene_validation_policy(policy)


def test_unknown_observation_fields_and_cross_recipe_lineage_fail_closed() -> None:
    recipe = _recipe()
    assembly = _assembly(recipe)
    assembly["unknown"] = True
    with pytest.raises(StrictSceneValidationError, match="assembly_observation_fields_invalid"):
        _v3(recipe, assembly)
    geometry = _geometry(recipe)
    geometry["recipe_sha256"] = "0" * 64
    with pytest.raises(StrictSceneValidationError, match="geometry_lineage_invalid"):
        _v4(recipe, geometry)


def test_cli_runs_v2_v4_and_publishes_idempotent_normalized_set(tmp_path: Path) -> None:
    recipe = _recipe()
    documents = {
        "recipe": recipe,
        "authority": _authority(recipe),
        "assembly": _assembly(recipe),
        "geometry": _geometry(recipe),
    }
    paths = {}
    for name, document in documents.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[name] = path
    output = tmp_path / "reports"
    arguments = [
        "daz",
        "recipes",
        "validate-construction",
        "--recipe",
        str(paths["recipe"]),
        "--recipe-authority",
        str(paths["authority"]),
        "--assembly-observation",
        str(paths["assembly"]),
        "--geometry-observation",
        str(paths["geometry"]),
        "--policy",
        str(POLICY_PATH),
        "--registry",
        str(REGISTRY_PATH),
        "--output",
        str(output),
    ]
    runner = CliRunner()
    first = runner.invoke(main, arguments)
    assert first.exit_code == 0, first.output
    payload = json.loads(first.output)
    assert payload["reason"] == "daz_construction_valid"
    assert payload["data"]["summary"]["required_count"] == 3
    assert [row["validator_id"] for row in payload["data"]["results"]] == [
        "DAZ-V2-001",
        "DAZ-V3-001",
        "DAZ-V4-001",
    ]
    for row in payload["data"]["results"]:
        assert all((output / relative).is_file() for relative in row["evidence_paths"])
    replay = runner.invoke(main, arguments)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False


def test_cli_warning_cannot_satisfy_required_layer(tmp_path: Path) -> None:
    recipe = _recipe()
    authority = _authority(recipe)
    authority["resource_estimate"]["gpu_vram_gib"] = 21.0
    documents = {
        "recipe": recipe,
        "authority": authority,
        "assembly": _assembly(recipe),
        "geometry": _geometry(recipe),
    }
    paths = {}
    for name, document in documents.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[name] = path
    result = CliRunner().invoke(
        main,
        [
            "daz",
            "recipes",
            "validate-construction",
            "--recipe",
            str(paths["recipe"]),
            "--recipe-authority",
            str(paths["authority"]),
            "--assembly-observation",
            str(paths["assembly"]),
            "--geometry-observation",
            str(paths["geometry"]),
            "--policy",
            str(POLICY_PATH),
            "--registry",
            str(REGISTRY_PATH),
            "--output",
            str(tmp_path / "reports"),
        ],
    )
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["reason"] == "daz_construction_invalid"
    assert payload["data"]["summary"]["failure_codes"] == ["VALIDATION_REQUIRED_WARNING"]
