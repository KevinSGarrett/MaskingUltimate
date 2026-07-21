from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maskfactory.cli import main  # noqa: E402
from maskfactory.daz.scenes import (  # noqa: E402
    ResolvedSceneStateError,
    evaluate_scene_preflight,
    generate_character_variation_profile,
    load_character_profile_policy,
    load_resolved_scene_state_policy,
    load_scene_preflight_policy,
    seal_resolved_scene_state,
    select_character_appearance,
    validate_resolved_scene_state,
    validate_resolved_scene_state_policy,
)
from test_daz_character_appearance import _fixture as appearance_fixture  # noqa: E402
from test_daz_character_appearance import _foundation  # noqa: E402
from test_daz_scene_preflight import (
    _formation_selection,
    _observation,
    _pose_selection,
)  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROFILE_POLICY = ROOT / "configs" / "daz" / "character_profiles.yaml"
PREFLIGHT_POLICY = ROOT / "configs" / "daz" / "scene_preflight.yaml"
STATE_POLICY = ROOT / "configs" / "daz" / "resolved_scene_state.yaml"


def _sha(document) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _rebind(document: dict, foundation: dict) -> dict:
    result = deepcopy(document)
    result["foundation_selection_id"] = foundation["selection_id"]
    result["foundation_selection_sha256"] = foundation["selection_sha256"]
    content = {
        key: value
        for key, value in result.items()
        if key not in {"schema_version", "selection_id", "selection_sha256"}
    }
    digest = _sha(content)
    prefix = result["selection_id"].split("_", 1)[0]
    result["selection_id"] = f"{prefix}_{digest[:24]}"
    result["selection_sha256"] = digest
    return result


def _chain() -> tuple[dict, dict, dict, dict, dict, dict, dict, dict]:
    graph, pools, appearance_policy, _base = appearance_fixture()
    foundation = _foundation(graph, pools, "standard_casual")
    appearance = select_character_appearance(
        graph,
        pools,
        foundation,
        appearance_policy,
        selection_seed=44,
        anatomy_configuration="adult_male_anatomy",
        hair_mode="required",
        wardrobe_state="standard_casual",
    )
    profile_policy = load_character_profile_policy(PROFILE_POLICY)
    profile = generate_character_variation_profile(
        profile_policy,
        seed=45,
        anatomy_configuration="adult_male_anatomy",
        age_appearance_category="adult_30_44",
    )
    pose = _rebind(_pose_selection(), foundation)
    formation = _rebind(_formation_selection(prop=True), foundation)
    observation = _observation(pose, formation, prop=True)
    preflight = evaluate_scene_preflight(
        pose, formation, observation, load_scene_preflight_policy(PREFLIGHT_POLICY)
    )
    policy = load_resolved_scene_state_policy(STATE_POLICY)
    readback = _readback(foundation, profile, appearance, pose, formation, preflight)
    return foundation, profile, appearance, pose, formation, preflight, readback, policy


def _readback(
    foundation: dict,
    profile: dict,
    appearance: dict,
    pose: dict,
    formation: dict,
    preflight: dict,
) -> dict:
    lineage = {
        "foundation_selection_id": foundation["selection_id"],
        "foundation_selection_sha256": foundation["selection_sha256"],
        "profile_id": profile["profile_id"],
        "profile_sha256": profile["profile_sha256"],
        "appearance_selection_id": appearance["selection_id"],
        "appearance_selection_sha256": appearance["selection_sha256"],
        "pose_selection_id": pose["selection_id"],
        "pose_selection_sha256": pose["selection_sha256"],
        "formation_selection_id": formation["selection_id"],
        "formation_selection_sha256": formation["selection_sha256"],
        "preflight_report_id": preflight["report_id"],
        "preflight_report_sha256": preflight["report_sha256"],
    }
    assets = {
        "figure": foundation["selected"]["figure_asset_id"],
        "character_preset": foundation["selected"]["character_preset_asset_id"],
        "skin_material": foundation["selected"]["skin_material_asset_id"],
        "anatomy": appearance["selected"]["anatomy_asset_id"],
        "hair": appearance["selected"]["hair_asset_id"],
        "pose": pose["selected"]["pose_asset_id"],
        "light": formation["selected"]["light"]["asset_id"],
        "environment": formation["selected"]["environment"]["asset_id"],
        "prop": formation["selected"]["prop"]["asset_id"],
    }
    for index, item in enumerate(appearance["selected"]["wardrobe_items_inner_to_outer"]):
        assets[f"wardrobe_{index:02d}"] = item["asset_id"]
    state = {
        "schema_version": "1.0.0",
        "scene_id": preflight["scene_id"],
        "lineage": lineage,
        "runtime_snapshot_sha256": "1" * 64,
        "script_bundle_sha256": "2" * 64,
        "mapping_set_sha256": "3" * 64,
        "default_scene_empty_before_load": True,
        "unexpected_renderable_node_count": 0,
        "assets": [
            {"role": role, "asset_id": asset_id, "node_id": f"node_{index:02d}"}
            for index, (role, asset_id) in enumerate(sorted(assets.items()))
        ],
        "property_values": [
            {
                "uri": "prop://body/stature",
                "source_id": profile["profile_id"],
                "requested_value": 0.25,
                "final_value": 0.25,
                "minimum": -1.0,
                "maximum": 1.0,
                "tolerance": 0.000001,
                "locked": False,
                "silently_ignored": False,
            }
        ],
        "controller_side_effects": [
            {
                "uri": "prop://body/corrective",
                "cause_uri": "prop://body/stature",
                "final_value": 0.01,
                "declared": True,
            }
        ],
        "joint_values": [
            {
                "bone": bone,
                "axis": axis,
                "requested_degrees": value,
                "final_degrees": value,
                "minimum_degrees": -90.0,
                "maximum_degrees": 90.0,
            }
            for bone, axes in pose["selected"]["bone_rotations_deg"].items()
            for axis, value in axes.items()
        ],
        "node_hierarchy": [{"node_id": "node_00", "parent_id": None}],
        "geometry_fingerprints": {"node_00": "4" * 64},
        "world_transforms": {
            "node_00": [
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
        },
        "material_assignments": {"node_00": ["skin"]},
        "opacity_parameters": {"node_00": 1.0},
        "camera": deepcopy(formation["selected"]["camera"]),
        "lighting_environment": {
            "light_asset_id": formation["selected"]["light"]["asset_id"],
            "environment_asset_id": formation["selected"]["environment"]["asset_id"],
            "prop_asset_id": formation["selected"]["prop"]["asset_id"],
        },
        "visibility_flags": {"node_00": True},
        "renderer": {"id": "iray", "version": "fixture"},
        "pass_profile": "pristine_and_semantic_v1",
        "unresolved_textures": [],
    }
    digest = _sha(state)
    return {
        **state,
        "semantic_replay_scene_state_sha256": digest,
        "annotation_restore_scene_state_sha256": digest,
    }


def test_policy_is_closed_and_requires_replay_restore_and_zero_silent_failures() -> None:
    policy = load_resolved_scene_state_policy(STATE_POLICY)
    validate_resolved_scene_state_policy(policy)
    assert policy["semantic_replay_hash_must_match"] is True
    assert policy["annotation_restore_hash_must_match"] is True
    assert policy["unresolved_textures_allowed"] == 0
    assert policy["undeclared_controller_side_effects_allowed"] == 0


def test_complete_readback_seals_and_replays_exactly() -> None:
    chain = _chain()
    document = seal_resolved_scene_state(*chain)
    assert document["replay_evidence"]["semantic_replay_matches"] is True
    assert document["replay_evidence"]["annotation_restore_matches"] is True
    assert (
        document["scene_state_sha256"]
        == document["replay_evidence"]["semantic_replay_scene_state_sha256"]
    )
    validate_resolved_scene_state(document, *chain)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda r: r["assets"].pop(), "asset_readback_mismatch"),
        (lambda r: r["assets"][0].__setitem__("asset_id", "ast_wrong"), "asset_readback_mismatch"),
        (
            lambda r: r["property_values"][0].__setitem__("final_value", 0.3),
            "property_readback_mismatch",
        ),
        (lambda r: r["property_values"][0].__setitem__("locked", True), "property_not_applied"),
        (
            lambda r: r["property_values"][0].__setitem__("silently_ignored", True),
            "property_not_applied",
        ),
        (
            lambda r: r["property_values"][0].__setitem__("final_value", 2.0),
            "property_out_of_range",
        ),
        (
            lambda r: r["controller_side_effects"][0].__setitem__("declared", False),
            "side_effect_undeclared",
        ),
        (
            lambda r: r["joint_values"][0].__setitem__("final_degrees", 1.0),
            "joint_readback_mismatch",
        ),
        (lambda r: r["joint_values"].pop(), "joint_set_mismatch"),
        (lambda r: r["camera"].__setitem__("focal_length_mm", 51.0), "numeric_readback_mismatch"),
        (
            lambda r: r["lighting_environment"].__setitem__("light_asset_id", "ast_wrong"),
            "formation_readback_mismatch",
        ),
        (
            lambda r: r.__setitem__("default_scene_empty_before_load", False),
            "default_scene_not_empty",
        ),
        (
            lambda r: r.__setitem__("unexpected_renderable_node_count", 1),
            "unexpected_renderable_nodes",
        ),
        (lambda r: r["unresolved_textures"].append("missing.png"), "unresolved_textures"),
        (
            lambda r: r.__setitem__("semantic_replay_scene_state_sha256", "0" * 64),
            "semantic_replay_mismatch",
        ),
        (
            lambda r: r.__setitem__("annotation_restore_scene_state_sha256", "0" * 64),
            "annotation_restore_mismatch",
        ),
    ],
)
def test_readback_mismatches_fail_closed(mutation, reason: str) -> None:
    foundation, profile, appearance, pose, formation, preflight, readback, policy = _chain()
    mutation(readback)
    with pytest.raises(ResolvedSceneStateError, match=reason):
        seal_resolved_scene_state(
            foundation, profile, appearance, pose, formation, preflight, readback, policy
        )


def test_nonaccepted_preflight_and_cross_selection_lineage_fail_closed() -> None:
    foundation, profile, appearance, pose, formation, preflight, readback, policy = _chain()
    invalid = deepcopy(preflight)
    invalid["summary"]["disposition"] = "reject"
    with pytest.raises(ResolvedSceneStateError, match="upstream_hash_invalid"):
        seal_resolved_scene_state(
            foundation, profile, appearance, pose, formation, invalid, readback, policy
        )
    invalid_pose = deepcopy(pose)
    invalid_pose["foundation_selection_id"] = "dcfs_" + "0" * 24
    content = {
        key: value
        for key, value in invalid_pose.items()
        if key not in {"schema_version", "selection_id", "selection_sha256"}
    }
    digest = _sha(content)
    invalid_pose["selection_id"] = f"dcps_{digest[:24]}"
    invalid_pose["selection_sha256"] = digest
    with pytest.raises(ResolvedSceneStateError, match="foundation_lineage"):
        seal_resolved_scene_state(
            foundation, profile, appearance, invalid_pose, formation, preflight, readback, policy
        )


def test_resolved_document_tamper_is_rejected_by_full_replay() -> None:
    chain = _chain()
    document = seal_resolved_scene_state(*chain)
    tampered = deepcopy(document)
    tampered["state"]["renderer"]["version"] = "tampered"
    with pytest.raises(ResolvedSceneStateError, match="state_replay_mismatch"):
        validate_resolved_scene_state(tampered, *chain)


def test_cli_seals_and_publishes_idempotently(tmp_path: Path) -> None:
    foundation, profile, appearance, pose, formation, preflight, readback, _policy = _chain()
    paths = {}
    for name, document in (
        ("foundation", foundation),
        ("profile", profile),
        ("appearance", appearance),
        ("pose", pose),
        ("formation", formation),
        ("preflight", preflight),
        ("readback", readback),
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[name] = path
    output = tmp_path / "out"
    arguments = [
        "daz",
        "recipes",
        "seal-resolved-state",
        "--foundation",
        str(paths["foundation"]),
        "--profile",
        str(paths["profile"]),
        "--appearance",
        str(paths["appearance"]),
        "--pose",
        str(paths["pose"]),
        "--formation",
        str(paths["formation"]),
        "--preflight-report",
        str(paths["preflight"]),
        "--readback",
        str(paths["readback"]),
        "--policy",
        str(STATE_POLICY),
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
