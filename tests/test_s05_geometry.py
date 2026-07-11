import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from maskfactory.stages.s05_geometry import (
    GeometryError,
    build_prompt_plan,
    carve_joint_band,
    crop_request,
    hair_prior,
    joint_band,
    limb_capsule_prior,
    render_prompt_overlay,
    sample_cross_section_half_widths,
    torso_partition_priors,
    write_geometry_artifacts,
)


def test_prompting_config_exact_thresholds_prompts_and_part_coverage() -> None:
    config = yaml.safe_load(Path("configs/prompting.yaml").read_text())
    gdino = config["grounding_dino"]
    assert gdino["box_threshold"] == 0.30
    assert gdino["text_threshold"] == 0.25
    assert gdino["may_write_final_masks"] is False
    assert set(gdino["prompts"]) == {
        "hair",
        "bra",
        "underwear",
        "shoe",
        "sock",
        "glove",
        "necklace",
        "handheld object",
        "chair",
        "bed",
        "surface",
    }
    ontology = yaml.safe_load(Path("configs/ontology.yaml").read_text())
    atomic = {
        label["name"] for label in ontology["labels"] if label["map"] == "part" and label["id"] != 0
    }
    covered = {part for recipe in config["part_recipes"].values() for part in recipe["parts"]}
    assert covered == atomic
    assert config["sam2"]["box_scale"] == 1.10
    assert config["sam2"]["positives"]["skeleton_samples_min"] == 3
    assert config["sam2"]["positives"]["skeleton_samples_max"] == 7


def test_limb_width_uses_five_stations_and_capsule_is_clipped() -> None:
    parsing = np.zeros((60, 80), dtype=bool)
    parsing[20:41, 10:71] = True  # 21-pixel-wide horizontal limb
    silhouette = parsing.copy()
    silhouette[:, 60:] = False

    widths = sample_cross_section_half_widths(parsing, (15, 30), (65, 30))
    capsule, radius, measured = limb_capsule_prior(parsing, silhouette, (15, 30), (65, 30))

    assert len(widths) == 5 and widths == measured
    assert all(width == pytest.approx(10.5) for width in widths)
    assert radius == pytest.approx(10.5)
    assert np.all(capsule <= parsing)
    assert np.all(capsule <= silhouette)
    assert not capsule[:, 60:].any()


def test_joint_band_exact_height_factors_and_carve_ownership() -> None:
    elbow = joint_band((50, 50), (25, 25), (10, 25), (40, 25), 10, joint="elbow")
    wrist = joint_band((50, 50), (25, 25), (10, 25), (40, 25), 10, joint="wrist")
    # Pixel-center rasterization: 0.6*10 gives seven longitudinal rows; 0.5*10 gives five.
    assert np.count_nonzero(elbow[25, :]) == 7
    assert np.count_nonzero(wrist[25, :]) == 5
    proximal = np.zeros((50, 50), dtype=bool)
    distal = np.zeros((50, 50), dtype=bool)
    proximal[20:31, 5:26] = True
    distal[20:31, 25:46] = True
    carved_a, carved_b, owned = carve_joint_band(proximal, distal, elbow)
    assert not (carved_a & owned).any() and not (carved_b & owned).any()
    assert owned.any()


def test_crop_hair_prompt_artifacts_and_debug_overlay(tmp_path: Path) -> None:
    request = crop_request("left_hand", [(1, 2), (20, 22), (10, 12)], image_size=(30, 30))
    assert request.scale == 1.6
    assert request.bbox_xyxy[0] == 0 and request.bbox_xyxy[3] == 28
    parsing_hair = np.zeros((40, 40), dtype=bool)
    parsing_hair[10:15, 10:15] = True
    hair = hair_prior(parsing_hair, [(12, 12, 25, 25)])
    assert hair[10, 10] and hair[24, 24]
    soft = np.zeros((40, 40), dtype=np.uint8)
    soft[10:30, 12:28] = 180
    soft[20, 20] = 255
    neighbor = np.zeros_like(soft)
    neighbor[5, 5] = 255
    plan = build_prompt_plan(
        "left_forearm",
        soft,
        skeleton_points_xy=[(12, 20), (16, 20), (20, 20), (24, 20), (27, 20)],
        neighbor_priors=[neighbor],
        skeleton_samples=5,
    )
    assert (20, 20) in plan.positive_points
    assert 3 <= len(plan.positive_points) <= 8  # peak plus 3..7 samples
    assert (5, 5) in plan.negative_points
    assert plan.box_xyxy == (11, 9, 29, 31)
    prompts = write_geometry_artifacts(tmp_path, {"left_forearm": soft}, [plan], [request])
    overlay = render_prompt_overlay(Image.new("RGB", (40, 40)), plan, tmp_path / "debug.png")
    assert prompts.exists() and overlay.exists()
    document = json.loads(prompts.read_text())
    assert document["plans"][0]["multimask_output"] is True
    assert (tmp_path / "prior_left_forearm.png").exists()


def test_missing_keypoint_prompt_fallback_records_low_quality() -> None:
    parsing_only = np.zeros((10, 10), dtype=np.uint8)
    parsing_only[2:8, 2:8] = 100
    plan = build_prompt_plan(
        "left_calf",
        parsing_only,
        skeleton_points_xy=[],
        skeleton_samples=3,
        prior_quality="low",
    )
    assert plan.prior_quality == "low"
    assert len(plan.positive_points) == 1
    with pytest.raises(GeometryError, match="exactly five"):
        sample_cross_section_half_widths(parsing_only, (2, 2), (8, 8), stations=4)


def test_front_torso_partition_boundaries_breasts_and_navel_carve() -> None:
    torso = np.zeros((120, 100), dtype=bool)
    torso[20:105, 20:80] = True
    torso[50:53, 25:75] = True  # narrow profile supplies deterministic fold
    result = torso_partition_priors(
        torso,
        left_shoulder_xy=(75, 20),
        right_shoulder_xy=(25, 20),
        left_hip_xy=(70, 85),
        right_hip_xy=(30, 85),
        view="front",
    )

    required = {
        "chest_upper_torso",
        "left_breast",
        "right_breast",
        "abdomen_stomach",
        "belly_button",
        "pelvic_region",
        "left_hip",
        "right_hip",
    }
    assert required == set(result)
    assert result["left_breast"].any() and result["right_breast"].any()
    assert not (result["chest_upper_torso"] & result["left_breast"]).any()
    assert not (result["abdomen_stomach"] & result["belly_button"]).any()
    assert all(np.all(mask <= torso) for mask in result.values())
    left_x = np.nonzero(result["left_breast"])[1].mean()
    right_x = np.nonzero(result["right_breast"])[1].mean()
    assert left_x > right_x  # labels remain character-perspective in a front view
    profile = torso_partition_priors(
        torso,
        left_shoulder_xy=(25, 20),
        right_shoulder_xy=(75, 20),
        left_hip_xy=(30, 85),
        right_hip_xy=(70, 85),
        view="left_profile",
    )
    assert "left_breast" not in profile and "back_upper_torso" not in profile


def test_back_torso_is_mutually_exclusive_and_densepose_seeds_are_clipped() -> None:
    torso = np.zeros((100, 100), dtype=bool)
    torso[10:90, 20:80] = True
    left_seed = np.zeros_like(torso)
    right_seed = np.zeros_like(torso)
    left_seed[20:50, 20:48] = True
    right_seed[20:50, 52:80] = True
    result = torso_partition_priors(
        torso,
        left_shoulder_xy=(25, 15),
        right_shoulder_xy=(75, 15),
        left_hip_xy=(30, 75),
        right_hip_xy=(70, 75),
        view="back",
        densepose_left_scapula=left_seed,
        densepose_right_scapula=right_seed,
    )

    assert {
        "back_upper_torso",
        "back_lower_torso",
        "spine_back_center",
        "left_scapula_back",
        "right_scapula_back",
    } == set(result)
    assert not (result["back_upper_torso"] & result["back_lower_torso"]).any()
    assert not any(name.startswith("chest") or "breast" in name for name in result)
    assert np.all(result["left_scapula_back"] <= result["back_upper_torso"])
    assert np.count_nonzero(result["spine_back_center"][40]) == 5
