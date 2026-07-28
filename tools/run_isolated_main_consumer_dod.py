"""Isolated Main-consumer DoD-climb runner (MF-P6-11.06 / 11.07 / adoption-receipt).

Standalone sibling of ``tools/run_isolated_main_consumer.py``. It executes three
additional *real-machinery* DoD-coverage matrices against the producer bridge and
emits isolated-consumer-signed evidence:

  * ``isolated_journal_dod_matrix`` (MF-P6-11.06): full closed durable state-machine
    walk, replay idempotency, same-key/different-body + illegal-transition refusal,
    fork/delete/reorder detection, and exact interruption reconstruction vs a
    corrupted-history refusal.
  * ``isolated_circuit_breaker_matrix`` (MF-P6-11.07): closed circuit permits, open
    circuit blocks the route with no mask substitution, half-open probe gating.
  * ``isolated_adoption_receipt_matrix``: eligible adopted receipt accepts while
    optional-only / partial-required / expired / file-presence-only /
    missing-duplicate receipts are refused.

Honesty ceiling (binding): producer-side, isolated-consumer-signed only. It NEVER
claims real Comfy_UI_Main adoption. HARD MF-P6-11.02 / 11.07 / 12.05 / 12.06 remain
OPEN; recorded in the evidence, not hidden.

Kept as a standalone file (not folded into the shared runner) so this stream's work
is durable under heavy multi-agent working-tree churn.

Usage:
  python tools/run_isolated_main_consumer_dod.py \
      --output runtime_artifacts/main_consumer/isolated_consumer_dod_run_evidence_<ts>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maskfactory.bridge.adoption_receipt_matrix import (
    build_adoption_receipt_matrix_decision,
    validate_adoption_receipt_matrix_decision,
)
from maskfactory.bridge.failure_control import (
    build_failure_control_evidence,
    validate_failure_control_evidence,
)
from maskfactory.bridge.journal import (
    BridgeJournalError,
    append_bridge_journal_event,
    checkpoint_bridge_journal,
    reconstruct_bridge_journal_state,
    validate_bridge_journal_history,
    validate_bridge_journal_reconstruction_evidence,
)
from maskfactory.validation import canonical_document_sha256

REPO_ROOT = Path(__file__).resolve().parents[1]
DECIDED_AT = "2026-07-20T05:00:00Z"

HARD_BLOCKERS_REQUIRING_REAL_MAIN = (
    "MF-P6-11.02",
    "MF-P6-11.07",
    "MF-P6-12.05",
    "MF-P6-12.06",
)


def _isolated_key(role: str) -> tuple[Ed25519PrivateKey, str]:
    """Deterministic isolated-consumer key the tool controls (reproducible)."""
    seed = hashlib.sha256(f"maskfactory-isolated-main-consumer-v1:{role}".encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed), f"isolated-main-consumer-{role}"


def _git_head() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    value = out.stdout.strip().lower()
    return value if len(value) == 40 and all(c in "0123456789abcdef" for c in value) else None


def run_journal_dod_matrix() -> dict[str, Any]:
    """Full MF-P6-11.06 DoD matrix over the real signed append-only journal."""
    key, key_id = _isolated_key("journal")
    trusted = {
        key_id: {
            "public_key_sha256": hashlib.sha256(key.public_key().public_bytes_raw()).hexdigest(),
            "roles": ["producer_journal"],
            "status": "active",
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": "2027-01-01T00:00:00Z",
        }
    }
    journal_id = "isolated-main-consumer-journal-dod-v1"

    def _append(entries, state, key_suffix, seconds, checkpoints=()):
        return append_bridge_journal_event(
            entries,
            journal_id=journal_id,
            state=state,
            idempotency_key=f"isolated-{key_suffix}",
            event_body={"isolated_consumer": True, "state": state},
            occurred_at=f"2026-07-20T05:00:{seconds:02d}Z",
            private_key=key,
            signing_key_id=key_id,
            checkpoints=checkpoints,
        )

    sub: list[dict[str, Any]] = []

    full_path = (
        "admit",
        "route",
        "lease",
        "submit_known",
        "reconcile",
        "result",
        "validate",
        "cache",
        "decision",
        "feedback",
        "adoption",
        "invalidation",
        "recovery",
        "rollback",
    )
    entries: tuple[dict[str, Any], ...] = ()
    for index, state in enumerate(full_path):
        entries, _, _ = _append(entries, state, f"{state}-001", index)
    full_ok = validate_bridge_journal_history(entries, trusted_signing_keys=trusted) == () and len(
        entries
    ) == len(full_path)
    sub.append(
        {"case": "full_closed_state_machine", "passed": full_ok, "entry_count": len(entries)}
    )

    base: tuple[dict[str, Any], ...] = ()
    for index, state in enumerate(("admit", "route", "submit")):
        base, _, _ = _append(base, state, f"base-{state}-001", index)
    checkpoint = checkpoint_bridge_journal(
        base,
        journal_id=journal_id,
        checkpoint_id="isolated-dod-checkpoint-001",
        created_at="2026-07-20T05:01:00Z",
        private_key=key,
        signing_key_id=key_id,
    )
    checkpoint_ok = (
        validate_bridge_journal_history(
            base, checkpoints=(checkpoint,), trusted_signing_keys=trusted
        )
        == ()
    )
    sub.append({"case": "signed_checkpointed_history", "passed": checkpoint_ok})

    replayed, entry, is_replay = _append(base, "submit", "base-submit-001", 2)
    replay_ok = (
        is_replay is True and replayed == base and entry["entry_sha256"] == base[-1]["entry_sha256"]
    )
    sub.append({"case": "same_key_same_body_replay_idempotent", "passed": bool(replay_ok)})

    try:
        append_bridge_journal_event(
            base,
            journal_id=journal_id,
            state="submit",
            idempotency_key="isolated-base-submit-001",
            event_body={"isolated_consumer": True, "tampered": True},
            occurred_at="2026-07-20T05:00:09Z",
            private_key=key,
            signing_key_id=key_id,
        )
        diff_body_ok = False
    except BridgeJournalError as exc:
        diff_body_ok = "same_key_different_body" in exc.codes
    sub.append({"case": "same_key_different_body_refused", "passed": diff_body_ok})

    admit_only: tuple[dict[str, Any], ...] = ()
    admit_only, _, _ = _append(admit_only, "admit", "illegal-admit-001", 0)
    try:
        _append(admit_only, "result", "illegal-result-001", 1)
        illegal_ok = False
    except BridgeJournalError as exc:
        illegal_ok = "illegal_transition" in exc.codes
    sub.append({"case": "illegal_transition_refused", "passed": illegal_ok})

    deleted = (base[0], base[2])
    delete_ok = "journal_delete_detected" in set(
        validate_bridge_journal_history(
            deleted, checkpoints=(checkpoint,), trusted_signing_keys=trusted
        )
    )
    reordered = (base[1], base[0], base[2])
    reorder_ok = "journal_reorder_detected" in set(
        validate_bridge_journal_history(
            reordered, checkpoints=(checkpoint,), trusted_signing_keys=trusted
        )
    )
    forked_entry = dict(base[2])
    forked_entry["previous_entry_sha256"] = base[0]["entry_sha256"]
    fork_ok = "journal_fork_detected" in set(
        validate_bridge_journal_history(
            (base[0], base[1], forked_entry),
            checkpoints=(checkpoint,),
            trusted_signing_keys=trusted,
        )
    )
    sub.append(
        {
            "case": "fork_delete_reorder_detected",
            "passed": bool(delete_ok and reorder_ok and fork_ok),
        }
    )

    cont = base
    for index, state in enumerate(("reconcile", "result", "decision"), start=3):
        cont, head, _ = _append(cont, state, f"cont-{state}-001", index, checkpoints=(checkpoint,))
    recon = reconstruct_bridge_journal_state(
        cont,
        checkpoints=(checkpoint,),
        trusted_signing_keys=trusted,
        decided_at="2026-07-20T05:02:00Z",
    )
    recon_ok = (
        recon.get("status") == "reconstructed"
        and recon.get("head_state") == "decision"
        and recon.get("head_sequence") == head["sequence"]
        and recon.get("head_entry_sha256") == head["entry_sha256"]
        and recon.get("entry_count") == len(cont)
        and recon.get("latest_checkpoint_sha256") == checkpoint["checkpoint_sha256"]
        and validate_bridge_journal_reconstruction_evidence(recon) == ()
        and bool((recon.get("external_main_prerequisites") or {}).get("unmet"))
    )
    corrupt = reconstruct_bridge_journal_state(
        (cont[0], cont[2]),
        checkpoints=(checkpoint,),
        trusted_signing_keys=trusted,
        decided_at="2026-07-20T05:02:00Z",
    )
    corrupt_ok = (
        corrupt.get("status") == "rejected"
        and "reconstruction_history_invalid" in (corrupt.get("rejection_reasons") or [])
        and validate_bridge_journal_reconstruction_evidence(corrupt) == ()
    )
    sub.append(
        {
            "case": "interruption_reconstruct_exact_state",
            "passed": bool(recon_ok and corrupt_ok),
        }
    )

    return {
        "check": "isolated_journal_dod_matrix",
        "passed": all(row["passed"] for row in sub),
        "reconstruction_decision_sha256": recon.get("decision_sha256"),
        "cases": sub,
    }


def _circuit_evidence(*, state: str, half_open_probe_allowed: bool = False) -> dict[str, Any]:
    body = {
        "route_key": "mode-b/predict",
        "release_id": "mfrel_isolated_circuit",
        "state": state,
        "failure_threshold": 3,
        "observation_window_ms": 60000,
        "cooldown_ms": 5000,
        "opened_at": "2026-07-20T04:00:00Z" if state != "closed" else None,
        "half_open_probe_allowed": half_open_probe_allowed,
    }
    body["evidence_sha256"] = canonical_document_sha256(
        body, excluded_top_level_fields=("evidence_sha256",)
    )
    return body


def run_circuit_breaker_matrix() -> dict[str, Any]:
    """MF-P6-11.07 circuit-breaker DoD over real ``build_failure_control_evidence``."""
    decided_at = "2026-07-20T05:05:00Z"

    def _observation(circuit: dict[str, Any]) -> dict[str, Any]:
        return {
            "at_time": decided_at,
            "request": {
                "request_id": "mfareq_isolated_circuit_0001",
                "pass_id": "pass_predict",
                "attempt_number": 1,
                "created_at": "2026-07-20T04:59:00Z",
                "deadline_at": "2026-07-20T06:00:00Z",
                "resource_envelope": {
                    "maximum_runtime_ms": 120000,
                    "maximum_queue_ms": 30000,
                    "maximum_vram_mb": 8192,
                    "maximum_ram_mb": 16384,
                    "maximum_output_bytes": 50_000_000,
                    "priority": "normal",
                    "allow_cpu_fallback": False,
                },
                "retry_policy": {
                    "maximum_attempts": 3,
                    "retry_only_typed_transient_errors": True,
                    "allow_silent_fallback": False,
                },
            },
            "route_requirements": {
                "required_vram_mb": 4096,
                "required_ram_mb": 8192,
                "required_runtime_ms": 5000,
                "observed_queue_ms": 100,
                "required_output_bytes": 1_000_000,
                "selected_device": "cuda",
                "signed_cpu_route_permitted": False,
            },
            "failure": {},
            "main_circuit_evidence": circuit,
            "main_retry_evidence": {},
            "main_scoped_block_evidence": {},
            "fallback_attempt": {},
            "dag_passes": [
                {"pass_id": "pass_predict", "depends_on": []},
                {"pass_id": "pass_refine", "depends_on": ["pass_predict"]},
                {"pass_id": "pass_unrelated", "depends_on": []},
            ],
        }

    rows: list[dict[str, Any]] = []

    closed = build_failure_control_evidence(
        _observation(_circuit_evidence(state="closed")), decided_at=decided_at
    )
    closed_ok = (
        closed.get("circuit", {}).get("state") == "closed"
        and closed.get("circuit", {}).get("blocks_route") is False
        and closed.get("admission", {}).get("provider_invocation_permitted") is True
        and validate_failure_control_evidence(closed) == ()
    )
    rows.append({"case": "closed_permits_provider", "passed": bool(closed_ok)})

    opened = build_failure_control_evidence(
        _observation(_circuit_evidence(state="open")), decided_at=decided_at
    )
    open_ok = (
        opened.get("circuit", {}).get("state") == "open"
        and opened.get("circuit", {}).get("blocks_route") is True
        and opened.get("admission", {}).get("provider_invocation_permitted") is False
        and opened.get("no_silent_fallback", {}).get("fallback_artifact_present") is False
        and validate_failure_control_evidence(opened) == ()
    )
    rows.append({"case": "open_blocks_route_no_substitution", "passed": bool(open_ok)})

    half_blocked = build_failure_control_evidence(
        _observation(_circuit_evidence(state="half_open", half_open_probe_allowed=False)),
        decided_at=decided_at,
    )
    half_blocked_ok = (
        half_blocked.get("circuit", {}).get("state") == "half_open"
        and half_blocked.get("circuit", {}).get("blocks_route") is True
        and half_blocked.get("admission", {}).get("provider_invocation_permitted") is False
        and validate_failure_control_evidence(half_blocked) == ()
    )
    rows.append({"case": "half_open_without_probe_blocks", "passed": bool(half_blocked_ok)})

    half_probe = build_failure_control_evidence(
        _observation(_circuit_evidence(state="half_open", half_open_probe_allowed=True)),
        decided_at=decided_at,
    )
    half_probe_ok = (
        half_probe.get("circuit", {}).get("state") == "half_open"
        and half_probe.get("circuit", {}).get("blocks_route") is False
        and half_probe.get("admission", {}).get("provider_invocation_permitted") is True
        and validate_failure_control_evidence(half_probe) == ()
    )
    rows.append({"case": "half_open_with_probe_permits", "passed": bool(half_probe_ok)})

    return {
        "check": "isolated_circuit_breaker_matrix",
        "passed": all(row["passed"] for row in rows),
        "cases": rows,
    }


_ADOPTION_MATRIX_CHECKS = (
    "api_contract",
    "artifact_security",
    "authority_policy",
    "canonicalization",
    "capabilities",
    "contract_tests",
    "media_scope",
    "node_pack",
    "ontology",
    "package_format",
    "release_hash",
    "revocation_freshness",
    "signature",
    "signed_journal",
    "trust_anchor",
    "wire_schemas",
)


def _adoption_qual_row(check: str) -> dict[str, Any]:
    return {
        "check": check,
        "test_ids": [f"test:{check}"],
        "result": "pass",
        "result_sha256": canonical_document_sha256({"check": check, "result": "pass"}),
        "execution": {
            "command_sha256": canonical_document_sha256({"check": check, "part": "command"}),
            "stdout_sha256": canonical_document_sha256({"check": check, "part": "stdout"}),
            "stderr_sha256": canonical_document_sha256({"check": check, "part": "stderr"}),
            "status": "pass",
            "exit_code": 0,
        },
    }


def _adoption_executed_hash(row: dict[str, Any]) -> str:
    execution = row["execution"]
    return canonical_document_sha256(
        {
            "check": row["check"],
            "test_ids": sorted(set(row["test_ids"])),
            "result_sha256": row["result_sha256"],
            "execution": {
                "command_sha256": execution["command_sha256"],
                "stdout_sha256": execution["stdout_sha256"],
                "stderr_sha256": execution["stderr_sha256"],
                "status": execution["status"],
                "exit_code": execution["exit_code"],
            },
        }
    )


def _adoption_receipt(decision: str = "adopted") -> dict[str, Any]:
    return {
        "adoption_id": "mfadopt_0123456789abcdef01234567",
        "adoption_payload_sha256": "a" * 64,
        "decided_at": "2026-07-19T00:00:00Z",
        "valid_until": "2026-07-20T00:00:00Z",
        "decision": decision,
        "compatibility_checks": [],
        "capability_decisions": [
            {
                "capability_id": "mask.package.read",
                "requirement_class": "required",
                "decision": "accepted",
            },
            {
                "capability_id": "mask.live.predict",
                "requirement_class": "optional",
                "decision": "accepted",
            },
        ],
        "signature": {
            "key_id": "comfy-main-adoption-prod",
            "public_key_base64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "signed_payload_sha256": "b" * 64,
            "value_base64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        },
    }


def run_adoption_receipt_matrix() -> dict[str, Any]:
    """Adversarial adoption-receipt matrix over ``build_adoption_receipt_matrix_decision``."""
    qualification = {
        "compatibility_checks": [_adoption_qual_row(c) for c in _ADOPTION_MATRIX_CHECKS]
    }
    by_check = {row["check"]: row for row in qualification["compatibility_checks"]}
    bound_checks = [
        {"check": c, "result": "pass", "evidence_sha256": _adoption_executed_hash(by_check[c])}
        for c in _ADOPTION_MATRIX_CHECKS
    ]

    rows: list[dict[str, Any]] = []

    receipt = _adoption_receipt("adopted")
    receipt["compatibility_checks"] = bound_checks
    accepted = build_adoption_receipt_matrix_decision(
        receipt,
        at_time="2026-07-19T12:00:00Z",
        qualification_bundle=qualification,
        release_publication_issues=[],
        capability_decision={"status": "accepted"},
        consumer_requirements_admission={"status": "accepted"},
        compatibility_decision={"compatible": True},
    )
    accept_ok = (
        accepted.get("status") == "accepted"
        and accepted.get("expected_decision") == "adopted"
        and validate_adoption_receipt_matrix_decision(accepted) == ()
    )
    rows.append({"case": "eligible_adopted_accepts", "passed": bool(accept_ok)})

    receipt = _adoption_receipt("adopted")
    receipt["compatibility_checks"] = bound_checks
    receipt["capability_decisions"][1]["decision"] = "rejected"
    optional_only = build_adoption_receipt_matrix_decision(
        receipt,
        at_time="2026-07-19T12:00:00Z",
        qualification_bundle=qualification,
        release_publication_issues=[],
        capability_decision={"status": "accepted"},
        consumer_requirements_admission={"status": "accepted"},
        compatibility_decision={"compatible": True},
    )
    optional_ok = (
        optional_only.get("status") == "rejected"
        and "optional_only_blocker" in (optional_only.get("rejection_reasons") or [])
        and validate_adoption_receipt_matrix_decision(optional_only) == ()
    )
    rows.append({"case": "optional_only_blocker_refused", "passed": bool(optional_ok)})

    receipt = _adoption_receipt("adopted")
    receipt["compatibility_checks"] = bound_checks
    receipt["capability_decisions"][0]["decision"] = "rejected"
    partial = build_adoption_receipt_matrix_decision(
        receipt,
        at_time="2026-07-19T12:00:00Z",
        qualification_bundle=qualification,
        release_publication_issues=[],
        capability_decision={"status": "accepted"},
        consumer_requirements_admission={"status": "accepted"},
        compatibility_decision={"compatible": True},
    )
    partial_ok = (
        partial.get("status") == "rejected"
        and "required_capability_coverage_partial" in (partial.get("rejection_reasons") or [])
        and validate_adoption_receipt_matrix_decision(partial) == ()
    )
    rows.append({"case": "partial_required_coverage_refused", "passed": bool(partial_ok)})

    stale_qual = {"compatibility_checks": [_adoption_qual_row(c) for c in _ADOPTION_MATRIX_CHECKS]}
    stale_qual["compatibility_checks"][0]["execution"] = {"status": "pass", "exit_code": 0}
    receipt = _adoption_receipt("adopted")
    receipt["compatibility_checks"] = [
        {"check": c, "result": "pass", "evidence_sha256": "0" * 64} for c in _ADOPTION_MATRIX_CHECKS
    ]
    expired = build_adoption_receipt_matrix_decision(
        receipt,
        at_time="2026-07-21T12:00:00Z",
        qualification_bundle=stale_qual,
        release_publication_issues=[],
        capability_decision={"status": "accepted"},
        consumer_requirements_admission={"status": "accepted"},
        compatibility_decision={"compatible": True},
    )
    expired_ok = (
        expired.get("status") == "rejected"
        and "decision_time_validity_failed" in (expired.get("rejection_reasons") or [])
        and "file_presence_only_claim" in (expired.get("rejection_reasons") or [])
        and validate_adoption_receipt_matrix_decision(expired) == ()
    )
    rows.append({"case": "expired_and_file_presence_only_refused", "passed": bool(expired_ok)})

    one = qualification["compatibility_checks"][0]
    receipt = _adoption_receipt("adopted")
    receipt["compatibility_checks"] = [
        {
            "check": "api_contract",
            "result": "pass",
            "evidence_sha256": _adoption_executed_hash(one),
        },
        {
            "check": "api_contract",
            "result": "pass",
            "evidence_sha256": _adoption_executed_hash(one),
        },
    ]
    dup = build_adoption_receipt_matrix_decision(
        receipt,
        at_time="2026-07-19T12:00:00Z",
        qualification_bundle=qualification,
    )
    dup_ok = (
        dup.get("status") == "rejected"
        and "compatibility_checks_missing_or_unknown" in (dup.get("rejection_reasons") or [])
        and "compatibility_checks_duplicate" in (dup.get("rejection_reasons") or [])
        and "required_executed_test_hashes_missing" in (dup.get("rejection_reasons") or [])
        and validate_adoption_receipt_matrix_decision(dup) == ()
    )
    rows.append({"case": "missing_duplicate_checks_refused", "passed": bool(dup_ok)})

    return {
        "check": "isolated_adoption_receipt_matrix",
        "passed": all(row["passed"] for row in rows),
        "cases": rows,
    }


def _check(name: str, passed: bool, **extra: Any) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), **extra}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    for runner, name in (
        (run_journal_dod_matrix, "isolated_journal_dod_matrix"),
        (run_circuit_breaker_matrix, "isolated_circuit_breaker_matrix"),
        (run_adoption_receipt_matrix, "isolated_adoption_receipt_matrix"),
    ):
        try:
            checks.append(runner())
        except Exception as exc:  # pragma: no cover - honest failure capture
            checks.append(_check(name, False, error=repr(exc)))

    evidence: dict[str, Any] = {
        "artifact_type": "isolated_main_consumer_dod_run",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authority_kind": "isolated_main_consumer",
        "is_real_comfyui_main": False,
        "producer_git_commit": _git_head(),
        "decided_at": DECIDED_AT,
        "checks": checks,
        "summary": {check["check"]: check["passed"] for check in checks},
        "claim_boundary": {
            "isolated_consumer_is_not_fixture_authority": True,
            "isolated_consumer_is_not_real_comfyui_main": True,
            "main_adoption_complete": False,
            "establishes_production_qualification": False,
            "advances": [
                "MF-P6-11.06 (full closed-state-machine journal DoD: replay idempotency, "
                "same-key/different-body + illegal-transition refusal, fork/delete/reorder "
                "detection, exact interruption reconstruction vs corrupted-history refusal)",
                "MF-P6-11.07 (circuit-breaker closed-permit/open-block/half-open-probe gating, "
                "no mask substitution)",
                "adoption-receipt admission matrix (eligible accept vs optional-only / "
                "partial-required / expired / file-presence-only / missing-duplicate refusals)",
            ],
            "hard_blockers_still_open": list(HARD_BLOCKERS_REQUIRING_REAL_MAIN),
            "advances_are_producer_isolated_only": True,
            "does_not_close_any_hard_blocker": True,
            "next_agent_step": (
                "Real receipts require a dedicated Comfy_UI_Main-side integration on an "
                "isolated clean maskfactory branch that consumes the producer adapter package "
                "and emits Main-signed adoption/qualification/adapter-execution/result-history "
                "artifacts pinned back here. Comfy_UI_Main is a dirty Wave64 tree and untouched."
            ),
        },
    }
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence["summary"], sort_keys=True))
    return 0 if all(check["passed"] for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
