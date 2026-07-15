import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from maskfactory.providers.geometry_benchmark import (
    CONTEXTS,
    DEFAULT_POLICY_PATH,
    POLICY_SHA256,
    GeometryBenchmarkError,
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
    spec = policy["providers"][provider]
    challenger = provider == "sam3d_body"
    hashes = (
        {"checkpoint": spec["frozen_artifact_hashes"]["checkpoint"]}
        if not challenger
        else {
            "checkpoint": "1" * 64,
            "mhr_model": "2" * 64,
            "model_config": "3" * 64,
            "source_archive": "4" * 64,
        }
    )
    return {
        "source_revision": spec["source_revision"],
        "checkpoint_revision": spec["checkpoint_revision"],
        "artifact_hashes": hashes,
        "runtime_fingerprint": f"fixture-{provider}-runtime",
        "observations": [
            {
                "context": context,
                "evaluated_projection_count": 100,
                "consistent_projection_count": 92 if challenger else 90,
                "visible_surface_truth_count": 100,
                "visible_surface_hit_count": 90,
                "predicted_surface_count": 100,
                "background_bleed_count": 0,
                "cross_person_bleed_count": 0,
                "side_eligible_count": 20,
                "left_right_error_count": 0,
                "front_back_eligible_count": 20,
                "front_back_error_count": 0,
                "identity_eligible_count": 20,
                "identity_assignment_error_count": 0,
                "hard_qa_eligible_count": 20,
                "hard_qa_failure_count": 0,
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
    truth.write_text('{"partition":"holdout","tier":"human_anchor_gold"}\n')
    document = {
        "schema_version": "1.0.0",
        "benchmark_id": "geometry-variant-fixture-v1",
        "results_opened_at": "2026-07-15T10:10:00Z",
        "policy_sha256": POLICY_SHA256,
        "truth_tier": "human_anchor_gold",
        "truth_partition": "holdout",
        "truth_manifest_sha256": hashlib.sha256(truth.read_bytes()).hexdigest(),
        "pipeline_fingerprint_sha256": "b" * 64,
        "hardware_fingerprint_sha256": "c" * 64,
        "providers": {
            provider: _provider_evidence(provider, policy)
            for provider in ("densepose_r50_fpn_s1x", "sam3d_body")
        },
        "fallback_drill": {
            "challenger": "sam3d_body",
            "injected_failure": "governed_primary_cuda_oom",
            "expected_provider": "densepose_r50_fpn_s1x",
            "observed_provider": "densepose_r50_fpn_s1x",
            "output_sha256": "d" * 64,
            "active_provider_after": "densepose_r50_fpn_s1x",
            "rollback_provider_after": "densepose_r50_fpn_s1x",
        },
    }
    _reseal(document)
    return document, truth


def test_frozen_policy_is_schema_valid_hash_locked_and_source_current() -> None:
    policy = load_policy()
    assert DEFAULT_POLICY_PATH == (
        ROOT / "qa/governance/benchmark_matrices/geometry_variant_benchmark_v1.json"
    )
    assert policy["sha256"] == POLICY_SHA256
    assert policy["providers"]["sam3d_body"]["frozen_artifact_hashes"] == {}
    assert policy["providers"]["sam3d_body"]["authority"] == (
        "planned_source_only_until_governed_installation"
    )
    assert not validate_document(policy, "geometry_variant_benchmark_policy")


def test_policy_edit_fails_even_after_reseal() -> None:
    policy = json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    policy["pass_requirements"]["max_peak_vram_bytes"] = 99_999_999_999
    _reseal(policy)
    with pytest.raises(GeometryBenchmarkError, match="was expected|locked hash"):
        validate_policy(policy)


def test_report_recomputes_every_geometry_denominator_context_and_runtime(
    tmp_path: Path,
) -> None:
    cases, truth = _fixture(tmp_path)
    report = build_report(cases, truth_manifest_path=truth)
    assert report["result"] == "pass"
    assert len(report["providers"]) == 2
    assert all(len(row["context_metrics"]) == 9 for row in report["providers"])
    densepose = report["providers"][0]["overall_metrics"]
    sam3d = report["providers"][1]["overall_metrics"]
    assert densepose["evaluated_projection_count"] == 900
    assert densepose["projection_consistency"] == 0.9
    assert sam3d["projection_consistency"] == 0.92
    assert report["comparison"]["overall_projection_consistency_delta"] == pytest.approx(0.02)
    assert report["authority"] == (
        "benchmark_evidence_only_no_installation_promotion_mask_or_gold_authority"
    )
    assert not validate_document(report, "geometry_variant_benchmark_report")
    verify_report(report, cases, truth_manifest_path=truth)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing_context", "too short|cover every geometry context"),
        ("duplicate_context", "context coverage is invalid"),
        ("bad_projection_denominator", "exceeds its explicit denominator"),
        ("bad_side_denominator", "exceeds its explicit denominator"),
        ("artifact_set", "artifact set is incomplete"),
        ("source_revision", "source revision mismatch"),
        ("checkpoint_revision", "checkpoint revision mismatch"),
        ("nondeterministic", "deterministic repeat evidence failed"),
    ],
)
def test_completeness_identity_and_denominator_invariants_fail_closed(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    cases, truth = _fixture(tmp_path)
    evidence = cases["providers"]["sam3d_body"]
    if mutation == "missing_context":
        evidence["observations"].pop()
    elif mutation == "duplicate_context":
        evidence["observations"][1]["context"] = evidence["observations"][0]["context"]
    elif mutation == "bad_projection_denominator":
        evidence["observations"][0]["consistent_projection_count"] = 101
    elif mutation == "bad_side_denominator":
        evidence["observations"][0]["left_right_error_count"] = 21
    elif mutation == "artifact_set":
        evidence["artifact_hashes"].pop("mhr_model")
    elif mutation == "source_revision":
        evidence["source_revision"] = "f" * 40
    elif mutation == "checkpoint_revision":
        evidence["checkpoint_revision"] = "f" * 40
    elif mutation == "nondeterministic":
        evidence["runtime_metrics"]["deterministic_output_sha256"][1] = "f" * 64
    _reseal(cases)
    with pytest.raises(GeometryBenchmarkError, match=expected):
        build_report(cases, truth_manifest_path=truth)


@pytest.mark.parametrize(
    ("mutation", "finding"),
    [
        ("primary", "projection_consistency_primary_win_failed"),
        ("projection_context", "contact:projection_consistency_noninferiority_failed"),
        ("visible_recall", "contact:visible_surface_recall_noninferiority_failed"),
        ("background_bleed", "contact:background_bleed_rate_regression"),
        ("cross_person", "contact:cross_person_bleed_rate_regression"),
        ("side", "contact:left_right_error_rate_regression"),
        ("front_back", "contact:front_back_error_rate_regression"),
        ("identity", "contact:identity_assignment_error_rate_regression"),
        ("hard_qa", "contact:hard_qa_failure_rate_regression"),
        ("vram", "peak_vram_limit_failed"),
        ("runtime", "runtime_failure"),
        ("repeats", "determinism_repeat_count_failed"),
        ("fallback", "fallback_drill_failed"),
    ],
)
def test_every_primary_noninferiority_runtime_and_fallback_gate_is_exact(
    tmp_path: Path, mutation: str, finding: str
) -> None:
    cases, truth = _fixture(tmp_path)
    evidence = cases["providers"]["sam3d_body"]
    contact = next(row for row in evidence["observations"] if row["context"] == "contact")
    if mutation == "primary":
        for row in evidence["observations"]:
            row["consistent_projection_count"] = 90
    elif mutation == "projection_context":
        contact["consistent_projection_count"] = 87
    elif mutation == "visible_recall":
        contact["visible_surface_hit_count"] = 87
    elif mutation == "background_bleed":
        contact["background_bleed_count"] = 1
    elif mutation == "cross_person":
        contact["cross_person_bleed_count"] = 1
    elif mutation == "side":
        contact["left_right_error_count"] = 1
    elif mutation == "front_back":
        contact["front_back_error_count"] = 1
    elif mutation == "identity":
        contact["identity_assignment_error_count"] = 1
    elif mutation == "hard_qa":
        contact["hard_qa_failure_count"] = 1
    elif mutation == "vram":
        evidence["runtime_metrics"]["peak_vram_bytes"] = 8_589_934_593
    elif mutation == "runtime":
        evidence["runtime_metrics"]["oom_count"] = 1
    elif mutation == "repeats":
        evidence["runtime_metrics"]["repeat_count"] = 3
        evidence["runtime_metrics"]["deterministic_output_sha256"] = ["a" * 64] * 3
    elif mutation == "fallback":
        cases["fallback_drill"]["observed_provider"] = "sam3d_body"
    _reseal(cases)
    report = build_report(cases, truth_manifest_path=truth)
    assert report["result"] == "fail"
    assert finding in report["findings"]
    verify_report(report, cases, truth_manifest_path=truth, require_pass=False)
    with pytest.raises(GeometryBenchmarkError, match="gates failed"):
        verify_report(report, cases, truth_manifest_path=truth)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("truth", "human_anchor_gold"),
        ("timestamp", "predate frozen policy"),
        ("policy", "policy hash mismatch"),
        ("provider", "sam3d_body.*required property|provider set is incomplete"),
    ],
)
def test_authority_and_exact_set_bindings_fail_closed(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    cases, truth = _fixture(tmp_path)
    if mutation == "truth":
        cases["truth_tier"] = "autonomous_certified_gold"
    elif mutation == "timestamp":
        cases["results_opened_at"] = "2026-07-15T10:04:59Z"
    elif mutation == "policy":
        cases["policy_sha256"] = "f" * 64
    elif mutation == "provider":
        cases["providers"].pop("sam3d_body")
    _reseal(cases)
    with pytest.raises((GeometryBenchmarkError, ValueError), match=expected):
        build_report(cases, truth_manifest_path=truth)


def test_truth_drift_and_report_tamper_fail(tmp_path: Path) -> None:
    cases, truth = _fixture(tmp_path)
    report = build_report(cases, truth_manifest_path=truth)
    report["comparison"]["overall_projection_consistency_delta"] = 0.99
    _reseal(report)
    with pytest.raises(GeometryBenchmarkError, match="recomputation mismatch"):
        verify_report(report, cases, truth_manifest_path=truth)
    truth.write_text("drift\n")
    with pytest.raises(GeometryBenchmarkError, match="truth manifest hash mismatch"):
        build_report(cases, truth_manifest_path=truth)


def test_one_command_builds_and_verifies_hash_sealed_report(tmp_path: Path) -> None:
    cases, truth = _fixture(tmp_path)
    cases_path = tmp_path / "cases.json"
    report_path = tmp_path / "report.json"
    cases_path.write_text(json.dumps(cases, indent=2) + "\n")
    command = [
        sys.executable,
        str(ROOT / "tools/evaluate_geometry_variant_benchmark.py"),
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
    assert json.loads(report_path.read_text())["result"] == "pass"
