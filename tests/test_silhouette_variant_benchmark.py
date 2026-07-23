import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from maskfactory.providers.silhouette_benchmark import (
    CONTEXTS,
    DEFAULT_POLICY_PATH,
    POLICY_SHA256,
    PROVIDER_CAPABILITIES,
    ROLE_MATRIX,
    SilhouetteBenchmarkError,
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


def _observation(role: str, context: str, label: str) -> dict:
    alpha = bool(ROLE_MATRIX[role]["requires_alpha"])
    return {
        "role": role,
        "context": context,
        "label": label,
        "case_count": 2,
        "total_pixels": 1000,
        "predicted_foreground_pixels": 400,
        "truth_foreground_pixels": 400,
        "intersection_pixels": 380,
        "truth_background_pixels": 600,
        "false_positive_background_pixels": 20,
        "boundary_true_positive": 90,
        "boundary_false_positive": 5,
        "boundary_false_negative": 5,
        "correction_pixels": 40,
        "alpha_reference_pixels": 1000 if alpha else 0,
        "alpha_absolute_error_sum": 20.0 if alpha else 0.0,
        "alpha_squared_error_sum": 5.0 if alpha else 0.0,
    }


def _provider_evidence(provider: str, policy: dict) -> dict:
    observations = [
        _observation(role, context, label)
        for role in PROVIDER_CAPABILITIES[provider]
        for context in CONTEXTS
        for label in ROLE_MATRIX[role]["labels"]
    ]
    return {
        "artifact_hashes": policy["providers"][provider]["artifact_hashes"],
        "runtime_fingerprint": policy["providers"][provider]["runtime_fingerprint"],
        "governed_resolution": policy["providers"][provider]["governed_resolution"],
        "observations": observations,
        "runtime_metrics": {
            "cold_latency_ms": 120.0,
            "warm_latency_ms": 60.0,
            "peak_vram_bytes": 1_000_000_000,
            "oom_count": 0,
            "crash_count": 0,
            "repeat_count": 2,
            "deterministic_output_sha256": ["a" * 64, "a" * 64],
        },
    }


def _fixture(tmp_path: Path) -> tuple[dict, Path]:
    policy = load_policy()
    truth = tmp_path / "human_anchor_holdout.json"
    truth.write_text(
        '{"partition":"holdout","tier":"human_anchor_gold","auxiliary_alpha":"reviewed"}\n',
        encoding="utf-8",
    )
    drills = []
    for role, spec in ROLE_MATRIX.items():
        for challenger in spec["challengers"]:
            baseline = str(spec["baseline"])
            drills.append(
                {
                    "role": role,
                    "challenger": challenger,
                    "injected_failure": "governed_primary_process_exit_17",
                    "expected_provider": baseline,
                    "observed_provider": baseline,
                    "output_sha256": hashlib.sha256(
                        f"{role}-{challenger}-fallback".encode()
                    ).hexdigest(),
                    "active_provider_after": baseline,
                    "rollback_provider_after": baseline,
                }
            )
    document = {
        "schema_version": "1.0.0",
        "benchmark_id": "silhouette-variant-fixture-v1",
        "results_opened_at": "2026-07-15T07:35:00Z",
        "policy_sha256": POLICY_SHA256,
        "truth_tier": "human_anchor_gold",
        "truth_partition": "holdout",
        "truth_manifest_sha256": hashlib.sha256(truth.read_bytes()).hexdigest(),
        "pipeline_fingerprint_sha256": "b" * 64,
        "hardware_fingerprint_sha256": "c" * 64,
        "providers": {
            provider: _provider_evidence(provider, policy) for provider in PROVIDER_CAPABILITIES
        },
        "fallback_drills": drills,
    }
    _reseal(document)
    return document, truth


def _rows(document: dict, provider: str, role: str) -> list[dict]:
    return [row for row in document["providers"][provider]["observations"] if row["role"] == role]


def test_frozen_policy_is_schema_valid_hash_locked_and_source_current() -> None:
    policy = load_policy()
    assert DEFAULT_POLICY_PATH == (
        ROOT / "qa/governance/benchmark_matrices/silhouette_variant_benchmark_v1.json"
    )
    assert policy["sha256"] == POLICY_SHA256
    assert policy["roles"]["matting"]["baseline"] == "vitmatte_small"
    assert policy["providers"]["birefnet_hr"]["governed_resolution"] == 1024
    assert not validate_document(policy, "silhouette_variant_benchmark_policy")


def test_policy_edit_fails_after_reseal() -> None:
    policy = json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    policy["pass_requirements"]["max_peak_vram_bytes"] += 1
    _reseal(policy)
    with pytest.raises(SilhouetteBenchmarkError, match="8589410304|locked hash"):
        validate_policy(policy)


def test_complete_report_recomputes_all_roles_contexts_labels_and_routes(
    tmp_path: Path,
) -> None:
    cases, truth = _fixture(tmp_path)
    report = build_report(cases, truth_manifest_path=truth)
    assert not validate_document(report, "silhouette_variant_benchmark_report")
    assert report["result"] == "pass"
    assert len(report["providers"]) == 5
    assert len(report["comparisons"]) == 8
    assert len(report["fallback_drills"]) == 8
    dynamic = next(row for row in report["providers"] if row["provider"] == "birefnet_dynamic")
    assert [row["role"] for row in dynamic["role_metrics"]] == [
        "silhouette",
        "hair_edge",
        "matting",
    ]
    silhouette = dynamic["role_metrics"][0]["overall"]
    assert silhouette["case_count"] == 10
    assert silhouette["total_pixels"] == 5000
    assert silhouette["foreground_iou"] == pytest.approx(380 / 420)
    assert silhouette["foreground_leakage_rate"] == pytest.approx(20 / 600)
    assert silhouette["boundary_f_2px"] == pytest.approx(180 / 190)
    assert silhouette["correction_pixels_per_100k"] == 4000
    assert silhouette["alpha_mse"] is None
    matting = dynamic["role_metrics"][2]["overall"]
    assert matting["alpha_mae"] == 0.02
    assert matting["alpha_mse"] == 0.005
    verify_report(report, cases, truth_manifest_path=truth)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing_observation", "coverage is incomplete"),
        ("duplicate_observation", "duplicate .* observation"),
        ("unsupported_role", "unsupported role|vocabulary is invalid"),
        ("truth_pixel_mismatch", "do not reconcile"),
        ("intersection_overflow", "intersection exceeds"),
        ("leakage_overflow", "leakage numerator exceeds"),
        ("binary_alpha", "binary role carries alpha"),
        ("matting_alpha_denominator", "alpha denominator"),
        ("artifact_drift", "artifact identity mismatch"),
        ("resolution_drift", "governed resolution mismatch"),
        ("nondeterministic", "deterministic repeat evidence failed"),
    ],
)
def test_completeness_pixel_and_identity_invariants_fail_closed(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    cases, truth = _fixture(tmp_path)
    provider = cases["providers"]["birefnet_dynamic"]
    if mutation == "missing_observation":
        provider["observations"].pop()
    elif mutation == "duplicate_observation":
        provider["observations"].append(copy.deepcopy(provider["observations"][0]))
    elif mutation == "unsupported_role":
        provider["observations"][0]["role"] = "matting"
    elif mutation == "truth_pixel_mismatch":
        provider["observations"][0]["truth_background_pixels"] -= 1
    elif mutation == "intersection_overflow":
        provider["observations"][0]["intersection_pixels"] = 401
    elif mutation == "leakage_overflow":
        provider["observations"][0]["false_positive_background_pixels"] = 601
    elif mutation == "binary_alpha":
        provider["observations"][0]["alpha_reference_pixels"] = 1000
    elif mutation == "matting_alpha_denominator":
        _rows(cases, "birefnet_dynamic", "matting")[0]["alpha_reference_pixels"] = 999
    elif mutation == "artifact_drift":
        provider["artifact_hashes"]["checkpoint"] = "f" * 64
    elif mutation == "resolution_drift":
        provider["governed_resolution"] = 2048
    elif mutation == "nondeterministic":
        provider["runtime_metrics"]["deterministic_output_sha256"][1] = "f" * 64
    _reseal(cases)
    with pytest.raises(SilhouetteBenchmarkError, match=expected):
        build_report(cases, truth_manifest_path=truth)


@pytest.mark.parametrize(
    ("mutation", "finding"),
    [
        ("boundary", "boundary_f_2px_noninferiority_failed"),
        ("iou", "foreground_iou_noninferiority_failed"),
        ("leakage", "foreground_leakage_regression"),
        ("alpha", "alpha_mse_regression"),
        ("runtime", "runtime_failure"),
        ("repeats", "determinism_repeat_count_failed"),
        ("fallback", "fallback_drill_failed"),
    ],
)
def test_each_quality_runtime_and_fallback_gate_is_exact(
    tmp_path: Path, mutation: str, finding: str
) -> None:
    cases, truth = _fixture(tmp_path)
    role = "matting" if mutation == "alpha" else "silhouette"
    challenger = "birefnet_dynamic"
    rows = _rows(cases, challenger, role)
    if mutation == "boundary":
        for row in rows:
            row.update(
                boundary_true_positive=60, boundary_false_positive=20, boundary_false_negative=20
            )
    elif mutation == "iou":
        for row in rows:
            row["intersection_pixels"] = 300
    elif mutation == "leakage":
        for row in rows:
            row["false_positive_background_pixels"] = 40
    elif mutation == "alpha":
        for row in rows:
            row["alpha_squared_error_sum"] = 10.0
    elif mutation == "runtime":
        cases["providers"][challenger]["runtime_metrics"]["crash_count"] = 1
    elif mutation == "vram":
        cases["providers"][challenger]["runtime_metrics"]["peak_vram_bytes"] = 9_000_000_000
    elif mutation == "repeats":
        runtime = cases["providers"][challenger]["runtime_metrics"]
        runtime["repeat_count"] = 3
        runtime["deterministic_output_sha256"] = ["a" * 64] * 3
    elif mutation == "fallback":
        cases["fallback_drills"][0]["observed_provider"] = challenger
    _reseal(cases)
    report = build_report(cases, truth_manifest_path=truth)
    assert report["result"] == "fail"
    assert any(item.endswith(finding) for item in report["findings"])
    verify_report(report, cases, truth_manifest_path=truth, require_pass=False)
    with pytest.raises(SilhouetteBenchmarkError, match="gates failed"):
        verify_report(report, cases, truth_manifest_path=truth)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("truth_tier", "human_anchor_gold"),
        ("results_opened_at", "predate frozen policy"),
        ("policy_sha256", "policy hash mismatch"),
        ("provider_set", "birefnet_hr_matting.*required|provider set is incomplete"),
        ("fallback_set", "fallback drill matrix"),
    ],
)
def test_authority_and_exact_set_bindings_fail_closed(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    cases, truth = _fixture(tmp_path)
    if mutation == "truth_tier":
        cases["truth_tier"] = "autonomous_certified_gold"
    elif mutation == "results_opened_at":
        cases["results_opened_at"] = "2026-07-15T07:32:00Z"
    elif mutation == "policy_sha256":
        cases["policy_sha256"] = "f" * 64
    elif mutation == "provider_set":
        cases["providers"].pop("birefnet_hr_matting")
    elif mutation == "fallback_set":
        cases["fallback_drills"].pop()
        cases["fallback_drills"].append(copy.deepcopy(cases["fallback_drills"][0]))
    _reseal(cases)
    with pytest.raises(SilhouetteBenchmarkError, match=expected):
        build_report(cases, truth_manifest_path=truth)


def test_truth_manifest_drift_and_report_tamper_fail(tmp_path: Path) -> None:
    cases, truth = _fixture(tmp_path)
    report = build_report(cases, truth_manifest_path=truth)
    report["comparisons"][0]["foreground_iou_delta"] = 0.99
    _reseal(report)
    with pytest.raises(SilhouetteBenchmarkError, match="recomputation mismatch"):
        verify_report(report, cases, truth_manifest_path=truth)
    truth.write_text("drift\n", encoding="utf-8")
    with pytest.raises(SilhouetteBenchmarkError, match="truth manifest hash mismatch"):
        build_report(cases, truth_manifest_path=truth)


def test_one_command_builds_and_verifies_hash_sealed_report(tmp_path: Path) -> None:
    cases, truth = _fixture(tmp_path)
    cases_path = tmp_path / "cases.json"
    report_path = tmp_path / "report.json"
    cases_path.write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    command = [
        sys.executable,
        str(ROOT / "tools/evaluate_silhouette_variant_benchmark.py"),
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
