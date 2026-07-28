from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.scenes import (
    ScenePreflightError,
    evaluate_scene_preflight,
    load_scene_preflight_policy,
    validate_scene_preflight_policy,
    validate_scene_preflight_report,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs" / "daz" / "scene_preflight.yaml"


def _sha(document) -> str:
    return hashlib.sha256(
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _pose_selection() -> dict:
    selected = {
        "pose_asset_id": "ast_000000000000000000000064",
        "descriptor_id": "dcpd_neutral_fixture",
        "descriptor_sha256": "1" * 64,
        "primary_asset_class": "pose_full_body",
        "pose_family": "neutral_calibration",
        "pose_subfamily": "relaxed_standing",
        "root_transform_policy": "preserve_root",
        "root_transform": {
            "translation_cm": [0.0, 0.0, 0.0],
            "rotation_deg": [0.0, 0.0, 0.0],
        },
        "owned_bones": ["pelvis"],
        "bone_rotations_deg": {"pelvis": {"bend": 0.0, "twist": 0.0, "side_side": 0.0}},
        "support_mode": "standing_feet",
        "support_contacts": ["left_foot", "right_foot"],
        "visibility_expectation": {"hands": "both_visible", "feet": "both_visible"},
        "self_occlusion_tags": [],
        "asymmetry_tag": "symmetric",
        "camera_view_suitability": ["front"],
        "joint_metrics": {
            "limit_source": "daz_runtime_property_limits",
            "bone_count": 1,
            "axis_value_count": 3,
            "maximum_utilization": 0.0,
            "minimum_boundary_margin_degrees": 45.0,
            "intersection_score": 0.0,
            "passed": True,
        },
        "source_readback_required": True,
        "final_daz_readback_required": True,
    }
    content = {
        "graph_id": "dacg_" + "1" * 24,
        "graph_sha256": "2" * 64,
        "pool_report_id": "dapr_" + "3" * 24,
        "pool_report_sha256": "4" * 64,
        "foundation_selection_id": "dcfs_" + "5" * 24,
        "foundation_selection_sha256": "6" * 64,
        "policy_sha256": "7" * 64,
        "descriptor_registry_sha256": "8" * 64,
        "request": {
            "selection_seed": 1,
            "pose_family": "neutral_calibration",
            "pose_subfamily": "relaxed_standing",
        },
        "candidate_counts": {"qualified_pose_pool_members": 1, "matching_candidates": 1},
        "rejection_counts": {},
        "selected": selected,
        "compatibility_evidence": {
            "asset_runtime_qualified": True,
            "required_dependencies_runtime_qualified": True,
            "genesis_9_compatible": True,
            "solo_only": True,
            "taxonomy_match": True,
            "root_transform_within_policy": True,
            "joint_limits_within_runtime_bounds": True,
            "hand_foot_articulation_declared_valid": True,
            "intersection_score_within_policy": True,
        },
    }
    digest = _sha(content)
    return {
        "schema_version": "1.0.0",
        "selection_id": f"dcps_{digest[:24]}",
        "selection_sha256": digest,
        **content,
    }


def _formation_selection(*, prop: bool = False, framing: str = "full_body_tight") -> dict:
    camera = {
        "projection_type": "perspective",
        "azimuth_bin": "front",
        "azimuth_degrees": 0.0,
        "elevation_bin": "eye_level",
        "elevation_degrees": 0.0,
        "roll_bin": "level",
        "roll_degrees": 0.0,
        "focal_family": "normal",
        "focal_length_mm": 50.0,
        "orthographic_scale": None,
        "look_at_target": "promoted_people_centroid",
        "framing_profile": framing,
        "aspect_ratio": "1:1",
        "resolution": [768, 768],
        "crop": [0, 0, 768, 768],
        "depth_of_field": {"mode": "off", "enabled": False, "f_stop": None},
        "motion_blur": {"mode": "off", "enabled": False},
        "lens_distortion_state": "pristine_none",
        "projected_bboxes_and_prominence": "required_final_readback",
        "annotation_camera_effects_off": True,
        "final_readback_required": True,
    }
    light = {
        "asset_id": "ast_0000000000000000000000c8",
        "descriptor_id": "dcfd_light_fixture",
        "descriptor_sha256": "9" * 64,
        "descriptor_type": "light",
        "lighting_profile": "front_soft",
        "environment_family": None,
        "environment_subfamily": None,
        "context_complexity": None,
        "prop_mode": None,
        "prop_role": None,
        "anchor_types": [],
        "stable_object_id": None,
        "final_readback_required": True,
    }
    environment = {
        "asset_id": "ast_0000000000000000000000c9",
        "descriptor_id": "dcfd_environment_fixture",
        "descriptor_sha256": "a" * 64,
        "descriptor_type": "environment",
        "lighting_profile": None,
        "environment_family": "controlled",
        "environment_subfamily": "transparent_solid_neutral",
        "context_complexity": "controlled",
        "prop_mode": None,
        "prop_role": None,
        "anchor_types": [],
        "stable_object_id": None,
        "final_readback_required": True,
    }
    prop_record = (
        {
            "asset_id": "ast_0000000000000000000000ca",
            "descriptor_id": "dcfd_prop_fixture",
            "descriptor_sha256": "b" * 64,
            "descriptor_type": "prop",
            "lighting_profile": None,
            "environment_family": None,
            "environment_subfamily": None,
            "context_complexity": None,
            "prop_mode": "occluder",
            "prop_role": "occluding_object",
            "anchor_types": ["foreground_occluder"],
            "stable_object_id": "object_202",
            "final_readback_required": True,
        }
        if prop
        else None
    )
    request = {
        "selection_seed": 2,
        "person_count": 1,
        "azimuth_bin": "front",
        "elevation_bin": "eye_level",
        "roll_bin": "level",
        "focal_family": "normal",
        "framing_profile": framing,
        "aspect_ratio": "1:1",
        "resolution_profile": "pilot_768",
        "depth_of_field_mode": "off",
        "lighting_profile": "front_soft",
        "exposure_profile": "normal",
        "environment_family": "controlled",
        "environment_subfamily": "transparent_solid_neutral",
        "context_complexity": "controlled",
        "prop_mode": "occluder" if prop else "none",
    }
    content = {
        "graph_id": "dacg_" + "1" * 24,
        "graph_sha256": "2" * 64,
        "pool_report_id": "dapr_" + "3" * 24,
        "pool_report_sha256": "4" * 64,
        "foundation_selection_id": "dcfs_" + "5" * 24,
        "foundation_selection_sha256": "6" * 64,
        "policy_sha256": "c" * 64,
        "descriptor_registry_sha256": "d" * 64,
        "request": request,
        "candidate_counts": {"light": 1, "environment": 1, "prop": 1 if prop else 0},
        "rejection_counts": {},
        "selected": {
            "camera": camera,
            "light": light,
            "environment": environment,
            "prop": prop_record,
            "exposure_profile": "normal",
        },
        "evidence_requirements": {
            "final_camera_readback_required": True,
            "projected_bbox_and_prominence_required": True,
            "pristine_annotation_camera_match_required": True,
            "final_light_environment_prop_readback_required": True,
            "prop_contact_and_occlusion_preflight_required": prop,
            "undeclared_human_and_reflection_check_required": True,
            "finite_nonempty_rgb_required": True,
        },
    }
    digest = _sha(content)
    return {
        "schema_version": "1.0.0",
        "selection_id": f"dcif_{digest[:24]}",
        "selection_sha256": digest,
        **content,
    }


def _observation(
    pose: dict,
    formation: dict,
    *,
    prop: bool = False,
) -> dict:
    visible_pixels = 350_000
    prominence = visible_pixels / (768 * 768)
    return {
        "schema_version": "1.0.0",
        "scene_id": "daz_scene_preflight_fixture",
        "pose_selection_id": pose["selection_id"],
        "pose_selection_sha256": pose["selection_sha256"],
        "formation_selection_id": formation["selection_id"],
        "formation_selection_sha256": formation["selection_sha256"],
        "repair_attempt": 0,
        "declared_person_count": 1,
        "resolution": [768, 768],
        "crop": [0, 0, 768, 768],
        "camera_clipped": False,
        "unexpected_renderable_node_count": 0,
        "undeclared_person_count": 0,
        "catastrophic_geometry": False,
        "persons": [
            {
                "construction_id": "c0",
                "bbox_xywh": [134, 20, 500, 700],
                "visible_pixels": visible_pixels,
                "projected_pixels": 350_000,
                "prominence": prominence,
                "visible_body_fraction": 1.0,
                "off_frame_fraction": 0.0,
                "bbox_height_fraction": 700 / 768,
                "visible_regions": [
                    "head",
                    "left_foot",
                    "left_hand",
                    "right_foot",
                    "right_hand",
                    "torso",
                ],
            }
        ],
        "collisions": [
            {
                "pair_id": "body_self_fixture",
                "category": "self_body",
                "maximum_depth_mm": 0.5,
                "penetration_volume_cc": 0.1,
                "visible": False,
                "intended_contact": False,
                "exempt": False,
                "broad_phase_overlap": True,
                "narrow_phase_ran": True,
            }
        ],
        "support_contacts": [
            {
                "contact_id": foot,
                "required": True,
                "observed": True,
                "distance_mm": 1.0,
                "normal_dot": 0.8,
                "penetration_mm": 0.5,
                "support_drift_mm": 1.0,
            }
            for foot in ("left_foot", "right_foot")
        ],
        "prop_observation": (
            {
                "stable_object_id": "object_202",
                "anchored": True,
                "floating": False,
                "target_region": "torso",
                "target_occlusion_fraction": 0.2,
                "observed_occlusion_fraction": 0.2,
            }
            if prop
            else None
        ),
    }


def _evaluate(*, prop: bool = False, framing: str = "full_body_tight"):
    pose = _pose_selection()
    formation = _formation_selection(prop=prop, framing=framing)
    observation = _observation(pose, formation, prop=prop)
    policy = load_scene_preflight_policy(POLICY)
    return pose, formation, observation, policy


def test_policy_is_closed_and_binds_existing_four_percent_promotion_floor() -> None:
    policy = load_scene_preflight_policy(POLICY)
    validate_scene_preflight_policy(policy)
    assert policy["promotion"]["minimum_visible_area_fraction"] == 0.04
    assert policy["contact"]["intended_distance_mm"] == [0.0, 4.0]
    assert policy["contact"]["maximum_penetration_mm"] == 2.0
    assert policy["repair"]["deterministic_camera_support_correction_maximum"] == 2


def test_passing_observation_is_accepted_and_exactly_replayable() -> None:
    pose, formation, observation, policy = _evaluate()
    report = evaluate_scene_preflight(pose, formation, observation, policy)
    assert report["summary"] == {
        "passed": True,
        "finding_count": 0,
        "failure_codes": [],
        "disposition": "accept",
        "repair_attempt": 0,
        "repair_attempts_remaining": 2,
        "new_recipe_revision_required_for_repair": False,
    }
    validate_scene_preflight_report(report, pose, formation, observation, policy)


@pytest.mark.parametrize(
    ("framing", "visible_body", "off_frame", "bbox_height", "extra_region"),
    [
        ("full_body_margin", 1.0, 0.0, 0.80, None),
        ("full_body_tight", 1.0, 0.0, 0.90, None),
        ("three_quarter_body", 0.75, 0.25, 0.85, None),
        ("waist_up", 0.55, 0.45, 0.80, None),
        ("chest_head", 0.35, 0.65, 0.70, None),
        ("head_shoulders", 0.20, 0.80, 0.60, None),
        ("close_up_specialist", 0.10, 0.90, 0.50, "specialist_target"),
        ("intentional_truncation", 0.70, 0.30, 0.70, None),
        ("negative_space", 0.95, 0.05, 0.60, None),
        ("off_center", 0.90, 0.10, 0.70, None),
    ],
)
def test_all_solo_framing_profiles_accept_in_range_observations(
    framing: str,
    visible_body: float,
    off_frame: float,
    bbox_height: float,
    extra_region: str | None,
) -> None:
    pose, formation, observation, policy = _evaluate(framing=framing)
    person = observation["persons"][0]
    person["visible_body_fraction"] = visible_body
    person["off_frame_fraction"] = off_frame
    person["bbox_height_fraction"] = bbox_height
    person["bbox_xywh"] = [134, 0, 500, round(768 * bbox_height)]
    if extra_region is not None:
        person["visible_regions"].append(extra_region)
        person["visible_regions"].sort()
    report = evaluate_scene_preflight(pose, formation, observation, policy)
    assert report["summary"]["disposition"] == "accept", report["findings"]


@pytest.mark.parametrize(
    ("mutation", "code", "disposition"),
    [
        (
            lambda o: o.__setitem__("camera_clipped", True),
            "GEOMETRY_CAMERA_CLIP_REPAIRABLE",
            "repair",
        ),
        (
            lambda o: o.__setitem__("unexpected_renderable_node_count", 1),
            "ASSEMBLY_UNEXPECTED_RENDERABLE_NODE",
            "reject",
        ),
        (
            lambda o: o.__setitem__("undeclared_person_count", 1),
            "ASSEMBLY_UNDECLARED_PERSON",
            "reject",
        ),
        (lambda o: o.__setitem__("catastrophic_geometry", True), "GEOMETRY_CATASTROPHIC", "reject"),
        (
            lambda o: o["persons"][0].__setitem__("bbox_xywh", [700, 20, 500, 700]),
            "GEOMETRY_FRAMING_RECENTERABLE",
            "repair",
        ),
        (
            lambda o: o["persons"][0].update(
                {"visible_pixels": 10_000, "prominence": 10_000 / (768 * 768)}
            ),
            "GEOMETRY_PERSON_BELOW_PROMINENCE",
            "reject",
        ),
        (
            lambda o: o["persons"][0].__setitem__("off_frame_fraction", 0.2),
            "GEOMETRY_FRAMING_RECENTERABLE",
            "repair",
        ),
        (
            lambda o: o["persons"][0]["visible_regions"].remove("left_foot"),
            "GEOMETRY_FRAMING_REQUIRED_REGION_MISSING",
            "reject",
        ),
        (
            lambda o: o["persons"][0].__setitem__("prominence", 0.5),
            "GEOMETRY_PROMINENCE_MISMATCH",
            "reject",
        ),
        (
            lambda o: o["collisions"][0].update({"maximum_depth_mm": 3.0, "visible": True}),
            "GEOMETRY_VISIBLE_PENETRATION",
            "reject",
        ),
        (
            lambda o: o["collisions"][0].update({"maximum_depth_mm": 3.0, "visible": False}),
            "GEOMETRY_HIDDEN_INTERSECTION_EXCESSIVE",
            "reject",
        ),
        (
            lambda o: o["collisions"][0].__setitem__("exempt", True),
            "GEOMETRY_COLLISION_EXEMPTION_INVALID",
            "reject",
        ),
        (
            lambda o: o["collisions"][0].__setitem__("narrow_phase_ran", False),
            "GEOMETRY_NARROW_PHASE_MISSING",
            "reject",
        ),
        (lambda o: o["support_contacts"].pop(), "GEOMETRY_SUPPORT_CONTACT_MISSING", "reject"),
        (
            lambda o: o["support_contacts"][0].__setitem__("observed", False),
            "GEOMETRY_SUPPORT_CONTACT_MISSING",
            "reject",
        ),
        (
            lambda o: o["support_contacts"][0].__setitem__("distance_mm", 5.0),
            "GEOMETRY_CONTACT_DISTANCE_INVALID",
            "reject",
        ),
        (
            lambda o: o["support_contacts"][0].__setitem__("normal_dot", -0.1),
            "GEOMETRY_CONTACT_NORMAL_INVALID",
            "reject",
        ),
        (
            lambda o: o["support_contacts"][0].__setitem__("penetration_mm", 2.1),
            "GEOMETRY_CONTACT_PENETRATION",
            "reject",
        ),
        (
            lambda o: o["support_contacts"][0].__setitem__("support_drift_mm", 5.0),
            "GEOMETRY_SUPPORT_DRIFT_REPAIRABLE",
            "repair",
        ),
    ],
)
def test_negative_geometry_fixtures_fail_closed(mutation, code: str, disposition: str) -> None:
    pose, formation, observation, policy = _evaluate()
    mutation(observation)
    report = evaluate_scene_preflight(pose, formation, observation, policy)
    assert code in report["summary"]["failure_codes"]
    assert report["summary"]["disposition"] == disposition
    assert report["summary"]["passed"] is False


def test_repair_budget_exhaustion_converts_repairable_failure_to_reject() -> None:
    pose, formation, observation, policy = _evaluate()
    observation["camera_clipped"] = True
    observation["repair_attempt"] = 2
    report = evaluate_scene_preflight(pose, formation, observation, policy)
    assert report["summary"]["disposition"] == "reject"
    assert report["summary"]["repair_attempts_remaining"] == 0


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda o: o["prop_observation"].__setitem__("floating", True), "GEOMETRY_FLOATING_PROP"),
        (lambda o: o["prop_observation"].__setitem__("anchored", False), "GEOMETRY_FLOATING_PROP"),
        (
            lambda o: o["prop_observation"].__setitem__("observed_occlusion_fraction", 0.5),
            "GEOMETRY_PROP_OCCLUSION_TARGET_MISSED",
        ),
        (
            lambda o: o["prop_observation"].__setitem__("stable_object_id", "object_wrong"),
            "ASSEMBLY_PROP_ID_MISMATCH",
        ),
    ],
)
def test_prop_anchor_identity_and_occlusion_fail_closed(mutation, code: str) -> None:
    pose, formation, observation, policy = _evaluate(prop=True)
    mutation(observation)
    report = evaluate_scene_preflight(pose, formation, observation, policy)
    assert code in report["summary"]["failure_codes"]
    assert report["summary"]["disposition"] == "reject"


def test_missing_selected_prop_and_undeclared_unselected_prop_fail_closed() -> None:
    pose, formation, observation, policy = _evaluate(prop=True)
    observation["prop_observation"] = None
    assert (
        "ASSEMBLY_PROP_MISSING"
        in evaluate_scene_preflight(pose, formation, observation, policy)["summary"][
            "failure_codes"
        ]
    )
    pose, formation, observation, policy = _evaluate(prop=False)
    observation["prop_observation"] = {
        "stable_object_id": "object_999",
        "anchored": True,
        "floating": False,
        "target_region": "",
        "target_occlusion_fraction": 0.0,
        "observed_occlusion_fraction": 0.0,
    }
    assert (
        "ASSEMBLY_UNDECLARED_PROP"
        in evaluate_scene_preflight(pose, formation, observation, policy)["summary"][
            "failure_codes"
        ]
    )


def test_lineage_camera_contract_and_selection_hash_tamper_raise_structural_errors() -> None:
    pose, formation, observation, policy = _evaluate()
    invalid = deepcopy(observation)
    invalid["pose_selection_sha256"] = "0" * 64
    with pytest.raises(ScenePreflightError, match="pose_lineage"):
        evaluate_scene_preflight(pose, formation, invalid, policy)
    invalid = deepcopy(observation)
    invalid["resolution"] = [512, 512]
    with pytest.raises(ScenePreflightError, match="camera_contract"):
        evaluate_scene_preflight(pose, formation, invalid, policy)
    invalid_pose = deepcopy(pose)
    invalid_pose["selected"]["support_mode"] = "none"
    with pytest.raises(ScenePreflightError, match="selection_hash"):
        evaluate_scene_preflight(invalid_pose, formation, observation, policy)


def test_nonfinite_and_collision_phase_contradiction_raise_structural_errors() -> None:
    pose, formation, observation, policy = _evaluate()
    invalid = deepcopy(observation)
    invalid["persons"][0]["prominence"] = float("nan")
    with pytest.raises(ScenePreflightError, match="person_observation"):
        evaluate_scene_preflight(pose, formation, invalid, policy)
    invalid = deepcopy(observation)
    invalid["collisions"][0].update({"broad_phase_overlap": False, "narrow_phase_ran": True})
    with pytest.raises(ScenePreflightError, match="phase_contradiction"):
        evaluate_scene_preflight(pose, formation, invalid, policy)


def test_cli_evaluates_and_publishes_idempotently(tmp_path: Path) -> None:
    pose, formation, observation, _policy = _evaluate()
    paths = {}
    for name, document in (
        ("pose", pose),
        ("formation", formation),
        ("observation", observation),
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[name] = path
    output = tmp_path / "out"
    arguments = [
        "daz",
        "recipes",
        "preflight",
        "--pose-selection",
        str(paths["pose"]),
        "--formation-selection",
        str(paths["formation"]),
        "--observation",
        str(paths["observation"]),
        "--policy",
        str(POLICY),
        "--output",
        str(output),
    ]
    runner = CliRunner()
    first = runner.invoke(main, arguments)
    assert first.exit_code == 0, first.output
    assert json.loads(first.output)["data"]["summary"]["disposition"] == "accept"
    assert json.loads(first.output)["data"]["publication"]["published"] is True
    replay = runner.invoke(main, arguments)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
