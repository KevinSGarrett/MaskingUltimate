"""Fail-closed semantic admission for governed autonomous mask campaigns."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
from PIL import Image


SCHEMA_VERSION = "maskfactory_mask_campaign_input.v1"
ZERO_SHA256 = "0" * 64
REQUIRED_RESOURCE_ROLES = (
    "source_image",
    "label_region",
    "owner_region",
    "side_region",
    "neighbor_region",
    "protected_region",
)
ALLOWED_SIDES = frozenset({"left", "right", "center", "bilateral"})
REQUIRED_PROVIDER_CAPABILITY = "mask_candidate"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_RESOURCE_FIELDS = {
    "role",
    "path",
    "bytes",
    "sha256",
    "mode",
    "width",
    "height",
    "semantic_absence",
}
_SEMANTIC_FIELDS = {
    "ontology_sha256",
    "target_label",
    "target_label_id",
    "owner_id",
    "side",
    "neighbor_labels",
    "protected_labels",
}
_PROVIDER_FIELDS = {
    "provider_id",
    "family",
    "contract_sha256",
    "checkpoint_sha256",
    "runtime_sha256",
    "capabilities",
}
_CONTRACT_FIELDS = {
    "schema_version",
    "record_id",
    "resources",
    "semantic_binding",
    "providers",
}


class MaskCampaignInputError(RuntimeError):
    """Semantic resources are incomplete, ambiguous, or contradictory."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MaskCampaignInputError(
            "CONTRACT_NOT_CANONICAL_JSON",
            "mask campaign contract is not canonical JSON",
        ) from exc


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    sealed = deepcopy(dict(value))
    sealed[field] = ZERO_SHA256
    sealed[field] = _canonical_sha256(sealed)
    return sealed


def _verify_self_hash(value: Mapping[str, Any], field: str) -> None:
    declared = value.get(field)
    if not isinstance(declared, str) or not _SHA256_RE.fullmatch(declared):
        raise MaskCampaignInputError(
            "SELF_HASH_INVALID",
            f"{field} is invalid",
        )
    zeroed = deepcopy(dict(value))
    zeroed[field] = ZERO_SHA256
    if _canonical_sha256(zeroed) != declared:
        raise MaskCampaignInputError(
            "SELF_HASH_MISMATCH",
            f"{field} canonical self-hash mismatch",
        )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise MaskCampaignInputError(
            "SEMANTIC_ID_INVALID",
            f"{field} is invalid",
        )
    return value


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise MaskCampaignInputError(
            "HASH_BINDING_INVALID",
            f"{field} is invalid",
        )
    return value


def _relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise MaskCampaignInputError("RESOURCE_PATH_INVALID", "resource path is empty")
    if any(character in value for character in "\r\n\x00"):
        raise MaskCampaignInputError(
            "RESOURCE_PATH_INVALID",
            "resource path contains a prohibited character",
        )
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or ":" in path.parts[0]
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise MaskCampaignInputError(
            "RESOURCE_PATH_ESCAPE",
            "resource path escapes the asset root",
        )
    return path.as_posix()


def _string_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise MaskCampaignInputError(
            "SEMANTIC_LIST_INVALID",
            f"{field} must be a list",
        )
    normalized = [_identifier(item, field=field) for item in value]
    if normalized != sorted(set(normalized)):
        raise MaskCampaignInputError(
            "SEMANTIC_LIST_AMBIGUOUS",
            f"{field} must be sorted and unique",
        )
    return normalized


def _mask_pixels(image: Image.Image, *, role: str) -> set[int]:
    if image.mode != "L":
        raise MaskCampaignInputError(
            "RESOURCE_MODE_MISMATCH",
            f"{role} must be an L-mode mask",
        )
    histogram = image.histogram()
    values = {index for index, count in enumerate(histogram) if count}
    if not values.issubset({0, 255}):
        raise MaskCampaignInputError(
            "MASK_NOT_BINARY",
            f"{role} must contain only 0 and 255",
        )
    return values


def _load_resources(
    asset_root: Path,
    rows: object,
) -> tuple[list[dict[str, Any]], dict[str, np.ndarray], tuple[int, int]]:
    if not isinstance(rows, list):
        raise MaskCampaignInputError(
            "RESOURCE_SET_INVALID",
            "resources must be a list",
        )
    if len(rows) != len(REQUIRED_RESOURCE_ROLES):
        raise MaskCampaignInputError(
            "RESOURCE_SET_INCOMPLETE",
            "exactly one resource per required semantic role is required",
        )
    normalized_rows: list[dict[str, Any]] = []
    masks: dict[str, np.ndarray] = {}
    roles: set[str] = set()
    resource_paths: set[str] = set()
    source_size: tuple[int, int] | None = None
    try:
        root = asset_root.resolve(strict=True)
    except OSError as exc:
        raise MaskCampaignInputError(
            "ASSET_ROOT_UNREADABLE",
            "asset root is missing or unreadable",
        ) from exc
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != _RESOURCE_FIELDS:
            raise MaskCampaignInputError(
                "RESOURCE_ROW_INVALID",
                "resource row field set mismatch",
            )
        role = row["role"]
        if role not in REQUIRED_RESOURCE_ROLES or role in roles:
            raise MaskCampaignInputError(
                "RESOURCE_ROLE_AMBIGUOUS",
                "resource roles must be required and unique",
            )
        roles.add(role)
        relative = _relative_path(row["path"])
        if relative in resource_paths:
            raise MaskCampaignInputError(
                "RESOURCE_PATH_AMBIGUOUS",
                "semantic resource paths must be unique",
            )
        resource_paths.add(relative)
        path = root.joinpath(*PurePosixPath(relative).parts)
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise MaskCampaignInputError(
                "RESOURCE_PATH_ESCAPE",
                f"{role} path is missing or outside the asset root",
            ) from exc
        if path.is_symlink() or not path.is_file():
            raise MaskCampaignInputError(
                "RESOURCE_NOT_REGULAR_FILE",
                f"{role} must be a regular non-symlink file",
            )
        expected_bytes = row["bytes"]
        width = row["width"]
        height = row["height"]
        if (
            not isinstance(width, int)
            or isinstance(width, bool)
            or width <= 0
            or not isinstance(height, int)
            or isinstance(height, bool)
            or height <= 0
            or not isinstance(row["mode"], str)
        ):
            raise MaskCampaignInputError(
                "RESOURCE_GEOMETRY_INVALID",
                f"{role} declared media geometry is invalid",
            )
        try:
            actual_bytes = path.stat().st_size
            actual_sha256 = _file_sha256(path)
        except OSError as exc:
            raise MaskCampaignInputError(
                "RESOURCE_UNREADABLE",
                f"{role} resource is unreadable",
            ) from exc
        if (
            not isinstance(expected_bytes, int)
            or isinstance(expected_bytes, bool)
            or expected_bytes <= 0
            or actual_bytes != expected_bytes
        ):
            raise MaskCampaignInputError(
                "RESOURCE_BYTES_MISMATCH",
                f"{role} byte count mismatch",
            )
        expected_sha256 = _sha256(row["sha256"], field=f"{role} SHA-256")
        if actual_sha256 != expected_sha256:
            raise MaskCampaignInputError(
                "RESOURCE_HASH_MISMATCH",
                f"{role} SHA-256 mismatch",
            )
        if not isinstance(row["semantic_absence"], bool):
            raise MaskCampaignInputError(
                "SEMANTIC_ABSENCE_INVALID",
                f"{role} semantic_absence must be boolean",
            )
        try:
            with Image.open(path) as image:
                image.load()
                size = image.size
                mode = image.mode
                if (
                    row["width"] != size[0]
                    or row["height"] != size[1]
                    or row["mode"] != mode
                ):
                    raise MaskCampaignInputError(
                        "RESOURCE_GEOMETRY_MISMATCH",
                        f"{role} declared media geometry differs from bytes",
                    )
                if role == "source_image":
                    if mode not in {"RGB", "RGBA"} or row["semantic_absence"]:
                        raise MaskCampaignInputError(
                            "SOURCE_IMAGE_INVALID",
                            "source image must be present RGB/RGBA media",
                        )
                    source_size = size
                else:
                    values = _mask_pixels(image, role=role)
                    present = 255 in values
                    if row["semantic_absence"] == present:
                        raise MaskCampaignInputError(
                            "SEMANTIC_ABSENCE_CONTRADICTORY",
                            f"{role} semantic absence contradicts mask pixels",
                        )
                    masks[role] = (
                        np.asarray(image, dtype=np.uint8) == 255
                    ).copy()
        except MaskCampaignInputError:
            raise
        except (OSError, ValueError) as exc:
            raise MaskCampaignInputError(
                "RESOURCE_MEDIA_UNREADABLE",
                f"{role} media is unreadable",
            ) from exc
        normalized_rows.append(
            {
                "role": role,
                "path": relative,
                "bytes": expected_bytes,
                "sha256": expected_sha256,
                "mode": row["mode"],
                "width": row["width"],
                "height": row["height"],
                "semantic_absence": row["semantic_absence"],
            }
        )
    if roles != set(REQUIRED_RESOURCE_ROLES) or source_size is None:
        raise MaskCampaignInputError(
            "RESOURCE_SET_INCOMPLETE",
            "required semantic resource roles are incomplete",
        )
    if any(
        (row["width"], row["height"]) != source_size
        for row in normalized_rows
    ):
        raise MaskCampaignInputError(
            "RESOURCE_GEOMETRY_MISMATCH",
            "all semantic resources must match source geometry",
        )
    return (
        sorted(normalized_rows, key=lambda row: row["role"]),
        masks,
        source_size,
    )


def _validate_semantics(
    value: object,
    *,
    masks: Mapping[str, np.ndarray],
    resources: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _SEMANTIC_FIELDS:
        raise MaskCampaignInputError(
            "SEMANTIC_BINDING_INVALID",
            "semantic binding field set mismatch",
        )
    side = value["side"]
    if side not in ALLOWED_SIDES:
        raise MaskCampaignInputError(
            "SIDE_AMBIGUOUS",
            "side must be explicit and governed",
        )
    neighbor_labels = _string_list(
        value["neighbor_labels"],
        field="neighbor_labels",
    )
    protected_labels = _string_list(
        value["protected_labels"],
        field="protected_labels",
    )
    neighbor_absent = resources["neighbor_region"]["semantic_absence"]
    protected_absent = resources["protected_region"]["semantic_absence"]
    if neighbor_absent != (not neighbor_labels):
        raise MaskCampaignInputError(
            "NEIGHBOR_BINDING_CONTRADICTORY",
            "neighbor labels and neighbor mask absence disagree",
        )
    if protected_absent != (not protected_labels):
        raise MaskCampaignInputError(
            "PROTECTED_BINDING_CONTRADICTORY",
            "protected labels and protected mask absence disagree",
        )
    if not set(neighbor_labels).issubset(protected_labels):
        raise MaskCampaignInputError(
            "PROTECTED_BINDING_MISMATCH",
            "protected labels do not include every bound neighbor label",
        )
    label = masks["label_region"]
    owner = masks["owner_region"]
    side_region = masks["side_region"]
    neighbor = masks["neighbor_region"]
    protected = masks["protected_region"]
    if np.any(label & ~owner):
        raise MaskCampaignInputError(
            "OWNER_BINDING_MISMATCH",
            "target label region is not fully owned by the bound owner",
        )
    if np.any(label & ~side_region):
        raise MaskCampaignInputError(
            "SIDE_BINDING_MISMATCH",
            "target label region is not fully inside the bound side",
        )
    if np.any(label & neighbor):
        raise MaskCampaignInputError(
            "NEIGHBOR_BINDING_AMBIGUOUS",
            "target and neighbor regions overlap",
        )
    if np.any(neighbor & ~protected):
        raise MaskCampaignInputError(
            "PROTECTED_BINDING_MISMATCH",
            "protected region does not contain all bound neighbors",
        )
    if np.any(label & protected):
        raise MaskCampaignInputError(
            "PROTECTED_BINDING_AMBIGUOUS",
            "target and protected regions overlap",
        )
    target_label_id = value["target_label_id"]
    if (
        not isinstance(target_label_id, int)
        or isinstance(target_label_id, bool)
        or target_label_id <= 0
    ):
        raise MaskCampaignInputError(
            "TARGET_LABEL_INVALID",
            "target_label_id must be a positive integer",
        )
    return {
        "ontology_sha256": _sha256(
            value["ontology_sha256"],
            field="ontology_sha256",
        ),
        "target_label": _identifier(value["target_label"], field="target_label"),
        "target_label_id": target_label_id,
        "owner_id": _identifier(value["owner_id"], field="owner_id"),
        "side": side,
        "neighbor_labels": neighbor_labels,
        "protected_labels": protected_labels,
    }


def _validate_providers(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) < 2:
        raise MaskCampaignInputError(
            "PROVIDER_SET_INCOMPLETE",
            "at least two provider candidates are required",
        )
    normalized: list[dict[str, Any]] = []
    provider_ids: set[str] = set()
    families: set[str] = set()
    checkpoints: set[str] = set()
    for row in value:
        if not isinstance(row, Mapping) or set(row) != _PROVIDER_FIELDS:
            raise MaskCampaignInputError(
                "PROVIDER_ROW_INVALID",
                "provider row field set mismatch",
            )
        provider_id = _identifier(row["provider_id"], field="provider_id")
        family = _identifier(row["family"], field="provider family")
        if provider_id in provider_ids or family in families:
            raise MaskCampaignInputError(
                "PROVIDER_SET_AMBIGUOUS",
                "provider IDs and families must be unique",
            )
        provider_ids.add(provider_id)
        families.add(family)
        capabilities = _string_list(row["capabilities"], field="capabilities")
        if REQUIRED_PROVIDER_CAPABILITY not in capabilities:
            raise MaskCampaignInputError(
                "PROVIDER_CAPABILITY_MISSING",
                "provider cannot produce a mask candidate",
            )
        checkpoint_sha256 = _sha256(
            row["checkpoint_sha256"],
            field="provider checkpoint SHA-256",
        )
        if checkpoint_sha256 in checkpoints:
            raise MaskCampaignInputError(
                "PROVIDER_SET_AMBIGUOUS",
                "provider checkpoints must be distinct",
            )
        checkpoints.add(checkpoint_sha256)
        normalized.append(
            {
                "provider_id": provider_id,
                "family": family,
                "contract_sha256": _sha256(
                    row["contract_sha256"],
                    field="provider contract SHA-256",
                ),
                "checkpoint_sha256": checkpoint_sha256,
                "runtime_sha256": _sha256(
                    row["runtime_sha256"],
                    field="provider runtime SHA-256",
                ),
                "capabilities": capabilities,
            }
        )
    return sorted(normalized, key=lambda row: row["provider_id"])


def _build_admitted_input(
    *,
    asset_root: Path,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    if set(contract) != _CONTRACT_FIELDS:
        raise MaskCampaignInputError(
            "CONTRACT_FIELD_SET_MISMATCH",
            "mask campaign contract field set mismatch",
        )
    if contract.get("schema_version") != SCHEMA_VERSION:
        raise MaskCampaignInputError(
            "CONTRACT_SCHEMA_MISMATCH",
            "mask campaign contract schema mismatch",
        )
    resources, masks, source_size = _load_resources(
        asset_root,
        contract["resources"],
    )
    by_role = {row["role"]: row for row in resources}
    semantic_binding = _validate_semantics(
        contract["semantic_binding"],
        masks=masks,
        resources=by_role,
    )
    providers = _validate_providers(contract["providers"])
    return _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "record_id": _identifier(contract["record_id"], field="record_id"),
            "resources": resources,
            "source_size": list(source_size),
            "semantic_binding": semantic_binding,
            "providers": providers,
            "candidate_generation_allowed": True,
            "seeded_defect_generation_allowed": True,
            "text_only_acceptance_allowed": False,
            "input_sha256": ZERO_SHA256,
        },
        "input_sha256",
    )


def prepare_mask_campaign_input(
    *,
    asset_root: Path,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Admit exact inputs or return a typed abstention before any inference."""

    try:
        if not isinstance(contract, Mapping):
            raise MaskCampaignInputError(
                "CONTRACT_INVALID",
                "mask campaign contract must be an object",
            )
        contract_sha256 = _canonical_sha256(contract)
        admitted = _build_admitted_input(asset_root=asset_root, contract=contract)
    except MaskCampaignInputError as exc:
        try:
            contract_sha256 = _canonical_sha256(contract)
        except MaskCampaignInputError:
            contract_sha256 = ZERO_SHA256
        return _seal(
            {
                "schema_version": SCHEMA_VERSION,
                "status": "ABSTAIN",
                "contract_sha256": contract_sha256,
                "reason_code": exc.code,
                "reason": exc.detail,
                "candidate_generation_allowed": False,
                "seeded_defect_generation_allowed": False,
                "text_only_acceptance_allowed": False,
                "preparation_sha256": ZERO_SHA256,
            },
            "preparation_sha256",
        )
    return _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "status": "ADMITTED",
            "contract_sha256": contract_sha256,
            "reason_code": None,
            "reason": None,
            "candidate_generation_allowed": True,
            "seeded_defect_generation_allowed": True,
            "text_only_acceptance_allowed": False,
            "campaign_input": admitted,
            "preparation_sha256": ZERO_SHA256,
        },
        "preparation_sha256",
    )


def validate_mask_campaign_preparation(
    preparation: Mapping[str, Any],
    *,
    asset_root: Path,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute exact bytes and reject rehashed semantic or authority drift."""

    if not isinstance(preparation, Mapping):
        raise MaskCampaignInputError(
            "PREPARATION_INVALID",
            "mask campaign preparation must be an object",
        )
    _verify_self_hash(preparation, "preparation_sha256")
    campaign_input = preparation.get("campaign_input")
    if isinstance(campaign_input, Mapping):
        _verify_self_hash(campaign_input, "input_sha256")
    expected = prepare_mask_campaign_input(asset_root=asset_root, contract=contract)
    if dict(preparation) != expected:
        raise MaskCampaignInputError(
            "PREPARATION_BINDING_MISMATCH",
            "mask campaign preparation differs from exact resource replay",
        )
    return expected


__all__ = [
    "ALLOWED_SIDES",
    "MaskCampaignInputError",
    "REQUIRED_RESOURCE_ROLES",
    "SCHEMA_VERSION",
    "prepare_mask_campaign_input",
    "validate_mask_campaign_preparation",
]
