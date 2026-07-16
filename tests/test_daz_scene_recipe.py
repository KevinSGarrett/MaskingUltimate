from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.scenes import (
    SceneRecipeError,
    canonical_json_bytes,
    derive_named_random_streams,
    publish_resolved_scene_recipe,
    seal_resolved_scene_recipe,
    validate_resolved_scene_recipe,
)


def _draft() -> dict:
    scene_id = "daz_scene_fixture001"
    streams = derive_named_random_streams(72599183, scene_id)
    return {
        "schema_version": "1.0.0",
        "scene_id": scene_id,
        "scene_family_id": "daz_family_fixture001",
        "master_seed": 72599183,
        "named_random_streams": streams,
        "registry_snapshot_id": "daz_registry_fixture001",
        "runtime_snapshot_id": "daz_runtime_fixture001",
        "script_bundle_sha256": "a" * 64,
        "ontology": {"name": "body_parts_v1", "snapshot_sha256": "b" * 64},
        "render_profile_id": "training_relationship_1024_v1",
        "coverage_demand_ids": ["cov_solo_profile"],
        "characters": [
            {
                "construction_id": "c0",
                "requested_promoted_id": None,
                "figure_asset_id": "daz_asset_g9base",
                "character_preset_asset_id": "daz_asset_characterA",
                "body_profile_id": "body_profile_0042",
                "face_profile_id": "face_profile_0107",
                "age_appearance_category": "adult_30_44",
                "anatomy_configuration": "adult_male",
                "anatomy_asset_ids": ["daz_asset_male_anatomy"],
                "skin_material_asset_id": "daz_asset_skinA",
                "hair_asset_id": "daz_asset_hairA",
                "wardrobe_asset_ids": ["daz_asset_topA", "daz_asset_pantsA"],
                "morph_values": {
                    "prop://body/height": 0.16,
                    "prop://body/muscularity": 0.31,
                },
                "pose_asset_id": "daz_asset_poseA",
                "pose_adjustments": {},
                "mapping_bundle_ids": ["map_g9_v1_0001", "map_g9_male_anatomy_v1"],
                "world_transform": {
                    "translation_cm": [-18.0, 0.0, 2.0],
                    "rotation_deg": [0.0, 12.0, 0.0],
                    "scale": 1.0,
                },
            }
        ],
        "relationship_template": None,
        "camera": {
            "projection": "perspective",
            "focal_length_mm": 55.0,
            "position_cm": [0.0, 155.0, 430.0],
            "target_cm": [0.0, 105.0, 0.0],
            "roll_deg": 0.0,
            "resolution": [1024, 1024],
            "crop": [0, 0, 1024, 1024],
        },
        "lighting": {
            "profile_id": "studio_soft_three_point_v2",
            "parameter_seed": streams["lighting"],
        },
        "environment": {
            "asset_id": "daz_asset_studioA",
            "background_profile": "mid_neutral",
        },
        "props": [],
    }


def test_named_streams_are_independent_stable_and_scene_bound() -> None:
    streams = derive_named_random_streams(72599183, "daz_scene_fixture001")
    assert streams == {
        "characters": 17821538334183338768,
        "poses": 162221569403821018,
        "placement": 7499190750237258246,
        "camera": 9159433141988819731,
        "lighting": 5720320751127622626,
        "environment": 17199794972591785516,
        "render": 11789197117079385498,
        "degrade": 14887673936129779963,
    }
    assert len(set(streams.values())) == len(streams)
    assert streams != derive_named_random_streams(72599183, "daz_scene_fixture002")


def test_canonical_json_and_sealing_ignore_mapping_insertion_order() -> None:
    first = _draft()
    second = {key: deepcopy(first[key]) for key in reversed(first)}
    second["characters"][0]["morph_values"] = {
        "prop://body/muscularity": 0.31,
        "prop://body/height": 0.16,
    }
    sealed_first = seal_resolved_scene_recipe(first)
    sealed_second = seal_resolved_scene_recipe(second)
    assert sealed_first == sealed_second
    assert canonical_json_bytes(sealed_first) == canonical_json_bytes(sealed_second)
    assert validate_resolved_scene_recipe(sealed_first)["valid"] is True


def test_tamper_stream_mismatch_and_nonfinite_values_fail_closed() -> None:
    sealed = seal_resolved_scene_recipe(_draft())
    tampered = deepcopy(sealed)
    tampered["camera"]["focal_length_mm"] = 85.0
    with pytest.raises(SceneRecipeError, match="scene_recipe_hash_mismatch"):
        validate_resolved_scene_recipe(tampered)

    wrong_stream = _draft()
    wrong_stream["named_random_streams"]["camera"] += 1
    with pytest.raises(SceneRecipeError, match="scene_random_stream_mismatch"):
        seal_resolved_scene_recipe(wrong_stream)

    nonfinite = _draft()
    nonfinite["characters"][0]["morph_values"]["prop://body/height"] = float("nan")
    with pytest.raises(SceneRecipeError, match="scene_nonfinite_number"):
        seal_resolved_scene_recipe(nonfinite)


def test_character_identity_relationship_and_crop_invariants_fail_closed() -> None:
    duplicate = _draft()
    duplicate["characters"].append(deepcopy(duplicate["characters"][0]))
    with pytest.raises(SceneRecipeError, match="scene_construction_id_duplicate"):
        seal_resolved_scene_recipe(duplicate)

    bad_relationship = _draft()
    bad_relationship["relationship_template"] = {
        "type": "contact",
        "participants": ["c0", "c1"],
    }
    with pytest.raises(SceneRecipeError, match="scene_relationship_participant_invalid"):
        seal_resolved_scene_recipe(bad_relationship)

    bad_crop = _draft()
    bad_crop["camera"]["crop"] = [0, 0, 2048, 1024]
    with pytest.raises(SceneRecipeError, match="scene_crop_exceeds_resolution"):
        seal_resolved_scene_recipe(bad_crop)


def test_resolved_recipe_publication_is_immutable_and_idempotent(tmp_path: Path) -> None:
    sealed = seal_resolved_scene_recipe(_draft())
    target, published = publish_resolved_scene_recipe(sealed, tmp_path)
    assert published is True
    assert publish_resolved_scene_recipe(sealed, tmp_path) == (target, False)
    assert target.name == f"{sealed['scene_id']}_{sealed['recipe_sha256'][:16]}.json"


def test_recipe_cli_seals_and_validates_byte_identical_replay(tmp_path: Path) -> None:
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(_draft()), encoding="utf-8")
    output = tmp_path / "recipes"
    runner = CliRunner()
    first = runner.invoke(main, ["daz", "recipes", "seal", str(draft), "--output", str(output)])
    second = runner.invoke(main, ["daz", "recipes", "seal", str(draft), "--output", str(output)])
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    first_envelope = json.loads(first.output)
    second_envelope = json.loads(second.output)
    assert first_envelope["data"]["recipe_sha256"] == second_envelope["data"]["recipe_sha256"]
    assert first_envelope["data"]["publication"]["published"] is True
    assert second_envelope["data"]["publication"]["published"] is False
    verified = runner.invoke(
        main,
        ["daz", "recipes", "validate", first_envelope["data"]["publication"]["path"]],
    )
    assert verified.exit_code == 0, verified.output
    assert json.loads(verified.output)["reason"] == "daz_scene_recipe_valid"
