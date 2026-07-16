"""Closed V0-V9 DAZ validation result registry and set aggregation."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from ..validation import require_valid_document


class ValidationRegistryError(ValueError):
    """A V0-V9 registry, result, result set, or publication is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_validation_registry(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_validation_registry(document)
    return document


def validate_validation_registry(registry: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "registry_version",
        "statuses",
        "retryability",
        "warnings_satisfy_required",
        "not_applicable_satisfies_required",
        "layers",
        "validators",
    }
    if not isinstance(registry, Mapping) or set(registry) != expected:
        raise ValidationRegistryError("validation_registry_fields_invalid", str(registry))
    if registry["schema_version"] != "1.0.0" or registry["registry_version"] != "1.0.0":
        raise ValidationRegistryError("validation_registry_identity_invalid", str(registry))
    if registry["statuses"] != ["pass", "fail", "warn", "not_applicable"]:
        raise ValidationRegistryError("validation_registry_statuses_invalid", str(registry))
    if registry["retryability"] != [
        "none",
        "same_recipe",
        "adjusted_recipe",
        "asset_retest",
    ]:
        raise ValidationRegistryError("validation_registry_retryability_invalid", str(registry))
    if registry["warnings_satisfy_required"] is not False:
        raise ValidationRegistryError("validation_registry_warning_policy_invalid", str(registry))
    if registry["not_applicable_satisfies_required"] is not True:
        raise ValidationRegistryError(
            "validation_registry_not_applicable_policy_invalid", str(registry)
        )
    expected_layers = {
        "V0": {
            "name": "contract",
            "scope": "scene",
            "typical_dispositions": ["reject_recipe", "reject_package"],
        },
        "V1": {
            "name": "asset",
            "scope": "scene",
            "typical_dispositions": ["hold", "quarantine_asset"],
        },
        "V2": {
            "name": "recipe",
            "scope": "scene",
            "typical_dispositions": ["reject", "regenerate"],
        },
        "V3": {
            "name": "assembly",
            "scope": "scene",
            "typical_dispositions": ["bounded_repair", "reject"],
        },
        "V4": {
            "name": "geometry",
            "scope": "scene",
            "typical_dispositions": [
                "bounded_repair",
                "reject",
                "quarantine_combination",
            ],
        },
        "V5": {
            "name": "render",
            "scope": "scene",
            "typical_dispositions": ["rerender", "reject"],
        },
        "V6": {
            "name": "semantic",
            "scope": "scene",
            "typical_dispositions": ["reject", "quarantine_mapping"],
        },
        "V7": {
            "name": "multi_person",
            "scope": "scene",
            "typical_dispositions": ["reject"],
        },
        "V8": {
            "name": "package",
            "scope": "scene",
            "typical_dispositions": ["reject"],
        },
        "V9": {
            "name": "corpus",
            "scope": "corpus",
            "typical_dispositions": ["exclude", "rebalance"],
        },
    }
    if registry["layers"] != expected_layers:
        raise ValidationRegistryError("validation_registry_layers_invalid", str(registry["layers"]))
    validators = registry["validators"]
    if not isinstance(validators, list) or len(validators) != 10:
        raise ValidationRegistryError("validation_registry_validators_invalid", str(validators))
    validator_ids: set[str] = set()
    names: set[str] = set()
    global_reason_codes: set[str] = set()
    expected_fields = {
        "validator_id",
        "validator_version",
        "layer",
        "name",
        "owner",
        "required",
        "allowed_retryability",
        "severity_by_status",
        "evidence_required_by_status",
        "reason_codes",
    }
    for index, validator in enumerate(validators):
        layer = f"V{index}"
        if (
            not isinstance(validator, Mapping)
            or set(validator) != expected_fields
            or validator["validator_id"] != f"DAZ-{layer}-001"
            or validator["validator_version"] != "1.0.0"
            or validator["layer"] != layer
            or not isinstance(validator["name"], str)
            or not validator["name"]
            or not isinstance(validator["owner"], str)
            or not validator["owner"]
            or validator["required"] is not True
            or not isinstance(validator["allowed_retryability"], list)
            or not validator["allowed_retryability"]
            or not set(validator["allowed_retryability"]) <= set(registry["retryability"])
            or set(validator["reason_codes"]) != set(registry["statuses"])
            or validator["severity_by_status"]
            != {
                "pass": "info",
                "fail": "error",
                "warn": "warning",
                "not_applicable": "info",
            }
            or validator["evidence_required_by_status"]
            != {"pass": True, "fail": True, "warn": True, "not_applicable": False}
        ):
            raise ValidationRegistryError("validation_registry_validator_invalid", str(validator))
        if validator["validator_id"] in validator_ids or validator["name"] in names:
            raise ValidationRegistryError(
                "validation_registry_validator_duplicate", validator["validator_id"]
            )
        validator_ids.add(validator["validator_id"])
        names.add(validator["name"])
        local_codes: set[str] = set()
        for status in registry["statuses"]:
            codes = validator["reason_codes"][status]
            if (
                not isinstance(codes, list)
                or not codes
                or len(codes) != len(set(codes))
                or any(not _reason_code(code) for code in codes)
            ):
                raise ValidationRegistryError(
                    "validation_registry_reason_codes_invalid", str(validator)
                )
            local_codes.update(codes)
        if (
            len(local_codes)
            != sum(len(validator["reason_codes"][status]) for status in registry["statuses"])
            or global_reason_codes & local_codes
        ):
            raise ValidationRegistryError(
                "validation_registry_reason_code_duplicate_invalid", str(sorted(local_codes))
            )
        global_reason_codes.update(local_codes)


def validate_validation_result(result: Mapping[str, Any], registry: Mapping[str, Any]) -> None:
    validate_validation_registry(registry)
    require_valid_document(result, "daz_validation_result")
    validators = {row["validator_id"]: row for row in registry["validators"]}
    validator = validators.get(result["validator_id"])
    if validator is None:
        raise ValidationRegistryError("validation_result_validator_unknown", result["validator_id"])
    if result["validator_version"] != validator["validator_version"]:
        raise ValidationRegistryError(
            "validation_result_version_mismatch", result["validator_version"]
        )
    if result["reason_code"] not in validator["reason_codes"][result["status"]]:
        raise ValidationRegistryError(
            "validation_result_reason_status_invalid",
            f"{result['status']}:{result['reason_code']}",
        )
    if result["retryability"] not in validator["allowed_retryability"]:
        raise ValidationRegistryError(
            "validation_result_retryability_invalid", result["retryability"]
        )
    if validator["evidence_required_by_status"][result["status"]] and not result["evidence_paths"]:
        raise ValidationRegistryError("validation_result_evidence_required", result["validator_id"])


def build_validation_set_report(
    results: Sequence[Mapping[str, Any]],
    *,
    entity_id: str,
    scope: str,
    registry: Mapping[str, Any],
    required_validator_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Aggregate one exact validator result per ID; warnings cannot satisfy requirements."""

    validate_validation_registry(registry)
    if not isinstance(entity_id, str) or not entity_id or scope not in {"scene", "corpus"}:
        raise ValidationRegistryError("validation_set_identity_invalid", f"{entity_id}:{scope}")
    validators = {row["validator_id"]: row for row in registry["validators"]}
    scope_validator_ids = {
        validator_id
        for validator_id, validator in validators.items()
        if registry["layers"][validator["layer"]]["scope"] == scope
    }
    required = (
        sorted(
            validator_id
            for validator_id in scope_validator_ids
            if validators[validator_id]["required"]
        )
        if required_validator_ids is None
        else list(required_validator_ids)
    )
    if (
        len(required) != len(set(required))
        or required != sorted(required)
        or not set(required) <= scope_validator_ids
    ):
        raise ValidationRegistryError("validation_set_required_ids_invalid", str(required))
    result_by_id: dict[str, dict[str, Any]] = {}
    for raw_result in results:
        result = dict(raw_result)
        validate_validation_result(result, registry)
        validator_id = result["validator_id"]
        if result["entity_id"] != entity_id:
            raise ValidationRegistryError("validation_set_entity_mismatch", result["entity_id"])
        if validator_id not in scope_validator_ids:
            raise ValidationRegistryError("validation_set_scope_mismatch", validator_id)
        if validator_id in result_by_id:
            raise ValidationRegistryError("validation_set_duplicate_result", validator_id)
        result_by_id[validator_id] = result
    findings: list[dict[str, str]] = []
    for validator_id in required:
        result = result_by_id.get(validator_id)
        if result is None:
            _finding(
                findings,
                "VALIDATION_REQUIRED_RESULT_MISSING",
                f"/required/{validator_id}",
                validator_id,
            )
        elif result["status"] == "fail":
            _finding(
                findings,
                "VALIDATION_REQUIRED_RESULT_FAILED",
                f"/results/{validator_id}",
                result["reason_code"],
            )
        elif result["status"] == "warn":
            _finding(
                findings,
                "VALIDATION_REQUIRED_WARNING",
                f"/results/{validator_id}",
                result["reason_code"],
            )
    ordered_results = [result_by_id[key] for key in sorted(result_by_id)]
    layers = [f"V{index}" for index in range(9)] if scope == "scene" else ["V9"]
    layer_summary = {}
    for layer in layers:
        layer_ids = {
            validator_id
            for validator_id, validator in validators.items()
            if validator["layer"] == layer
        }
        layer_results = [
            result for result in ordered_results if result["validator_id"] in layer_ids
        ]
        required_layer_ids = set(required) & layer_ids
        layer_summary[layer] = {
            status: sum(result["status"] == status for result in layer_results)
            for status in registry["statuses"]
        }
        layer_summary[layer]["required_satisfied"] = all(
            result_by_id.get(validator_id, {}).get("status") in {"pass", "not_applicable"}
            for validator_id in required_layer_ids
        )
    findings.sort(key=lambda row: (row["code"], row["path"], row["detail"]))
    required_pass_count = sum(
        result_by_id.get(validator_id, {}).get("status") == "pass" for validator_id in required
    )
    required_satisfied_count = sum(
        result_by_id.get(validator_id, {}).get("status") in {"pass", "not_applicable"}
        for validator_id in required
    )
    content = {
        "registry_version": registry["registry_version"],
        "registry_sha256": _canonical_sha(registry),
        "entity_id": entity_id,
        "scope": scope,
        "required_validator_ids": required,
        "results": ordered_results,
        "layer_summary": layer_summary,
        "findings": findings,
        "summary": {
            "passed": not findings,
            "finding_count": len(findings),
            "failure_codes": sorted({row["code"] for row in findings}),
            "result_count": len(ordered_results),
            "required_count": len(required),
            "required_pass_count": required_pass_count,
            "required_satisfied_count": required_satisfied_count,
            "warning_count": sum(result["status"] == "warn" for result in ordered_results),
            "failed_count": sum(result["status"] == "fail" for result in ordered_results),
            "not_applicable_count": sum(
                result["status"] == "not_applicable" for result in ordered_results
            ),
        },
    }
    digest = _canonical_sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"dvsr_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    require_valid_document(report, "daz_validation_set_report")
    return report


def publish_validation_set_report(
    report: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    require_valid_document(report, "daz_validation_set_report")
    _verify_hashed_report(report)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{report['report_id']}.json"
    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise ValidationRegistryError("validation_publication_conflict", str(target))
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


def _verify_hashed_report(report: Mapping[str, Any]) -> None:
    content = {
        key: value
        for key, value in report.items()
        if key not in {"schema_version", "report_id", "report_sha256"}
    }
    digest = _canonical_sha(content)
    if report["report_sha256"] != digest or report["report_id"] != f"dvsr_{digest[:24]}":
        raise ValidationRegistryError("validation_report_hash_invalid", report["report_id"])


def _canonical_sha(document: Any) -> str:
    try:
        payload = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValidationRegistryError("validation_noncanonical_value", str(exc)) from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reason_code(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 3 <= len(value) <= 128
        and value[0].isalpha()
        and value == value.upper()
        and all(character.isalnum() or character == "_" for character in value)
    )


def _finding(findings: list[dict[str, str]], code: str, path: str, detail: str) -> None:
    findings.append({"code": code, "path": path, "detail": detail})
