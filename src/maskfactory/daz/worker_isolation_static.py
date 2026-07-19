"""STATIC worker-mode decision + clean-restart contracts (MF-P9-03.10 / 03.11).

Host-side evidence gates only. Never claims live DAZ Studio mode benchmark,
seven-day soak, doctor-green, gold, Main-complete, or PRODUCTION_EVIDENCE_PASS.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ..validation import ArtifactValidationError, require_valid_document
from .policy import DazPolicyError
from .runtime import DazRuntimeProfile, load_daz_runtime_profile

PROOF_TIER = "STATIC_PASS"
AUTHORITY = "daz_worker_isolation_static_only"
MODE_DECISION_ARTIFACT = "daz_worker_mode_decision_static_report"
CLEAN_RESTART_ARTIFACT = "daz_clean_restart_static_report"

PRODUCTION_MODE = "hidden_gui"
CHALLENGER_MODE = "headless"
DEBUG_MODE = "interactive_debug"
ALLOWED_MODES = (PRODUCTION_MODE, CHALLENGER_MODE, DEBUG_MODE)

# Dimensions that a live mode benchmark must cover before headless promotion.
MODE_BENCHMARK_DIMENSIONS = (
    "startup_success",
    "runtime_probe",
    "dialog_rate",
    "crash_oom",
    "output_hash_parity",
    "renderer_plugin_compat",
    "latency",
    "vram",
)

REQUIRED_CLEAN_RESTART_CHECKS = (
    "process_per_job",
    "persistent_worker_disabled",
    "no_default_scene",
    "startup_scene_empty",
    "refuse_parallel_daz",
    "job_private_state",
    "partial_not_accepted",
    "repeated_job_isolation",
)


class WorkerIsolationStaticError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _require_profile(profile: DazRuntimeProfile | Path) -> DazRuntimeProfile:
    if isinstance(profile, DazRuntimeProfile):
        return profile
    if isinstance(profile, Path):
        try:
            return load_daz_runtime_profile(profile)
        except DazPolicyError as exc:
            raise WorkerIsolationStaticError(f"runtime_profile_invalid:{exc}") from exc
    raise WorkerIsolationStaticError("invalid_runtime_profile")


def evaluate_mode_benchmark_matrix(
    *,
    hidden_gui: Mapping[str, bool],
    headless: Mapping[str, bool],
) -> dict[str, Any]:
    """Evaluate STATIC mode evidence matrix. Missing dimensions fail closed."""
    for label, row in (("hidden_gui", hidden_gui), ("headless", headless)):
        if set(row) != set(MODE_BENCHMARK_DIMENSIONS):
            raise WorkerIsolationStaticError(f"mode_benchmark_incomplete:{label}")
        if any(not isinstance(row[key], bool) for key in MODE_BENCHMARK_DIMENSIONS):
            raise WorkerIsolationStaticError(f"mode_benchmark_non_bool:{label}")

    hidden_pass = all(hidden_gui[key] for key in MODE_BENCHMARK_DIMENSIONS)
    headless_pass = all(headless[key] for key in MODE_BENCHMARK_DIMENSIONS)
    # STATIC climb: host can only assert contractual readiness, not live parity.
    return {
        "dimensions": list(MODE_BENCHMARK_DIMENSIONS),
        "hidden_gui": {key: bool(hidden_gui[key]) for key in MODE_BENCHMARK_DIMENSIONS},
        "headless": {key: bool(headless[key]) for key in MODE_BENCHMARK_DIMENSIONS},
        "hidden_gui_all_pass": hidden_pass,
        "headless_all_pass": headless_pass,
        "headless_promotion_eligible": False,
        "live_mode_benchmark_complete": False,
    }


def decide_worker_execution_mode(
    profile: DazRuntimeProfile | Path,
    *,
    benchmark_matrix: Mapping[str, Any],
    requested_mode: str | None = None,
) -> dict[str, Any]:
    """Decide production worker mode from profile + STATIC evidence matrix.

    Production remains ``hidden_gui`` until a live headless parity suite exists.
    Headless may be named as challenger only; promotion is refused under STATIC.
    """
    runtime = _require_profile(profile)
    if runtime.execution_mode != PRODUCTION_MODE:
        raise WorkerIsolationStaticError("profile_execution_mode_not_hidden_gui")
    if runtime.process_lifetime != "process_per_job":
        raise WorkerIsolationStaticError("profile_process_lifetime_not_process_per_job")
    if runtime.safety.get("persistent_worker") is not False:
        raise WorkerIsolationStaticError("profile_persistent_worker_not_disabled")
    if not runtime.startup.get("no_default_scene"):
        raise WorkerIsolationStaticError("profile_default_scene_not_disabled")

    matrix = dict(benchmark_matrix)
    for required in (
        "dimensions",
        "hidden_gui",
        "headless",
        "hidden_gui_all_pass",
        "headless_all_pass",
        "headless_promotion_eligible",
        "live_mode_benchmark_complete",
    ):
        if required not in matrix:
            raise WorkerIsolationStaticError(f"benchmark_matrix_missing:{required}")
    if matrix["live_mode_benchmark_complete"] is True:
        raise WorkerIsolationStaticError("live_mode_benchmark_overclaim")
    if matrix["headless_promotion_eligible"] is True:
        raise WorkerIsolationStaticError("headless_promotion_overclaim")

    mode = requested_mode or PRODUCTION_MODE
    if mode not in ALLOWED_MODES:
        raise WorkerIsolationStaticError(f"unsupported_worker_mode:{mode}")
    if mode == CHALLENGER_MODE:
        raise WorkerIsolationStaticError("headless_requires_live_mode_benchmark")
    if mode == DEBUG_MODE:
        raise WorkerIsolationStaticError("interactive_debug_cannot_write_accepted_packages")

    draft: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": MODE_DECISION_ARTIFACT,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "selected_production_mode": PRODUCTION_MODE,
        "challenger_mode": CHALLENGER_MODE,
        "debug_mode": DEBUG_MODE,
        "decision": "retain_hidden_gui_pending_live_headless_parity",
        "profile_bindings": {
            "profile_id": runtime.profile_id,
            "instance_name": runtime.instance_name,
            "execution_mode": runtime.execution_mode,
            "process_lifetime": runtime.process_lifetime,
            "persistent_worker": bool(runtime.safety.get("persistent_worker")),
            "no_default_scene": bool(runtime.startup.get("no_default_scene")),
            "no_prompt": bool(runtime.startup.get("no_prompt")),
        },
        "benchmark_matrix": {
            "dimensions": list(matrix["dimensions"]),
            "hidden_gui_all_pass": bool(matrix["hidden_gui_all_pass"]),
            "headless_all_pass": bool(matrix["headless_all_pass"]),
            "headless_promotion_eligible": False,
            "live_mode_benchmark_complete": False,
        },
        "command_contract": {
            "includes_instance_name": True,
            "includes_no_default_scene": True,
            "includes_no_prompt": True,
            "includes_headless_flag": False,
            "hidden_window_launch": True,
        },
        "live_daz_execution": False,
        "live_mode_benchmark_complete": False,
        "headless_promoted": False,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "visual_qa_pass_claimed": False,
        "main_complete_claimed": False,
        "production_evidence_pass_claimed": False,
    }
    digest = _sha(draft)
    draft["report_id"] = f"dwmd_{digest[:24]}"
    draft["seal_sha256"] = digest
    try:
        require_valid_document(draft, "daz_worker_mode_decision_static_report")
    except ArtifactValidationError as exc:
        raise WorkerIsolationStaticError(f"mode_decision_schema_invalid:{exc}") from exc
    return draft


def evaluate_clean_restart_fixture(
    *,
    observations: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate a STATIC repeated-job / dirty-scene isolation fixture."""
    required_keys = {
        "job_a_id",
        "job_b_id",
        "job_a_startup_node_count",
        "job_b_startup_node_count",
        "job_a_process_exited",
        "job_b_launched_after_job_a_exit",
        "shared_scene_state_reused",
        "partial_promoted_to_accepted",
        "parallel_daz_pids_observed",
        "process_lifetime",
        "persistent_worker",
        "no_default_scene",
    }
    if set(observations) < required_keys:
        missing = sorted(required_keys - set(observations))
        raise WorkerIsolationStaticError(
            f"clean_restart_observation_incomplete:{','.join(missing)}"
        )

    job_a = str(observations["job_a_id"])
    job_b = str(observations["job_b_id"])
    if not job_a or not job_b or job_a == job_b:
        raise WorkerIsolationStaticError("clean_restart_job_ids_invalid")

    checks: dict[str, bool] = {
        "process_per_job": observations["process_lifetime"] == "process_per_job",
        "persistent_worker_disabled": observations["persistent_worker"] is False,
        "no_default_scene": observations["no_default_scene"] is True,
        "startup_scene_empty": (
            observations["job_a_startup_node_count"] == 0
            and observations["job_b_startup_node_count"] == 0
        ),
        "refuse_parallel_daz": observations["parallel_daz_pids_observed"] == 0,
        "job_private_state": observations["shared_scene_state_reused"] is False,
        "partial_not_accepted": observations["partial_promoted_to_accepted"] is False,
        "repeated_job_isolation": (
            observations["job_a_process_exited"] is True
            and observations["job_b_launched_after_job_a_exit"] is True
            and job_a != job_b
        ),
    }
    if set(checks) != set(REQUIRED_CLEAN_RESTART_CHECKS):
        raise WorkerIsolationStaticError("clean_restart_check_set_drift")
    if not all(checks.values()):
        failed = sorted(key for key, ok in checks.items() if not ok)
        raise WorkerIsolationStaticError(f"clean_restart_fixture_failed:{','.join(failed)}")

    draft: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": CLEAN_RESTART_ARTIFACT,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "required_checks": list(REQUIRED_CLEAN_RESTART_CHECKS),
        "checks": checks,
        "jobs": {"job_a_id": job_a, "job_b_id": job_b},
        "worker_script_binding": {
            "startup_scene_empty_error": "startup_scene_not_empty",
            "process_exit_after_job": True,
            "source": "integrations/daz/scripts/1.0.0/worker_main.dsa",
        },
        "all_checks_pass": True,
        "live_daz_execution": False,
        "live_repeated_job_fixture_complete": False,
        "dirty_scene_reuse_allowed": False,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "visual_qa_pass_claimed": False,
        "main_complete_claimed": False,
        "production_evidence_pass_claimed": False,
    }
    digest = _sha(draft)
    draft["report_id"] = f"dcrs_{digest[:24]}"
    draft["seal_sha256"] = digest
    try:
        require_valid_document(draft, "daz_clean_restart_static_report")
    except ArtifactValidationError as exc:
        raise WorkerIsolationStaticError(f"clean_restart_schema_invalid:{exc}") from exc
    return draft


def refuse_dirty_scene_reuse(
    *,
    startup_node_count: int,
    shared_scene_state_reused: bool,
    partial_promoted_to_accepted: bool,
) -> None:
    """Fail closed on dirty-scene / partial-promotion attempts."""
    if startup_node_count != 0:
        raise WorkerIsolationStaticError("startup_scene_not_empty")
    if shared_scene_state_reused:
        raise WorkerIsolationStaticError("dirty_scene_reuse_forbidden")
    if partial_promoted_to_accepted:
        raise WorkerIsolationStaticError("partial_promotion_forbidden")


def build_worker_isolation_portfolio_report(
    *,
    mode_decision: Mapping[str, Any],
    clean_restart: Mapping[str, Any],
) -> dict[str, Any]:
    """Combine 03.10/03.11 STATIC seals into one portfolio evidence document."""
    for document, schema in (
        (mode_decision, "daz_worker_mode_decision_static_report"),
        (clean_restart, "daz_clean_restart_static_report"),
    ):
        try:
            require_valid_document(document, schema)
        except ArtifactValidationError as exc:
            raise WorkerIsolationStaticError(f"portfolio_component_invalid:{schema}:{exc}") from exc
        except DazPolicyError as exc:
            raise WorkerIsolationStaticError(str(exc)) from exc

    draft: dict[str, Any] = {
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "items": ["MF-P9-03.10", "MF-P9-03.11"],
        "result": "pass_daz_worker_isolation_static",
        "mode_decision_report_id": mode_decision["report_id"],
        "mode_decision_seal_sha256": mode_decision["seal_sha256"],
        "selected_production_mode": mode_decision["selected_production_mode"],
        "clean_restart_report_id": clean_restart["report_id"],
        "clean_restart_seal_sha256": clean_restart["seal_sha256"],
        "live_daz_execution": False,
        "live_mode_benchmark_complete": False,
        "live_repeated_job_fixture_complete": False,
        "headless_promoted": False,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "visual_qa_pass_claimed": False,
        "main_complete_claimed": False,
        "production_evidence_pass_claimed": False,
    }
    digest = _sha(draft)
    draft["seal_sha256"] = digest
    return draft


__all__ = [
    "ALLOWED_MODES",
    "AUTHORITY",
    "CHALLENGER_MODE",
    "CLEAN_RESTART_ARTIFACT",
    "DEBUG_MODE",
    "MODE_BENCHMARK_DIMENSIONS",
    "MODE_DECISION_ARTIFACT",
    "PRODUCTION_MODE",
    "PROOF_TIER",
    "REQUIRED_CLEAN_RESTART_CHECKS",
    "WorkerIsolationStaticError",
    "build_worker_isolation_portfolio_report",
    "decide_worker_execution_mode",
    "evaluate_clean_restart_fixture",
    "evaluate_mode_benchmark_matrix",
    "refuse_dirty_scene_reuse",
]
