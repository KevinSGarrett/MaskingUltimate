"""Deterministic qualified solo-pose selection, joint limits, and partial composition."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from ...validation import require_valid_document
from ..assets.catalog import validate_asset_compatibility_graph
from ..assets.pools import validate_asset_pool_report
from .selection import validate_character_foundation_selection

POSE_POOL_ID = "g9_poses_by_taxonomy"


class SoloPoseSelectionError(ValueError):
    """A solo pose descriptor or qualified selection is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_solo_pose_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_solo_pose_policy(document)
    return document


def validate_solo_pose_policy(policy: Mapping[str, Any]) -> None:
    expected_keys = {
        "schema_version",
        "policy_version",
        "figure_generation",
        "taxonomy",
        "allowed_pose_asset_classes",
        "joint_constraints",
        "root_transform_policies",
        "family_support_modes",
        "visibility_expectations",
        "asymmetry_tags",
        "camera_views",
        "self_occlusion_tags",
        "maximum_declared_intersection_score",
        "partial_pose_priority_range",
        "source_readback_required",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected_keys:
        raise SoloPoseSelectionError("pose_policy_fields_invalid", str(sorted(policy)))
    if (
        policy["schema_version"] != "1.0.0"
        or policy["policy_version"] != "1.0.0"
        or policy["figure_generation"] != "genesis_9"
        or policy["source_readback_required"] is not True
    ):
        raise SoloPoseSelectionError("pose_policy_version_invalid", "version/scope")
    expected_families = (
        "neutral_calibration",
        "locomotion",
        "seated",
        "crouching_kneeling",
        "lying_reclining",
        "athletic_dance_flexibility",
    )
    taxonomy = policy["taxonomy"]
    if not isinstance(taxonomy, Mapping) or tuple(taxonomy) != expected_families:
        raise SoloPoseSelectionError("pose_policy_taxonomy_invalid", str(taxonomy))
    for family, subfamilies in taxonomy.items():
        if (
            not isinstance(subfamilies, list)
            or not subfamilies
            or len(subfamilies) != len(set(subfamilies))
            or any(not _token(value) for value in subfamilies)
        ):
            raise SoloPoseSelectionError("pose_policy_subfamilies_invalid", family)
    allowed_classes = policy["allowed_pose_asset_classes"]
    expected_classes = [
        "pose_full_body",
        "pose_partial_upper",
        "pose_partial_lower",
        "pose_hand_left",
        "pose_hand_right",
        "pose_foot",
        "animation",
    ]
    if allowed_classes != expected_classes:
        raise SoloPoseSelectionError("pose_policy_asset_classes_invalid", str(allowed_classes))
    joint = policy["joint_constraints"]
    if (
        not isinstance(joint, Mapping)
        or set(joint)
        != {
            "axes",
            "limit_source",
            "maximum_utilization",
            "boundary_margin_degrees",
            "allowed_overrun_degrees",
            "finite_values_required",
            "final_daz_readback_required",
        }
        or joint["axes"] != ["bend", "twist", "side_side"]
        or joint["limit_source"] != "daz_runtime_property_limits"
        or joint["finite_values_required"] is not True
        or joint["final_daz_readback_required"] is not True
        or not 0 < joint["maximum_utilization"] <= 1
        or joint["boundary_margin_degrees"] < 0
        or joint["allowed_overrun_degrees"] != 0
    ):
        raise SoloPoseSelectionError("pose_policy_joint_constraints_invalid", str(joint))
    root_policies = policy["root_transform_policies"]
    if not isinstance(root_policies, Mapping) or tuple(root_policies) != (
        "preserve_root",
        "bounded_root",
        "support_aligned",
        "airborne",
    ):
        raise SoloPoseSelectionError("pose_policy_root_policies_invalid", str(root_policies))
    for name, limits in root_policies.items():
        if (
            not isinstance(limits, Mapping)
            or set(limits) != {"maximum_translation_cm", "maximum_rotation_degrees"}
            or not _finite_nonnegative(limits["maximum_translation_cm"])
            or not _finite_nonnegative(limits["maximum_rotation_degrees"])
        ):
            raise SoloPoseSelectionError("pose_policy_root_policy_invalid", name)
    supports = policy["family_support_modes"]
    if not isinstance(supports, Mapping) or tuple(supports) != expected_families:
        raise SoloPoseSelectionError("pose_policy_support_invalid", str(supports))
    for family, modes in supports.items():
        if not isinstance(modes, list) or not modes or len(modes) != len(set(modes)):
            raise SoloPoseSelectionError("pose_policy_support_invalid", family)
    for key in (
        "visibility_expectations",
        "asymmetry_tags",
        "camera_views",
        "self_occlusion_tags",
    ):
        values = policy[key]
        if not isinstance(values, list) or not values or len(values) != len(set(values)):
            raise SoloPoseSelectionError("pose_policy_vocabulary_invalid", key)
    if not 0 <= policy["maximum_declared_intersection_score"] <= 1:
        raise SoloPoseSelectionError("pose_policy_intersection_limit_invalid", "intersection")
    priorities = policy["partial_pose_priority_range"]
    if (
        not isinstance(priorities, list)
        or len(priorities) != 2
        or any(not isinstance(value, int) or isinstance(value, bool) for value in priorities)
        or priorities[0] < 0
        or priorities[0] >= priorities[1]
    ):
        raise SoloPoseSelectionError("pose_policy_priority_invalid", str(priorities))


def validate_pose_descriptor_registry(
    registry: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[str, Mapping[str, Any]]:
    """Validate a closed normalized-pose registry and return descriptors by asset ID."""

    validate_solo_pose_policy(policy)
    if not isinstance(registry, Mapping) or set(registry) != {"schema_version", "poses"}:
        raise SoloPoseSelectionError("pose_registry_fields_invalid", str(registry))
    if registry["schema_version"] != "1.0.0" or not isinstance(registry["poses"], list):
        raise SoloPoseSelectionError("pose_registry_invalid", "version/poses")
    by_asset: dict[str, Mapping[str, Any]] = {}
    descriptor_ids: set[str] = set()
    for descriptor in registry["poses"]:
        _validate_pose_descriptor(descriptor, policy)
        asset_id = descriptor["asset_id"]
        descriptor_id = descriptor["descriptor_id"]
        if asset_id in by_asset:
            raise SoloPoseSelectionError("pose_registry_asset_duplicate", asset_id)
        if descriptor_id in descriptor_ids:
            raise SoloPoseSelectionError("pose_registry_descriptor_duplicate", descriptor_id)
        by_asset[asset_id] = descriptor
        descriptor_ids.add(descriptor_id)
    return by_asset


def select_solo_pose(
    graph: Mapping[str, Any],
    pool_report: Mapping[str, Any],
    foundation_selection: Mapping[str, Any],
    descriptor_registry: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    selection_seed: int,
    pose_family: str,
    pose_subfamily: str,
) -> dict[str, Any]:
    """Select one qualified normalized solo pose and recompute all constraint metrics."""

    validate_asset_compatibility_graph(graph)
    validate_asset_pool_report(pool_report)
    validate_character_foundation_selection(foundation_selection, graph, pool_report)
    descriptors = validate_pose_descriptor_registry(descriptor_registry, policy)
    if (
        not isinstance(selection_seed, int)
        or isinstance(selection_seed, bool)
        or not 0 <= selection_seed < 2**64
    ):
        raise SoloPoseSelectionError("pose_selection_seed_invalid", str(selection_seed))
    if pose_family not in policy["taxonomy"]:
        raise SoloPoseSelectionError("pose_family_invalid", pose_family)
    if pose_subfamily not in policy["taxonomy"][pose_family]:
        raise SoloPoseSelectionError("pose_subfamily_invalid", pose_subfamily)
    if (
        pool_report["graph_id"] != graph["graph_id"]
        or pool_report["graph_sha256"] != graph["graph_sha256"]
    ):
        raise SoloPoseSelectionError("pose_graph_pool_mismatch", str(pool_report["report_id"]))

    nodes = {str(node["asset_id"]): node for node in graph["nodes"]}
    pools = {str(pool["pool_id"]): pool for pool in pool_report["pools"]}
    pool = pools.get(POSE_POOL_ID)
    if pool is None:
        raise SoloPoseSelectionError("pose_pool_missing", POSE_POOL_ID)
    qualified = set(pool_report["qualification_projection"]["qualified_asset_ids"])
    base_id = str(foundation_selection["selected"]["figure_asset_id"])
    scene_category = str(foundation_selection["request"]["scene_category"])
    rejections: Counter[str] = Counter()
    candidates = []
    for asset_id in pool["qualified_member_asset_ids"]:
        node = nodes[str(asset_id)]
        descriptor = descriptors.get(str(asset_id))
        reason = _pose_rejection(
            node,
            descriptor,
            base_id=base_id,
            scene_category=scene_category,
            pose_family=pose_family,
            pose_subfamily=pose_subfamily,
            qualified=qualified,
            policy=policy,
        )
        if reason is not None:
            rejections[reason] += 1
            continue
        metrics = _joint_metrics(descriptor, policy)
        rank = _canonical_sha(
            {
                "algorithm": "sha256_rank_v1",
                "selection_seed": selection_seed,
                "graph_sha256": graph["graph_sha256"],
                "pool_report_sha256": pool_report["report_sha256"],
                "foundation_selection_sha256": foundation_selection["selection_sha256"],
                "descriptor_sha256": _canonical_sha(descriptor),
            }
        )
        candidates.append((rank, str(asset_id), descriptor, metrics))
    if not candidates:
        raise SoloPoseSelectionError(
            "pose_no_qualified_candidate",
            json.dumps(dict(sorted(rejections.items())), sort_keys=True),
        )
    candidates.sort(key=lambda row: (row[0], row[1]))
    _rank, asset_id, descriptor, metrics = candidates[0]
    selected = {
        "pose_asset_id": asset_id,
        "descriptor_id": descriptor["descriptor_id"],
        "descriptor_sha256": _canonical_sha(descriptor),
        "primary_asset_class": descriptor["primary_asset_class"],
        "pose_family": descriptor["pose_family"],
        "pose_subfamily": descriptor["pose_subfamily"],
        "root_transform_policy": descriptor["root_transform_policy"],
        "root_transform": descriptor["root_transform"],
        "owned_bones": descriptor["owned_bones"],
        "bone_rotations_deg": descriptor["bone_rotations_deg"],
        "support_mode": descriptor["support_mode"],
        "support_contacts": descriptor["support_contacts"],
        "visibility_expectation": descriptor["visibility_expectation"],
        "self_occlusion_tags": descriptor["self_occlusion_tags"],
        "asymmetry_tag": descriptor["asymmetry_tag"],
        "camera_view_suitability": descriptor["camera_view_suitability"],
        "joint_metrics": metrics,
        "source_readback_required": descriptor["source_readback_required"],
        "final_daz_readback_required": True,
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
        "request": {
            "selection_seed": selection_seed,
            "pose_family": pose_family,
            "pose_subfamily": pose_subfamily,
        },
        "candidate_counts": {
            "qualified_pose_pool_members": len(pool["qualified_member_asset_ids"]),
            "matching_candidates": len(candidates),
        },
        "rejection_counts": dict(sorted(rejections.items())),
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
    digest = _canonical_sha(content)
    document = {
        "schema_version": "1.0.0",
        "selection_id": f"dcps_{digest[:24]}",
        "selection_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_solo_pose_selection")
    return document


def validate_solo_pose_selection(
    selection: Mapping[str, Any],
    graph: Mapping[str, Any],
    pool_report: Mapping[str, Any],
    foundation_selection: Mapping[str, Any],
    descriptor_registry: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    require_valid_document(selection, "daz_solo_pose_selection")
    request = selection["request"]
    expected = select_solo_pose(
        graph,
        pool_report,
        foundation_selection,
        descriptor_registry,
        policy,
        selection_seed=request["selection_seed"],
        pose_family=request["pose_family"],
        pose_subfamily=request["pose_subfamily"],
    )
    if selection != expected:
        raise SoloPoseSelectionError("pose_selection_replay_mismatch", selection["selection_id"])


def publish_solo_pose_selection(
    selection: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    require_valid_document(selection, "daz_solo_pose_selection")
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{selection['selection_id']}.json"
    payload = json.dumps(selection, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise SoloPoseSelectionError("pose_publication_conflict", str(target))
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


def compose_partial_pose_descriptors(
    components: Sequence[tuple[Mapping[str, Any], int]], policy: Mapping[str, Any]
) -> dict[str, Any]:
    """Compose normalized partial poses with deterministic declared-priority conflict handling."""

    validate_solo_pose_policy(policy)
    if not components:
        raise SoloPoseSelectionError("pose_composition_empty", "components")
    minimum, maximum = policy["partial_pose_priority_range"]
    normalized = []
    for descriptor, priority in components:
        _validate_pose_descriptor(descriptor, policy)
        if descriptor["primary_asset_class"] == "pose_full_body":
            raise SoloPoseSelectionError(
                "pose_composition_full_body_forbidden", descriptor["asset_id"]
            )
        if (
            not isinstance(priority, int)
            or isinstance(priority, bool)
            or not minimum <= priority <= maximum
        ):
            raise SoloPoseSelectionError("pose_composition_priority_invalid", str(priority))
        normalized.append((priority, descriptor["descriptor_id"], descriptor))
    normalized.sort(key=lambda row: (row[0], row[1]))
    winners: dict[str, tuple[int, str, Mapping[str, float]]] = {}
    for priority, descriptor_id, descriptor in normalized:
        for bone in descriptor["owned_bones"]:
            rotations = descriptor["bone_rotations_deg"][bone]
            existing = winners.get(bone)
            if existing is not None and priority == existing[0] and rotations != existing[2]:
                raise SoloPoseSelectionError(
                    "pose_composition_ownership_conflict", f"{bone}:{descriptor_id}:{existing[1]}"
                )
            if (
                existing is None
                or priority > existing[0]
                or (priority == existing[0] and descriptor_id > existing[1])
            ):
                winners[bone] = (priority, descriptor_id, rotations)
    component_records = [
        {
            "priority": priority,
            "descriptor_id": descriptor_id,
            "descriptor_sha256": _canonical_sha(descriptor),
        }
        for priority, descriptor_id, descriptor in normalized
    ]
    rotations = {bone: winners[bone][2] for bone in sorted(winners)}
    content = {"components": component_records, "bone_rotations_deg": rotations}
    digest = _canonical_sha(content)
    return {
        "schema_version": "1.0.0",
        "composition_id": f"dcpc_{digest[:24]}",
        "composition_sha256": digest,
        **content,
    }


def _validate_pose_descriptor(descriptor: Any, policy: Mapping[str, Any]) -> None:
    expected = {
        "descriptor_id",
        "asset_id",
        "figure_generation",
        "primary_asset_class",
        "pose_family",
        "pose_subfamily",
        "root_transform_policy",
        "root_transform",
        "owned_bones",
        "bone_rotations_deg",
        "joint_limits_deg",
        "support_mode",
        "support_contacts",
        "visibility_expectation",
        "self_occlusion_tags",
        "asymmetry_tag",
        "camera_view_suitability",
        "hand_foot_articulation_valid",
        "intersection_score",
        "conversion",
        "source_readback_required",
    }
    if not isinstance(descriptor, Mapping) or set(descriptor) != expected:
        raise SoloPoseSelectionError("pose_descriptor_fields_invalid", str(descriptor))
    if (
        not isinstance(descriptor["descriptor_id"], str)
        or not descriptor["descriptor_id"].startswith("dcpd_")
        or not isinstance(descriptor["asset_id"], str)
        or not descriptor["asset_id"].startswith("ast_")
        or descriptor["figure_generation"] != policy["figure_generation"]
        or descriptor["primary_asset_class"] not in policy["allowed_pose_asset_classes"]
    ):
        raise SoloPoseSelectionError(
            "pose_descriptor_identity_invalid", str(descriptor.get("asset_id"))
        )
    family = descriptor["pose_family"]
    subfamily = descriptor["pose_subfamily"]
    if family not in policy["taxonomy"] or subfamily not in policy["taxonomy"][family]:
        raise SoloPoseSelectionError("pose_descriptor_taxonomy_invalid", f"{family}/{subfamily}")
    root_policy = descriptor["root_transform_policy"]
    if root_policy not in policy["root_transform_policies"]:
        raise SoloPoseSelectionError("pose_descriptor_root_policy_invalid", str(root_policy))
    _validate_root_transform(descriptor["root_transform"], root_policy, policy)
    owned = descriptor["owned_bones"]
    rotations = descriptor["bone_rotations_deg"]
    limits = descriptor["joint_limits_deg"]
    if (
        not isinstance(owned, list)
        or not owned
        or owned != sorted(set(owned))
        or any(not _token(bone) for bone in owned)
        or not isinstance(rotations, Mapping)
        or not isinstance(limits, Mapping)
        or set(rotations) != set(owned)
        or set(limits) != set(owned)
    ):
        raise SoloPoseSelectionError(
            "pose_descriptor_bones_invalid", str(descriptor["descriptor_id"])
        )
    _joint_metrics(descriptor, policy)
    support_mode = descriptor["support_mode"]
    if support_mode not in policy["family_support_modes"][family]:
        raise SoloPoseSelectionError("pose_descriptor_support_mode_invalid", support_mode)
    contacts = descriptor["support_contacts"]
    if (
        not isinstance(contacts, list)
        or contacts != sorted(set(contacts))
        or any(not _token(value) for value in contacts)
    ):
        raise SoloPoseSelectionError("pose_descriptor_support_contacts_invalid", str(contacts))
    if support_mode not in {"none", "airborne"} and not contacts:
        raise SoloPoseSelectionError("pose_descriptor_support_contacts_missing", support_mode)
    visibility = descriptor["visibility_expectation"]
    if (
        not isinstance(visibility, Mapping)
        or set(visibility) != {"hands", "feet"}
        or any(value not in policy["visibility_expectations"] for value in visibility.values())
    ):
        raise SoloPoseSelectionError("pose_descriptor_visibility_invalid", str(visibility))
    occlusions = descriptor["self_occlusion_tags"]
    if (
        not isinstance(occlusions, list)
        or occlusions != sorted(set(occlusions))
        or any(value not in policy["self_occlusion_tags"] for value in occlusions)
    ):
        raise SoloPoseSelectionError("pose_descriptor_occlusion_invalid", str(occlusions))
    if descriptor["asymmetry_tag"] not in policy["asymmetry_tags"]:
        raise SoloPoseSelectionError(
            "pose_descriptor_asymmetry_invalid", descriptor["asymmetry_tag"]
        )
    views = descriptor["camera_view_suitability"]
    if (
        not isinstance(views, list)
        or not views
        or views != sorted(set(views))
        or any(value not in policy["camera_views"] for value in views)
    ):
        raise SoloPoseSelectionError("pose_descriptor_camera_views_invalid", str(views))
    if descriptor["hand_foot_articulation_valid"] is not True:
        raise SoloPoseSelectionError("Q-POSE-006", descriptor["descriptor_id"])
    score = descriptor["intersection_score"]
    if not _finite_nonnegative(score) or score > policy["maximum_declared_intersection_score"]:
        raise SoloPoseSelectionError("Q-POSE-003", str(score))
    conversion = descriptor["conversion"]
    if (
        not isinstance(conversion, Mapping)
        or set(conversion) != {"required", "dependency_asset_ids", "validated"}
        or not isinstance(conversion["required"], bool)
        or not isinstance(conversion["validated"], bool)
        or not isinstance(conversion["dependency_asset_ids"], list)
        or conversion["dependency_asset_ids"] != sorted(set(conversion["dependency_asset_ids"]))
        or (conversion["required"] and not conversion["validated"])
    ):
        raise SoloPoseSelectionError("Q-POSE-007", descriptor["descriptor_id"])
    if descriptor["source_readback_required"] is not True:
        raise SoloPoseSelectionError(
            "pose_descriptor_readback_missing", descriptor["descriptor_id"]
        )


def _joint_metrics(descriptor: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    axes = policy["joint_constraints"]["axes"]
    maximum_utilization = policy["joint_constraints"]["maximum_utilization"]
    margin = policy["joint_constraints"]["boundary_margin_degrees"]
    maximum = 0.0
    closest_margin = math.inf
    values_checked = 0
    for bone in descriptor["owned_bones"]:
        rotations = descriptor["bone_rotations_deg"][bone]
        limits = descriptor["joint_limits_deg"][bone]
        if not isinstance(rotations, Mapping) or set(rotations) != set(axes):
            raise SoloPoseSelectionError("Q-POSE-002", f"{bone}:rotations")
        if not isinstance(limits, Mapping) or set(limits) != set(axes):
            raise SoloPoseSelectionError("Q-POSE-002", f"{bone}:limits")
        for axis in axes:
            value = rotations[axis]
            bounds = limits[axis]
            if not _finite(value) or (
                not isinstance(bounds, list)
                or len(bounds) != 2
                or not all(_finite(item) for item in bounds)
                or bounds[0] >= bounds[1]
                or bounds[0] < -360
                or bounds[1] > 360
            ):
                raise SoloPoseSelectionError("Q-POSE-002", f"{bone}:{axis}")
            lower, upper = float(bounds[0]), float(bounds[1])
            effective_lower, effective_upper = lower + margin, upper - margin
            if effective_lower > effective_upper or not effective_lower <= value <= effective_upper:
                raise SoloPoseSelectionError("Q-POSE-001", f"{bone}:{axis}:{value}")
            center = (lower + upper) / 2.0
            half = (upper - lower) / 2.0
            utilization = abs(float(value) - center) / half
            if utilization > maximum_utilization:
                raise SoloPoseSelectionError("Q-POSE-001", f"{bone}:{axis}:{utilization:.6f}")
            maximum = max(maximum, utilization)
            closest_margin = min(closest_margin, float(value) - lower, upper - float(value))
            values_checked += 1
    return {
        "limit_source": "daz_runtime_property_limits",
        "bone_count": len(descriptor["owned_bones"]),
        "axis_value_count": values_checked,
        "maximum_utilization": round(maximum, 9),
        "minimum_boundary_margin_degrees": round(closest_margin, 9),
        "intersection_score": descriptor["intersection_score"],
        "passed": True,
    }


def _validate_root_transform(transform: Any, root_policy: str, policy: Mapping[str, Any]) -> None:
    if not isinstance(transform, Mapping) or set(transform) != {"translation_cm", "rotation_deg"}:
        raise SoloPoseSelectionError("Q-POSE-005", str(transform))
    translation = transform["translation_cm"]
    rotation = transform["rotation_deg"]
    if (
        not isinstance(translation, list)
        or len(translation) != 3
        or not isinstance(rotation, list)
        or len(rotation) != 3
        or not all(_finite(value) for value in [*translation, *rotation])
    ):
        raise SoloPoseSelectionError("Q-POSE-002", "root_transform")
    limits = policy["root_transform_policies"][root_policy]
    if (
        max(abs(float(value)) for value in translation) > limits["maximum_translation_cm"]
        or max(abs(float(value)) for value in rotation) > limits["maximum_rotation_degrees"]
    ):
        raise SoloPoseSelectionError("Q-POSE-005", root_policy)


def _pose_rejection(
    node: Mapping[str, Any],
    descriptor: Mapping[str, Any] | None,
    *,
    base_id: str,
    scene_category: str,
    pose_family: str,
    pose_subfamily: str,
    qualified: set[str],
    policy: Mapping[str, Any],
) -> str | None:
    if descriptor is None:
        return "descriptor_missing"
    if node["asset_id"] not in qualified:
        return "not_qualified"
    if node["primary_asset_class"] not in policy["allowed_pose_asset_classes"]:
        return "asset_class"
    if descriptor["primary_asset_class"] != node["primary_asset_class"]:
        return "descriptor_asset_class"
    if policy["figure_generation"] not in node["figure_generations"]:
        return "generation"
    if node["compatibility_bases"] and base_id not in node["compatibility_bases"]:
        return "base"
    if scene_category not in node["scene_categories"]:
        return "scene_category"
    if node["facets"].get("pose_taxonomy") != pose_family:
        return "taxonomy_facet"
    if descriptor["pose_family"] != pose_family or descriptor["pose_subfamily"] != pose_subfamily:
        return "taxonomy_request"
    if "multi_person_pose" in node["capabilities"]:
        return "multi_person_only"
    for dependency in node["dependencies"]:
        if dependency["required"] and dependency["asset_id"] not in qualified:
            return "dependency_unqualified"
    return None


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
        raise SoloPoseSelectionError("Q-POSE-002", str(exc)) from exc
    return hashlib.sha256(payload).hexdigest()


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _finite_nonnegative(value: Any) -> bool:
    return _finite(value) and value >= 0


def _token(value: Any) -> bool:
    return isinstance(value, str) and value and value.replace("_", "a").isalnum()


__all__ = [
    "POSE_POOL_ID",
    "SoloPoseSelectionError",
    "compose_partial_pose_descriptors",
    "load_solo_pose_policy",
    "publish_solo_pose_selection",
    "select_solo_pose",
    "validate_pose_descriptor_registry",
    "validate_solo_pose_policy",
    "validate_solo_pose_selection",
]
