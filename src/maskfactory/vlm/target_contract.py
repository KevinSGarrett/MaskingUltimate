"""Exact target binding required before visual criticism or bounded repair."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .critic_catalog import canonical_sha256

SHA256 = re.compile(r"^[a-f0-9]{64}$")
CONTRACT_KEYS = frozenset(
    {
        "schema_version",
        "contract_id",
        "source",
        "owner",
        "target",
        "candidate",
        "excluded_labels",
        "protected_regions",
        "transforms",
        "contract_sha256",
    }
)
V2_CONTRACT_KEYS = frozenset(
    {
        "schema_version",
        "contract_id",
        "source",
        "owner",
        "target",
        "candidate",
        "protected_regions",
        "transforms",
        "package",
        "contract_sha256",
    }
)


class TargetContractError(ValueError):
    """The target contract is incomplete, ambiguous, or identity-inconsistent."""


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise TargetContractError(f"{field} must be a SHA-256")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TargetContractError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TargetContractError(f"{field} must be a nonnegative integer")
    return value


def _matrix(value: Any, field: str) -> tuple[tuple[float, ...], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        raise TargetContractError(f"{field} must be a 3x3 matrix")
    result = []
    for row in value:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != 3:
            raise TargetContractError(f"{field} must be a 3x3 matrix")
        parsed = tuple(float(cell) for cell in row)
        if not all(math.isfinite(cell) for cell in parsed):
            raise TargetContractError(f"{field} contains a non-finite value")
        result.append(parsed)
    return tuple(result)


def _multiply(
    left: tuple[tuple[float, ...], ...], right: tuple[tuple[float, ...], ...]
) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(sum(left[row][k] * right[k][column] for k in range(3)) for column in range(3))
        for row in range(3)
    )


def _identity_close(value: tuple[tuple[float, ...], ...]) -> bool:
    return all(
        abs(value[row][column] - (1.0 if row == column else 0.0)) <= 1e-8
        for row in range(3)
        for column in range(3)
    )


def target_contract_sha256(contract: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {key: value for key, value in contract.items() if key != "contract_sha256"}
    )


def validate_target_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("schema_version") == "2.0.0":
        _validate_target_contract_v2(contract)
        return
    if set(contract) != CONTRACT_KEYS:
        raise TargetContractError("target contract fields are incomplete or unknown")
    if contract["schema_version"] != "1.0.0":
        raise TargetContractError("target contract schema is unsupported")
    if not str(contract["contract_id"]).strip():
        raise TargetContractError("target contract ID is empty")
    if contract["contract_sha256"] != target_contract_sha256(contract):
        raise TargetContractError("target contract canonical hash mismatch")

    source = contract["source"]
    if not isinstance(source, Mapping) or set(source) != {
        "image_id",
        "sha256",
        "width",
        "height",
    }:
        raise TargetContractError("target source identity is incomplete")
    width = _positive_int(source["width"], "source.width")
    height = _positive_int(source["height"], "source.height")
    _sha256(source["sha256"], "source.sha256")
    if not str(source["image_id"]).strip():
        raise TargetContractError("source.image_id is empty")

    owner = contract["owner"]
    if not isinstance(owner, Mapping) or set(owner) != {
        "person_index",
        "character_instance_id",
        "person_mask_sha256",
    }:
        raise TargetContractError("target owner identity is incomplete")
    if isinstance(owner["person_index"], bool) or not isinstance(owner["person_index"], int):
        raise TargetContractError("owner.person_index must be an integer")
    if owner["person_index"] < 0 or not str(owner["character_instance_id"]).strip():
        raise TargetContractError("target owner is ambiguous")
    _sha256(owner["person_mask_sha256"], "owner.person_mask_sha256")

    target = contract["target"]
    required_target = {
        "label_id",
        "expected_presence",
        "minimum_area_pixels",
        "maximum_area_pixels",
        "allowed_roi_xyxy",
        "inclusion_rule",
        "exclusion_rule",
    }
    if not isinstance(target, Mapping) or set(target) != required_target:
        raise TargetContractError("target definition is incomplete")
    label_id = str(target["label_id"])
    if not label_id or target["inclusion_rule"] != "visible_pixels_only":
        raise TargetContractError("target label or inclusion rule is ambiguous")
    if target["exclusion_rule"] != "exclude_occluded_outside_owner_and_named_labels":
        raise TargetContractError("target exclusion rule is ambiguous")
    presence = target["expected_presence"]
    if presence not in {"visible_nonempty", "visible_empty"}:
        raise TargetContractError("target expected_presence is invalid")
    minimum_area = _nonnegative_int(target["minimum_area_pixels"], "minimum_area_pixels")
    maximum_area = _nonnegative_int(target["maximum_area_pixels"], "maximum_area_pixels")
    if presence == "visible_empty" and (minimum_area != 0 or maximum_area != 0):
        raise TargetContractError("empty target must have zero area bounds")
    if presence == "visible_nonempty" and not (1 <= minimum_area <= maximum_area <= width * height):
        raise TargetContractError("nonempty target area bounds are invalid")
    roi = target["allowed_roi_xyxy"]
    if not isinstance(roi, Sequence) or isinstance(roi, (str, bytes)) or len(roi) != 4:
        raise TargetContractError("target allowed ROI must be xyxy")
    x0, y0, x1, y1 = (int(value) for value in roi)
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise TargetContractError("target allowed ROI escapes source geometry")

    candidate = contract["candidate"]
    if not isinstance(candidate, Mapping) or set(candidate) != {
        "mask_sha256",
        "width",
        "height",
        "binary_values",
    }:
        raise TargetContractError("candidate identity is incomplete")
    _sha256(candidate["mask_sha256"], "candidate.mask_sha256")
    if (candidate["width"], candidate["height"]) != (width, height):
        raise TargetContractError("candidate geometry differs from source geometry")
    if candidate["binary_values"] != [0, 255]:
        raise TargetContractError("candidate is not strict binary")

    excluded = contract["excluded_labels"]
    if not isinstance(excluded, Sequence) or isinstance(excluded, (str, bytes)):
        raise TargetContractError("excluded label set is ambiguous")
    normalized_excluded = [str(value) if isinstance(value, str) else "" for value in excluded]
    if (
        len(set(normalized_excluded)) != len(normalized_excluded)
        or label_id in normalized_excluded
        or any(not value.strip() for value in normalized_excluded)
    ):
        raise TargetContractError("excluded label set is ambiguous")
    protected = contract["protected_regions"]
    if not isinstance(protected, Sequence) or isinstance(protected, (str, bytes)):
        raise TargetContractError("protected regions must be a list")
    region_ids = set()
    for region in protected:
        if not isinstance(region, Mapping) or set(region) != {
            "region_id",
            "label_id",
            "owner_person_index",
            "mask_sha256",
        }:
            raise TargetContractError("protected region identity is incomplete")
        region_id = str(region["region_id"])
        if not region_id or region_id in region_ids:
            raise TargetContractError("protected region IDs are empty or duplicated")
        region_ids.add(region_id)
        if (
            _nonnegative_int(region["owner_person_index"], "protected_region.owner_person_index")
            != owner["person_index"]
        ):
            raise TargetContractError("protected region owner differs from target owner")
        _sha256(region["mask_sha256"], "protected_region.mask_sha256")

    transforms = contract["transforms"]
    if not isinstance(transforms, Mapping) or set(transforms) != {
        "source_to_candidate",
        "candidate_to_source",
    }:
        raise TargetContractError("target transforms are incomplete")
    forward = _matrix(transforms["source_to_candidate"], "source_to_candidate")
    inverse = _matrix(transforms["candidate_to_source"], "candidate_to_source")
    if not _identity_close(_multiply(forward, inverse)) or not _identity_close(
        _multiply(inverse, forward)
    ):
        raise TargetContractError("target transforms do not round-trip")


def _closed_mapping(value: Any, keys: set[str], field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise TargetContractError(f"{field} fields are incomplete or unknown")
    return value


def _unique_strings(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TargetContractError(f"{field} must be a list")
    result = [item if isinstance(item, str) else "" for item in value]
    if (not allow_empty and not result) or any(not item.strip() for item in result):
        raise TargetContractError(f"{field} contains an empty value")
    if len(result) != len(set(result)):
        raise TargetContractError(f"{field} contains duplicates")
    return result


def _validate_target_contract_v2(contract: Mapping[str, Any]) -> None:
    """Validate the complete autonomous-gold target semantics before model execution."""

    if set(contract) != V2_CONTRACT_KEYS:
        raise TargetContractError("target contract fields are incomplete or unknown")
    if contract["contract_sha256"] != target_contract_sha256(contract):
        raise TargetContractError("target contract canonical hash mismatch")
    if not isinstance(contract.get("contract_id"), str) or not contract["contract_id"].strip():
        raise TargetContractError("target contract ID is empty")

    source = _closed_mapping(
        contract["source"],
        {
            "image_id",
            "encoded_sha256",
            "decoded_pixel_sha256",
            "width",
            "height",
            "decoder",
        },
        "target source",
    )
    width = _positive_int(source["width"], "source.width")
    height = _positive_int(source["height"], "source.height")
    _sha256(source["encoded_sha256"], "source.encoded_sha256")
    _sha256(source["decoded_pixel_sha256"], "source.decoded_pixel_sha256")
    if not isinstance(source["image_id"], str) or not source["image_id"].strip():
        raise TargetContractError("source.image_id is empty")
    decoder = _closed_mapping(
        source["decoder"],
        {"name", "version", "exif_orientation", "color_policy", "icc_policy", "alpha_policy"},
        "source decoder",
    )
    if any(not isinstance(decoder[key], str) or not decoder[key].strip() for key in decoder):
        raise TargetContractError("source decoder policy is incomplete")

    owner = _closed_mapping(
        contract["owner"],
        {"person_index", "character_instance_id", "person_mask_sha256"},
        "target owner",
    )
    _nonnegative_int(owner["person_index"], "owner.person_index")
    if (
        not isinstance(owner["character_instance_id"], str)
        or not owner["character_instance_id"].strip()
    ):
        raise TargetContractError("target owner is ambiguous")
    _sha256(owner["person_mask_sha256"], "owner.person_mask_sha256")

    target = _closed_mapping(
        contract["target"],
        {
            "label_id",
            "ontology_version",
            "ontology_sha256",
            "label_scale",
            "laterality",
            "perspective",
            "visibility_policy",
            "expected_state",
            "inclusions",
            "exclusions",
            "allowed_roi_xyxy",
            "overlap_policy",
            "topology_policy",
            "context",
        },
        "target definition",
    )
    if any(
        not isinstance(target[key], str) or not target[key].strip()
        for key in ("label_id", "ontology_version")
    ):
        raise TargetContractError("target label or ontology is ambiguous")
    _sha256(target["ontology_sha256"], "target.ontology_sha256")
    if target["label_scale"] not in {
        "whole_person",
        "coarse_region",
        "atomic_anatomy",
        "material",
        "projected_region",
        "scene_action",
    }:
        raise TargetContractError("target label_scale is invalid")
    if target["laterality"] not in {"none", "left", "right", "midline"}:
        raise TargetContractError("target laterality is invalid")
    if target["perspective"] != "character_perspective":
        raise TargetContractError("target perspective is ambiguous")
    if target["visibility_policy"] not in {"visible_only", "amodal"}:
        raise TargetContractError("target visibility policy is invalid")
    if target["expected_state"] not in {"present", "absent", "not_applicable", "occluded"}:
        raise TargetContractError("target expected state is invalid")
    _unique_strings(target["inclusions"], "target.inclusions")
    _unique_strings(target["exclusions"], "target.exclusions")
    roi = target["allowed_roi_xyxy"]
    if not isinstance(roi, Sequence) or isinstance(roi, (str, bytes)) or len(roi) != 4:
        raise TargetContractError("target allowed ROI must be xyxy")
    x0, y0, x1, y1 = (int(item) for item in roi)
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise TargetContractError("target allowed ROI escapes source geometry")
    overlap = _closed_mapping(
        target["overlap_policy"],
        {"protected_overlap_max_pixels", "cross_person_overlap_max_pixels", "containment_rule"},
        "target overlap policy",
    )
    _nonnegative_int(overlap["protected_overlap_max_pixels"], "protected overlap")
    _nonnegative_int(overlap["cross_person_overlap_max_pixels"], "cross-person overlap")
    if not isinstance(overlap["containment_rule"], str) or not overlap["containment_rule"].strip():
        raise TargetContractError("target containment rule is ambiguous")
    topology = _closed_mapping(
        target["topology_policy"],
        {"minimum_components", "maximum_components", "holes_allowed", "thin_structures_expected"},
        "target topology policy",
    )
    minimum = _nonnegative_int(topology["minimum_components"], "minimum components")
    maximum = _nonnegative_int(topology["maximum_components"], "maximum components")
    if minimum > maximum or any(
        not isinstance(topology[key], bool) for key in ("holes_allowed", "thin_structures_expected")
    ):
        raise TargetContractError("target topology policy is invalid")
    context = _closed_mapping(
        target["context"],
        {
            "truncated",
            "contact",
            "self_occluded",
            "cross_person_occluded",
            "crop_edge",
            "out_of_frame",
        },
        "target context",
    )
    if any(not isinstance(value, bool) for value in context.values()):
        raise TargetContractError("target context values must be boolean")

    candidate = _closed_mapping(
        contract["candidate"],
        {
            "encoded_sha256",
            "decoded_pixel_sha256",
            "width",
            "height",
            "binary_values",
            "coordinate_space",
        },
        "candidate identity",
    )
    _sha256(candidate["encoded_sha256"], "candidate.encoded_sha256")
    _sha256(candidate["decoded_pixel_sha256"], "candidate.decoded_pixel_sha256")
    if (candidate["width"], candidate["height"]) != (width, height) or candidate[
        "binary_values"
    ] != [0, 255]:
        raise TargetContractError("candidate geometry or strict binary values are invalid")
    if (
        not isinstance(candidate["coordinate_space"], str)
        or not candidate["coordinate_space"].strip()
    ):
        raise TargetContractError("candidate coordinate space is ambiguous")

    protected = contract["protected_regions"]
    if not isinstance(protected, Sequence) or isinstance(protected, (str, bytes)):
        raise TargetContractError("protected regions must be a list")
    for region in protected:
        item = _closed_mapping(
            region,
            {"region_id", "label_id", "owner_person_index", "mask_sha256", "overlap_max_pixels"},
            "protected region",
        )
        if not isinstance(item["region_id"], str) or not item["region_id"].strip():
            raise TargetContractError("protected region identity is incomplete")
        _nonnegative_int(item["owner_person_index"], "protected region owner")
        _sha256(item["mask_sha256"], "protected_region.mask_sha256")
        _nonnegative_int(item["overlap_max_pixels"], "protected region overlap")

    transforms = _closed_mapping(
        contract["transforms"],
        {"coordinate_space", "chain", "round_trip_sha256"},
        "target transforms",
    )
    _sha256(transforms["round_trip_sha256"], "transforms.round_trip_sha256")
    if (
        not isinstance(transforms["coordinate_space"], str)
        or not transforms["coordinate_space"].strip()
    ):
        raise TargetContractError("transform coordinate space is ambiguous")
    chain = transforms["chain"]
    if not isinstance(chain, Sequence) or isinstance(chain, (str, bytes)) or not chain:
        raise TargetContractError("transform chain is incomplete")
    for step in chain:
        item = _closed_mapping(
            step,
            {"operation", "from_space", "to_space", "matrix", "inverse_matrix"},
            "transform step",
        )
        if any(
            not isinstance(item[key], str) or not item[key].strip()
            for key in ("operation", "from_space", "to_space")
        ):
            raise TargetContractError("transform step identity is incomplete")
        forward = _matrix(item["matrix"], "transform matrix")
        inverse = _matrix(item["inverse_matrix"], "transform inverse")
        if not _identity_close(_multiply(forward, inverse)) or not _identity_close(
            _multiply(inverse, forward)
        ):
            raise TargetContractError("target transforms do not round-trip")

    package = _closed_mapping(
        contract["package"], {"package_id", "revision", "parent_revision"}, "target package"
    )
    if (
        not isinstance(package["package_id"], str)
        or not package["package_id"].strip()
        or not isinstance(package["revision"], int)
        or package["revision"] < 1
    ):
        raise TargetContractError("target package identity is invalid")
    if package["parent_revision"] is not None and (
        not isinstance(package["parent_revision"], int)
        or package["parent_revision"] < 1
        or package["parent_revision"] >= package["revision"]
    ):
        raise TargetContractError("target package parent revision is invalid")


def authorize_critic_invocation(
    contract: Mapping[str, Any],
    *,
    source_sha256: str,
    candidate_mask_sha256: str,
    source_size: tuple[int, int],
) -> dict[str, str]:
    """Fail before any critic call unless live inputs exactly match the contract."""

    validate_target_contract(contract)
    source_field = "decoded_pixel_sha256" if contract["schema_version"] == "2.0.0" else "sha256"
    candidate_field = (
        "decoded_pixel_sha256" if contract["schema_version"] == "2.0.0" else "mask_sha256"
    )
    if source_sha256 != contract["source"][source_field]:
        raise TargetContractError("critic source hash differs from target contract")
    if candidate_mask_sha256 != contract["candidate"][candidate_field]:
        raise TargetContractError("critic candidate hash differs from target contract")
    if source_size != (contract["source"]["width"], contract["source"]["height"]):
        raise TargetContractError("critic source geometry differs from target contract")
    return {
        "contract_id": str(contract["contract_id"]),
        "contract_sha256": str(contract["contract_sha256"]),
        "invocation_sha256": canonical_sha256(
            {
                "contract_sha256": contract["contract_sha256"],
                "source_sha256": source_sha256,
                "candidate_mask_sha256": candidate_mask_sha256,
                "source_size": list(source_size),
            }
        ),
    }
