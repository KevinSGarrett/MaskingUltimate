"""Fail-closed collision, support-contact, promotion, and framing preflight."""

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


class ScenePreflightError(ValueError):
    """Scene preflight input, policy, or replay evidence is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_scene_preflight_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_scene_preflight_policy(document)
    return document


def validate_scene_preflight_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "scope",
        "promotion",
        "framing_profiles",
        "collision_limits",
        "contact",
        "geometry",
        "repair",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise ScenePreflightError("preflight_policy_fields_invalid", str(policy))
    if (
        policy["schema_version"] != "1.0.0"
        or policy["policy_version"] != "1.0.0"
        or policy["scope"] != "solo_scene_preflight"
    ):
        raise ScenePreflightError("preflight_policy_version_invalid", "version/scope")
    promotion = policy["promotion"]
    if (
        not isinstance(promotion, Mapping)
        or set(promotion)
        != {
            "minimum_visible_area_fraction",
            "maximum_people",
            "require_exact_declared_person_count",
            "deterministic_tie_break",
        }
        or not 0 < promotion["minimum_visible_area_fraction"] < 1
        or promotion["maximum_people"] != 1
        or promotion["require_exact_declared_person_count"] is not True
        or promotion["deterministic_tie_break"]
        != ["prominence_desc", "visible_area_desc", "construction_id_asc"]
    ):
        raise ScenePreflightError("preflight_promotion_policy_invalid", str(promotion))
    profiles = policy["framing_profiles"]
    expected_profiles = (
        "full_body_margin",
        "full_body_tight",
        "three_quarter_body",
        "waist_up",
        "chest_head",
        "head_shoulders",
        "close_up_specialist",
        "intentional_truncation",
        "negative_space",
        "off_center",
    )
    if not isinstance(profiles, Mapping) or tuple(profiles) != expected_profiles:
        raise ScenePreflightError("preflight_framing_profiles_invalid", str(profiles))
    for name, profile in profiles.items():
        if not isinstance(profile, Mapping) or set(profile) != {
            "visible_body_fraction",
            "off_frame_fraction",
            "bbox_height_fraction",
            "required_regions",
        }:
            raise ScenePreflightError("preflight_framing_profile_invalid", name)
        for key in ("visible_body_fraction", "off_frame_fraction", "bbox_height_fraction"):
            _validate_unit_range(profile[key], f"{name}.{key}")
        regions = profile["required_regions"]
        if not isinstance(regions, list) or not regions or len(regions) != len(set(regions)):
            raise ScenePreflightError("preflight_framing_regions_invalid", name)
    collision = policy["collision_limits"]
    expected_collision = (
        "self_body",
        "hair_body",
        "garment_body",
        "garment_garment",
        "person_person",
        "person_prop_support",
    )
    if not isinstance(collision, Mapping) or tuple(collision) != expected_collision:
        raise ScenePreflightError("preflight_collision_policy_invalid", str(collision))
    for category, limits in collision.items():
        if (
            not isinstance(limits, Mapping)
            or set(limits) != {"maximum_depth_mm", "maximum_volume_cc", "exempt_allowed"}
            or not _finite_nonnegative(limits["maximum_depth_mm"])
            or not _finite_nonnegative(limits["maximum_volume_cc"])
            or not isinstance(limits["exempt_allowed"], bool)
        ):
            raise ScenePreflightError("preflight_collision_limit_invalid", category)
    contact = policy["contact"]
    if not isinstance(contact, Mapping) or set(contact) != {
        "intended_distance_mm",
        "maximum_penetration_mm",
        "minimum_normal_dot",
        "maximum_support_drift_mm",
        "all_declared_support_contacts_required",
        "floating_prop_rejected",
    }:
        raise ScenePreflightError("preflight_contact_policy_invalid", str(contact))
    distance = contact["intended_distance_mm"]
    if (
        not isinstance(distance, list)
        or len(distance) != 2
        or not all(_finite_nonnegative(value) for value in distance)
        or distance[0] > distance[1]
        or not _finite_nonnegative(contact["maximum_penetration_mm"])
        or not -1 <= contact["minimum_normal_dot"] <= 1
        or not _finite_nonnegative(contact["maximum_support_drift_mm"])
        or contact["all_declared_support_contacts_required"] is not True
        or contact["floating_prop_rejected"] is not True
    ):
        raise ScenePreflightError("preflight_contact_tolerance_invalid", str(contact))
    geometry = policy["geometry"]
    if (
        not isinstance(geometry, Mapping)
        or set(geometry)
        != {
            "finite_values_required",
            "camera_clipping_rejected",
            "unexpected_renderable_nodes_rejected",
            "undeclared_people_rejected",
            "catastrophic_geometry_rejected",
            "broad_phase_required",
            "narrow_phase_required_for_overlaps",
        }
        or any(value is not True for value in geometry.values())
    ):
        raise ScenePreflightError("preflight_geometry_policy_invalid", str(geometry))
    repair = policy["repair"]
    if (
        not isinstance(repair, Mapping)
        or set(repair)
        != {
            "deterministic_camera_support_correction_maximum",
            "allowed_codes",
            "new_recipe_revision_required",
        }
        or repair["deterministic_camera_support_correction_maximum"] != 2
        or not isinstance(repair["allowed_codes"], list)
        or not repair["allowed_codes"]
        or repair["new_recipe_revision_required"] is not True
    ):
        raise ScenePreflightError("preflight_repair_policy_invalid", str(repair))


def evaluate_scene_preflight(
    pose_selection: Mapping[str, Any],
    formation_selection: Mapping[str, Any],
    observation: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate one final scene observation without allowing a failed metric to be overridden."""

    validate_scene_preflight_policy(policy)
    require_valid_document(pose_selection, "daz_solo_pose_selection")
    require_valid_document(formation_selection, "daz_scene_formation_selection")
    _verify_selection_hash(pose_selection)
    _verify_selection_hash(formation_selection)
    _validate_observation(observation)
    if (
        observation["pose_selection_id"] != pose_selection["selection_id"]
        or observation["pose_selection_sha256"] != pose_selection["selection_sha256"]
    ):
        raise ScenePreflightError("preflight_pose_lineage_mismatch", observation["scene_id"])
    if (
        observation["formation_selection_id"] != formation_selection["selection_id"]
        or observation["formation_selection_sha256"] != formation_selection["selection_sha256"]
    ):
        raise ScenePreflightError("preflight_formation_lineage_mismatch", observation["scene_id"])
    if (
        formation_selection["request"]["person_count"] != 1
        or observation["declared_person_count"] != 1
    ):
        raise ScenePreflightError("preflight_scope_not_solo", observation["scene_id"])
    camera = formation_selection["selected"]["camera"]
    if observation["resolution"] != camera["resolution"] or observation["crop"] != camera["crop"]:
        raise ScenePreflightError("preflight_camera_contract_mismatch", observation["scene_id"])
    framing_profile = camera["framing_profile"]
    if framing_profile not in policy["framing_profiles"]:
        raise ScenePreflightError("preflight_framing_profile_unsupported", framing_profile)

    findings: list[dict[str, Any]] = []
    checks: dict[str, dict[str, Any]] = {}
    _check_scene_integrity(observation, findings, checks)
    _check_person(observation, framing_profile, policy, findings, checks)
    _check_collisions(observation, policy, findings, checks)
    _check_support_contacts(pose_selection, observation, policy, findings, checks)
    _check_prop(formation_selection, observation, policy, findings, checks)
    findings.sort(key=lambda finding: (finding["code"], finding["path"], finding["detail"]))
    failure_codes = sorted({finding["code"] for finding in findings})
    repair_allowed = set(policy["repair"]["allowed_codes"])
    repairable = bool(findings) and set(failure_codes).issubset(repair_allowed)
    repair_budget = policy["repair"]["deterministic_camera_support_correction_maximum"]
    if not findings:
        disposition = "accept"
    elif repairable and observation["repair_attempt"] < repair_budget:
        disposition = "repair"
    else:
        disposition = "reject"
    content = {
        "scene_id": observation["scene_id"],
        "pose_selection_id": pose_selection["selection_id"],
        "pose_selection_sha256": pose_selection["selection_sha256"],
        "formation_selection_id": formation_selection["selection_id"],
        "formation_selection_sha256": formation_selection["selection_sha256"],
        "observation_sha256": _canonical_sha(observation),
        "policy_sha256": _canonical_sha(policy),
        "checks": dict(sorted(checks.items())),
        "findings": findings,
        "summary": {
            "passed": not findings,
            "finding_count": len(findings),
            "failure_codes": failure_codes,
            "disposition": disposition,
            "repair_attempt": observation["repair_attempt"],
            "repair_attempts_remaining": max(0, repair_budget - observation["repair_attempt"]),
            "new_recipe_revision_required_for_repair": disposition == "repair",
        },
    }
    digest = _canonical_sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"dcpf_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    require_valid_document(report, "daz_scene_preflight_report")
    return report


def validate_scene_preflight_report(
    report: Mapping[str, Any],
    pose_selection: Mapping[str, Any],
    formation_selection: Mapping[str, Any],
    observation: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    require_valid_document(report, "daz_scene_preflight_report")
    expected = evaluate_scene_preflight(pose_selection, formation_selection, observation, policy)
    if report != expected:
        raise ScenePreflightError("preflight_report_replay_mismatch", report["report_id"])


def publish_scene_preflight_report(
    report: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    require_valid_document(report, "daz_scene_preflight_report")
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{report['report_id']}.json"
    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise ScenePreflightError("preflight_publication_conflict", str(target))
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


def _validate_observation(observation: Any) -> None:
    expected = {
        "schema_version",
        "scene_id",
        "pose_selection_id",
        "pose_selection_sha256",
        "formation_selection_id",
        "formation_selection_sha256",
        "repair_attempt",
        "declared_person_count",
        "resolution",
        "crop",
        "camera_clipped",
        "unexpected_renderable_node_count",
        "undeclared_person_count",
        "catastrophic_geometry",
        "persons",
        "collisions",
        "support_contacts",
        "prop_observation",
    }
    if not isinstance(observation, Mapping) or set(observation) != expected:
        raise ScenePreflightError("preflight_observation_fields_invalid", str(observation))
    if (
        observation["schema_version"] != "1.0.0"
        or not isinstance(observation["scene_id"], str)
        or not observation["scene_id"].startswith("daz_scene_")
        or not isinstance(observation["repair_attempt"], int)
        or isinstance(observation["repair_attempt"], bool)
        or observation["repair_attempt"] < 0
        or not isinstance(observation["declared_person_count"], int)
        or isinstance(observation["declared_person_count"], bool)
        or not isinstance(observation["camera_clipped"], bool)
        or not isinstance(observation["catastrophic_geometry"], bool)
        or not isinstance(observation["unexpected_renderable_node_count"], int)
        or observation["unexpected_renderable_node_count"] < 0
        or not isinstance(observation["undeclared_person_count"], int)
        or observation["undeclared_person_count"] < 0
    ):
        raise ScenePreflightError("preflight_observation_scalar_invalid", str(observation))
    for key, length in (("resolution", 2), ("crop", 4)):
        values = observation[key]
        if (
            not isinstance(values, list)
            or len(values) != length
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in values
            )
        ):
            raise ScenePreflightError("preflight_observation_frame_invalid", key)
    if (
        not isinstance(observation["persons"], list)
        or not isinstance(observation["collisions"], list)
        or not isinstance(observation["support_contacts"], list)
    ):
        raise ScenePreflightError("preflight_observation_collection_invalid", "collections")
    for person in observation["persons"]:
        _validate_person(person)
    for collision in observation["collisions"]:
        _validate_collision(collision)
    for contact in observation["support_contacts"]:
        _validate_contact(contact)
    prop = observation["prop_observation"]
    if prop is not None:
        if (
            not isinstance(prop, Mapping)
            or set(prop)
            != {
                "stable_object_id",
                "anchored",
                "floating",
                "target_region",
                "target_occlusion_fraction",
                "observed_occlusion_fraction",
            }
            or not isinstance(prop["stable_object_id"], str)
            or not prop["stable_object_id"].startswith("object_")
            or not isinstance(prop["anchored"], bool)
            or not isinstance(prop["floating"], bool)
            or not isinstance(prop["target_region"], str)
            or not _finite_unit(prop["target_occlusion_fraction"])
            or not _finite_unit(prop["observed_occlusion_fraction"])
        ):
            raise ScenePreflightError("preflight_prop_observation_invalid", str(prop))


def _validate_person(person: Any) -> None:
    expected = {
        "construction_id",
        "bbox_xywh",
        "visible_pixels",
        "projected_pixels",
        "prominence",
        "visible_body_fraction",
        "off_frame_fraction",
        "bbox_height_fraction",
        "visible_regions",
    }
    if (
        not isinstance(person, Mapping)
        or set(person) != expected
        or not isinstance(person["construction_id"], str)
        or not person["construction_id"].startswith("c")
        or not isinstance(person["bbox_xywh"], list)
        or len(person["bbox_xywh"]) != 4
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in person["bbox_xywh"]
        )
        or not isinstance(person["visible_pixels"], int)
        or person["visible_pixels"] < 0
        or not isinstance(person["projected_pixels"], int)
        or person["projected_pixels"] <= 0
        or person["visible_pixels"] > person["projected_pixels"]
        or not _finite_unit(person["prominence"])
        or not _finite_unit(person["visible_body_fraction"])
        or not _finite_unit(person["off_frame_fraction"])
        or not _finite_unit(person["bbox_height_fraction"])
        or not isinstance(person["visible_regions"], list)
        or len(person["visible_regions"]) != len(set(person["visible_regions"]))
    ):
        raise ScenePreflightError("preflight_person_observation_invalid", str(person))


def _validate_collision(collision: Any) -> None:
    expected = {
        "pair_id",
        "category",
        "maximum_depth_mm",
        "penetration_volume_cc",
        "visible",
        "intended_contact",
        "exempt",
        "broad_phase_overlap",
        "narrow_phase_ran",
    }
    if (
        not isinstance(collision, Mapping)
        or set(collision) != expected
        or not isinstance(collision["pair_id"], str)
        or not collision["pair_id"]
        or not isinstance(collision["category"], str)
        or not _finite_nonnegative(collision["maximum_depth_mm"])
        or not _finite_nonnegative(collision["penetration_volume_cc"])
        or any(
            not isinstance(collision[key], bool)
            for key in (
                "visible",
                "intended_contact",
                "exempt",
                "broad_phase_overlap",
                "narrow_phase_ran",
            )
        )
    ):
        raise ScenePreflightError("preflight_collision_observation_invalid", str(collision))


def _validate_contact(contact: Any) -> None:
    expected = {
        "contact_id",
        "required",
        "observed",
        "distance_mm",
        "normal_dot",
        "penetration_mm",
        "support_drift_mm",
    }
    if (
        not isinstance(contact, Mapping)
        or set(contact) != expected
        or not isinstance(contact["contact_id"], str)
        or not contact["contact_id"]
        or not isinstance(contact["required"], bool)
        or not isinstance(contact["observed"], bool)
        or not _finite_nonnegative(contact["distance_mm"])
        or not _finite(contact["normal_dot"])
        or not -1 <= contact["normal_dot"] <= 1
        or not _finite_nonnegative(contact["penetration_mm"])
        or not _finite_nonnegative(contact["support_drift_mm"])
    ):
        raise ScenePreflightError("preflight_contact_observation_invalid", str(contact))


def _check_scene_integrity(
    observation: Mapping[str, Any],
    findings: list[dict[str, Any]],
    checks: dict[str, dict[str, Any]],
) -> None:
    values = {
        "camera_clipped": observation["camera_clipped"],
        "unexpected_renderable_node_count": observation["unexpected_renderable_node_count"],
        "undeclared_person_count": observation["undeclared_person_count"],
        "catastrophic_geometry": observation["catastrophic_geometry"],
    }
    failures = {
        "camera_clipped": (values["camera_clipped"], "GEOMETRY_CAMERA_CLIP_REPAIRABLE"),
        "unexpected_renderable_node_count": (
            values["unexpected_renderable_node_count"] != 0,
            "ASSEMBLY_UNEXPECTED_RENDERABLE_NODE",
        ),
        "undeclared_person_count": (
            values["undeclared_person_count"] != 0,
            "ASSEMBLY_UNDECLARED_PERSON",
        ),
        "catastrophic_geometry": (
            values["catastrophic_geometry"],
            "GEOMETRY_CATASTROPHIC",
        ),
    }
    for name, (failed, code) in failures.items():
        checks[name] = {"passed": not failed, "observed": values[name]}
        if failed:
            _finding(findings, code, f"/{name}", str(values[name]))


def _check_person(
    observation: Mapping[str, Any],
    framing_profile: str,
    policy: Mapping[str, Any],
    findings: list[dict[str, Any]],
    checks: dict[str, dict[str, Any]],
) -> None:
    people = observation["persons"]
    count_pass = len(people) == observation["declared_person_count"] == 1
    checks["declared_person_count"] = {
        "passed": count_pass,
        "declared": observation["declared_person_count"],
        "observed": len(people),
    }
    if not count_pass:
        _finding(findings, "ASSEMBLY_PERSON_COUNT_MISMATCH", "/persons", str(len(people)))
        return
    person = people[0]
    width, height = observation["resolution"]
    x, y, bbox_width, bbox_height = person["bbox_xywh"]
    bbox_inside = (
        x + bbox_width <= width and y + bbox_height <= height and bbox_width > 0 and bbox_height > 0
    )
    checks["bbox_inside_frame"] = {"passed": bbox_inside, "bbox_xywh": person["bbox_xywh"]}
    if not bbox_inside:
        _finding(
            findings,
            "GEOMETRY_FRAMING_RECENTERABLE",
            "/persons/0/bbox_xywh",
            str(person["bbox_xywh"]),
        )
    image_area = width * height
    area_fraction = person["visible_pixels"] / image_area
    promotion_pass = area_fraction >= policy["promotion"]["minimum_visible_area_fraction"]
    checks["promotion_visible_area"] = {
        "passed": promotion_pass,
        "observed": round(area_fraction, 9),
        "minimum": policy["promotion"]["minimum_visible_area_fraction"],
    }
    if not promotion_pass:
        _finding(
            findings,
            "GEOMETRY_PERSON_BELOW_PROMINENCE",
            "/persons/0/visible_pixels",
            str(person["visible_pixels"]),
        )
    profile = policy["framing_profiles"][framing_profile]
    for field in ("visible_body_fraction", "off_frame_fraction", "bbox_height_fraction"):
        passed = profile[field][0] <= person[field] <= profile[field][1]
        checks[f"framing_{field}"] = {
            "passed": passed,
            "observed": person[field],
            "allowed": profile[field],
        }
        if not passed:
            _finding(
                findings, "GEOMETRY_FRAMING_RECENTERABLE", f"/persons/0/{field}", str(person[field])
            )
    missing_regions = sorted(set(profile["required_regions"]) - set(person["visible_regions"]))
    checks["framing_required_regions"] = {
        "passed": not missing_regions,
        "missing": missing_regions,
    }
    if missing_regions:
        _finding(
            findings,
            "GEOMETRY_FRAMING_REQUIRED_REGION_MISSING",
            "/persons/0/visible_regions",
            ",".join(missing_regions),
        )
    prominence_pass = abs(person["prominence"] - area_fraction) <= 1e-9
    checks["prominence_recomputed"] = {
        "passed": prominence_pass,
        "observed": person["prominence"],
        "recomputed": round(area_fraction, 9),
    }
    if not prominence_pass:
        _finding(
            findings,
            "GEOMETRY_PROMINENCE_MISMATCH",
            "/persons/0/prominence",
            str(person["prominence"]),
        )


def _check_collisions(
    observation: Mapping[str, Any],
    policy: Mapping[str, Any],
    findings: list[dict[str, Any]],
    checks: dict[str, dict[str, Any]],
) -> None:
    passed = True
    for index, collision in enumerate(observation["collisions"]):
        category = collision["category"]
        if category not in policy["collision_limits"]:
            raise ScenePreflightError("preflight_collision_category_invalid", category)
        if collision["broad_phase_overlap"] and not collision["narrow_phase_ran"]:
            passed = False
            _finding(
                findings,
                "GEOMETRY_NARROW_PHASE_MISSING",
                f"/collisions/{index}",
                collision["pair_id"],
            )
            continue
        if not collision["broad_phase_overlap"] and collision["narrow_phase_ran"]:
            raise ScenePreflightError(
                "preflight_collision_phase_contradiction", collision["pair_id"]
            )
        limits = policy["collision_limits"][category]
        if collision["exempt"] and not limits["exempt_allowed"]:
            passed = False
            _finding(
                findings, "GEOMETRY_COLLISION_EXEMPTION_INVALID", f"/collisions/{index}", category
            )
            continue
        if collision["intended_contact"]:
            maximum_depth = min(
                limits["maximum_depth_mm"], policy["contact"]["maximum_penetration_mm"]
            )
        else:
            maximum_depth = limits["maximum_depth_mm"]
        if (
            collision["maximum_depth_mm"] > maximum_depth
            or collision["penetration_volume_cc"] > limits["maximum_volume_cc"]
        ):
            passed = False
            code = (
                "GEOMETRY_VISIBLE_PENETRATION"
                if collision["visible"]
                else "GEOMETRY_HIDDEN_INTERSECTION_EXCESSIVE"
            )
            _finding(findings, code, f"/collisions/{index}", collision["pair_id"])
    checks["collision_limits"] = {"passed": passed, "pair_count": len(observation["collisions"])}


def _check_support_contacts(
    pose_selection: Mapping[str, Any],
    observation: Mapping[str, Any],
    policy: Mapping[str, Any],
    findings: list[dict[str, Any]],
    checks: dict[str, dict[str, Any]],
) -> None:
    declared = set(pose_selection["selected"]["support_contacts"])
    observed_by_id = {contact["contact_id"]: contact for contact in observation["support_contacts"]}
    if len(observed_by_id) != len(observation["support_contacts"]):
        raise ScenePreflightError("preflight_contact_duplicate", observation["scene_id"])
    missing = sorted(declared - set(observed_by_id))
    passed = not missing
    for contact_id in missing:
        _finding(findings, "GEOMETRY_SUPPORT_CONTACT_MISSING", "/support_contacts", contact_id)
    minimum_distance, maximum_distance = policy["contact"]["intended_distance_mm"]
    for index, contact in enumerate(observation["support_contacts"]):
        if contact["required"] != (contact["contact_id"] in declared):
            raise ScenePreflightError("preflight_contact_required_mismatch", contact["contact_id"])
        if contact["required"] and not contact["observed"]:
            passed = False
            _finding(
                findings,
                "GEOMETRY_SUPPORT_CONTACT_MISSING",
                f"/support_contacts/{index}",
                contact["contact_id"],
            )
        if (
            contact["observed"]
            and not minimum_distance <= contact["distance_mm"] <= maximum_distance
        ):
            passed = False
            _finding(
                findings,
                "GEOMETRY_CONTACT_DISTANCE_INVALID",
                f"/support_contacts/{index}/distance_mm",
                str(contact["distance_mm"]),
            )
        if contact["observed"] and contact["normal_dot"] < policy["contact"]["minimum_normal_dot"]:
            passed = False
            _finding(
                findings,
                "GEOMETRY_CONTACT_NORMAL_INVALID",
                f"/support_contacts/{index}/normal_dot",
                str(contact["normal_dot"]),
            )
        if contact["penetration_mm"] > policy["contact"]["maximum_penetration_mm"]:
            passed = False
            _finding(
                findings,
                "GEOMETRY_CONTACT_PENETRATION",
                f"/support_contacts/{index}/penetration_mm",
                str(contact["penetration_mm"]),
            )
        if contact["support_drift_mm"] > policy["contact"]["maximum_support_drift_mm"]:
            passed = False
            _finding(
                findings,
                "GEOMETRY_SUPPORT_DRIFT_REPAIRABLE",
                f"/support_contacts/{index}/support_drift_mm",
                str(contact["support_drift_mm"]),
            )
    checks["support_contacts"] = {
        "passed": passed,
        "declared": sorted(declared),
        "observed": sorted(observed_by_id),
    }


def _check_prop(
    formation_selection: Mapping[str, Any],
    observation: Mapping[str, Any],
    policy: Mapping[str, Any],
    findings: list[dict[str, Any]],
    checks: dict[str, dict[str, Any]],
) -> None:
    selected = formation_selection["selected"]["prop"]
    observed = observation["prop_observation"]
    if selected is None:
        passed = observed is None
        checks["prop_contract"] = {
            "passed": passed,
            "selected": False,
            "observed": observed is not None,
        }
        if not passed:
            _finding(
                findings,
                "ASSEMBLY_UNDECLARED_PROP",
                "/prop_observation",
                observed["stable_object_id"],
            )
        return
    if observed is None:
        checks["prop_contract"] = {"passed": False, "selected": True, "observed": False}
        _finding(
            findings, "ASSEMBLY_PROP_MISSING", "/prop_observation", selected["stable_object_id"]
        )
        return
    passed = selected["stable_object_id"] == observed["stable_object_id"]
    if not passed:
        _finding(
            findings,
            "ASSEMBLY_PROP_ID_MISMATCH",
            "/prop_observation/stable_object_id",
            observed["stable_object_id"],
        )
    if not observed["anchored"] or observed["floating"]:
        passed = False
        _finding(
            findings, "GEOMETRY_FLOATING_PROP", "/prop_observation", observed["stable_object_id"]
        )
    if (
        observed["target_region"]
        and abs(observed["observed_occlusion_fraction"] - observed["target_occlusion_fraction"])
        > 0.05
    ):
        passed = False
        _finding(
            findings,
            "GEOMETRY_PROP_OCCLUSION_TARGET_MISSED",
            "/prop_observation/observed_occlusion_fraction",
            str(observed["observed_occlusion_fraction"]),
        )
    checks["prop_contract"] = {"passed": passed, "selected": True, "observed": True}


def _verify_selection_hash(selection: Mapping[str, Any]) -> None:
    content = {
        key: value
        for key, value in selection.items()
        if key not in {"schema_version", "selection_id", "selection_sha256"}
    }
    digest = _canonical_sha(content)
    expected_prefix = "dcps_" if selection["selection_id"].startswith("dcps_") else "dcif_"
    if (
        selection["selection_sha256"] != digest
        or selection["selection_id"] != f"{expected_prefix}{digest[:24]}"
    ):
        raise ScenePreflightError(
            "preflight_upstream_selection_hash_invalid", selection["selection_id"]
        )


def _finding(findings: list[dict[str, Any]], code: str, path: str, detail: str) -> None:
    findings.append({"code": code, "path": path, "detail": detail})


def _validate_unit_range(value: Any, name: str) -> None:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(_finite_unit(item) for item in value)
        or value[0] > value[1]
    ):
        raise ScenePreflightError("preflight_unit_range_invalid", name)


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
        raise ScenePreflightError("preflight_noncanonical_value", str(exc)) from exc
    return hashlib.sha256(payload).hexdigest()


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _finite_nonnegative(value: Any) -> bool:
    return _finite(value) and value >= 0


def _finite_unit(value: Any) -> bool:
    return _finite(value) and 0 <= value <= 1


__all__ = [
    "ScenePreflightError",
    "evaluate_scene_preflight",
    "load_scene_preflight_policy",
    "publish_scene_preflight_report",
    "validate_scene_preflight_policy",
    "validate_scene_preflight_report",
]
