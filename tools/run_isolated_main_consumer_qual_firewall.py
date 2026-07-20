"""Isolated Main-consumer qualification + firewall deepening runner (MF-P6-12.05 / 12.06).

Third standalone sibling of ``tools/run_isolated_main_consumer.py`` (and the two
``_dod`` runners). It DEEPENS the producer-side, isolated-consumer adversarial
coverage for the two HARD cross-project items by exercising the REAL oracles with
tampered / hostile inputs and proving each one fails closed:

  * ``isolated_cross_project_qualification_depth_matrix`` (MF-P6-12.05): runs the
    real ``build_cross_project_qualification_evidence`` /
    ``validate_cross_project_qualification_evidence`` and proves — honest
    producer_partial baseline, fabricated-Main-receipt rejection,
    fixture-claimed-as-production rejection, currency relabel rejection,
    decision-hash-drift detection, completion-overclaim detection, matrix-row
    set-drift detection, and that a pinned Main commit ALONE is insufficient
    (still producer_partial, no production qualification).
  * ``isolated_final_release_firewall_depth_matrix`` (MF-P6-12.06): runs the real
    ``evaluate_final_release_handoff`` / ``validate_final_release_handoff_evidence``
    and proves — honest incomplete_core, fabricated-core-claim rejection,
    fixture-only release refusal, fixture-authority-cannot-close-core refusal,
    adoption/release hash-pin mismatch refusal, optional-profile independence held,
    decision-hash-drift detection, and gate-set-drift detection. Core close is
    NEVER authorized.

Honesty ceiling (binding): producer-side, isolated-consumer-signed only. It NEVER
claims real Comfy_UI_Main adoption. HARD MF-P6-11.02 / 11.07 / 12.05 / 12.06 remain
OPEN and are recorded in the evidence, not hidden. Comfy_UI_Main is a dirty Wave64
tree and is NOT touched.

Kept as a standalone file (not folded into the shared runners) so this stream's work
is durable under heavy multi-agent working-tree churn.

Usage:
  python tools/run_isolated_main_consumer_qual_firewall.py \
      --output runtime_artifacts/main_consumer/isolated_consumer_qual_firewall_run_evidence_<ts>.json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from maskfactory.bridge.cross_project_qualification import (
    build_cross_project_qualification_evidence,
    validate_cross_project_qualification_evidence,
)
from maskfactory.bridge.final_release_handoff import (
    evaluate_final_release_handoff,
    validate_final_release_handoff_evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DECIDED_AT = "2026-07-20T05:00:00Z"

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


# ---------------------------------------------------------------------------
# MF-P6-12.05 cross-project qualification depth (real oracle + validator).
# ---------------------------------------------------------------------------


def _xproj(observation: dict[str, Any] | None) -> dict[str, Any]:
    return build_cross_project_qualification_evidence(
        observation=observation,
        decided_at=DECIDED_AT,
        bind_fixture_main=False,
    )


def run_cross_project_qualification_depth_matrix() -> dict[str, Any]:
    """Deepened MF-P6-12.05 adversarial matrix over the real qualification oracle."""
    head = _git_head()
    rows: list[dict[str, Any]] = []

    # 1. Honest producer baseline -> producer_partial, all matrix rows pass, no overclaim.
    baseline = _xproj({"producer_git_commit": head})
    baseline_issues = validate_cross_project_qualification_evidence(baseline)
    baseline_claim = baseline.get("claim_boundary") or {}
    matrix_rows_pass = all(
        row.get("result") == "pass" for row in (baseline.get("matrix_results") or [])
    )
    rows.append(
        {
            "case": "honest_producer_partial_baseline",
            "passed": bool(
                baseline.get("status") == "producer_partial"
                and baseline_issues == ()
                and matrix_rows_pass
                and baseline_claim.get("mf_p6_12_05_complete") is False
                and baseline_claim.get("establishes_production_qualification") is False
            ),
            "status": baseline.get("status"),
            "decision_sha256": baseline.get("decision_sha256"),
        }
    )

    # 2. Fabricated Main receipt must flip the decision to rejected (not fabricated pass).
    fabricated = _xproj(
        {
            "producer_git_commit": head,
            "fabricated_main_receipt": {
                "main_adapter_execution_receipt_present": True,
                "result_sha256": "a" * 64,
                "history_sha256": "b" * 64,
                "claim_mf_p6_12_05_complete": True,
            },
        }
    )
    rows.append(
        {
            "case": "fabricated_main_receipt_rejected",
            "passed": bool(
                fabricated.get("status") == "rejected"
                and "fabricated_main_receipt" in (fabricated.get("rejection_reasons") or [])
                and validate_cross_project_qualification_evidence(fabricated) == ()
                and (fabricated.get("claim_boundary") or {}).get("mf_p6_12_05_complete") is False
            ),
        }
    )

    # 3. Claiming fixture evidence as production qualification is refused.
    claimed = _xproj({"producer_git_commit": head, "claim_production_qualification": True})
    rows.append(
        {
            "case": "fixture_claimed_as_production_rejected",
            "passed": bool(
                claimed.get("status") == "rejected"
                and "fixture_evidence_claimed_as_production"
                in (claimed.get("rejection_reasons") or [])
                and validate_cross_project_qualification_evidence(claimed) == ()
            ),
        }
    )

    # 4. Relabelling the failed currency-review as pass is refused.
    relabel = _xproj({"producer_git_commit": head, "claimed_currency_status": "pass"})
    rows.append(
        {
            "case": "currency_relabel_rejected",
            "passed": bool(
                relabel.get("status") == "rejected"
                and "currency_policy_relabel_forbidden" in (relabel.get("rejection_reasons") or [])
                and validate_cross_project_qualification_evidence(relabel) == ()
            ),
        }
    )

    # 5. Tampering the sealed decision hash is detected by the validator.
    tampered_hash = copy.deepcopy(baseline)
    tampered_hash["decision_sha256"] = "0" * 64
    rows.append(
        {
            "case": "decision_hash_drift_detected",
            "passed": "decision_hash_drift"
            in validate_cross_project_qualification_evidence(tampered_hash),
        }
    )

    # 6. Forging a completion claim is detected by the validator.
    overclaim = copy.deepcopy(baseline)
    overclaim["claim_boundary"] = dict(overclaim.get("claim_boundary") or {})
    overclaim["claim_boundary"]["mf_p6_12_05_complete"] = True
    rows.append(
        {
            "case": "completion_overclaim_detected",
            "passed": "completion_overclaim"
            in validate_cross_project_qualification_evidence(overclaim),
        }
    )

    # 7. Dropping a matrix row (closed-set violation) is detected by the validator.
    row_drift = copy.deepcopy(baseline)
    if isinstance(row_drift.get("matrix_results"), list) and row_drift["matrix_results"]:
        row_drift["matrix_results"] = row_drift["matrix_results"][:-1]
    rows.append(
        {
            "case": "matrix_row_set_drift_detected",
            "passed": "matrix_row_set_drift"
            in validate_cross_project_qualification_evidence(row_drift),
        }
    )

    # 8. A pinned Main runtime commit ALONE (no adoption/qualification/adapter/history)
    #    is insufficient: still producer_partial with no production qualification.
    commit_only = _xproj(
        {
            "producer_git_commit": head,
            "pinned_main_runtime_git_commit": "c" * 40,
        }
    )
    consumer_binding = commit_only.get("consumer_binding") or {}
    rows.append(
        {
            "case": "pinned_main_commit_alone_insufficient",
            "passed": bool(
                commit_only.get("status") == "producer_partial"
                and consumer_binding.get("complete") is False
                and validate_cross_project_qualification_evidence(commit_only) == ()
                and (commit_only.get("claim_boundary") or {}).get(
                    "establishes_production_qualification"
                )
                is False
            ),
        }
    )

    return {
        "check": "isolated_cross_project_qualification_depth_matrix",
        "passed": all(row["passed"] for row in rows),
        "baseline_decision_sha256": baseline.get("decision_sha256"),
        "cases": rows,
    }


# ---------------------------------------------------------------------------
# MF-P6-12.06 final-release firewall depth (real oracle + validator).
# ---------------------------------------------------------------------------


def _released_snapshot(*, fixture_only: bool) -> dict[str, Any]:
    return {
        "release_id": "mfrel_isolated_firewall_depth",
        "release_payload_sha256": "d" * 64,
        "release_status": "published",
        "fixture_only": fixture_only,
        "producer": {"git_commit": "e" * 40},
    }


def run_final_release_firewall_depth_matrix() -> dict[str, Any]:
    """Deepened MF-P6-12.06 adversarial matrix over the real handoff oracle."""
    rows: list[dict[str, Any]] = []

    # 1. Honest handoff with no Main adoption -> incomplete_core, close refused.
    honest = evaluate_final_release_handoff(decided_at=DECIDED_AT)
    honest_claim = honest.get("claim_boundary") or {}
    honest_ok = (
        honest.get("status") == "incomplete_core"
        and honest.get("core_autonomous_runtime_close_authorized") is False
        and "core_close_refused_without_exact_gates" in (honest.get("rejection_reasons") or [])
        and honest_claim.get("core_closed") is False
        and validate_final_release_handoff_evidence(honest) == ()
    )
    rows.append(
        {
            "case": "honest_incomplete_core",
            "passed": bool(honest_ok),
            "decision_sha256": honest.get("decision_sha256"),
        }
    )

    # 2. A fabricated core-complete claim is rejected outright.
    fabricated = evaluate_final_release_handoff(
        decided_at=DECIDED_AT, fabricated_core_complete_claim=True
    )
    rows.append(
        {
            "case": "fabricated_core_claim_rejected",
            "passed": bool(
                fabricated.get("status") == "rejected"
                and fabricated.get("core_autonomous_runtime_close_authorized") is False
                and "fabricated_core_complete_claim" in (fabricated.get("rejection_reasons") or [])
                and validate_final_release_handoff_evidence(fabricated) == ()
            ),
        }
    )

    # 3. A fixture-only release can never satisfy the published-release gate.
    fixture_release = evaluate_final_release_handoff(
        decided_at=DECIDED_AT,
        release_snapshot=_released_snapshot(fixture_only=True),
        release_publication_issues=[],
    )
    gate_by_id = {
        g.get("gate_id"): g for g in (fixture_release.get("exact_core_close_gates") or [])
    }
    rows.append(
        {
            "case": "fixture_only_release_refused",
            "passed": bool(
                fixture_release.get("status") == "incomplete_core"
                and "final_producer_release_fixture_only"
                in (fixture_release.get("rejection_reasons") or [])
                and gate_by_id.get("final_producer_release_published", {}).get("status") != "met"
                and fixture_release.get("core_autonomous_runtime_close_authorized") is False
                and validate_final_release_handoff_evidence(fixture_release) == ()
            ),
        }
    )

    # 4. A fixture-authority adoption receipt can never authorize core close.
    fixture_adoption = evaluate_final_release_handoff(
        decided_at=DECIDED_AT,
        adoption_receipt={"signature": {"key_id": "comfy-main-adoption-fixture"}},
    )
    rows.append(
        {
            "case": "fixture_authority_cannot_close_core",
            "passed": bool(
                fixture_adoption.get("status") == "incomplete_core"
                and "fixture_authority_cannot_close_core"
                in (fixture_adoption.get("rejection_reasons") or [])
                and (fixture_adoption.get("claim_boundary") or {}).get("fixture_main_bound") is True
                and fixture_adoption.get("core_autonomous_runtime_close_authorized") is False
                and validate_final_release_handoff_evidence(fixture_adoption) == ()
            ),
        }
    )

    # 5. An adoption that does not pin the exact release id/hash is refused.
    pin_mismatch = evaluate_final_release_handoff(
        decided_at=DECIDED_AT,
        release_snapshot=_released_snapshot(fixture_only=False),
        release_publication_issues=[],
        adoption_receipt={
            "adoption_id": "mfadopt_isolated_firewall_depth",
            "adoption_payload_sha256": "f" * 64,
            "adoption_scope": "production_authority",
            "decision": "adopted",
            "production_use_authorized": True,
            "fixture_only": False,
            "release_id": "mfrel_some_other_release",
            "release_payload_sha256": "1" * 64,
            "signature": {"key_id": "comfy-main-adoption-prod"},
        },
    )
    rows.append(
        {
            "case": "adoption_release_pin_mismatch_refused",
            "passed": bool(
                pin_mismatch.get("status") == "incomplete_core"
                and "adoption_release_hash_pin_mismatch"
                in (pin_mismatch.get("rejection_reasons") or [])
                and pin_mismatch.get("core_autonomous_runtime_close_authorized") is False
                and validate_final_release_handoff_evidence(pin_mismatch) == ()
            ),
        }
    )

    # 6. Optional profiles are computed independently and cannot revoke/force core.
    honest_gate_by_id = {g.get("gate_id"): g for g in (honest.get("exact_core_close_gates") or [])}
    independence = (honest.get("profile_status_inputs") or {}).get("independence_proof") or {}
    rows.append(
        {
            "case": "optional_profile_independence_held",
            "passed": bool(
                independence.get("optional_failure_cannot_revoke_core") is True
                and independence.get("core_close_requires_exact_gates") is True
                and honest_gate_by_id.get("optional_profiles_remain_independent", {}).get("status")
                == "met"
            ),
        }
    )

    # 7. Tampering the sealed decision hash is detected by the validator.
    tampered_hash = copy.deepcopy(honest)
    tampered_hash["decision_sha256"] = "0" * 64
    rows.append(
        {
            "case": "decision_hash_drift_detected",
            "passed": "decision_hash_drift"
            in validate_final_release_handoff_evidence(tampered_hash),
        }
    )

    # 8. Dropping a required close gate (closed-set violation) is detected.
    gate_drift = copy.deepcopy(honest)
    if (
        isinstance(gate_drift.get("exact_core_close_gates"), list)
        and gate_drift["exact_core_close_gates"]
    ):
        gate_drift["exact_core_close_gates"] = gate_drift["exact_core_close_gates"][:-1]
    rows.append(
        {
            "case": "gate_set_drift_detected",
            "passed": "gate_set_drift" in validate_final_release_handoff_evidence(gate_drift),
        }
    )

    return {
        "check": "isolated_final_release_firewall_depth_matrix",
        "passed": all(row["passed"] for row in rows),
        "honest_decision_sha256": honest.get("decision_sha256"),
        "cases": rows,
    }


def _check(name: str, passed: bool, **extra: Any) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), **extra}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    runners: tuple[tuple[Callable[[], dict[str, Any]], str], ...] = (
        (
            run_cross_project_qualification_depth_matrix,
            "isolated_cross_project_qualification_depth_matrix",
        ),
        (
            run_final_release_firewall_depth_matrix,
            "isolated_final_release_firewall_depth_matrix",
        ),
    )
    for runner, name in runners:
        try:
            checks.append(runner())
        except Exception as exc:  # pragma: no cover - honest failure capture
            checks.append(_check(name, False, error=repr(exc)))

    evidence: dict[str, Any] = {
        "artifact_type": "isolated_main_consumer_qual_firewall_run",
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
                "MF-P6-12.05 (cross-project qualification DEPTH: honest producer_partial "
                "baseline, fabricated-Main-receipt / fixture-claimed-as-production / "
                "currency-relabel rejection, decision-hash-drift / completion-overclaim / "
                "matrix-row-set-drift detection, pinned-Main-commit-alone insufficiency — "
                "real build/validate_cross_project_qualification_evidence)",
                "MF-P6-12.06 (final-release firewall DEPTH: honest incomplete_core, "
                "fabricated-core-claim / fixture-only-release / fixture-authority / "
                "adoption-release-pin-mismatch refusal, optional-profile independence, "
                "decision-hash-drift / gate-set-drift detection, core never closed — "
                "real evaluate/validate_final_release_handoff)",
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
