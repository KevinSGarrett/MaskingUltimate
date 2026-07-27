"""Producer-side fail-closed checks for consumer invalidation contracts.

This additive boundary validates that Main-provided evidence is sufficient for:
cache/route invalidation, revalidation, and rollback-to-last-compatible release.
Main-owned runtime actions remain external; missing action evidence is surfaced
as explicit blockers and causes a closed rejection.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from jsonschema import Draft202012Validator

from maskfactory.validation import (
    INVALIDATION_REASON_POLICY,
    canonical_document_sha256,
    validate_bridge_event_chain,
    validate_mask_authority_invalidation_event,
)

POLICY_PATH = Path(__file__).parents[3] / "configs" / "bridge_consumer_invalidation_policy.yaml"
SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "bridge_consumer_invalidation_decision.schema.json"
)
POLICY_ID = "maskfactory-bridge-consumer-invalidation-v1"
_REQUIRED_ROLLBACK_PROOF_ARTIFACTS = frozenset(
    {"compatibility_proof", "route_table_snapshot", "cache_tombstone_manifest"}
)


class ConsumerInvalidationError(ValueError):
    """Consumer invalidation policy or evidence is unavailable/malformed."""


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConsumerInvalidationError("consumer invalidation policy is unavailable") from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise ConsumerInvalidationError("unexpected consumer invalidation policy")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise ConsumerInvalidationError("consumer invalidation policy hash mismatch")
    reasons = policy.get("reason_codes")
    if not isinstance(reasons, list) or len(reasons) != len(set(reasons)):
        raise ConsumerInvalidationError("consumer invalidation policy reason codes are invalid")
    return dict(policy)


def _ordered(policy: Mapping[str, Any], reasons: list[str]) -> list[str]:
    return [code for code in policy["reason_codes"] if code in set(reasons)] or ["eligible"]


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _required_actions(reason: str) -> set[str]:
    policy = INVALIDATION_REASON_POLICY.get(reason)
    if policy is None:
        return {"revalidate_adoption"}
    return set(policy[1])


def _external_blockers(
    event: Mapping[str, Any],
    consumer_action_evidence: Mapping[str, Any] | None,
) -> tuple[list[dict[str, str]], list[str]]:
    blockers: list[dict[str, str]] = []
    reasons: list[str] = []
    action_rows = [row for row in event.get("required_actions") or () if isinstance(row, Mapping)]
    evidence_map = consumer_action_evidence if isinstance(consumer_action_evidence, Mapping) else {}
    observed_actions = {
        row.get("action") for row in action_rows if isinstance(row.get("action"), str)
    }
    expected_actions = _required_actions(str(event.get("reason")))
    if not expected_actions.issubset(observed_actions):
        reasons.append("invalidation_missing_consumer_contract_actions")
    for row in action_rows:
        action_id = row.get("action_id")
        action = row.get("action")
        if not isinstance(action_id, str) or not isinstance(action, str):
            continue
        evidence = evidence_map.get(action_id)
        if (
            not isinstance(evidence, Mapping)
            or evidence.get("status") != "performed"
            or not isinstance(evidence.get("evidence_sha256"), str)
        ):
            blockers.append(
                {
                    "action_id": action_id,
                    "action": action,
                    "blocker": "main_runtime_evidence_missing",
                }
            )
    if blockers:
        reasons.append("external_main_runtime_action_required")
    return blockers, reasons


def _cache_issues(event: Mapping[str, Any], cache_snapshot: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(cache_snapshot, Mapping):
        return ["stale_cache_snapshot"]
    captured = _utc(cache_snapshot.get("captured_at"))
    effective = _utc(event.get("effective_at"))
    if captured is None or effective is None or captured < effective:
        return ["stale_cache_snapshot"]
    scope_sha256 = ((event.get("target_transitions") or [{}])[0] or {}).get("scope_sha256")
    invalidated = cache_snapshot.get("invalidated_scope_sha256")
    if isinstance(scope_sha256, str) and invalidated != scope_sha256:
        return ["stale_cache_snapshot"]
    return []


def _revocation_issues(
    event: Mapping[str, Any], revocation_head: Mapping[str, Any] | None
) -> list[str]:
    if not isinstance(revocation_head, Mapping):
        return ["revocation_head_drift"]
    expected = revocation_head.get("expected_head_sha256")
    observed = revocation_head.get("observed_head_sha256")
    observed_at = _utc(revocation_head.get("observed_at"))
    effective = _utc(event.get("effective_at"))
    if not isinstance(expected, str) or not isinstance(observed, str) or expected != observed:
        return ["revocation_head_drift"]
    if observed_at is None or effective is None or observed_at < effective:
        return ["revocation_head_drift"]
    return []


def _recovery_marker_issues(
    recovery_markers: Sequence[Mapping[str, Any]] | None,
    bridge_journal_events: Sequence[Mapping[str, Any]],
) -> list[str]:
    marker_rows = [row for row in recovery_markers or () if isinstance(row, Mapping)]
    started = any(
        row.get("marker") == "recovery_started" and isinstance(row.get("journal_head_sha256"), str)
        for row in marker_rows
    )
    completed = any(
        row.get("marker") == "recovery_completed"
        and isinstance(row.get("journal_head_sha256"), str)
        for row in marker_rows
    )
    if started and completed:
        return []
    # Allow equivalent proof via signed bridge journal events when explicit marker docs are unavailable.
    started = started or any(
        event.get("event_type") == "recovery_started" for event in bridge_journal_events
    )
    completed = completed or any(
        event.get("event_type") == "recovery_completed" for event in bridge_journal_events
    )
    return [] if started and completed else ["restart_recovery_marker_missing"]


def _rollback_issues(
    event: Mapping[str, Any],
    rollback_proof: Mapping[str, Any] | None,
    compatible_release_history: Sequence[Mapping[str, Any]] | None,
) -> list[str]:
    if event.get("reason") != "release_revoked":
        return []
    if not isinstance(rollback_proof, Mapping):
        return ["rollback_contract_required"]
    reasons: list[str] = []
    if rollback_proof.get("compatibility_checks_passed") is not True:
        reasons.append("rollback_target_incompatible")
    artifacts = [
        row for row in rollback_proof.get("proof_artifacts") or () if isinstance(row, Mapping)
    ]
    kinds = {row.get("kind") for row in artifacts}
    if not _REQUIRED_ROLLBACK_PROOF_ARTIFACTS.issubset(kinds):
        reasons.append("compatibility_proof_artifact_missing")
    if not isinstance(rollback_proof.get("compatibility_proof_sha256"), str):
        reasons.append("compatibility_proof_artifact_missing")
    target_release_id = rollback_proof.get("target_release_id")
    target_release_sha256 = rollback_proof.get("target_release_sha256")
    if not isinstance(target_release_id, str) or not isinstance(target_release_sha256, str):
        reasons.append("rollback_target_incompatible")
    history = [row for row in compatible_release_history or () if isinstance(row, Mapping)]
    expected_target = next(
        (
            row
            for row in history
            if row.get("compatible") is True and row.get("revoked") is not True
        ),
        None,
    )
    if isinstance(expected_target, Mapping):
        if target_release_id != expected_target.get(
            "release_id"
        ) or target_release_sha256 != expected_target.get("release_payload_sha256"):
            reasons.append("rollback_target_not_last_compatible")
    return reasons


def build_consumer_invalidation_decision(
    event: Mapping[str, Any],
    *,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
    bridge_journal_events: Sequence[Mapping[str, Any]] = (),
    expected_journal_head_sha256: str | None = None,
    consumer_action_evidence: Mapping[str, Any] | None = None,
    cache_snapshot: Mapping[str, Any] | None = None,
    revocation_head: Mapping[str, Any] | None = None,
    recovery_markers: Sequence[Mapping[str, Any]] | None = None,
    rollback_proof: Mapping[str, Any] | None = None,
    compatible_release_history: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one fail-closed producer decision for consumer invalidation handling."""
    policy = _policy()
    reasons: list[str] = []

    invalidation_issues = validate_mask_authority_invalidation_event(
        event, trusted_signing_keys=trusted_signing_keys
    )
    if invalidation_issues:
        reasons.append("invalidation_event_invalid")
    if event.get("severity") != "blocking":
        reasons.append("invalidation_event_not_blocking")

    journal_issues = validate_bridge_event_chain(
        bridge_journal_events,
        trusted_signing_keys=trusted_signing_keys,
        expected_head_sha256=expected_journal_head_sha256,
    )
    if journal_issues:
        reasons.append("journal_chain_invalid")

    event_id = event.get("event_id")
    payload_hash = event.get("event_payload_sha256")
    if isinstance(event_id, str) and isinstance(payload_hash, str):
        bound = any(
            isinstance(item.get("state_transition"), Mapping)
            and item["state_transition"].get("invalidation_event_id") == event_id
            and item["state_transition"].get("invalidation_event_sha256") == payload_hash
            for item in bridge_journal_events
            if isinstance(item, Mapping)
        )
        if not bound:
            reasons.append("invalidation_journal_binding_missing")
    else:
        reasons.append("invalidation_event_invalid")

    reasons.extend(_cache_issues(event, cache_snapshot))
    reasons.extend(_revocation_issues(event, revocation_head))
    reasons.extend(_recovery_marker_issues(recovery_markers, bridge_journal_events))
    reasons.extend(_rollback_issues(event, rollback_proof, compatible_release_history))
    external_blockers, blocker_reasons = _external_blockers(event, consumer_action_evidence)
    reasons.extend(blocker_reasons)

    consumed_context = {
        "event_id": event.get("event_id"),
        "event_payload_sha256": event.get("event_payload_sha256"),
        "reason": event.get("reason"),
        "required_actions": [
            {
                "action_id": row.get("action_id"),
                "action": row.get("action"),
                "deadline_at": row.get("deadline_at"),
            }
            for row in event.get("required_actions") or ()
            if isinstance(row, Mapping)
        ],
        "cache_snapshot_sha256": (
            cache_snapshot.get("snapshot_sha256") if isinstance(cache_snapshot, Mapping) else None
        ),
        "revocation_head_sha256": (
            revocation_head.get("observed_head_sha256")
            if isinstance(revocation_head, Mapping)
            else None
        ),
        "journal_event_count": len(
            [row for row in bridge_journal_events if isinstance(row, Mapping)]
        ),
        "rollback_target_release_id": (
            rollback_proof.get("target_release_id") if isinstance(rollback_proof, Mapping) else None
        ),
        "rollback_target_release_sha256": (
            rollback_proof.get("target_release_sha256")
            if isinstance(rollback_proof, Mapping)
            else None
        ),
    }
    decision = {
        "schema_version": "1.0.0",
        "record_type": "bridge_consumer_invalidation_decision",
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "status": "accepted" if not reasons else "rejected",
        "rejection_reasons": _ordered(policy, reasons),
        "external_main_runtime_blockers": external_blockers,
        "consumed_context": consumed_context,
        "decision_sha256": "",
    }
    decision["decision_sha256"] = canonical_document_sha256(
        decision, excluded_top_level_fields=("decision_sha256",)
    )
    return decision


def validate_consumer_invalidation_decision(decision: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate decision shape, policy binding, and canonical self-hash."""
    try:
        policy = _policy()
    except ConsumerInvalidationError as exc:
        return (str(exc),)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    issues = [
        f"schema:{error.validator}"
        for error in Draft202012Validator(schema).iter_errors(dict(decision))
    ]
    if (
        decision.get("policy_id") != policy["policy_id"]
        or decision.get("policy_sha256") != policy["policy_sha256"]
    ):
        issues.append("policy_drift")
    if not set(decision.get("rejection_reasons") or ()).issubset(set(policy["reason_codes"])):
        issues.append("reason_code_drift")
    expected = canonical_document_sha256(decision, excluded_top_level_fields=("decision_sha256",))
    if decision.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")
    if (decision.get("status") == "accepted") != (
        decision.get("rejection_reasons") == ["eligible"]
    ):
        issues.append("decision_status_reasons")
    return tuple(sorted(set(issues)))


__all__ = [
    "ConsumerInvalidationError",
    "build_consumer_invalidation_decision",
    "validate_consumer_invalidation_decision",
]
