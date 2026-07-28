from __future__ import annotations

from pathlib import Path

import pytest

from maskfactory.daz.worker_isolation_static import (
    MODE_BENCHMARK_DIMENSIONS,
    PRODUCTION_MODE,
    REQUIRED_CLEAN_RESTART_CHECKS,
    WorkerIsolationStaticError,
    build_worker_isolation_portfolio_report,
    decide_worker_execution_mode,
    evaluate_clean_restart_fixture,
    evaluate_mode_benchmark_matrix,
    refuse_dirty_scene_reuse,
)
from maskfactory.validation import validate_document

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CONFIG = ROOT / "configs" / "daz" / "runtime.yaml"


def _matrix_row(*, value: bool) -> dict[str, bool]:
    return {key: value for key in MODE_BENCHMARK_DIMENSIONS}


def _clean_observations(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "job_a_id": "job_static_a",
        "job_b_id": "job_static_b",
        "job_a_startup_node_count": 0,
        "job_b_startup_node_count": 0,
        "job_a_process_exited": True,
        "job_b_launched_after_job_a_exit": True,
        "shared_scene_state_reused": False,
        "partial_promoted_to_accepted": False,
        "parallel_daz_pids_observed": 0,
        "process_lifetime": "process_per_job",
        "persistent_worker": False,
        "no_default_scene": True,
    }
    base.update(overrides)
    return base


def test_mode_decision_retains_hidden_gui_and_refuses_live_overclaims() -> None:
    matrix = evaluate_mode_benchmark_matrix(
        hidden_gui=_matrix_row(value=False),
        headless=_matrix_row(value=False),
    )
    assert matrix["live_mode_benchmark_complete"] is False
    assert matrix["headless_promotion_eligible"] is False

    decision = decide_worker_execution_mode(RUNTIME_CONFIG, benchmark_matrix=matrix)
    assert decision["selected_production_mode"] == PRODUCTION_MODE
    assert decision["headless_promoted"] is False
    assert decision["live_daz_execution"] is False
    assert decision["command_contract"]["includes_headless_flag"] is False
    assert validate_document(decision, "daz_worker_mode_decision_static_report") == ()


def test_headless_and_debug_requests_fail_closed() -> None:
    matrix = evaluate_mode_benchmark_matrix(
        hidden_gui=_matrix_row(value=True),
        headless=_matrix_row(value=True),
    )
    with pytest.raises(WorkerIsolationStaticError, match="headless_requires_live"):
        decide_worker_execution_mode(
            RUNTIME_CONFIG, benchmark_matrix=matrix, requested_mode="headless"
        )
    with pytest.raises(WorkerIsolationStaticError, match="interactive_debug"):
        decide_worker_execution_mode(
            RUNTIME_CONFIG,
            benchmark_matrix=matrix,
            requested_mode="interactive_debug",
        )
    with pytest.raises(WorkerIsolationStaticError, match="live_mode_benchmark_overclaim"):
        decide_worker_execution_mode(
            RUNTIME_CONFIG,
            benchmark_matrix={**matrix, "live_mode_benchmark_complete": True},
        )


def test_incomplete_mode_matrix_fails_closed() -> None:
    with pytest.raises(WorkerIsolationStaticError, match="mode_benchmark_incomplete"):
        evaluate_mode_benchmark_matrix(
            hidden_gui={"startup_success": True},
            headless=_matrix_row(value=False),
        )


def test_clean_restart_fixture_passes_and_schema_validates() -> None:
    report = evaluate_clean_restart_fixture(observations=_clean_observations())
    assert report["all_checks_pass"] is True
    assert set(report["checks"]) == set(REQUIRED_CLEAN_RESTART_CHECKS)
    assert report["live_repeated_job_fixture_complete"] is False
    assert report["dirty_scene_reuse_allowed"] is False
    assert validate_document(report, "daz_clean_restart_static_report") == ()


def test_dirty_scene_and_failed_isolation_fail_closed() -> None:
    with pytest.raises(WorkerIsolationStaticError, match="startup_scene_not_empty"):
        refuse_dirty_scene_reuse(
            startup_node_count=3,
            shared_scene_state_reused=False,
            partial_promoted_to_accepted=False,
        )
    with pytest.raises(WorkerIsolationStaticError, match="dirty_scene_reuse_forbidden"):
        refuse_dirty_scene_reuse(
            startup_node_count=0,
            shared_scene_state_reused=True,
            partial_promoted_to_accepted=False,
        )
    with pytest.raises(WorkerIsolationStaticError, match="clean_restart_fixture_failed"):
        evaluate_clean_restart_fixture(
            observations=_clean_observations(shared_scene_state_reused=True)
        )
    with pytest.raises(WorkerIsolationStaticError, match="clean_restart_fixture_failed"):
        evaluate_clean_restart_fixture(observations=_clean_observations(job_a_process_exited=False))


def test_portfolio_report_binds_both_item_seals() -> None:
    matrix = evaluate_mode_benchmark_matrix(
        hidden_gui=_matrix_row(value=False),
        headless=_matrix_row(value=False),
    )
    mode = decide_worker_execution_mode(RUNTIME_CONFIG, benchmark_matrix=matrix)
    clean = evaluate_clean_restart_fixture(observations=_clean_observations())
    portfolio = build_worker_isolation_portfolio_report(mode_decision=mode, clean_restart=clean)
    assert portfolio["items"] == ["MF-P9-03.10", "MF-P9-03.11"]
    assert portfolio["mode_decision_seal_sha256"] == mode["seal_sha256"]
    assert portfolio["clean_restart_seal_sha256"] == clean["seal_sha256"]
    assert portfolio["production_evidence_pass_claimed"] is False
