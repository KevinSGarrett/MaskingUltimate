"""Closed D9 coverage vocabulary bound to canonical and DAZ source snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml

from ...datasets.coverage import ATTRIBUTES, CONTEXTS, POSES, VIEWS
from ...models.ontology_contract import V2_PART_CLASS_NAMES
from ...validation import require_valid_document


class CoverageVocabularyError(ValueError):
    """The policy, bound source, vocabulary report, or publication is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


SOURCE_PATHS = {
    "canonical_coverage": "src/maskfactory/datasets/coverage.py",
    "ontology_contract": "src/maskfactory/models/ontology_contract.py",
    "character_profiles": "configs/daz/character_profiles.yaml",
    "appearance_selection": "configs/daz/appearance_selection.yaml",
    "solo_pose_selection": "configs/daz/solo_pose_selection.yaml",
    "scene_formation_selection": "configs/daz/scene_formation_selection.yaml",
    "duo_recipe_selection": "configs/daz/duo_recipe_selection.yaml",
    "render_pass_profiles": "configs/daz/render_pass_profiles.yaml",
    "asset_vocabularies": "configs/daz/asset_vocabularies.yaml",
}

REQUIRED_AXIS_IDS = (
    "canonical_view",
    "canonical_pose",
    "instance_context",
    "canonical_attribute",
    "ontology_version",
    "ontology_label",
    "figure_generation",
    "anatomy_configuration",
    "anatomy_composition",
    "presentation",
    "adult_age_appearance",
    "body_shape_tier",
    "skin_tone_band",
    "skin_undertone",
    "skin_response",
    "hair_construction",
    "hair_length",
    "hair_texture",
    "hair_occlusion",
    "wardrobe_state",
    "fit_profile",
    "opacity_class",
    "garment_layer_count",
    "clothing_boundary_property",
    "pose_family",
    "support_mode",
    "self_occlusion",
    "relationship_family",
    "instance_count",
    "camera_azimuth",
    "camera_elevation",
    "camera_roll",
    "focal_family",
    "framing_profile",
    "aspect_ratio",
    "resolution_profile",
    "depth_of_field_mode",
    "motion_blur_mode",
    "lighting_profile",
    "exposure_profile",
    "environment_family",
    "environment_subfamily",
    "context_complexity",
    "prop_mode",
    "prop_role",
    "prop_anchor_type",
    "render_profile",
    "degradation_lane",
    "label_visibility_state",
    "p_index_role",
    "finger_configuration",
    "footwear_state",
    "body_region_major",
    "background_contrast",
    "appearance_similarity",
    "crop_region",
)

REQUIRED_REGISTRY_AXIS_IDS = (
    "asset_product_family",
    "character_preset_id",
    "skin_material_asset_id",
    "hair_asset_id",
    "garment_asset_id",
    "pose_asset_id",
    "environment_asset_id",
    "recipe_family_id",
)

REQUIRED_CONTINUOUS_AXIS_IDS = (
    "body_morph_value",
    "camera_azimuth_degrees",
    "camera_elevation_degrees",
    "camera_roll_degrees",
    "focal_length_mm",
    "prominence_score",
)

REQUIRED_INTERSECTION_IDS = (
    "hands_fingers_framing",
    "hand_body_target",
    "hands_prop_grip",
    "feet_footwear_low_angle",
    "hair_region_occlusion",
    "hair_background_contrast",
    "skin_lighting",
    "wardrobe_view",
    "garment_skin_boundary",
    "anatomy_visibility",
    "age_body_pose",
    "wide_foreshortening",
    "telephoto_multi_depth",
    "multi_crossed_similar",
    "anatomy_p_index_role",
    "crop_body_region",
    "support_pose",
    "prop_body_occlusion",
)

REPORTING_STATES = (
    "planned",
    "attempted",
    "rendered",
    "accepted",
    "packaged",
    "dataset_selected",
    "consumed_by_training",
)
REPORTING_UNITS = ("scene", "person_instance", "effective_training_weight")


def load_coverage_vocabulary(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_coverage_vocabulary(document)
    return document


def validate_coverage_vocabulary(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "vocabulary_version",
        "scope",
        "source_snapshots",
        "axes",
        "registry_axes",
        "continuous_axes",
        "high_risk_intersections",
        "reporting",
        "authority",
        "publication",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise CoverageVocabularyError("coverage_vocabulary_fields_invalid", str(policy))
    if (
        policy["schema_version"] != "1.0.0"
        or policy["vocabulary_version"] != "1.0.0"
        or policy["scope"] != "daz_coverage_planning_and_reporting"
    ):
        raise CoverageVocabularyError("coverage_vocabulary_identity_invalid", str(policy))
    _validate_sources(policy["source_snapshots"])
    axes = _validate_axes(policy["axes"])
    by_axis = {row["axis_id"]: row["values"] for row in policy["axes"]}
    if (
        by_axis["canonical_view"] != list(VIEWS)
        or by_axis["canonical_pose"] != list(POSES)
        or by_axis["instance_context"] != list(CONTEXTS)
        or by_axis["canonical_attribute"] != list(ATTRIBUTES)
        or by_axis["ontology_label"] != list(V2_PART_CLASS_NAMES[1:])
    ):
        raise CoverageVocabularyError(
            "coverage_vocabulary_canonical_crosswalk_invalid", "canonical_coverage"
        )
    registry_axes = _validate_registry_axes(policy["registry_axes"])
    _validate_continuous_axes(policy["continuous_axes"])
    _validate_intersections(policy["high_risk_intersections"], axes | registry_axes)
    if policy["reporting"] != {
        "states": list(REPORTING_STATES),
        "units": list(REPORTING_UNITS),
        "separate_marginal_pairwise_and_selected_three_way": True,
        "accepted_only_updates_accepted_coverage": True,
        "scene_count_is_not_person_instance_count": True,
        "effective_weight_is_not_instance_count": True,
    }:
        raise CoverageVocabularyError(
            "coverage_vocabulary_reporting_invalid", str(policy["reporting"])
        )
    if policy["authority"] != {
        "synthetic_counts_as_gold": False,
        "synthetic_counts_as_real_accuracy": False,
        "synthetic_diagnostic_is_promotion_authority": False,
        "registry_values_require_versioned_snapshot": True,
        "unknown_values_fail_closed": True,
    }:
        raise CoverageVocabularyError(
            "coverage_vocabulary_authority_invalid", str(policy["authority"])
        )
    if policy["publication"] != {"immutable": True, "atomic": True}:
        raise CoverageVocabularyError(
            "coverage_vocabulary_publication_invalid", str(policy["publication"])
        )


def build_coverage_vocabulary_report(
    policy: Mapping[str, Any], repository_root: Path
) -> dict[str, Any]:
    """Verify every bound source and emit the normalized closed-vocabulary report."""

    validate_coverage_vocabulary(policy)
    root = Path(repository_root).resolve(strict=True)
    source_records = []
    source_documents: dict[str, Any] = {}
    for source in policy["source_snapshots"]:
        path = (root / source["path"]).resolve(strict=True)
        if root not in path.parents:
            raise CoverageVocabularyError("coverage_vocabulary_source_escape", str(path))
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != source["sha256"]:
            raise CoverageVocabularyError(
                "coverage_vocabulary_source_hash_mismatch", source["source_id"]
            )
        source_records.append({**source, "bytes": len(payload)})
        if path.suffix.lower() in {".yaml", ".yml"}:
            source_documents[source["source_id"]] = yaml.safe_load(payload)
    _validate_source_crosswalk(policy["axes"], source_documents)
    content = {
        "vocabulary_version": policy["vocabulary_version"],
        "policy_sha256": _canonical_sha(policy),
        "scope": policy["scope"],
        "source_snapshots": source_records,
        "axes": [{**axis, "value_count": len(axis["values"])} for axis in policy["axes"]],
        "registry_axes": [dict(axis) for axis in policy["registry_axes"]],
        "continuous_axes": [dict(axis) for axis in policy["continuous_axes"]],
        "high_risk_intersections": [
            dict(intersection) for intersection in policy["high_risk_intersections"]
        ],
        "reporting": dict(policy["reporting"]),
        "authority": dict(policy["authority"]),
        "publication": dict(policy["publication"]),
        "summary": {
            "closed": True,
            "source_hashes_match": True,
            "canonical_crosswalk_exact": True,
            "fixed_axis_count": len(policy["axes"]),
            "fixed_value_count": sum(len(axis["values"]) for axis in policy["axes"]),
            "registry_axis_count": len(policy["registry_axes"]),
            "continuous_axis_count": len(policy["continuous_axes"]),
            "high_risk_intersection_count": len(policy["high_risk_intersections"]),
        },
    }
    digest = _canonical_sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"dcvr_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    validate_coverage_vocabulary_report(report)
    return report


def validate_coverage_vocabulary_report(report: Mapping[str, Any]) -> None:
    require_valid_document(report, "daz_coverage_vocabulary_report")
    _verify_hashed_document(report, "report_id", "report_sha256", "dcvr")
    axes = report["axes"]
    registry_axes = report["registry_axes"]
    continuous_axes = report["continuous_axes"]
    intersections = report["high_risk_intersections"]
    reconstructed_policy = {
        "schema_version": "1.0.0",
        "vocabulary_version": report["vocabulary_version"],
        "scope": report["scope"],
        "source_snapshots": [
            {key: value for key, value in source.items() if key != "bytes"}
            for source in report["source_snapshots"]
        ],
        "axes": [
            {key: value for key, value in axis.items() if key != "value_count"} for axis in axes
        ],
        "registry_axes": registry_axes,
        "continuous_axes": continuous_axes,
        "high_risk_intersections": intersections,
        "reporting": report["reporting"],
        "authority": report["authority"],
        "publication": report["publication"],
    }
    validate_coverage_vocabulary(reconstructed_policy)
    if (
        report["policy_sha256"] != _canonical_sha(reconstructed_policy)
        or [axis["axis_id"] for axis in axes] != list(REQUIRED_AXIS_IDS)
        or [axis["axis_id"] for axis in registry_axes] != list(REQUIRED_REGISTRY_AXIS_IDS)
        or [axis["axis_id"] for axis in continuous_axes] != list(REQUIRED_CONTINUOUS_AXIS_IDS)
        or [row["intersection_id"] for row in intersections] != list(REQUIRED_INTERSECTION_IDS)
        or any(axis["value_count"] != len(axis["values"]) for axis in axes)
        or report["summary"]
        != {
            "closed": True,
            "source_hashes_match": True,
            "canonical_crosswalk_exact": True,
            "fixed_axis_count": len(axes),
            "fixed_value_count": sum(len(axis["values"]) for axis in axes),
            "registry_axis_count": len(registry_axes),
            "continuous_axis_count": len(continuous_axes),
            "high_risk_intersection_count": len(intersections),
        }
    ):
        raise CoverageVocabularyError(
            "coverage_vocabulary_report_semantics_invalid", report["report_id"]
        )


def publish_coverage_vocabulary_report(
    report: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    validate_coverage_vocabulary_report(report)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{report['report_id']}.json"
    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise CoverageVocabularyError("coverage_vocabulary_publication_conflict", str(target))
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


def _validate_sources(sources: Any) -> None:
    if not isinstance(sources, list):
        raise CoverageVocabularyError("coverage_vocabulary_sources_invalid", str(sources))
    expected_fields = {"source_id", "path", "sha256"}
    if (
        [row.get("source_id") for row in sources] != list(SOURCE_PATHS)
        or any(not isinstance(row, Mapping) or set(row) != expected_fields for row in sources)
        or any(row["path"] != SOURCE_PATHS[row["source_id"]] for row in sources)
        or any(not _sha256(row["sha256"]) for row in sources)
    ):
        raise CoverageVocabularyError("coverage_vocabulary_sources_invalid", str(sources))


def _validate_axes(axes: Any) -> set[str]:
    fields = {"axis_id", "layer", "unit", "authority", "values"}
    if (
        not isinstance(axes, list)
        or [row.get("axis_id") for row in axes] != list(REQUIRED_AXIS_IDS)
        or any(not isinstance(row, Mapping) or set(row) != fields for row in axes)
    ):
        raise CoverageVocabularyError("coverage_vocabulary_axes_invalid", str(axes))
    for axis in axes:
        values = axis["values"]
        if (
            axis["unit"] not in {"scene", "person_instance"}
            or axis["layer"]
            not in {
                "canonical",
                "generation",
                "risk",
                "image_formation",
                "render",
                "label",
                "multi_person",
            }
            or not isinstance(axis["authority"], str)
            or not axis["authority"]
            or not isinstance(values, list)
            or not values
            or len({_canonical_sha(value) for value in values}) != len(values)
            or any(
                isinstance(value, bool)
                or not isinstance(value, (str, int))
                or isinstance(value, str)
                and not value
                for value in values
            )
        ):
            raise CoverageVocabularyError(
                "coverage_vocabulary_axis_values_invalid", axis["axis_id"]
            )
    return set(REQUIRED_AXIS_IDS)


def _validate_registry_axes(axes: Any) -> set[str]:
    fields = {"axis_id", "layer", "unit", "registry", "value_pattern"}
    if (
        not isinstance(axes, list)
        or [row.get("axis_id") for row in axes] != list(REQUIRED_REGISTRY_AXIS_IDS)
        or any(not isinstance(row, Mapping) or set(row) != fields for row in axes)
    ):
        raise CoverageVocabularyError("coverage_vocabulary_registry_axes_invalid", str(axes))
    for axis in axes:
        try:
            re.compile(axis["value_pattern"])
        except (TypeError, re.error) as exc:
            raise CoverageVocabularyError(
                "coverage_vocabulary_registry_pattern_invalid", axis["axis_id"]
            ) from exc
        if (
            axis["layer"] != "inventory"
            or axis["unit"] not in {"scene", "person_instance"}
            or axis["registry"] not in {"daz_asset_registry", "daz_recipe_registry"}
        ):
            raise CoverageVocabularyError(
                "coverage_vocabulary_registry_axis_invalid", axis["axis_id"]
            )
    return set(REQUIRED_REGISTRY_AXIS_IDS)


def _validate_continuous_axes(axes: Any) -> None:
    fields = {"axis_id", "unit", "minimum", "maximum", "authority"}
    if (
        not isinstance(axes, list)
        or [row.get("axis_id") for row in axes] != list(REQUIRED_CONTINUOUS_AXIS_IDS)
        or any(not isinstance(row, Mapping) or set(row) != fields for row in axes)
    ):
        raise CoverageVocabularyError("coverage_vocabulary_continuous_axes_invalid", str(axes))
    for axis in axes:
        if (
            axis["unit"] not in {"scene", "person_instance"}
            or isinstance(axis["minimum"], bool)
            or isinstance(axis["maximum"], bool)
            or not isinstance(axis["minimum"], (int, float))
            or not isinstance(axis["maximum"], (int, float))
            or axis["minimum"] >= axis["maximum"]
            or not isinstance(axis["authority"], str)
            or not axis["authority"]
        ):
            raise CoverageVocabularyError(
                "coverage_vocabulary_continuous_axis_invalid", axis["axis_id"]
            )


def _validate_intersections(intersections: Any, axes: set[str]) -> None:
    if (
        not isinstance(intersections, list)
        or [row.get("intersection_id") for row in intersections] != list(REQUIRED_INTERSECTION_IDS)
        or any(
            not isinstance(row, Mapping)
            or set(row) != {"intersection_id", "axes"}
            or not isinstance(row["axes"], list)
            or not 2 <= len(row["axes"]) <= 4
            or len(set(row["axes"])) != len(row["axes"])
            or not set(row["axes"]) <= axes
            for row in intersections
        )
    ):
        raise CoverageVocabularyError(
            "coverage_vocabulary_intersections_invalid", str(intersections)
        )


def _validate_source_crosswalk(axes: list[Mapping[str, Any]], documents: Mapping[str, Any]) -> None:
    by_axis = {row["axis_id"]: row["values"] for row in axes}
    character = documents["character_profiles"]
    appearance = documents["appearance_selection"]
    pose = documents["solo_pose_selection"]
    formation = documents["scene_formation_selection"]
    duo = documents["duo_recipe_selection"]
    render = documents["render_pass_profiles"]
    assets = documents["asset_vocabularies"]
    expected = {
        "canonical_view": list(VIEWS),
        "canonical_pose": list(POSES),
        "instance_context": list(CONTEXTS),
        "canonical_attribute": list(ATTRIBUTES),
        "figure_generation": assets["figure_generations"],
        "anatomy_configuration": appearance["anatomy_configurations"],
        "adult_age_appearance": list(character["age_categories"]),
        "body_shape_tier": list(character["distribution_tiers"]),
        "wardrobe_state": list(appearance["wardrobe_states"]),
        "fit_profile": _ordered_union(
            row["allowed_fit_profiles"] for row in appearance["wardrobe_states"].values()
        ),
        "pose_family": list(pose["taxonomy"]),
        "support_mode": _ordered_union(pose["family_support_modes"].values()),
        "self_occlusion": pose["self_occlusion_tags"],
        "relationship_family": list(duo["relationship_families"]),
        "camera_azimuth": list(formation["camera"]["azimuth_bins"]),
        "camera_elevation": list(formation["camera"]["elevation_bins"]),
        "camera_roll": list(formation["camera"]["roll_bins"]),
        "focal_family": list(formation["camera"]["focal_families"]),
        "framing_profile": formation["camera"]["framing_profiles"],
        "aspect_ratio": formation["camera"]["aspect_ratios"],
        "resolution_profile": list(formation["camera"]["resolution_profiles"]),
        "depth_of_field_mode": formation["camera"]["depth_of_field_modes"],
        "motion_blur_mode": formation["camera"]["motion_blur_modes"],
        "lighting_profile": formation["lighting_profiles"],
        "exposure_profile": formation["exposure_profiles"],
        "environment_family": list(formation["environment_families"]),
        "environment_subfamily": _ordered_union(formation["environment_families"].values()),
        "context_complexity": formation["context_complexities"],
        "prop_mode": formation["prop_modes"],
        "prop_role": formation["prop_roles"],
        "prop_anchor_type": formation["prop_anchor_types"],
        "render_profile": list(render["profiles"]),
    }
    mismatched = [axis_id for axis_id, values in expected.items() if by_axis[axis_id] != values]
    if mismatched:
        raise CoverageVocabularyError(
            "coverage_vocabulary_source_crosswalk_invalid", ",".join(mismatched)
        )


def _ordered_union(groups: Any) -> list[Any]:
    result = []
    for group in groups:
        for value in group:
            if value not in result:
                result.append(value)
    return result


def _verify_hashed_document(
    document: Mapping[str, Any], id_field: str, hash_field: str, prefix: str
) -> None:
    content = {
        key: value
        for key, value in document.items()
        if key not in {"schema_version", id_field, hash_field}
    }
    digest = _canonical_sha(content)
    if document[hash_field] != digest or document[id_field] != f"{prefix}_{digest[:24]}":
        raise CoverageVocabularyError(
            "coverage_vocabulary_document_hash_invalid", str(document.get(id_field))
        )


def _canonical_sha(value: Any) -> str:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CoverageVocabularyError("coverage_vocabulary_noncanonical", str(exc)) from exc
    return hashlib.sha256(payload).hexdigest()


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None
