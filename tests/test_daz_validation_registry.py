from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.validation_registry import (
    ValidationRegistryError,
    build_validation_set_report,
    load_validation_registry,
    publish_validation_set_report,
    validate_validation_registry,
    validate_validation_result,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "configs" / "daz" / "validation_registry.yaml"


def _registry() -> dict:
    return load_validation_registry(REGISTRY_PATH)


def _result(
    validator: dict,
    *,
    entity_id: str = "daz_scene_fixture",
    status: str = "pass",
    reason_code: str | None = None,
    retryability: str = "none",
) -> dict:
    return {
        "validator_id": validator["validator_id"],
        "validator_version": validator["validator_version"],
        "entity_id": entity_id,
        "status": status,
        "reason_code": reason_code or validator["reason_codes"][status][0],
        "metric": "fixture_metric" if status in {"pass", "fail", "warn"} else None,
        "observed": {"value": 1} if status in {"pass", "fail", "warn"} else None,
        "expected": {"operator": "eq", "value": 1},
        "evidence_paths": [f"evidence/{validator['validator_id']}.json"],
        "retryability": retryability,
        "affected_asset_ids": [],
        "affected_mapping_ids": [],
    }


def test_registry_freezes_all_v0_v9_layers_and_scopes() -> None:
    registry = _registry()
    validate_validation_registry(registry)
    assert list(registry["layers"]) == [f"V{index}" for index in range(10)]
    assert all(registry["layers"][f"V{index}"]["scope"] == "scene" for index in range(9))
    assert registry["layers"]["V9"]["scope"] == "corpus"
    assert [row["validator_id"] for row in registry["validators"]] == [
        f"DAZ-V{index}-001" for index in range(10)
    ]
    assert registry["warnings_satisfy_required"] is False
    assert registry["not_applicable_satisfies_required"] is True
    assert all(validator["owner"] for validator in registry["validators"])
    assert all(
        validator["severity_by_status"]["fail"] == "error"
        and validator["evidence_required_by_status"]["pass"] is True
        for validator in registry["validators"]
    )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda r: r.__setitem__("registry_version", "2.0.0"), "identity"),
        (lambda r: r["statuses"].reverse(), "statuses"),
        (lambda r: r["retryability"].pop(), "retryability"),
        (lambda r: r.__setitem__("warnings_satisfy_required", True), "warning_policy"),
        (
            lambda r: r.__setitem__("not_applicable_satisfies_required", False),
            "not_applicable_policy",
        ),
        (lambda r: r["layers"]["V9"].__setitem__("scope", "scene"), "layers"),
        (lambda r: r["validators"].pop(), "validators"),
        (lambda r: r["validators"][0].__setitem__("validator_id", "DAZ-V0-002"), "validator"),
        (
            lambda r: r["validators"][1]["reason_codes"]["fail"].append(
                r["validators"][0]["reason_codes"]["fail"][0]
            ),
            "reason_code_duplicate",
        ),
    ],
)
def test_closed_registry_drift_fails(mutation, reason: str) -> None:
    registry = _registry()
    mutation(registry)
    with pytest.raises(ValidationRegistryError, match=f"validation_registry_{reason}_invalid"):
        validate_validation_registry(registry)


@pytest.mark.parametrize("layer_index", range(10))
@pytest.mark.parametrize("status", ["pass", "fail", "warn", "not_applicable"])
def test_result_contract_accepts_every_layer_and_status(layer_index: int, status: str) -> None:
    registry = _registry()
    validator = registry["validators"][layer_index]
    retryability = validator["allowed_retryability"][0]
    validate_validation_result(
        _result(validator, status=status, retryability=retryability), registry
    )


def test_every_closed_reason_code_is_bound_to_exact_status() -> None:
    registry = _registry()
    for validator in registry["validators"]:
        for status, reason_codes in validator["reason_codes"].items():
            for reason_code in reason_codes:
                validate_validation_result(
                    _result(
                        validator,
                        status=status,
                        reason_code=reason_code,
                        retryability=validator["allowed_retryability"][0],
                    ),
                    registry,
                )


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda r: r.__setitem__("validator_id", "DAZ-V0-999"), "validator_unknown"),
        (lambda r: r.__setitem__("validator_version", "9.9.9"), "version_mismatch"),
        (lambda r: r.__setitem__("reason_code", "CONTRACT_SCHEMA_INVALID"), "reason_status"),
        (lambda r: r.__setitem__("retryability", "same_recipe"), "retryability"),
    ],
)
def test_registry_semantic_result_drift_fails(mutate, reason: str) -> None:
    registry = _registry()
    result = _result(registry["validators"][0])
    mutate(result)
    with pytest.raises(ValidationRegistryError, match=f"validation_result_{reason}"):
        validate_validation_result(result, registry)


@pytest.mark.parametrize("path", ["../escape.json", "/absolute.json", "C:/absolute.json"])
def test_evidence_paths_must_be_safe_relative_paths(path: str) -> None:
    registry = _registry()
    result = _result(registry["validators"][0])
    result["evidence_paths"] = [path]
    with pytest.raises(ValueError):
        validate_validation_result(result, registry)


def test_evidence_requirement_is_status_bound() -> None:
    registry = _registry()
    validator = registry["validators"][0]
    passed = _result(validator)
    passed["evidence_paths"] = []
    with pytest.raises(ValidationRegistryError, match="validation_result_evidence_required"):
        validate_validation_result(passed, registry)
    not_applicable = _result(validator, status="not_applicable")
    not_applicable["evidence_paths"] = []
    validate_validation_result(not_applicable, registry)


def test_scene_set_all_required_passes() -> None:
    registry = _registry()
    results = [_result(validator) for validator in registry["validators"][:9]]
    report = build_validation_set_report(
        results, entity_id="daz_scene_fixture", scope="scene", registry=registry
    )
    assert report["summary"]["passed"] is True
    assert report["summary"]["required_count"] == 9
    assert report["summary"]["required_satisfied_count"] == 9
    assert list(report["layer_summary"]) == [f"V{index}" for index in range(9)]


def test_required_not_applicable_is_executed_and_satisfied() -> None:
    registry = _registry()
    results = [_result(validator) for validator in registry["validators"][:9]]
    results[7] = _result(registry["validators"][7], status="not_applicable")
    report = build_validation_set_report(
        results, entity_id="daz_scene_fixture", scope="scene", registry=registry
    )
    assert report["summary"]["passed"] is True
    assert report["summary"]["required_pass_count"] == 8
    assert report["summary"]["required_satisfied_count"] == 9


def test_corpus_scope_uses_only_v9() -> None:
    registry = _registry()
    result = _result(registry["validators"][9], entity_id="corpus_fixture")
    report = build_validation_set_report(
        [result], entity_id="corpus_fixture", scope="corpus", registry=registry
    )
    assert report["summary"]["passed"] is True
    assert list(report["layer_summary"]) == ["V9"]


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (None, "VALIDATION_REQUIRED_RESULT_MISSING"),
        ("fail", "VALIDATION_REQUIRED_RESULT_FAILED"),
        ("warn", "VALIDATION_REQUIRED_WARNING"),
    ],
)
def test_missing_fail_and_warning_cannot_satisfy_required(status: str | None, code: str) -> None:
    registry = _registry()
    validator = registry["validators"][0]
    results = [] if status is None else [_result(validator, status=status)]
    report = build_validation_set_report(
        results,
        entity_id="daz_scene_fixture",
        scope="scene",
        registry=registry,
        required_validator_ids=[validator["validator_id"]],
    )
    assert report["summary"]["passed"] is False
    assert code in report["summary"]["failure_codes"]


def test_optional_warning_is_informative() -> None:
    registry = _registry()
    required = registry["validators"][0]
    optional = registry["validators"][1]
    report = build_validation_set_report(
        [_result(required), _result(optional, status="warn")],
        entity_id="daz_scene_fixture",
        scope="scene",
        registry=registry,
        required_validator_ids=[required["validator_id"]],
    )
    assert report["summary"]["passed"] is True
    assert report["summary"]["warning_count"] == 1


@pytest.mark.parametrize("defect", ["duplicate", "entity", "scope", "required_order"])
def test_result_set_structural_defects_fail(defect: str) -> None:
    registry = _registry()
    result = _result(registry["validators"][0])
    results = [result]
    kwargs = {
        "entity_id": "daz_scene_fixture",
        "scope": "scene",
        "registry": registry,
        "required_validator_ids": ["DAZ-V0-001"],
    }
    if defect == "duplicate":
        results.append(deepcopy(result))
    elif defect == "entity":
        results[0]["entity_id"] = "other"
    elif defect == "scope":
        results = [_result(registry["validators"][9], entity_id="daz_scene_fixture")]
    else:
        kwargs["required_validator_ids"] = ["DAZ-V1-001", "DAZ-V0-001"]
    with pytest.raises(ValidationRegistryError, match="validation_set_"):
        build_validation_set_report(results, **kwargs)


def test_publication_is_immutable_and_idempotent(tmp_path: Path) -> None:
    registry = _registry()
    report = build_validation_set_report(
        [_result(validator) for validator in registry["validators"][:9]],
        entity_id="daz_scene_fixture",
        scope="scene",
        registry=registry,
    )
    target, published = publish_validation_set_report(report, tmp_path)
    assert published is True
    assert publish_validation_set_report(report, tmp_path) == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValidationRegistryError, match="validation_publication_conflict"):
        publish_validation_set_report(report, tmp_path)


def test_cli_validation_set_is_idempotent(tmp_path: Path) -> None:
    registry = _registry()
    results = [_result(validator) for validator in registry["validators"][:9]]
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(results), encoding="utf-8")
    output = tmp_path / "reports"
    arguments = [
        "daz",
        "recipes",
        "aggregate-validation-set",
        "--results",
        str(results_path),
        "--entity-id",
        "daz_scene_fixture",
        "--scope",
        "scene",
        "--registry",
        str(REGISTRY_PATH),
        "--output",
        str(output),
    ]
    runner = CliRunner()
    first = runner.invoke(main, arguments)
    assert first.exit_code == 0, first.output
    payload = json.loads(first.output)
    assert payload["data"]["summary"]["passed"] is True
    assert payload["data"]["publication"]["published"] is True
    replay = runner.invoke(main, arguments)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
