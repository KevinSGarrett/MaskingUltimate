"""Qualified deterministic camera, light, environment, and prop scene formation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import yaml

from ...validation import require_valid_document
from ..assets.catalog import validate_asset_compatibility_graph
from ..assets.pools import validate_asset_pool_report
from .selection import validate_character_foundation_selection

FORMATION_POOLS = {
    "light": "lights_by_profile",
    "environment": "environments_by_context_complexity",
    "prop": "props_by_occlusion_support_role",
}


class SceneFormationSelectionError(ValueError):
    """A camera or qualified image-formation asset selection is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_scene_formation_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_scene_formation_policy(document)
    return document


def validate_scene_formation_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "camera",
        "lighting_profiles",
        "exposure_profiles",
        "environment_families",
        "context_complexities",
        "environment_restrictions",
        "prop_modes",
        "prop_roles",
        "prop_anchor_types",
        "asset_mutation_forbidden",
        "stable_object_ids_required",
        "final_asset_readback_required",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise SceneFormationSelectionError("formation_policy_fields_invalid", str(policy))
    if (
        policy["schema_version"] != "1.0.0"
        or policy["policy_version"] != "1.0.0"
        or policy["stable_object_ids_required"] is not True
        or policy["final_asset_readback_required"] is not True
    ):
        raise SceneFormationSelectionError("formation_policy_version_invalid", "version")
    camera = policy["camera"]
    camera_keys = {
        "azimuth_bins",
        "elevation_bins",
        "roll_bins",
        "focal_families",
        "framing_profiles",
        "aspect_ratios",
        "resolution_profiles",
        "depth_of_field_modes",
        "motion_blur_modes",
        "annotation_depth_of_field",
        "annotation_motion_blur",
        "final_readback_required",
    }
    if not isinstance(camera, Mapping) or set(camera) != camera_keys:
        raise SceneFormationSelectionError("formation_camera_policy_invalid", str(camera))
    for key in ("azimuth_bins", "elevation_bins", "roll_bins"):
        _validate_ranges(camera[key], key, minimum=-180, maximum=180)
    focal = camera["focal_families"]
    if not isinstance(focal, Mapping) or tuple(focal) != (
        "ultra_wide",
        "wide",
        "normal_wide",
        "normal",
        "portrait",
        "telephoto",
        "orthographic",
    ):
        raise SceneFormationSelectionError("formation_focal_policy_invalid", str(focal))
    for family, value in focal.items():
        if family == "orthographic":
            if value is not None:
                raise SceneFormationSelectionError("formation_focal_policy_invalid", family)
        elif (
            not isinstance(value, list)
            or len(value) != 2
            or not all(_finite(item) and item > 0 for item in value)
            or value[0] > value[1]
        ):
            raise SceneFormationSelectionError("formation_focal_policy_invalid", family)
    for key in (
        "framing_profiles",
        "aspect_ratios",
        "depth_of_field_modes",
        "motion_blur_modes",
    ):
        _validate_unique_list(camera[key], f"camera.{key}")
    resolution = camera["resolution_profiles"]
    if not isinstance(resolution, Mapping) or any(
        not isinstance(value, int) or isinstance(value, bool) or not 512 <= value <= 2048
        for value in resolution.values()
    ):
        raise SceneFormationSelectionError("formation_resolution_policy_invalid", str(resolution))
    if (
        camera["motion_blur_modes"] != ["off"]
        or camera["annotation_depth_of_field"] != "off"
        or camera["annotation_motion_blur"] != "off"
        or camera["final_readback_required"] is not True
    ):
        raise SceneFormationSelectionError("formation_annotation_camera_invalid", "camera")
    for key in (
        "lighting_profiles",
        "exposure_profiles",
        "context_complexities",
        "environment_restrictions",
        "prop_modes",
        "prop_roles",
        "prop_anchor_types",
        "asset_mutation_forbidden",
    ):
        _validate_unique_list(policy[key], key)
    environments = policy["environment_families"]
    if not isinstance(environments, Mapping) or tuple(environments) != (
        "controlled",
        "indoor",
        "outdoor",
    ):
        raise SceneFormationSelectionError(
            "formation_environment_policy_invalid", str(environments)
        )
    for family, subfamilies in environments.items():
        _validate_unique_list(subfamilies, f"environment.{family}")
    if policy["prop_modes"] != ["none", "support_surface", "handheld_worn", "occluder"]:
        raise SceneFormationSelectionError(
            "formation_prop_modes_invalid", str(policy["prop_modes"])
        )


def validate_formation_descriptor_registry(
    registry: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[str, Mapping[str, Any]]:
    validate_scene_formation_policy(policy)
    if not isinstance(registry, Mapping) or set(registry) != {"schema_version", "assets"}:
        raise SceneFormationSelectionError("formation_registry_fields_invalid", str(registry))
    if registry["schema_version"] != "1.0.0" or not isinstance(registry["assets"], list):
        raise SceneFormationSelectionError("formation_registry_invalid", "version/assets")
    result: dict[str, Mapping[str, Any]] = {}
    ids: set[str] = set()
    for descriptor in registry["assets"]:
        _validate_descriptor(descriptor, policy)
        if descriptor["asset_id"] in result:
            raise SceneFormationSelectionError(
                "formation_registry_asset_duplicate", descriptor["asset_id"]
            )
        if descriptor["descriptor_id"] in ids:
            raise SceneFormationSelectionError(
                "formation_registry_descriptor_duplicate", descriptor["descriptor_id"]
            )
        result[descriptor["asset_id"]] = descriptor
        ids.add(descriptor["descriptor_id"])
    return result


def select_scene_formation(
    graph: Mapping[str, Any],
    pool_report: Mapping[str, Any],
    foundation_selection: Mapping[str, Any],
    descriptor_registry: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    selection_seed: int,
    person_count: int,
    azimuth_bin: str,
    elevation_bin: str,
    roll_bin: str,
    focal_family: str,
    framing_profile: str,
    aspect_ratio: str,
    resolution_profile: str,
    depth_of_field_mode: str,
    lighting_profile: str,
    exposure_profile: str,
    environment_family: str,
    environment_subfamily: str,
    context_complexity: str,
    prop_mode: str,
) -> dict[str, Any]:
    """Resolve procedural camera values and qualified light/environment/prop assets."""

    validate_asset_compatibility_graph(graph)
    validate_asset_pool_report(pool_report)
    validate_character_foundation_selection(foundation_selection, graph, pool_report)
    descriptors = validate_formation_descriptor_registry(descriptor_registry, policy)
    request = {
        "selection_seed": selection_seed,
        "person_count": person_count,
        "azimuth_bin": azimuth_bin,
        "elevation_bin": elevation_bin,
        "roll_bin": roll_bin,
        "focal_family": focal_family,
        "framing_profile": framing_profile,
        "aspect_ratio": aspect_ratio,
        "resolution_profile": resolution_profile,
        "depth_of_field_mode": depth_of_field_mode,
        "lighting_profile": lighting_profile,
        "exposure_profile": exposure_profile,
        "environment_family": environment_family,
        "environment_subfamily": environment_subfamily,
        "context_complexity": context_complexity,
        "prop_mode": prop_mode,
    }
    _validate_request(request, policy)
    if (
        pool_report["graph_id"] != graph["graph_id"]
        or pool_report["graph_sha256"] != graph["graph_sha256"]
    ):
        raise SceneFormationSelectionError(
            "formation_graph_pool_mismatch", pool_report["report_id"]
        )
    nodes = {str(node["asset_id"]): node for node in graph["nodes"]}
    pools = {str(pool["pool_id"]): pool for pool in pool_report["pools"]}
    qualified = set(pool_report["qualification_projection"]["qualified_asset_ids"])
    base_id = foundation_selection["selected"]["figure_asset_id"]
    scene_category = foundation_selection["request"]["scene_category"]
    selections: dict[str, Mapping[str, Any] | None] = {}
    candidate_counts = {}
    rejection_counts: Counter[str] = Counter()
    for descriptor_type in ("light", "environment", "prop"):
        if descriptor_type == "prop" and prop_mode == "none":
            selections[descriptor_type] = None
            candidate_counts[descriptor_type] = 0
            continue
        pool_id = FORMATION_POOLS[descriptor_type]
        pool = pools.get(pool_id)
        if pool is None:
            raise SceneFormationSelectionError("formation_pool_missing", pool_id)
        candidates = []
        for asset_id in pool["qualified_member_asset_ids"]:
            node = nodes[str(asset_id)]
            descriptor = descriptors.get(str(asset_id))
            reason = _asset_rejection(
                descriptor_type,
                node,
                descriptor,
                request=request,
                base_id=base_id,
                scene_category=scene_category,
                qualified=qualified,
            )
            if reason is not None:
                rejection_counts[f"{descriptor_type}_{reason}"] += 1
                continue
            rank = _canonical_sha(
                {
                    "algorithm": "sha256_rank_v1",
                    "selection_seed": selection_seed,
                    "descriptor_type": descriptor_type,
                    "graph_sha256": graph["graph_sha256"],
                    "pool_report_sha256": pool_report["report_sha256"],
                    "descriptor_sha256": _canonical_sha(descriptor),
                }
            )
            candidates.append((rank, str(asset_id), descriptor))
        if not candidates:
            raise SceneFormationSelectionError(
                "formation_no_qualified_candidate",
                f"{descriptor_type}:{json.dumps(dict(sorted(rejection_counts.items())))}",
            )
        candidates.sort(key=lambda row: (row[0], row[1]))
        selections[descriptor_type] = candidates[0][2]
        candidate_counts[descriptor_type] = len(candidates)

    camera = _resolve_camera(request, policy)
    selected = {
        "camera": camera,
        "light": _selected_descriptor(selections["light"]),
        "environment": _selected_descriptor(selections["environment"]),
        "prop": _selected_descriptor(selections["prop"]),
        "exposure_profile": exposure_profile,
    }
    content = {
        "graph_id": graph["graph_id"],
        "graph_sha256": graph["graph_sha256"],
        "pool_report_id": pool_report["report_id"],
        "pool_report_sha256": pool_report["report_sha256"],
        "foundation_selection_id": foundation_selection["selection_id"],
        "foundation_selection_sha256": foundation_selection["selection_sha256"],
        "policy_sha256": _canonical_sha(policy),
        "descriptor_registry_sha256": _canonical_sha(descriptor_registry),
        "request": request,
        "candidate_counts": candidate_counts,
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "selected": selected,
        "evidence_requirements": {
            "final_camera_readback_required": True,
            "projected_bbox_and_prominence_required": True,
            "pristine_annotation_camera_match_required": True,
            "final_light_environment_prop_readback_required": True,
            "prop_contact_and_occlusion_preflight_required": prop_mode != "none",
            "undeclared_human_and_reflection_check_required": True,
            "finite_nonempty_rgb_required": True,
        },
    }
    digest = _canonical_sha(content)
    document = {
        "schema_version": "1.0.0",
        "selection_id": f"dcif_{digest[:24]}",
        "selection_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_scene_formation_selection")
    return document


def validate_scene_formation_selection(
    selection: Mapping[str, Any],
    graph: Mapping[str, Any],
    pool_report: Mapping[str, Any],
    foundation_selection: Mapping[str, Any],
    descriptor_registry: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    require_valid_document(selection, "daz_scene_formation_selection")
    expected = select_scene_formation(
        graph,
        pool_report,
        foundation_selection,
        descriptor_registry,
        policy,
        **selection["request"],
    )
    if selection != expected:
        raise SceneFormationSelectionError(
            "formation_selection_replay_mismatch", selection["selection_id"]
        )


def publish_scene_formation_selection(
    selection: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    require_valid_document(selection, "daz_scene_formation_selection")
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{selection['selection_id']}.json"
    payload = json.dumps(selection, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise SceneFormationSelectionError("formation_publication_conflict", str(target))
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


def _validate_descriptor(descriptor: Any, policy: Mapping[str, Any]) -> None:
    expected = {
        "descriptor_id",
        "asset_id",
        "descriptor_type",
        "lighting_profile",
        "environment_family",
        "environment_subfamily",
        "context_complexity",
        "prop_mode",
        "prop_role",
        "anchor_types",
        "stable_object_id",
        "environment_restrictions_satisfied",
        "forbidden_mutations",
        "final_readback_required",
    }
    if not isinstance(descriptor, Mapping) or set(descriptor) != expected:
        raise SceneFormationSelectionError("formation_descriptor_fields_invalid", str(descriptor))
    if (
        not isinstance(descriptor["descriptor_id"], str)
        or not descriptor["descriptor_id"].startswith("dcfd_")
        or not isinstance(descriptor["asset_id"], str)
        or not descriptor["asset_id"].startswith("ast_")
        or descriptor["descriptor_type"] not in FORMATION_POOLS
        or descriptor["final_readback_required"] is not True
        or descriptor["forbidden_mutations"] != []
    ):
        raise SceneFormationSelectionError(
            "formation_descriptor_identity_invalid", str(descriptor.get("asset_id"))
        )
    kind = descriptor["descriptor_type"]
    if kind == "light":
        if (
            descriptor["lighting_profile"] not in policy["lighting_profiles"]
            or any(
                descriptor[key] is not None
                for key in (
                    "environment_family",
                    "environment_subfamily",
                    "context_complexity",
                    "prop_mode",
                    "prop_role",
                    "stable_object_id",
                )
            )
            or descriptor["anchor_types"]
            or descriptor["environment_restrictions_satisfied"]
        ):
            raise SceneFormationSelectionError(
                "formation_light_descriptor_invalid", descriptor["descriptor_id"]
            )
    elif kind == "environment":
        family = descriptor["environment_family"]
        if (
            descriptor["lighting_profile"] is not None
            or family not in policy["environment_families"]
            or descriptor["environment_subfamily"] not in policy["environment_families"][family]
            or descriptor["context_complexity"] not in policy["context_complexities"]
            or descriptor["prop_mode"] is not None
            or descriptor["prop_role"] is not None
            or descriptor["stable_object_id"] is not None
            or descriptor["anchor_types"]
            or descriptor["environment_restrictions_satisfied"]
            != policy["environment_restrictions"]
        ):
            raise SceneFormationSelectionError(
                "formation_environment_descriptor_invalid", descriptor["descriptor_id"]
            )
    else:
        if (
            descriptor["lighting_profile"] is not None
            or descriptor["environment_family"] is not None
            or descriptor["environment_subfamily"] is not None
            or descriptor["context_complexity"] is not None
            or descriptor["prop_mode"] not in policy["prop_modes"][1:]
            or descriptor["prop_role"] not in policy["prop_roles"]
            or not isinstance(descriptor["stable_object_id"], str)
            or not descriptor["stable_object_id"].startswith("object_")
            or not isinstance(descriptor["anchor_types"], list)
            or not descriptor["anchor_types"]
            or descriptor["anchor_types"] != sorted(set(descriptor["anchor_types"]))
            or any(value not in policy["prop_anchor_types"] for value in descriptor["anchor_types"])
            or descriptor["environment_restrictions_satisfied"]
        ):
            raise SceneFormationSelectionError(
                "formation_prop_descriptor_invalid", descriptor["descriptor_id"]
            )
        expected_role = {
            "support_surface": "support_surface",
            "handheld_worn": "accessory_or_prop",
            "occluder": "occluding_object",
        }[descriptor["prop_mode"]]
        if descriptor["prop_role"] != expected_role:
            raise SceneFormationSelectionError(
                "formation_prop_role_invalid", descriptor["descriptor_id"]
            )


def _validate_request(request: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    if (
        not isinstance(request["selection_seed"], int)
        or isinstance(request["selection_seed"], bool)
        or not 0 <= request["selection_seed"] < 2**64
        or not isinstance(request["person_count"], int)
        or isinstance(request["person_count"], bool)
        or not 1 <= request["person_count"] <= 4
    ):
        raise SceneFormationSelectionError("formation_request_numeric_invalid", str(request))
    camera = policy["camera"]
    memberships = {
        "azimuth_bin": camera["azimuth_bins"],
        "elevation_bin": camera["elevation_bins"],
        "roll_bin": camera["roll_bins"],
        "focal_family": camera["focal_families"],
        "framing_profile": camera["framing_profiles"],
        "aspect_ratio": camera["aspect_ratios"],
        "resolution_profile": camera["resolution_profiles"],
        "depth_of_field_mode": camera["depth_of_field_modes"],
        "lighting_profile": policy["lighting_profiles"],
        "exposure_profile": policy["exposure_profiles"],
        "environment_family": policy["environment_families"],
        "context_complexity": policy["context_complexities"],
        "prop_mode": policy["prop_modes"],
    }
    for field, allowed in memberships.items():
        if request[field] not in allowed:
            raise SceneFormationSelectionError("formation_request_axis_invalid", field)
    if (
        request["environment_subfamily"]
        not in policy["environment_families"][request["environment_family"]]
    ):
        raise SceneFormationSelectionError("formation_environment_subfamily_invalid", "subfamily")
    multi_framing = {"multi_person_group_full", "multi_person_mixed_truncation"}
    if (request["framing_profile"] in multi_framing) != (request["person_count"] > 1):
        raise SceneFormationSelectionError("formation_framing_person_count_invalid", "framing")
    if request["focal_family"] == "orthographic" and request["framing_profile"] not in {
        "full_body_margin",
        "full_body_tight",
    }:
        raise SceneFormationSelectionError("formation_orthographic_scope_invalid", "framing")


def _resolve_camera(request: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    camera = policy["camera"]
    azimuth = _sample_range(
        camera["azimuth_bins"][request["azimuth_bin"]], request["selection_seed"], "azimuth"
    )
    elevation = _sample_range(
        camera["elevation_bins"][request["elevation_bin"]],
        request["selection_seed"],
        "elevation",
    )
    roll = _sample_range(
        camera["roll_bins"][request["roll_bin"]], request["selection_seed"], "roll"
    )
    focal_range = camera["focal_families"][request["focal_family"]]
    focal_length = (
        None
        if focal_range is None
        else _sample_range(focal_range, request["selection_seed"], "focal_length")
    )
    width, height = _resolution(
        camera["resolution_profiles"][request["resolution_profile"]], request["aspect_ratio"]
    )
    dof_mode = request["depth_of_field_mode"]
    f_stop = {"off": None, "mild": 5.6, "strong_person_relevant": 2.8}[dof_mode]
    return {
        "projection_type": "orthographic" if focal_range is None else "perspective",
        "azimuth_bin": request["azimuth_bin"],
        "azimuth_degrees": azimuth,
        "elevation_bin": request["elevation_bin"],
        "elevation_degrees": elevation,
        "roll_bin": request["roll_bin"],
        "roll_degrees": roll,
        "focal_family": request["focal_family"],
        "focal_length_mm": focal_length,
        "orthographic_scale": (
            round(2.0 + 2.0 * _uniform(request["selection_seed"], "ortho_scale"), 6)
            if focal_range is None
            else None
        ),
        "look_at_target": "promoted_people_centroid",
        "framing_profile": request["framing_profile"],
        "aspect_ratio": request["aspect_ratio"],
        "resolution": [width, height],
        "crop": [0, 0, width, height],
        "depth_of_field": {"mode": dof_mode, "enabled": dof_mode != "off", "f_stop": f_stop},
        "motion_blur": {"mode": "off", "enabled": False},
        "lens_distortion_state": "pristine_none",
        "projected_bboxes_and_prominence": "required_final_readback",
        "annotation_camera_effects_off": True,
        "final_readback_required": True,
    }


def _asset_rejection(
    kind: str,
    node: Mapping[str, Any],
    descriptor: Mapping[str, Any] | None,
    *,
    request: Mapping[str, Any],
    base_id: str,
    scene_category: str,
    qualified: set[str],
) -> str | None:
    if descriptor is None or descriptor["descriptor_type"] != kind:
        return "descriptor"
    if node["asset_id"] not in qualified:
        return "not_qualified"
    if scene_category not in node["scene_categories"]:
        return "scene_category"
    if node["figure_generations"] != ["generation_neutral"] and (
        "genesis_9" not in node["figure_generations"]
        or (node["compatibility_bases"] and base_id not in node["compatibility_bases"])
    ):
        return "base"
    for dependency in node["dependencies"]:
        if dependency["required"] and dependency["asset_id"] not in qualified:
            return "dependency"
    if kind == "light":
        if node["primary_asset_class"] != "light_preset":
            return "class"
        if descriptor["lighting_profile"] != request["lighting_profile"]:
            return "profile"
        if node["facets"].get("lighting_profile") != request["lighting_profile"]:
            return "facet"
    elif kind == "environment":
        if descriptor["environment_family"] != request["environment_family"]:
            return "family"
        if descriptor["environment_subfamily"] != request["environment_subfamily"]:
            return "subfamily"
        if descriptor["context_complexity"] != request["context_complexity"]:
            return "complexity"
        if node["facets"].get("context_complexity") != request["context_complexity"]:
            return "facet"
    else:
        if descriptor["prop_mode"] != request["prop_mode"]:
            return "mode"
        if node["facets"].get("occlusion_support_role") != descriptor["prop_role"]:
            return "facet"
    return None


def _selected_descriptor(descriptor: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if descriptor is None:
        return None
    return {
        "asset_id": descriptor["asset_id"],
        "descriptor_id": descriptor["descriptor_id"],
        "descriptor_sha256": _canonical_sha(descriptor),
        "descriptor_type": descriptor["descriptor_type"],
        "lighting_profile": descriptor["lighting_profile"],
        "environment_family": descriptor["environment_family"],
        "environment_subfamily": descriptor["environment_subfamily"],
        "context_complexity": descriptor["context_complexity"],
        "prop_mode": descriptor["prop_mode"],
        "prop_role": descriptor["prop_role"],
        "anchor_types": descriptor["anchor_types"],
        "stable_object_id": descriptor["stable_object_id"],
        "final_readback_required": True,
    }


def _validate_ranges(ranges: Any, name: str, *, minimum: float, maximum: float) -> None:
    if not isinstance(ranges, Mapping) or not ranges:
        raise SceneFormationSelectionError("formation_range_policy_invalid", name)
    for key, value in ranges.items():
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(_finite(item) for item in value)
            or value[0] < minimum
            or value[1] > maximum
            or value[0] > value[1]
        ):
            raise SceneFormationSelectionError("formation_range_policy_invalid", f"{name}.{key}")


def _validate_unique_list(values: Any, name: str) -> None:
    if (
        not isinstance(values, list)
        or not values
        or len(values) != len(set(values))
        or any(not isinstance(value, str) or not value for value in values)
    ):
        raise SceneFormationSelectionError("formation_vocabulary_invalid", name)


def _resolution(short_side: int, aspect: str) -> tuple[int, int]:
    numerator, denominator = (int(value) for value in aspect.split(":"))
    if numerator >= denominator:
        return round(short_side * numerator / denominator), short_side
    return short_side, round(short_side * denominator / numerator)


def _sample_range(bounds: list[float], seed: int, namespace: str) -> float:
    if bounds[0] == bounds[1]:
        return float(bounds[0])
    return round(bounds[0] + (bounds[1] - bounds[0]) * _uniform(seed, namespace), 6)


def _uniform(seed: int, namespace: str) -> float:
    payload = json.dumps(
        {"algorithm": "sha256_first_u64_be_v1", "namespace": namespace, "seed": seed},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    integer = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return integer / 2**64


def _canonical_sha(document: Any) -> str:
    try:
        payload = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SceneFormationSelectionError("formation_noncanonical_value", str(exc)) from exc
    return hashlib.sha256(payload).hexdigest()


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


__all__ = [
    "FORMATION_POOLS",
    "SceneFormationSelectionError",
    "load_scene_formation_policy",
    "publish_scene_formation_selection",
    "select_scene_formation",
    "validate_formation_descriptor_registry",
    "validate_scene_formation_policy",
    "validate_scene_formation_selection",
]
