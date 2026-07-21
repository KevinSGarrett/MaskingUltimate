"""STATIC solo engineering fixture-set contract for DAZ (MF-P9-06.10).

Builds a deterministic 24–100 scene engineering fixture set with policy-aligned
coverage dimensions, exact named random streams, and sealable synthetic
resolved-recipe drafts. Fixtures remain unrendered/unaccepted and are never
training-eligible. No live DAZ execution, qualified assets, or visual
acceptance is claimed.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from ...validation import ArtifactValidationError, require_valid_document
from .recipe import (
    REQUIRED_RANDOM_STREAMS,
    canonical_json_bytes,
    derive_named_random_streams,
    seal_resolved_scene_recipe,
    validate_resolved_scene_recipe,
)

PROOF_TIER = "STATIC_PASS"
AUTHORITY = "daz_engineering_fixture_set_static_only_unrendered"
ARTIFACT_TYPE = "daz_engineering_fixture_set"
SCHEMA_VERSION = "1.1.0"
MIN_FIXTURES = 24
MAX_FIXTURES = 100
DEFAULT_MASTER_SEED = 20260719
CURRICULUM_STAGE = "engineering"

# Policy-aligned closed vocabularies (solo_pose / appearance / formation).
POSE_FAMILIES = (
    "neutral_calibration",
    "locomotion",
    "seated",
    "crouching_kneeling",
    "lying_reclining",
    "athletic_dance_flexibility",
)
FRAMING_PROFILES = (
    "full_body_margin",
    "three_quarter_body",
    "waist_up",
    "head_shoulders",
)
WARDROBE_STATES = (
    "unclothed",
    "underwear_only",
    "standard_casual",
    "layered_clothing",
)
LIGHTING_PROFILES = (
    "front_soft",
    "backlight_rim",
    "overcast_diffuse",
    "indoor_practical_warm",
)
ANATOMY_CONFIGURATIONS = (
    "adult_female_anatomy",
    "adult_male_anatomy",
)
PROP_MODES = (
    "none",
    "support_surface",
    "handheld_worn",
    "occluder",
)

COVERAGE_DIMENSIONS = (
    "pose_family",
    "framing_profile",
    "wardrobe_state",
    "lighting_profile",
    "anatomy_configuration",
    "prop_mode",
)

COVERAGE_VALUE_SETS: dict[str, tuple[str, ...]] = {
    "pose_family": POSE_FAMILIES,
    "framing_profile": FRAMING_PROFILES,
    "wardrobe_state": WARDROBE_STATES,
    "lighting_profile": LIGHTING_PROFILES,
    "anatomy_configuration": ANATOMY_CONFIGURATIONS,
    "prop_mode": PROP_MODES,
}

_FRAMING_CAMERA = {
    "full_body_margin": {
        "focal_length_mm": 35.0,
        "position_cm": [0.0, 140.0, 520.0],
        "target_cm": [0.0, 95.0, 0.0],
    },
    "three_quarter_body": {
        "focal_length_mm": 50.0,
        "position_cm": [0.0, 145.0, 380.0],
        "target_cm": [0.0, 110.0, 0.0],
    },
    "waist_up": {
        "focal_length_mm": 70.0,
        "position_cm": [0.0, 150.0, 260.0],
        "target_cm": [0.0, 130.0, 0.0],
    },
    "head_shoulders": {
        "focal_length_mm": 85.0,
        "position_cm": [0.0, 160.0, 160.0],
        "target_cm": [0.0, 155.0, 0.0],
    },
}

_WARDROBE_ASSETS = {
    "unclothed": [],
    "underwear_only": ["daz_asset_eng_underwear"],
    "standard_casual": ["daz_asset_eng_top", "daz_asset_eng_pants"],
    "layered_clothing": [
        "daz_asset_eng_top",
        "daz_asset_eng_pants",
        "daz_asset_eng_outerwear",
    ],
}

_PROP_ENTRIES = {
    "none": [],
    "support_surface": [
        {
            "object_id": "prop_support_0",
            "asset_id": "daz_asset_eng_support",
            "prop_mode": "support_surface",
        }
    ],
    "handheld_worn": [
        {
            "object_id": "prop_handheld_0",
            "asset_id": "daz_asset_eng_handheld",
            "prop_mode": "handheld_worn",
        }
    ],
    "occluder": [
        {
            "object_id": "prop_occluder_0",
            "asset_id": "daz_asset_eng_occluder",
            "prop_mode": "occluder",
        }
    ],
}


class EngineeringFixtureError(ValueError):
    """Engineering fixture-set contract violated."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def _canonical_sha(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(document)).hexdigest()


def _coverage_for_index(index: int) -> dict[str, str]:
    return {
        "pose_family": POSE_FAMILIES[index % len(POSE_FAMILIES)],
        "framing_profile": FRAMING_PROFILES[index % len(FRAMING_PROFILES)],
        "wardrobe_state": WARDROBE_STATES[index % len(WARDROBE_STATES)],
        "lighting_profile": LIGHTING_PROFILES[index % len(LIGHTING_PROFILES)],
        "anatomy_configuration": ANATOMY_CONFIGURATIONS[index % len(ANATOMY_CONFIGURATIONS)],
        "prop_mode": PROP_MODES[index % len(PROP_MODES)],
    }


def _assert_exact_streams(streams: Mapping[str, Any], *, scene_id: str) -> None:
    expected_keys = set(REQUIRED_RANDOM_STREAMS)
    actual_keys = set(streams.keys())
    if actual_keys != expected_keys:
        raise EngineeringFixtureError(
            "random_stream_keys_invalid",
            f"{scene_id}: expected {sorted(expected_keys)}, got {sorted(actual_keys)}",
        )
    for key, value in streams.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise EngineeringFixtureError("random_stream_value_invalid", f"{scene_id}:{key}")


def _synthetic_resolved_recipe_draft(
    *,
    scene_id: str,
    master_seed: int,
    coverage: Mapping[str, str],
    streams: Mapping[str, int],
) -> dict[str, Any]:
    """Build a sealable synthetic solo recipe draft from engineering coverage.

    Uses fixture-only synthetic asset IDs. Does not claim live/qualified assets.
    """

    anatomy = coverage["anatomy_configuration"]
    wardrobe_state = coverage["wardrobe_state"]
    framing = coverage["framing_profile"]
    camera = _FRAMING_CAMERA[framing]
    male = anatomy == "adult_male_anatomy"
    figure_asset = "daz_asset_eng_g9_male" if male else "daz_asset_eng_g9_female"
    preset_asset = "daz_asset_eng_character_male" if male else "daz_asset_eng_character_female"
    anatomy_asset = "daz_asset_eng_male_anatomy" if male else "daz_asset_eng_female_anatomy"
    mapping_ids = (
        ["map_g9_v1_eng", "map_g9_male_anatomy_eng"]
        if male
        else ["map_g9_v1_eng", "map_g9_female_anatomy_eng"]
    )
    index_token = scene_id.rsplit("_", 1)[-1]
    return {
        "schema_version": "1.0.0",
        "scene_id": scene_id,
        "scene_family_id": f"daz_family_eng_{index_token}",
        "scene_variant_id": f"daz_variant_eng_{index_token}",
        "master_seed": master_seed,
        "named_random_streams": dict(streams),
        "registry_snapshot_id": "daz_registry_engineering_static",
        "runtime_snapshot_id": "daz_runtime_engineering_static",
        "script_bundle_sha256": "e" * 64,
        "ontology": {"name": "body_parts_v1", "snapshot_sha256": "f" * 64},
        "render_profile_id": "engineering_unrendered_static_v1",
        "coverage_demand_ids": [
            "cov_engineering_solo",
            f"cov_pose_{coverage['pose_family']}",
            f"cov_wardrobe_{wardrobe_state}",
        ],
        "characters": [
            {
                "construction_id": "c0",
                "requested_promoted_id": None,
                "figure_asset_id": figure_asset,
                "character_preset_asset_id": preset_asset,
                "body_profile_id": f"body_profile_eng_{index_token}",
                "face_profile_id": f"face_profile_eng_{index_token}",
                "age_appearance_category": "adult_30_44",
                "anatomy_configuration": anatomy,
                "anatomy_asset_ids": [anatomy_asset],
                "skin_material_asset_id": "daz_asset_eng_skin",
                "hair_asset_id": "daz_asset_eng_hair",
                "wardrobe_asset_ids": list(_WARDROBE_ASSETS[wardrobe_state]),
                "morph_values": {
                    "prop://body/height": 0.12,
                    "prop://body/muscularity": 0.24,
                },
                "pose_asset_id": f"daz_asset_eng_pose_{coverage['pose_family']}",
                "pose_adjustments": {
                    "pose_family": coverage["pose_family"],
                    "engineering_unrendered": True,
                },
                "mapping_bundle_ids": mapping_ids,
                "world_transform": {
                    "translation_cm": [0.0, 0.0, 0.0],
                    "rotation_deg": [0.0, 0.0, 0.0],
                    "scale": 1.0,
                },
            }
        ],
        "relationship_template": None,
        "camera": {
            "projection": "perspective",
            "focal_length_mm": camera["focal_length_mm"],
            "position_cm": list(camera["position_cm"]),
            "target_cm": list(camera["target_cm"]),
            "roll_deg": 0.0,
            "resolution": [1024, 1024],
            "crop": [0, 0, 1024, 1024],
        },
        "lighting": {
            "profile_id": coverage["lighting_profile"],
            "parameter_seed": streams["lighting"],
        },
        "environment": {
            "asset_id": "daz_asset_eng_studio",
            "background_profile": "mid_neutral",
        },
        "props": deepcopy(_PROP_ENTRIES[coverage["prop_mode"]]),
    }


def _coverage_summary(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    observed: dict[str, list[str]] = {}
    for dimension, allowed in COVERAGE_VALUE_SETS.items():
        values = sorted({item["coverage"][dimension] for item in fixtures})
        missing = [value for value in allowed if value not in values]
        if missing:
            raise EngineeringFixtureError(
                "coverage_marginal_incomplete",
                f"{dimension} missing {missing}",
            )
        unexpected = [value for value in values if value not in allowed]
        if unexpected:
            raise EngineeringFixtureError(
                "coverage_value_unexpected",
                f"{dimension} unexpected {unexpected}",
            )
        observed[dimension] = values
    return {
        "dimensions": list(COVERAGE_DIMENSIONS),
        "value_sets": {key: list(values) for key, values in COVERAGE_VALUE_SETS.items()},
        "observed_values": observed,
        "full_marginal_coverage": True,
    }


def build_engineering_fixture_set(
    *,
    fixture_count: int = MIN_FIXTURES,
    master_seed: int = DEFAULT_MASTER_SEED,
) -> dict[str, Any]:
    """Build a deterministic unrendered solo engineering fixture set."""

    if not isinstance(fixture_count, int) or isinstance(fixture_count, bool):
        raise EngineeringFixtureError("fixture_count_invalid", str(fixture_count))
    if not MIN_FIXTURES <= fixture_count <= MAX_FIXTURES:
        raise EngineeringFixtureError(
            "fixture_count_out_of_range",
            f"expected {MIN_FIXTURES}..{MAX_FIXTURES}, got {fixture_count}",
        )
    if (
        not isinstance(master_seed, int)
        or isinstance(master_seed, bool)
        or not 0 <= master_seed < 2**63
    ):
        raise EngineeringFixtureError("master_seed_invalid", str(master_seed))

    fixtures: list[dict[str, Any]] = []
    scene_ids: set[str] = set()
    recipe_hashes: set[str] = set()
    resolved_hashes: set[str] = set()
    for index in range(fixture_count):
        scene_id = f"daz_scene_eng_{index:03d}"
        if scene_id in scene_ids:
            raise EngineeringFixtureError("duplicate_scene_id", scene_id)
        scene_ids.add(scene_id)
        coverage = _coverage_for_index(index)
        streams = derive_named_random_streams(master_seed, scene_id)
        _assert_exact_streams(streams, scene_id=scene_id)
        recipe_stub = {
            "scene_id": scene_id,
            "master_seed": master_seed,
            "person_count": 1,
            "curriculum_stage": CURRICULUM_STAGE,
            "coverage": coverage,
            "named_random_streams": streams,
            "live_qualified_assets": False,
        }
        recipe_sha = _canonical_sha(recipe_stub)
        if recipe_sha in recipe_hashes:
            raise EngineeringFixtureError("duplicate_recipe_hash", scene_id)
        recipe_hashes.add(recipe_sha)

        draft = _synthetic_resolved_recipe_draft(
            scene_id=scene_id,
            master_seed=master_seed,
            coverage=coverage,
            streams=streams,
        )
        sealed = seal_resolved_scene_recipe(draft)
        validate_resolved_scene_recipe(sealed)
        resolved_sha = sealed["recipe_sha256"]
        if resolved_sha in resolved_hashes:
            raise EngineeringFixtureError("duplicate_resolved_recipe_hash", scene_id)
        resolved_hashes.add(resolved_sha)

        fixtures.append(
            {
                "scene_id": scene_id,
                "fixture_index": index,
                "person_count": 1,
                "status": "engineering_unrendered",
                "curriculum_stage": CURRICULUM_STAGE,
                "rendered": False,
                "accepted": False,
                "training_eligible": False,
                "live_qualified_assets": False,
                "coverage": coverage,
                "recipe_stub": recipe_stub,
                "recipe_sha256": recipe_sha,
                "resolved_recipe": sealed,
                "resolved_recipe_sha256": resolved_sha,
            }
        )

    coverage_summary = _coverage_summary(fixtures)
    core = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "fixture_count": fixture_count,
        "master_seed": master_seed,
        "person_count": 1,
        "curriculum_stage": CURRICULUM_STAGE,
        "rendered": False,
        "accepted": False,
        "training_eligible": False,
        "mapping_authority": False,
        "live_daz_execution": False,
        "live_qualified_assets": False,
        "stream_contract": list(REQUIRED_RANDOM_STREAMS),
        "coverage_dimensions": list(COVERAGE_DIMENSIONS),
        "coverage_summary": coverage_summary,
        "fixtures": fixtures,
    }
    canonical_sha = _canonical_sha(core)
    document = {
        **core,
        "set_id": f"daz_engineering_fixture_set_{canonical_sha[:24]}",
        "canonical_sha256": canonical_sha,
    }
    validate_engineering_fixture_set(document)
    return document


def validate_engineering_fixture_set(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate schema invariants and fail closed on acceptance/training claims."""

    if not isinstance(document, Mapping):
        raise EngineeringFixtureError("fixture_set_not_object", type(document).__name__)
    payload = deepcopy(dict(document))
    try:
        require_valid_document(payload, "daz_engineering_fixture_set")
    except ArtifactValidationError as exc:
        raise EngineeringFixtureError("fixture_set_schema_invalid", str(exc)) from exc

    if payload.get("accepted") is True or payload.get("rendered") is True:
        raise EngineeringFixtureError(
            "acceptance_claim_forbidden",
            "STATIC engineering fixtures cannot claim rendered/accepted",
        )
    if payload.get("training_eligible") is True:
        raise EngineeringFixtureError(
            "training_eligibility_forbidden",
            "STATIC engineering fixtures cannot be training eligible",
        )
    if payload.get("mapping_authority") is True:
        raise EngineeringFixtureError(
            "mapping_authority_forbidden",
            "STATIC engineering fixtures cannot claim mapping authority",
        )
    if payload.get("live_daz_execution") is True:
        raise EngineeringFixtureError(
            "live_daz_execution_forbidden",
            "STATIC engineering fixtures cannot claim live DAZ execution",
        )
    if payload.get("live_qualified_assets") is True:
        raise EngineeringFixtureError(
            "live_qualified_assets_forbidden",
            "STATIC engineering fixtures cannot claim live qualified assets",
        )
    if payload.get("fixture_count") != len(payload.get("fixtures", ())):
        raise EngineeringFixtureError(
            "fixture_count_mismatch",
            "fixture_count must equal fixtures array length",
        )
    if payload.get("stream_contract") != list(REQUIRED_RANDOM_STREAMS):
        raise EngineeringFixtureError(
            "stream_contract_mismatch",
            "stream_contract must equal REQUIRED_RANDOM_STREAMS",
        )

    scene_ids: set[str] = set()
    recipe_hashes: set[str] = set()
    resolved_hashes: set[str] = set()
    for fixture in payload["fixtures"]:
        if fixture.get("accepted") is True or fixture.get("rendered") is True:
            raise EngineeringFixtureError(
                "fixture_acceptance_claim_forbidden",
                str(fixture.get("scene_id")),
            )
        if fixture.get("training_eligible") is True:
            raise EngineeringFixtureError(
                "fixture_training_eligibility_forbidden",
                str(fixture.get("scene_id")),
            )
        if fixture.get("live_qualified_assets") is True:
            raise EngineeringFixtureError(
                "fixture_live_qualified_assets_forbidden",
                str(fixture.get("scene_id")),
            )
        scene_id = fixture["scene_id"]
        if scene_id in scene_ids:
            raise EngineeringFixtureError("duplicate_scene_id", scene_id)
        scene_ids.add(scene_id)

        coverage = fixture["coverage"]
        for dimension, allowed in COVERAGE_VALUE_SETS.items():
            value = coverage.get(dimension)
            if value not in allowed:
                raise EngineeringFixtureError(
                    "coverage_value_unexpected",
                    f"{scene_id}:{dimension}={value}",
                )

        stub = fixture["recipe_stub"]
        recomputed = _canonical_sha(stub)
        if recomputed != fixture["recipe_sha256"]:
            raise EngineeringFixtureError("recipe_hash_drift", scene_id)
        if recomputed in recipe_hashes:
            raise EngineeringFixtureError("duplicate_recipe_hash", scene_id)
        recipe_hashes.add(recomputed)
        expected_streams = derive_named_random_streams(stub["master_seed"], stub["scene_id"])
        if stub.get("named_random_streams") != expected_streams:
            raise EngineeringFixtureError("random_stream_mismatch", scene_id)
        _assert_exact_streams(stub["named_random_streams"], scene_id=scene_id)

        resolved = fixture["resolved_recipe"]
        try:
            validate_resolved_scene_recipe(resolved)
        except Exception as exc:
            raise EngineeringFixtureError(
                "resolved_recipe_invalid",
                f"{scene_id}: {exc}",
            ) from exc
        if resolved["recipe_sha256"] != fixture["resolved_recipe_sha256"]:
            raise EngineeringFixtureError("resolved_recipe_hash_drift", scene_id)
        if fixture["resolved_recipe_sha256"] in resolved_hashes:
            raise EngineeringFixtureError("duplicate_resolved_recipe_hash", scene_id)
        resolved_hashes.add(fixture["resolved_recipe_sha256"])
        if resolved["scene_id"] != scene_id:
            raise EngineeringFixtureError("resolved_recipe_scene_mismatch", scene_id)
        if resolved["named_random_streams"] != expected_streams:
            raise EngineeringFixtureError("resolved_recipe_stream_mismatch", scene_id)

    _coverage_summary(list(payload["fixtures"]))

    core = {
        key: value for key, value in payload.items() if key not in {"set_id", "canonical_sha256"}
    }
    canonical_sha = _canonical_sha(core)
    if payload.get("canonical_sha256") != canonical_sha:
        raise EngineeringFixtureError("set_digest_invalid", "canonical digest mismatch")
    if payload.get("set_id") != f"daz_engineering_fixture_set_{canonical_sha[:24]}":
        raise EngineeringFixtureError("set_identity_invalid", "set_id mismatch")
    return payload


def publish_engineering_fixture_set(
    document: Mapping[str, Any],
    output_root: Path,
) -> tuple[Path, bool]:
    """Atomically publish an immutable engineering fixture-set document."""

    validated = validate_engineering_fixture_set(document)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / f"{validated['set_id']}.json"
    payload = json.dumps(validated, indent=2, sort_keys=True) + "\n"
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if existing == payload:
            return target, False
        raise EngineeringFixtureError(
            "fixture_set_immutable_conflict",
            f"refusing to overwrite divergent fixture set at {target}",
        )

    fd, tmp_name = tempfile.mkstemp(prefix=".daz_eng_fix_", suffix=".json", dir=output_root)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    return target, True


__all__ = [
    "ANATOMY_CONFIGURATIONS",
    "AUTHORITY",
    "COVERAGE_DIMENSIONS",
    "COVERAGE_VALUE_SETS",
    "CURRICULUM_STAGE",
    "DEFAULT_MASTER_SEED",
    "EngineeringFixtureError",
    "FRAMING_PROFILES",
    "LIGHTING_PROFILES",
    "MAX_FIXTURES",
    "MIN_FIXTURES",
    "POSE_FAMILIES",
    "PROP_MODES",
    "PROOF_TIER",
    "SCHEMA_VERSION",
    "WARDROBE_STATES",
    "build_engineering_fixture_set",
    "publish_engineering_fixture_set",
    "validate_engineering_fixture_set",
]
