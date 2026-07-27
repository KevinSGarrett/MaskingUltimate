"""Frozen contracts for continuous self-hosted autonomy campaigns."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

FREEZE_SCHEMA_VERSION = "maskfactory_self_hosted_autonomy_contract_freeze.v1"
FREEZE_REGISTRY_PATH = Path("configs/self_hosted_autonomy_contract_freeze_v1.json")
TELEMETRY_SCHEMA_PATH = Path(
    "configs/self_hosted_autonomy_campaign_telemetry_v1.schema.json"
)
ACCEPTANCE_SCHEMA_PATH = Path("configs/self_hosted_autonomy_acceptance_v1.schema.json")
AUTHORITY_PATHS = (
    Path("Plan/27_SELF_HOSTED_AUTONOMOUS_LLM_CONTINUOUS_OPERATIONS_SPEC.md"),
    Path("Plan/28_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION_AND_COMFYUI_ADOPTION.md"),
    Path(
        "Plan/Instructions/"
        "16_SELF_HOSTED_AUTONOMOUS_LLM_CONTINUOUS_OPERATIONS.md"
    ),
    Path(
        "Plan/Instructions/"
        "18_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION_AND_COMFYUI_ADOPTION.md"
    ),
    Path("Plan/SELF_HOSTED_AUTONOMOUS_LLM_PURSUING_GOAL_MESSAGE.md"),
    Path("Plan/Items/23_ITEMS_P6_SELF_HOSTED_AUTONOMOUS_LLM_OPERATIONS.md"),
    Path("Plan/Items/24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md"),
)
ITEM_PATH = Path("Plan/Items/23_ITEMS_P6_SELF_HOSTED_AUTONOMOUS_LLM_OPERATIONS.md")
ITEM_PATHS = (
    ITEM_PATH,
    Path("Plan/Items/24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md"),
)
INCOMPLETE_CLAIM = "SELF_HOSTED_AUTONOMOUS_LLM_THROUGHPUT_INCOMPLETE"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ITEM_ID = re.compile(
    r"^- \[[ xX]\] (MF-P6-(?:1[3-9]|2[0-2])\.\d{2})\b",
    re.MULTILINE,
)
_REGISTRY_FIELDS = {
    "schema_version",
    "registry_id",
    "frozen_at",
    "incomplete_claim",
    "authority_files",
    "schema_files",
    "item_ids",
    "registry_sha256",
}
_ROW_FIELDS = {"path", "sha256"}


class ContinuousContractError(ValueError):
    """Raised when a frozen continuous-operations contract fails closed."""


def canonical_sha256(document: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContinuousContractError(f"cannot read strict JSON {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ContinuousContractError(f"JSON root must be an object: {path}")
    return document


def _validate_rows(
    repo_root: Path,
    rows: Any,
    *,
    label: str,
) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    paths: list[str] = []
    if not isinstance(rows, list) or not rows:
        return [f"{label} must be a non-empty array"], paths
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != _ROW_FIELDS:
            problems.append(f"{label}[{index}] must contain exactly path and sha256")
            continue
        relative = row["path"]
        expected = row["sha256"]
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
        ):
            problems.append(f"{label}[{index}] path is invalid")
            continue
        if Path(relative).as_posix() != relative or ".." in Path(relative).parts:
            problems.append(f"{label}[{index}] path escapes or is not canonical")
            continue
        if not isinstance(expected, str) or not _SHA256.fullmatch(expected):
            problems.append(f"{label}[{index}] sha256 is invalid")
            continue
        paths.append(relative)
        target = repo_root / relative
        if not target.is_file():
            problems.append(f"{label}[{index}] missing bound file: {relative}")
            continue
        observed = file_sha256(target)
        if observed != expected:
            problems.append(
                f"{label}[{index}] stale hash for {relative}: {observed} != {expected}"
            )
    if len(paths) != len(set(paths)):
        problems.append(f"{label} contains duplicate paths")
    return problems, paths


def validate_freeze_registry(repo_root: Path) -> list[str]:
    """Return every fail-closed authority, schema, identity, or hash defect."""

    repo_root = Path(repo_root).resolve()
    registry_path = repo_root / FREEZE_REGISTRY_PATH
    if not registry_path.is_file():
        return [f"missing freeze registry: {FREEZE_REGISTRY_PATH.as_posix()}"]
    try:
        registry = read_json(registry_path)
    except ContinuousContractError as exc:
        return [str(exc)]
    problems: list[str] = []
    if set(registry) != _REGISTRY_FIELDS:
        unknown = sorted(set(registry) - _REGISTRY_FIELDS)
        missing = sorted(_REGISTRY_FIELDS - set(registry))
        problems.append(
            f"freeze registry fields differ: unknown={unknown} missing={missing}"
        )
    if registry.get("schema_version") != FREEZE_SCHEMA_VERSION:
        problems.append("freeze registry schema_version drifted")
    if registry.get("registry_id") != "maskfactory_self_hosted_autonomy_contract_v1":
        problems.append("freeze registry_id drifted")
    if registry.get("incomplete_claim") != INCOMPLETE_CLAIM:
        problems.append("freeze incomplete claim drifted")
    declared_self = registry.get("registry_sha256")
    if not isinstance(declared_self, str) or not _SHA256.fullmatch(declared_self):
        problems.append("freeze registry_sha256 is invalid")
    else:
        unsigned = dict(registry)
        unsigned.pop("registry_sha256", None)
        if canonical_sha256(unsigned) != declared_self:
            problems.append("freeze registry self hash drifted")

    authority_problems, authority_paths = _validate_rows(
        repo_root, registry.get("authority_files"), label="authority_files"
    )
    schema_problems, schema_paths = _validate_rows(
        repo_root, registry.get("schema_files"), label="schema_files"
    )
    problems.extend(authority_problems)
    problems.extend(schema_problems)

    expected_authority_paths = {path.as_posix() for path in AUTHORITY_PATHS}
    if set(authority_paths) != expected_authority_paths:
        problems.append(
            "freeze authority_files do not match the closed v1 authority set"
        )
    expected_schema_paths = {
        TELEMETRY_SCHEMA_PATH.as_posix(),
        ACCEPTANCE_SCHEMA_PATH.as_posix(),
    }
    if set(schema_paths) != expected_schema_paths:
        problems.append("freeze schema_files do not match the closed v1 schema set")

    item_ids = registry.get("item_ids")
    if not isinstance(item_ids, list) or not all(
        isinstance(item_id, str) for item_id in item_ids
    ):
        problems.append("freeze item_ids must be an array of strings")
        item_ids = []
    if len(item_ids) != len(set(item_ids)):
        problems.append("freeze item_ids contains duplicates")
    observed_item_ids: list[str] = []
    for item_path in ITEM_PATHS:
        item_file = repo_root / item_path
        if item_file.is_file():
            observed_item_ids.extend(
                _ITEM_ID.findall(item_file.read_text(encoding="utf-8"))
            )
    if len(observed_item_ids) != len(set(observed_item_ids)):
        problems.append("P6 item authority contains duplicate item IDs")
    if item_ids != observed_item_ids:
        problems.append("freeze item_ids differ from ordered P6 item authority")

    required_cross_references = {
        FREEZE_REGISTRY_PATH.as_posix(),
        TELEMETRY_SCHEMA_PATH.as_posix(),
        ACCEPTANCE_SCHEMA_PATH.as_posix(),
    }
    for relative in authority_paths:
        text = (repo_root / relative).read_text(encoding="utf-8")
        missing = sorted(
            reference
            for reference in required_cross_references
            if reference not in text
        )
        if missing:
            problems.append(
                f"authority file {relative} misses cross-references: {missing}"
            )

    try:
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import SchemaError
    except ImportError:
        problems.append("jsonschema is required for closed schema validation")
    else:
        for relative in schema_paths:
            try:
                schema = read_json(repo_root / relative)
                Draft202012Validator.check_schema(schema)
                if schema.get("additionalProperties") is not False:
                    problems.append(f"schema root is not closed: {relative}")
            except (ContinuousContractError, SchemaError) as exc:
                problems.append(f"invalid closed schema {relative}: {exc}")
    return problems


def validate_campaign_document(
    repo_root: Path,
    document: Mapping[str, Any],
    *,
    kind: str,
) -> None:
    """Validate one campaign telemetry or acceptance document."""

    schema_path = {
        "telemetry": TELEMETRY_SCHEMA_PATH,
        "acceptance": ACCEPTANCE_SCHEMA_PATH,
    }.get(kind)
    if schema_path is None:
        raise ContinuousContractError(f"unsupported campaign document kind: {kind}")
    problems = validate_freeze_registry(repo_root)
    if problems:
        raise ContinuousContractError("; ".join(problems))
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise ContinuousContractError("jsonschema is required") from exc
    schema = read_json(Path(repo_root) / schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        pointer = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ContinuousContractError(
            f"{kind} schema violation at {pointer or '/'}: {error.message}"
        )


__all__ = [
    "ACCEPTANCE_SCHEMA_PATH",
    "AUTHORITY_PATHS",
    "ContinuousContractError",
    "FREEZE_REGISTRY_PATH",
    "FREEZE_SCHEMA_VERSION",
    "INCOMPLETE_CLAIM",
    "ITEM_PATH",
    "ITEM_PATHS",
    "TELEMETRY_SCHEMA_PATH",
    "canonical_sha256",
    "file_sha256",
    "read_json",
    "validate_campaign_document",
    "validate_freeze_registry",
]
