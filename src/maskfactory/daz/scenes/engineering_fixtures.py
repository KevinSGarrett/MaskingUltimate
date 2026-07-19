"""STATIC solo engineering fixture-set contract for DAZ (MF-P9-06.10).

Builds a deterministic 24–100 scene engineering fixture set with coverage
dimensions and recipe hashes. Fixtures remain unrendered/unaccepted and are
never training-eligible. No live DAZ execution or visual acceptance is claimed.
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
from .recipe import canonical_json_bytes, derive_named_random_streams

PROOF_TIER = "STATIC_PASS"
AUTHORITY = "daz_engineering_fixture_set_static_only_unrendered"
ARTIFACT_TYPE = "daz_engineering_fixture_set"
SCHEMA_VERSION = "1.0.0"
MIN_FIXTURES = 24
MAX_FIXTURES = 100
DEFAULT_MASTER_SEED = 20260719
COVERAGE_DIMENSIONS = (
    "pose_family",
    "camera_framing",
    "wardrobe_class",
    "lighting_family",
    "anatomy_variant",
    "prop_presence",
)

POSE_FAMILIES = ("standing", "seated", "kneeling", "reclined", "contrapposto", "arms_raised")
CAMERA_FRAMINGS = ("full_body", "three_quarter", "upper_body", "close_portrait")
WARDROBE_CLASSES = ("nude_baseline", "lingerie", "casual", "structured")
LIGHTING_FAMILIES = ("soft_key", "hard_rim", "overcast", "practical_warm")
ANATOMY_VARIANTS = ("female_g9", "male_g9", "neutral_g9")
PROP_PRESENCE = ("none", "chair", "floor_support", "handheld")


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
        "camera_framing": CAMERA_FRAMINGS[index % len(CAMERA_FRAMINGS)],
        "wardrobe_class": WARDROBE_CLASSES[index % len(WARDROBE_CLASSES)],
        "lighting_family": LIGHTING_FAMILIES[index % len(LIGHTING_FAMILIES)],
        "anatomy_variant": ANATOMY_VARIANTS[index % len(ANATOMY_VARIANTS)],
        "prop_presence": PROP_PRESENCE[index % len(PROP_PRESENCE)],
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
    for index in range(fixture_count):
        scene_id = f"daz_scene_eng_{index:03d}"
        if scene_id in scene_ids:
            raise EngineeringFixtureError("duplicate_scene_id", scene_id)
        scene_ids.add(scene_id)
        coverage = _coverage_for_index(index)
        streams = derive_named_random_streams(master_seed, scene_id)
        recipe_stub = {
            "scene_id": scene_id,
            "master_seed": master_seed,
            "person_count": 1,
            "coverage": coverage,
            "named_random_streams": streams,
        }
        recipe_sha = _canonical_sha(recipe_stub)
        if recipe_sha in recipe_hashes:
            raise EngineeringFixtureError("duplicate_recipe_hash", scene_id)
        recipe_hashes.add(recipe_sha)
        fixtures.append(
            {
                "scene_id": scene_id,
                "fixture_index": index,
                "person_count": 1,
                "status": "engineering_unrendered",
                "rendered": False,
                "accepted": False,
                "training_eligible": False,
                "coverage": coverage,
                "recipe_stub": recipe_stub,
                "recipe_sha256": recipe_sha,
            }
        )

    # Require each coverage dimension to appear at least once across the set.
    for dimension in COVERAGE_DIMENSIONS:
        values = {item["coverage"][dimension] for item in fixtures}
        if not values:
            raise EngineeringFixtureError("coverage_empty", dimension)

    core = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "fixture_count": fixture_count,
        "master_seed": master_seed,
        "person_count": 1,
        "rendered": False,
        "accepted": False,
        "training_eligible": False,
        "mapping_authority": False,
        "live_daz_execution": False,
        "coverage_dimensions": list(COVERAGE_DIMENSIONS),
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
    if payload.get("fixture_count") != len(payload.get("fixtures", ())):
        raise EngineeringFixtureError(
            "fixture_count_mismatch",
            "fixture_count must equal fixtures array length",
        )

    scene_ids: set[str] = set()
    recipe_hashes: set[str] = set()
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
        scene_id = fixture["scene_id"]
        if scene_id in scene_ids:
            raise EngineeringFixtureError("duplicate_scene_id", scene_id)
        scene_ids.add(scene_id)
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

    core = {
        key: value
        for key, value in payload.items()
        if key not in {"set_id", "canonical_sha256"}
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
    "AUTHORITY",
    "COVERAGE_DIMENSIONS",
    "DEFAULT_MASTER_SEED",
    "EngineeringFixtureError",
    "MAX_FIXTURES",
    "MIN_FIXTURES",
    "PROOF_TIER",
    "build_engineering_fixture_set",
    "publish_engineering_fixture_set",
    "validate_engineering_fixture_set",
]
