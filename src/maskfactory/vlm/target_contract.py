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


def authorize_critic_invocation(
    contract: Mapping[str, Any],
    *,
    source_sha256: str,
    candidate_mask_sha256: str,
    source_size: tuple[int, int],
) -> dict[str, str]:
    """Fail before any critic call unless live inputs exactly match the contract."""

    validate_target_contract(contract)
    if source_sha256 != contract["source"]["sha256"]:
        raise TargetContractError("critic source hash differs from target contract")
    if candidate_mask_sha256 != contract["candidate"]["mask_sha256"]:
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
