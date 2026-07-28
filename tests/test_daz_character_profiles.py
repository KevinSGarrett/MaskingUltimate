from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.scenes import (
    AGE_CATEGORIES,
    BODY_AXES,
    FACE_AXES,
    CharacterProfileError,
    build_character_profile_batch_report,
    generate_character_variation_profile,
    load_character_profile_policy,
    validate_character_profile_batch_report,
    validate_character_profile_policy,
    validate_character_variation_profile,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs" / "daz" / "character_profiles.yaml"


def _policy() -> dict:
    return load_character_profile_policy(POLICY)


def test_policy_closes_exact_axes_adult_categories_tiers_and_normalized_range() -> None:
    policy = _policy()
    assert tuple(policy["body_axes"]) == BODY_AXES
    assert tuple(policy["face_axes"]) == FACE_AXES
    assert tuple(policy["age_categories"]) == AGE_CATEGORIES
    assert policy["normalized_range"] == [-1.0, 1.0]
    assert {tier: row["weight"] for tier, row in policy["distribution_tiers"].items()} == {
        "central": 0.50,
        "moderate": 0.35,
        "validated_extreme": 0.15,
    }
    assert not any("minor" in category or "child" in category for category in AGE_CATEGORIES)


def test_profile_is_deterministic_bounded_correlated_and_fixed_vector() -> None:
    policy = _policy()
    first = generate_character_variation_profile(
        policy,
        seed=123,
        anatomy_configuration="adult_female_anatomy",
        age_appearance_category="adult_30_44",
    )
    second = generate_character_variation_profile(
        policy,
        seed=123,
        anatomy_configuration="adult_female_anatomy",
        age_appearance_category="adult_30_44",
    )
    assert first == second
    assert first["profile_id"] == "dcvp_011a60eb70aea1b00b8a956a"
    assert {
        key: first["body"]["values"][key]
        for key in ("stature", "body_mass", "shoulder_width", "hand_scale")
    } == {
        "stature": 0.090675,
        "body_mass": 0.072169,
        "shoulder_width": -0.486728,
        "hand_scale": 0.425876,
    }
    assert {
        key: first["face"]["values"][key] for key in ("head_width", "jaw_width", "lip_volume")
    } == {"head_width": -0.08997, "jaw_width": -0.529707, "lip_volume": 0.054676}
    assert all(-1 <= value <= 1 for value in first["body"]["values"].values())
    assert all(-1 <= value <= 1 for value in first["face"]["values"].values())
    assert first["constraints"]["all_passed"] is True
    validate_character_variation_profile(first, policy)


def test_age_profile_is_multichannel_coherent_monotonic_and_requires_final_readback() -> None:
    policy = _policy()
    means = []
    for category in AGE_CATEGORIES:
        profile = generate_character_variation_profile(
            policy,
            seed=123,
            anatomy_configuration="adult_female_anatomy",
            age_appearance_category=category,
        )
        values = list(profile["age"]["property_values"].values())
        means.append(sum(values) / len(values))
        assert max(values) - min(values) <= 0.20
        assert profile["age"]["asset_property_mapping_required"] is True
        assert profile["age"]["final_readback_required"] is True
    assert means == sorted(means)


def test_constraints_adjust_dependent_axes_without_escaping_normalized_bounds() -> None:
    policy = _policy()
    adjusted = None
    for seed in range(100):
        candidate = generate_character_variation_profile(
            policy,
            seed=seed,
            anatomy_configuration="adult_male_anatomy",
            age_appearance_category="adult_45_64",
        )
        if candidate["constraints"]["adjustments"]:
            adjusted = candidate
            break
    assert adjusted is not None
    values = adjusted["body"]["values"]
    constraints = policy["constraints"]
    assert (
        abs(values["shoulder_width"] - values["torso_length"])
        <= constraints["shoulder_torso_max_delta"]
    )
    assert abs(values["pelvis_width"] - values["hip_width"]) <= constraints["pelvis_hip_max_delta"]
    assert abs(values["arm_length"] - values["hand_scale"]) <= constraints["arm_hand_max_delta"]
    assert abs(values["leg_length"] - values["foot_scale"]) <= constraints["leg_foot_max_delta"]


def test_batch_report_proves_target_shares_correlations_bounds_and_replay() -> None:
    policy = _policy()
    report = build_character_profile_batch_report(policy, seed_start=0, samples_per_stratum=100)
    assert report["profile_count"] == 800
    assert report["tier_target_shares"] == {
        "central": 0.5,
        "moderate": 0.35,
        "validated_extreme": 0.15,
    }
    assert report["tier_max_abs_deviation"] == 0.017102
    assert report["distribution_passed"] is True
    assert report["correlations_passed"] is True
    assert min(report["correlations"].values()) >= 0.25
    assert report["bounds_passed"] is True
    assert report["constraints_passed"] is True
    validate_character_profile_batch_report(report, policy)


def test_policy_profile_and_batch_tampering_or_sparse_report_fail_closed() -> None:
    policy = _policy()
    duplicate_axis = deepcopy(policy)
    duplicate_axis["body_axes"]["invented_axis"] = duplicate_axis["body_axes"]["stature"]
    with pytest.raises(CharacterProfileError, match="profile_policy_axes_invalid"):
        validate_character_profile_policy(duplicate_axis)

    with pytest.raises(CharacterProfileError, match="profile_batch_request_invalid"):
        build_character_profile_batch_report(policy, seed_start=0, samples_per_stratum=49)

    profile = generate_character_variation_profile(
        policy,
        seed=1,
        anatomy_configuration="adult_male_anatomy",
        age_appearance_category="adult_21_29",
    )
    tampered = deepcopy(profile)
    tampered["body"]["values"]["stature"] = 0.0
    with pytest.raises(CharacterProfileError, match="profile_replay_mismatch"):
        validate_character_variation_profile(tampered, policy)

    report = build_character_profile_batch_report(policy, seed_start=1000, samples_per_stratum=50)
    changed_report = deepcopy(report)
    changed_report["body_tier_shares"]["central"] = 0.5
    with pytest.raises(CharacterProfileError, match="profile_batch_replay_mismatch"):
        validate_character_profile_batch_report(changed_report, policy)


def test_profile_cli_generates_reports_validates_and_publishes_idempotently(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    profile_output = tmp_path / "profiles"
    arguments = [
        "daz",
        "recipes",
        "generate-profile",
        "--seed",
        "123",
        "--anatomy-configuration",
        "adult_female_anatomy",
        "--age-appearance-category",
        "adult_30_44",
        "--output",
        str(profile_output),
    ]
    first = runner.invoke(main, arguments)
    second = runner.invoke(main, arguments)
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    first_envelope = json.loads(first.output)
    second_envelope = json.loads(second.output)
    assert first_envelope["data"]["profile_sha256"] == second_envelope["data"]["profile_sha256"]
    assert first_envelope["data"]["publication"]["published"] is True
    assert second_envelope["data"]["publication"]["published"] is False
    profile_path = first_envelope["data"]["publication"]["path"]
    validated = runner.invoke(main, ["daz", "recipes", "validate-profile", profile_path])
    assert validated.exit_code == 0, validated.output

    report_output = tmp_path / "reports"
    reported = runner.invoke(
        main,
        [
            "daz",
            "recipes",
            "profile-report",
            "--samples-per-stratum",
            "50",
            "--output",
            str(report_output),
        ],
    )
    assert reported.exit_code == 0, reported.output
    report_envelope = json.loads(reported.output)
    assert report_envelope["data"]["profile_count"] == 400
    report_path = report_envelope["data"]["publication"]["path"]
    validated = runner.invoke(main, ["daz", "recipes", "validate-profile", report_path])
    assert validated.exit_code == 0, validated.output
