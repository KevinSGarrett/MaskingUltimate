"""Executable MaskFactory<->Main contract crosswalk and compatibility checks."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from maskfactory.validation import canonical_document_sha256, load_canonical_json

POLICY_PATH = Path(__file__).parents[3] / "configs" / "bridge_crosswalk_policy.yaml"
CROSSWALK_PATH = (
    Path(__file__).parents[3] / "qa/governance/bridge/maskfactory_main_crosswalk_v1.json"
)
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "bridge_crosswalk.schema.json"
POLICY_ID = "maskfactory-main-crosswalk-compatibility-v1"
RECORD_TYPE = "maskfactory_main_contract_crosswalk"


class CrosswalkError(ValueError):
    """Raised when crosswalk inputs or policy are invalid."""


def _decode(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise CrosswalkError(f"invalid JSON pointer: {pointer!r}")
    return [_decode(token) for token in pointer[1:].split("/")]


def _has_pointer(document: Any, pointer: str) -> bool:
    current = document
    for token in _tokens(pointer):
        if isinstance(current, Mapping):
            if token not in current:
                return False
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit():
                return False
            index = int(token)
            if index < 0 or index >= len(current):
                return False
            current = current[index]
        else:
            return False
    return True


def _resolve(document: Any, pointer: str) -> Any:
    current = document
    for token in _tokens(pointer):
        if isinstance(current, Mapping):
            if token not in current:
                raise CrosswalkError(f"missing source field {pointer}")
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit():
                raise CrosswalkError(f"invalid array pointer {pointer}")
            index = int(token)
            if index < 0 or index >= len(current):
                raise CrosswalkError(f"missing source field {pointer}")
            current = current[index]
        else:
            raise CrosswalkError(f"missing source field {pointer}")
    return current


def _set_pointer(document: dict[str, Any], pointer: str, value: Any) -> None:
    tokens = _tokens(pointer)
    if not tokens:
        raise CrosswalkError("target pointer cannot be root")
    cursor: Any = document
    for index, token in enumerate(tokens[:-1]):
        next_token = tokens[index + 1]
        if isinstance(cursor, dict):
            if token not in cursor:
                cursor[token] = [] if next_token.isdigit() else {}
            cursor = cursor[token]
            continue
        if isinstance(cursor, list):
            if not token.isdigit():
                raise CrosswalkError(f"invalid target array pointer {pointer}")
            slot = int(token)
            while len(cursor) <= slot:
                cursor.append({} if not next_token.isdigit() else [])
            if cursor[slot] is None:
                cursor[slot] = {} if not next_token.isdigit() else []
            cursor = cursor[slot]
            continue
        raise CrosswalkError(f"cannot write target pointer {pointer}")
    leaf = tokens[-1]
    if isinstance(cursor, dict):
        cursor[leaf] = value
        return
    if isinstance(cursor, list):
        if not leaf.isdigit():
            raise CrosswalkError(f"invalid terminal array pointer {pointer}")
        slot = int(leaf)
        while len(cursor) <= slot:
            cursor.append(None)
        cursor[slot] = value
        return
    raise CrosswalkError(f"cannot write target pointer {pointer}")


def _flatten_leaf_pointers(value: Any, prefix: str = "") -> set[str]:
    if isinstance(value, Mapping):
        rows: set[str] = set()
        for key, item in value.items():
            pointer = f"{prefix}/{str(key).replace('~', '~0').replace('/', '~1')}"
            rows |= _flatten_leaf_pointers(item, pointer)
        return rows or {prefix}
    if isinstance(value, list):
        rows: set[str] = set()
        for index, item in enumerate(value):
            rows |= _flatten_leaf_pointers(item, f"{prefix}/{index}")
        return rows or {prefix}
    return {prefix or ""}


def _compatible_versions(
    declared_major: int,
    declared_minor: int,
    producer_major: int,
    producer_minor: int,
) -> tuple[bool, str]:
    if producer_major != declared_major:
        return False, "incompatible_major_version"
    if producer_minor < declared_minor:
        return False, "producer_minor_older_than_crosswalk"
    if producer_minor > declared_minor:
        return True, "minor_addition_candidate"
    return True, "exact_version"


def _convert(row: Mapping[str, Any], value: Any) -> Any:
    conversion = row["conversion"]
    if conversion == "identity":
        return value
    if conversion == "enum_map":
        enum_map = row.get("enum_map")
        if not isinstance(enum_map, Mapping) or value not in enum_map:
            raise CrosswalkError(f"enum mapping missing for {row['source_path']}")
        return enum_map[value]
    if conversion == "literal":
        return row["default_value"]
    raise CrosswalkError(f"unknown conversion {conversion!r}")


def _load_policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CrosswalkError("crosswalk policy unavailable") from exc
    if not isinstance(policy, Mapping):
        raise CrosswalkError("crosswalk policy malformed")
    required = {
        "schema_version",
        "policy_id",
        "policy_version",
        "canonicalization",
        "strict_fail_closed",
        "allow_declared_minor_additions_only",
        "producer_observation_mode",
        "policy_sha256",
    }
    if set(policy) != required or policy.get("policy_id") != POLICY_ID:
        raise CrosswalkError("crosswalk policy shape mismatch")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise CrosswalkError("crosswalk policy hash mismatch")
    return dict(policy)


def load_crosswalk_definition() -> dict[str, Any]:
    """Load and validate the versioned crosswalk definition."""
    policy = _load_policy()
    schema = load_canonical_json(SCHEMA_PATH.read_bytes())
    document = load_canonical_json(CROSSWALK_PATH.read_bytes())
    problems = list(Draft202012Validator(schema).iter_errors(document))
    if problems:
        raise CrosswalkError(f"crosswalk schema invalid: {problems[0].message}")
    if document.get("record_type") != RECORD_TYPE:
        raise CrosswalkError("unexpected crosswalk record type")
    expected = canonical_document_sha256(document, excluded_top_level_fields=("crosswalk_sha256",))
    if document.get("crosswalk_sha256") != expected:
        raise CrosswalkError("crosswalk hash mismatch")
    if (
        document.get("policy_id") != policy["policy_id"]
        or document.get("policy_sha256") != policy["policy_sha256"]
    ):
        raise CrosswalkError("crosswalk policy binding mismatch")
    return dict(document)


def evaluate_maskfactory_main_crosswalk(
    producer_payload: Mapping[str, Any],
    *,
    producer_major: int,
    producer_minor: int,
    target_major: int,
    target_minor: int,
) -> dict[str, Any]:
    """Apply the executable mapping and return a compatibility decision."""
    crosswalk = load_crosswalk_definition()
    matrix = crosswalk["compatibility_matrix"]
    declared = crosswalk["versions"]
    status, reason = _compatible_versions(
        int(declared["producer_major"]),
        int(declared["producer_minor"]),
        producer_major,
        producer_minor,
    )
    reasons: list[str] = [] if status else [reason]
    if target_major != int(declared["target_major"]):
        reasons.append("incompatible_target_major_version")
    if target_minor < int(declared["target_minor"]):
        reasons.append("target_minor_older_than_crosswalk")

    mapped: dict[str, Any] = {}
    producer_observations: dict[str, Any] = {}
    addition_rows = {
        row["source_path"]: row
        for row in matrix["compatible_minor_additions"]
        if row.get("producer_minor") == producer_minor
    }
    row_by_source = {row["source_path"]: row for row in matrix["rows"]}
    drop_rows = [
        row
        for row in matrix["rows"]
        if row["rule"] == "drop" and row.get("producer_observation_mode") == "preserve_only"
    ]
    removed_paths = {str(path) for path in matrix.get("removed_source_paths") or ()}
    order_sequences = {
        str(row["source_path"]): row
        for row in matrix.get("order_sensitive_sequences") or ()
        if isinstance(row, Mapping) and isinstance(row.get("source_path"), str)
    }

    for required in matrix["required_source_paths"]:
        if not _has_pointer(producer_payload, required):
            reasons.append(f"missing_required_source:{required}")
    for removed in sorted(removed_paths):
        if _has_pointer(producer_payload, removed):
            reasons.append(f"removed_source_field:{removed}")
    for pointer, sequence in sorted(order_sequences.items()):
        if not _has_pointer(producer_payload, pointer):
            continue
        observed = _resolve(producer_payload, pointer)
        canonical = sequence.get("canonical_order")
        if not isinstance(observed, list) or not isinstance(canonical, list):
            reasons.append(f"order_sensitive_type:{pointer}")
            continue
        if observed != canonical:
            reasons.append(f"order_sensitive_reorder:{pointer}")
            continue
        _set_pointer(mapped, str(sequence["target_path"]), list(observed))
    present = _flatten_leaf_pointers(producer_payload)
    for pointer in sorted(path for path in present if path):
        if any(
            pointer == removed or pointer.startswith(removed + "/") for removed in removed_paths
        ):
            continue
        if any(pointer == root or pointer.startswith(root + "/") for root in order_sequences):
            continue
        row = row_by_source.get(pointer)
        if row is None:
            if producer_minor > int(declared["producer_minor"]) and pointer in addition_rows:
                addition = addition_rows[pointer]
                _set_pointer(mapped, addition["target_path"], _resolve(producer_payload, pointer))
                continue
            preserved = False
            for drop_row in drop_rows:
                root = drop_row["source_path"]
                if pointer == root or pointer.startswith(root + "/"):
                    if root not in producer_observations and _has_pointer(producer_payload, root):
                        producer_observations[root] = _resolve(producer_payload, root)
                    preserved = True
                    break
            if preserved:
                continue
            reasons.append(f"unmapped_source_field:{pointer}")
            continue
        mode = row["rule"]
        value = _resolve(producer_payload, pointer)
        if mode == "reject":
            reasons.append(f"rejected_source_field:{pointer}")
            continue
        if mode == "drop":
            if row.get("producer_observation_mode") == "preserve_only":
                producer_observations[pointer] = value
            continue
        if mode == "default":
            _set_pointer(mapped, row["target_path"], row["default_value"])
            continue
        try:
            converted = _convert(row, value)
        except CrosswalkError as exc:
            reasons.append(str(exc))
            continue
        _set_pointer(mapped, row["target_path"], converted)

    for required in matrix["required_target_paths"]:
        if not _has_pointer(mapped, required):
            reasons.append(f"missing_required_target:{required}")

    decision = {
        "schema_version": "1.0.0",
        "record_type": "bridge_crosswalk_decision",
        "crosswalk_id": crosswalk["crosswalk_id"],
        "crosswalk_sha256": crosswalk["crosswalk_sha256"],
        "producer_version": f"{producer_major}.{producer_minor}.0",
        "target_version": f"{target_major}.{target_minor}.0",
        "compatible": not reasons,
        "reasons": sorted(set(reasons)) or ["compatible"],
        "mapped_target": mapped,
        "producer_observations": producer_observations,
        "decision_sha256": "",
    }
    decision["decision_sha256"] = canonical_document_sha256(
        decision, excluded_top_level_fields=("decision_sha256",)
    )
    return decision
