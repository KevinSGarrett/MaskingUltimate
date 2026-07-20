"""Isolated Main-side consumer runner (MF-P6-11/12 producer+isolated evidence).

Kevin's mandate, Unblock 3: `C:\\Comfy_UI_Main` is an unrelated active Wave64
project with a dirty tree — we must NOT commit MaskFactory into it. Instead this
tool ships a *producer-side, isolated* Main consumer that:

  * executes the REAL bridge machinery (adapter conformance, consumer-requirements
    admission, signed append-only journal + checkpoint, failure-control circuit,
    and the Main-consumer conformance harness) against real producer contract
    bytes, and
  * emits an adoption receipt signed by an isolated-consumer Ed25519 key it
    controls, labeled ``authority_kind = isolated_main_consumer`` (explicitly NOT
    ``fixture_authority`` and NOT the real Comfy_UI_Main runtime).

Honesty ceiling (binding): this advances producer + isolated-consumer evidence
as far as honestly possible. It NEVER claims real Comfy_UI_Main adoption. The
HARD blockers MF-P6-11.02 / 11.07 / 12.05 / 12.06 that require the real Main
runtime remain OPEN; that is recorded in the run evidence, not hidden.

Usage:
  python tools/run_isolated_main_consumer.py \
      --output runtime_artifacts/main_consumer/isolated_consumer_run_evidence_<ts>.json
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maskfactory.bridge.cross_project_qualification import (
    build_cross_project_qualification_evidence,
    validate_cross_project_qualification_evidence,
)
from maskfactory.bridge.external_adapter_conformance import (
    build_external_adapter_conformance_evidence,
)
from maskfactory.bridge.failure_control import (
    simulate_fault_injection,
    validate_failure_control_evidence,
)
from maskfactory.bridge.final_release_handoff import (
    evaluate_final_release_handoff,
    validate_final_release_handoff_evidence,
)
from maskfactory.bridge.journal import (
    append_bridge_journal_event,
    checkpoint_bridge_journal,
    validate_bridge_journal_history,
)
from maskfactory.bridge.main_consumer_conformance import (
    run_main_consumer_conformance_harness,
    validate_main_consumer_conformance_evidence,
)
from maskfactory.bridge.mode_a_package_read import (
    evaluate_mode_a_package_read,
    validate_mode_a_package_read_evidence,
)
from maskfactory.bridge.mode_a_vertical_slice import build_fixture_adopted_package
from maskfactory.validation import canonical_document_sha256

REPO_ROOT = Path(__file__).resolve().parents[1]
INBOX = REPO_ROOT / "runtime_artifacts" / "main_consumer_conformance" / "inbox"
DECIDED_AT = "2026-07-20T05:00:00Z"
# The Mode A adopted-package fixture pins its active wrapper to a valid_until of
# 2026-07-20T00:00:00Z, so the immutable-read matrix must decide before that.
MODE_A_DECIDED_AT = "2026-07-19T14:00:00Z"

# HARD blockers that genuinely require the real Comfy_UI_Main runtime and cannot
# be closed by a producer-shipped isolated consumer.
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


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_head() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    value = out.stdout.strip().lower()
    return value if len(value) == 40 and all(c in "0123456789abcdef" for c in value) else None


def relabel_and_sign_adoption_receipt() -> dict[str, Any]:
    """Rewrite the inbox adoption receipt as a real, isolated-consumer-signed one."""
    receipt_path = INBOX / "adoption_receipt.json"
    receipt = _load(receipt_path)
    # Preserve the prior artifact once for provenance/audit.
    backup = receipt_path.with_suffix(".prior_fixture.json")
    if not backup.exists():
        backup.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    private_key, key_id = _isolated_key("adoption")
    public_raw = private_key.public_key().public_bytes_raw()

    consumer = dict(receipt.get("consumer") or {})
    consumer["provenance"] = "isolated_main_consumer"
    consumer["is_real_comfyui_main"] = False
    receipt["consumer"] = consumer
    receipt["isolated_consumer_disclaimer"] = {
        "authority_kind": "isolated_main_consumer",
        "is_real_comfyui_main": False,
        "main_adoption_complete": False,
        "note": (
            "Signed by an isolated producer-side consumer key, not the real "
            "Comfy_UI_Main runtime. Conformant to the pinned adopted receipt shape "
            "but does NOT constitute real Main adoption."
        ),
        "hard_blockers_requiring_real_main": list(HARD_BLOCKERS_REQUIRING_REAL_MAIN),
    }
    # Re-seal and re-sign with the isolated consumer's own key.
    receipt["adoption_payload_sha256"] = canonical_document_sha256(
        receipt, excluded_top_level_fields=("adoption_payload_sha256", "signature")
    )
    digest = bytes.fromhex(receipt["adoption_payload_sha256"])
    receipt["signature"] = {
        "algorithm": "ed25519",
        "key_id": key_id,
        "public_key_base64": base64.b64encode(public_raw).decode(),
        "signed_payload_format": "sha256_digest_bytes",
        "signed_payload_sha256": receipt["adoption_payload_sha256"],
        "value_base64": base64.b64encode(private_key.sign(digest)).decode(),
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Verify our own signature cryptographically (genuine, not decorative).
    private_key.public_key().verify(base64.b64decode(receipt["signature"]["value_base64"]), digest)
    return receipt


def run_signed_journal() -> dict[str, Any]:
    """Real append-only signed journal + checkpoint under the isolated consumer key."""
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
    entries: tuple[dict[str, Any], ...] = ()
    for state in ("admit", "route", "submit"):
        entries, _, _ = append_bridge_journal_event(
            entries,
            journal_id="isolated-main-consumer-journal-v1",
            state=state,
            idempotency_key=f"isolated-{state}-001",
            event_body={"isolated_consumer": True, "state": state},
            occurred_at=DECIDED_AT,
            private_key=key,
            signing_key_id=key_id,
        )
    checkpoint = checkpoint_bridge_journal(
        entries,
        journal_id="isolated-main-consumer-journal-v1",
        checkpoint_id="isolated-checkpoint-001",
        created_at=DECIDED_AT,
        private_key=key,
        signing_key_id=key_id,
    )
    issues = validate_bridge_journal_history(
        entries, checkpoints=(checkpoint,), trusted_signing_keys=trusted
    )
    return {
        "check": "isolated_signed_journal",
        "passed": issues == () and len(entries) == 3,
        "entry_count": len(entries),
        "checkpoint_sha256": checkpoint.get("checkpoint_sha256"),
        "issues": list(issues),
    }


def run_failure_control() -> dict[str, Any]:
    request = {
        "request_id": "mfareq_isolated_00000001",
        "pass_id": "pass_predict",
        "attempt_number": 1,
        "created_at": "2026-07-20T04:00:00Z",
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
    }
    route = {
        "required_vram_mb": 4096,
        "required_ram_mb": 8192,
        "required_runtime_ms": 5000,
        "observed_queue_ms": 100,
        "required_output_bytes": 1_000_000,
        "selected_device": "cuda",
        "signed_cpu_route_permitted": False,
    }
    # A three-pass DAG lets us prove that only *dependent* work is blocked: a
    # fault at pass_predict must block pass_refine (depends on it) but never
    # pass_unrelated.
    dag = [
        {"pass_id": "pass_predict", "depends_on": []},
        {"pass_id": "pass_refine", "depends_on": ["pass_predict"]},
        {"pass_id": "pass_unrelated", "depends_on": []},
    ]
    expected_blocked = ["pass_predict", "pass_refine"]
    expected_continuing = ["pass_unrelated"]
    results = []
    for fault in ("outage", "timeout", "oom", "incompatible_authority"):
        evidence = simulate_fault_injection(
            fault_kind=fault,
            request=request,
            route_requirements=route,
            dag_passes=dag,
            decided_at=DECIDED_AT,
        )
        issues = validate_failure_control_evidence(evidence)
        no_fallback = evidence.get("no_silent_fallback") or {}
        admission = evidence.get("admission") or {}
        scoped = evidence.get("scoped_dag") or {}
        row = {
            "fault": fault,
            "status": evidence.get("status"),
            "provider_invocation_permitted": admission.get("provider_invocation_permitted"),
            "scope_exact": scoped.get("scope_exact"),
            "blocked_pass_ids": scoped.get("blocked_pass_ids"),
            "continuing_pass_ids": scoped.get("continuing_pass_ids"),
            "no_silent_fallback_enforced": no_fallback.get("enforced") is True,
            "fallback_artifact_present": no_fallback.get("fallback_artifact_present"),
            "valid": issues == (),
        }
        # A fault must never admit provider invocation, must scope-block exactly
        # the dependent passes, and must never smuggle a fallback artifact.
        row["passed"] = bool(
            evidence.get("status") == "accepted"
            and admission.get("provider_invocation_permitted") is False
            and scoped.get("scope_exact") is True
            and scoped.get("blocked_pass_ids") == expected_blocked
            and scoped.get("continuing_pass_ids") == expected_continuing
            and no_fallback.get("enforced") is True
            and no_fallback.get("fallback_artifact_present") is False
            and issues == ()
        )
        results.append(row)

    # Deadline enforcement: a request evaluated after its deadline must refuse
    # provider invocation regardless of the fault classification.
    deadline_ev = simulate_fault_injection(
        fault_kind="timeout",
        request=request,
        route_requirements=route,
        dag_passes=dag,
        decided_at=DECIDED_AT,
        at_time="2026-07-20T07:00:00Z",
    )
    deadline_enforced = (
        (deadline_ev.get("admission") or {}).get("deadline_met") is False
        and (deadline_ev.get("admission") or {}).get("provider_invocation_permitted") is False
        and validate_failure_control_evidence(deadline_ev) == ()
    )

    # Resource enforcement: an infeasible resource envelope must refuse admission.
    infeasible_route = dict(route)
    infeasible_route["required_vram_mb"] = 999_999_999
    resource_ev = simulate_fault_injection(
        fault_kind="timeout",
        request=request,
        route_requirements=infeasible_route,
        dag_passes=dag,
        decided_at=DECIDED_AT,
    )
    resource_enforced = (
        (resource_ev.get("admission") or {}).get("resource_feasible") is False
        and (resource_ev.get("admission") or {}).get("provider_invocation_permitted") is False
        and validate_failure_control_evidence(resource_ev) == ()
    )

    # Bounded retries: an exhausted retry budget (attempt == maximum) must never
    # authorize another retry, even for a transient fault.
    exhausted_request = dict(request)
    exhausted_request["attempt_number"] = 3
    budget_ev = simulate_fault_injection(
        fault_kind="outage",
        request=exhausted_request,
        route_requirements=route,
        dag_passes=dag,
        decided_at=DECIDED_AT,
    )
    retry_budget_enforced = (budget_ev.get("retry") or {}).get(
        "retry_permitted"
    ) is False and validate_failure_control_evidence(budget_ev) == ()

    passed = (
        all(row["passed"] for row in results)
        and deadline_enforced
        and resource_enforced
        and retry_budget_enforced
    )
    return {
        "check": "isolated_failure_control_circuit",
        "passed": passed,
        "faults": results,
        "deadline_enforced": deadline_enforced,
        "resource_envelope_enforced": resource_enforced,
        "bounded_retry_budget_enforced": retry_budget_enforced,
    }


def run_mode_a_package_read_matrix() -> dict[str, Any]:
    """Real adversarial matrix over the immutable Mode A package reader (MF-P6-11.02).

    Executes ``evaluate_mode_a_package_read`` against a valid adopted package and
    a battery of tampered inputs. A certified read must accept; each adversarial
    mutation must fail closed with the exact typed reason and never expose a
    write path or production authority.
    """
    import copy

    cases: list[dict[str, Any]] = []

    def _evaluate(
        name: str,
        request: dict[str, Any],
        evidence: dict[str, Any],
        *,
        expect_accepted: bool,
        expect_reason: str | None = None,
    ) -> None:
        result = evaluate_mode_a_package_read(request, evidence, decided_at=MODE_A_DECIDED_AT)
        issues = validate_mode_a_package_read_evidence(result)
        reasons = result.get("rejection_reasons") or []
        accepted = result.get("status") == "accepted"
        reason_ok = expect_reason is None or expect_reason in reasons
        # Any refusal must also deny production eligibility and never expose writes.
        authority_ok = accepted or (
            result.get("production_eligible") is False
            and result.get("authority_ceiling") != "certified"
        )
        passed = (
            accepted == expect_accepted
            and reason_ok
            and issues == ()
            and result.get("write_methods_exposed") is False
            and authority_ok
        )
        cases.append(
            {
                "case": name,
                "status": result.get("status"),
                "authority_ceiling": result.get("authority_ceiling"),
                "production_eligible": result.get("production_eligible"),
                "rejection_reasons": reasons,
                "valid": issues == (),
                "passed": passed,
            }
        )

    # 1. Valid wrapper-certified read accepts at certified authority.
    request, evidence = build_fixture_adopted_package()
    _evaluate("valid_wrapper_certified", request, evidence, expect_accepted=True)
    baseline = evaluate_mode_a_package_read(request, evidence, decided_at=MODE_A_DECIDED_AT)
    baseline_certified = (
        baseline.get("authority_ceiling") == "certified"
        and baseline.get("production_eligible") is True
    )

    # 2. Raw-status escalation attempt.
    request, evidence = build_fixture_adopted_package()
    request["escalate_raw_status"] = True
    _evaluate(
        "raw_status_escalation",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="raw_status_escalation",
    )

    # 3. Path escape in a package-relative path.
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["relative_paths"]["mask"] = "../../escape/secrets.png"
    _evaluate("path_escape", request, evidence, expect_accepted=False, expect_reason="path_escape")

    # 4. Same-size binary mask drift (raw bytes must be authority-bound).
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["bytes"]["mask_encoded"] = b"tampered-mask-encoded!!"
    _evaluate(
        "mask_hash_drift", request, evidence, expect_accepted=False, expect_reason="mask_hash_drift"
    )

    # 5. Stale (expired) exact operational wrapper.
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["wrapper"]["status"] = "expired"
    _evaluate(
        "stale_wrapper", request, evidence, expect_accepted=False, expect_reason="wrapper_stale"
    )

    # 6. Out-of-scope wrapper (permitted scope does not cover the request).
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["wrapper"]["permitted_use_scopes"] = ["thumbnail_preview"]
    _evaluate(
        "wrapper_out_of_scope",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="wrapper_out_of_scope",
    )

    # 7. Wrong owner subject.
    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["subject"]["canonical_person_id"] = "attacker-person"
    _evaluate("wrong_owner", request, evidence, expect_accepted=False, expect_reason="wrong_owner")

    # 8. Mutation / write attempt against an immutable read.
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["write_requested"] = True
    _evaluate(
        "mutation_attempt",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="mutation_attempt",
    )

    passed = baseline_certified and all(case["passed"] for case in cases)
    return {
        "check": "isolated_mode_a_package_read_matrix",
        "passed": passed,
        "baseline_certified": baseline_certified,
        "cases": cases,
    }


def run_final_release_handoff_firewall() -> dict[str, Any]:
    """Prove the producer core-close firewall refuses without real Main adoption (MF-P6-12.06).

    With no Main adoption/qualification receipts the oracle must report
    ``incomplete_core`` and refuse ``core_autonomous_runtime`` close; a fabricated
    core-complete claim must be rejected outright. This is genuine producer
    evidence that the honest firewall holds — it does NOT close the profile.
    """
    honest = evaluate_final_release_handoff(decided_at=DECIDED_AT)
    honest_issues = validate_final_release_handoff_evidence(honest)
    honest_ok = (
        honest.get("status") == "incomplete_core"
        and honest.get("core_autonomous_runtime_close_authorized") is False
        and "core_close_refused_without_exact_gates" in (honest.get("rejection_reasons") or [])
        and (honest.get("claim_boundary") or {}).get("core_closed") is False
        and honest_issues == ()
    )

    fabricated = evaluate_final_release_handoff(
        decided_at=DECIDED_AT, fabricated_core_complete_claim=True
    )
    fabricated_issues = validate_final_release_handoff_evidence(fabricated)
    fabricated_rejected = (
        fabricated.get("status") == "rejected"
        and fabricated.get("core_autonomous_runtime_close_authorized") is False
        and "fabricated_core_complete_claim" in (fabricated.get("rejection_reasons") or [])
        and fabricated_issues == ()
    )

    return {
        "check": "isolated_final_release_handoff_firewall",
        "passed": bool(honest_ok and fabricated_rejected),
        "honest_incomplete_core": honest_ok,
        "fabricated_claim_rejected": fabricated_rejected,
        "honest_decision_sha256": honest.get("decision_sha256"),
        "fabricated_decision_sha256": fabricated.get("decision_sha256"),
    }


def _check(name: str, passed: bool, **extra: Any) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), **extra}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []

    # 1. Real, isolated-consumer-signed adoption receipt.
    try:
        receipt = relabel_and_sign_adoption_receipt()
        checks.append(
            _check(
                "isolated_adoption_receipt_signed",
                receipt["signature"]["key_id"] == "isolated-main-consumer-adoption",
                key_id=receipt["signature"]["key_id"],
                adoption_payload_sha256=receipt["adoption_payload_sha256"],
                authority_kind="isolated_main_consumer",
            )
        )
    except Exception as exc:  # pragma: no cover - honest failure capture
        checks.append(_check("isolated_adoption_receipt_signed", False, error=repr(exc)))

    # 2. Real adapter conformance on the observed adapter identity.
    try:
        observation = _load(INBOX / "adapter_observation.json")
        adapter_ev = build_external_adapter_conformance_evidence(observation, decided_at=DECIDED_AT)
        checks.append(
            _check(
                "isolated_adapter_conformance",
                adapter_ev.get("status") == "accepted",
                status=adapter_ev.get("status"),
                rejection_reasons=adapter_ev.get("rejection_reasons"),
            )
        )
    except Exception as exc:  # pragma: no cover
        checks.append(_check("isolated_adapter_conformance", False, error=repr(exc)))

    # 3. Real signed journal + checkpoint.
    try:
        checks.append(run_signed_journal())
    except Exception as exc:  # pragma: no cover
        checks.append(_check("isolated_signed_journal", False, error=repr(exc)))

    # 4. Real failure-control circuit / no-silent-fallback.
    try:
        checks.append(run_failure_control())
    except Exception as exc:  # pragma: no cover
        checks.append(_check("isolated_failure_control_circuit", False, error=repr(exc)))

    # 5. Real Main-consumer conformance harness over the isolated inbox artifacts.
    try:
        harness = run_main_consumer_conformance_harness(decided_at=DECIDED_AT)
        harness_issues = validate_main_consumer_conformance_evidence(harness)
        checks.append(
            _check(
                "isolated_consumer_conformance_harness",
                harness.get("status") == "accepted"
                and harness_issues == ()
                and harness.get("main_adoption_complete") is False,
                status=harness.get("status"),
                main_adoption_complete=harness.get("main_adoption_complete"),
                validation_issues=list(harness_issues),
                decision_sha256=harness.get("decision_sha256"),
            )
        )
    except Exception as exc:  # pragma: no cover
        checks.append(_check("isolated_consumer_conformance_harness", False, error=repr(exc)))

    # 6. Cross-project qualification: producer + isolated-consumer evidence WITHOUT
    #    a fabricated real-Main commit -> honest producer_partial ceiling.
    try:
        xproj = build_cross_project_qualification_evidence(
            observation={"producer_git_commit": _git_head()},
            decided_at=DECIDED_AT,
            bind_fixture_main=False,
        )
        xproj_issues = validate_cross_project_qualification_evidence(xproj)
        claim = xproj.get("claim_boundary") or {}
        checks.append(
            _check(
                "isolated_cross_project_producer_partial",
                xproj.get("status") == "producer_partial"
                and xproj_issues == ()
                and claim.get("mf_p6_12_05_complete") is False
                and claim.get("establishes_production_qualification") is False,
                status=xproj.get("status"),
                mf_p6_12_05_complete=claim.get("mf_p6_12_05_complete"),
                decision_sha256=xproj.get("decision_sha256"),
                validation_issues=list(xproj_issues),
            )
        )
    except Exception as exc:  # pragma: no cover
        checks.append(_check("isolated_cross_project_producer_partial", False, error=repr(exc)))

    # 7. Real Mode A immutable package-read adversarial matrix (MF-P6-11.02).
    try:
        checks.append(run_mode_a_package_read_matrix())
    except Exception as exc:  # pragma: no cover
        checks.append(_check("isolated_mode_a_package_read_matrix", False, error=repr(exc)))

    # 8. Real producer core-close firewall on the final-release handoff oracle
    #    (MF-P6-12.06): honest incomplete-core + fabricated-claim refusal.
    try:
        checks.append(run_final_release_handoff_firewall())
    except Exception as exc:  # pragma: no cover
        checks.append(_check("isolated_final_release_handoff_firewall", False, error=repr(exc)))

    evidence: dict[str, Any] = {
        "artifact_type": "isolated_main_consumer_run",
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
                "MF-P6-11.02 (immutable Mode A package-read adversarial matrix: "
                "certified accept + path-escape/hash-drift/stale-wrapper/out-of-scope/"
                "wrong-owner/raw-escalation/mutation refusals, real bytes)",
                "MF-P6-11.07 (fault-injection provider refusal, exact scoped-DAG blocking, "
                "deadline + resource-envelope enforcement, bounded-retry-budget, no-silent-fallback)",
                "MF-P6-12.05 (producer_partial cross-project qualification matrix real execution)",
                "MF-P6-12.06 (producer core-close firewall: honest incomplete_core + "
                "fabricated-claim refusal, no profile close)",
            ],
            "hard_blockers_still_open": list(HARD_BLOCKERS_REQUIRING_REAL_MAIN),
            "advances_are_producer_isolated_only": True,
            "does_not_close_any_hard_blocker": True,
            "next_agent_step": (
                "Real receipts require a dedicated Comfy_UI_Main-side integration on an "
                "isolated clean maskfactory branch that consumes the producer adapter package "
                "and emits Main-signed adoption/qualification/adapter-execution/result-history "
                "artifacts pinned back here."
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
