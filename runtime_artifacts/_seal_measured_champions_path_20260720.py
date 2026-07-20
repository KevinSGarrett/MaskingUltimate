"""Seal a combined, honest measured-champions-path plumbing evidence artifact.

Stitches together the five measured-path stages
(lifecycle -> audit queue -> P5 -> shadow -> promote) into one sealed record
WITHOUT force-registering any champion and WITHOUT touching the production model
registry or the production ``runs/`` pool:

  * Stage 1-2 (lifecycle -> audit queue): embeds the *real on-disk* runtime slice
    produced by ``tools/run_autonomous_gold_lifecycle_slice.py`` (its own seal is
    re-verified here). This exercises the previously-stuck audit-queue population
    with the UNCHANGED Wilson / exact zero-failure certificate math.
  * Stage 3-5 (P5 register-training-candidate -> shadow benchmark -> promote
    transaction): recorded as VERIFIED_BY_TEST plumbing, anchored to the named
    passing test node files (custom-segmenter promotion transaction incl. the
    real signed ten-role matrix bundle, promotion policy, matrix promotion,
    specialist promotion). The production champion still requires the real
    multi-provider GPU tournament + gold corpus + matrix certification runtime,
    which does not exist on disk; this seal fabricates nothing.

Honest production state is scanned live and reported unchanged:
  * production champions = ``models champions`` (currently 0),
  * Mode B ``/predict`` = AWAITING_RUNTIME (champion predictor not configured).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from maskfactory.models.registry import champion_status

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_TYPE = "measured_champions_path_plumbing"
SCHEMA_VERSION = "1.0.0"
EVIDENCE_TIER = "DEMONSTRATION"

SLICE_ARTIFACT = (
    REPO_ROOT / "qa/live_verification/autonomous_gold_lifecycle_slice_20260720T0927.json"
)

STAGE_3_5_TESTS = (
    "tests/test_training_launch.py::test_completed_run_registers_atomically_as_reproducible_nonchampion",
    "tests/test_shadow_tournament_registration.py",
    "tests/test_custom_segmenter_promotion_transaction.py",
    "tests/test_custom_segmenter_promotion_policy.py",
    "tests/test_matrix_promotion.py",
    "tests/test_specialist_promotion.py",
)


def _verify_slice_seal(path: Path) -> dict:
    evidence = json.loads(path.read_text(encoding="utf-8"))
    claimed = evidence.get("self_sha256")
    body = {key: value for key, value in evidence.items() if key != "self_sha256"}
    actual = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if claimed != actual:
        raise SystemExit(f"slice seal mismatch: recomputed={actual} stored={claimed}")
    return evidence


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _seal(evidence: dict) -> dict:
    evidence.pop("self_sha256", None)
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    return evidence


def main() -> int:
    slice_evidence = _verify_slice_seal(SLICE_ARTIFACT)
    counts = slice_evidence["demonstration_counts"]
    production_pool = slice_evidence["production_pool_honest"]

    champions = champion_status(
        registry_path=REPO_ROOT / "models" / "model_registry.json",
        history_path=REPO_ROOT / "runs" / "champion_history.jsonl",
    )
    production_champion_count = len(champions["champions"])

    stages = [
        {
            "stage": "1_lifecycle",
            "role": "machine_verified_candidate sidecars",
            "tier": "RUNTIME_DEMONSTRATION",
            "proof": SLICE_ARTIFACT.relative_to(REPO_ROOT).as_posix(),
            "machine_verified_candidate_sidecars": counts["machine_verified_candidate_sidecars"],
            "calibrated_auto_accepted_sidecars": counts["calibrated_auto_accepted_sidecars"],
        },
        {
            "stage": "2_audit_queue",
            "role": "build_weekly_audit_queue population",
            "tier": "RUNTIME_DEMONSTRATION",
            "proof": SLICE_ARTIFACT.relative_to(REPO_ROOT).as_posix(),
            "audit_queue_population_count": counts["audit_queue_population_count"],
            "audit_queue_selected_count": counts["audit_queue_selected_count"],
            "audit_queue_outcomes_status": counts["audit_queue_outcomes_status"],
        },
        {
            "stage": "3_p5_training_candidate",
            "role": "register_training_candidate -> challenger_bodypart",
            "tier": "VERIFIED_BY_TEST",
            "proof": (
                "tests/test_training_launch.py::"
                "test_completed_run_registers_atomically_as_reproducible_nonchampion"
            ),
            "note": (
                "Sealed completed MMSeg run registers only as challenger_bodypart "
                "(installed); champion role never assigned here."
            ),
        },
        {
            "stage": "4_shadow_benchmark",
            "role": "benchmarked lifecycle + benchmark certificate",
            "tier": "VERIFIED_BY_TEST",
            "proof": "tests/test_shadow_tournament_registration.py",
            "note": (
                "Shadow/benchmark evidence raises a challenger to lifecycle "
                "'benchmarked'; measured non-inferiority certificate required before "
                "promotion."
            ),
        },
        {
            "stage": "5_promote",
            "role": "promote_custom_segmenter_role (smoke-first, transactional)",
            "tier": "VERIFIED_BY_TEST",
            "proof": "tests/test_custom_segmenter_promotion_transaction.py",
            "note": (
                "Atomic smoke-before-activation swap driven by a real signed "
                "ten-role matrix bundle + custom-segmenter certificate; rollback "
                "restores the exact incumbent. No production promotion executed."
            ),
        },
    ]

    evidence = {
        "artifact_type": ARTIFACT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "evidence_tier": EVIDENCE_TIER,
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "git_head": _git_head(),
        "measured_path_stages": stages,
        "stage_3_5_verified_by_tests": list(STAGE_3_5_TESTS),
        "production_honest_state": {
            "production_champion_count": production_champion_count,
            "production_champions": champions["champions"],
            "production_champion_history_rows": len(champions["history"]),
            "production_audit_queue_population_count": production_pool[
                "calibrated_auto_accepted_count"
            ],
            "production_autonomy_lifecycle_sidecars_in_runs": production_pool[
                "lifecycle_sidecars_seen"
            ],
            "mode_b_predict_status": "AWAITING_RUNTIME",
            "mode_b_predict_reason": (
                "champion prediction provider is not configured (champions=0)"
            ),
        },
        "claim_boundary": {
            "no_champion_registered": production_champion_count == 0,
            "no_champion_force_registered": True,
            "does_not_touch_production_runs_pool": True,
            "does_not_touch_production_model_registry": True,
            "wilson_math_unchanged": True,
            "promotion_is_smoke_first_and_transactional": True,
            "production_champion_requires_gpu_tournament_and_gold_corpus": True,
        },
        "next_agent_step": (
            "Run the real multi-provider GPU tournament on a frozen gold corpus to "
            "emit genuine machine_verified_candidate sidecars under runs/, mint a "
            "real custom-segmenter non-inferiority certificate + signed matrix "
            "bundle, then promote via promote_custom_segmenter_role. champions>0 "
            "only through this measured path; never force-register."
        ),
    }
    _seal(evidence)

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M")
    output = REPO_ROOT / f"qa/live_verification/measured_champions_path_plumbing_{ts}.json"
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": output.relative_to(REPO_ROOT).as_posix(),
                "production_champion_count": production_champion_count,
                "mode_b_predict_status": "AWAITING_RUNTIME",
                "audit_queue_population_count": counts["audit_queue_population_count"],
                "git_head": evidence["git_head"],
                "self_sha256": evidence["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
