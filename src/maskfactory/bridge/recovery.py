"""Producer receipt-last recovery and atomicity conformance (MF-P6-11.08).

Additive controls:
- receipt-last commit ordering (artifacts → receipt → event → checkpoint last)
- restart reconstruction with outcome_unknown reconciliation before retry
- decision-time health/capability/revocation/release/service/node-pack/lease capture
- GPU-lease coordination evidence (token-bound; never delete a replacement owner)
- cache freshness binding and Main tombstone/rebuild validation
- fail-closed kill/rollback/drift/contention drills without duplicate execution,
  orphan promotion, or authority drift

This module does not implement Main-owned durable journal persistence, remote
provider history APIs, cache mutation, or node-pack install/rollback actions.
It only evaluates producer observations and validates Main-signed evidence.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from jsonschema import Draft202012Validator

from maskfactory.bridge.journal import validate_bridge_journal_history
from maskfactory.validation import canonical_document_sha256

POLICY_PATH = Path(__file__).parents[3] / "configs" / "bridge_recovery_policy.yaml"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "bridge_recovery_evidence.schema.json"
POLICY_ID = "maskfactory-bridge-recovery-v1"
EXTERNAL_MAIN_DEPENDENCIES = (
    "main_durable_journal_retention",
    "main_atomic_append_with_side_effects",
    "main_remote_execution_history_provider",
    "main_cache_tombstone_and_rebuild",
    "main_node_pack_atomic_install_rollback",
    "main_signed_decision_snapshots",
)

_PHASE_INDEX = {
    "reservation": 0,
    "admission": 1,
    "lease_acquired": 2,
    "submitted": 3,
    "provider_result": 4,
    "artifacts_staged": 5,
    "artifacts_published": 6,
    "receipt_signed": 7,
    "receipt_written": 8,
    "receipt_committed_event": 9,
    "checkpoint_advanced": 10,
    "cache_published": 11,
}


class RecoveryError(ValueError):
    """Raised when recovery policy or inputs are unusable."""


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RecoveryError("recovery policy is unavailable") from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise RecoveryError("unexpected recovery policy")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise RecoveryError("recovery policy hash mismatch")
    return dict(policy)


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError:
        return None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strings(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, str) and item]


def _sha(value: object) -> str | None:
    if (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    ):
        return value
    return None


def _ordered_reasons(policy: Mapping[str, Any], reasons: set[str]) -> list[str]:
    return [code for code in policy["rejection_reason_codes"] if code in reasons]


def _completed_phases(transaction: Mapping[str, Any]) -> set[str]:
    completed = set(_strings(transaction.get("completed_phases")))
    phase = transaction.get("current_phase")
    if isinstance(phase, str) and phase in _PHASE_INDEX:
        completed.add(phase)
    return completed


def _receipt_last_order_ok(completed: set[str]) -> tuple[bool, set[str]]:
    reasons: set[str] = set()
    order = (
        "artifacts_published",
        "receipt_signed",
        "receipt_written",
        "receipt_committed_event",
        "checkpoint_advanced",
    )
    reached = [phase for phase in order if phase in completed]
    if not reached:
        return True, reasons
    # Any later phase requires every earlier phase.
    for index, phase in enumerate(order):
        if phase not in completed:
            continue
        missing_prior = [prior for prior in order[:index] if prior not in completed]
        if missing_prior:
            if phase in {"receipt_signed", "receipt_written", "receipt_committed_event"} and (
                "artifacts_published" in missing_prior
            ):
                reasons.add("receipt_before_artifacts")
            if phase == "checkpoint_advanced" and any(
                item in missing_prior
                for item in (
                    "receipt_signed",
                    "receipt_written",
                    "receipt_committed_event",
                )
            ):
                reasons.add("checkpoint_before_receipt")
            reasons.add("incomplete_transaction")
    return not reasons, reasons


def _validate_receipt_binding(transaction: Mapping[str, Any]) -> set[str]:
    reasons: set[str] = set()
    receipt = _mapping(transaction.get("receipt"))
    artifacts = [row for row in transaction.get("artifacts") or () if isinstance(row, Mapping)]
    completed = _completed_phases(transaction)
    if "receipt_committed_event" in completed or "checkpoint_advanced" in completed:
        receipt_sha = _sha(receipt.get("receipt_sha256"))
        if receipt_sha is None:
            reasons.add("unresolved_receipt_digest")
        artifact_shas = {_sha(row.get("artifact_sha256")) for row in artifacts}
        if not artifacts or None in artifact_shas:
            reasons.add("unresolved_receipt_digest")
        claimed = set(_strings(receipt.get("artifact_sha256s")))
        if claimed and claimed != {sha for sha in artifact_shas if sha is not None}:
            reasons.add("authority_drift")
        if receipt.get("resolved") is not True:
            reasons.add("unresolved_receipt_digest")
    # Orphan promotion: published artifacts without receipt/checkpoint authority.
    if "artifacts_published" in completed and "checkpoint_advanced" not in completed:
        if transaction.get("orphan_promotion_attempted") is True:
            reasons.add("orphan_artifact_promotion")
        if transaction.get("authority_granted_without_checkpoint") is True:
            reasons.add("authority_drift")
            reasons.add("orphan_artifact_promotion")
    return reasons


def _validate_reconciliation(
    policy: Mapping[str, Any],
    *,
    transaction: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
) -> tuple[bool, bool, str, set[str]]:
    reasons: set[str] = set()
    submission_state = transaction.get("submission_state")
    outcome_unknown = submission_state == "outcome_unknown" or (
        transaction.get("outcome_unknown") is True
    )
    retry_requested = transaction.get("retry_requested") is True
    if outcome_unknown and not reconciliation:
        reasons.add("outcome_unknown_unreconciled")
        if retry_requested:
            reasons.add("resubmit_without_not_found")
        return False, False, "outcome_unknown requires reconciliation before retry", reasons

    if not reconciliation:
        return True, False, "no reconciliation required", reasons

    outcomes = _mapping(policy.get("reconciliation_outcomes"))
    outcome = reconciliation.get("outcome")
    profile = _mapping(outcomes.get(outcome)) if isinstance(outcome, str) else {}
    if not profile:
        reasons.add("reconciliation_evidence_invalid")
        return False, False, "unknown reconciliation outcome", reasons

    remote_id = reconciliation.get("remote_execution_id")
    remote_sha = _sha(reconciliation.get("remote_execution_sha256"))
    result_sha = _sha(reconciliation.get("remote_result_sha256"))
    not_found_sha = _sha(reconciliation.get("not_found_evidence_sha256"))
    remote_present = isinstance(remote_id, str) and bool(remote_id) and remote_sha is not None
    result_present = result_sha is not None
    not_found_present = not_found_sha is not None
    checked = _utc(reconciliation.get("checked_at")) is not None
    authorized = reconciliation.get("resubmission_authorized") is True

    if reconciliation.get("remote_status") != profile.get("remote_status"):
        reasons.add("reconciliation_evidence_invalid")
    if reconciliation.get("resubmission_authorized") is not profile.get("resubmission_authorized"):
        reasons.add("reconciliation_evidence_invalid")
    if not checked:
        reasons.add("reconciliation_evidence_invalid")
    if profile.get("requires_remote_identity") and not remote_present:
        reasons.add("reconciliation_evidence_invalid")
    if not profile.get("requires_remote_identity") and remote_present:
        reasons.add("reconciliation_evidence_invalid")
    if profile.get("requires_result") and not result_present:
        reasons.add("reconciliation_evidence_invalid")
    if not profile.get("requires_result") and result_present:
        reasons.add("reconciliation_evidence_invalid")
    if profile.get("requires_not_found") and not not_found_present:
        reasons.add("reconciliation_evidence_invalid")
    if not profile.get("requires_not_found") and not_found_present:
        reasons.add("reconciliation_evidence_invalid")

    resubmit_permitted = (
        profile.get("resubmission_authorized") is True
        and authorized
        and not_found_present
        and not reasons
    )
    if retry_requested and not resubmit_permitted:
        reasons.add("resubmit_without_not_found")
    if transaction.get("duplicate_submission_attempted") is True:
        reasons.add("duplicate_execution")
    detail = "reconciliation accepted" if not reasons else "reconciliation rejected"
    return not reasons, resubmit_permitted, detail, reasons


def _snapshot_hash(snapshot: Mapping[str, Any]) -> str | None:
    digest = snapshot.get("snapshot_sha256")
    if not isinstance(digest, str):
        return None
    recomputed = canonical_document_sha256(snapshot, excluded_top_level_fields=("snapshot_sha256",))
    return digest if digest == recomputed else None


def _validate_decision_snapshot(
    policy: Mapping[str, Any],
    *,
    snapshot: Mapping[str, Any],
    current: Mapping[str, Any],
) -> tuple[bool, str, set[str]]:
    reasons: set[str] = set()
    required = set(policy["decision_snapshot_required_fields"])
    if not snapshot:
        return False, "decision snapshot absent", {"decision_snapshot_incomplete"}
    missing = [name for name in required if name not in snapshot]
    if missing or _snapshot_hash(snapshot) is None:
        reasons.add("decision_snapshot_incomplete")

    health = _mapping(snapshot.get("health"))
    if health.get("status") != "ok" or _sha(health.get("health_sha256")) is None:
        reasons.add("health_stale_or_missing")

    capability = _mapping(snapshot.get("capability"))
    cap_hash = _sha(capability.get("capability_sha256"))
    current_cap = _sha(_mapping(current.get("capability")).get("capability_sha256"))
    if cap_hash is None:
        reasons.add("capability_changed")
    elif current_cap is not None and current_cap != cap_hash:
        reasons.add("capability_changed")

    revocation = _mapping(snapshot.get("revocation"))
    rev_hash = _sha(revocation.get("revocation_head_sha256"))
    current_rev = _sha(_mapping(current.get("revocation")).get("revocation_head_sha256"))
    fresh = revocation.get("fresh") is True
    if rev_hash is None or not fresh:
        reasons.add("revocation_stale_or_missing")
    elif current_rev is not None and current_rev != rev_hash:
        reasons.add("revocation_stale_or_missing")

    release = _mapping(snapshot.get("adopted_release"))
    release_hash = _sha(release.get("release_sha256"))
    current_release = _sha(_mapping(current.get("adopted_release")).get("release_sha256"))
    if release_hash is None or (current_release is not None and current_release != release_hash):
        reasons.add("release_binding_drift")

    service = _mapping(snapshot.get("service_openapi"))
    service_hash = _sha(service.get("service_sha256"))
    current_service = _sha(_mapping(current.get("service_openapi")).get("service_sha256"))
    if service_hash is None or (current_service is not None and current_service != service_hash):
        reasons.add("service_drift")

    node_pack = _mapping(snapshot.get("node_pack"))
    node_hash = _sha(node_pack.get("node_pack_sha256"))
    current_node = _sha(_mapping(current.get("node_pack")).get("node_pack_sha256"))
    inventory_closed = node_pack.get("closed_manifest") is True
    stale_files = node_pack.get("stale_unmanifested_files") is True
    if node_hash is None or not inventory_closed or stale_files:
        reasons.add("node_pack_drift")
    elif current_node is not None and current_node != node_hash:
        reasons.add("node_pack_drift")

    detail = "decision snapshot coherent" if not reasons else "decision snapshot rejected"
    return not reasons, detail, reasons


def _validate_cache(
    policy: Mapping[str, Any],
    *,
    cache: Mapping[str, Any],
    transaction: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> tuple[bool, str, set[str]]:
    reasons: set[str] = set()
    if not cache:
        # Cache evidence is required once cache_published or authority is claimed.
        completed = _completed_phases(transaction)
        if "cache_published" in completed or transaction.get("authority_granted") is True:
            return False, "cache evidence required", {"cache_stale_or_unbound"}
        return True, "cache not required for incomplete transaction", reasons

    if not isinstance(cache.get("request_id"), str) or not cache.get("request_id"):
        reasons.add("cache_stale_or_unbound")
    for field in (
        "receipt_sha256",
        "artifact_sha256",
        "release_sha256",
        "capability_sha256",
        "revocation_head_sha256",
        "node_pack_sha256",
        "authority_sha256",
    ):
        if _sha(cache.get(field)) is None:
            reasons.add("cache_stale_or_unbound")

    captured = _utc(cache.get("captured_at"))
    decided = _utc(cache.get("decided_at")) or _utc(transaction.get("decided_at"))
    max_age = int(policy.get("cache_freshness_max_age_ms") or 300000)
    if captured is None or decided is None:
        reasons.add("cache_stale_or_unbound")
    else:
        age_ms = int((decided - captured).total_seconds() * 1000)
        if age_ms < 0 or age_ms > max_age:
            reasons.add("cache_stale_or_unbound")

    # Bind cache identities to decision snapshot when present.
    capability = _sha(_mapping(snapshot.get("capability")).get("capability_sha256"))
    release = _sha(_mapping(snapshot.get("adopted_release")).get("release_sha256"))
    revocation = _sha(_mapping(snapshot.get("revocation")).get("revocation_head_sha256"))
    node_pack = _sha(_mapping(snapshot.get("node_pack")).get("node_pack_sha256"))
    if capability and cache.get("capability_sha256") != capability:
        reasons.add("cache_stale_or_unbound")
    if release and cache.get("release_sha256") != release:
        reasons.add("cache_stale_or_unbound")
    if revocation and cache.get("revocation_head_sha256") != revocation:
        reasons.add("cache_stale_or_unbound")
    if node_pack and cache.get("node_pack_sha256") != node_pack:
        reasons.add("cache_stale_or_unbound")

    tombstone = _mapping(cache.get("main_tombstone_evidence"))
    if cache.get("tombstoned") is True:
        if (
            tombstone.get("status") != "tombstoned"
            or _sha(tombstone.get("evidence_sha256")) is None
        ):
            reasons.add("cache_stale_or_unbound")
    detail = "cache freshness bound" if not reasons else "cache evidence rejected"
    return not reasons, detail, reasons


def _validate_gpu_lease(lease: Mapping[str, Any]) -> tuple[str, bool, str, set[str]]:
    reasons: set[str] = set()
    state = lease.get("state")
    allowed = {"held", "contended", "stale_owner", "lost", "absent", "released"}
    if state not in allowed:
        reasons.add("gpu_lease_contention")
        return "absent", False, "gpu lease evidence invalid", reasons
    token = lease.get("token")
    request_id = lease.get("request_id")
    held = state == "held" and isinstance(token, str) and bool(token)
    if state == "contended":
        reasons.add("gpu_lease_contention")
    if state == "stale_owner":
        reasons.add("gpu_lease_contention")
    if state == "lost":
        reasons.add("gpu_lease_contention")
    if lease.get("cleanup_deleted_foreign_token") is True:
        reasons.add("gpu_lease_unowned_cleanup")
    if held and (not isinstance(request_id, str) or not request_id):
        reasons.add("gpu_lease_contention")
        held = False
    if lease.get("device_id") is not None and not isinstance(lease.get("device_id"), str):
        reasons.add("gpu_lease_contention")
    detail = (
        "gpu lease coordinated"
        if not reasons and held
        else ("gpu lease refused or unbound" if reasons else f"gpu lease state={state}")
    )
    return str(state), held, detail, reasons


def _validate_journal(
    *,
    journal_entries: Sequence[Mapping[str, Any]],
    checkpoints: Sequence[Mapping[str, Any]],
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[bool, str, set[str]]:
    if not journal_entries:
        return True, "journal not supplied for unit observation", set()
    issues = validate_bridge_journal_history(
        journal_entries,
        checkpoints=checkpoints,
        trusted_signing_keys=trusted_signing_keys,
    )
    if issues:
        return False, "journal recovery invalid: " + ",".join(issues), {"journal_recovery_invalid"}
    return True, "journal history valid for restart reconstruction", set()


def _validate_rollback(rollback: Mapping[str, Any]) -> tuple[bool, str, set[str]]:
    if not rollback:
        return True, "no rollback drill", set()
    reasons: set[str] = set()
    if rollback.get("started") is not True:
        reasons.add("rollback_incomplete")
    if rollback.get("completed") is not True:
        reasons.add("rollback_incomplete")
    if rollback.get("duplicate_execution") is True:
        reasons.add("duplicate_execution")
    if rollback.get("orphan_promotion") is True:
        reasons.add("orphan_artifact_promotion")
    if rollback.get("authority_drift") is True:
        reasons.add("authority_drift")
    required = ("from_release_sha256", "to_release_sha256", "evidence_sha256")
    for field in required:
        if _sha(rollback.get(field)) is None:
            reasons.add("rollback_incomplete")
    detail = "rollback drill clean" if not reasons else "rollback drill failed closed"
    return not reasons, detail, reasons


def build_recovery_evidence(observation: Mapping[str, Any], *, decided_at: str) -> dict[str, Any]:
    """Build fail-closed receipt-last recovery evidence from an observation."""
    policy = _policy()
    reasons: set[str] = set()
    transaction = _mapping(observation.get("transaction"))
    reconciliation = _mapping(observation.get("reconciliation"))
    snapshot = _mapping(observation.get("decision_snapshot"))
    current = _mapping(observation.get("current_context"))
    cache = _mapping(observation.get("cache"))
    lease = _mapping(observation.get("gpu_lease"))
    rollback = _mapping(observation.get("rollback"))
    kill_boundary = observation.get("kill_boundary")
    journal_entries = [
        row for row in observation.get("journal_entries") or () if isinstance(row, Mapping)
    ]
    checkpoints = [row for row in observation.get("checkpoints") or () if isinstance(row, Mapping)]
    trusted_keys = observation.get("trusted_signing_keys")
    trusted = trusted_keys if isinstance(trusted_keys, Mapping) else None

    completed = _completed_phases(transaction)
    order_ok, order_reasons = _receipt_last_order_ok(completed)
    reasons.update(order_reasons)
    reasons.update(_validate_receipt_binding(transaction))

    if isinstance(kill_boundary, str) and kill_boundary in set(policy["durable_kill_boundaries"]):
        # Kill at a durable boundary must leave authority ungranted and fail closed.
        if transaction.get("authority_granted") is True:
            reasons.add("kill_boundary_fail_closed")
            reasons.add("authority_drift")
        if transaction.get("orphan_promotion_attempted") is True:
            reasons.add("orphan_artifact_promotion")
            reasons.add("kill_boundary_fail_closed")
        if transaction.get("duplicate_submission_attempted") is True:
            reasons.add("duplicate_execution")
            reasons.add("kill_boundary_fail_closed")
        if "checkpoint_advanced" in completed and kill_boundary != "checkpoint_advanced":
            # Completing checkpoint after an earlier kill boundary without recovery is drift.
            if observation.get("recovered_cleanly") is not True:
                reasons.add("kill_boundary_fail_closed")

    recon_ok, resubmit_permitted, recon_detail, recon_reasons = _validate_reconciliation(
        policy, transaction=transaction, reconciliation=reconciliation
    )
    reasons.update(recon_reasons)

    snap_ok, snap_detail, snap_reasons = _validate_decision_snapshot(
        policy, snapshot=snapshot, current=current
    )
    reasons.update(snap_reasons)

    cache_ok, cache_detail, cache_reasons = _validate_cache(
        policy, cache=cache, transaction=transaction, snapshot=snapshot
    )
    reasons.update(cache_reasons)

    lease_state, lease_held, lease_detail, lease_reasons = _validate_gpu_lease(lease)
    reasons.update(lease_reasons)

    journal_ok, journal_detail, journal_reasons = _validate_journal(
        journal_entries=journal_entries,
        checkpoints=checkpoints,
        trusted_signing_keys=trusted,
    )
    reasons.update(journal_reasons)

    rollback_ok, rollback_detail, rollback_reasons = _validate_rollback(rollback)
    reasons.update(rollback_reasons)

    # Complete commit requires full receipt-last chain and coherent evidence.
    commit_complete = {
        "artifacts_published",
        "receipt_signed",
        "receipt_written",
        "receipt_committed_event",
        "checkpoint_advanced",
    }.issubset(completed)
    if transaction.get("commit_claimed") is True and not commit_complete:
        reasons.add("incomplete_transaction")

    prerequisites: list[dict[str, Any]] = []
    for name in policy["external_main_prerequisites"]:
        if name == "main_durable_journal_retention":
            status = (
                "met"
                if journal_ok
                else ("missing_external_main_evidence" if not journal_entries else "failed")
            )
            detail = journal_detail
        elif name == "main_atomic_append_with_side_effects":
            if transaction.get("commit_claimed") is True:
                status = (
                    "met"
                    if order_ok and commit_complete and "unresolved_receipt_digest" not in reasons
                    else "failed"
                )
            else:
                status = "met" if order_ok else "failed"
            detail = "receipt-last ordering enforced"
        elif name == "main_remote_execution_history_provider":
            needs = transaction.get("submission_state") == "outcome_unknown" or bool(reconciliation)
            status = (
                "met"
                if (recon_ok if needs else True)
                else ("missing_external_main_evidence" if not reconciliation else "failed")
            )
            detail = recon_detail
        elif name == "main_cache_tombstone_and_rebuild":
            status = (
                "met" if cache_ok else ("missing_external_main_evidence" if not cache else "failed")
            )
            detail = cache_detail
        elif name == "main_node_pack_atomic_install_rollback":
            node_ok = "node_pack_drift" not in reasons and (rollback_ok if rollback else True)
            status = "met" if node_ok else "failed"
            detail = rollback_detail if rollback else snap_detail
        else:
            status = (
                "met"
                if snap_ok
                else ("missing_external_main_evidence" if not snapshot else "failed")
            )
            detail = snap_detail
        if status != "met":
            reasons.add("external_main_prerequisite_unmet")
        prerequisites.append({"prerequisite": name, "status": status, "detail": detail})

    integrity_failures = {
        "receipt_before_artifacts",
        "checkpoint_before_receipt",
        "unresolved_receipt_digest",
        "orphan_artifact_promotion",
        "authority_drift",
        "duplicate_execution",
        "outcome_unknown_unreconciled",
        "resubmit_without_not_found",
        "kill_boundary_fail_closed",
        "gpu_lease_unowned_cleanup",
        "rollback_incomplete",
        "journal_recovery_invalid",
    }
    ordered = _ordered_reasons(policy, reasons)
    # Integrity violations reject. Soft refusals (drift/contention/incomplete/Main gaps)
    # keep status=accepted with refusal_reasons and commit_ready=false.
    hard = set(ordered) & integrity_failures
    status = "rejected" if hard else "accepted"
    rejection_reasons = ordered if status == "rejected" else []
    refusal_reasons = ordered if status == "accepted" else []

    commit_ready = (
        status == "accepted"
        and commit_complete
        and order_ok
        and snap_ok
        and cache_ok
        and journal_ok
        and rollback_ok
        and recon_ok
        and lease_held
        and not refusal_reasons
        and transaction.get("commit_claimed") is True
        and transaction.get("orphan_promotion_attempted") is not True
        and transaction.get("duplicate_submission_attempted") is not True
        and transaction.get("authority_granted_without_checkpoint") is not True
        and not isinstance(kill_boundary, str)
    )

    request_id = str(transaction.get("request_id") or observation.get("request_id") or "unknown")
    evidence = {
        "schema_version": "1.0.0",
        "record_type": "bridge_recovery_evidence",
        "decided_at": decided_at,
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "request_id": request_id,
        "kill_boundary": kill_boundary if isinstance(kill_boundary, str) else None,
        "transaction": {
            "current_phase": (
                transaction.get("current_phase")
                if transaction.get("current_phase") in _PHASE_INDEX
                else "reservation"
            ),
            "completed_phases": sorted(completed, key=lambda p: _PHASE_INDEX.get(p, 99)),
            "receipt_last_order_ok": order_ok,
            "commit_complete": commit_complete,
            "commit_ready": commit_ready,
            "submission_state": (
                transaction.get("submission_state")
                if transaction.get("submission_state")
                in {"none", "submitted", "outcome_unknown", "reconciled"}
                else "none"
            ),
            "detail": (
                "receipt-last commit ready" if commit_ready else "receipt-last commit not ready"
            ),
        },
        "reconciliation": {
            "required": (
                transaction.get("submission_state") == "outcome_unknown"
                or transaction.get("outcome_unknown") is True
            ),
            "outcome": (
                reconciliation.get("outcome")
                if isinstance(reconciliation.get("outcome"), str)
                else None
            ),
            "resubmission_authorized": resubmit_permitted,
            "evidence_valid": recon_ok,
            "detail": recon_detail,
        },
        "decision_snapshot": {
            "complete": snap_ok,
            "health_ok": "health_stale_or_missing" not in reasons,
            "capability_unchanged": "capability_changed" not in reasons,
            "revocation_fresh": "revocation_stale_or_missing" not in reasons,
            "release_bound": "release_binding_drift" not in reasons,
            "service_bound": "service_drift" not in reasons,
            "node_pack_exact": "node_pack_drift" not in reasons,
            "detail": snap_detail,
        },
        "gpu_lease": {
            "state": lease_state,
            "held": lease_held,
            "foreign_token_cleanup_refused": "gpu_lease_unowned_cleanup" not in reasons,
            "detail": lease_detail,
        },
        "cache": {
            "fresh": cache_ok,
            "bound": "cache_stale_or_unbound" not in reasons,
            "detail": cache_detail,
        },
        "integrity": {
            "no_duplicate_execution": "duplicate_execution" not in reasons,
            "no_orphan_promotion": "orphan_artifact_promotion" not in reasons,
            "no_authority_drift": "authority_drift" not in reasons,
            "kill_boundary_fail_closed": "kill_boundary_fail_closed" not in reasons,
            "rollback_clean": rollback_ok,
            "detail": rollback_detail if rollback else "integrity constraints evaluated",
        },
        "external_main_prerequisites": prerequisites,
        "status": status,
        "rejection_reasons": rejection_reasons,
        "refusal_reasons": refusal_reasons,
        "decision_sha256": "",
    }
    evidence["decision_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("decision_sha256",)
    )
    return evidence


def validate_recovery_evidence(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate schema, policy binding, hash, and fail-closed coherence."""
    issues: list[str] = []
    try:
        policy = _policy()
    except RecoveryError as exc:
        return (str(exc),)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    issues.extend(
        f"schema:{error.validator}"
        for error in Draft202012Validator(schema).iter_errors(dict(evidence))
    )
    if (
        evidence.get("policy_id") != policy["policy_id"]
        or evidence.get("policy_sha256") != policy["policy_sha256"]
    ):
        issues.append("policy_drift")
    expected = canonical_document_sha256(evidence, excluded_top_level_fields=("decision_sha256",))
    if evidence.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")
    allowed = set(policy["rejection_reason_codes"])
    reasons = set(_strings(evidence.get("rejection_reasons")))
    refusals = set(_strings(evidence.get("refusal_reasons")))
    if not reasons.issubset(allowed) or not refusals.issubset(allowed):
        issues.append("decision_reason_code")
    if evidence.get("status") == "rejected" and not reasons:
        issues.append("decision_status_reasons")
    integrity = _mapping(evidence.get("integrity"))
    if evidence.get("status") == "accepted":
        if integrity.get("no_duplicate_execution") is not True:
            issues.append("accepted_with_duplicate_execution")
        if integrity.get("no_orphan_promotion") is not True:
            issues.append("accepted_with_orphan_promotion")
        if integrity.get("no_authority_drift") is not True:
            issues.append("accepted_with_authority_drift")
    txn = _mapping(evidence.get("transaction"))
    if txn.get("commit_ready") is True:
        if txn.get("receipt_last_order_ok") is not True or txn.get("commit_complete") is not True:
            issues.append("commit_ready_incoherent")
        if evidence.get("gpu_lease", {}).get("held") is not True:
            issues.append("commit_ready_without_lease")
        if evidence.get("decision_snapshot", {}).get("complete") is not True:
            issues.append("commit_ready_without_snapshot")
    return tuple(sorted(set(issues)))


def simulate_kill_at_boundary(
    *,
    kill_boundary: str,
    request_id: str,
    decided_at: str,
    decision_snapshot: Mapping[str, Any] | None = None,
    gpu_lease: Mapping[str, Any] | None = None,
    recovered_cleanly: bool = True,
) -> dict[str, Any]:
    """Simulate a kill at a durable boundary and evaluate recovery evidence."""
    policy = _policy()
    if kill_boundary not in set(policy["durable_kill_boundaries"]):
        raise RecoveryError(f"unsupported kill boundary: {kill_boundary}")

    phase_map = {
        "reservation": "reservation",
        "admission": "admission",
        "lease_acquired": "lease_acquired",
        "submitted_known": "submitted",
        "submitted_unknown": "submitted",
        "provider_result": "provider_result",
        "artifacts_staged": "artifacts_staged",
        "artifacts_published": "artifacts_published",
        "receipt_signed": "receipt_signed",
        "receipt_written": "receipt_written",
        "receipt_committed_event": "receipt_committed_event",
        "checkpoint_advanced": "checkpoint_advanced",
        "cache_published": "cache_published",
        "install_switch": "artifacts_published",
        "rollback": "artifacts_published",
    }
    current_phase = phase_map[kill_boundary]
    completed = [
        phase for phase, index in _PHASE_INDEX.items() if index <= _PHASE_INDEX[current_phase]
    ]
    outcome_unknown = kill_boundary == "submitted_unknown"
    snapshot = dict(decision_snapshot or _default_snapshot())
    lease = dict(
        gpu_lease
        or {
            "state": (
                "held"
                if _PHASE_INDEX[current_phase] >= _PHASE_INDEX["lease_acquired"]
                else "absent"
            ),
            "token": (
                "lease-token-test"
                if _PHASE_INDEX[current_phase] >= _PHASE_INDEX["lease_acquired"]
                else None
            ),
            "request_id": request_id,
            "device_id": "cuda:0",
            "cleanup_deleted_foreign_token": False,
        }
    )
    reconciliation: dict[str, Any] = {}
    if outcome_unknown:
        # Restart must reconcile before retry; default drill supplies not-found.
        reconciliation = {
            "outcome": "not_found",
            "remote_status": "not_found",
            "remote_execution_id": None,
            "remote_execution_sha256": None,
            "remote_result_sha256": None,
            "not_found_evidence_sha256": "c" * 64,
            "checked_at": decided_at,
            "resubmission_authorized": True,
        }
    needs_receipt = _PHASE_INDEX[current_phase] >= _PHASE_INDEX["receipt_committed_event"]
    artifacts = [{"artifact_sha256": "22" * 32}] if needs_receipt else []
    receipt = (
        {
            "receipt_sha256": "11" * 32,
            "artifact_sha256s": ["22" * 32],
            "resolved": True,
        }
        if needs_receipt
        else {}
    )
    cache: dict[str, Any] = {}
    if current_phase == "cache_published":
        cache = {
            "request_id": request_id,
            "receipt_sha256": "11" * 32,
            "artifact_sha256": "22" * 32,
            "release_sha256": _sha(_mapping(snapshot.get("adopted_release")).get("release_sha256")),
            "capability_sha256": _sha(
                _mapping(snapshot.get("capability")).get("capability_sha256")
            ),
            "revocation_head_sha256": _sha(
                _mapping(snapshot.get("revocation")).get("revocation_head_sha256")
            ),
            "node_pack_sha256": _sha(_mapping(snapshot.get("node_pack")).get("node_pack_sha256")),
            "authority_sha256": "33" * 32,
            "captured_at": decided_at,
            "decided_at": decided_at,
            "tombstoned": False,
            "main_tombstone_evidence": {},
        }
    observation = {
        "request_id": request_id,
        "kill_boundary": kill_boundary,
        "recovered_cleanly": recovered_cleanly,
        "transaction": {
            "request_id": request_id,
            "current_phase": current_phase,
            "completed_phases": completed,
            "submission_state": (
                "outcome_unknown"
                if outcome_unknown
                else ("submitted" if current_phase == "submitted" else "none")
            ),
            "outcome_unknown": outcome_unknown,
            "retry_requested": False,
            "duplicate_submission_attempted": False,
            "orphan_promotion_attempted": False,
            "authority_granted": False,
            "authority_granted_without_checkpoint": False,
            "commit_claimed": False,
            "receipt": receipt,
            "artifacts": artifacts,
            "decided_at": decided_at,
        },
        "reconciliation": reconciliation,
        "decision_snapshot": snapshot,
        "current_context": {
            "capability": _mapping(snapshot.get("capability")),
            "revocation": _mapping(snapshot.get("revocation")),
            "adopted_release": _mapping(snapshot.get("adopted_release")),
            "service_openapi": _mapping(snapshot.get("service_openapi")),
            "node_pack": _mapping(snapshot.get("node_pack")),
        },
        "cache": cache,
        "gpu_lease": lease,
        "rollback": {},
        "journal_entries": [],
        "checkpoints": [],
    }
    if kill_boundary == "rollback":
        observation["rollback"] = {
            "started": True,
            "completed": True,
            "duplicate_execution": False,
            "orphan_promotion": False,
            "authority_drift": False,
            "from_release_sha256": "d" * 64,
            "to_release_sha256": "e" * 64,
            "evidence_sha256": "f" * 64,
        }
    return build_recovery_evidence(observation, decided_at=decided_at)


def _default_snapshot() -> dict[str, Any]:
    body = {
        "health": {"status": "ok", "health_sha256": "a" * 64},
        "capability": {"capability_sha256": "b" * 64},
        "adopted_release": {"release_sha256": "c" * 64},
        "revocation": {"revocation_head_sha256": "d" * 64, "fresh": True},
        "service_openapi": {"service_sha256": "e" * 64},
        "node_pack": {
            "node_pack_sha256": "f" * 64,
            "closed_manifest": True,
            "stale_unmanifested_files": False,
        },
        "policy": {"policy_sha256": "1" * 64},
        "route": {"route_sha256": "2" * 64},
        "gpu_lease": {"lease_sha256": "3" * 64},
    }
    body["snapshot_sha256"] = canonical_document_sha256(
        body, excluded_top_level_fields=("snapshot_sha256",)
    )
    return body


__all__ = [
    "EXTERNAL_MAIN_DEPENDENCIES",
    "POLICY_ID",
    "RecoveryError",
    "build_recovery_evidence",
    "simulate_kill_at_boundary",
    "validate_recovery_evidence",
]
