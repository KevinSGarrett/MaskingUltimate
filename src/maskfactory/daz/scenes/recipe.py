"""Canonical JSON, named random streams, and sealed DAZ scene recipes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from ...validation import ArtifactValidationError, require_valid_document

REQUIRED_RANDOM_STREAMS = (
    "characters",
    "poses",
    "placement",
    "camera",
    "lighting",
    "environment",
    "render",
    "degrade",
)


class SceneRecipeError(ValueError):
    """A resolved scene recipe is incomplete, noncanonical, or hash-invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def derive_named_random_streams(master_seed: int, scene_id: str) -> dict[str, int]:
    """Derive independent 64-bit streams from the root seed and scene namespace."""

    if (
        not isinstance(master_seed, int)
        or isinstance(master_seed, bool)
        or not 0 <= master_seed < 2**63
    ):
        raise SceneRecipeError("scene_master_seed_invalid", str(master_seed))
    if not isinstance(scene_id, str) or not scene_id.startswith("daz_scene_"):
        raise SceneRecipeError("scene_id_invalid", str(scene_id))
    streams = {}
    for namespace in REQUIRED_RANDOM_STREAMS:
        payload = canonical_json_bytes(
            {
                "algorithm": "sha256_first_u64_be_v1",
                "master_seed": master_seed,
                "namespace": namespace,
                "scene_id": scene_id,
            }
        )
        streams[namespace] = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return streams


def canonical_json_bytes(document: Any) -> bytes:
    """Serialize JSON deterministically and refuse non-finite or non-string-key data."""

    _validate_json_value(document, pointer="")
    try:
        return json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SceneRecipeError("scene_canonical_json_invalid", str(exc)) from exc


def seal_resolved_scene_recipe(document: Mapping[str, Any]) -> dict[str, Any]:
    """Derive streams and SHA-256 for one fully resolved, registry-order-independent recipe."""

    if not isinstance(document, Mapping):
        raise SceneRecipeError("scene_recipe_not_object", type(document).__name__)
    recipe = deepcopy(dict(document))
    recipe.pop("recipe_sha256", None)
    expected_streams = derive_named_random_streams(
        recipe.get("master_seed"), recipe.get("scene_id")
    )
    supplied_streams = recipe.get("named_random_streams")
    if supplied_streams is not None and supplied_streams != expected_streams:
        raise SceneRecipeError("scene_random_stream_mismatch", str(recipe.get("scene_id")))
    recipe["named_random_streams"] = expected_streams
    _validate_scene_invariants(recipe)
    recipe["recipe_sha256"] = hashlib.sha256(canonical_json_bytes(recipe)).hexdigest()
    try:
        require_valid_document(recipe, "daz_resolved_scene_recipe")
    except ArtifactValidationError as exc:
        raise SceneRecipeError("scene_recipe_schema_invalid", str(exc)) from exc
    return recipe


def validate_resolved_scene_recipe(recipe: Mapping[str, Any]) -> dict[str, Any]:
    """Validate schema, invariants, streams, and exact content hash."""

    try:
        require_valid_document(recipe, "daz_resolved_scene_recipe")
    except ArtifactValidationError as exc:
        raise SceneRecipeError("scene_recipe_schema_invalid", str(exc)) from exc
    _validate_scene_invariants(recipe)
    expected_streams = derive_named_random_streams(recipe["master_seed"], recipe["scene_id"])
    if recipe["named_random_streams"] != expected_streams:
        raise SceneRecipeError("scene_random_stream_mismatch", recipe["scene_id"])
    content = {key: value for key, value in recipe.items() if key != "recipe_sha256"}
    expected_sha = hashlib.sha256(canonical_json_bytes(content)).hexdigest()
    if recipe["recipe_sha256"] != expected_sha:
        raise SceneRecipeError("scene_recipe_hash_mismatch", recipe["scene_id"])
    return {
        "scene_id": recipe["scene_id"],
        "scene_family_id": recipe["scene_family_id"],
        "scene_variant_id": recipe["scene_variant_id"],
        "recipe_sha256": expected_sha,
        "character_count": len(recipe["characters"]),
        "valid": True,
    }


def publish_resolved_scene_recipe(
    recipe: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    """Atomically publish immutable pretty JSON after full integrity validation."""

    validate_resolved_scene_recipe(recipe)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{recipe['scene_id']}_{recipe['recipe_sha256'][:16]}.json"
    payload = json.dumps(recipe, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise SceneRecipeError("scene_recipe_publication_conflict", str(target))
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


def _validate_scene_invariants(recipe: Mapping[str, Any]) -> None:
    _validate_json_value(recipe, pointer="")
    characters = recipe.get("characters")
    if not isinstance(characters, list) or not 1 <= len(characters) <= 4:
        raise SceneRecipeError("scene_character_count_invalid", str(characters))
    if any(not isinstance(character, Mapping) for character in characters):
        raise SceneRecipeError("scene_character_record_invalid", str(characters))
    construction_ids = [character.get("construction_id") for character in characters]
    if len(construction_ids) != len(set(construction_ids)):
        raise SceneRecipeError("scene_construction_id_duplicate", str(construction_ids))
    expected_ids = [f"c{index}" for index in range(len(characters))]
    if construction_ids != expected_ids:
        raise SceneRecipeError(
            "scene_construction_ids_noncanonical", f"{construction_ids}!={expected_ids}"
        )
    requested = [
        character.get("requested_promoted_id")
        for character in characters
        if character.get("requested_promoted_id") is not None
    ]
    if len(requested) != len(set(requested)):
        raise SceneRecipeError("scene_requested_promoted_id_duplicate", str(requested))
    relationship = recipe.get("relationship_template")
    if relationship is not None:
        participants = relationship.get("participants")
        if not isinstance(participants, list) or not set(participants).issubset(construction_ids):
            raise SceneRecipeError("scene_relationship_participant_invalid", str(participants))
    lighting = recipe.get("lighting")
    streams = recipe.get("named_random_streams")
    if isinstance(lighting, Mapping) and isinstance(streams, Mapping):
        if lighting.get("parameter_seed") != streams.get("lighting"):
            raise SceneRecipeError("scene_lighting_seed_mismatch", str(recipe.get("scene_id")))
    camera = recipe.get("camera")
    if isinstance(camera, Mapping):
        resolution = camera.get("resolution")
        crop = camera.get("crop")
        if (
            isinstance(resolution, list)
            and len(resolution) == 2
            and isinstance(crop, list)
            and len(crop) == 4
            and (crop[2] > resolution[0] or crop[3] > resolution[1])
        ):
            raise SceneRecipeError("scene_crop_exceeds_resolution", str(crop))


def _validate_json_value(value: Any, *, pointer: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SceneRecipeError("scene_nonfinite_number", pointer or "/")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, pointer=f"{pointer}/{index}")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise SceneRecipeError("scene_nonstring_json_key", f"{pointer}/{key}")
            _validate_json_value(item, pointer=f"{pointer}/{key}")
        return
    raise SceneRecipeError("scene_non_json_value", f"{pointer}:{type(value).__name__}")
