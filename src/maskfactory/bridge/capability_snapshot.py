"""Fail-closed qualification for a release-bound capability snapshot.

The frozen snapshot is a declaration.  This additive boundary resolves the
declaration against supplied immutable bytes and independently produced
evidence before exposing any route as qualified.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from maskfactory.bridge.clean_release_packaging import argv_has_editable_or_source
from maskfactory.validation import canonical_document_sha256

POLICY_PATH = Path(__file__).parents[3] / "configs" / "bridge_capability_snapshot_policy.yaml"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "maskfactory_capability_decision.schema.json"
POLICY_ID = "maskfactory-bridge-capability-qualification-v1"


class CapabilityQualificationError(ValueError):
    """Raised when the local qualification policy cannot be trusted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _policy() -> dict[str, Any]:
    try:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityQualificationError(
            "capability qualification policy is unavailable"
        ) from exc
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_id") != POLICY_ID or policy.get("policy_sha256") != expected:
        raise CapabilityQualificationError("capability qualification policy hash mismatch")
    return policy


def _canonical_stack(stack: Mapping[str, Any]) -> str:
    value = dict(stack)
    value.pop("stack_sha256", None)
    return canonical_document_sha256(value)


def _decode_document(raw: object) -> Mapping[str, Any] | None:
    if not isinstance(raw, bytes):
        return None
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return document if isinstance(document, Mapping) else None


def _release_publication_policy_issues(document: Mapping[str, Any]) -> tuple[str, ...]:
    """Apply additive release packaging guardrails when publication bytes carry evidence."""
    if document.get("record_type") != "maskfactory_release_publication_evidence":
        return ()
    issues: list[str] = []
    repository = document.get("repository_observation")
    if isinstance(repository, Mapping) and repository.get("clean") is not True:
        issues.append("release_publication_dirty_source_authority")
    installation = document.get("installation")
    rollback = document.get("rollback")
    if isinstance(installation, Mapping) and argv_has_editable_or_source(installation.get("argv")):
        issues.append("release_publication_editable_install_forbidden")
    if isinstance(rollback, Mapping) and argv_has_editable_or_source(rollback.get("argv")):
        issues.append("release_publication_editable_rollback_forbidden")
    return tuple(sorted(set(issues)))


def _chain_head(entries: list[Mapping[str, Any]], issues: list[str]) -> str:
    previous = ""
    for entry in entries:
        declared = entry.get("entry_sha256")
        material = dict(entry)
        material.pop("entry_sha256", None)
        if not isinstance(declared, str) or declared != canonical_document_sha256(material):
            issues.append("ledger_entry_hash_drift")
        if entry.get("previous_entry_sha256") != previous:
            issues.append("ledger_chain_discontinuous")
        previous = declared if isinstance(declared, str) else ""
    return previous


def _certificate(
    certificate_id: object,
    stack: Mapping[str, Any],
    evidence: Mapping[str, Any],
    now: datetime,
    policy: Mapping[str, Any],
    issues: list[str],
) -> bool:
    certificates = evidence.get("certificate_bytes")
    raw = certificates.get(certificate_id) if isinstance(certificates, Mapping) else None
    document = _decode_document(raw)
    if document is None:
        issues.append("certificate_bytes_unresolved")
        return False
    if document.get("certificate_id") != certificate_id:
        issues.append("certificate_id_drift")
    authority = _decode_document(evidence.get("certificate_authority_bytes"))
    if authority is None:
        issues.append("certificate_authority_unresolved")
    else:
        expected_authority = authority.get("authority_sha256")
        if expected_authority != canonical_document_sha256(
            authority, excluded_top_level_fields=("authority_sha256",)
        ):
            issues.append("certificate_authority_hash_drift")
        signer_id = document.get("signer_id")
        if (
            authority.get("status") != "active"
            or not isinstance(authority.get("trusted_signer_ids"), list)
            or signer_id not in authority["trusted_signer_ids"]
        ):
            issues.append("certificate_signer_not_authorized")
    if document.get("payload_sha256") != canonical_document_sha256(
        document, excluded_top_level_fields=("payload_sha256", "signed_payload_sha256")
    ):
        issues.append("certificate_payload_hash_drift")
    if document.get("signed_payload_sha256") != document.get("payload_sha256"):
        issues.append("certificate_signature_binding_drift")
    if document.get("signer_role") != policy["required_certificate_role"]:
        issues.append("certificate_signer_not_trusted")
    if document.get("issuer_kind") != "independent_benchmark":
        issues.append("certificate_self_reported")
    if document.get("status") != "active":
        issues.append("certificate_not_active")
    if document.get("route_id") != (stack.get("route_key") or {}).get("route_key_id"):
        issues.append("certificate_route_scope_drift")
    if document.get("stack_sha256") != stack.get("stack_sha256"):
        issues.append("certificate_stack_scope_drift")
    if document.get("qualification_scope_sha256") != (stack.get("qualification_scope") or {}).get(
        "scope_sha256"
    ):
        issues.append("certificate_qualification_scope_drift")
    if (
        _timestamp(document.get("valid_from")) is None
        or _timestamp(document.get("valid_until")) is None
    ):
        issues.append("certificate_time_malformed")
    elif not (_timestamp(document["valid_from"]) <= now < _timestamp(document["valid_until"])):
        issues.append("certificate_expired")
    revocations = evidence.get("revocation_index")
    revoked = (
        revocations.get("revoked_certificate_ids", []) if isinstance(revocations, Mapping) else None
    )
    if not isinstance(revoked, list) or certificate_id in revoked:
        issues.append("certificate_revoked_or_index_unresolved")
    elif document.get("revocation_head_sha256") != canonical_document_sha256(revocations):
        issues.append("certificate_revocation_head_drift")
    return not issues


def _stack_bytes_resolve(
    stack: Mapping[str, Any], evidence: Mapping[str, Any], issues: list[str]
) -> None:
    artifacts = evidence.get("artifact_bytes")
    if not isinstance(artifacts, Mapping):
        issues.append("artifact_bytes_unresolved")
        return
    for artifact in stack.get("model_artifacts", []):
        if not isinstance(artifact, Mapping):
            issues.append("artifact_declaration_malformed")
            continue
        raw = artifacts.get(artifact.get("model_id"))
        if not isinstance(raw, bytes) or _sha256(raw) != artifact.get("sha256"):
            issues.append("model_artifact_bytes_drift")
    for key, declared in (
        ("workflow", (stack.get("workflow") or {}).get("sha256")),
        ("runtime_lock", (stack.get("runtime") or {}).get("environment_lock_sha256")),
        ("hardware_profile", (stack.get("hardware") or {}).get("hardware_profile_sha256")),
        ("route_key", (stack.get("route_key") or {}).get("sha256")),
    ):
        raw = artifacts.get(key)
        if not isinstance(raw, bytes) or _sha256(raw) != declared:
            issues.append(f"{key}_bytes_drift")


def _performance_is_independent(
    stack: Mapping[str, Any],
    entries: list[Mapping[str, Any]],
    now: datetime,
    policy: Mapping[str, Any],
) -> bool:
    route_id = (stack.get("route_key") or {}).get("route_key_id")
    valid: list[Mapping[str, Any]] = []
    maximum_age = int(policy["maximum_performance_age_seconds"])
    for entry in entries:
        observed_at = _timestamp(entry.get("observed_at"))
        if (
            entry.get("route_id") == route_id
            and entry.get("stack_sha256") == stack.get("stack_sha256")
            and entry.get("self_reported") is False
            and entry.get("independence") == "independent"
            and observed_at is not None
            and 0 <= (now - observed_at).total_seconds() <= maximum_age
        ):
            valid.append(entry)
    sources = {entry.get("evidence_source_id") for entry in valid}
    correlations = {entry.get("correlation_group") for entry in valid}
    minimum = int(policy["minimum_independent_evidence_sources"])
    return (
        len(sources) >= minimum
        and len(correlations) >= minimum
        and None not in sources | correlations
    )


def _route_record(stack: Mapping[str, Any], certificate_id: str | None = None) -> dict[str, Any]:
    return {
        "route_id": (stack.get("route_key") or {}).get("route_key_id", ""),
        "stack_id": stack.get("stack_id", ""),
        "stack_sha256": stack.get("stack_sha256", ""),
        "lifecycle": stack.get("lifecycle", "draft"),
        "certificate_id": certificate_id,
    }


def _close_route_branch_within_budget(
    evidence: Mapping[str, Any],
    policy: Mapping[str, Any],
    issues: list[str],
) -> None:
    """Fail closed when close-route branch tournaments exceed the frozen attempt budget."""
    branches = evidence.get("close_route_branches")
    if branches is None:
        return
    if not isinstance(branches, list):
        issues.append("close_route_branch_malformed")
        return
    margin = float(policy["close_route_score_margin"])
    maximum_attempts = int(policy["maximum_close_route_branch_attempts"])
    for branch in branches:
        if not isinstance(branch, Mapping):
            issues.append("close_route_branch_malformed")
            continue
        score_a = branch.get("score_a")
        score_b = branch.get("score_b")
        attempts = branch.get("branch_attempts")
        if not isinstance(score_a, (int, float)) or not isinstance(score_b, (int, float)):
            issues.append("close_route_branch_malformed")
            continue
        if abs(float(score_a) - float(score_b)) > margin:
            continue
        if not isinstance(attempts, int) or attempts < 1:
            issues.append("close_route_branch_malformed")
        elif attempts > maximum_attempts:
            issues.append("close_route_branch_budget_exceeded")


def restore_route_champion_from_rollback(
    decision: Mapping[str, Any],
    *,
    route_id: str,
) -> dict[str, Any]:
    """Restore the prior route champion from an accepted decision's rollback binding.

    This is a pure reconstruction helper. It never mutates the decision bytes and
    never claims Main/production adoption authority.
    """
    if decision.get("status") != "accepted":
        raise CapabilityQualificationError("rollback restore requires an accepted decision")
    bindings = [
        row
        for row in decision.get("rollback_bindings") or ()
        if isinstance(row, Mapping) and row.get("route_id") == route_id
    ]
    if len(bindings) != 1:
        raise CapabilityQualificationError("rollback binding for route is missing or ambiguous")
    binding = bindings[0]
    qualified = [
        row
        for row in decision.get("qualified_routes") or ()
        if isinstance(row, Mapping) and row.get("route_id") == route_id
    ]
    if len(qualified) != 1:
        raise CapabilityQualificationError("qualified route for rollback restore is missing")
    current = qualified[0]
    if current.get("stack_sha256") != binding.get("current_stack_sha256"):
        raise CapabilityQualificationError(
            "rollback current champion does not match qualified route"
        )
    restored = {
        "route_id": route_id,
        "previous_champion_stack_sha256": binding.get("current_stack_sha256"),
        "restored_champion_stack_sha256": binding.get("rollback_stack_sha256"),
        "tested_ledger_entry_sha256": binding.get("tested_ledger_entry_sha256"),
        "action": "restore_prior_route_champion",
    }
    restored["restore_sha256"] = canonical_document_sha256(
        restored, excluded_top_level_fields=("restore_sha256",)
    )
    return restored


def build_capability_decision(
    snapshot: Mapping[str, Any], evidence: Mapping[str, Any], *, decided_at: str
) -> dict[str, Any]:
    """Resolve a snapshot to evidence bytes and derive safe route eligibility.

    Evidence is deliberately caller-supplied and byte-oriented.  `artifact_bytes`
    maps every declared model plus workflow/runtime_lock/hardware_profile/route_key
    to actual bytes; `certificate_bytes` maps certificate ID to signed JSON bytes.
    A newcomer never becomes promoted solely because it appears in this input.
    """
    policy = _policy()
    issues: list[str] = []
    now = _timestamp(decided_at)
    if now is None:
        raise CapabilityQualificationError("decision time must be RFC3339")
    expected_snapshot = canonical_document_sha256(
        snapshot, excluded_top_level_fields=("snapshot_sha256",)
    )
    if snapshot.get("snapshot_sha256") != expected_snapshot:
        issues.append("snapshot_hash_drift")
    release = evidence.get("release_publication")
    if not isinstance(release, Mapping) or not isinstance(release.get("bytes"), bytes):
        issues.append("release_publication_unresolved")
        release = {}
    release_sha = _sha256(release["bytes"]) if isinstance(release.get("bytes"), bytes) else ""
    if release.get("sha256") != release_sha:
        issues.append("release_publication_bytes_drift")
    release_document = _decode_document(release.get("bytes"))
    if release_document is None and isinstance(release.get("bytes"), bytes):
        issues.append("release_publication_document_unresolved")
    elif isinstance(release_document, Mapping):
        issues.extend(_release_publication_policy_issues(release_document))
    revocation = evidence.get("revocation_index")
    if not isinstance(revocation, Mapping):
        issues.append("revocation_index_unresolved")
        revocation = {}
    revocation_head = canonical_document_sha256(revocation)
    entries = evidence.get("performance_ledger")
    if not isinstance(entries, list) or not all(isinstance(entry, Mapping) for entry in entries):
        issues.append("performance_ledger_unresolved")
        entries = []
    ledger_head = _chain_head(list(entries), issues)
    previous = evidence.get("previous_decision")
    previous_qualified = (
        {
            route.get("stack_sha256")
            for route in previous.get("qualified_routes", [])
            if isinstance(route, Mapping)
        }
        if isinstance(previous, Mapping)
        else set()
    )

    _close_route_branch_within_budget(evidence, policy, issues)

    qualified: list[dict[str, Any]] = []
    challengers: list[dict[str, Any]] = []
    rollback_bindings: list[dict[str, Any]] = []
    route_champions: set[str] = set()
    for stack in snapshot.get("provider_stacks", []):
        if not isinstance(stack, Mapping):
            issues.append("stack_declaration_malformed")
            continue
        stack_issues: list[str] = []
        if stack.get("stack_sha256") != _canonical_stack(stack):
            stack_issues.append("stack_hash_drift")
        _stack_bytes_resolve(stack, evidence, stack_issues)
        lifecycle = stack.get("lifecycle")
        certificate_ids = stack.get("certificate_ids")
        certificate_id = (
            certificate_ids[0] if isinstance(certificate_ids, list) and certificate_ids else None
        )
        record = _route_record(stack, certificate_id)
        if lifecycle != "promoted":
            challengers.append(record)
            continue
        if stack.get("stack_sha256") not in previous_qualified:
            stack_issues.append("newcomer_direct_promotion")
        if not isinstance(certificate_id, str) or not _certificate(
            certificate_id, stack, evidence, now, policy, stack_issues
        ):
            stack_issues.append("qualification_certificate_unresolved")
        if not _performance_is_independent(stack, list(entries), now, policy):
            stack_issues.append("performance_evidence_not_independent_or_fresh")
        route_id = record["route_id"]
        if not route_id or route_id in route_champions:
            stack_issues.append("route_champion_ambiguous")
        route_champions.add(route_id)
        rollback = (
            (evidence.get("rollback_state") or {}).get(route_id)
            if isinstance(evidence.get("rollback_state"), Mapping)
            else None
        )
        if (
            not isinstance(rollback, Mapping)
            or rollback.get("current_stack_sha256") != stack.get("stack_sha256")
            or rollback.get("rollback_stack_sha256") in {None, stack.get("stack_sha256")}
            or rollback.get("tested_ledger_entry_sha256")
            not in {entry.get("entry_sha256") for entry in entries}
        ):
            stack_issues.append("rollback_binding_unverified")
        else:
            rollback_bindings.append({"route_id": route_id, **rollback})
        if stack_issues:
            issues.extend(stack_issues)
            challengers.append(record)
        else:
            qualified.append(record)

    decision = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_capability_decision",
        "decision_id": "mfcapdec_"
        + hashlib.sha256(f"{snapshot.get('snapshot_id')}:{decided_at}".encode()).hexdigest()[:24],
        "decided_at": decided_at,
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "release_binding": {"id": release.get("id", ""), "sha256": release_sha},
        "snapshot_binding": {"id": snapshot.get("snapshot_id", ""), "sha256": expected_snapshot},
        "ledger_head_sha256": ledger_head or "0" * 64,
        "revocation_head_sha256": revocation_head,
        "qualified_routes": sorted(qualified, key=lambda value: value["route_id"]),
        "challenger_routes": sorted(
            challengers, key=lambda value: (value["route_id"], value["stack_id"])
        ),
        "rollback_bindings": sorted(rollback_bindings, key=lambda value: value["route_id"]),
        "status": "accepted" if not issues else "rejected",
        "rejection_reasons": sorted(set(issues)),
        "decision_sha256": "",
    }
    decision["decision_sha256"] = canonical_document_sha256(
        decision, excluded_top_level_fields=("decision_sha256",)
    )
    return decision


def validate_capability_decision(decision: Mapping[str, Any]) -> tuple[str, ...]:
    """Check a materialized decision's schema, policy binding, and self-hash."""
    try:
        policy = _policy()
    except CapabilityQualificationError as exc:
        return (str(exc),)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    issues = [
        f"schema:{error.validator}"
        for error in Draft202012Validator(schema).iter_errors(dict(decision))
    ]
    if decision.get("policy_sha256") != policy["policy_sha256"]:
        issues.append("policy_hash_drift")
    expected = canonical_document_sha256(decision, excluded_top_level_fields=("decision_sha256",))
    if decision.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")
    if (decision.get("status") == "accepted") != (not decision.get("rejection_reasons")):
        issues.append("decision_status_reasons")
    return tuple(sorted(set(issues)))
