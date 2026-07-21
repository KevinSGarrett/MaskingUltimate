"""STATIC binders for MF-P9-08 DAZ validation / certificate / adapter contracts.

Config- and fixture-bound only. Proves V0–V9 registry closure, warn-cannot-satisfy,
repair-budget policy, acceptance-certificate honesty, and S00 adapter policy binding.
Never claims live DAZ Studio validation, accepted packages, pilot completion, gold,
doctor-green, Main-complete, or PRODUCTION_EVIDENCE_PASS.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from ..validation import validate_document
from .acceptance_certificate import (
    AcceptanceCertificateError,
    load_acceptance_certificate_policy,
    validate_acceptance_certificate_policy,
)
from .repair_retry import load_repair_retry_policy, validate_repair_retry_policy
from .s00_adapter import load_s00_adapter_policy, validate_s00_adapter_policy
from .validation_registry import (
    ValidationRegistryError,
    build_validation_set_report,
    load_validation_registry,
    validate_validation_registry,
    validate_validation_result,
)

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "daz_validation_static_contracts_report"
AUTHORITY = "daz_validation_static_only_no_live_daz_accepted_package_pilot_or_gold_authority"
SCHEMA_VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "configs" / "daz" / "validation_registry.yaml"
ACCEPTANCE_POLICY_PATH = ROOT / "configs" / "daz" / "acceptance_certificate_policy.yaml"
REPAIR_POLICY_PATH = ROOT / "configs" / "daz" / "repair_retry_policy.yaml"
S00_POLICY_PATH = ROOT / "configs" / "daz" / "s00_package_adapter.yaml"

TRACKER_ITEMS = (
    "MF-P9-08.01",
    "MF-P9-08.02",
    "MF-P9-08.03",
    "MF-P9-08.04",
    "MF-P9-08.05",
    "MF-P9-08.07",
    "MF-P9-08.08",
    "MF-P9-08.09",
)

REGISTRY_CHECKS = (
    "v0_v9_layers_closed",
    "ten_required_validators_bound",
    "warnings_cannot_satisfy_required",
    "warn_status_set_fails_closed",
    "fail_status_set_fails_closed",
)
ACCEPTANCE_CHECKS = (
    "acceptance_policy_loads",
    "warnings_cannot_satisfy_acceptance",
    "failures_cannot_satisfy_acceptance",
    "synthetic_exact_truth_tier_only",
    "overclaim_accepted_package_refused",
)
REPAIR_CHECKS = (
    "repair_retry_policy_loads",
    "bounded_retry_budgets_present",
    "deterministic_history_contract",
)
S00_CHECKS = (
    "s00_adapter_policy_loads",
    "adapter_refuses_gold_authority",
    "adapter_mapping_authority_false",
)

HONEST_NON_CLAIMS = (
    "mf_p9_08_01_complete",
    "mf_p9_08_05_complete",
    "mf_p9_08_10_pilot_complete",
    "live_daz_validation_executed",
    "accepted_package_produced",
    "doctor_green",
    "gold",
    "Main-complete",
    "PRODUCTION_EVIDENCE_PASS",
)


class DazValidationStaticError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refuse_validation_overclaim(document: Mapping[str, Any]) -> None:
    """Fail closed on live-DAZ / accepted-package / pilot / gold overclaims."""
    forbidden_true = (
        "mf_p9_08_01_complete",
        "mf_p9_08_05_complete",
        "mf_p9_08_10_pilot_complete",
        "live_daz_validation_executed",
        "accepted_package_produced",
        "doctor_green_claimed",
        "gold_claimed",
        "visual_qa_pass_claimed",
        "main_complete_claimed",
        "production_evidence_pass_claimed",
    )
    for key in forbidden_true:
        if document.get(key) is True:
            raise DazValidationStaticError(f"validation_overclaim:{key}")


def _fixture_result(
    validator: Mapping[str, Any],
    *,
    entity_id: str,
    status: str,
) -> dict[str, Any]:
    retryability = (
        "none"
        if "none" in validator["allowed_retryability"]
        else validator["allowed_retryability"][0]
    )
    return {
        "validator_id": validator["validator_id"],
        "validator_version": validator["validator_version"],
        "entity_id": entity_id,
        "status": status,
        "reason_code": validator["reason_codes"][status][0],
        "metric": "fixture_metric" if status in {"pass", "fail", "warn"} else None,
        "observed": {"value": 1} if status in {"pass", "fail", "warn"} else None,
        "expected": {"operator": "eq", "value": 1},
        "evidence_paths": [f"evidence/{validator['validator_id']}.json"],
        "retryability": retryability,
        "affected_asset_ids": [],
        "affected_mapping_ids": [],
    }


def evaluate_registry_static_binder() -> dict[str, Any]:
    """Bind closed V0–V9 registry and prove warn/fail cannot satisfy required sets."""
    if not REGISTRY_PATH.is_file():
        raise DazValidationStaticError("validation_registry_missing")
    registry = load_validation_registry(REGISTRY_PATH)
    validate_validation_registry(registry)

    layers = list(registry["layers"])
    if layers != [f"V{index}" for index in range(10)]:
        raise DazValidationStaticError("v0_v9_layers_not_closed")
    validators = registry["validators"]
    if len(validators) != 10 or any(not row["required"] for row in validators):
        raise DazValidationStaticError("ten_required_validators_missing")
    if registry["warnings_satisfy_required"] is not False:
        raise DazValidationStaticError("warnings_can_satisfy_required")

    scene_validators = [row for row in validators if row["layer"] != "V9"]
    entity_id = "daz_validation_static_fixture"

    pass_results = [
        _fixture_result(row, entity_id=entity_id, status="pass") for row in scene_validators
    ]
    for result in pass_results:
        validate_validation_result(result, registry)
    pass_report = build_validation_set_report(
        pass_results,
        entity_id=entity_id,
        scope="scene",
        registry=registry,
    )
    if pass_report["summary"]["passed"] is not True:
        raise DazValidationStaticError("all_pass_set_not_pass")

    warn_results = deepcopy(pass_results)
    warn_results[0] = _fixture_result(scene_validators[0], entity_id=entity_id, status="warn")
    warn_report = build_validation_set_report(
        warn_results,
        entity_id=entity_id,
        scope="scene",
        registry=registry,
    )
    if warn_report["summary"]["passed"] is True:
        raise DazValidationStaticError("warn_status_set_incorrectly_passed")

    fail_results = deepcopy(pass_results)
    fail_results[1] = _fixture_result(scene_validators[1], entity_id=entity_id, status="fail")
    fail_report = build_validation_set_report(
        fail_results,
        entity_id=entity_id,
        scope="scene",
        registry=registry,
    )
    if fail_report["summary"]["passed"] is True:
        raise DazValidationStaticError("fail_status_set_incorrectly_passed")

    return {
        "v0_v9_layers_closed": True,
        "ten_required_validators_bound": True,
        "warnings_cannot_satisfy_required": True,
        "warn_status_set_fails_closed": True,
        "fail_status_set_fails_closed": True,
        "registry_path": REGISTRY_PATH.as_posix(),
        "registry_sha256": _file_sha(REGISTRY_PATH),
        "pass_set_passed": True,
        "warn_set_passed": False,
        "fail_set_passed": False,
    }


def evaluate_acceptance_static_binder() -> dict[str, Any]:
    """Bind acceptance-certificate policy honesty without minting accepted packages."""
    if not ACCEPTANCE_POLICY_PATH.is_file():
        raise DazValidationStaticError("acceptance_policy_missing")
    policy = load_acceptance_certificate_policy(ACCEPTANCE_POLICY_PATH)
    validate_acceptance_certificate_policy(policy)
    if policy["warnings_satisfy_acceptance"] is not False:
        raise DazValidationStaticError("warnings_satisfy_acceptance")
    if policy["failures_satisfy_acceptance"] is not False:
        raise DazValidationStaticError("failures_satisfy_acceptance")
    if policy["eligible_truth_tiers"] != ["synthetic_exact"]:
        raise DazValidationStaticError("truth_tier_not_synthetic_exact_only")

    mutated = deepcopy(policy)
    mutated["warnings_satisfy_acceptance"] = True
    try:
        validate_acceptance_certificate_policy(mutated)
        raise DazValidationStaticError("warn_acceptance_negative_passed")
    except AcceptanceCertificateError:
        overclaim_refused = True

    return {
        "acceptance_policy_loads": True,
        "warnings_cannot_satisfy_acceptance": True,
        "failures_cannot_satisfy_acceptance": True,
        "synthetic_exact_truth_tier_only": True,
        "overclaim_accepted_package_refused": overclaim_refused,
        "policy_path": ACCEPTANCE_POLICY_PATH.as_posix(),
        "policy_sha256": _file_sha(ACCEPTANCE_POLICY_PATH),
    }


def evaluate_repair_static_binder() -> dict[str, Any]:
    """Bind repair/retry policy budgets without live DAZ repair execution."""
    if not REPAIR_POLICY_PATH.is_file():
        raise DazValidationStaticError("repair_policy_missing")
    policy = load_repair_retry_policy(REPAIR_POLICY_PATH)
    validate_repair_retry_policy(policy)
    budgets = policy["retry_budgets"]
    if not isinstance(budgets, Mapping) or not budgets:
        raise DazValidationStaticError("repair_budgets_absent")
    if any(not isinstance(value, int) or value < 1 for value in budgets.values()):
        raise DazValidationStaticError("repair_budgets_unbounded_or_invalid")
    if "authority_freeze_fields" not in policy or not policy["authority_freeze_fields"]:
        raise DazValidationStaticError("repair_history_freeze_absent")
    return {
        "repair_retry_policy_loads": True,
        "bounded_retry_budgets_present": True,
        "deterministic_history_contract": True,
        "policy_path": REPAIR_POLICY_PATH.as_posix(),
        "policy_sha256": _file_sha(REPAIR_POLICY_PATH),
        "retry_budget_keys": sorted(budgets),
    }


def evaluate_s00_static_binder() -> dict[str, Any]:
    """Bind S00 adapter policy; refuse gold / v2-active overclaims."""
    if not S00_POLICY_PATH.is_file():
        raise DazValidationStaticError("s00_policy_missing")
    policy = load_s00_adapter_policy(S00_POLICY_PATH)
    validate_s00_adapter_policy(policy)
    truth_tier = policy["training_contract"]["truth_tier"]
    if truth_tier in {"human_anchor_gold", "autonomous_certified_gold"}:
        raise DazValidationStaticError(f"s00_policy_gold_truth_tier:{truth_tier}")
    if policy["body_parts_v2_active"] is not False:
        raise DazValidationStaticError("s00_policy_v2_active")
    if policy["active_ontology"] != "body_parts_v1":
        raise DazValidationStaticError("s00_policy_active_ontology_drift")
    return {
        "s00_adapter_policy_loads": True,
        "adapter_refuses_gold_authority": True,
        "adapter_mapping_authority_false": True,
        "policy_path": S00_POLICY_PATH.as_posix(),
        "policy_sha256": _file_sha(S00_POLICY_PATH),
        "truth_tier": truth_tier,
        "body_parts_v2_active": False,
    }


def run_daz_validation_static_suite() -> dict[str, Any]:
    """Execute MF-P9-08 STATIC binders and seal a schema-valid report."""
    registry = evaluate_registry_static_binder()
    acceptance = evaluate_acceptance_static_binder()
    repair = evaluate_repair_static_binder()
    s00 = evaluate_s00_static_binder()

    registry_checks = {key: bool(registry[key]) for key in REGISTRY_CHECKS}
    acceptance_checks = {key: bool(acceptance[key]) for key in ACCEPTANCE_CHECKS}
    repair_checks = {key: bool(repair[key]) for key in REPAIR_CHECKS}
    s00_checks = {key: bool(s00[key]) for key in S00_CHECKS}

    if not all(registry_checks.values()):
        raise DazValidationStaticError("registry_checks_failed")
    if not all(acceptance_checks.values()):
        raise DazValidationStaticError("acceptance_checks_failed")
    if not all(repair_checks.values()):
        raise DazValidationStaticError("repair_checks_failed")
    if not all(s00_checks.values()):
        raise DazValidationStaticError("s00_checks_failed")

    # Negative overclaim fixture.
    try:
        refuse_validation_overclaim({"mf_p9_08_10_pilot_complete": True})
        raise DazValidationStaticError("overclaim_negative_passed")
    except DazValidationStaticError as exc:
        if "mf_p9_08_10_pilot_complete" not in exc.reason:
            raise
        overclaim_blocked = True

    # Tamper fixture: mutating registry warnings policy must fail closed.
    try:
        mutated = load_validation_registry(REGISTRY_PATH)
        mutated = dict(mutated)
        mutated["warnings_satisfy_required"] = True
        validate_validation_registry(mutated)
        raise DazValidationStaticError("registry_warn_policy_tamper_passed")
    except ValidationRegistryError:
        registry_tamper_blocked = True

    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "items": list(TRACKER_ITEMS),
        "registry_checks": dict(sorted(registry_checks.items())),
        "acceptance_checks": dict(sorted(acceptance_checks.items())),
        "repair_checks": dict(sorted(repair_checks.items())),
        "s00_checks": dict(sorted(s00_checks.items())),
        "checks": {
            "registry_v0_v9_binder": "pass",
            "acceptance_certificate_binder": "pass",
            "repair_retry_binder": "pass",
            "s00_adapter_binder": "pass",
        },
        "negative_fixtures": {
            "completion_overclaim_blocked": overclaim_blocked,
            "registry_warn_policy_tamper_blocked": registry_tamper_blocked,
        },
        "mf_p9_08_01_complete": False,
        "mf_p9_08_05_complete": False,
        "mf_p9_08_10_pilot_complete": False,
        "live_daz_validation_executed": False,
        "accepted_package_produced": False,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "visual_qa_pass_claimed": False,
        "main_complete_claimed": False,
        "production_evidence_pass_claimed": False,
        "honest_non_claims": list(HONEST_NON_CLAIMS),
        "bindings": {
            "registry_sha256": registry["registry_sha256"],
            "acceptance_policy_sha256": acceptance["policy_sha256"],
            "repair_policy_sha256": repair["policy_sha256"],
            "s00_policy_sha256": s00["policy_sha256"],
        },
        "implementation": {
            "module": "src/maskfactory/daz/validation_static_contracts.py",
            "configs": [
                "configs/daz/validation_registry.yaml",
                "configs/daz/acceptance_certificate_policy.yaml",
                "configs/daz/repair_retry_policy.yaml",
                "configs/daz/s00_package_adapter.yaml",
            ],
            "tests": ["tests/test_daz_validation_static_contracts.py"],
        },
    }
    refuse_validation_overclaim(draft)
    digest = _sha(draft)
    draft["report_id"] = f"dvs_{digest[:24]}"
    draft["seal_sha256"] = digest
    draft["sha256"] = _sha({key: value for key, value in draft.items() if key != "sha256"})

    issues = validate_document(draft, "daz_validation_static_contracts_report")
    if issues:
        detail = "; ".join(
            f"{getattr(issue, 'pointer', None) or '/'}: {issue.message}" for issue in issues
        )
        raise DazValidationStaticError(f"schema_validation_failed:{detail}")
    return draft


__all__ = [
    "ACCEPTANCE_CHECKS",
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "HONEST_NON_CLAIMS",
    "PROOF_TIER",
    "REGISTRY_CHECKS",
    "REPAIR_CHECKS",
    "S00_CHECKS",
    "SCHEMA_VERSION",
    "TRACKER_ITEMS",
    "DazValidationStaticError",
    "evaluate_acceptance_static_binder",
    "evaluate_registry_static_binder",
    "evaluate_repair_static_binder",
    "evaluate_s00_static_binder",
    "refuse_validation_overclaim",
    "run_daz_validation_static_suite",
]
