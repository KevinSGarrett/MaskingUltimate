from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from maskfactory.validation import validate_document
from maskfactory.vlm.qwen_benchmark import (
    CHALLENGERS,
    DATASETS,
    HIGH_RISK_CONTEXTS,
    POLICY_SHA256,
    PROVIDERS,
    QwenBenchmarkError,
    build_report,
    canonical_sha256,
    file_sha256,
    load_policy,
    validate_policy,
    verify_report,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "qa/governance/benchmark_matrices/qwen_challenger_benchmark_v1.json"
LABELS = ("hair", "left_hand_base", "right_foot_base", "skin", "chest_upper_torso")


def _seal(document: dict) -> dict:
    document["sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    return document


def _case(
    dataset: str,
    index: int,
    *,
    image_id: str,
    defect: bool,
    context: str,
) -> dict:
    return {
        "case_id": f"{dataset}_{index:04d}",
        "image_id": image_id,
        "dataset": dataset,
        "label": LABELS[index % len(LABELS)],
        "contexts": [context],
        "truth_verdict": "fail" if defect else "pass",
        "severity": "serious" if defect and index % 2 == 0 else ("minor" if defect else "none"),
        "natural_error": defect and dataset == "incremental_200",
        "human_anchor_sha256": f"{index + len(dataset):064x}"[-64:],
    }


def _write_manifest(root: Path, dataset: str, cases: list[dict]) -> dict:
    manifest = _seal(
        {
            "schema_version": "1.0.0",
            "dataset": dataset,
            "frozen_at": "2026-07-15T08:43:00Z",
            "authority": "human_anchor_gold",
            "partition": "holdout",
            "case_ids": sorted(case["case_id"] for case in cases),
            "source_image_ids": sorted({case["image_id"] for case in cases}),
        }
    )
    path = root / "manifests" / f"{dataset}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": path.relative_to(root).as_posix(), "sha256": file_sha256(path)}


def _cases() -> list[dict]:
    cases = []
    defect_contexts = HIGH_RISK_CONTEXTS[:-1]
    for index in range(20):
        cases.append(
            _case(
                "teacher_holdout",
                index,
                image_id=f"teacher_image_{index:04d}",
                defect=index >= 10,
                context=(
                    defect_contexts[index % len(defect_contexts)] if index >= 10 else "good_mask"
                ),
            )
        )
    for source in range(20):
        image_id = f"panel_source_{source:04d}"
        cases.append(
            _case(
                "local_40_panel",
                source * 2,
                image_id=image_id,
                defect=False,
                context="good_mask",
            )
        )
        cases.append(
            _case(
                "local_40_panel",
                source * 2 + 1,
                image_id=image_id,
                defect=True,
                context=defect_contexts[source % len(defect_contexts)],
            )
        )
    for index in range(200):
        defect = index >= 100
        cases.append(
            _case(
                "incremental_200",
                index,
                image_id=f"incremental_image_{index:04d}",
                defect=defect,
                context=defect_contexts[index % len(defect_contexts)] if defect else "good_mask",
            )
        )
    return cases


def _observations(cases: list[dict], provider: str) -> list[dict]:
    observations = []
    defect_index = 0
    for case in cases:
        defect = case["truth_verdict"] == "fail"
        if defect:
            defect_index += 1
        missed = provider == "qwen2_5_vl_7b" and defect and defect_index % 10 == 0
        verdict = "uncertain" if missed else ("fail" if defect else "pass")
        observations.append(
            {
                "case_id": case["case_id"],
                "verdict": verdict,
                "correction_useful": True if defect and not missed else None,
                "reviewer_time_sec": 10.0 if provider == "qwen2_5_vl_7b" else 9.0,
            }
        )
    return observations


def _runtime(provider: str) -> dict:
    warm = {"qwen2_5_vl_7b": 900.0, "qwen3_vl_4b": 1000.0, "qwen3_vl_8b_quantized": 1200.0}[
        provider
    ]
    vram = {
        "qwen2_5_vl_7b": 5_000_000_000,
        "qwen3_vl_4b": 3_527_545_978,
        "qwen3_vl_8b_quantized": 5_534_897_929,
    }[provider]
    digest = {"qwen2_5_vl_7b": "1", "qwen3_vl_4b": "2", "qwen3_vl_8b_quantized": "3"}[provider] * 64
    return {
        "cold_latency_ms": warm * 4,
        "warm_latency_ms": warm,
        "peak_vram_bytes": vram,
        "oom_count": 0,
        "crash_count": 0,
        "repeat_count": 2,
        "deterministic_output_sha256": [digest, digest],
    }


def _document(tmp_path: Path) -> tuple[dict, dict]:
    policy = load_policy(POLICY_PATH, root=ROOT)
    cases = _cases()
    manifests = {
        dataset: _write_manifest(
            tmp_path,
            dataset,
            [case for case in cases if case["dataset"] == dataset],
        )
        for dataset in DATASETS
    }
    document = _seal(
        {
            "schema_version": "1.0.0",
            "benchmark_id": "qwen-human-anchor-fixture",
            "evaluated_at": "2026-07-15T08:44:00Z",
            "policy_sha256": policy["sha256"],
            "dataset_manifests": manifests,
            "training_image_ids": ["training_image_0001", "training_image_0002"],
            "cases": cases,
            "providers": [
                {
                    "provider": provider,
                    "identity": copy.deepcopy(policy["provider_identities"][provider]),
                    "observations": _observations(cases, provider),
                    "runtime": _runtime(provider),
                }
                for provider in PROVIDERS
            ],
            "rollback_drills": [
                {
                    "challenger": challenger,
                    "failure_injected": True,
                    "incumbent_before": "qwen2_5_vl_7b",
                    "returned_provider": "qwen2_5_vl_7b",
                    "incumbent_after": "qwen2_5_vl_7b",
                    "returned_output_sha256": ("4" if challenger == CHALLENGERS[0] else "5") * 64,
                }
                for challenger in CHALLENGERS
            ],
        }
    )
    return document, policy


def _provider(document: dict, name: str) -> dict:
    return next(row for row in document["providers"] if row["provider"] == name)


def _observation(provider: dict, case_id: str) -> dict:
    return next(row for row in provider["observations"] if row["case_id"] == case_id)


def test_frozen_policy_and_all_three_schemas_are_current() -> None:
    policy = load_policy(POLICY_PATH, root=ROOT)
    assert policy["sha256"] == POLICY_SHA256
    assert policy["authority"].startswith("pre_result_policy_only")
    for name in (
        "qwen_challenger_benchmark_policy",
        "qwen_challenger_benchmark_cases",
        "qwen_challenger_benchmark_report",
    ):
        schema = json.loads((ROOT / f"src/maskfactory/schemas/{name}.schema.json").read_text())
        Draft202012Validator.check_schema(schema)


def test_report_recomputes_three_corpora_selects_winner_and_denies_mask_authority(
    tmp_path: Path,
) -> None:
    document, policy = _document(tmp_path)
    report = build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)
    assert validate_document(report, "qwen_challenger_benchmark_report") == ()
    assert report["result"] == "pass" and report["winner"] == "qwen3_vl_4b"
    assert [row["challenger"] for row in report["comparisons"]] == list(CHALLENGERS)
    assert all(row["result"] == "pass" for row in report["comparisons"])
    incremental = next(
        row
        for row in report["comparisons"][0]["dataset_results"]
        if row["dataset"] == "incremental_200"
    )
    assert incremental["challenger"]["case_count"] == 200
    assert incremental["challenger"]["overall_defect_recall"] == 1
    assert incremental["reviewer_time_reduction_fraction"] == pytest.approx(0.1)
    assert "no_mask_gold_or_block_clearance_authority" in report["authority"]


def test_report_and_source_cases_are_canonical_hash_bound(tmp_path: Path) -> None:
    document, policy = _document(tmp_path)
    report = build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)
    report["winner"] = "qwen3_vl_8b_quantized"
    report["sha256"] = canonical_sha256(
        {key: value for key, value in report.items() if key != "sha256"}
    )
    with pytest.raises(QwenBenchmarkError, match="exact recomputation"):
        verify_report(report, document, policy=policy, root=ROOT, artifact_root=tmp_path)
    document["sha256"] = "0" * 64
    with pytest.raises(QwenBenchmarkError, match="source cases hash"):
        build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)


def test_policy_rejects_identity_and_governing_source_drift() -> None:
    policy = load_policy(POLICY_PATH, root=ROOT)
    drifted = copy.deepcopy(policy)
    drifted["provider_identities"]["qwen3_vl_4b"]["model_blob_sha256"] = "0" * 64
    _seal(drifted)
    with pytest.raises(QwenBenchmarkError, match="locked hash"):
        validate_policy(drifted, root=ROOT)
    drifted = copy.deepcopy(policy)
    drifted["source_hashes"]["configs/vlm.yaml"] = "0" * 64
    _seal(drifted)
    with pytest.raises(QwenBenchmarkError, match="governing source hash drift"):
        validate_policy(drifted, root=ROOT, expected_sha256=None)


def test_training_leakage_and_cross_partition_overlap_fail(tmp_path: Path) -> None:
    document, policy = _document(tmp_path)
    document["training_image_ids"].append(document["cases"][0]["image_id"])
    _seal(document)
    with pytest.raises(QwenBenchmarkError, match="leaked"):
        build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)

    document, policy = _document(tmp_path)
    teacher = next(case for case in document["cases"] if case["dataset"] == "teacher_holdout")
    incremental = next(case for case in document["cases"] if case["dataset"] == "incremental_200")
    incremental["image_id"] = teacher["image_id"]
    document["dataset_manifests"]["incremental_200"] = _write_manifest(
        tmp_path,
        "incremental_200",
        [case for case in document["cases"] if case["dataset"] == "incremental_200"],
    )
    _seal(document)
    with pytest.raises(QwenBenchmarkError, match="share source images"):
        build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)


def test_local_panel_balance_and_incremental_size_are_exact(tmp_path: Path) -> None:
    document, policy = _document(tmp_path)
    document["cases"] = [
        case for case in document["cases"] if case["case_id"] != "local_40_panel_0039"
    ]
    for provider in document["providers"]:
        provider["observations"] = [
            row for row in provider["observations"] if row["case_id"] != "local_40_panel_0039"
        ]
    _seal(document)
    with pytest.raises(QwenBenchmarkError, match="local gate"):
        build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)

    document, policy = _document(tmp_path)
    removed = next(case for case in document["cases"] if case["case_id"] == "incremental_200_0199")
    document["cases"].remove(removed)
    for provider in document["providers"]:
        provider["observations"] = [
            row for row in provider["observations"] if row["case_id"] != removed["case_id"]
        ]
    _seal(document)
    with pytest.raises(QwenBenchmarkError, match="at least 200"):
        build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)


def test_incremental_context_and_natural_error_requirements_fail_closed(tmp_path: Path) -> None:
    document, policy = _document(tmp_path)
    for case in document["cases"]:
        if case["dataset"] == "incremental_200" and case["contexts"] == ["occlusion"]:
            case["contexts"] = ["hair"]
    _seal(document)
    with pytest.raises(QwenBenchmarkError, match="coverage is incomplete"):
        build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)

    document, policy = _document(tmp_path)
    defect = next(
        case
        for case in document["cases"]
        if case["dataset"] == "incremental_200" and case["truth_verdict"] == "fail"
    )
    defect["natural_error"] = False
    _seal(document)
    with pytest.raises(QwenBenchmarkError, match="naturally occurring"):
        build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)


def test_candidate_identity_observation_coverage_and_usefulness_are_strict(tmp_path: Path) -> None:
    document, policy = _document(tmp_path)
    _provider(document, "qwen3_vl_4b")["identity"]["model"] = "different"
    _seal(document)
    with pytest.raises(QwenBenchmarkError, match="identity mismatch"):
        build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)

    document, policy = _document(tmp_path)
    _provider(document, "qwen3_vl_4b")["observations"].pop()
    _seal(document)
    with pytest.raises(QwenBenchmarkError, match="cover every case"):
        build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)

    document, policy = _document(tmp_path)
    provider = _provider(document, "qwen3_vl_4b")
    good_case = next(case for case in document["cases"] if case["truth_verdict"] == "pass")
    _observation(provider, good_case["case_id"])["correction_useful"] = False
    _seal(document)
    with pytest.raises(QwenBenchmarkError, match="true-positive diagnoses"):
        build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)


def test_per_label_regression_and_reviewer_time_regression_block_candidate(tmp_path: Path) -> None:
    document, policy = _document(tmp_path)
    provider = _provider(document, "qwen3_vl_4b")
    target = next(
        case
        for case in document["cases"]
        if case["truth_verdict"] == "fail"
        and _observation(_provider(document, "qwen2_5_vl_7b"), case["case_id"])["verdict"] == "fail"
    )
    observation = _observation(provider, target["case_id"])
    observation["verdict"] = "uncertain"
    observation["correction_useful"] = None
    _seal(document)
    report = build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)
    comparison = report["comparisons"][0]
    assert "per_label_or_high_risk_regression" in comparison["findings"]
    assert comparison["result"] == "fail"

    document, policy = _document(tmp_path)
    for observation in _provider(document, "qwen3_vl_4b")["observations"]:
        observation["reviewer_time_sec"] = 11.0
    _seal(document)
    report = build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)
    assert any(
        finding.endswith("median_reviewer_time_regression")
        for finding in report["comparisons"][0]["findings"]
    )


@pytest.mark.parametrize(
    ("field", "value", "finding"),
    [
        ("warm_latency_ms", 2000.0, "warm_latency_regression"),
        ("oom_count", 1, "runtime_oom_or_crash"),
        ("crash_count", 1, "runtime_oom_or_crash"),
    ],
)
def test_runtime_regressions_block_promotion(
    tmp_path: Path, field: str, value: int | float, finding: str
) -> None:
    document, policy = _document(tmp_path)
    _provider(document, "qwen3_vl_4b")["runtime"][field] = value
    _seal(document)
    report = build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)
    assert finding in report["comparisons"][0]["findings"]


def test_determinism_and_rollback_drift_fail_closed(tmp_path: Path) -> None:
    document, policy = _document(tmp_path)
    _provider(document, "qwen3_vl_4b")["runtime"]["deterministic_output_sha256"][1] = "9" * 64
    _seal(document)
    with pytest.raises(QwenBenchmarkError, match="deterministic repeat"):
        build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)

    document, policy = _document(tmp_path)
    document["rollback_drills"][0]["returned_provider"] = "qwen3_vl_4b"
    _seal(document)
    with pytest.raises(QwenBenchmarkError, match="returned_provider"):
        build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)


def test_no_measured_quality_or_labor_win_cannot_promote(tmp_path: Path) -> None:
    document, policy = _document(tmp_path)
    incumbent = _provider(document, "qwen2_5_vl_7b")
    candidate = _provider(document, "qwen3_vl_4b")
    candidate["observations"] = copy.deepcopy(incumbent["observations"])
    for row in candidate["observations"]:
        row["reviewer_time_sec"] = 10.0
    _seal(document)
    report = build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)
    assert "no_measured_quality_or_labor_win" in report["comparisons"][0]["findings"]


def test_manifest_hash_authority_time_and_path_escape_are_rejected(tmp_path: Path) -> None:
    document, policy = _document(tmp_path)
    document["dataset_manifests"]["teacher_holdout"]["sha256"] = "0" * 64
    _seal(document)
    with pytest.raises(QwenBenchmarkError, match="file/hash mismatch"):
        build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)

    document, policy = _document(tmp_path)
    document["evaluated_at"] = policy["frozen_at"]
    _seal(document)
    with pytest.raises(QwenBenchmarkError, match="predate"):
        build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)

    document, policy = _document(tmp_path)
    document["dataset_manifests"]["teacher_holdout"]["path"] = "../escape.json"
    _seal(document)
    with pytest.raises(QwenBenchmarkError, match="escapes"):
        build_report(document, policy=policy, root=ROOT, artifact_root=tmp_path)


def test_cli_builds_and_verifies_exact_report(tmp_path: Path) -> None:
    document, _policy = _document(tmp_path)
    cases_path = tmp_path / "cases.json"
    report_path = tmp_path / "report.json"
    cases_path.write_text(json.dumps(document), encoding="utf-8")
    command = [
        sys.executable,
        str(ROOT / "tools/evaluate_qwen_challenger_benchmark.py"),
        str(cases_path),
        "--policy",
        str(POLICY_PATH),
        "--root",
        str(ROOT),
        "--artifact-root",
        str(tmp_path),
        "--output",
        str(report_path),
    ]
    built = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    assert json.loads(built.stdout)["winner"] == "qwen3_vl_4b"
    verified = subprocess.run(
        command + ["--verify"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    assert (
        json.loads(verified.stdout)["sha256"]
        == json.loads(report_path.read_text(encoding="utf-8"))["sha256"]
    )
