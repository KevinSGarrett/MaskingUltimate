"""Idempotently re-apply the DoD-climb wave #3 edits and partial-commit only my
paths (survives a hostile shared working tree with concurrent hard resets).

Edits deepen tools/run_isolated_main_consumer.py (MF-P6-11.02 Mode A package-read
matrix 8->23 cases; MF-P6-11.07 failure-controller +7 checks) and record honest
tracker notes in Plan/Tracker/phases/P6.md. Uses `git commit -- <paths>` so other
agents' concurrently-staged index files are NOT swept in.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "run_isolated_main_consumer.py"
P6 = REPO / "Plan" / "Tracker" / "phases" / "P6.md"

# NOTE: Plan/Tracker/phases/P6.md is intentionally EXCLUDED. It is a shared,
# high-contention tracker file being concurrently edited (uncommitted) by sibling
# agents; a whole-file partial commit would risk reverting their in-progress work.
# The honest 11.02 86->87 / 11.07 82->84 credits, notes, and HARD-open status are
# durably recorded in the seal + run-evidence JSON committed here instead.
MY_PATHS = [
    "tools/run_isolated_main_consumer.py",
    "runtime_artifacts/_seal_isolated_consumer_climb3_20260720.py",
    "runtime_artifacts/main_consumer/isolated_consumer_run_evidence_20260720T094526.json",
    "qa/live_verification/isolated_consumer_dod_climb3_20260720T0945.json",
    "runtime_artifacts/_apply_and_commit_climb3_20260720.py",
]

SRC_IMPORT_OLD = """from maskfactory.bridge.external_adapter_conformance import (
    build_external_adapter_conformance_evidence,
)
from maskfactory.bridge.failure_control import (
    simulate_fault_injection,
    validate_failure_control_evidence,
)"""
SRC_IMPORT_NEW = """from maskfactory.bridge.error_matrix import build_bridge_error_decision
from maskfactory.bridge.external_adapter_conformance import (
    build_external_adapter_conformance_evidence,
)
from maskfactory.bridge.failure_control import (
    build_failure_control_evidence,
    simulate_fault_injection,
    validate_failure_control_evidence,
)"""

SRC_EVAL_OLD = """    def _evaluate(
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
        )"""
SRC_EVAL_NEW = """    def _evaluate(
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
        # Any refusal must also deny production eligibility and never expose writes.
        authority_ok = accepted or (
            result.get("production_eligible") is False
            and result.get("authority_ceiling") != "certified"
        )
        ceiling_ok = expect_ceiling is None or result.get("authority_ceiling") == expect_ceiling
        eligible_ok = (
            expect_production_eligible is None
            or result.get("production_eligible") is expect_production_eligible
        )
        passed = (
            accepted == expect_accepted
            and reason_ok
            and issues == ()
            and result.get("write_methods_exposed") is False
            and authority_ok
            and ceiling_ok
            and eligible_ok
        )"""

SRC_CASES_OLD = """    _evaluate(
        \"mutation_attempt\",
        request,
        evidence,
        expect_accepted=False,
        expect_reason=\"mutation_attempt\",
    )

    passed = baseline_certified and all(case[\"passed\"] for case in cases)"""
SRC_CASES_NEW = """    _evaluate(
        \"mutation_attempt\",
        request,
        evidence,
        expect_accepted=False,
        expect_reason=\"mutation_attempt\",
    )

    # 9. Non-production QA read WITHOUT a wrapper accepts, but is capped at the
    #    raw noncertified ceiling and is never production-eligible.
    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    evidence = copy.deepcopy(evidence)
    request[\"exact_use_scope\"] = \"qa\"
    evidence[\"wrapper\"] = None
    _evaluate(
        \"qa_noncertified_read_accepts_capped\",
        request,
        evidence,
        expect_accepted=True,
        expect_ceiling=\"qa_passed_noncertified\",
        expect_production_eligible=False,
    )

    # 10. Missing exact operational wrapper for a production scope.
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence[\"wrapper\"] = None
    _evaluate(
        \"wrapper_missing_production\",
        request,
        evidence,
        expect_accepted=False,
        expect_reason=\"wrapper_missing\",
    )

    # 11. Revoked exact operational wrapper.
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence[\"wrapper\"][\"revocation_status\"] = \"revoked\"
    _evaluate(
        \"wrapper_revoked\",
        request,
        evidence,
        expect_accepted=False,
        expect_reason=\"wrapper_revoked\",
    )

    # 12. Catalog not adopted (release/adoption decision not 'adopted').
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence[\"catalog\"][\"adoption_decision\"] = \"pending\"
    _evaluate(
        \"catalog_not_adopted\",
        request,
        evidence,
        expect_accepted=False,
        expect_reason=\"catalog_not_adopted\",
    )

    # 13. Source encoded byte drift (raw source bytes are authority-bound).
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence[\"bytes\"][\"source_encoded\"] = b\"tampered-source-encoded!\"
    _evaluate(
        \"source_hash_drift\",
        request,
        evidence,
        expect_accepted=False,
        expect_reason=\"source_hash_drift\",
    )

    # 14. Manifest byte drift.
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence[\"bytes\"][\"manifest\"] = b'{\"parts\":{\"left_forearm\":{\"status\":\"tampered\"}}}'
    _evaluate(
        \"manifest_hash_drift\",
        request,
        evidence,
        expect_accepted=False,
        expect_reason=\"manifest_hash_drift\",
    )

    # 15. Package-digest drift with intact component bytes.
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence[\"catalog\"][\"packages\"][0][\"package_sha256\"] = \"0\" * 64
    _evaluate(
        \"package_hash_drift\",
        request,
        evidence,
        expect_accepted=False,
        expect_reason=\"package_hash_drift\",
    )

    # 16. Ontology version mismatch between request and adopted catalog entry.
    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request[\"ontology_version\"] = \"body_parts_v2\"
    _evaluate(
        \"ontology_mismatch\",
        request,
        evidence,
        expect_accepted=False,
        expect_reason=\"ontology_mismatch\",
    )

    # 17. Scene-instance mismatch.
    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request[\"subject\"][\"scene_instance_id\"] = \"scene-instance-attacker\"
    _evaluate(
        \"instance_mismatch\",
        request,
        evidence,
        expect_accepted=False,
        expect_reason=\"instance_mismatch\",
    )

    # 18. Character-revision mismatch.
    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request[\"subject\"][\"character_revision\"] = \"char-rev-attacker\"
    _evaluate(
        \"character_revision_mismatch\",
        request,
        evidence,
        expect_accepted=False,
        expect_reason=\"character_revision_mismatch\",
    )

    # 19. Rejected raw part status can never be read for production.
    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request[\"raw_part_status\"] = \"rejected_needs_fix\"
    _evaluate(
        \"rejected_part_status\",
        request,
        evidence,
        expect_accepted=False,
        expect_reason=\"rejected_part_status\",
    )

    # 20. Non-current / unsigned revocation-identity head.
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence[\"bytes\"][\"revocation_identity\"] = b\"not-a-signed-revocation-record\"
    _evaluate(
        \"revocation_not_current\",
        request,
        evidence,
        expect_accepted=False,
        expect_reason=\"revocation_not_current\",
    )

    # 21. Transform-chain drift versus the adopted transform hash.
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence[\"catalog\"][\"packages\"][0][\"transform_chain_sha256\"] = \"a\" * 64
    _evaluate(
        \"transform_drift\",
        request,
        evidence,
        expect_accepted=False,
        expect_reason=\"transform_drift\",
    )

    # 22. Derived artifact attempting to inherit parent certified authority.
    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    request[\"artifact_kind\"] = \"refinement\"
    request[\"claim_parent_authority\"] = True
    _evaluate(
        \"derived_authority_escalation\",
        request,
        evidence,
        expect_accepted=False,
        expect_reason=\"derived_authority_escalation\",
    )

    # 23. Claimed 'certified' authority state without an active exact wrapper.
    request, evidence = build_fixture_adopted_package()
    request = copy.deepcopy(request)
    evidence = copy.deepcopy(evidence)
    request[\"claimed_authority_state\"] = \"certified\"
    evidence[\"wrapper\"] = None
    _evaluate(
        \"claimed_certified_without_wrapper\",
        request,
        evidence,
        expect_accepted=False,
        expect_reason=\"raw_status_escalation\",
    )

    passed = baseline_certified and all(case[\"passed\"] for case in cases)"""

SRC_FC_DEF_OLD = """def run_failure_control() -> dict[str, Any]:
    request = {"""
SRC_FC_DEF_NEW = """def _fc_circuit(*, state: str = \"closed\", half_open_probe_allowed: bool = False) -> dict[str, Any]:
    \"\"\"Build a self-consistent Main circuit-breaker evidence body (signed hash).\"\"\"
    body = {
        \"route_key\": \"mode-b/predict\",
        \"release_id\": \"mfrel_isolated_failure_control\",
        \"state\": state,
        \"failure_threshold\": 3,
        \"observation_window_ms\": 60000,
        \"cooldown_ms\": 5000,
        \"opened_at\": \"2026-07-20T03:59:00Z\" if state != \"closed\" else None,
        \"half_open_probe_allowed\": half_open_probe_allowed,
    }
    body[\"evidence_sha256\"] = canonical_document_sha256(
        body, excluded_top_level_fields=(\"evidence_sha256\",)
    )
    return body


def run_failure_control() -> dict[str, Any]:
    request = {"""

SRC_FC_TAIL_OLD = """    retry_budget_enforced = (budget_ev.get(\"retry\") or {}).get(
        \"retry_permitted\"
    ) is False and validate_failure_control_evidence(budget_ev) == ()

    passed = (
        all(row[\"passed\"] for row in results)
        and deadline_enforced
        and resource_enforced
        and retry_budget_enforced
    )
    return {
        \"check\": \"isolated_failure_control_circuit\",
        \"passed\": passed,
        \"faults\": results,
        \"deadline_enforced\": deadline_enforced,
        \"resource_envelope_enforced\": resource_enforced,
        \"bounded_retry_budget_enforced\": retry_budget_enforced,
    }"""
SRC_FC_TAIL_NEW = """    retry_budget_enforced = (budget_ev.get(\"retry\") or {}).get(
        \"retry_permitted\"
    ) is False and validate_failure_control_evidence(budget_ev) == ()

    # Positive baseline: a fully healthy admission MUST permit provider invocation.
    healthy_obs = {
        \"at_time\": \"2026-07-20T05:00:00Z\",
        \"request\": dict(request),
        \"route_requirements\": dict(route),
        \"failure\": {},
        \"main_circuit_evidence\": _fc_circuit(state=\"closed\"),
        \"main_retry_evidence\": {},
        \"main_scoped_block_evidence\": {},
        \"fallback_attempt\": {},
        \"dag_passes\": list(dag),
    }
    healthy_ev = build_failure_control_evidence(healthy_obs, decided_at=DECIDED_AT)
    healthy_admits = (
        healthy_ev.get(\"status\") == \"accepted\"
        and (healthy_ev.get(\"admission\") or {}).get(\"provider_invocation_permitted\") is True
        and (healthy_ev.get(\"no_silent_fallback\") or {}).get(\"fallback_artifact_present\") is False
        and validate_failure_control_evidence(healthy_ev) == ()
    )

    # Open circuit blocks the route with no mask substitution.
    open_obs = dict(healthy_obs)
    open_obs[\"main_circuit_evidence\"] = _fc_circuit(state=\"open\")
    open_ev = build_failure_control_evidence(open_obs, decided_at=DECIDED_AT)
    circuit_open_blocks = (
        open_ev.get(\"status\") == \"accepted\"
        and (open_ev.get(\"circuit\") or {}).get(\"blocks_route\") is True
        and (open_ev.get(\"admission\") or {}).get(\"provider_invocation_permitted\") is False
        and (open_ev.get(\"no_silent_fallback\") or {}).get(\"fallback_artifact_present\") is False
        and validate_failure_control_evidence(open_ev) == ()
    )

    # Half-open: blocks without an authorized probe; permits one trial with a probe.
    half_blocked_obs = dict(healthy_obs)
    half_blocked_obs[\"main_circuit_evidence\"] = _fc_circuit(
        state=\"half_open\", half_open_probe_allowed=False
    )
    half_blocked_ev = build_failure_control_evidence(half_blocked_obs, decided_at=DECIDED_AT)
    half_probe_obs = dict(healthy_obs)
    half_probe_obs[\"main_circuit_evidence\"] = _fc_circuit(
        state=\"half_open\", half_open_probe_allowed=True
    )
    half_probe_ev = build_failure_control_evidence(half_probe_obs, decided_at=DECIDED_AT)
    half_open_gated = (
        (half_blocked_ev.get(\"circuit\") or {}).get(\"blocks_route\") is True
        and (half_blocked_ev.get(\"admission\") or {}).get(\"provider_invocation_permitted\") is False
        and (half_probe_ev.get(\"circuit\") or {}).get(\"blocks_route\") is False
        and (half_probe_ev.get(\"admission\") or {}).get(\"provider_invocation_permitted\") is True
        and validate_failure_control_evidence(half_blocked_ev) == ()
        and validate_failure_control_evidence(half_probe_ev) == ()
    )

    # Silent-fallback artifact (empty/weaker mask) refused outright.
    fallback_matrix = build_bridge_error_decision(
        {
            \"failure_domain\": \"availability\",
            \"failure_domains\": [\"availability\"],
            \"failure_code\": \"SERVICE_UNAVAILABLE\",
        }
    )
    fallback_obs = dict(healthy_obs)
    fallback_obs[\"failure\"] = {
        \"fault_kind\": \"outage\",
        \"failure_domain\": \"availability\",
        \"failure_code\": \"SERVICE_UNAVAILABLE\",
    }
    fallback_obs[\"main_retry_evidence\"] = {
        \"attempt_number\": 1,
        \"maximum_attempts\": 3,
        \"retry_only_typed_transient_errors\": True,
        \"allow_silent_fallback\": False,
        \"retry_permitted\": True,
    }
    fallback_obs[\"main_scoped_block_evidence\"] = {
        \"blocked_pass_ids\": [\"pass_predict\", \"pass_refine\"],
        \"continuing_pass_ids\": [\"pass_unrelated\"],
        \"affected_scope\": fallback_matrix[\"affected_scope\"],
        \"contains_fallback_artifact\": False,
    }
    fallback_obs[\"fallback_attempt\"] = {
        \"kind\": \"empty_mask\",
        \"artifact_present\": True,
        \"kinds\": [\"empty_mask\", \"weaker_authority\"],
    }
    fallback_ev = build_failure_control_evidence(fallback_obs, decided_at=DECIDED_AT)
    fallback_refused = (
        fallback_ev.get(\"status\") == \"rejected\"
        and \"silent_fallback_forbidden\" in (fallback_ev.get(\"rejection_reasons\") or [])
        and \"fallback_artifact_present\" in (fallback_ev.get(\"rejection_reasons\") or [])
        and (fallback_ev.get(\"admission\") or {}).get(\"provider_invocation_permitted\") is False
        and set((fallback_ev.get(\"no_silent_fallback\") or {}).get(\"forbidden_kinds_observed\") or [])
        == {\"empty_mask\", \"weaker_authority\"}
    )

    # Scoped-DAG overreach rejected.
    overreach_obs = dict(fallback_obs)
    overreach_obs[\"fallback_attempt\"] = {}
    overreach_obs[\"main_scoped_block_evidence\"] = {
        \"blocked_pass_ids\": [\"pass_predict\", \"pass_refine\", \"pass_unrelated\"],
        \"continuing_pass_ids\": [],
        \"affected_scope\": fallback_matrix[\"affected_scope\"],
        \"contains_fallback_artifact\": False,
    }
    overreach_ev = build_failure_control_evidence(overreach_obs, decided_at=DECIDED_AT)
    scoped_overreach_rejected = (
        overreach_ev.get(\"status\") == \"rejected\"
        and \"scoped_block_overreach\" in (overreach_ev.get(\"rejection_reasons\") or [])
        and (overreach_ev.get(\"admission\") or {}).get(\"provider_invocation_permitted\") is False
    )

    # Scoped-DAG underreach rejected.
    underreach_obs = dict(overreach_obs)
    underreach_obs[\"main_scoped_block_evidence\"] = {
        \"blocked_pass_ids\": [\"pass_predict\"],
        \"continuing_pass_ids\": [\"pass_refine\", \"pass_unrelated\"],
        \"affected_scope\": fallback_matrix[\"affected_scope\"],
        \"contains_fallback_artifact\": False,
    }
    underreach_ev = build_failure_control_evidence(underreach_obs, decided_at=DECIDED_AT)
    scoped_underreach_rejected = (
        underreach_ev.get(\"status\") == \"rejected\"
        and \"scoped_block_underreach\" in (underreach_ev.get(\"rejection_reasons\") or [])
        and (underreach_ev.get(\"admission\") or {}).get(\"provider_invocation_permitted\") is False
    )

    # Incoherent Main retry evidence (retry for non-transient authority fault) rejected.
    authority_matrix = build_bridge_error_decision(
        {
            \"failure_domain\": \"authority\",
            \"failure_domains\": [\"authority\"],
            \"failure_code\": \"INCOMPATIBLE_AUTHORITY\",
        }
    )
    bad_retry_obs = dict(healthy_obs)
    bad_retry_obs[\"failure\"] = {
        \"fault_kind\": \"incompatible_authority\",
        \"failure_domain\": \"authority\",
        \"failure_code\": \"INCOMPATIBLE_AUTHORITY\",
    }
    bad_retry_obs[\"main_retry_evidence\"] = {
        \"attempt_number\": 1,
        \"maximum_attempts\": 3,
        \"retry_only_typed_transient_errors\": True,
        \"allow_silent_fallback\": False,
        \"retry_permitted\": True,
    }
    bad_retry_obs[\"main_scoped_block_evidence\"] = {
        \"blocked_pass_ids\": [\"pass_predict\", \"pass_refine\"],
        \"continuing_pass_ids\": [\"pass_unrelated\"],
        \"affected_scope\": authority_matrix[\"affected_scope\"],
        \"contains_fallback_artifact\": False,
    }
    bad_retry_ev = build_failure_control_evidence(bad_retry_obs, decided_at=DECIDED_AT)
    bad_retry_rejected = (
        bad_retry_ev.get(\"status\") == \"rejected\"
        and bool(
            {\"main_retry_evidence_invalid\", \"non_transient_retry_forbidden\"}
            & set(bad_retry_ev.get(\"rejection_reasons\") or [])
        )
        and (bad_retry_ev.get(\"admission\") or {}).get(\"provider_invocation_permitted\") is False
    )

    passed = (
        all(row[\"passed\"] for row in results)
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
        \"check\": \"isolated_failure_control_circuit\",
        \"passed\": passed,
        \"faults\": results,
        \"deadline_enforced\": deadline_enforced,
        \"resource_envelope_enforced\": resource_enforced,
        \"bounded_retry_budget_enforced\": retry_budget_enforced,
        \"healthy_admission_permits_provider\": healthy_admits,
        \"circuit_open_blocks_route\": circuit_open_blocks,
        \"half_open_probe_gated\": half_open_gated,
        \"silent_fallback_refused\": fallback_refused,
        \"scoped_dag_overreach_rejected\": scoped_overreach_rejected,
        \"scoped_dag_underreach_rejected\": scoped_underreach_rejected,
        \"incoherent_main_retry_rejected\": bad_retry_rejected,
    }"""

P6_1102_PCT_OLD = "- 🚫 **MF-P6-11.02** -- 86% **[HARD BLOCKER]**"
P6_1102_PCT_NEW = "- 🚫 **MF-P6-11.02** -- 87% **[HARD BLOCKER]**"
P6_1107_PCT_OLD = "- 🚫 **MF-P6-11.07** -- 82% **[HARD BLOCKER]**"
P6_1107_PCT_NEW = "- 🚫 **MF-P6-11.07** -- 84% **[HARD BLOCKER]**"

P6_1102_NOTE_ANCHOR = "self_sha256=6a777715a169acfeeacb8007aa30ef9ac42d9d3632db20e0916bbded9e667c5c. Credited 84 -> 86.\n"
P6_1102_NOTE_ADD = (
    "    - Note (2026-07-20T14:48:29+00:00, ai_agent): 2026-07-20 isolated-consumer DoD-climb wave #3: "
    "deepened the REAL immutable Mode A package-read adversarial matrix (tools/run_isolated_main_consumer.py "
    "-> evaluate_mode_a_package_read) from 8 to 23 cases. Adds a non-production QA read that accepts but is "
    "capped at qa_passed_noncertified with production_eligible=false (raw evidence usable, never self-promoting), "
    "plus new fail-closed refusals for wrapper_missing/wrapper_revoked, catalog_not_adopted, source/manifest/"
    "package hash drift, ontology/instance/character-revision mismatch, rejected_part_status, unsigned/non-current "
    "revocation head, transform_drift, derived-artifact parent-authority escalation, and "
    "claimed-certified-without-active-wrapper -- each with typed reasons, production_eligible=false, and no write "
    "path. STATIC_PASS producer+isolated real-execution only; HARD blocker stays OPEN (no real Comfy_UI_Main "
    "adopted-package/exact-wrapper authority; NOT fabricated; Comfy_UI_Main Wave64 dirty tree NOT touched). Receipt: "
    "runtime_artifacts/main_consumer/isolated_consumer_run_evidence_20260720T094526.json "
    "(self_sha256=fd43a8cb8b40bc3ef57c3bf69b96c5f406932dd6af17e26f4342e9dfabcdfab0); seal "
    "qa/live_verification/isolated_consumer_dod_climb3_20260720T0945.json "
    "self_sha256=2225863e730e44ee428c76a93022563a085856839e7b364f25ddf2fb9721b6ba. Credited 86 -> 87.\n"
)

P6_1107_NOTE_ANCHOR = "self_sha256=6a777715a169acfeeacb8007aa30ef9ac42d9d3632db20e0916bbded9e667c5c. Credited 80 -> 82.\n"
P6_1107_NOTE_ADD = (
    "    - Note (2026-07-20T14:48:29+00:00, ai_agent): 2026-07-20 isolated-consumer DoD-climb wave #3: deepened "
    "the REAL failure-controller matrix (tools/run_isolated_main_consumer.py -> simulate_fault_injection/"
    "build_failure_control_evidence) with 7 new checks beyond the prior fault/deadline/resource/retry-budget set. "
    "Adds a POSITIVE baseline (healthy admission with a valid closed circuit, feasible resources, within deadline "
    "PERMITS provider invocation -- proving it is not a trivial always-refuse); open-circuit route block with no "
    "mask substitution; half-open gating (blocks without an authorized probe, permits exactly one trial with a "
    "probe); silent-fallback artifact (empty/weaker mask) refused outright with forbidden_kinds surfaced; "
    "scoped-DAG overreach AND underreach both rejected; and incoherent Main retry evidence (retry claimed for a "
    "non-transient authority fault) rejected. All validate clean. STATIC_PASS producer+isolated real-execution only; "
    "HARD blocker stays OPEN (awaiting Main live circuit-breaker/DAG/retry signed evidence; NOT fabricated; "
    "Comfy_UI_Main Wave64 dirty tree NOT touched). Receipt: "
    "runtime_artifacts/main_consumer/isolated_consumer_run_evidence_20260720T094526.json "
    "(self_sha256=fd43a8cb8b40bc3ef57c3bf69b96c5f406932dd6af17e26f4342e9dfabcdfab0); seal "
    "qa/live_verification/isolated_consumer_dod_climb3_20260720T0945.json "
    "self_sha256=2225863e730e44ee428c76a93022563a085856839e7b364f25ddf2fb9721b6ba. Credited 82 -> 84.\n"
)


def _apply(text: str, old: str, new: str, label: str, marker: str) -> str:
    if marker in text:
        print(f"skip (already present): {label}")
        return text
    if old not in text:
        print(f"WARN anchor missing: {label}")
        return text
    print(f"applied: {label}")
    return text.replace(old, new, 1)


def apply_edits() -> None:
    src = TOOL.read_text(encoding="utf-8")
    src = _apply(src, SRC_IMPORT_OLD, SRC_IMPORT_NEW, "src.imports", "build_bridge_error_decision")
    src = _apply(src, SRC_EVAL_OLD, SRC_EVAL_NEW, "src.eval_helper", "expect_ceiling")
    src = _apply(
        src, SRC_CASES_OLD, SRC_CASES_NEW, "src.cases", "claimed_certified_without_wrapper"
    )
    src = _apply(src, SRC_FC_DEF_OLD, SRC_FC_DEF_NEW, "src.fc_circuit", "def _fc_circuit")
    src = _apply(
        src, SRC_FC_TAIL_OLD, SRC_FC_TAIL_NEW, "src.fc_tail", "incoherent_main_retry_rejected"
    )
    TOOL.write_text(src, encoding="utf-8")

    # P6.md is intentionally NOT written here (shared/contended tracker file).
    return
    p6 = P6.read_text(encoding="utf-8")
    p6 = _apply(p6, P6_1102_PCT_OLD, P6_1102_PCT_NEW, "p6.1102.pct", "MF-P6-11.02** -- 87%")
    p6 = _apply(p6, P6_1107_PCT_OLD, P6_1107_PCT_NEW, "p6.1107.pct", "MF-P6-11.07** -- 84%")
    p6 = _apply(
        p6,
        P6_1102_NOTE_ANCHOR,
        P6_1102_NOTE_ANCHOR + P6_1102_NOTE_ADD,
        "p6.1102.note",
        "Credited 86 -> 87.",
    )
    p6 = _apply(
        p6,
        P6_1107_NOTE_ANCHOR,
        P6_1107_NOTE_ANCHOR + P6_1107_NOTE_ADD,
        "p6.1107.note",
        "Credited 82 -> 84.",
    )
    P6.write_text(p6, encoding="utf-8")


def _run(args: list[str], timeout: float = 45.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "TIMEOUT")


def main() -> int:
    apply_edits()

    if "--commit" in sys.argv:
        import time

        msg = (
            "evidence(bridge-dod): isolated Main-consumer DoD-climb #3 -- deepen HARD "
            "MF-P6-11.02 Mode A package-read matrix (8->23 adversarial cases) and "
            "MF-P6-11.07 failure-controller (+7 checks: healthy-admit baseline, open/"
            "half-open circuit gating, silent-fallback refusal, scoped-DAG over/under-"
            "reach, incoherent-retry rejection). Producer+isolated STATIC_PASS only; "
            "HARD blockers stay OPEN (AWAITING_MAIN); Comfy_UI_Main Wave64 NOT touched."
        )
        committed = False
        for attempt in range(1, 121):
            # Re-apply each attempt in case a concurrent hard reset clobbered us.
            apply_edits()
            add = _run(["git", "add", "--", *MY_PATHS])
            if add.returncode != 0:
                print(
                    f"attempt {attempt} ADD_RC {add.returncode}: {add.stderr.strip()[:100]}",
                    flush=True,
                )
                time.sleep(2)
                continue
            commit = _run(["git", "commit", "-m", msg, "--", *MY_PATHS])
            out = (commit.stdout + commit.stderr).strip()
            print(f"attempt {attempt} COMMIT_RC {commit.returncode}: {out[:200]}", flush=True)
            if commit.returncode == 0 or "nothing to commit" in out:
                committed = True
                break
            time.sleep(2)
        print(f"COMMITTED={committed}", flush=True)
        if committed:
            for attempt in range(1, 61):
                push = _run(["git", "push"], timeout=90.0)
                out = (push.stdout + push.stderr).strip()
                print(f"push attempt {attempt} RC {push.returncode}: {out[:200]}", flush=True)
                if push.returncode == 0 or "up to date" in out.lower():
                    break
                if "non-fast-forward" in out or "fetch first" in out or "rejected" in out:
                    pull = _run(["git", "pull", "--rebase"], timeout=120.0)
                    print(
                        f"  pull --rebase RC {pull.returncode}: "
                        f"{(pull.stdout + pull.stderr).strip()[:160]}",
                        flush=True,
                    )
                time.sleep(2)
    print("SCRIPT_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
