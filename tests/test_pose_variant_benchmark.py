import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from maskfactory.providers.pose_benchmark import (
    CONTEXTS,
    DEFAULT_POLICY_PATH,
    POLICY_SHA256,
    PROVIDER_JOINTS,
    PoseBenchmarkError,
    build_report,
    load_policy,
    validate_policy,
    verify_report,
)
from maskfactory.validation import validate_document

ROOT = Path(__file__).resolve().parents[1]


def _canonical(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _reseal(document: dict) -> None:
    document["sha256"] = _canonical(
        {key: value for key, value in document.items() if key != "sha256"}
    )


def _provider_evidence(provider: str, policy: dict) -> dict:
    observations = []
    for context in CONTEXTS:
        for joint in PROVIDER_JOINTS[provider]:
            observations.append(
                {
                    "context": context,
                    "joint": joint,
                    "visible_count": 10,
                    "correct_pck_005_count": 8,
                    "correct_pck_010_count": 9,
                    "normalized_error_sum": 0.5,
                }
            )
    return {
        "artifact_hashes": policy["providers"][provider]["artifact_hashes"],
        "runtime_fingerprint": policy["providers"][provider]["runtime_fingerprint"],
        "observations": observations,
        "side_metrics": [
            {
                "context": context,
                "eligible_count": 20,
                "correct_count": 20,
                "error_count": 0,
            }
            for context in CONTEXTS
        ],
        "identity_metrics": [
            {
                "context": context,
                "eligible_count": 10,
                "correct_count": 10,
                "error_count": 0,
            }
            for context in CONTEXTS
        ],
        "runtime_metrics": {
            "cold_latency_ms": 100.0,
            "warm_latency_ms": 50.0,
            "peak_vram_bytes": 512_000_000,
            "oom_count": 0,
            "crash_count": 0,
            "repeat_count": 2,
            "deterministic_output_sha256": ["a" * 64, "a" * 64],
        },
    }


def _fixture(tmp_path: Path) -> tuple[dict, Path]:
    policy = load_policy()
    truth = tmp_path / "human_anchor_holdout.json"
    truth.write_text('{"partition":"holdout","tier":"human_anchor_gold"}\n', encoding="utf-8")
    document = {
        "schema_version": "1.0.0",
        "benchmark_id": "pose-variant-fixture-v1",
        "results_opened_at": "2026-07-15T07:05:00Z",
        "policy_sha256": POLICY_SHA256,
        "truth_tier": "human_anchor_gold",
        "truth_partition": "holdout",
        "truth_manifest_sha256": hashlib.sha256(truth.read_bytes()).hexdigest(),
        "pipeline_fingerprint_sha256": "b" * 64,
        "hardware_fingerprint_sha256": "c" * 64,
        "providers": {
            provider: _provider_evidence(provider, policy) for provider in PROVIDER_JOINTS
        },
        "fallback_drills": [
            {
                "challenger": challenger,
                "injected_failure": "governed_primary_process_exit_17",
                "expected_provider": "dwpose_133",
                "observed_provider": "dwpose_133",
                "output_sha256": ("d" if challenger == "rtmw_x" else "e") * 64,
                "active_provider_after": "dwpose_133",
                "rollback_provider_after": "dwpose_133",
            }
            for challenger in ("rtmw_x", "rtmo_crowd")
        ],
    }
    _reseal(document)
    return document, truth


def _observation(document: dict, provider: str, context: str, joint: str) -> dict:
    return next(
        row
        for row in document["providers"][provider]["observations"]
        if row["context"] == context and row["joint"] == joint
    )


def test_frozen_policy_is_schema_valid_hash_locked_and_source_current() -> None:
    policy = load_policy()
    assert DEFAULT_POLICY_PATH == (
        ROOT / "qa/governance/benchmark_matrices/pose_variant_benchmark_v1.json"
    )
    assert policy["sha256"] == POLICY_SHA256
    assert len(policy["providers"]["dwpose_133"]["joint_vocabulary"]) == 133
    assert len(policy["providers"]["rtmw_x"]["joint_vocabulary"]) == 133
    assert len(policy["providers"]["rtmo_crowd"]["joint_vocabulary"]) == 14
    assert not validate_document(policy, "pose_variant_benchmark_policy")


def test_policy_edit_fails_after_reseal() -> None:
    policy = json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    policy["pass_requirements"]["max_pck_010_drop"] = 0.5
    _reseal(policy)
    with pytest.raises(PoseBenchmarkError, match="0.02 was expected|locked hash"):
        validate_policy(policy)


def test_complete_report_recomputes_every_joint_context_side_and_identity(
    tmp_path: Path,
) -> None:
    cases, truth = _fixture(tmp_path)
    report = build_report(cases, truth_manifest_path=truth)
    assert not validate_document(report, "pose_variant_benchmark_report")
    assert report["result"] == "pass"
    assert [len(row["joint_metrics"]) for row in report["providers"]] == [133, 133, 14]
    assert all(len(row["context_metrics"]) == 7 for row in report["providers"])
    dwpose = report["providers"][0]
    assert dwpose["overall_metrics"] == {
        "visible_count": 133 * 7 * 10,
        "correct_pck_005_count": 133 * 7 * 8,
        "correct_pck_010_count": 133 * 7 * 9,
        "normalized_error_sum": 133 * 7 * 0.5,
        "pck_005": 0.8,
        "pck_010": 0.9,
        "mean_normalized_error": 0.05,
    }
    assert report["comparisons"][0]["joint_intersection_count"] == 133
    assert report["comparisons"][1]["joint_intersection_count"] == 12
    assert report["comparisons"][1]["contexts"] == ["crowded_scene"]
    verify_report(report, cases, truth_manifest_path=truth)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing_joint", "coverage is incomplete"),
        ("duplicate_joint", "duplicate .* observation"),
        ("bad_pck_counts", "nested denominators"),
        ("bad_side_denominator", "counts do not reconcile"),
        ("bad_identity_context", "context coverage is invalid"),
        ("nondeterministic", "deterministic repeat evidence failed"),
        ("artifact_drift", "artifact identity mismatch"),
    ],
)
def test_completeness_and_identity_invariants_fail_closed(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    cases, truth = _fixture(tmp_path)
    provider = cases["providers"]["rtmw_x"]
    if mutation == "missing_joint":
        provider["observations"].pop()
    elif mutation == "duplicate_joint":
        provider["observations"].append(copy.deepcopy(provider["observations"][0]))
    elif mutation == "bad_pck_counts":
        provider["observations"][0]["correct_pck_005_count"] = 11
    elif mutation == "bad_side_denominator":
        provider["side_metrics"][0]["error_count"] = 1
    elif mutation == "bad_identity_context":
        provider["identity_metrics"][1]["context"] = provider["identity_metrics"][0]["context"]
    elif mutation == "nondeterministic":
        provider["runtime_metrics"]["deterministic_output_sha256"][1] = "f" * 64
    elif mutation == "artifact_drift":
        provider["artifact_hashes"]["checkpoint"] = "f" * 64
    _reseal(cases)
    with pytest.raises(PoseBenchmarkError, match=expected):
        build_report(cases, truth_manifest_path=truth)


@pytest.mark.parametrize(
    ("mutation", "finding"),
    [
        ("pck", "pck_010_noninferiority_failed"),
        ("side", "wrong_side_regression"),
        ("identity", "cross_person_regression"),
        ("runtime", "runtime_failure"),
        ("repeats", "determinism_repeat_count_failed"),
        ("fallback", "fallback_drill_failed"),
    ],
)
def test_each_noninferiority_and_fallback_gate_is_exact(
    tmp_path: Path, mutation: str, finding: str
) -> None:
    cases, truth = _fixture(tmp_path)
    challenger = cases["providers"]["rtmw_x"]
    if mutation == "pck":
        for row in challenger["observations"]:
            row["correct_pck_010_count"] = 8
    elif mutation == "side":
        challenger["side_metrics"][0].update(correct_count=19, error_count=1)
    elif mutation == "identity":
        challenger["identity_metrics"][0].update(correct_count=9, error_count=1)
    elif mutation == "runtime":
        challenger["runtime_metrics"]["crash_count"] = 1
    elif mutation == "repeats":
        challenger["runtime_metrics"]["repeat_count"] = 3
        challenger["runtime_metrics"]["deterministic_output_sha256"] = ["a" * 64] * 3
    elif mutation == "fallback":
        cases["fallback_drills"][0]["observed_provider"] = "rtmw_x"
    _reseal(cases)
    report = build_report(cases, truth_manifest_path=truth)
    assert report["result"] == "fail"
    assert f"rtmw_x:{finding}" in report["findings"]
    verify_report(report, cases, truth_manifest_path=truth, require_pass=False)
    with pytest.raises(PoseBenchmarkError, match="gates failed"):
        verify_report(report, cases, truth_manifest_path=truth)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("truth_tier", "human_anchor_gold"),
        ("results_opened_at", "predate frozen policy"),
        ("policy_sha256", "policy hash mismatch"),
        ("provider_set", "rtmo_crowd.*required property|provider set is incomplete"),
        ("fallback_set", "fallback drill set"),
    ],
)
def test_authority_and_exact_set_bindings_fail_closed(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    cases, truth = _fixture(tmp_path)
    if mutation == "truth_tier":
        cases["truth_tier"] = "autonomous_certified_gold"
    elif mutation == "results_opened_at":
        cases["results_opened_at"] = "2026-07-15T07:00:00Z"
    elif mutation == "policy_sha256":
        cases["policy_sha256"] = "f" * 64
    elif mutation == "provider_set":
        cases["providers"].pop("rtmo_crowd")
    elif mutation == "fallback_set":
        cases["fallback_drills"][1]["challenger"] = "rtmw_x"
    _reseal(cases)
    with pytest.raises((PoseBenchmarkError, ValueError), match=expected):
        build_report(cases, truth_manifest_path=truth)


def test_truth_manifest_drift_and_report_tamper_fail(tmp_path: Path) -> None:
    cases, truth = _fixture(tmp_path)
    report = build_report(cases, truth_manifest_path=truth)
    report["comparisons"][0]["pck_010_delta"] = 0.99
    _reseal(report)
    with pytest.raises(PoseBenchmarkError, match="recomputation mismatch"):
        verify_report(report, cases, truth_manifest_path=truth)
    truth.write_text("drift\n", encoding="utf-8")
    with pytest.raises(PoseBenchmarkError, match="truth manifest hash mismatch"):
        build_report(cases, truth_manifest_path=truth)


def test_one_command_builds_and_verifies_hash_sealed_report(tmp_path: Path) -> None:
    cases, truth = _fixture(tmp_path)
    cases_path = tmp_path / "cases.json"
    report_path = tmp_path / "report.json"
    cases_path.write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    command = [
        sys.executable,
        str(ROOT / "tools/evaluate_pose_variant_benchmark.py"),
        str(cases_path),
        "--truth-manifest",
        str(truth),
        "--output",
        str(report_path),
    ]
    built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert built.returncode == 0, built.stderr
    verified = subprocess.run(
        [*command, "--verify"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert verified.returncode == 0, verified.stderr
    assert json.loads(report_path.read_text(encoding="utf-8"))["result"] == "pass"
