"""Producer final release + Main adoption/handoff validation (MF-P6-12.06).

Additive producer-side oracle that:
- validates a final MaskFactory release snapshot/publication observation
- validates Main adoption/handoff receipts and reciprocal acknowledgement bindings
- regenerates claim-safe completion-profile status inputs from tracker item state
- refuses ``core_autonomous_runtime`` close authorization without every exact gate
- reports ``incomplete_core`` honestly when Main adoption evidence is missing

This module does not publish a production release, impersonate Main adoption,
mutate tracker/Plan reports, or close any completion profile.
"""

from __future__ import annotations

import json
import runpy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from maskfactory.bridge.adoption_receipt_matrix import (
    build_adoption_receipt_matrix_decision,
)
from maskfactory.validation import canonical_document_sha256

POLICY_PATH = Path(__file__).parents[3] / "configs" / "bridge_final_release_handoff_policy.yaml"
SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "bridge_final_release_handoff_evidence.schema.json"
)
TRACKER_SOURCE = Path(__file__).parents[3] / "Plan" / "Tracker" / "tracker.py"
TRACKER_JSON = Path(__file__).parents[3] / "Plan" / "Tracker" / "tracker.json"
POLICY_ID = "maskfactory-bridge-final-release-handoff-v1"
PROFILE_IDS = (
    "core_autonomous_runtime",
    "independent_real_accuracy",
    "scale_daz_maturity",
)
EXTERNAL_MAIN_DEPENDENCIES = (
    "main_production_adoption_receipt",
    "main_installed_runtime_identities",
    "main_compatibility_vertical_slice_evidence",
    "main_qualification_bundle_runtime_evidence",
)


class FinalReleaseHandoffError(ValueError):
    """Raised when final-release handoff policy or inputs are unusable."""


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FinalReleaseHandoffError("final release handoff policy unavailable") from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise FinalReleaseHandoffError("unexpected final release handoff policy")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise FinalReleaseHandoffError("final release handoff policy hash mismatch")
    gates = policy.get("exact_core_close_gates")
    codes = policy.get("rejection_reason_codes")
    if (
        not isinstance(gates, list)
        or not gates
        or len(gates) != len(set(gates))
        or not isinstance(codes, list)
        or len(codes) != len(set(codes))
    ):
        raise FinalReleaseHandoffError("final release handoff policy is not closed")
    return dict(policy)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sha(value: object) -> str | None:
    if (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    ):
        return value
    return None


def _commit(value: object) -> str | None:
    if (
        isinstance(value, str)
        and len(value) == 40
        and all(ch in "0123456789abcdef" for ch in value)
    ):
        return value
    return None


def _ordered(policy: Mapping[str, Any], reasons: set[str]) -> list[str]:
    ordered = [code for code in policy["rejection_reason_codes"] if code in reasons]
    return ordered or ["eligible"]


def _gate(gate_id: str, *, status: str, detail: str) -> dict[str, Any]:
    return {"gate_id": gate_id, "status": status, "detail": detail}


def _prerequisite(name: str, *, present: bool, passed: bool, detail: str) -> dict[str, Any]:
    status = (
        "met"
        if present and passed
        else ("missing_external_main_evidence" if not present else "failed")
    )
    return {"prerequisite": name, "status": status, "detail": detail}


def _tracker_module() -> dict[str, Any]:
    return runpy.run_path(str(TRACKER_SOURCE))


def load_tracker_data(path: Path | None = None) -> dict[str, Any]:
    """Load tracker JSON without mutating Plan/tracker reports."""
    target = path or TRACKER_JSON
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FinalReleaseHandoffError(f"tracker data unavailable: {target}") from exc
    if not isinstance(data, Mapping) or not isinstance(data.get("items"), Mapping):
        raise FinalReleaseHandoffError("tracker data missing items map")
    return dict(data)


def regenerate_profile_status_inputs(
    tracker_data: Mapping[str, Any],
    *,
    core_close_authorized: bool,
) -> dict[str, Any]:
    """Recompute claim-safe profile status inputs from item statuses only."""
    module = _tracker_module()
    compute = module["compute_completion_profile_status"]
    closure = module["completion_profile_dependency_closure"]
    profiles_meta = module["COMPLETION_PROFILES"]
    items = tracker_data.get("items")
    if not isinstance(items, Mapping):
        raise FinalReleaseHandoffError("tracker items map required")

    status_map = {
        item_id: {
            "status": (row or {}).get("status"),
            "orphaned": bool((row or {}).get("orphaned")),
            "conditional": bool((row or {}).get("conditional")),
        }
        for item_id, row in items.items()
        if isinstance(item_id, str)
    }
    tracker_items_sha256 = canonical_document_sha256(status_map)
    profiles: dict[str, Any] = {}
    for profile_id in PROFILE_IDS:
        status = compute(tracker_data, profile_id)
        open_ids = sorted(
            item_id
            for item_id in closure(tracker_data, profile_id)
            if (items.get(item_id) or {}).get("status") != "complete"
            or bool((items.get(item_id) or {}).get("orphaned"))
        )
        classification = profiles_meta[profile_id]["classification"]
        profiles[profile_id] = {
            "profile_id": profile_id,
            "classification": classification,
            "status": status,
            "open_driving_item_count": len(open_ids),
            "open_driving_item_ids": open_ids,
            "close_authorized": bool(
                profile_id == "core_autonomous_runtime"
                and core_close_authorized
                and status == "complete"
            ),
        }

    return {
        "tracker_items_sha256": tracker_items_sha256,
        "profiles": profiles,
        "independence_proof": {
            "optional_failure_cannot_revoke_core": True,
            "core_close_requires_exact_gates": True,
            "optional_statuses_computed_independently": True,
        },
        "core_close_refused": not (
            core_close_authorized and profiles["core_autonomous_runtime"]["status"] == "complete"
        ),
    }


def evaluate_final_release_handoff(
    *,
    release_snapshot: Mapping[str, Any] | None = None,
    release_publication_issues: Sequence[Any] | None = None,
    adoption_receipt: Mapping[str, Any] | None = None,
    reciprocal_acknowledgement: Mapping[str, Any] | None = None,
    qualification_bundle: Mapping[str, Any] | None = None,
    tracker_data: Mapping[str, Any] | None = None,
    producer_git_commit: str | None = None,
    consumer_git_commit: str | None = None,
    at_time: str | None = None,
    adoption_matrix_decision: Mapping[str, Any] | None = None,
    claim_firewall_ok: bool = True,
    fabricated_core_complete_claim: bool = False,
    decided_at: str | None = None,
) -> dict[str, Any]:
    """Evaluate final release + adoption handoff and regenerate profile inputs."""
    policy = _policy()
    reasons: set[str] = set()
    gates: list[dict[str, Any]] = []
    decided = decided_at or _utc_now()
    decision_time = at_time or decided

    release = _mapping(release_snapshot)
    release_present = bool(release)
    release_id = release.get("release_id") if isinstance(release.get("release_id"), str) else None
    release_hash = _sha(release.get("release_payload_sha256"))
    release_status = (
        release.get("release_status") if isinstance(release.get("release_status"), str) else None
    )
    release_fixture = release.get("fixture_only") if "fixture_only" in release else None
    producer_from_release = _commit(
        _mapping(release.get("producer")).get("git_commit")
        or _mapping(release.get("producer")).get("commit")
        or release.get("producer_git_commit")
    )
    publication_issue_count = (
        len(tuple(release_publication_issues)) if release_publication_issues is not None else 0
    )
    if not release_present:
        reasons.add("final_producer_release_missing")
        gates.append(
            _gate(
                "final_producer_release_published",
                status="missing",
                detail="no producer release snapshot supplied",
            )
        )
    else:
        if release_status != "published":
            reasons.add("final_producer_release_not_published")
        if release_fixture is not False:
            reasons.add("final_producer_release_fixture_only")
        if release_publication_issues is None or publication_issue_count:
            reasons.add("release_publication_validation_failed")
        release_ok = (
            release_status == "published"
            and release_fixture is False
            and release_publication_issues is not None
            and publication_issue_count == 0
            and release_id is not None
            and release_hash is not None
        )
        gates.append(
            _gate(
                "final_producer_release_published",
                status="met" if release_ok else "failed",
                detail=(
                    "published non-fixture release with clean publication validation"
                    if release_ok
                    else "release missing published/non-fixture/clean-publication evidence"
                ),
            )
        )

    adoption = _mapping(adoption_receipt)
    adoption_present = bool(adoption)
    adoption_id = (
        adoption.get("adoption_id") if isinstance(adoption.get("adoption_id"), str) else None
    )
    adoption_hash = _sha(adoption.get("adoption_payload_sha256"))
    adoption_scope = (
        adoption.get("adoption_scope") if isinstance(adoption.get("adoption_scope"), str) else None
    )
    adoption_decision = (
        adoption.get("decision") if isinstance(adoption.get("decision"), str) else None
    )
    production_authorized = (
        adoption.get("production_use_authorized")
        if isinstance(adoption.get("production_use_authorized"), bool)
        else None
    )
    adoption_fixture = adoption.get("fixture_only") if "fixture_only" in adoption else None
    consumer_from_adoption = _commit(_mapping(adoption.get("consumer")).get("git_commit"))

    matrix_status: str | None = None
    if not adoption_present:
        reasons.add("main_adoption_receipt_missing")
        gates.append(
            _gate(
                "main_adoption_receipt_present",
                status="missing",
                detail="Main adoption receipt absent; core remains incomplete",
            )
        )
        gates.append(
            _gate(
                "adoption_release_hash_pin",
                status="missing",
                detail="cannot pin adoption to release without Main receipt",
            )
        )
    else:
        if adoption_scope != "production_authority" or adoption_fixture is not False:
            reasons.add("main_adoption_not_production_authority")
        if (
            adoption_decision not in {"adopted", "partially_adopted"}
            or production_authorized is not True
        ):
            reasons.add("main_adoption_decision_not_authorizing")
        adoption_present_ok = (
            adoption_scope == "production_authority"
            and adoption_fixture is False
            and adoption_decision in {"adopted", "partially_adopted"}
            and production_authorized is True
            and adoption_id is not None
            and adoption_hash is not None
        )
        gates.append(
            _gate(
                "main_adoption_receipt_present",
                status="met" if adoption_present_ok else "failed",
                detail=(
                    "production-authority authorizing adoption present"
                    if adoption_present_ok
                    else "adoption is not production-authority authorizing evidence"
                ),
            )
        )
        release_pin_ok = (
            release_present
            and adoption.get("release_id") == release_id
            and _sha(adoption.get("release_payload_sha256")) == release_hash
            and release_id is not None
            and release_hash is not None
        )
        if not release_pin_ok:
            reasons.add("adoption_release_hash_pin_mismatch")
        gates.append(
            _gate(
                "adoption_release_hash_pin",
                status="met" if release_pin_ok else "failed",
                detail=(
                    "adoption binds exact release_id and release_payload_sha256"
                    if release_pin_ok
                    else "adoption/release identity pin mismatch or incomplete"
                ),
            )
        )
        if adoption_matrix_decision is None:
            matrix = build_adoption_receipt_matrix_decision(
                adoption,
                at_time=decision_time,
                qualification_bundle=qualification_bundle,
                release_publication_issues=(
                    []
                    if release_publication_issues is not None and publication_issue_count == 0
                    else None
                ),
            )
        else:
            matrix = _mapping(adoption_matrix_decision)
        matrix_status = (
            matrix.get("status") if isinstance(matrix.get("status"), str) else "rejected"
        )
        if matrix_status != "accepted":
            # Matrix rejection is additive evidence; do not fabricate Main authority.
            if "external_main_qualification_bundle_required" in set(
                matrix.get("rejection_reasons") or ()
            ):
                reasons.add("qualification_bundle_missing")
            if not adoption_present_ok:
                pass
            elif "eligible" not in set(matrix.get("rejection_reasons") or ()):
                reasons.add("main_adoption_decision_not_authorizing")

    ack = _mapping(reciprocal_acknowledgement)
    ack_present = bool(ack)
    ack_id = (
        ack.get("acknowledgement_id") if isinstance(ack.get("acknowledgement_id"), str) else None
    )
    ack_adoption_id = ack.get("adoption_id") if isinstance(ack.get("adoption_id"), str) else None
    ack_adoption_hash = _sha(ack.get("adoption_payload_sha256"))
    invalidation_head = _sha(ack.get("invalidation_head_sha256"))
    rollback_target = _sha(ack.get("rollback_target_sha256"))
    if not ack_present:
        reasons.add("reciprocal_producer_acknowledgement_missing")
        binding_ok = False
        gates.append(
            _gate(
                "reciprocal_producer_acknowledgement",
                status="missing",
                detail="reciprocal producer acknowledgement absent",
            )
        )
    else:
        binding_ok = (
            adoption_present
            and ack_adoption_id == adoption_id
            and ack_adoption_hash == adoption_hash
            and invalidation_head is not None
            and rollback_target is not None
            and ack_id is not None
        )
        if not binding_ok:
            reasons.add("reciprocal_acknowledgement_binding_failed")
        gates.append(
            _gate(
                "reciprocal_producer_acknowledgement",
                status="met" if binding_ok else "failed",
                detail=(
                    "acknowledgement binds adoption, invalidation head, and rollback target"
                    if binding_ok
                    else "acknowledgement binding incomplete or mismatched"
                ),
            )
        )

    producer_pin = (
        _commit(producer_git_commit)
        or producer_from_release
        or _commit(ack.get("producer_git_commit"))
    )
    consumer_pin = (
        _commit(consumer_git_commit)
        or consumer_from_adoption
        or _commit(ack.get("consumer_git_commit"))
    )
    producer_pin_matches = bool(producer_pin) and (
        producer_from_release is None or producer_pin == producer_from_release
    )
    consumer_pin_matches = bool(consumer_pin) and (
        consumer_from_adoption is None or consumer_pin == consumer_from_adoption
    )
    both_pinned = bool(
        producer_pin and consumer_pin and producer_pin_matches and consumer_pin_matches
    )
    if not both_pinned:
        reasons.add("producer_consumer_commit_pin_mismatch")
    gates.append(
        _gate(
            "producer_consumer_commit_pin_match",
            status=(
                "met"
                if both_pinned
                else ("missing" if not (producer_pin or consumer_pin) else "failed")
            ),
            detail=(
                "producer and consumer commits pinned and consistent with release/adoption"
                if both_pinned
                else "producer/consumer commit pins missing or inconsistent"
            ),
        )
    )

    qualification = _mapping(qualification_bundle)
    qualification_present = bool(qualification)
    qualification_id = (
        qualification.get("qualification_id")
        if isinstance(qualification.get("qualification_id"), str)
        else None
    )
    qualification_hash = _sha(qualification.get("qualification_payload_sha256"))
    qualification_fixture = (
        qualification.get("fixture_only") if "fixture_only" in qualification else None
    )
    bound_to_adoption = False
    if not qualification_present:
        reasons.add("qualification_bundle_missing")
        gates.append(
            _gate(
                "qualification_bundle_bound",
                status="missing",
                detail="cross-project qualification bundle absent",
            )
        )
    else:
        bound_to_adoption = (
            adoption_present
            and adoption.get("qualification_bundle_id") == qualification_id
            and _sha(adoption.get("qualification_bundle_sha256")) == qualification_hash
            and qualification_id is not None
            and qualification_hash is not None
            and qualification_fixture is False
        )
        if not bound_to_adoption:
            reasons.add("qualification_bundle_binding_failed")
        gates.append(
            _gate(
                "qualification_bundle_bound",
                status="met" if bound_to_adoption else "failed",
                detail=(
                    "adoption binds non-fixture executed qualification bundle"
                    if bound_to_adoption
                    else "qualification bundle missing, fixture-only, or not bound by adoption"
                ),
            )
        )

    data = dict(tracker_data) if isinstance(tracker_data, Mapping) else load_tracker_data()
    # Provisional profile inputs with close unauthorized; recompute after gate set.
    provisional = regenerate_profile_status_inputs(data, core_close_authorized=False)
    core_status = provisional["profiles"]["core_autonomous_runtime"]["status"]
    core_complete = core_status == "complete"
    if not core_complete:
        reasons.add("core_profile_dependency_closure_incomplete")
    gates.append(
        _gate(
            "core_profile_dependency_closure_complete",
            status="met" if core_complete else "failed",
            detail=(
                "core dependency closure recomputed complete"
                if core_complete
                else f"core dependency closure status={core_status} with "
                f"{provisional['profiles']['core_autonomous_runtime']['open_driving_item_count']} open items"
            ),
        )
    )

    optional_core = provisional["profiles"]["core_autonomous_runtime"]["status"]
    optional_acc = provisional["profiles"]["independent_real_accuracy"]["status"]
    optional_scale = provisional["profiles"]["scale_daz_maturity"]["status"]
    independence_ok = (
        optional_core in {"complete", "blocked", "in_progress", "open", "waiting_for_prerequisite"}
        and optional_acc
        in {
            "complete",
            "blocked",
            "in_progress",
            "open",
            "waiting_for_prerequisite",
            "error(missing item id)",
        }
        and optional_scale
        in {
            "complete",
            "blocked",
            "in_progress",
            "open",
            "waiting_for_prerequisite",
            "error(missing item id)",
        }
        and provisional["independence_proof"]["optional_failure_cannot_revoke_core"] is True
    )
    # Optional incomplete must never be used to force core complete, and core
    # incomplete must remain visible even if optional profiles are complete.
    if optional_acc == "complete" and not core_complete and fabricated_core_complete_claim:
        independence_ok = False
        reasons.add("optional_profile_independence_violated")
    if not independence_ok:
        reasons.add("optional_profile_independence_violated")
    gates.append(
        _gate(
            "optional_profiles_remain_independent",
            status="met" if independence_ok else "failed",
            detail=(
                "optional profiles computed independently and cannot revoke/force core"
                if independence_ok
                else "optional/core independence invariant failed"
            ),
        )
    )

    if not claim_firewall_ok:
        reasons.add("claim_firewall_violated")
    gates.append(
        _gate(
            "claim_firewall_intact",
            status="met" if claim_firewall_ok else "failed",
            detail=(
                "operational handoff evidence does not claim independent real accuracy"
                if claim_firewall_ok
                else "claim firewall violation observed"
            ),
        )
    )

    if fabricated_core_complete_claim:
        reasons.add("fabricated_core_complete_claim")

    gate_by_id = {row["gate_id"]: row for row in gates}
    all_gates_met = all(
        gate_by_id[gid]["status"] == "met" for gid in policy["exact_core_close_gates"]
    )
    residual = {code for code in reasons if code != "eligible"}
    close_authorized = all_gates_met and not residual and not fabricated_core_complete_claim

    if not close_authorized:
        reasons.add("core_close_refused_without_exact_gates")

    profile_inputs = regenerate_profile_status_inputs(data, core_close_authorized=close_authorized)

    if close_authorized:
        status = "accepted"
        reasons = {"eligible"}
    elif fabricated_core_complete_claim:
        status = "rejected"
    else:
        # Prefer honest incomplete-core when Main adoption or any exact gate is unmet.
        status = "incomplete_core"

    external = [
        _prerequisite(
            "main_production_adoption_receipt",
            present=adoption_present,
            passed=gate_by_id["main_adoption_receipt_present"]["status"] == "met",
            detail="requires Main-signed production-authority adoption receipt",
        ),
        _prerequisite(
            "main_installed_runtime_identities",
            present=bool(consumer_pin),
            passed=bool(consumer_pin_matches and consumer_pin),
            detail="requires Main installed controller/runtime git identity pin",
        ),
        _prerequisite(
            "main_compatibility_vertical_slice_evidence",
            present=ack_present,
            passed=binding_ok,
            detail="requires reciprocal acknowledgement binding rollback/invalidation evidence",
        ),
        _prerequisite(
            "main_qualification_bundle_runtime_evidence",
            present=qualification_present,
            passed=bound_to_adoption,
            detail="requires non-fixture executed qualification bundle bound by adoption",
        ),
    ]

    evidence = {
        "schema_version": "1.0.0",
        "record_type": "bridge_final_release_handoff_evidence",
        "decided_at": decided,
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "status": status,
        "rejection_reasons": _ordered(policy, reasons),
        "core_autonomous_runtime_close_authorized": close_authorized,
        "exact_core_close_gates": [gate_by_id[gid] for gid in policy["exact_core_close_gates"]],
        "release_validation": {
            "present": release_present,
            "release_id": release_id,
            "release_payload_sha256": release_hash,
            "release_status": release_status,
            "fixture_only": release_fixture if isinstance(release_fixture, bool) else None,
            "publication_issue_count": publication_issue_count,
            "producer_git_commit": producer_from_release,
        },
        "adoption_validation": {
            "present": adoption_present,
            "adoption_id": adoption_id,
            "adoption_payload_sha256": adoption_hash,
            "adoption_scope": adoption_scope,
            "decision": adoption_decision,
            "production_use_authorized": production_authorized,
            "fixture_only": adoption_fixture if isinstance(adoption_fixture, bool) else None,
            "consumer_git_commit": consumer_from_adoption,
            "matrix_status": matrix_status if adoption_present else "not_evaluated",
        },
        "reciprocal_acknowledgement": {
            "present": ack_present,
            "acknowledgement_id": ack_id,
            "adoption_id": ack_adoption_id,
            "adoption_payload_sha256": ack_adoption_hash,
            "invalidation_head_sha256": invalidation_head,
            "rollback_target_sha256": rollback_target,
            "binding_ok": binding_ok,
        },
        "commit_pins": {
            "producer_git_commit": producer_pin,
            "consumer_git_commit": consumer_pin,
            "producer_pin_matches_release": producer_pin_matches,
            "consumer_pin_matches_adoption": consumer_pin_matches,
            "both_projects_pinned": both_pinned,
        },
        "qualification_binding": {
            "present": qualification_present,
            "qualification_id": qualification_id,
            "qualification_payload_sha256": qualification_hash,
            "bound_to_adoption": bound_to_adoption,
            "fixture_only": (
                qualification_fixture if isinstance(qualification_fixture, bool) else None
            ),
        },
        "profile_status_inputs": profile_inputs,
        "external_main_prerequisites": external,
        "claim_boundary": {
            "establishes_handoff_validation_only": True,
            "may_close_core_without_exact_gates": False,
            "may_impersonate_main_adoption": False,
            "may_mutate_optional_profiles": False,
            "core_closed": False,
            "optional_profile_status_changed": False,
        },
        "decision_sha256": "",
    }
    evidence["decision_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("decision_sha256",)
    )
    return evidence


def validate_final_release_handoff_evidence(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate evidence schema, policy binding, hash, and close-authorization invariants."""
    try:
        policy = _policy()
    except FinalReleaseHandoffError as exc:
        return (str(exc),)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    issues = [
        f"schema:{error.validator}"
        for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            dict(evidence)
        )
    ]
    if (
        evidence.get("policy_id") != policy["policy_id"]
        or evidence.get("policy_sha256") != policy["policy_sha256"]
    ):
        issues.append("policy_drift")
    allowed = set(policy["rejection_reason_codes"])
    if not set(evidence.get("rejection_reasons") or ()).issubset(allowed):
        issues.append("reason_code_drift")
    expected = canonical_document_sha256(evidence, excluded_top_level_fields=("decision_sha256",))
    if evidence.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")
    close_authorized = evidence.get("core_autonomous_runtime_close_authorized") is True
    reasons = list(evidence.get("rejection_reasons") or ())
    if close_authorized and (evidence.get("status") != "accepted" or reasons != ["eligible"]):
        issues.append("close_authorization_inconsistent")
    if not close_authorized and "core_close_refused_without_exact_gates" not in reasons:
        issues.append("missing_core_close_refusal")
    if evidence.get("claim_boundary", {}).get("core_closed") is True:
        issues.append("oracle_must_not_close_core")
    gate_ids = [row.get("gate_id") for row in evidence.get("exact_core_close_gates") or ()]
    if gate_ids != list(policy["exact_core_close_gates"]):
        issues.append("gate_set_drift")
    return tuple(sorted(set(issues)))


__all__ = [
    "EXTERNAL_MAIN_DEPENDENCIES",
    "POLICY_ID",
    "FinalReleaseHandoffError",
    "evaluate_final_release_handoff",
    "load_tracker_data",
    "regenerate_profile_status_inputs",
    "validate_final_release_handoff_evidence",
]
