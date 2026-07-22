"""Regression lock for the autonomous-gold lifecycle/audit-queue runtime driver.

Proves the two honest branches of the measured path:
  * fail-closed: below the genuine Wilson/zero-failure sample floor the
    certificate does NOT pass, so NO calibrated_auto_accepted sidecar is written
    and the audit population stays zero (no fabricated certificate);
  * claim firewall: even when the historical population statistics pass, they
    cannot create calibrated sidecars or a gold audit population.

The production ``runs/`` pool is scanned separately and is never touched by the
demonstration, so the honest production state is preserved.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "run_autonomous_gold_lifecycle_slice.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("_agls_harness", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_slice_fails_closed_below_sample_floor(tmp_path: Path) -> None:
    harness = _load_harness()
    evidence = harness.run_slice(
        tmp_path / "wd_small",
        draft_count=30,
        calibrated_count=5,
        production_machine_root=tmp_path / "no_production_runs",
    )
    assert evidence["certificate_summary"]["passed"] is False
    assert evidence["demonstration_counts"]["calibrated_auto_accepted_sidecars"] == 0
    assert evidence["demonstration_counts"]["audit_queue_population_count"] == 0
    # Fail-closed must never claim gold, but the plumbing is still honest.
    assert evidence["claim_boundary"]["wilson_math_unchanged"] is True
    assert evidence["claim_boundary"]["no_champion_force_registered"] is True


def test_passing_population_statistics_still_cannot_reach_gold_queue(tmp_path: Path) -> None:
    harness = _load_harness()
    evidence = harness.run_slice(
        tmp_path / "wd",
        draft_count=600,
        calibrated_count=30,
        production_machine_root=tmp_path / "no_production_runs",
    )
    counts = evidence["demonstration_counts"]
    assert evidence["certificate_summary"]["passed"] is True
    assert evidence["certificate_verify_valid"] is False
    assert evidence["certificate_verify_reason"] == (
        "population_certificate_not_per_record_authority"
    )
    assert evidence["certificate_summary"]["aggregate_false_accept_bound_method"] == (
        "one_sided_wilson"
    )
    assert evidence["certificate_summary"]["serious_false_accept_bound_method"] == (
        "exact_zero_failure"
    )
    assert counts["machine_verified_candidate_sidecars"] == 600
    assert counts["calibrated_auto_accepted_sidecars"] == 0
    assert counts["audit_queue_population_count"] == 0
    assert counts["audit_queue_selected_count"] == 0
    assert counts["audit_queue_outcomes_status"] == "empty"
    # Honest boundary: demonstration never inflates the production pool.
    assert evidence["production_pool_honest"]["calibrated_auto_accepted_count"] == 0
    assert evidence["production_pool_honest"]["lifecycle_sidecars_seen"] == 0
    assert evidence["claim_boundary"]["does_not_touch_production_runs_pool"] is True
    assert evidence["claim_boundary"]["is_not_independent_real_accuracy_claim"] is True
