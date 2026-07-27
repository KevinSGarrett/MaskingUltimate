"""Build a fail-closed 66-class source/truth/critic gap matrix."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import yaml

from .continuous_contract import canonical_sha256
from .visual_reference_readiness import validate_visual_reference_readiness

SCHEMA_VERSION = "maskfactory.visual_66_class_gap_matrix.v1"
ZERO_SHA256 = "0" * 64

REFERENCE_TAG_BY_CLASS = {
    "hair": "part_hair",
    "head_face": "part_head_face",
    "neck": "part_neck_throat",
    "chest_upper_torso": "part_torso_abdomen",
    "left_breast": "part_chest_breasts",
    "right_breast": "part_chest_breasts",
    "abdomen_stomach": "part_torso_abdomen",
    "belly_button": "part_torso_abdomen",
    "pelvic_region": "part_hips_pelvis_buttocks",
    "left_hip": "part_hips_pelvis_buttocks",
    "right_hip": "part_hips_pelvis_buttocks",
    "left_shoulder": "part_shoulder",
    "right_shoulder": "part_shoulder",
    "left_upper_arm": "part_upper_arm",
    "right_upper_arm": "part_upper_arm",
    "left_elbow": "part_elbow",
    "right_elbow": "part_elbow",
    "left_forearm": "part_forearm_wrist",
    "right_forearm": "part_forearm_wrist",
    "left_wrist": "part_forearm_wrist",
    "right_wrist": "part_forearm_wrist",
    "left_hand_base": "part_hand_fingers",
    "right_hand_base": "part_hand_fingers",
    "left_thumb": "part_hand_fingers",
    "right_thumb": "part_hand_fingers",
    "left_index_finger": "part_hand_fingers",
    "right_index_finger": "part_hand_fingers",
    "left_middle_finger": "part_hand_fingers",
    "right_middle_finger": "part_hand_fingers",
    "left_ring_finger": "part_hand_fingers",
    "right_ring_finger": "part_hand_fingers",
    "left_pinky": "part_hand_fingers",
    "right_pinky": "part_hand_fingers",
    "left_glute": "part_hips_pelvis_buttocks",
    "right_glute": "part_hips_pelvis_buttocks",
    "left_thigh": "part_thigh",
    "right_thigh": "part_thigh",
    "left_knee": "part_knee",
    "right_knee": "part_knee",
    "left_calf": "part_lower_leg_calf",
    "right_calf": "part_lower_leg_calf",
    "left_ankle": "part_ankle",
    "right_ankle": "part_ankle",
    "left_foot_base": "part_foot_toes",
    "right_foot_base": "part_foot_toes",
    "left_toes": "part_foot_toes",
    "right_toes": "part_foot_toes",
    "back_upper_torso": "part_back",
    "back_lower_torso": "part_back",
    "left_ear": "part_ear",
    "right_ear": "part_ear",
    "left_areola": "part_chest_breasts",
    "right_areola": "part_chest_breasts",
    "left_nipple": "part_chest_breasts",
    "right_nipple": "part_chest_breasts",
    "vulva": "part_groin_intimate",
    "penis_shaft": "part_groin_intimate",
    "glans_penis": "part_groin_intimate",
    "left_scrotal_region": "part_groin_intimate",
    "right_scrotal_region": "part_groin_intimate",
    "anus": "part_groin_intimate",
}

COMPLETED_CALIBRATION_CLASSES = {
    "hair",
    "head_face",
    "neck",
    "left_breast",
    "right_breast",
    "left_glute",
    "right_glute",
    "vulva",
    "penis_shaft",
    "glans_penis",
    "left_scrotal_region",
    "right_scrotal_region",
    "anus",
}

EXTERNAL_CANDIDATE_BY_CLASS = {
    "left_breast": "coarse_unsided_breast_region",
    "right_breast": "coarse_unsided_breast_region",
    "left_glute": "coarse_unsided_buttocks_region",
    "right_glute": "coarse_unsided_buttocks_region",
    "left_areola": "explicitly_not_directly_supplied",
    "right_areola": "explicitly_not_directly_supplied",
    "left_nipple": "unsided_nipple_candidate_only",
    "right_nipple": "unsided_nipple_candidate_only",
    "vulva": "coarse_external_vulva_alias",
    "penis_shaft": "coarse_unsplit_penis_region",
    "glans_penis": "coarse_unsplit_penis_region",
    "left_scrotal_region": "ambiguous_unsided_scrotal_region",
    "right_scrotal_region": "ambiguous_unsided_scrotal_region",
    "anus": "exact_name_candidate_annotation",
}


class Visual66ClassGapMatrixError(RuntimeError):
    """The current 66-class gap matrix cannot be proven."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_object(value: bytes, *, name: str) -> dict[str, Any]:
    try:
        document = json.loads(value.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Visual66ClassGapMatrixError(f"{name} is unreadable") from exc
    if not isinstance(document, dict):
        raise Visual66ClassGapMatrixError(f"{name} must be an object")
    return document


def _part_labels(ontology_bytes: bytes) -> list[dict[str, Any]]:
    try:
        ontology = yaml.safe_load(ontology_bytes)
    except yaml.YAMLError as exc:
        raise Visual66ClassGapMatrixError("ontology YAML is unreadable") from exc
    if not isinstance(ontology, dict) or not isinstance(ontology.get("labels"), list):
        raise Visual66ClassGapMatrixError("ontology labels are unavailable")
    labels = [
        label
        for label in ontology["labels"]
        if isinstance(label, dict)
        and label.get("map") == "part"
        and isinstance(label.get("id"), int)
    ]
    labels.sort(key=lambda label: int(label["id"]))
    if [label["id"] for label in labels] != list(range(66)):
        raise Visual66ClassGapMatrixError("ontology part IDs are not exactly 0..65")
    if len({str(label.get("name")) for label in labels}) != 66:
        raise Visual66ClassGapMatrixError("ontology part names are not unique")
    return labels


def build_visual_66_class_gap_matrix(
    *,
    ontology_bytes: bytes,
    ontology_git_commit: str,
    ontology_git_path: str,
    ontology_git_blob: str,
    readiness_bytes: bytes,
    crosswalk_bytes: bytes,
    observed_at_utc: str,
) -> dict[str, Any]:
    """Return the current class-by-class evidence and qualification gaps."""

    if (
        len(ontology_git_commit) != 40
        or len(ontology_git_blob) != 40
        or not ontology_git_path
    ):
        raise Visual66ClassGapMatrixError("ontology Git provenance is invalid")
    readiness = _load_object(readiness_bytes, name="readiness receipt")
    validate_visual_reference_readiness(readiness)
    crosswalk = _load_object(crosswalk_bytes, name="ontology crosswalk")
    if crosswalk.get("schema_version") != (
        "maskfactory.nude_external_ontology_crosswalk.v1"
    ):
        raise Visual66ClassGapMatrixError("ontology crosswalk schema is invalid")
    explicitly_missing = crosswalk.get("not_directly_supplied_as_reliable_fine_masks")
    if not isinstance(explicitly_missing, list):
        raise Visual66ClassGapMatrixError("crosswalk fine-mask exclusions are absent")
    benchmark_counts = readiness["reference_library"][
        "benchmark_body_part_tag_counts"
    ]
    rows: list[dict[str, Any]] = []
    for label in _part_labels(ontology_bytes):
        name = str(label["name"])
        reference_tag = REFERENCE_TAG_BY_CLASS.get(name)
        external = EXTERNAL_CANDIDATE_BY_CLASS.get(name)
        explicit_crosswalk_gap = name in explicitly_missing or (
            name == "glans_penis" and "penis_glans" in explicitly_missing
        )
        completed = name in COMPLETED_CALIBRATION_CLASSES
        rows.append(
            {
                "class_id": int(label["id"]),
                "class_name": name,
                "side": label.get("side"),
                "enabled": label.get("enabled") is True,
                "reference_metadata_tag": reference_tag,
                "reference_benchmark_count": (
                    int(benchmark_counts.get(reference_tag, 0))
                    if reference_tag
                    else 0
                ),
                "reference_metadata_is_mask_truth": False,
                "external_annotation_candidate": external,
                "crosswalk_explicitly_lacks_reliable_fine_mask": (
                    explicit_crosswalk_gap
                ),
                "completed_calibration_only": completed,
                "current_qualified_mask_truth": False,
                "current_qualified_primary": False,
                "current_independent_family_juror": False,
                "promotion_eligible": False,
                "next_action": (
                    "background_no_candidate_required"
                    if name == "background"
                    else (
                        "preserve_completed_calibration_no_rerun"
                        if completed
                        else "requires_source_bound_mask_truth_and_dual_critic_review"
                    )
                ),
            }
        )
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "observed_at_utc": observed_at_utc,
        "ontology": {
            "git_commit": ontology_git_commit,
            "git_path": ontology_git_path,
            "git_blob": ontology_git_blob,
            "bytes": len(ontology_bytes),
            "sha256": _sha256_bytes(ontology_bytes),
            "runtime_activation_claimed": False,
        },
        "inputs": {
            "readiness_receipt_bytes": len(readiness_bytes),
            "readiness_receipt_raw_sha256": _sha256_bytes(readiness_bytes),
            "readiness_receipt_self_sha256": readiness["self_sha256"],
            "crosswalk_bytes": len(crosswalk_bytes),
            "crosswalk_sha256": _sha256_bytes(crosswalk_bytes),
        },
        "class_count": 66,
        "classes": rows,
        "summary": {
            "classes_with_reference_metadata_hint": sum(
                row["reference_metadata_tag"] is not None for row in rows
            ),
            "classes_with_external_annotation_candidate": sum(
                row["external_annotation_candidate"] is not None for row in rows
            ),
            "classes_with_current_qualified_mask_truth": 0,
            "classes_with_current_qualified_primary": 0,
            "classes_with_current_independent_family_juror": 0,
            "completed_calibration_only_classes": sum(
                row["completed_calibration_only"] for row in rows
            ),
            "promotion_eligible_classes": 0,
        },
        "authority_boundary": {
            "classification": "SOURCE_TRUTH_CRITIC_GAP_MATRIX_ONLY",
            "promotion_allowed": False,
            "candidate_materialization_allowed": False,
            "candidate_screening_allowed": True,
            "mask_generation_performed": False,
            "visual_critic_execution_performed": False,
            "limitations": [
                "Reference tags are coarse retrieval hints and include observed false positives.",
                "External aliases cannot infer side or finer atomic anatomy.",
                "Completed calibration-only classes remain non-production evidence.",
                "Every non-background class still lacks current qualified mask truth.",
                "The full suite still lacks a qualified primary and independent-family juror.",
            ],
        },
        "self_sha256": ZERO_SHA256,
    }
    receipt["self_sha256"] = canonical_sha256(receipt)
    validate_visual_66_class_gap_matrix(receipt)
    return receipt


def validate_visual_66_class_gap_matrix(receipt: Mapping[str, Any]) -> None:
    """Validate the zero-self hash, exact class coverage, and no-credit boundary."""

    declared = receipt.get("self_sha256")
    if not isinstance(declared, str) or len(declared) != 64:
        raise Visual66ClassGapMatrixError("gap matrix self hash is invalid")
    canonical = dict(receipt)
    canonical["self_sha256"] = ZERO_SHA256
    if canonical_sha256(canonical) != declared:
        raise Visual66ClassGapMatrixError("gap matrix self hash mismatch")
    classes = receipt.get("classes")
    summary = receipt.get("summary")
    boundary = receipt.get("authority_boundary")
    if (
        receipt.get("schema_version") != SCHEMA_VERSION
        or receipt.get("class_count") != 66
        or not isinstance(classes, list)
        or [row.get("class_id") for row in classes] != list(range(66))
        or not isinstance(summary, Mapping)
        or not isinstance(boundary, Mapping)
    ):
        raise Visual66ClassGapMatrixError("gap matrix structure is invalid")
    if (
        summary.get("classes_with_current_qualified_mask_truth") != 0
        or summary.get("classes_with_current_qualified_primary") != 0
        or summary.get("classes_with_current_independent_family_juror") != 0
        or summary.get("promotion_eligible_classes") != 0
        or boundary.get("promotion_allowed") is not False
        or boundary.get("candidate_materialization_allowed") is not False
        or boundary.get("mask_generation_performed") is not False
        or boundary.get("visual_critic_execution_performed") is not False
    ):
        raise Visual66ClassGapMatrixError("gap matrix exceeds current authority")
