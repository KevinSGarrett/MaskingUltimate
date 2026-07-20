"""Rewrite Mode A + failure-control matrices in run_isolated_main_consumer.py.

Restores the deepened matrices that produced
runtime_artifacts/main_consumer/isolated_consumer_run_evidence_20260720T094526.json
(23 Mode A cases + circuit/healthy-admit failure-control depth).
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGET = REPO / "tools" / "run_isolated_main_consumer.py"

FAILURE_FN = '''def run_failure_control() -> dict[str, Any]:
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

    # --- Circuit / healthy-admit / silent-fallback / DAG reach depth (climb3) ---
    from maskfactory.bridge.failure_control import build_failure_control_evidence

    def _circuit(*, state: str, half_open_probe_allowed: bool = False) -> dict[str, Any]:
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

    def _healthy_obs(circuit: dict[str, Any]) -> dict[str, Any]:
        return {
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

    healthy = build_failure_control_evidence(
        _healthy_obs(_circuit(state="closed")), decided_at=DECIDED_AT
    )
    healthy_admission_permits_provider = (
        healthy.get("circuit", {}).get("state") == "closed"
        and healthy.get("circuit", {}).get("blocks_route") is False
        and healthy.get("admission", {}).get("provider_invocation_permitted") is True
        and validate_failure_control_evidence(healthy) == ()
    )

    opened = build_failure_control_evidence(
        _healthy_obs(_circuit(state="open")), decided_at=DECIDED_AT
    )
    circuit_open_blocks_route = (
        opened.get("circuit", {}).get("state") == "open"
        and opened.get("circuit", {}).get("blocks_route") is True
        and opened.get("admission", {}).get("provider_invocation_permitted") is False
        and opened.get("no_silent_fallback", {}).get("fallback_artifact_present") is False
        and validate_failure_control_evidence(opened) == ()
    )

    half_blocked = build_failure_control_evidence(
        _healthy_obs(_circuit(state="half_open", half_open_probe_allowed=False)),
        decided_at=DECIDED_AT,
    )
    half_open_blocks = (
        half_blocked.get("circuit", {}).get("blocks_route") is True
        and half_blocked.get("admission", {}).get("provider_invocation_permitted") is False
        and validate_failure_control_evidence(half_blocked) == ()
    )
    half_probe = build_failure_control_evidence(
        _healthy_obs(_circuit(state="half_open", half_open_probe_allowed=True)),
        decided_at=DECIDED_AT,
    )
    half_open_permits = (
        half_probe.get("circuit", {}).get("blocks_route") is False
        and half_probe.get("admission", {}).get("provider_invocation_permitted") is True
        and validate_failure_control_evidence(half_probe) == ()
    )
    half_open_probe_gated = bool(half_open_blocks and half_open_permits)

    # Silent-fallback artifact must be refused outright.
    fallback_obs = _healthy_obs(_circuit(state="closed"))
    fallback_obs["fallback_attempt"] = {
        "kind": "empty_mask",
        "artifact_present": True,
    }
    fallback_ev = build_failure_control_evidence(fallback_obs, decided_at=DECIDED_AT)
    silent_fallback_refused = (
        fallback_ev.get("no_silent_fallback", {}).get("enforced") is True
        and fallback_ev.get("no_silent_fallback", {}).get("fallback_artifact_present") is True
        and fallback_ev.get("admission", {}).get("provider_invocation_permitted") is False
        and "silent_fallback_forbidden" in (fallback_ev.get("rejection_reasons") or [])
    )

    # Scoped-DAG overreach / underreach against a real outage fault profile.
    outage_matrix_scope = (
        simulate_fault_injection(
            fault_kind="outage",
            request=request,
            route_requirements=route,
            dag_passes=dag,
            decided_at=DECIDED_AT,
        ).get("error_matrix")
        or {}
    ).get("affected_scope") or "request"

    over_obs = _healthy_obs(_circuit(state="closed"))
    over_obs["failure"] = {
        "fault_kind": "outage",
        "failure_domain": "availability",
        "failure_code": "fault_outage",
    }
    over_obs["main_scoped_block_evidence"] = {
        "blocked_pass_ids": ["pass_predict", "pass_refine", "pass_unrelated"],
        "continuing_pass_ids": [],
        "affected_scope": outage_matrix_scope,
        "contains_fallback_artifact": False,
    }
    over_obs["main_retry_evidence"] = {
        "attempt_number": 1,
        "maximum_attempts": 3,
        "retry_only_typed_transient_errors": True,
        "allow_silent_fallback": False,
        "retry_permitted": True,
    }
    over_ev = build_failure_control_evidence(over_obs, decided_at=DECIDED_AT)
    scoped_dag_overreach_rejected = (
        "scoped_block_overreach" in (over_ev.get("rejection_reasons") or [])
        and over_ev.get("scoped_dag", {}).get("scope_exact") is False
        and over_ev.get("admission", {}).get("provider_invocation_permitted") is False
    )

    under_obs = dict(over_obs)
    under_obs["main_scoped_block_evidence"] = {
        "blocked_pass_ids": ["pass_predict"],
        "continuing_pass_ids": ["pass_refine", "pass_unrelated"],
        "affected_scope": outage_matrix_scope,
        "contains_fallback_artifact": False,
    }
    under_ev = build_failure_control_evidence(under_obs, decided_at=DECIDED_AT)
    scoped_dag_underreach_rejected = (
        "scoped_block_underreach" in (under_ev.get("rejection_reasons") or [])
        and under_ev.get("scoped_dag", {}).get("scope_exact") is False
        and under_ev.get("admission", {}).get("provider_invocation_permitted") is False
    )

    # Incoherent Main retry: retry claimed for non-transient authority fault.
    auth_ev = simulate_fault_injection(
        fault_kind="incompatible_authority",
        request=request,
        route_requirements=route,
        dag_passes=dag,
        decided_at=DECIDED_AT,
    )
    auth_scope = (auth_ev.get("error_matrix") or {}).get("affected_scope") or "request"
    inco_obs = _healthy_obs(_circuit(state="closed"))
    inco_obs["failure"] = {
        "fault_kind": "incompatible_authority",
        "failure_domain": "authority",
        "failure_code": "fault_incompatible_authority",
    }
    inco_obs["main_scoped_block_evidence"] = {
        "blocked_pass_ids": expected_blocked,
        "continuing_pass_ids": expected_continuing,
        "affected_scope": auth_scope,
        "contains_fallback_artifact": False,
    }
    inco_obs["main_retry_evidence"] = {
        "attempt_number": 1,
        "maximum_attempts": 3,
        "retry_only_typed_transient_errors": True,
        "allow_silent_fallback": False,
        "retry_permitted": True,  # incoherent: authority faults are non-transient
    }
    inco_ev = build_failure_control_evidence(inco_obs, decided_at=DECIDED_AT)
    incoherent_main_retry_rejected = (
        inco_ev.get("admission", {}).get("provider_invocation_permitted") is False
        and (
            "non_transient_retry_forbidden" in (inco_ev.get("rejection_reasons") or [])
            or "main_retry_evidence_invalid" in (inco_ev.get("rejection_reasons") or [])
        )
    )

    passed = (
        all(row["passed"] for row in results)
        and deadline_enforced
        and resource_enforced
        and retry_budget_enforced
        and healthy_admission_permits_provider
        and circuit_open_blocks_route
        and half_open_probe_gated
        and silent_fallback_refused
        and scoped_dag_overreach_rejected
        and scoped_dag_underreach_rejected
        and incoherent_main_retry_rejected
    )
    return {
        "check": "isolated_failure_control_circuit",
        "passed": passed,
        "faults": results,
        "deadline_enforced": deadline_enforced,
        "resource_envelope_enforced": resource_enforced,
        "bounded_retry_budget_enforced": retry_budget_enforced,
        "healthy_admission_permits_provider": healthy_admission_permits_provider,
        "circuit_open_blocks_route": circuit_open_blocks_route,
        "half_open_probe_gated": half_open_probe_gated,
        "silent_fallback_refused": silent_fallback_refused,
        "scoped_dag_overreach_rejected": scoped_dag_overreach_rejected,
        "scoped_dag_underreach_rejected": scoped_dag_underreach_rejected,
        "incoherent_main_retry_rejected": incoherent_main_retry_rejected,
    }


'''

MODE_A_FN = '''def run_mode_a_package_read_matrix() -> dict[str, Any]:
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

    # 1. Valid wrapper-certified single-person read accepts at certified authority.
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

    # 9. Non-production QA read without wrapper accepts but is capped.
    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    evidence = copy.deepcopy(evidence)
    request["exact_use_scope"] = "qa"
    evidence["wrapper"] = None
    _evaluate("qa_noncertified_read_accepts_capped", request, evidence, expect_accepted=True)
    qa_row = cases[-1]
    if (
        qa_row["authority_ceiling"] != "qa_passed_noncertified"
        or qa_row["production_eligible"] is not False
    ):
        qa_row["passed"] = False

    # 10. Production scope without wrapper refused.
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

    # 11. Revoked wrapper.
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

    # 12. Catalog not adopted.
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["catalog"]["adoption_decision"] = "rejected"
    evidence["catalog"]["release_status"] = "rejected"
    _evaluate(
        "catalog_not_adopted",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="catalog_not_adopted",
    )

    # 13. Source hash drift.
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["bytes"]["source_encoded"] = b"tampered-source-encoded!!"
    _evaluate(
        "source_hash_drift",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="source_hash_drift",
    )

    # 14. Manifest hash drift.
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

    # 15. Package hash drift via catalog entry rewrite.
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["catalog"]["packages"][0]["package_sha256"] = "f" * 64
    _evaluate(
        "package_hash_drift",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="package_hash_drift",
    )

    # 16. Ontology mismatch.
    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["ontology_version"] = "body_parts_v9_unknown"
    _evaluate(
        "ontology_mismatch",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="ontology_mismatch",
    )

    # 17. Instance mismatch.
    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["subject"]["scene_instance_id"] = "scene-attacker"
    _evaluate(
        "instance_mismatch",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="instance_mismatch",
    )

    # 18. Character revision mismatch.
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

    # 19. Rejected raw part status.
    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    evidence = copy.deepcopy(evidence)
    request["raw_part_status"] = "rejected_needs_fix"
    evidence["catalog"]["packages"][0]["raw_part_status"] = "rejected_needs_fix"
    _evaluate(
        "rejected_part_status",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="rejected_part_status",
    )

    # 20. Revocation head not current / unsigned.
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["bytes"]["revocation_identity"] = b'{"unsigned":true}'
    _evaluate(
        "revocation_not_current",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="revocation_not_current",
    )

    # 21. Transform drift.
    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    chain = copy.deepcopy(request["transform_chain"])
    chain["chain_sha256"] = "a" * 64
    request["transform_chain"] = chain
    _evaluate(
        "transform_drift",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="transform_drift",
    )

    # 22. Derived-artifact parent-authority escalation refused.
    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request["artifact_kind"] = "derived_union"
    request["parent_authority_state"] = "certified"
    request["claim_parent_authority"] = True
    _evaluate(
        "derived_authority_escalation",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="derived_authority_escalation",
    )

    # 23. Claimed certified without wrapper refused.
    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    evidence = copy.deepcopy(evidence)
    evidence["wrapper"] = None
    request["claimed_authority_state"] = "certified"
    request["escalate_raw_status"] = True
    _evaluate(
        "claimed_certified_without_wrapper",
        request,
        evidence,
        expect_accepted=False,
        expect_reason="wrapper_missing",
    )

    passed = baseline_certified and all(case["passed"] for case in cases)
    return {
        "check": "isolated_mode_a_package_read_matrix",
        "passed": passed,
        "baseline_certified": baseline_certified,
        "cases": cases,
    }


'''


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    f_start = text.index("def run_failure_control()")
    f_end = text.index("def run_mode_a_package_read_matrix()")
    m_start = f_end
    m_end = text.index("def run_final_release_handoff_firewall()")
    new = text[:f_start] + FAILURE_FN + MODE_A_FN + text[m_end:]
    # Ensure build_failure_control_evidence import available at module level too.
    if "build_failure_control_evidence" not in text.split("from maskfactory.bridge.failure_control")[1][
        :400
    ]:
        new = new.replace(
            "from maskfactory.bridge.failure_control import (\n"
            "    simulate_fault_injection,\n"
            "    validate_failure_control_evidence,\n"
            ")",
            "from maskfactory.bridge.failure_control import (\n"
            "    build_failure_control_evidence,\n"
            "    simulate_fault_injection,\n"
            "    validate_failure_control_evidence,\n"
            ")",
        )
    TARGET.write_text(new, encoding="utf-8")
    print("patched", TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
