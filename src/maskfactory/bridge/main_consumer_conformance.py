"""Pinned Main-consumer conformance fixture packs and fail-closed harness.

MaskFactory owns producer-side shapes, adapter observation templates, and
requirements/capability disagreement oracles. Main must later supply matching
runtime artifacts. This module never fabricates Main adoption completion.
"""

from __future__ import annotations

import copy
import json
import runpy
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

from maskfactory.bridge.consumer_requirements import evaluate_consumer_requirements_admission
from maskfactory.bridge.external_adapter_conformance import (
    build_external_adapter_conformance_evidence,
)
from maskfactory.validation import canonical_document_sha256

REPO_ROOT = Path(__file__).parents[3]
POLICY_PATH = REPO_ROOT / "configs" / "bridge_main_consumer_conformance_policy.yaml"
SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "main_consumer_conformance_evidence.schema.json"
)
POLICY_ID = "maskfactory-bridge-main-consumer-conformance-v1"
GOLDEN_VECTORS_PATH = (
    REPO_ROOT / "qa" / "governance" / "bridge" / "main_consumer_conformance_golden_vectors_v1.json"
)


class MainConsumerConformanceError(ValueError):
    """Raised when conformance policy or pinned pack material is unusable."""


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MainConsumerConformanceError("main-consumer conformance policy unavailable") from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise MainConsumerConformanceError("unexpected main-consumer conformance policy")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise MainConsumerConformanceError("main-consumer conformance policy hash mismatch")
    codes = policy.get("reason_codes")
    if not isinstance(codes, list) or not codes or len(codes) != len(set(codes)):
        raise MainConsumerConformanceError("main-consumer conformance policy is not closed")
    return dict(policy)


def _ordered(policy: Mapping[str, Any], reasons: list[str]) -> list[str]:
    return [code for code in policy["reason_codes"] if code in set(reasons)] or ["eligible"]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MainConsumerConformanceError(f"unreadable conformance artifact: {path.name}") from exc
    if not isinstance(document, Mapping):
        raise MainConsumerConformanceError(f"non-object conformance artifact: {path.name}")
    return dict(document)


def _pack_root(policy: Mapping[str, Any]) -> Path:
    return REPO_ROOT / str(policy["fixture_pack_relative_root"])


def _inbox_root(policy: Mapping[str, Any], override: Path | None) -> Path:
    if override is not None:
        return override
    return REPO_ROOT / str(policy["main_artifact_inbox_relative_root"])


def load_fixture_pack(policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Load and hash-verify the pinned Main-consumer conformance fixture pack."""
    policy = policy or _policy()
    root = _pack_root(policy)
    reasons: list[str] = []
    members: dict[str, dict[str, Any]] = {}
    for relative in policy["required_pack_members"]:
        path = root / relative
        if not path.is_file():
            reasons.append("pack_member_missing")
            continue
        members[relative] = _load_json(path)

    manifest = members.get("pack_manifest_v1.json")
    if not isinstance(manifest, Mapping):
        reasons.append("pack_manifest_invalid")
        return {
            "status": "invalid",
            "reasons": _ordered(policy, reasons or ["pack_manifest_invalid"]),
            "manifest": {},
            "members": members,
        }

    expected_manifest = canonical_document_sha256(
        manifest, excluded_top_level_fields=("manifest_sha256",)
    )
    if manifest.get("manifest_sha256") != expected_manifest:
        reasons.append("pack_manifest_invalid")

    declared = {
        row["path"]: row
        for row in manifest.get("members") or ()
        if isinstance(row, Mapping) and isinstance(row.get("path"), str)
    }
    for relative in policy["required_pack_members"]:
        if relative == "pack_manifest_v1.json":
            continue
        member = members.get(relative)
        row = declared.get(relative)
        if member is None or row is None:
            reasons.append("pack_member_missing")
            continue
        observed = canonical_document_sha256(member)
        if observed != row.get("sha256"):
            reasons.append("pack_member_hash_drift")
        shape_hash = member.get("shape_sha256")
        if isinstance(shape_hash, str):
            expected_shape = canonical_document_sha256(
                member, excluded_top_level_fields=("shape_sha256",)
            )
            if shape_hash != expected_shape:
                reasons.append("pack_member_hash_drift")

    claim = (
        manifest.get("claim_boundary")
        if isinstance(manifest.get("claim_boundary"), Mapping)
        else {}
    )
    if claim.get("main_adoption_complete") is True:
        reasons.append("main_fabrication_claim_forbidden")

    ordered = _ordered(policy, reasons) if reasons else []
    return {
        "status": "ready" if not reasons else "invalid",
        "reasons": ordered,
        "manifest": manifest,
        "members": members,
    }


def load_receipt_shape(decision: str, *, pack: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return one pinned adopted/rejected/partially_adopted receipt shape."""
    pack = pack or load_fixture_pack()
    mapping = {
        "adopted": "receipt_shapes/adopted_receipt_shape_v1.json",
        "rejected": "receipt_shapes/rejected_receipt_shape_v1.json",
        "partially_adopted": "receipt_shapes/partially_adopted_receipt_shape_v1.json",
    }
    relative = mapping.get(decision)
    if relative is None:
        raise MainConsumerConformanceError(f"unknown receipt shape decision: {decision}")
    shape = pack["members"].get(relative)
    if not isinstance(shape, Mapping):
        raise MainConsumerConformanceError(f"receipt shape unavailable: {decision}")
    return dict(shape)


def load_adapter_observation_template(
    template_id: str, *, pack: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Return one pinned adapter observation template."""
    pack = pack or load_fixture_pack()
    for relative, member in pack["members"].items():
        if (
            relative.startswith("adapter_observations/")
            and member.get("template_id") == template_id
        ):
            return dict(member)
    raise MainConsumerConformanceError(f"adapter observation template unavailable: {template_id}")


def load_disagreement_vectors(*, pack: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return pinned requirements/capability disagreement golden vectors."""
    pack = pack or load_fixture_pack()
    relative = "disagreement_vectors/requirements_capability_disagreement_v1.json"
    vectors = pack["members"].get(relative)
    if not isinstance(vectors, Mapping):
        raise MainConsumerConformanceError("disagreement vectors unavailable")
    return dict(vectors)


def _builder() -> dict[str, Any]:
    path = REPO_ROOT / "tests" / "fixtures" / "mask_bridge_contracts" / "build_contract_fixtures.py"
    return runpy.run_path(str(path))


def _baseline_requirements_admission() -> (
    tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]
):
    builder = _builder()
    requirements = builder["build_consumer_requirements"]()
    builder["sign"](
        requirements,
        "requirements_sha256",
        "consumer_requirements",
        ("requirements_sha256", "signature"),
    )
    offer = {
        "capability_id": "mask.package.read",
        "access_modes": ["mode_a_package_read", "mode_b_live_predict"],
        "labels": ["left_hand", "torso"],
        "artifact_kinds": ["atomic_visible", "protected_qa"],
        "media_scopes": ["still_image"],
        "transform_operations": ["inverse_project"],
        "maximum_person_count": 2,
        "authority_states": ["qa_passed_noncertified", "certified"],
        "truth_tiers": [
            "machine_candidate",
            "qa_passed_machine_candidate",
            "operationally_certified_artifact",
        ],
        "certificate_kinds": ["exact_serving_route_output"],
        "issuer_kinds": ["maskfactory_autonomous"],
        "versions": {
            "api_contracts": ["maskfactory-api/1.0"],
            "package_formats": ["maskfactory-package/1.0"],
            "ontology_versions": ["body_parts_v1"],
            "node_pack_versions": ["1.0.0"],
        },
        "runtime": {
            "maximum_p50_latency_ms": 2000,
            "maximum_p95_latency_ms": 4000,
            "maximum_vram_mb": 8192,
            "maximum_ram_mb": 16384,
            "maximum_output_bytes": 1000000,
            "minimum_concurrency": 1,
        },
        "evidence": [
            {"evidence_id": "certificate", "kind": "authority_certificate", "sha256": "a" * 64},
            {"evidence_id": "benchmark", "kind": "route_benchmark", "sha256": "b" * 64},
        ],
    }
    return requirements, builder["TRUSTED_KEYS"], [offer]


def _mutate_offers(mutation: str, offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = copy.deepcopy(offers)
    if mutation == "drop_required_offer":
        return []
    if mutation == "drop_optional_offer":
        return rows
    if mutation == "shrink_required_labels":
        rows[0]["labels"] = ["left_hand"]
        return rows
    if mutation == "lower_authority_states":
        rows[0]["authority_states"] = ["draft"]
        return rows
    if mutation == "wrong_api_contract_version":
        rows[0]["versions"]["api_contracts"] = ["maskfactory-api/9.9"]
        return rows
    if mutation == "exceed_latency_budget":
        rows[0]["runtime"]["maximum_p50_latency_ms"] = 999999
        rows[0]["runtime"]["maximum_p95_latency_ms"] = 999999
        return rows
    if mutation == "duplicate_capability_offer":
        return [rows[0], copy.deepcopy(rows[0])]
    raise MainConsumerConformanceError(f"unknown disagreement mutation: {mutation}")


def evaluate_disagreement_vectors(*, pack: Mapping[str, Any] | None = None) -> list[dict[str, str]]:
    """Execute pinned disagreement vectors against the consumer-requirements oracle."""
    vectors_doc = load_disagreement_vectors(pack=pack)
    requirements, trusted_keys, baseline_offers = _baseline_requirements_admission()
    results: list[dict[str, str]] = []
    for vector in vectors_doc.get("vectors") or ():
        if not isinstance(vector, Mapping):
            continue
        vector_id = str(vector.get("id") or "unknown")
        mutation = str(vector.get("mutation") or "")
        offers = _mutate_offers(mutation, baseline_offers)
        admission = {
            "schema_version": "1.0.0",
            "record_type": "maskfactory_consumer_requirements_admission",
            "requirements": requirements,
            "offered_capabilities": offers,
        }
        decision, issues = evaluate_consumer_requirements_admission(
            admission,
            trusted_signing_keys=trusted_keys,
            observed_at="2026-07-17T00:01:00Z",
            replay_ledger={},
        )
        failures: list[str] = []
        expected_status = vector.get("expected_status")
        if decision.get("status") != expected_status:
            failures.append(f"status:{decision.get('status')}!={expected_status}")
        rejection = set(decision.get("rejection_reasons") or ())
        for needle in vector.get("expected_rejection_contains") or ():
            if needle not in rejection and not any(needle in item for item in rejection):
                # also check unmet constraint names nested in outcomes
                nested = {
                    constraint
                    for row in list(decision.get("required_outcomes") or ())
                    + list(decision.get("optional_outcomes") or ())
                    if isinstance(row, Mapping)
                    for constraint in row.get("unmet_constraints") or ()
                }
                if needle not in nested and needle not in {
                    row.get("capability_id")
                    for row in list(decision.get("required_outcomes") or ())
                    if isinstance(row, Mapping) and row.get("status") == "unmet"
                }:
                    failures.append(f"missing_rejection:{needle}")
        for validator in vector.get("expected_issue_validators") or ():
            if validator not in {issue.validator for issue in issues}:
                failures.append(f"missing_issue:{validator}")
        if vector.get("expected_required_all_met") is True:
            unmet_required = [
                row.get("capability_id")
                for row in decision.get("required_outcomes") or ()
                if isinstance(row, Mapping) and row.get("status") != "met"
            ]
            if unmet_required:
                failures.append(f"required_unmet:{unmet_required}")
        for capability_id in vector.get("expected_optional_unmet") or ():
            optional = {
                row.get("capability_id"): row
                for row in decision.get("optional_outcomes") or ()
                if isinstance(row, Mapping)
            }
            row = optional.get(capability_id)
            if not isinstance(row, Mapping) or row.get("status") != "unmet":
                failures.append(f"optional_not_unmet:{capability_id}")
        results.append(
            {
                "vector_id": vector_id,
                "status": "passed" if not failures else "failed",
                "detail": "ok" if not failures else ";".join(failures),
            }
        )
    return results


def _compatibility_checks(receipt: Mapping[str, Any]) -> set[str]:
    rows = [row for row in receipt.get("compatibility_checks") or () if isinstance(row, Mapping)]
    return {str(row.get("check")) for row in rows if isinstance(row.get("check"), str)}


def _validate_receipt_against_shape(
    receipt: Mapping[str, Any], shape: Mapping[str, Any]
) -> list[str]:
    reasons: list[str] = []
    for field in shape.get("required_top_level_fields") or ():
        if field not in receipt:
            reasons.append("main_adoption_receipt_shape_mismatch")
            break
    if receipt.get("decision") != shape.get("decision"):
        reasons.append("main_adoption_receipt_shape_mismatch")
    if receipt.get("adoption_scope") != shape.get("adoption_scope"):
        reasons.append("main_adoption_receipt_shape_mismatch")
    if receipt.get("evidence_context") != shape.get("evidence_context"):
        reasons.append("main_adoption_receipt_shape_mismatch")
    if receipt.get("fixture_only") != shape.get("fixture_only"):
        reasons.append("main_adoption_receipt_shape_mismatch")
    if receipt.get("production_use_authorized") != shape.get("production_use_authorized"):
        reasons.append("main_adoption_receipt_shape_mismatch")
    if receipt.get("required_capabilities_satisfied") != shape.get(
        "required_capabilities_satisfied"
    ):
        reasons.append("main_adoption_decision_incoherent")
    consumer = receipt.get("consumer") if isinstance(receipt.get("consumer"), Mapping) else {}
    if consumer.get("project") != shape.get("consumer_project"):
        reasons.append("main_adoption_receipt_shape_mismatch")
    required_checks = set(shape.get("required_compatibility_checks") or ())
    if _compatibility_checks(receipt) != required_checks:
        reasons.append("main_adoption_receipt_shape_mismatch")

    decisions = [
        row for row in receipt.get("capability_decisions") or () if isinstance(row, Mapping)
    ]
    required_rows = [row for row in decisions if row.get("requirement_class") == "required"]
    optional_rows = [row for row in decisions if row.get("requirement_class") == "optional"]
    rules = (
        shape.get("capability_decision_rules")
        if isinstance(shape.get("capability_decision_rules"), Mapping)
        else {}
    )
    if rules.get("required_must_all_be") == "accepted" and any(
        row.get("decision") != "accepted" for row in required_rows
    ):
        reasons.append("main_adoption_decision_incoherent")
    if rules.get("optional_must_all_be") == "accepted" and any(
        row.get("decision") != "accepted" for row in optional_rows
    ):
        reasons.append("main_adoption_decision_incoherent")
    if rules.get("required_must_include_rejected") is True and not any(
        row.get("decision") == "rejected" for row in required_rows
    ):
        reasons.append("main_adoption_decision_incoherent")
    if rules.get("optional_must_include_rejected") is True and not any(
        row.get("decision") == "rejected" for row in optional_rows
    ):
        reasons.append("main_adoption_decision_incoherent")
    if rules.get("accepted_capabilities_must_be_empty_when_required_fail") is True and receipt.get(
        "accepted_capabilities"
    ):
        reasons.append("main_adoption_decision_incoherent")
    if receipt.get("decision") == "adopted" and receipt.get("fixture_only") is True:
        reasons.append("main_fabrication_claim_forbidden")
    return sorted(set(reasons))


def _validate_adapter_observation(observation: Mapping[str, Any], *, decided_at: str) -> list[str]:
    evidence = build_external_adapter_conformance_evidence(observation, decided_at=decided_at)
    if evidence.get("status") != "accepted":
        return ["main_adapter_observation_rejected"]
    return []


def _validate_requirements_bundle(bundle: Mapping[str, Any]) -> list[str]:
    requirements = bundle.get("requirements")
    offers = bundle.get("offered_capabilities")
    trusted = bundle.get("trusted_signing_keys")
    observed_at = bundle.get("observed_at", "2026-07-17T00:01:00Z")
    if (
        not isinstance(requirements, Mapping)
        or not isinstance(offers, list)
        or not isinstance(trusted, Mapping)
    ):
        return ["main_requirements_capability_disagreement"]
    admission = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_consumer_requirements_admission",
        "requirements": requirements,
        "offered_capabilities": offers,
    }
    decision, _issues = evaluate_consumer_requirements_admission(
        admission,
        trusted_signing_keys=trusted,
        observed_at=str(observed_at),
        replay_ledger={},
    )
    expected = bundle.get("expected_status")
    if expected is not None and decision.get("status") != expected:
        return ["main_requirements_capability_disagreement"]
    return []


def run_main_consumer_conformance_harness(
    *,
    decided_at: str = "2026-07-19T12:00:00Z",
    main_artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Validate pinned packs always; validate Main artifacts only when present."""
    policy = _policy()
    pack = load_fixture_pack(policy)
    reasons = list(pack["reasons"])
    artifact_results: list[dict[str, str]] = []
    disagreement_results = evaluate_disagreement_vectors(pack=pack)
    if any(row["status"] != "passed" for row in disagreement_results):
        reasons.append("disagreement_vector_drift")

    inbox = _inbox_root(policy, main_artifact_root)
    names = policy.get("main_supplied_artifact_names") or {}
    receipt_name = str(names.get("adoption_receipt", "adoption_receipt.json"))
    observation_name = str(names.get("adapter_observation", "adapter_observation.json"))
    bundle_name = str(
        names.get("requirements_capability_bundle", "requirements_capability_bundle.json")
    )

    receipt_path = inbox / receipt_name
    observation_path = inbox / observation_name
    bundle_path = inbox / bundle_name
    present = any(path.is_file() for path in (receipt_path, observation_path, bundle_path))

    if pack["status"] != "ready":
        harness_status = "rejected"
    elif not present:
        reasons.append("main_artifact_missing")
        harness_status = "awaiting_main"
        for artifact in (
            "adoption_receipt",
            "adapter_observation",
            "requirements_capability_bundle",
        ):
            artifact_results.append(
                {
                    "artifact": artifact,
                    "status": "missing_external_main_evidence",
                    "detail": "Main has not supplied this artifact under the MaskFactory inbox",
                }
            )
    else:
        if receipt_path.is_file():
            receipt = _load_json(receipt_path)
            decision = str(receipt.get("decision") or "")
            try:
                shape = load_receipt_shape(decision, pack=pack)
            except MainConsumerConformanceError:
                reasons.append("main_adoption_receipt_shape_mismatch")
                artifact_results.append(
                    {
                        "artifact": "adoption_receipt",
                        "status": "failed",
                        "detail": f"no pinned shape for decision={decision!r}",
                    }
                )
            else:
                shape_reasons = _validate_receipt_against_shape(receipt, shape)
                reasons.extend(shape_reasons)
                artifact_results.append(
                    {
                        "artifact": "adoption_receipt",
                        "status": "met" if not shape_reasons else "failed",
                        "detail": (
                            "matches pinned shape" if not shape_reasons else ",".join(shape_reasons)
                        ),
                    }
                )
        else:
            reasons.append("main_artifact_missing")
            artifact_results.append(
                {
                    "artifact": "adoption_receipt",
                    "status": "missing_external_main_evidence",
                    "detail": f"missing {receipt_name}",
                }
            )

        if observation_path.is_file():
            observation = _load_json(observation_path)
            observation_reasons = _validate_adapter_observation(observation, decided_at=decided_at)
            reasons.extend(observation_reasons)
            artifact_results.append(
                {
                    "artifact": "adapter_observation",
                    "status": "met" if not observation_reasons else "failed",
                    "detail": (
                        "adapter conformance accepted"
                        if not observation_reasons
                        else ",".join(observation_reasons)
                    ),
                }
            )
        else:
            reasons.append("main_artifact_missing")
            artifact_results.append(
                {
                    "artifact": "adapter_observation",
                    "status": "missing_external_main_evidence",
                    "detail": f"missing {observation_name}",
                }
            )

        if bundle_path.is_file():
            bundle = _load_json(bundle_path)
            bundle_reasons = _validate_requirements_bundle(bundle)
            reasons.extend(bundle_reasons)
            artifact_results.append(
                {
                    "artifact": "requirements_capability_bundle",
                    "status": "met" if not bundle_reasons else "failed",
                    "detail": (
                        "requirements/capability bundle coherent"
                        if not bundle_reasons
                        else ",".join(bundle_reasons)
                    ),
                }
            )
        else:
            artifact_results.append(
                {
                    "artifact": "requirements_capability_bundle",
                    "status": "not_applicable",
                    "detail": "optional Main bundle absent",
                }
            )

        harness_status = "accepted" if not reasons else "rejected"

    if harness_status == "awaiting_main" and "disagreement_vector_drift" in reasons:
        harness_status = "rejected"
    if harness_status == "accepted" and reasons:
        harness_status = "rejected"

    ordered_reasons = (
        ["eligible"] if harness_status == "accepted" and not reasons else _ordered(policy, reasons)
    )

    # Producer fixtures alone can never claim Main adoption complete.
    evidence = {
        "schema_version": "1.0.0",
        "record_type": "main_consumer_conformance_evidence",
        "decided_at": decided_at,
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "pack_id": pack["manifest"].get("pack_id", "unavailable"),
        "pack_manifest_sha256": pack["manifest"].get("manifest_sha256", "0" * 64),
        "fixture_pack_status": (
            pack["status"] if pack["status"] in {"ready", "invalid"} else "invalid"
        ),
        "main_artifacts_present": present,
        "main_adoption_complete": False,
        "artifact_results": sorted(artifact_results, key=lambda row: row["artifact"]),
        "disagreement_vector_results": sorted(
            disagreement_results, key=lambda row: row["vector_id"]
        ),
        "status": harness_status,
        "rejection_reasons": ordered_reasons,
        "claim_boundary": {
            "producer_fixture_pack_is_not_main_adoption": True,
            "fabricated_main_adoption_rejected": True,
            "main_must_supply_runtime_artifacts": True,
        },
        "decision_sha256": "",
    }
    evidence["decision_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("decision_sha256",)
    )
    return evidence


def validate_main_consumer_conformance_evidence(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate harness evidence schema, policy binding, and claim boundary."""
    try:
        policy = _policy()
    except MainConsumerConformanceError as exc:
        return (str(exc),)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    issues = [
        f"schema:{error.validator}"
        for error in Draft202012Validator(schema).iter_errors(dict(evidence))
    ]
    if (
        evidence.get("policy_id") != policy["policy_id"]
        or evidence.get("policy_sha256") != policy["policy_sha256"]
    ):
        issues.append("policy_drift")
    if evidence.get("main_adoption_complete") is not False:
        issues.append("main_fabrication_claim_forbidden")
    claim = (
        evidence.get("claim_boundary")
        if isinstance(evidence.get("claim_boundary"), Mapping)
        else {}
    )
    if claim.get("producer_fixture_pack_is_not_main_adoption") is not True:
        issues.append("main_fabrication_claim_forbidden")
    allowed = set(policy.get("reason_codes") or ())
    if not set(evidence.get("rejection_reasons") or ()).issubset(allowed):
        issues.append("decision_reason_code")
    if evidence.get("status") not in set(policy.get("harness_statuses") or ()):
        issues.append("decision_status_reasons")
    expected = canonical_document_sha256(evidence, excluded_top_level_fields=("decision_sha256",))
    if evidence.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")
    return tuple(sorted(set(issues)))


def load_golden_vectors() -> dict[str, Any]:
    """Load governance golden vectors for the Main-consumer conformance pack."""
    return _load_json(GOLDEN_VECTORS_PATH)


__all__ = [
    "MainConsumerConformanceError",
    "evaluate_disagreement_vectors",
    "load_adapter_observation_template",
    "load_disagreement_vectors",
    "load_fixture_pack",
    "load_golden_vectors",
    "load_receipt_shape",
    "run_main_consumer_conformance_harness",
    "validate_main_consumer_conformance_evidence",
]
