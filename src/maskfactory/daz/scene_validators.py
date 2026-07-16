"""Strict V2 recipe, V3 assembly, and V4 geometry validators."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .scenes.recipe import SceneRecipeError, validate_resolved_scene_recipe
from .validation_registry import validate_validation_registry, validate_validation_result


class StrictSceneValidationError(ValueError):
    """A validator policy or input contract is structurally invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_strict_scene_validation_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_strict_scene_validation_policy(document)
    return document


def validate_strict_scene_validation_policy(policy: Mapping[str, Any]) -> None:
    if not isinstance(policy, Mapping) or set(policy) != {
        "schema_version",
        "policy_version",
        "recipe",
        "assembly",
        "geometry",
    }:
        raise StrictSceneValidationError("strict_validator_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["policy_version"] != "1.0.0":
        raise StrictSceneValidationError("strict_validator_policy_identity_invalid", str(policy))
    recipe = policy["recipe"]
    if not isinstance(recipe, Mapping) or set(recipe) != {
        "allowed_ontology_names",
        "allowed_render_profile_ids",
        "configuration_matrix",
        "maximum_storage_gib",
        "maximum_gpu_vram_gib",
        "cost_warning_fraction",
    }:
        raise StrictSceneValidationError("strict_validator_recipe_policy_invalid", str(recipe))
    if (
        recipe["allowed_ontology_names"] != ["body_parts_v1", "body_parts_v2"]
        or not _unique_strings(recipe["allowed_render_profile_ids"])
        or recipe["configuration_matrix"]
        != {
            "1": ["solo"],
            "2": ["separated", "overlap", "contact"],
            "3": ["separated", "overlap", "contact"],
            "4": ["separated", "overlap", "contact"],
        }
        or not _finite_positive(recipe["maximum_storage_gib"])
        or not _finite_positive(recipe["maximum_gpu_vram_gib"])
        or not _finite(recipe["cost_warning_fraction"])
        or not 0 < recipe["cost_warning_fraction"] < 1
    ):
        raise StrictSceneValidationError("strict_validator_recipe_policy_invalid", str(recipe))
    assembly = policy["assembly"]
    if not isinstance(assembly, Mapping) or set(assembly) != {
        "accepted_runtime_warning_codes",
        "figure_scale_range",
        "maximum_absolute_world_coordinate_cm",
        "numeric_tolerance",
    }:
        raise StrictSceneValidationError("strict_validator_assembly_policy_invalid", str(assembly))
    if (
        not _unique_strings(assembly["accepted_runtime_warning_codes"])
        or not _valid_range(assembly["figure_scale_range"], positive=True)
        or not _finite_positive(assembly["maximum_absolute_world_coordinate_cm"])
        or not _finite(assembly["numeric_tolerance"])
        or assembly["numeric_tolerance"] < 0
    ):
        raise StrictSceneValidationError("strict_validator_assembly_policy_invalid", str(assembly))
    geometry = policy["geometry"]
    if not isinstance(geometry, Mapping) or set(geometry) != {
        "allowed_subdivision_levels",
        "allowed_smoothing_modes",
        "recognized_topology_modifiers",
        "minimum_visible_area_fraction",
        "maximum_off_frame_fraction",
        "collision_limits",
        "tolerated_intentional_contact_depth_mm",
        "tolerated_intentional_contact_volume_cc",
    }:
        raise StrictSceneValidationError("strict_validator_geometry_policy_invalid", str(geometry))
    expected_categories = {
        "self_body",
        "hair_body",
        "garment_body",
        "garment_garment",
        "person_person",
        "person_prop_support",
    }
    limits = geometry["collision_limits"]
    if (
        geometry["allowed_subdivision_levels"] != [0, 1, 2, 3]
        or not _unique_strings(geometry["allowed_smoothing_modes"])
        or not _unique_strings(geometry["recognized_topology_modifiers"])
        or not _finite(geometry["minimum_visible_area_fraction"])
        or not 0 < geometry["minimum_visible_area_fraction"] <= 1
        or not _finite(geometry["maximum_off_frame_fraction"])
        or not 0 <= geometry["maximum_off_frame_fraction"] <= 1
        or not isinstance(limits, Mapping)
        or set(limits) != expected_categories
        or any(
            not isinstance(value, Mapping)
            or set(value) != {"maximum_depth_mm", "maximum_volume_cc"}
            or not _finite_nonnegative(value["maximum_depth_mm"])
            or not _finite_nonnegative(value["maximum_volume_cc"])
            for value in limits.values()
        )
        or not _finite_nonnegative(geometry["tolerated_intentional_contact_depth_mm"])
        or not _finite_nonnegative(geometry["tolerated_intentional_contact_volume_cc"])
    ):
        raise StrictSceneValidationError("strict_validator_geometry_policy_invalid", str(geometry))


def validate_recipe_layer(
    recipe: Mapping[str, Any],
    authority: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    registry: Mapping[str, Any],
    evidence_paths: Sequence[str],
) -> dict[str, Any]:
    """Return the normalized V2 result for one sealed recipe and bound authority snapshot."""

    validate_strict_scene_validation_policy(policy)
    validate_validation_registry(registry)
    findings: list[dict[str, str]] = []
    try:
        validate_resolved_scene_recipe(recipe)
    except SceneRecipeError as exc:
        if exc.reason_code in {
            "scene_random_stream_mismatch",
            "scene_recipe_hash_mismatch",
            "scene_canonical_json_invalid",
        }:
            code = "RECIPE_NONDETERMINISTIC"
        elif exc.reason_code in {
            "scene_master_seed_invalid",
            "scene_nonfinite_number",
            "scene_character_count_invalid",
            "scene_crop_exceeds_resolution",
        }:
            code = "RECIPE_RANGE_INVALID"
        else:
            code = "RECIPE_UNRESOLVABLE"
        findings.append(_finding(code, "/recipe", exc.reason_code))
    _validate_recipe_authority(authority)
    if not findings:
        recipe_policy = policy["recipe"]
        if recipe["registry_snapshot_id"] != authority["registry_snapshot_id"]:
            findings.append(
                _finding("RECIPE_UNRESOLVABLE", "/registry_snapshot_id", "snapshot_mismatch")
            )
        ontology = {
            (row["name"], row["snapshot_sha256"]) for row in authority["ontology_snapshots"]
        }
        if (
            recipe["ontology"]["name"] not in recipe_policy["allowed_ontology_names"]
            or (recipe["ontology"]["name"], recipe["ontology"]["snapshot_sha256"]) not in ontology
        ):
            findings.append(
                _finding("RECIPE_UNRESOLVABLE", "/ontology", "unknown_or_hash_mismatch")
            )
        if (
            recipe["render_profile_id"] not in recipe_policy["allowed_render_profile_ids"]
            or recipe["render_profile_id"] not in authority["render_profile_ids"]
        ):
            findings.append(
                _finding("RECIPE_UNRESOLVABLE", "/render_profile_id", "unknown_profile")
            )
        count = len(recipe["characters"])
        relationship_family = (
            "solo"
            if recipe["relationship_template"] is None
            else recipe["relationship_template"].get("type")
        )
        if relationship_family not in recipe_policy["configuration_matrix"][str(count)]:
            findings.append(
                _finding("RECIPE_RANGE_INVALID", "/relationship_template", str(relationship_family))
            )
        _check_recipe_references(recipe, authority, findings)
        estimate = authority["resource_estimate"]
        if (
            estimate["storage_gib"] > recipe_policy["maximum_storage_gib"]
            or estimate["gpu_vram_gib"] > recipe_policy["maximum_gpu_vram_gib"]
        ):
            findings.append(
                _finding("RECIPE_RANGE_INVALID", "/resource_estimate", "limit_exceeded")
            )
    findings.sort(key=lambda row: (row["code"], row["path"], row["detail"]))
    hard_findings = [row for row in findings if row["code"] != "RECIPE_COST_WARNING"]
    estimate = authority["resource_estimate"]
    recipe_policy = policy["recipe"]
    cost_warning = not hard_findings and (
        estimate["storage_gib"]
        >= recipe_policy["maximum_storage_gib"] * recipe_policy["cost_warning_fraction"]
        or estimate["gpu_vram_gib"]
        >= recipe_policy["maximum_gpu_vram_gib"] * recipe_policy["cost_warning_fraction"]
    )
    if cost_warning:
        findings.append(_finding("RECIPE_COST_WARNING", "/resource_estimate", "near_limit"))
    if hard_findings:
        status = "fail"
        reason = _first_code(
            findings,
            ["RECIPE_NONDETERMINISTIC", "RECIPE_UNRESOLVABLE", "RECIPE_RANGE_INVALID"],
        )
        retryability = "adjusted_recipe"
    elif cost_warning:
        status, reason, retryability = "warn", "RECIPE_COST_WARNING", "adjusted_recipe"
    else:
        status, reason, retryability = "pass", "RECIPE_VALID", "none"
    return _result(
        "DAZ-V2-001",
        recipe.get("scene_id", "invalid_recipe"),
        status,
        reason,
        findings,
        evidence_paths,
        retryability,
        registry,
        affected_assets=_referenced_assets(recipe),
        affected_mappings=_referenced_mappings(recipe),
    )


def validate_assembly_layer(
    recipe: Mapping[str, Any],
    observation: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    registry: Mapping[str, Any],
    evidence_paths: Sequence[str],
) -> dict[str, Any]:
    """Return V3 after exact node/readback/fit/framing checks."""

    validate_strict_scene_validation_policy(policy)
    validate_validation_registry(registry)
    validate_resolved_scene_recipe(recipe)
    _validate_assembly_observation(observation)
    if (
        observation["scene_id"] != recipe["scene_id"]
        or observation["recipe_sha256"] != recipe["recipe_sha256"]
    ):
        raise StrictSceneValidationError("assembly_lineage_invalid", observation["scene_id"])
    findings: list[dict[str, str]] = []
    expected_assets = _expected_recipe_assets(recipe)
    readbacks = {row["key"]: row for row in observation["asset_readbacks"]}
    if len(readbacks) != len(observation["asset_readbacks"]):
        raise StrictSceneValidationError(
            "assembly_asset_readback_duplicate", observation["scene_id"]
        )
    if not observation["default_scene_empty_before_load"]:
        findings.append(_finding("ASSEMBLY_NODE_MISMATCH", "/default_scene", "not_empty"))
    if set(observation["expected_node_ids"]) != set(observation["observed_renderable_node_ids"]):
        findings.append(_finding("ASSEMBLY_NODE_MISMATCH", "/nodes", "set_mismatch"))
    if set(readbacks) != set(expected_assets):
        findings.append(_finding("ASSEMBLY_NODE_MISMATCH", "/asset_readbacks", "role_set_mismatch"))
    for key, asset_id in expected_assets.items():
        row = readbacks.get(key)
        if (
            row is None
            or row["expected_asset_id"] != asset_id
            or row["observed_asset_id"] != asset_id
            or row["count"] != 1
        ):
            findings.append(
                _finding("ASSEMBLY_NODE_MISMATCH", f"/asset_readbacks/{key}", "readback_mismatch")
            )
    if observation["unresolved_textures"]:
        findings.append(_finding("ASSEMBLY_NODE_MISMATCH", "/unresolved_textures", "unresolved"))
    assembly_policy = policy["assembly"]
    if any(
        not _matrix_finite(matrix) for matrix in observation["world_transforms"].values()
    ) or set(observation["world_transforms"]) != set(observation["expected_node_ids"]):
        findings.append(
            _finding(
                "ASSEMBLY_TRANSFORM_INVALID",
                "/world_transforms",
                "node_set_nonfinite_or_shape",
            )
        )
    scale_min, scale_max = assembly_policy["figure_scale_range"]
    if len(observation["figure_scales"]) != len(recipe["characters"]) or any(
        not _finite(scale) or not scale_min <= scale <= scale_max
        for scale in observation["figure_scales"]
    ):
        findings.append(_finding("ASSEMBLY_TRANSFORM_INVALID", "/figure_scales", "implausible"))
    world_limit = assembly_policy["maximum_absolute_world_coordinate_cm"]
    if len(observation["world_bounds"]) != len(recipe["characters"]) or any(
        not _bounds_valid(bounds, world_limit) for bounds in observation["world_bounds"]
    ):
        findings.append(_finding("ASSEMBLY_TRANSFORM_INVALID", "/world_bounds", "implausible"))
    tolerance = assembly_policy["numeric_tolerance"]
    expected_numeric = _numeric_recipe_values(recipe)
    expected_properties = {
        key: value for key, value in expected_numeric.items() if ":morph:" in key
    }
    expected_joints = {key: value for key, value in expected_numeric.items() if ":pose" in key}
    if not _numeric_readbacks_match(
        observation["property_readbacks"], expected_properties, tolerance
    ) or not _numeric_readbacks_match(observation["joint_readbacks"], expected_joints, tolerance):
        findings.append(_finding("ASSEMBLY_FIT_INVALID", "/numeric_readbacks", "mismatch"))
    if any(not row["declared"] for row in observation["controller_side_effects"]):
        findings.append(_finding("ASSEMBLY_FIT_INVALID", "/controller_side_effects", "undeclared"))
    if not observation["support_contacts_plausible"]:
        findings.append(_finding("ASSEMBLY_FIT_INVALID", "/support_contacts", "implausible"))
    transform_readbacks = {
        row["construction_id"]: row for row in observation["character_transform_readbacks"]
    }
    expected_transforms = {
        row["construction_id"]: row["world_transform"] for row in recipe["characters"]
    }
    if (
        len(transform_readbacks) != len(observation["character_transform_readbacks"])
        or set(transform_readbacks) != set(expected_transforms)
        or any(
            row["requested"] != expected_transforms[construction_id]
            or not _values_close(row["observed"], expected_transforms[construction_id], tolerance)
            for construction_id, row in transform_readbacks.items()
        )
        or not _values_close(observation["camera_readback"], recipe["camera"], tolerance)
    ):
        findings.append(_finding("ASSEMBLY_TRANSFORM_INVALID", "/transform_readbacks", "mismatch"))
    expected_prominence = [
        row["construction_id"]
        for row in sorted(
            observation["p_index_prominence"],
            key=lambda row: (-row["prominence"], row["construction_id"]),
        )
    ]
    observed_prominence = [
        row["construction_id"]
        for row in sorted(observation["p_index_prominence"], key=lambda row: row["p_index"])
    ]
    p_indices = [row["p_index"] for row in observation["p_index_prominence"]]
    if (
        not observation["camera_sees_intended_people"]
        or observation["visible_person_count"] != len(recipe["characters"])
        or expected_prominence != observed_prominence
        or set(observed_prominence) != {row["construction_id"] for row in recipe["characters"]}
        or sorted(p_indices) != list(range(len(recipe["characters"])))
    ):
        findings.append(_finding("ASSEMBLY_FRAMING_INVALID", "/framing", "people_or_prominence"))
    warnings = []
    allowed_warnings = set(assembly_policy["accepted_runtime_warning_codes"])
    for index, row in enumerate(observation["runtime_messages"]):
        if row["severity"] == "error" or row["code"] not in allowed_warnings:
            findings.append(
                _finding("ASSEMBLY_NODE_MISMATCH", f"/runtime_messages/{index}", row["code"])
            )
        else:
            warnings.append(row["code"])
    findings.sort(key=lambda row: (row["code"], row["path"], row["detail"]))
    if findings:
        status = "fail"
        reason = _first_code(
            findings,
            [
                "ASSEMBLY_NODE_MISMATCH",
                "ASSEMBLY_TRANSFORM_INVALID",
                "ASSEMBLY_FIT_INVALID",
                "ASSEMBLY_FRAMING_INVALID",
            ],
        )
        retryability = "adjusted_recipe"
    elif warnings:
        status, reason, retryability = "warn", "ASSEMBLY_RUNTIME_WARNING", "adjusted_recipe"
        findings = [_finding(reason, "/runtime_messages", ",".join(sorted(warnings)))]
    else:
        status, reason, retryability = "pass", "ASSEMBLY_VALID", "none"
    return _result(
        "DAZ-V3-001",
        recipe["scene_id"],
        status,
        reason,
        findings,
        evidence_paths,
        retryability,
        registry,
        affected_assets=_referenced_assets(recipe),
        affected_mappings=_referenced_mappings(recipe),
    )


def validate_geometry_layer(
    recipe: Mapping[str, Any],
    observation: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    registry: Mapping[str, Any],
    evidence_paths: Sequence[str],
) -> dict[str, Any]:
    """Return V4 after topology, collision/contact, and framing checks."""

    validate_strict_scene_validation_policy(policy)
    validate_validation_registry(registry)
    validate_resolved_scene_recipe(recipe)
    _validate_geometry_observation(observation)
    if (
        observation["scene_id"] != recipe["scene_id"]
        or observation["recipe_sha256"] != recipe["recipe_sha256"]
    ):
        raise StrictSceneValidationError("geometry_lineage_invalid", observation["scene_id"])
    geometry_policy = policy["geometry"]
    findings: list[dict[str, str]] = []
    tolerated_contacts: list[str] = []
    for index, mesh in enumerate(observation["meshes"]):
        topology_invalid = (
            mesh["observed_topology_sha256"] != mesh["expected_topology_sha256"]
            or mesh["subdivision_level"] not in geometry_policy["allowed_subdivision_levels"]
            or mesh["smoothing_mode"] not in geometry_policy["allowed_smoothing_modes"]
            or mesh["observed_facet_count"] != mesh["expected_facet_count"]
            or sorted(mesh["observed_material_groups"]) != sorted(mesh["expected_material_groups"])
            or not set(mesh["topology_modifiers"])
            <= set(geometry_policy["recognized_topology_modifiers"])
        )
        if topology_invalid:
            findings.append(
                _finding("GEOMETRY_TOPOLOGY_MISMATCH", f"/meshes/{index}", mesh["node_id"])
            )
        if (
            mesh["scanned_vertex_count"] != mesh["vertex_count"]
            or mesh["nonfinite_vertex_count"] != 0
        ):
            findings.append(
                _finding(
                    "GEOMETRY_NONFINITE",
                    f"/meshes/{index}/vertices",
                    (
                        f"{mesh['node_id']}:scanned={mesh['scanned_vertex_count']}:"
                        f"total={mesh['vertex_count']}:nonfinite={mesh['nonfinite_vertex_count']}"
                    ),
                )
            )
    for index, collision in enumerate(observation["collisions"]):
        if collision["broad_phase_overlap"] and not collision["narrow_phase_ran"]:
            findings.append(
                _finding(
                    "GEOMETRY_PENETRATION_EXCESS",
                    f"/collisions/{index}",
                    f"{collision['pair_id']}:narrow_phase_missing",
                )
            )
            continue
        limits = geometry_policy["collision_limits"][collision["category"]]
        if (
            collision["maximum_depth_mm"] > limits["maximum_depth_mm"]
            or collision["penetration_volume_cc"] > limits["maximum_volume_cc"]
        ):
            findings.append(
                _finding(
                    "GEOMETRY_PENETRATION_EXCESS", f"/collisions/{index}", collision["pair_id"]
                )
            )
        elif collision["intended_contact"] and (
            collision["maximum_depth_mm"] > 0 or collision["penetration_volume_cc"] > 0
        ):
            if (
                collision["maximum_depth_mm"]
                <= geometry_policy["tolerated_intentional_contact_depth_mm"]
                and collision["penetration_volume_cc"]
                <= geometry_policy["tolerated_intentional_contact_volume_cc"]
            ):
                tolerated_contacts.append(collision["pair_id"])
            else:
                findings.append(
                    _finding(
                        "GEOMETRY_PENETRATION_EXCESS", f"/collisions/{index}", collision["pair_id"]
                    )
                )
    construction_ids = {row["construction_id"] for row in recipe["characters"]}
    observed_ids = {row["construction_id"] for row in observation["framing"]}
    if len(observed_ids) != len(observation["framing"]) or observed_ids != construction_ids:
        findings.append(_finding("GEOMETRY_VISIBILITY_INVALID", "/framing", "person_set_mismatch"))
    for index, framing in enumerate(observation["framing"]):
        if (
            not framing["visible"]
            or framing["visible_area_fraction"] < geometry_policy["minimum_visible_area_fraction"]
            or framing["off_frame_fraction"] > geometry_policy["maximum_off_frame_fraction"]
            or framing["camera_clipped"]
            or not set(framing["required_regions"]) <= set(framing["visible_regions"])
        ):
            findings.append(
                _finding(
                    "GEOMETRY_VISIBILITY_INVALID", f"/framing/{index}", framing["construction_id"]
                )
            )
    if not observation["support_alignment_plausible"]:
        findings.append(
            _finding("GEOMETRY_VISIBILITY_INVALID", "/support_alignment", "implausible")
        )
    findings.sort(key=lambda row: (row["code"], row["path"], row["detail"]))
    if findings:
        status = "fail"
        reason = _first_code(
            findings,
            [
                "GEOMETRY_NONFINITE",
                "GEOMETRY_TOPOLOGY_MISMATCH",
                "GEOMETRY_PENETRATION_EXCESS",
                "GEOMETRY_VISIBILITY_INVALID",
            ],
        )
        retryability = (
            "asset_retest" if reason == "GEOMETRY_TOPOLOGY_MISMATCH" else "adjusted_recipe"
        )
    elif tolerated_contacts:
        status, reason, retryability = "warn", "GEOMETRY_TOLERATED_CONTACT", "adjusted_recipe"
        findings = [_finding(reason, "/collisions", ",".join(sorted(tolerated_contacts)))]
    else:
        status, reason, retryability = "pass", "GEOMETRY_VALID", "none"
    return _result(
        "DAZ-V4-001",
        recipe["scene_id"],
        status,
        reason,
        findings,
        evidence_paths,
        retryability,
        registry,
        affected_assets=_referenced_assets(recipe),
        affected_mappings=_referenced_mappings(recipe),
    )


def _validate_recipe_authority(authority: Any) -> None:
    expected = {
        "schema_version",
        "registry_snapshot_id",
        "ontology_snapshots",
        "render_profile_ids",
        "asset_records",
        "mapping_bundle_records",
        "numeric_ranges",
        "resource_estimate",
    }
    if not isinstance(authority, Mapping) or set(authority) != expected:
        raise StrictSceneValidationError("recipe_authority_fields_invalid", str(authority))
    if authority["schema_version"] != "1.0.0" or not _unique_strings(
        authority["render_profile_ids"]
    ):
        raise StrictSceneValidationError("recipe_authority_identity_invalid", str(authority))
    if not isinstance(authority["registry_snapshot_id"], str) or not authority[
        "registry_snapshot_id"
    ].startswith("daz_registry_"):
        raise StrictSceneValidationError("recipe_authority_identity_invalid", str(authority))
    for row in authority["ontology_snapshots"]:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"name", "snapshot_sha256"}
            or not _sha256(row["snapshot_sha256"])
        ):
            raise StrictSceneValidationError("recipe_authority_ontology_invalid", str(row))
    for row in authority["asset_records"]:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"asset_id", "resolved", "qualified", "compatible_figure_asset_ids"}
            or not isinstance(row["asset_id"], str)
            or not isinstance(row["resolved"], bool)
            or not isinstance(row["qualified"], bool)
            or not _unique_strings(row["compatible_figure_asset_ids"], allow_empty=True)
        ):
            raise StrictSceneValidationError("recipe_authority_asset_invalid", str(row))
    for row in authority["mapping_bundle_records"]:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"mapping_bundle_id", "resolved", "asset_ids"}
            or not isinstance(row["mapping_bundle_id"], str)
            or not isinstance(row["resolved"], bool)
            or not _unique_strings(row["asset_ids"])
        ):
            raise StrictSceneValidationError("recipe_authority_mapping_invalid", str(row))
    for row in authority["numeric_ranges"]:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"key", "minimum", "maximum"}
            or not isinstance(row["key"], str)
            or not row["key"]
            or not _finite(row["minimum"])
            or not _finite(row["maximum"])
            or row["minimum"] > row["maximum"]
        ):
            raise StrictSceneValidationError("recipe_authority_numeric_range_invalid", str(row))
    estimate = authority["resource_estimate"]
    if (
        not isinstance(estimate, Mapping)
        or set(estimate) != {"storage_gib", "gpu_vram_gib"}
        or any(not _finite_nonnegative(estimate[key]) for key in estimate)
    ):
        raise StrictSceneValidationError("recipe_authority_resource_invalid", str(estimate))


def _check_recipe_references(
    recipe: Mapping[str, Any], authority: Mapping[str, Any], findings: list[dict[str, str]]
) -> None:
    assets = {row["asset_id"]: row for row in authority["asset_records"]}
    if len(assets) != len(authority["asset_records"]):
        raise StrictSceneValidationError("recipe_authority_asset_duplicate", recipe["scene_id"])
    for asset_id in _referenced_assets(recipe):
        row = assets.get(asset_id)
        if row is None or not row["resolved"] or not row["qualified"]:
            findings.append(_finding("RECIPE_UNRESOLVABLE", "/assets", asset_id))
    for character in recipe["characters"]:
        figure = character["figure_asset_id"]
        character_assets = _character_assets(character)
        for asset_id in character_assets:
            row = assets.get(asset_id)
            if (
                row is not None
                and asset_id != figure
                and figure not in row["compatible_figure_asset_ids"]
            ):
                findings.append(
                    _finding(
                        "RECIPE_UNRESOLVABLE",
                        f"/compatibility/{character['construction_id']}",
                        asset_id,
                    )
                )
    mappings = {row["mapping_bundle_id"]: row for row in authority["mapping_bundle_records"]}
    if len(mappings) != len(authority["mapping_bundle_records"]):
        raise StrictSceneValidationError("recipe_authority_mapping_duplicate", recipe["scene_id"])
    for character in recipe["characters"]:
        required_assets = set(_character_assets(character))
        for mapping_id in character["mapping_bundle_ids"]:
            row = mappings.get(mapping_id)
            if row is None or not row["resolved"] or not required_assets & set(row["asset_ids"]):
                findings.append(
                    _finding(
                        "RECIPE_UNRESOLVABLE",
                        f"/mappings/{character['construction_id']}",
                        mapping_id,
                    )
                )
    numeric_values = _numeric_recipe_values(recipe)
    numeric_ranges = {row["key"]: row for row in authority["numeric_ranges"]}
    if len(numeric_ranges) != len(authority["numeric_ranges"]):
        raise StrictSceneValidationError(
            "recipe_authority_numeric_range_duplicate", recipe["scene_id"]
        )
    if set(numeric_ranges) != set(numeric_values):
        findings.append(_finding("RECIPE_RANGE_INVALID", "/numeric_ranges", "coverage_mismatch"))
    for key, value in numeric_values.items():
        limits = numeric_ranges.get(key)
        if limits is None or not limits["minimum"] <= value <= limits["maximum"]:
            findings.append(_finding("RECIPE_RANGE_INVALID", f"/numeric_ranges/{key}", str(value)))


def _validate_assembly_observation(observation: Any) -> None:
    expected = {
        "schema_version",
        "scene_id",
        "recipe_sha256",
        "default_scene_empty_before_load",
        "expected_node_ids",
        "observed_renderable_node_ids",
        "asset_readbacks",
        "property_readbacks",
        "joint_readbacks",
        "controller_side_effects",
        "unresolved_textures",
        "world_transforms",
        "character_transform_readbacks",
        "camera_readback",
        "figure_scales",
        "world_bounds",
        "support_contacts_plausible",
        "camera_sees_intended_people",
        "visible_person_count",
        "p_index_prominence",
        "runtime_messages",
    }
    if not isinstance(observation, Mapping) or set(observation) != expected:
        raise StrictSceneValidationError("assembly_observation_fields_invalid", str(observation))
    if observation["schema_version"] != "1.0.0" or not _sha256(observation["recipe_sha256"]):
        raise StrictSceneValidationError("assembly_observation_identity_invalid", str(observation))
    if not _unique_strings(observation["expected_node_ids"]) or not _unique_strings(
        observation["observed_renderable_node_ids"], allow_empty=True
    ):
        raise StrictSceneValidationError(
            "assembly_observation_nodes_invalid", observation["scene_id"]
        )
    for row in observation["asset_readbacks"]:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"key", "expected_asset_id", "observed_asset_id", "count"}
            or not isinstance(row["count"], int)
            or isinstance(row["count"], bool)
            or row["count"] < 0
        ):
            raise StrictSceneValidationError("assembly_observation_asset_invalid", str(row))
    for collection in ("property_readbacks", "joint_readbacks"):
        for row in observation[collection]:
            if (
                not isinstance(row, Mapping)
                or set(row) != {"key", "requested", "observed", "minimum", "maximum"}
                or any(
                    not _finite(row[key]) for key in ("requested", "observed", "minimum", "maximum")
                )
            ):
                raise StrictSceneValidationError("assembly_observation_readback_invalid", str(row))
    for row in observation["controller_side_effects"]:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"uri", "declared"}
            or not isinstance(row["declared"], bool)
        ):
            raise StrictSceneValidationError("assembly_observation_side_effect_invalid", str(row))
    if not _unique_strings(observation["unresolved_textures"], allow_empty=True) or not isinstance(
        observation["world_transforms"], Mapping
    ):
        raise StrictSceneValidationError(
            "assembly_observation_geometry_invalid", observation["scene_id"]
        )
    if not isinstance(observation["figure_scales"], list) or not isinstance(
        observation["world_bounds"], list
    ):
        raise StrictSceneValidationError(
            "assembly_observation_geometry_invalid", observation["scene_id"]
        )
    if not isinstance(observation["camera_readback"], Mapping) or not isinstance(
        observation["character_transform_readbacks"], list
    ):
        raise StrictSceneValidationError(
            "assembly_observation_transform_readback_invalid", observation["scene_id"]
        )
    for row in observation["character_transform_readbacks"]:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"construction_id", "requested", "observed"}
            or not isinstance(row["construction_id"], str)
            or not isinstance(row["requested"], Mapping)
            or not isinstance(row["observed"], Mapping)
        ):
            raise StrictSceneValidationError(
                "assembly_observation_transform_readback_invalid", str(row)
            )
    if any(
        not isinstance(observation[key], bool)
        for key in (
            "default_scene_empty_before_load",
            "support_contacts_plausible",
            "camera_sees_intended_people",
        )
    ):
        raise StrictSceneValidationError(
            "assembly_observation_boolean_invalid", observation["scene_id"]
        )
    if (
        not isinstance(observation["visible_person_count"], int)
        or isinstance(observation["visible_person_count"], bool)
        or observation["visible_person_count"] < 0
    ):
        raise StrictSceneValidationError(
            "assembly_observation_count_invalid", observation["scene_id"]
        )
    for row in observation["p_index_prominence"]:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"construction_id", "p_index", "prominence"}
            or not isinstance(row["p_index"], int)
            or isinstance(row["p_index"], bool)
            or row["p_index"] < 0
            or not _finite_nonnegative(row["prominence"])
        ):
            raise StrictSceneValidationError("assembly_observation_prominence_invalid", str(row))
    for row in observation["runtime_messages"]:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"severity", "code"}
            or row["severity"] not in {"warning", "error"}
            or not isinstance(row["code"], str)
        ):
            raise StrictSceneValidationError("assembly_observation_runtime_invalid", str(row))


def _validate_geometry_observation(observation: Any) -> None:
    expected = {
        "schema_version",
        "scene_id",
        "recipe_sha256",
        "meshes",
        "collisions",
        "framing",
        "support_alignment_plausible",
    }
    if (
        not isinstance(observation, Mapping)
        or set(observation) != expected
        or observation["schema_version"] != "1.0.0"
        or not _sha256(observation["recipe_sha256"])
    ):
        raise StrictSceneValidationError("geometry_observation_fields_invalid", str(observation))
    for row in observation["meshes"]:
        fields = {
            "node_id",
            "expected_topology_sha256",
            "observed_topology_sha256",
            "subdivision_level",
            "smoothing_mode",
            "expected_facet_count",
            "observed_facet_count",
            "expected_material_groups",
            "observed_material_groups",
            "vertex_count",
            "scanned_vertex_count",
            "nonfinite_vertex_count",
            "topology_modifiers",
        }
        if (
            not isinstance(row, Mapping)
            or set(row) != fields
            or not _sha256(row["expected_topology_sha256"])
            or not _sha256(row["observed_topology_sha256"])
            or not _unique_strings(row["expected_material_groups"])
            or not _unique_strings(row["observed_material_groups"])
            or not _unique_strings(row["topology_modifiers"], allow_empty=True)
        ):
            raise StrictSceneValidationError("geometry_observation_mesh_invalid", str(row))
        if any(
            not isinstance(row[key], int) or isinstance(row[key], bool) or row[key] < 0
            for key in (
                "subdivision_level",
                "vertex_count",
                "scanned_vertex_count",
                "nonfinite_vertex_count",
                "expected_facet_count",
                "observed_facet_count",
            )
        ):
            raise StrictSceneValidationError("geometry_observation_mesh_invalid", str(row))
        if row["nonfinite_vertex_count"] > row["scanned_vertex_count"]:
            raise StrictSceneValidationError("geometry_observation_mesh_invalid", str(row))
    mesh_ids = [row["node_id"] for row in observation["meshes"]]
    if not mesh_ids or len(mesh_ids) != len(set(mesh_ids)):
        raise StrictSceneValidationError(
            "geometry_observation_mesh_set_invalid", observation["scene_id"]
        )
    categories = {
        "self_body",
        "hair_body",
        "garment_body",
        "garment_garment",
        "person_person",
        "person_prop_support",
    }
    for row in observation["collisions"]:
        if (
            not isinstance(row, Mapping)
            or set(row)
            != {
                "pair_id",
                "category",
                "maximum_depth_mm",
                "penetration_volume_cc",
                "intended_contact",
                "visible",
                "broad_phase_overlap",
                "narrow_phase_ran",
            }
            or row["category"] not in categories
            or not _finite_nonnegative(row["maximum_depth_mm"])
            or not _finite_nonnegative(row["penetration_volume_cc"])
            or not isinstance(row["intended_contact"], bool)
            or not isinstance(row["visible"], bool)
            or not isinstance(row["broad_phase_overlap"], bool)
            or not isinstance(row["narrow_phase_ran"], bool)
        ):
            raise StrictSceneValidationError("geometry_observation_collision_invalid", str(row))
        if not row["broad_phase_overlap"] and row["narrow_phase_ran"]:
            raise StrictSceneValidationError(
                "geometry_observation_collision_phase_invalid", row["pair_id"]
            )
        if not row["broad_phase_overlap"] and (
            row["maximum_depth_mm"] > 0 or row["penetration_volume_cc"] > 0
        ):
            raise StrictSceneValidationError(
                "geometry_observation_collision_phase_invalid", row["pair_id"]
            )
    pair_ids = [row["pair_id"] for row in observation["collisions"]]
    if len(pair_ids) != len(set(pair_ids)):
        raise StrictSceneValidationError(
            "geometry_observation_collision_duplicate", observation["scene_id"]
        )
    for row in observation["framing"]:
        if (
            not isinstance(row, Mapping)
            or set(row)
            != {
                "construction_id",
                "visible",
                "visible_area_fraction",
                "off_frame_fraction",
                "camera_clipped",
                "visible_regions",
                "required_regions",
            }
            or not isinstance(row["visible"], bool)
            or not isinstance(row["camera_clipped"], bool)
            or not _finite_unit(row["visible_area_fraction"])
            or not _finite_unit(row["off_frame_fraction"])
            or not _unique_strings(row["visible_regions"])
            or not _unique_strings(row["required_regions"])
        ):
            raise StrictSceneValidationError("geometry_observation_framing_invalid", str(row))
    if not isinstance(observation["support_alignment_plausible"], bool):
        raise StrictSceneValidationError("geometry_observation_support_invalid", str(observation))


def _result(
    validator_id: str,
    entity_id: str,
    status: str,
    reason_code: str,
    findings: Sequence[Mapping[str, str]],
    evidence_paths: Sequence[str],
    retryability: str,
    registry: Mapping[str, Any],
    *,
    affected_assets: Sequence[str],
    affected_mappings: Sequence[str],
) -> dict[str, Any]:
    validator = next(row for row in registry["validators"] if row["validator_id"] == validator_id)
    result = {
        "validator_id": validator_id,
        "validator_version": validator["validator_version"],
        "entity_id": entity_id,
        "status": status,
        "reason_code": reason_code,
        "metric": "defect_count",
        "observed": {"defect_count": len(findings), "findings": list(findings)},
        "expected": {"operator": "eq", "value": 0},
        "evidence_paths": sorted(set(evidence_paths)),
        "retryability": retryability,
        "affected_asset_ids": sorted(set(affected_assets)),
        "affected_mapping_ids": sorted(set(affected_mappings)),
    }
    validate_validation_result(result, registry)
    return result


def _expected_recipe_assets(recipe: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for character in recipe["characters"]:
        prefix = character["construction_id"]
        for role, asset_id in (
            ("figure", character["figure_asset_id"]),
            ("character_preset", character["character_preset_asset_id"]),
            ("skin_material", character["skin_material_asset_id"]),
            ("hair", character["hair_asset_id"]),
            ("pose", character["pose_asset_id"]),
        ):
            if asset_id is not None:
                result[f"{prefix}:{role}"] = asset_id
        for index, asset_id in enumerate(character["anatomy_asset_ids"]):
            result[f"{prefix}:anatomy:{index:02d}"] = asset_id
        for index, asset_id in enumerate(character["wardrobe_asset_ids"]):
            result[f"{prefix}:wardrobe:{index:02d}"] = asset_id
    if recipe["environment"]["asset_id"] is not None:
        result["scene:environment"] = recipe["environment"]["asset_id"]
    for index, prop in enumerate(recipe["props"]):
        if isinstance(prop, Mapping) and isinstance(prop.get("asset_id"), str):
            result[f"scene:prop:{index:02d}"] = prop["asset_id"]
    return dict(sorted(result.items()))


def _character_assets(character: Mapping[str, Any]) -> list[str]:
    values = [
        character["figure_asset_id"],
        character["character_preset_asset_id"],
        character["skin_material_asset_id"],
        character["hair_asset_id"],
        character["pose_asset_id"],
        *character["anatomy_asset_ids"],
        *character["wardrobe_asset_ids"],
    ]
    return sorted({value for value in values if isinstance(value, str)})


def _referenced_assets(recipe: Mapping[str, Any]) -> list[str]:
    if not isinstance(recipe, Mapping) or not isinstance(recipe.get("characters"), list):
        return []
    assets = {
        asset
        for character in recipe["characters"]
        if isinstance(character, Mapping)
        for asset in _character_assets(character)
    }
    environment = recipe.get("environment")
    if isinstance(environment, Mapping) and isinstance(environment.get("asset_id"), str):
        assets.add(environment["asset_id"])
    for prop in recipe.get("props", []):
        if isinstance(prop, Mapping) and isinstance(prop.get("asset_id"), str):
            assets.add(prop["asset_id"])
    return sorted(assets)


def _referenced_mappings(recipe: Mapping[str, Any]) -> list[str]:
    if not isinstance(recipe, Mapping) or not isinstance(recipe.get("characters"), list):
        return []
    return sorted(
        {
            mapping
            for character in recipe["characters"]
            if isinstance(character, Mapping)
            for mapping in character.get("mapping_bundle_ids", [])
        }
    )


def _numeric_recipe_values(recipe: Mapping[str, Any]) -> dict[str, float]:
    values: dict[str, float] = {}
    for character in recipe["characters"]:
        construction_id = character["construction_id"]
        for uri, value in character["morph_values"].items():
            if _finite(value):
                values[f"{construction_id}:morph:{uri}"] = value
        _collect_numeric_values(
            character["pose_adjustments"],
            prefix=f"{construction_id}:pose",
            destination=values,
        )
    return dict(sorted(values.items()))


def _collect_numeric_values(value: Any, *, prefix: str, destination: dict[str, float]) -> None:
    if _finite(value):
        destination[prefix] = value
    elif isinstance(value, Mapping):
        for key, item in sorted(value.items()):
            _collect_numeric_values(item, prefix=f"{prefix}/{key}", destination=destination)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _collect_numeric_values(item, prefix=f"{prefix}/{index}", destination=destination)


def _bounds_valid(bounds: Any, limit: float) -> bool:
    return (
        isinstance(bounds, Mapping)
        and set(bounds) == {"minimum_cm", "maximum_cm"}
        and all(
            isinstance(bounds[key], list)
            and len(bounds[key]) == 3
            and all(_finite(value) and abs(value) <= limit for value in bounds[key])
            for key in ("minimum_cm", "maximum_cm")
        )
        and all(
            low <= high
            for low, high in zip(bounds["minimum_cm"], bounds["maximum_cm"], strict=True)
        )
    )


def _numeric_readbacks_match(
    rows: Sequence[Mapping[str, Any]], expected: Mapping[str, float], tolerance: float
) -> bool:
    by_key = {row["key"]: row for row in rows}
    return (
        len(by_key) == len(rows)
        and set(by_key) == set(expected)
        and all(
            row["requested"] == expected[key]
            and row["minimum"] <= row["observed"] <= row["maximum"]
            and abs(row["observed"] - expected[key]) <= tolerance
            for key, row in by_key.items()
        )
    )


def _values_close(observed: Any, expected: Any, tolerance: float) -> bool:
    if _finite(observed) and _finite(expected):
        return abs(observed - expected) <= tolerance
    if isinstance(observed, Mapping) and isinstance(expected, Mapping):
        return set(observed) == set(expected) and all(
            _values_close(observed[key], expected[key], tolerance) for key in expected
        )
    if isinstance(observed, list) and isinstance(expected, list):
        return len(observed) == len(expected) and all(
            _values_close(left, right, tolerance)
            for left, right in zip(observed, expected, strict=True)
        )
    return observed == expected


def _matrix_finite(matrix: Any) -> bool:
    return (
        isinstance(matrix, list) and len(matrix) == 16 and all(_finite(value) for value in matrix)
    )


def _finding(code: str, path: str, detail: str) -> dict[str, str]:
    return {"code": code, "path": path, "detail": detail}


def _first_code(findings: Sequence[Mapping[str, str]], priority: Sequence[str]) -> str:
    codes = {row["code"] for row in findings}
    return next(code for code in priority if code in codes)


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _unique_strings(value: Any, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and len(value) == len(set(value))
        and all(isinstance(item, str) and item for item in value)
    )


def _valid_range(value: Any, *, positive: bool = False) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(_finite(item) for item in value)
        and value[0] <= value[1]
        and (not positive or value[0] > 0)
    )


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _finite_positive(value: Any) -> bool:
    return _finite(value) and value > 0


def _finite_nonnegative(value: Any) -> bool:
    return _finite(value) and value >= 0


def _finite_unit(value: Any) -> bool:
    return _finite(value) and 0 <= value <= 1


__all__ = [
    "StrictSceneValidationError",
    "load_strict_scene_validation_policy",
    "validate_assembly_layer",
    "validate_geometry_layer",
    "validate_recipe_layer",
    "validate_strict_scene_validation_policy",
]
