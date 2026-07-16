"""Deterministic correlated, bounded adult body/face/age appearance profiles."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml

from ...validation import require_valid_document

BODY_AXES = (
    "stature",
    "overall_scale",
    "body_mass",
    "body_fat_distribution",
    "muscularity_total",
    "upper_body_muscularity",
    "lower_body_muscularity",
    "shoulder_width",
    "chest_depth",
    "chest_or_bust_volume",
    "waist_width",
    "abdomen_prominence",
    "pelvis_width",
    "hip_width",
    "glute_volume",
    "torso_length",
    "arm_length",
    "forearm_proportion",
    "hand_scale",
    "leg_length",
    "thigh_volume",
    "calf_volume",
    "foot_scale",
    "head_scale",
    "neck_length",
)
FACE_AXES = (
    "head_width",
    "head_height",
    "head_depth",
    "jaw_width",
    "jaw_angle",
    "chin_projection",
    "chin_height",
    "cheek_volume",
    "cheek_height",
    "forehead_shape",
    "nose_length",
    "nose_width",
    "nose_projection",
    "eye_spacing",
    "eye_size",
    "eye_tilt",
    "brow_shape",
    "lip_shape",
    "lip_volume",
    "ear_size",
    "ear_projection",
    "neck_thickness",
)
AGE_CATEGORIES = (
    "adult_21_29",
    "adult_30_44",
    "adult_45_64",
    "adult_65_plus",
)
ANATOMY_CONFIGURATIONS = ("adult_male_anatomy", "adult_female_anatomy")
TIERS = ("central", "moderate", "validated_extreme")


class CharacterProfileError(ValueError):
    """A character-profile policy or generated profile is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_character_profile_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_character_profile_policy(document)
    return document


def validate_character_profile_policy(policy: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != "1.0.0" or policy.get("profile_version") != "1.0.0":
        raise CharacterProfileError("profile_policy_version_invalid", "versions must be 1.0.0")
    if policy.get("algorithm") != "sha256_namespaced_box_muller_factor_model_v1":
        raise CharacterProfileError(
            "profile_policy_algorithm_invalid", str(policy.get("algorithm"))
        )
    if policy.get("normalized_range") != [-1.0, 1.0]:
        raise CharacterProfileError(
            "profile_policy_range_invalid", str(policy.get("normalized_range"))
        )
    tiers = policy.get("distribution_tiers")
    if not isinstance(tiers, Mapping) or tuple(tiers) != TIERS:
        raise CharacterProfileError("profile_policy_tiers_invalid", str(tiers))
    weight_sum = 0.0
    previous_max = 0.0
    for tier in TIERS:
        entry = tiers[tier]
        if not isinstance(entry, Mapping):
            raise CharacterProfileError("profile_policy_tiers_invalid", tier)
        weight = entry.get("weight")
        minimum = entry.get("minimum_abs")
        maximum = entry.get("maximum_abs")
        if (
            not all(
                isinstance(value, (int, float)) and math.isfinite(float(value))
                for value in (weight, minimum, maximum)
            )
            or not 0 < float(weight) < 1
            or float(minimum) != previous_max
            or not float(minimum) < float(maximum) <= 1
        ):
            raise CharacterProfileError("profile_policy_tiers_invalid", tier)
        weight_sum += float(weight)
        previous_max = float(maximum)
    if not math.isclose(weight_sum, 1.0, abs_tol=1e-12) or previous_max != 1.0:
        raise CharacterProfileError("profile_policy_tiers_invalid", "weights/ranges")
    _validate_axis_policy(
        policy,
        axes_field="body_axes",
        factors_field="body_factors",
        expected_axes=BODY_AXES,
    )
    _validate_axis_policy(
        policy,
        axes_field="face_axes",
        factors_field="face_factors",
        expected_axes=FACE_AXES,
    )
    constraints = policy.get("constraints")
    expected_constraints = {
        "shoulder_torso_max_delta",
        "pelvis_hip_max_delta",
        "arm_hand_max_delta",
        "leg_foot_max_delta",
        "stature_scale_max_delta",
    }
    if (
        not isinstance(constraints, Mapping)
        or set(constraints) != expected_constraints
        or any(
            not isinstance(value, (int, float)) or not 0 < float(value) <= 1
            for value in constraints.values()
        )
    ):
        raise CharacterProfileError("profile_policy_constraints_invalid", str(constraints))
    categories = policy.get("age_categories")
    if not isinstance(categories, Mapping) or tuple(categories) != AGE_CATEGORIES:
        raise CharacterProfileError("profile_policy_age_categories_invalid", str(categories))
    for category, entry in categories.items():
        if not isinstance(entry, Mapping):
            raise CharacterProfileError("profile_policy_age_categories_invalid", category)
        if (
            not 0 <= float(entry.get("center", -1)) <= 1
            or not 0 < float(entry.get("spread", 0)) <= 0.25
        ):
            raise CharacterProfileError("profile_policy_age_categories_invalid", category)
        for field in (
            "skin_detail_tags",
            "hair_density_tags",
            "hair_color_tags",
            "posture_tags",
        ):
            values = entry.get(field)
            if not isinstance(values, list) or not values or len(values) != len(set(values)):
                raise CharacterProfileError(
                    "profile_policy_age_categories_invalid", f"{category}:{field}"
                )
    expected_channels = [
        "mf://age/face",
        "mf://age/body",
        "mf://age/skin",
        "mf://age/posture",
        "mf://age/hair",
    ]
    if policy.get("age_channels") != expected_channels:
        raise CharacterProfileError(
            "profile_policy_age_channels_invalid", str(policy.get("age_channels"))
        )


def generate_character_variation_profile(
    policy: Mapping[str, Any],
    *,
    seed: int,
    anatomy_configuration: str,
    age_appearance_category: str,
) -> dict[str, Any]:
    """Generate one normalized profile; asset-specific morph mapping remains a later bound step."""

    validate_character_profile_policy(policy)
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed < 2**64:
        raise CharacterProfileError("profile_seed_invalid", str(seed))
    if anatomy_configuration not in ANATOMY_CONFIGURATIONS:
        raise CharacterProfileError("profile_anatomy_configuration_invalid", anatomy_configuration)
    if age_appearance_category not in AGE_CATEGORIES:
        raise CharacterProfileError("profile_age_category_invalid", age_appearance_category)
    namespace = f"{anatomy_configuration}:{age_appearance_category}"
    body_factors = {
        factor: _normal(seed, f"{namespace}:body_factor:{factor}")
        for factor in policy["body_factors"]
    }
    face_factors = {
        factor: _normal(seed, f"{namespace}:face_factor:{factor}")
        for factor in policy["face_factors"]
    }
    body_values, body_tiers = _sample_axes(
        policy,
        seed=seed,
        namespace=f"{namespace}:body",
        axes_field="body_axes",
        factors=body_factors,
    )
    face_values, face_tiers = _sample_axes(
        policy,
        seed=seed,
        namespace=f"{namespace}:face",
        axes_field="face_axes",
        factors=face_factors,
    )
    adjustments = _apply_body_constraints(body_values, policy["constraints"])
    age_shared = _normal(seed, f"{namespace}:age_shared")
    age = _build_age_profile(
        policy,
        seed=seed,
        namespace=namespace,
        category=age_appearance_category,
        shared=age_shared,
    )
    policy_sha = _canonical_sha(policy)
    content = {
        "policy_version": policy["profile_version"],
        "policy_sha256": policy_sha,
        "seed": seed,
        "anatomy_configuration": anatomy_configuration,
        "age_appearance_category": age_appearance_category,
        "latent_factors": {
            "body": _round_mapping(body_factors),
            "face": _round_mapping(face_factors),
            "age_shared": round(age_shared, 8),
        },
        "body": {
            "values": _round_mapping(body_values, places=6),
            "sampling_tiers": body_tiers,
            "strata": _body_strata(body_values),
        },
        "face": {
            "values": _round_mapping(face_values, places=6),
            "sampling_tiers": face_tiers,
            "strata": _face_strata(face_values),
        },
        "age": age,
        "constraints": {"all_passed": True, "adjustments": adjustments},
    }
    digest = _canonical_sha(content)
    document = {
        "schema_version": "1.0.0",
        "profile_id": f"dcvp_{digest[:24]}",
        "profile_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_character_variation_profile")
    return document


def validate_character_variation_profile(
    profile: Mapping[str, Any], policy: Mapping[str, Any]
) -> None:
    """Replay exact deterministic generation and reject any profile or policy drift."""

    require_valid_document(profile, "daz_character_variation_profile")
    expected = generate_character_variation_profile(
        policy,
        seed=profile["seed"],
        anatomy_configuration=profile["anatomy_configuration"],
        age_appearance_category=profile["age_appearance_category"],
    )
    if profile != expected:
        raise CharacterProfileError("profile_replay_mismatch", str(profile["profile_id"]))


def build_character_profile_batch_report(
    policy: Mapping[str, Any], *, seed_start: int, samples_per_stratum: int
) -> dict[str, Any]:
    """Measure bounds, requested tier shares, constraints, and declared correlations."""

    validate_character_profile_policy(policy)
    if (
        not isinstance(seed_start, int)
        or seed_start < 0
        or not isinstance(samples_per_stratum, int)
        or samples_per_stratum < 50
    ):
        raise CharacterProfileError(
            "profile_batch_request_invalid", f"{seed_start}:{samples_per_stratum}"
        )
    profiles = []
    for anatomy_index, anatomy in enumerate(ANATOMY_CONFIGURATIONS):
        for age_index, category in enumerate(AGE_CATEGORIES):
            offset = (anatomy_index * len(AGE_CATEGORIES) + age_index) * samples_per_stratum
            for sample_index in range(samples_per_stratum):
                profiles.append(
                    generate_character_variation_profile(
                        policy,
                        seed=seed_start + offset + sample_index,
                        anatomy_configuration=anatomy,
                        age_appearance_category=category,
                    )
                )
    body_tiers = _tier_summary(profiles, domain="body")
    face_tiers = _tier_summary(profiles, domain="face")
    target_shares = {tier: float(policy["distribution_tiers"][tier]["weight"]) for tier in TIERS}
    tier_max_abs_deviation = round(
        max(
            abs(observed[tier] - target_shares[tier])
            for observed in (body_tiers, face_tiers)
            for tier in TIERS
        ),
        6,
    )
    correlations = {
        "body_mass__abdomen_prominence": _correlation(
            profiles, "body", "body_mass", "abdomen_prominence"
        ),
        "muscularity_total__upper_body_muscularity": _correlation(
            profiles, "body", "muscularity_total", "upper_body_muscularity"
        ),
        "arm_length__leg_length": _correlation(profiles, "body", "arm_length", "leg_length"),
        "head_width__head_depth": _correlation(profiles, "face", "head_width", "head_depth"),
        "jaw_width__jaw_angle": _correlation(profiles, "face", "jaw_width", "jaw_angle"),
        "lip_shape__lip_volume": _correlation(profiles, "face", "lip_shape", "lip_volume"),
    }
    content = {
        "policy_version": policy["profile_version"],
        "policy_sha256": _canonical_sha(policy),
        "seed_start": seed_start,
        "samples_per_stratum": samples_per_stratum,
        "profile_count": len(profiles),
        "anatomy_configurations": list(ANATOMY_CONFIGURATIONS),
        "age_categories": list(AGE_CATEGORIES),
        "tier_target_shares": target_shares,
        "body_tier_shares": body_tiers,
        "face_tier_shares": face_tiers,
        "tier_max_abs_deviation": tier_max_abs_deviation,
        "distribution_passed": tier_max_abs_deviation <= 0.03,
        "correlations": correlations,
        "declared_correlation_floor": 0.25,
        "correlations_passed": all(value >= 0.25 for value in correlations.values()),
        "bounds_passed": all(
            -1 <= value <= 1
            for profile in profiles
            for domain in ("body", "face")
            for value in profile[domain]["values"].values()
        ),
        "constraints_passed": all(profile["constraints"]["all_passed"] for profile in profiles),
        "adjusted_profile_count": sum(
            bool(profile["constraints"]["adjustments"]) for profile in profiles
        ),
        "profile_set_sha256": _canonical_sha(
            {"profile_sha256": [profile["profile_sha256"] for profile in profiles]}
        ),
    }
    digest = _canonical_sha(content)
    document = {
        "schema_version": "1.0.0",
        "report_id": f"dcpr_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_character_profile_batch_report")
    return document


def validate_character_profile_batch_report(
    report: Mapping[str, Any], policy: Mapping[str, Any]
) -> None:
    """Recompute every sampled profile and exact aggregate report."""

    require_valid_document(report, "daz_character_profile_batch_report")
    expected = build_character_profile_batch_report(
        policy,
        seed_start=report["seed_start"],
        samples_per_stratum=report["samples_per_stratum"],
    )
    if report != expected:
        raise CharacterProfileError("profile_batch_replay_mismatch", str(report["report_id"]))


def publish_character_profile_document(
    document: Mapping[str, Any], output_root: Path, *, document_id: str
) -> tuple[Path, bool]:
    """Atomically publish one immutable validated profile or batch report."""

    if not isinstance(document_id, str) or not document_id:
        raise CharacterProfileError("profile_document_id_invalid", str(document_id))
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{document_id}.json"
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise CharacterProfileError("profile_publication_conflict", str(target))
        return target, False
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=root
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target, True


def _validate_axis_policy(
    policy: Mapping[str, Any],
    *,
    axes_field: str,
    factors_field: str,
    expected_axes: tuple[str, ...],
) -> None:
    factors = policy.get(factors_field)
    axes = policy.get(axes_field)
    if (
        not isinstance(factors, list)
        or not factors
        or len(factors) != len(set(factors))
        or not isinstance(axes, Mapping)
        or tuple(axes) != expected_axes
    ):
        raise CharacterProfileError("profile_policy_axes_invalid", axes_field)
    for axis, entry in axes.items():
        if not isinstance(entry, Mapping) or set(entry) != {"loadings", "noise_weight"}:
            raise CharacterProfileError("profile_policy_axis_invalid", f"{axes_field}:{axis}")
        loadings = entry["loadings"]
        noise = entry["noise_weight"]
        if (
            not isinstance(loadings, Mapping)
            or not loadings
            or any(factor not in factors for factor in loadings)
            or any(
                not isinstance(value, (int, float)) or not math.isfinite(float(value))
                for value in loadings.values()
            )
            or not isinstance(noise, (int, float))
            or not 0 < float(noise) <= 1
        ):
            raise CharacterProfileError("profile_policy_axis_invalid", f"{axes_field}:{axis}")


def _sample_axes(
    policy: Mapping[str, Any],
    *,
    seed: int,
    namespace: str,
    axes_field: str,
    factors: Mapping[str, float],
) -> tuple[dict[str, float], dict[str, str]]:
    values = {}
    tiers = {}
    tier_factors = {
        factor: _normal(seed, f"{namespace}:tier_factor:{factor}") for factor in factors
    }
    for axis, entry in policy[axes_field].items():
        noise = float(entry["noise_weight"])
        numerator = sum(
            float(weight) * factors[factor] for factor, weight in entry["loadings"].items()
        )
        numerator += noise * _normal(seed, f"{namespace}:axis_noise:{axis}")
        denominator = math.sqrt(
            sum(float(weight) ** 2 for weight in entry["loadings"].values()) + noise**2
        )
        z_value = numerator / denominator
        tier_numerator = sum(
            float(weight) * tier_factors[factor] for factor, weight in entry["loadings"].items()
        )
        tier_numerator += noise * _normal(seed, f"{namespace}:tier_noise:{axis}")
        tier_z = tier_numerator / denominator
        tier = _choose_tier(policy, 0.5 * (1.0 + math.erf(tier_z / math.sqrt(2.0))))
        tier_policy = policy["distribution_tiers"][tier]
        half_normal_percentile = math.erf(abs(z_value) / math.sqrt(2.0))
        blended = 0.8 * half_normal_percentile + 0.2 * _uniform(
            seed, f"{namespace}:magnitude:{axis}"
        )
        magnitude = float(tier_policy["minimum_abs"]) + blended * (
            float(tier_policy["maximum_abs"]) - float(tier_policy["minimum_abs"])
        )
        sign = -1.0 if z_value < 0 else 1.0
        values[axis] = max(-1.0, min(1.0, sign * magnitude))
        tiers[axis] = tier
    return values, tiers


def _choose_tier(policy: Mapping[str, Any], value: float) -> str:
    cumulative = 0.0
    for tier in TIERS:
        cumulative += float(policy["distribution_tiers"][tier]["weight"])
        if value < cumulative:
            return tier
    return TIERS[-1]


def _apply_body_constraints(values: dict[str, float], policy: Mapping[str, Any]) -> list[str]:
    constraints = (
        ("shoulder_width", "torso_length", "shoulder_torso_max_delta"),
        ("pelvis_width", "hip_width", "pelvis_hip_max_delta"),
        ("arm_length", "hand_scale", "arm_hand_max_delta"),
        ("leg_length", "foot_scale", "leg_foot_max_delta"),
        ("stature", "overall_scale", "stature_scale_max_delta"),
    )
    adjustments = []
    for anchor, dependent, policy_key in constraints:
        maximum = float(policy[policy_key])
        delta = values[dependent] - values[anchor]
        if abs(delta) > maximum:
            values[dependent] = max(-1.0, min(1.0, values[anchor] + math.copysign(maximum, delta)))
            adjustments.append(f"{dependent}:clamped_to_{anchor}:{policy_key}")
    return adjustments


def _build_age_profile(
    policy: Mapping[str, Any],
    *,
    seed: int,
    namespace: str,
    category: str,
    shared: float,
) -> dict[str, Any]:
    entry = policy["age_categories"][category]
    values = {}
    for channel in policy["age_channels"]:
        independent = _normal(seed, f"{namespace}:age_channel:{channel}")
        correlated = (0.85 * shared + 0.35 * independent) / math.sqrt(0.85**2 + 0.35**2)
        value = float(entry["center"]) + float(entry["spread"]) * max(-1.0, min(1.0, correlated))
        values[channel] = round(max(0.0, min(1.0, value)), 6)
    content = {
        "category": category,
        "property_values": values,
        "skin_detail_tags": list(entry["skin_detail_tags"]),
        "hair_density_tags": list(entry["hair_density_tags"]),
        "hair_color_tags": list(entry["hair_color_tags"]),
        "posture_tags": list(entry["posture_tags"]),
    }
    return {
        "profile_id": f"age_{_canonical_sha(content)[:24]}",
        "property_values": values,
        "skin_detail_tags": content["skin_detail_tags"],
        "hair_density_tags": content["hair_density_tags"],
        "hair_color_tags": content["hair_color_tags"],
        "posture_tags": content["posture_tags"],
        "asset_property_mapping_required": True,
        "final_readback_required": True,
    }


def _body_strata(values: Mapping[str, float]) -> dict[str, str]:
    return {
        "stature": _three_bin(values["stature"], "short", "medium", "tall"),
        "body_mass": _three_bin(values["body_mass"], "low", "medium", "high"),
        "muscularity": _three_bin(values["muscularity_total"], "low", "medium", "high"),
        "shoulders": _three_bin(values["shoulder_width"], "narrow", "medium", "broad"),
        "pelvis_hips": _three_bin(
            (values["pelvis_width"] + values["hip_width"]) / 2,
            "narrow",
            "medium",
            "broad",
        ),
        "torso": _three_bin(values["torso_length"], "short", "medium", "long"),
        "limbs": _three_bin(
            (values["arm_length"] + values["leg_length"]) / 2,
            "short",
            "medium",
            "long",
        ),
        "hands": _three_bin(values["hand_scale"], "small", "medium", "large"),
        "feet": _three_bin(values["foot_scale"], "small", "medium", "large"),
    }


def _face_strata(values: Mapping[str, float]) -> dict[str, str]:
    return {
        "head_frame": _three_bin(values["head_width"], "narrow", "medium", "broad"),
        "jaw": _three_bin(values["jaw_width"], "narrow", "medium", "broad"),
        "features": _three_bin(values["eye_size"], "small", "medium", "large"),
        "soft_tissue": _three_bin(values["cheek_volume"], "low", "medium", "high"),
    }


def _three_bin(value: float, low: str, middle: str, high: str) -> str:
    if value < -1 / 3:
        return low
    if value > 1 / 3:
        return high
    return middle


def _tier_summary(profiles: list[Mapping[str, Any]], *, domain: str) -> dict[str, float]:
    counts = {tier: 0 for tier in TIERS}
    total = 0
    for profile in profiles:
        for tier in profile[domain]["sampling_tiers"].values():
            counts[tier] += 1
            total += 1
    return {tier: round(counts[tier] / total, 6) for tier in TIERS}


def _correlation(profiles: list[Mapping[str, Any]], domain: str, first: str, second: str) -> float:
    xs = [float(profile[domain]["values"][first]) for profile in profiles]
    ys = [float(profile[domain]["values"][second]) for profile in profiles]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    denominator = math.sqrt(sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys))
    return round(numerator / denominator if denominator else 0.0, 6)


def _uniform(seed: int, namespace: str) -> float:
    digest = hashlib.sha256(f"{seed}:{namespace}".encode("utf-8")).digest()
    return (int.from_bytes(digest[:8], "big") + 0.5) / 2**64


def _normal(seed: int, namespace: str) -> float:
    first = _uniform(seed, f"{namespace}:u1")
    second = _uniform(seed, f"{namespace}:u2")
    return math.sqrt(-2.0 * math.log(first)) * math.cos(2.0 * math.pi * second)


def _round_mapping(values: Mapping[str, float], *, places: int = 8) -> dict[str, float]:
    return {key: round(float(value), places) for key, value in values.items()}


def _canonical_sha(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


__all__ = [
    "AGE_CATEGORIES",
    "ANATOMY_CONFIGURATIONS",
    "BODY_AXES",
    "CharacterProfileError",
    "FACE_AXES",
    "build_character_profile_batch_report",
    "generate_character_variation_profile",
    "load_character_profile_policy",
    "publish_character_profile_document",
    "validate_character_profile_policy",
    "validate_character_profile_batch_report",
    "validate_character_variation_profile",
]
