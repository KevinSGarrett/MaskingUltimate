"""Isolated Main-consumer climb-4 runner (MF-P6-11.02 / 11.07 depth).

Fourth standalone sibling of ``tools/run_isolated_main_consumer.py``. Durable under
multi-agent working-tree churn (do NOT fold into the shared runner). Deepens:

  * ``isolated_mode_a_package_read_matrix`` (MF-P6-11.02): 30 real adversarial
    cases over ``evaluate_mode_a_package_read`` (certified + multi-person accept,
    QA/diagnostic noncertified ceiling, path/hash/wrapper/catalog/revocation/
    transform/person/release/mutation refusals).
  * ``isolated_failure_control_circuit`` (MF-P6-11.07): fault-injection + healthy
    admit + open/half-open circuit gating + silent-fallback refuse + scoped-DAG
    over/under + incoherent-retry reject + deadline/resource/retry-budget.

Honesty ceiling: producer-side, isolated-consumer-signed only. NEVER claims real
Comfy_UI_Main adoption. HARD MF-P6-11.02 / 11.07 / 12.05 / 12.06 remain OPEN.
Comfy_UI_Main dirty Wave64 tree is NOT touched.

Usage:
  python tools/run_isolated_main_consumer_climb4.py \\
      --output runtime_artifacts/main_consumer/isolated_consumer_climb4_run_evidence_<ts>.json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maskfactory.bridge.failure_control import (
    build_failure_control_evidence,
    simulate_fault_injection,
    validate_failure_control_evidence,
)
from maskfactory.bridge.mode_a_package_read import (
    evaluate_mode_a_package_read,
    validate_mode_a_package_read_evidence,
)
from maskfactory.bridge.mode_a_vertical_slice import build_fixture_adopted_package
from maskfactory.validation import canonical_document_sha256

REPO_ROOT = Path(__file__).resolve().parents[1]
DECIDED_AT = "2026-07-20T05:00:00Z"
MODE_A_DECIDED_AT = "2026-07-19T14:00:00Z"

HARD_BLOCKERS_REQUIRING_REAL_MAIN = (
    "MF-P6-11.02",
    "MF-P6-11.07",
    "MF-P6-12.05",
    "MF-P6-12.06",
)


def _git_head() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    value = out.stdout.strip().lower()
    return value if len(value) == 40 and all(c in "0123456789abcdef" for c in value) else None


def _fc_circuit(*, state: str = "closed", half_open_probe_allowed: bool = False) -> dict[str, Any]:
    body = {
        "route_key": "mode-b/predict",
        "release_id": "mfrel_isolated_circuit_climb4",
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


def run_failure_control_depth() -> dict[str, Any]:
    request = {
        "request_id": "mfareq_isolated_climb4_0001",
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
    dag = [
        {"pass_id": "pass_predict", "depends_on": []},
        {"pass_id": "pass_refine", "depends_on": ["pass_predict"]},
        {"pass_id": "pass_unrelated", "depends_on": []},
    ]
    expected_blocked = ["pass_predict", "pass_refine"]
    expected_continuing = ["pass_unrelated"]
    results: list[dict[str, Any]] = []
    for fault in ("outage", "timeout", "oom", "incompatible_authority"):
        evidence = simulate_fault_injection(
            fault_kind=fault,
            request=request,
            route_requirements=route,
            dag_passes=dag,
            decided_at=DECIDED_AT,
        )
        issues = validate_failure_control_evidence(evidence)
        admission = evidence.get("admission") or {}
        scoped = evidence.get("scoped_dag") or {}
        no_fallback = evidence.get("no_silent_fallback") or {}
        results.append(
            {
                "fault": fault,
                "status": evidence.get("status"),
                "passed": bool(
                    evidence.get("status") == "accepted"
                    and admission.get("provider_invocation_permitted") is False
                    and scoped.get("scope_exact") is True
                    and scoped.get("blocked_pass_ids") == expected_blocked
                    and scoped.get("continuing_pass_ids") == expected_continuing
                    and no_fallback.get("enforced") is True
                    and no_fallback.get("fallback_artifact_present") is False
                    and issues == ()
                ),
            }
        )

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

    infeasible_route = dict(route, required_vram_mb=999_999_999)
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

    budget_ev = simulate_fault_injection(
        fault_kind="outage",
        request=dict(request, attempt_number=3),
        route_requirements=route,
        dag_passes=dag,
        decided_at=DECIDED_AT,
    )
    retry_budget_enforced = (budget_ev.get("retry") or {}).get(
        "retry_permitted"
    ) is False and validate_failure_control_evidence(budget_ev) == ()

    def _obs(circuit: dict[str, Any], **extra: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "at_time": DECIDED_AT,
            "request": request,
            "route_requirements": route,
            "failure": {},
            "main_circuit_evidence": circuit,
            "main_retry_evidence": {},
            "main_scoped_block_evidence": {},
            "fallback_attempt": {},
            "dag_passes": dag,
        }
        body.update(extra)
        return body

    healthy_ev = build_failure_control_evidence(
        _obs(_fc_circuit(state="closed")), decided_at=DECIDED_AT
    )
    healthy_admits = (
        healthy_ev.get("status") == "accepted"
        and (healthy_ev.get("admission") or {}).get("provider_invocation_permitted") is True
        and (healthy_ev.get("circuit") or {}).get("blocks_route") is False
        and (healthy_ev.get("no_silent_fallback") or {}).get("fallback_artifact_present") is False
        and validate_failure_control_evidence(healthy_ev) == ()
    )

    open_ev = build_failure_control_evidence(_obs(_fc_circuit(state="open")), decided_at=DECIDED_AT)
    circuit_open_blocks = (
        (open_ev.get("circuit") or {}).get("state") == "open"
        and (open_ev.get("circuit") or {}).get("blocks_route") is True
        and (open_ev.get("admission") or {}).get("provider_invocation_permitted") is False
        and (open_ev.get("no_silent_fallback") or {}).get("fallback_artifact_present") is False
        and validate_failure_control_evidence(open_ev) == ()
    )

    half_blocked_ev = build_failure_control_evidence(
        _obs(_fc_circuit(state="half_open", half_open_probe_allowed=False)),
        decided_at=DECIDED_AT,
    )
    half_probe_ev = build_failure_control_evidence(
        _obs(_fc_circuit(state="half_open", half_open_probe_allowed=True)),
        decided_at=DECIDED_AT,
    )
    half_open_gated = (
        (half_blocked_ev.get("admission") or {}).get("provider_invocation_permitted") is False
        and (half_probe_ev.get("admission") or {}).get("provider_invocation_permitted") is True
        and validate_failure_control_evidence(half_blocked_ev) == ()
        and validate_failure_control_evidence(half_probe_ev) == ()
    )

    fallback_ev = build_failure_control_evidence(
        _obs(
            _fc_circuit(state="closed"),
            fallback_attempt={
                "artifact_present": True,
                "artifact_kind": "empty_mask",
                "allow_silent_fallback": False,
            },
        ),
        decided_at=DECIDED_AT,
    )
    fallback_refused = (
        fallback_ev.get("status") == "rejected"
        and "silent_fallback_forbidden" in (fallback_ev.get("rejection_reasons") or [])
        and "fallback_artifact_present" in (fallback_ev.get("rejection_reasons") or [])
        and (fallback_ev.get("admission") or {}).get("provider_invocation_permitted") is False
        and (fallback_ev.get("no_silent_fallback") or {}).get("fallback_artifact_present") is True
        and (fallback_ev.get("no_silent_fallback") or {}).get("enforced") is True
        and validate_failure_control_evidence(fallback_ev) == ()
    )

    overreach_ev = build_failure_control_evidence(
        {
            "at_time": DECIDED_AT,
            "request": request,
            "route_requirements": route,
            "failure": {"fault_kind": "outage"},
            "main_circuit_evidence": _fc_circuit(state="closed"),
            "main_retry_evidence": {},
            "main_scoped_block_evidence": {
                "blocked_pass_ids": ["pass_predict", "pass_refine", "pass_unrelated"],
                "continuing_pass_ids": [],
                "contains_fallback_artifact": False,
            },
            "fallback_attempt": {},
            "dag_passes": dag,
        },
        decided_at=DECIDED_AT,
    )
    underreach_ev = build_failure_control_evidence(
        {
            "at_time": DECIDED_AT,
            "request": request,
            "route_requirements": route,
            "failure": {"fault_kind": "outage"},
            "main_circuit_evidence": _fc_circuit(state="closed"),
            "main_retry_evidence": {},
            "main_scoped_block_evidence": {
                "blocked_pass_ids": ["pass_predict"],
                "continuing_pass_ids": ["pass_refine", "pass_unrelated"],
                "contains_fallback_artifact": False,
            },
            "fallback_attempt": {},
            "dag_passes": dag,
        },
        decided_at=DECIDED_AT,
    )
    scoped_overreach_rejected = (overreach_ev.get("scoped_dag") or {}).get(
        "scope_exact"
    ) is False and (overreach_ev.get("admission") or {}).get(
        "provider_invocation_permitted"
    ) is False
    scoped_underreach_rejected = (underreach_ev.get("scoped_dag") or {}).get(
        "scope_exact"
    ) is False and (underreach_ev.get("admission") or {}).get(
        "provider_invocation_permitted"
    ) is False

    bad_retry_ev = build_failure_control_evidence(
        {
            "at_time": DECIDED_AT,
            "request": request,
            "route_requirements": route,
            "failure": {"fault_kind": "incompatible_authority"},
            "main_circuit_evidence": _fc_circuit(state="closed"),
            "main_retry_evidence": {
                "retry_requested": True,
                "retry_reason": "authority_mismatch",
                "allow_silent_fallback": False,
            },
            "main_scoped_block_evidence": {},
            "fallback_attempt": {},
            "dag_passes": dag,
        },
        decided_at=DECIDED_AT,
    )
    bad_retry_rejected = (
        bad_retry_ev.get("status") == "rejected"
        and bool(
            {"main_retry_evidence_invalid", "non_transient_retry_forbidden"}
            & set(bad_retry_ev.get("rejection_reasons") or [])
        )
        and (bad_retry_ev.get("admission") or {}).get("provider_invocation_permitted") is False
    )

    passed = (
        all(row["passed"] for row in results)
        and deadline_enforced
        and resource_enforced
        and retry_budget_enforced
        and healthy_admits
        and circuit_open_blocks
        and half_open_gated
        and fallback_refused
        and scoped_overreach_rejected
        and scoped_underreach_rejected
        and bad_retry_rejected
    )
    return {
        "check": "isolated_failure_control_circuit",
        "passed": passed,
        "faults": results,
        "deadline_enforced": deadline_enforced,
        "resource_envelope_enforced": resource_enforced,
        "bounded_retry_budget_enforced": retry_budget_enforced,
        "healthy_admission_permits_provider": healthy_admits,
        "circuit_open_blocks_route": circuit_open_blocks,
        "half_open_probe_gated": half_open_gated,
        "silent_fallback_refused": fallback_refused,
        "scoped_dag_overreach_rejected": scoped_overreach_rejected,
        "scoped_dag_underreach_rejected": scoped_underreach_rejected,
        "incoherent_main_retry_rejected": bad_retry_rejected,
    }


def run_mode_a_package_read_matrix() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []

    def _evaluate(
        name: str,
        request: dict[str, Any],
        evidence: dict[str, Any],
        *,
        expect_accepted: bool,
        expect_reason: str | None = None,
        expect_ceiling: str | None = None,
        expect_production_eligible: bool | None = None,
    ) -> None:
        result = evaluate_mode_a_package_read(request, evidence, decided_at=MODE_A_DECIDED_AT)
        issues = validate_mode_a_package_read_evidence(result)
        reasons = result.get("rejection_reasons") or []
        accepted = result.get("status") == "accepted"
        reason_ok = expect_reason is None or expect_reason in reasons
        ceiling_ok = expect_ceiling is None or result.get("authority_ceiling") == expect_ceiling
        prod_ok = (
            expect_production_eligible is None
            or result.get("production_eligible") is expect_production_eligible
        )
        authority_ok = accepted or (
            result.get("production_eligible") is False
            and result.get("authority_ceiling") != "certified"
        )
        passed = (
            accepted == expect_accepted
            and reason_ok
            and ceiling_ok
            and prod_ok
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

    request, evidence = build_fixture_adopted_package()
    _evaluate("valid_wrapper_certified", request, evidence, expect_accepted=True)
    baseline = evaluate_mode_a_package_read(request, evidence, decided_at=MODE_A_DECIDED_AT)
    baseline_certified = (
        baseline.get("authority_ceiling") == "certified"
        and baseline.get("production_eligible") is True
    )

    request, evidence = build_fixture_adopted_package()
    request["escalate_raw_status"] = True
    _evaluate(
        "raw_status_escalation",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="raw_status_escalation",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["relative_paths"]["mask"] = "../../escape/secrets.png"
    _evaluate("path_escape", request, evidence, expect_accepted=False, expect_reason="path_escape")

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["bytes"]["mask_encoded"] = b"tampered-mask-encoded!!"
    _evaluate(
        "mask_hash_drift", request, evidence, expect_accepted=False, expect_reason="mask_hash_drift"
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["wrapper"]["status"] = "expired"
    _evaluate(
        "stale_wrapper", request, evidence, expect_accepted=False, expect_reason="wrapper_stale"
    )

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

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["subject"]["canonical_person_id"] = "attacker-person"
    _evaluate("wrong_owner", request, evidence, expect_accepted=False, expect_reason="wrong_owner")

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

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    evidence = copy.deepcopy(evidence)
    request["exact_use_scope"] = "qa"
    evidence["wrapper"] = None
    _evaluate(
        "qa_noncertified_read_accepts_capped",
        request,
        evidence,
        expect_accepted=True,
        expect_ceiling="qa_passed_noncertified",
        expect_production_eligible=False,
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["wrapper"] = None
    _evaluate(
        "wrapper_missing_production",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="wrapper_missing",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["wrapper"]["revocation_status"] = "revoked"
    _evaluate(
        "wrapper_revoked",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="wrapper_revoked",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["catalog"]["adoption_decision"] = "pending"
    _evaluate(
        "catalog_not_adopted",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="catalog_not_adopted",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["bytes"]["source_encoded"] = b"tampered-source-encoded!"
    _evaluate(
        "source_hash_drift",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="source_hash_drift",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["bytes"]["manifest"] = b'{"parts":{"left_forearm":{"status":"tampered"}}}'
    _evaluate(
        "manifest_hash_drift",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="manifest_hash_drift",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["catalog"]["packages"][0]["package_sha256"] = "0" * 64
    _evaluate(
        "package_hash_drift",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="package_hash_drift",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["ontology_version"] = "body_parts_v2"
    _evaluate(
        "ontology_mismatch",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="ontology_mismatch",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["subject"]["scene_instance_id"] = "scene-instance-attacker"
    _evaluate(
        "instance_mismatch",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="instance_mismatch",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["subject"]["character_revision"] = "char-rev-attacker"
    _evaluate(
        "character_revision_mismatch",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="character_revision_mismatch",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["raw_part_status"] = "rejected_needs_fix"
    _evaluate(
        "rejected_part_status",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="rejected_part_status",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["bytes"]["revocation_identity"] = b"not-a-signed-revocation-record"
    _evaluate(
        "revocation_not_current",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="revocation_not_current",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["catalog"]["packages"][0]["transform_chain_sha256"] = "a" * 64
    _evaluate(
        "transform_drift",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="transform_drift",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["artifact_kind"] = "refinement"
    request["claim_parent_authority"] = True
    _evaluate(
        "derived_authority_escalation",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="derived_authority_escalation",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    evidence = copy.deepcopy(evidence)
    request["claimed_authority_state"] = "certified"
    evidence["wrapper"] = None
    _evaluate(
        "claimed_certified_without_wrapper",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="raw_status_escalation",
    )

    request, evidence = build_fixture_adopted_package(person_index=1)
    _evaluate(
        "multi_person_wrapper_certified",
        request,
        evidence,
        expect_accepted=True,
        expect_ceiling="certified",
        expect_production_eligible=True,
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["person_index"] = 9
    _evaluate(
        "missing_person_catalog_refused",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="catalog_not_adopted",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["bytes"]["release"] = b"tampered-release-bytes"
    _evaluate(
        "release_capability_drift",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="release_capability_drift",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    evidence = copy.deepcopy(evidence)
    request["exact_use_scope"] = "diagnostic"
    evidence["wrapper"] = None
    _evaluate(
        "diagnostic_noncertified_accepts_capped",
        request,
        evidence,
        expect_accepted=True,
        expect_ceiling="qa_passed_noncertified",
        expect_production_eligible=False,
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["mutation_target"] = "masks/left_forearm.png"
    _evaluate(
        "mutation_target_write_forbidden",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="mutation_attempt",
    )

    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["bytes"]["source_decoded_pixels"] = b"tampered-source-pixels!!"
    _evaluate(
        "source_pixel_hash_drift",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="source_hash_drift",
    )

    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["raw_part_status"] = "withdrawn"
    _evaluate(
        "withdrawn_part_status",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="rejected_part_status",
    )

    passed = baseline_certified and all(case["passed"] for case in cases)
    return {
        "check": "isolated_mode_a_package_read_matrix",
        "passed": passed,
        "baseline_certified": baseline_certified,
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    for runner in (run_mode_a_package_read_matrix, run_failure_control_depth):
        try:
            checks.append(runner())
        except Exception as exc:  # honest failure capture
            checks.append({"check": runner.__name__, "passed": False, "error": repr(exc)})

    evidence: dict[str, Any] = {
        "artifact_type": "isolated_main_consumer_climb4_run",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authority_kind": "isolated_main_consumer",
        "is_real_comfyui_main": False,
        "producer_git_commit": _git_head(),
        "decided_at": DECIDED_AT,
        "runner": "tools/run_isolated_main_consumer_climb4.py",
        "checks": checks,
        "summary": {check["check"]: check["passed"] for check in checks},
        "claim_boundary": {
            "isolated_consumer_is_not_fixture_authority": True,
            "isolated_consumer_is_not_real_comfyui_main": True,
            "main_adoption_complete": False,
            "establishes_production_qualification": False,
            "advances": [
                "MF-P6-11.02 (Mode A immutable package-read: 30 adversarial cases, real bytes)",
                "MF-P6-11.07 (failure-control depth: healthy-admit/open/half-open/"
                "silent-fallback/scoped-DAG/incoherent-retry + deadline/resource/retry)",
            ],
            "hard_blockers_still_open": list(HARD_BLOCKERS_REQUIRING_REAL_MAIN),
            "advances_are_producer_isolated_only": True,
            "does_not_close_any_hard_blocker": True,
            "next_agent_step": (
                "Real HARD-close receipts require the actual Comfy_UI_Main runtime. "
                "Dirty Wave64 Main was NOT touched; use Comfy_UI_Main_MaskFactory_Consumer "
                "or a clean Main maskfactory branch."
            ),
        },
    }
    payload = json.dumps(
        {k: v for k, v in evidence.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence["summary"], sort_keys=True))
    return 0 if all(check["passed"] for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
