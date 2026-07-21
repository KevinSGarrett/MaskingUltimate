"""Deterministic pre-render duo placement, overlap, and contact recipes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import yaml

from ...validation import require_valid_document


class DuoRecipeSelectionError(ValueError):
    """A duo policy, template, or deterministic selection is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_duo_recipe_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_duo_recipe_policy(document)
    return document


def validate_duo_recipe_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "anatomy_families",
        "relationship_families",
        "required_matrix",
        "root_transform_bounds",
        "separation",
        "contact",
        "camera_clearance_required",
        "final_root_joint_and_contact_readback_required",
        "p_index_assignment_stage",
        "templates",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise DuoRecipeSelectionError("duo_policy_fields_invalid", str(policy))
    if (
        policy["schema_version"] != "1.0.0"
        or policy["policy_version"] != "1.0.0"
        or policy["anatomy_families"]
        != {
            "MM": ["adult_male", "adult_male"],
            "MF": ["adult_male", "adult_female"],
            "FF": ["adult_female", "adult_female"],
        }
        or policy["required_matrix"]
        != {
            "anatomy_families": ["MM", "MF", "FF"],
            "relationship_families": ["no_contact", "overlap_no_contact", "contact_support"],
        }
        or policy["camera_clearance_required"] is not True
        or policy["final_root_joint_and_contact_readback_required"] is not True
        or policy["p_index_assignment_stage"] != "after_final_render"
    ):
        raise DuoRecipeSelectionError("duo_policy_identity_invalid", "version/matrix")
    families = policy["relationship_families"]
    if tuple(families) != ("no_contact", "overlap_no_contact", "contact_support"):
        raise DuoRecipeSelectionError("duo_relationship_families_invalid", str(families))
    if any(
        not isinstance(values, list) or not values or len(values) != len(set(values))
        for values in families.values()
    ):
        raise DuoRecipeSelectionError("duo_relationship_taxonomy_invalid", str(families))
    bounds = policy["root_transform_bounds"]
    if (
        not isinstance(bounds, Mapping)
        or set(bounds)
        != {
            "maximum_translation_cm",
            "maximum_rotation_degrees",
            "minimum_scale",
            "maximum_scale",
        }
        or not all(_finite(value) for value in bounds.values())
        or not 0 < bounds["maximum_translation_cm"] <= 250
        or not 0 < bounds["maximum_rotation_degrees"] <= 180
        or not 0 < bounds["minimum_scale"] <= 1 <= bounds["maximum_scale"] <= 2
        or dict(bounds)
        != {
            "maximum_translation_cm": 250.0,
            "maximum_rotation_degrees": 180.0,
            "minimum_scale": 0.85,
            "maximum_scale": 1.15,
        }
    ):
        raise DuoRecipeSelectionError("duo_transform_bounds_invalid", str(bounds))
    separation = policy["separation"]
    if (
        not isinstance(separation, Mapping)
        or set(separation)
        != {
            "minimum_no_contact_root_distance_cm",
            "minimum_overlap_depth_separation_cm",
        }
        or not all(_finite(value) and value > 0 for value in separation.values())
        or dict(separation)
        != {
            "minimum_no_contact_root_distance_cm": 80.0,
            "minimum_overlap_depth_separation_cm": 20.0,
        }
    ):
        raise DuoRecipeSelectionError("duo_separation_policy_invalid", str(separation))
    contact = policy["contact"]
    if (
        set(contact)
        != {
            "minimum_distance_mm",
            "maximum_distance_mm",
            "maximum_penetration_mm",
            "solver_activation",
            "reciprocal_surface_and_normal_check_required",
            "post_simulation_recheck_required",
        }
        or contact["solver_activation"] != "disabled_until_d8_validation"
        or contact["reciprocal_surface_and_normal_check_required"] is not True
        or contact["post_simulation_recheck_required"] is not True
        or not all(
            _finite(contact[key])
            for key in (
                "minimum_distance_mm",
                "maximum_distance_mm",
                "maximum_penetration_mm",
            )
        )
        or not 0 <= contact["minimum_distance_mm"] <= contact["maximum_distance_mm"] <= 20
        or not 0 <= contact["maximum_penetration_mm"] <= contact["maximum_distance_mm"]
        or {
            key: contact[key]
            for key in (
                "minimum_distance_mm",
                "maximum_distance_mm",
                "maximum_penetration_mm",
            )
        }
        != {
            "minimum_distance_mm": 0.0,
            "maximum_distance_mm": 4.0,
            "maximum_penetration_mm": 2.0,
        }
    ):
        raise DuoRecipeSelectionError("duo_contact_policy_invalid", str(contact))
    templates = policy["templates"]
    if not isinstance(templates, list) or not templates:
        raise DuoRecipeSelectionError("duo_templates_invalid", str(templates))
    template_ids = set()
    covered = set()
    for template in templates:
        _validate_template(template, policy)
        if template["template_id"] in template_ids:
            raise DuoRecipeSelectionError("duo_template_duplicate", template["template_id"])
        template_ids.add(template["template_id"])
        covered.add((template["relationship_family"], template["spatial_subfamily"]))
    expected_coverage = {
        (family, subfamily)
        for family, subfamilies in policy["relationship_families"].items()
        for subfamily in subfamilies
    }
    if covered != expected_coverage:
        raise DuoRecipeSelectionError("duo_matrix_incomplete", str(sorted(covered)))


def select_duo_recipe(
    policy: Mapping[str, Any], *, selection_seed: int, anatomy_family: str, relationship_family: str
) -> dict[str, Any]:
    """Select one deterministic fixture-stage duo template without assigning p-indices."""

    validate_duo_recipe_policy(policy)
    if (
        not isinstance(selection_seed, int)
        or isinstance(selection_seed, bool)
        or not 0 <= selection_seed < 2**64
    ):
        raise DuoRecipeSelectionError("duo_seed_invalid", str(selection_seed))
    if anatomy_family not in policy["anatomy_families"]:
        raise DuoRecipeSelectionError("duo_anatomy_family_invalid", anatomy_family)
    if relationship_family not in policy["relationship_families"]:
        raise DuoRecipeSelectionError("duo_relationship_family_invalid", relationship_family)
    candidates = [
        row for row in policy["templates"] if row["relationship_family"] == relationship_family
    ]
    candidates.sort(
        key=lambda row: (_sha({"seed": selection_seed, "template": row}), row["template_id"])
    )
    template = candidates[0]
    anatomy = list(policy["anatomy_families"][anatomy_family])
    if (
        anatomy_family == "MF"
        and int(
            _sha({"selection_seed": selection_seed, "axis": "mixed_anatomy_slot_order"})[:16], 16
        )
        % 2
    ):
        anatomy.reverse()
    slots = [
        {
            "slot_id": slot_id,
            "construction_id": f"c{index}",
            "anatomy_configuration": anatomy[index],
            **template["slots"][slot_id],
        }
        for index, slot_id in enumerate(("a", "b"))
    ]
    request = {
        "selection_seed": selection_seed,
        "anatomy_family": anatomy_family,
        "relationship_family": relationship_family,
    }
    content = {
        "policy_sha256": _sha(policy),
        "request": request,
        "selected_template": {
            "template_id": template["template_id"],
            "template_sha256": _sha(template),
            "relationship_family": template["relationship_family"],
            "spatial_subfamily": template["spatial_subfamily"],
            "camera_clearance": template["camera_clearance"],
        },
        "slots": slots,
        "relationship": {
            **template["relationship"],
            "template_id": template["template_id"],
            "template_sha256": _sha(template),
            "policy_sha256": _sha(policy),
        },
        "evidence_requirements": {
            "slot_names_are_not_p_indices": True,
            "final_p_index_assignment_required": True,
            "contact_solver_required": relationship_family == "contact_support",
            "contact_not_yet_claimed": True,
            "final_root_joint_contact_readback_required": True,
            "camera_clearance_required": True,
            "instance_ownership_validation_required": True,
        },
    }
    digest = _sha(content)
    result = {
        "schema_version": "1.0.0",
        "selection_id": f"dcds_{digest[:24]}",
        "selection_sha256": digest,
        **content,
    }
    require_valid_document(result, "daz_duo_recipe_selection")
    return result


def validate_duo_recipe_selection(selection: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    require_valid_document(selection, "daz_duo_recipe_selection")
    if selection != select_duo_recipe(policy, **selection["request"]):
        raise DuoRecipeSelectionError("duo_selection_replay_mismatch", selection["selection_id"])


def publish_duo_recipe_selection(
    selection: Mapping[str, Any], policy: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    """Atomically publish one replay-validated selection without overwriting conflicts."""

    validate_duo_recipe_selection(selection, policy)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{selection['selection_id']}.json"
    payload = json.dumps(selection, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise DuoRecipeSelectionError("duo_publication_conflict", str(target))
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


def apply_duo_selection_to_recipe_draft(
    draft: Mapping[str, Any], selection: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[str, Any]:
    """Bind a verified duo selection to a two-character draft without assigning p-indices."""

    validate_duo_recipe_selection(selection, policy)
    if not isinstance(draft, Mapping):
        raise DuoRecipeSelectionError("duo_recipe_draft_invalid", str(draft))
    characters = draft.get("characters")
    if (
        not isinstance(characters, list)
        or len(characters) != 2
        or [row.get("construction_id") for row in characters] != ["c0", "c1"]
    ):
        raise DuoRecipeSelectionError("duo_recipe_character_contract_invalid", str(characters))
    result = deepcopy(dict(draft))
    for character, slot in zip(result["characters"], selection["slots"], strict=True):
        if character.get("requested_promoted_id") is not None:
            raise DuoRecipeSelectionError(
                "duo_recipe_p_index_premature", character["construction_id"]
            )
        if character.get("anatomy_configuration") != slot["anatomy_configuration"]:
            raise DuoRecipeSelectionError(
                "duo_recipe_anatomy_mismatch", character["construction_id"]
            )
        character["world_transform"] = deepcopy(slot["root_transform"])
    result["relationship_template"] = {
        **deepcopy(selection["relationship"]),
        "duo_selection_id": selection["selection_id"],
        "duo_selection_sha256": selection["selection_sha256"],
    }
    return result


def _validate_template(template: Any, policy: Mapping[str, Any]) -> None:
    expected = {
        "template_id",
        "relationship_family",
        "spatial_subfamily",
        "slots",
        "relationship",
        "camera_clearance",
    }
    if (
        not isinstance(template, Mapping)
        or set(template) != expected
        or not str(template.get("template_id", "")).startswith("daz_duo_")
    ):
        raise DuoRecipeSelectionError("duo_template_fields_invalid", str(template))
    family = template["relationship_family"]
    if (
        family not in policy["relationship_families"]
        or template["spatial_subfamily"] not in policy["relationship_families"][family]
    ):
        raise DuoRecipeSelectionError(
            "duo_template_family_invalid", str(template.get("template_id"))
        )
    if not isinstance(template["slots"], Mapping) or tuple(template["slots"]) != ("a", "b"):
        raise DuoRecipeSelectionError("duo_slots_invalid", str(template.get("template_id")))
    for slot_id, slot in template["slots"].items():
        if set(slot) != {
            "pose_family",
            "pose_subfamily",
            "root_transform",
            "contact_sites",
            "mutable_dofs",
        }:
            raise DuoRecipeSelectionError("duo_slot_fields_invalid", slot_id)
        _validate_transform(slot["root_transform"], policy)
        if not _token(slot["pose_family"]) or not _token(slot["pose_subfamily"]):
            raise DuoRecipeSelectionError("duo_pose_taxonomy_invalid", slot_id)
        for field in ("contact_sites", "mutable_dofs"):
            if (
                not isinstance(slot[field], list)
                or len(slot[field]) != len(set(slot[field]))
                or any(not _token(v) for v in slot[field])
            ):
                raise DuoRecipeSelectionError("duo_slot_vocabulary_invalid", f"{slot_id}.{field}")
    relationship = template["relationship"]
    if set(relationship) != {
        "type",
        "participants",
        "front_slot",
        "a_site",
        "b_site",
        "distance_mm",
        "maximum_penetration_mm",
    }:
        raise DuoRecipeSelectionError("duo_relationship_fields_invalid", template["template_id"])
    if relationship["participants"] != ["c0", "c1"]:
        raise DuoRecipeSelectionError(
            "duo_relationship_participants_invalid", template["template_id"]
        )
    if family == "no_contact" and (
        relationship
        != {
            "type": "separated",
            "participants": ["c0", "c1"],
            "front_slot": None,
            "a_site": None,
            "b_site": None,
            "distance_mm": None,
            "maximum_penetration_mm": None,
        }
        or any(
            template["slots"][slot][field]
            for slot in ("a", "b")
            for field in ("contact_sites", "mutable_dofs")
        )
        or _distance(template) < policy["separation"]["minimum_no_contact_root_distance_cm"]
    ):
        raise DuoRecipeSelectionError("duo_no_contact_invalid", template["template_id"])
    if family == "overlap_no_contact" and (
        relationship["type"] != "overlap"
        or relationship["front_slot"] not in {"a", "b"}
        or any(
            relationship[field] is not None
            for field in ("a_site", "b_site", "distance_mm", "maximum_penetration_mm")
        )
        or any(
            template["slots"][slot][field]
            for slot in ("a", "b")
            for field in ("contact_sites", "mutable_dofs")
        )
        or abs(
            template["slots"]["a"]["root_transform"]["translation_cm"][2]
            - template["slots"]["b"]["root_transform"]["translation_cm"][2]
        )
        < policy["separation"]["minimum_overlap_depth_separation_cm"]
    ):
        raise DuoRecipeSelectionError("duo_overlap_invalid", template["template_id"])
    if family == "contact_support":
        contact = policy["contact"]
        if (
            relationship["type"] != "contact"
            or relationship["front_slot"] is not None
            or relationship["a_site"] not in template["slots"]["a"]["contact_sites"]
            or relationship["b_site"] not in template["slots"]["b"]["contact_sites"]
            or relationship["distance_mm"]
            != [contact["minimum_distance_mm"], contact["maximum_distance_mm"]]
            or relationship["maximum_penetration_mm"] != contact["maximum_penetration_mm"]
            or not template["slots"]["a"]["mutable_dofs"]
            or not template["slots"]["b"]["mutable_dofs"]
        ):
            raise DuoRecipeSelectionError("duo_contact_invalid", template["template_id"])
    clearance = template["camera_clearance"]
    if set(clearance) != {
        "minimum_people_margin_fraction",
        "minimum_visible_fraction_per_slot",
    } or any(not _finite(v) or not 0 < v <= 1 for v in clearance.values()):
        raise DuoRecipeSelectionError("duo_camera_clearance_invalid", template["template_id"])


def _validate_transform(transform: Any, policy: Mapping[str, Any]) -> None:
    bounds = policy["root_transform_bounds"]
    if (
        not isinstance(transform, Mapping)
        or set(transform) != {"translation_cm", "rotation_deg", "scale"}
        or any(
            not isinstance(transform[k], list)
            or len(transform[k]) != 3
            or any(not _finite(v) for v in transform[k])
            for k in ("translation_cm", "rotation_deg")
        )
        or any(abs(v) > bounds["maximum_translation_cm"] for v in transform["translation_cm"])
        or any(abs(v) > bounds["maximum_rotation_degrees"] for v in transform["rotation_deg"])
        or not _finite(transform["scale"])
        or not bounds["minimum_scale"] <= transform["scale"] <= bounds["maximum_scale"]
    ):
        raise DuoRecipeSelectionError("duo_root_transform_invalid", str(transform))


def _distance(template: Mapping[str, Any]) -> float:
    a = template["slots"]["a"]["root_transform"]["translation_cm"]
    b = template["slots"]["b"]["root_transform"]["translation_cm"]
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _token(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value
        and value.replace("_", "a").isalnum()
        and value[0].islower()
    )


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


__all__ = [
    "DuoRecipeSelectionError",
    "apply_duo_selection_to_recipe_draft",
    "load_duo_recipe_policy",
    "publish_duo_recipe_selection",
    "select_duo_recipe",
    "validate_duo_recipe_policy",
    "validate_duo_recipe_selection",
]
