"""Frozen Qwen challenger benchmark across human-anchor evaluation partitions."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from ..validation import ArtifactValidationError, require_valid_document

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY_PATH = (
    ROOT / "qa" / "governance" / "benchmark_matrices" / "qwen_challenger_benchmark_v1.json"
)
POLICY_SHA256 = "3425c7464035eb012e6c4220748103d61df6b7bb8a69cef24e14b6fdfa163ffd"
DATASETS = ("teacher_holdout", "local_40_panel", "incremental_200")
PROVIDERS = ("qwen2_5_vl_7b", "qwen3_vl_4b", "qwen3_vl_8b_quantized")
CHALLENGERS = PROVIDERS[1:]
HIGH_RISK_CONTEXTS = (
    "serious_anatomy_swap",
    "missing_part",
    "neighbor_or_person_contamination",
    "clothing_skin_boundary",
    "hair",
    "hands_or_fingers",
    "feet_or_toes",
    "occlusion",
    "multi_person_contact",
    "good_mask",
)
SOURCE_FILES = (
    "configs/cloud_teacher.yaml",
    "configs/external_sources.yaml",
    "configs/vlm.yaml",
    "env/qwen3_vl_ollama.lock.json",
    "models/model_registry.json",
    "src/maskfactory/providers/qwen3_vl.py",
    "src/maskfactory/vlm/client.py",
    "src/maskfactory/vlm/cloud_teacher.py",
    "src/maskfactory/vlm/eval.py",
    "src/maskfactory/vlm/prompts/p_workhorse.txt",
)


class QwenBenchmarkError(ValueError):
    """Qwen benchmark policy, observations, report, or rollback evidence is invalid."""


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise QwenBenchmarkError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise QwenBenchmarkError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC)


def _count(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QwenBenchmarkError(f"{field} must be a nonnegative integer")
    return value


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QwenBenchmarkError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise QwenBenchmarkError(f"{field} must be finite and nonnegative")
    return result


def _rate(numerator: int | float, denominator: int | float) -> float:
    return numerator / denominator if denominator else 0.0


def _schema(document: Mapping[str, Any], name: str) -> None:
    try:
        require_valid_document(document, name)
    except ArtifactValidationError as exc:
        raise QwenBenchmarkError(str(exc)) from exc


def validate_policy(
    policy: Mapping[str, Any],
    *,
    root: Path = ROOT,
    expected_sha256: str | None = POLICY_SHA256,
) -> None:
    _schema(policy, "qwen_challenger_benchmark_policy")
    payload = {key: value for key, value in policy.items() if key != "sha256"}
    if policy["sha256"] != canonical_sha256(payload):
        raise QwenBenchmarkError("Qwen benchmark policy hash mismatch")
    if expected_sha256 is not None and policy["sha256"] != expected_sha256:
        raise QwenBenchmarkError("Qwen benchmark policy differs from locked hash")
    _timestamp(policy["frozen_at"], "frozen_at")
    if tuple(policy["datasets"]) != DATASETS:
        raise QwenBenchmarkError("Qwen benchmark dataset order drifted")
    if tuple(policy["high_risk_contexts"]) != HIGH_RISK_CONTEXTS:
        raise QwenBenchmarkError("Qwen benchmark high-risk contexts drifted")
    if tuple(policy["providers"]) != PROVIDERS or tuple(policy["challengers"]) != CHALLENGERS:
        raise QwenBenchmarkError("Qwen benchmark provider identities drifted")
    if policy["incumbent"] != "qwen2_5_vl_7b" or policy["rollback_provider"] != "qwen2_5_vl_7b":
        raise QwenBenchmarkError("Qwen benchmark incumbent/rollback drifted")
    if policy["fallback_provider"] != "llava_13b":
        raise QwenBenchmarkError("Qwen benchmark fallback drifted")
    if policy["generation_options"] != {
        "num_ctx": 4096,
        "num_predict": 192,
        "seed": 1337,
        "temperature": 0,
        "think": False,
    }:
        raise QwenBenchmarkError("Qwen benchmark generation options drifted")
    if set(policy["provider_identities"]) != set(PROVIDERS):
        raise QwenBenchmarkError("Qwen benchmark provider identity set is incomplete")
    if set(policy["source_hashes"]) != set(SOURCE_FILES):
        raise QwenBenchmarkError("Qwen benchmark source hash set is incomplete")
    root = Path(root)
    for relative in SOURCE_FILES:
        source = root / relative
        if not source.is_file() or file_sha256(source) != policy["source_hashes"][relative]:
            raise QwenBenchmarkError(f"governing source hash drift: {relative}")


def load_policy(path: Path = DEFAULT_POLICY_PATH, *, root: Path = ROOT) -> dict[str, Any]:
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(policy, dict):
        raise QwenBenchmarkError("Qwen benchmark policy is not an object")
    validate_policy(policy, root=root)
    return policy


def _contained_path(root: Path, relative: str, field: str) -> Path:
    root = Path(root).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise QwenBenchmarkError(f"{field} escapes the benchmark root") from exc
    return path


def _validate_manifest(
    reference: Mapping[str, Any],
    dataset: str,
    cases: Sequence[Mapping[str, Any]],
    *,
    root: Path,
) -> datetime:
    path = _contained_path(root, reference["path"], f"{dataset} manifest")
    if not path.is_file() or file_sha256(path) != reference["sha256"]:
        raise QwenBenchmarkError(f"{dataset} manifest file/hash mismatch")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    expected_keys = {
        "schema_version",
        "dataset",
        "frozen_at",
        "authority",
        "partition",
        "case_ids",
        "source_image_ids",
        "sha256",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise QwenBenchmarkError(f"{dataset} manifest contract is invalid")
    payload = {key: value for key, value in manifest.items() if key != "sha256"}
    if manifest["sha256"] != canonical_sha256(payload):
        raise QwenBenchmarkError(f"{dataset} manifest canonical hash mismatch")
    if (
        manifest["schema_version"] != "1.0.0"
        or manifest["dataset"] != dataset
        or manifest["authority"] != "human_anchor_gold"
        or manifest["partition"] != "holdout"
    ):
        raise QwenBenchmarkError(f"{dataset} lacks frozen human-anchor holdout authority")
    case_ids = sorted(str(case["case_id"]) for case in cases)
    image_ids = sorted({str(case["image_id"]) for case in cases})
    if manifest["case_ids"] != case_ids or manifest["source_image_ids"] != image_ids:
        raise QwenBenchmarkError(f"{dataset} manifest population mismatch")
    return _timestamp(manifest["frozen_at"], f"{dataset}.frozen_at")


def _validate_case(case: Mapping[str, Any]) -> None:
    if case["dataset"] not in DATASETS:
        raise QwenBenchmarkError("Qwen benchmark case dataset is invalid")
    if case["truth_verdict"] not in {"pass", "fail"}:
        raise QwenBenchmarkError("Qwen benchmark truth verdict is invalid")
    if case["severity"] not in {"none", "minor", "serious"}:
        raise QwenBenchmarkError("Qwen benchmark severity is invalid")
    if (case["truth_verdict"] == "pass") != (case["severity"] == "none"):
        raise QwenBenchmarkError("Qwen benchmark truth verdict/severity disagree")
    contexts = tuple(case["contexts"])
    if (
        not contexts
        or len(set(contexts)) != len(contexts)
        or not set(contexts) <= set(HIGH_RISK_CONTEXTS)
    ):
        raise QwenBenchmarkError("Qwen benchmark case context vocabulary is invalid")
    if case["truth_verdict"] == "pass":
        if contexts != ("good_mask",) or case["natural_error"] is not False:
            raise QwenBenchmarkError("good-mask cases cannot claim natural defects")
    elif case["dataset"] == "incremental_200" and case["natural_error"] is not True:
        raise QwenBenchmarkError("incremental defect cases must be naturally occurring")


def _validate_populations(cases: Sequence[Mapping[str, Any]], training_images: set[str]) -> None:
    if len({case["case_id"] for case in cases}) != len(cases):
        raise QwenBenchmarkError("Qwen benchmark case IDs must be globally unique")
    by_dataset = {name: [case for case in cases if case["dataset"] == name] for name in DATASETS}
    teacher = by_dataset["teacher_holdout"]
    if (
        not teacher
        or not any(case["truth_verdict"] == "pass" for case in teacher)
        or not any(case["truth_verdict"] == "fail" for case in teacher)
        or not any(case["severity"] == "serious" for case in teacher)
    ):
        raise QwenBenchmarkError("teacher holdout lacks good, defect, or serious coverage")
    local = by_dataset["local_40_panel"]
    if (
        len(local) != 40
        or sum(case["truth_verdict"] == "pass" for case in local) != 20
        or len({case["image_id"] for case in local}) != 20
        or set(Counter(case["image_id"] for case in local).values()) != {2}
    ):
        raise QwenBenchmarkError("local gate must be 20 good/20 defect panels from 20 sources")
    incremental = by_dataset["incremental_200"]
    if (
        len(incremental) < 200
        or not any(case["truth_verdict"] == "pass" for case in incremental)
        or not any(case["truth_verdict"] == "fail" for case in incremental)
        or not any(case["severity"] == "serious" for case in incremental)
    ):
        raise QwenBenchmarkError(
            "incremental benchmark requires at least 200 cases with good, defect, and serious coverage"
        )
    covered = {context for case in incremental for context in case["contexts"]}
    if covered != set(HIGH_RISK_CONTEXTS):
        raise QwenBenchmarkError("incremental benchmark high-risk coverage is incomplete")
    images = {name: {case["image_id"] for case in rows} for name, rows in by_dataset.items()}
    if any(values & training_images for values in images.values()):
        raise QwenBenchmarkError("evaluation image leaked from Qwen training data")
    for index, left in enumerate(DATASETS):
        for right in DATASETS[index + 1 :]:
            if images[left] & images[right]:
                raise QwenBenchmarkError("Qwen benchmark partitions share source images")


def _validate_provider(
    evidence: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    provider = evidence["provider"]
    if evidence["identity"] != policy["provider_identities"][provider]:
        raise QwenBenchmarkError(f"{provider} immutable candidate identity mismatch")
    observations: dict[str, Mapping[str, Any]] = {}
    truth = {str(case["case_id"]): case for case in cases}
    for observation in evidence["observations"]:
        case_id = observation["case_id"]
        if case_id not in truth or case_id in observations:
            raise QwenBenchmarkError(f"{provider} observation population is invalid")
        if observation["verdict"] not in {"pass", "fail", "uncertain"}:
            raise QwenBenchmarkError(f"{provider} observation verdict is invalid")
        _number(observation["reviewer_time_sec"], "reviewer_time_sec")
        is_true_positive = (
            truth[case_id]["truth_verdict"] == "fail" and observation["verdict"] == "fail"
        )
        if is_true_positive != isinstance(observation["correction_useful"], bool):
            raise QwenBenchmarkError(
                f"{provider} correction usefulness is not scoped to true-positive diagnoses"
            )
        observations[case_id] = observation
    if set(observations) != set(truth):
        raise QwenBenchmarkError(f"{provider} observations do not cover every case")
    runtime = evidence["runtime"]
    for field in ("cold_latency_ms", "warm_latency_ms", "peak_vram_bytes"):
        _number(runtime[field], f"{provider}.{field}")
    for field in ("oom_count", "crash_count", "repeat_count"):
        _count(runtime[field], f"{provider}.{field}")
    repeats = runtime["deterministic_output_sha256"]
    if len(repeats) != runtime["repeat_count"] or len(set(repeats)) != 1:
        raise QwenBenchmarkError(f"{provider} deterministic repeat evidence failed")
    return observations


def _summary(
    cases: Sequence[Mapping[str, Any]], observations: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    defects = [case for case in cases if case["truth_verdict"] == "fail"]
    serious = [case for case in defects if case["severity"] == "serious"]
    true_positive = [case for case in defects if observations[case["case_id"]]["verdict"] == "fail"]
    false_positive = [
        case
        for case in cases
        if case["truth_verdict"] == "pass" and observations[case["case_id"]]["verdict"] == "fail"
    ]
    false_negative = [
        case for case in defects if observations[case["case_id"]]["verdict"] != "fail"
    ]
    false_pass = [case for case in defects if observations[case["case_id"]]["verdict"] == "pass"]
    serious_tp = [case for case in serious if observations[case["case_id"]]["verdict"] == "fail"]
    useful = sum(
        observations[case["case_id"]]["correction_useful"] is True for case in true_positive
    )
    review_times = [float(observations[case["case_id"]]["reviewer_time_sec"]) for case in cases]
    return {
        "case_count": len(cases),
        "defect_count": len(defects),
        "serious_defect_count": len(serious),
        "true_positive_count": len(true_positive),
        "false_positive_count": len(false_positive),
        "false_negative_count": len(false_negative),
        "false_pass_count": len(false_pass),
        "serious_true_positive_count": len(serious_tp),
        "useful_correction_count": useful,
        "overall_defect_recall": _rate(len(true_positive), len(defects)),
        "serious_defect_recall": _rate(len(serious_tp), len(serious)),
        "precision": _rate(len(true_positive), len(true_positive) + len(false_positive)),
        "false_pass_rate": _rate(len(false_pass), len(defects)),
        "correction_usefulness": _rate(useful, len(true_positive)),
        "median_reviewer_time_sec": median(review_times),
        "reviewer_time_sum_sec": sum(review_times),
    }


def _stratum_summaries(
    cases: Sequence[Mapping[str, Any]], observations: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    strata: dict[str, list[Mapping[str, Any]]] = {}
    for case in cases:
        strata.setdefault(f"label:{case['label']}", []).append(case)
        for context in case["contexts"]:
            strata.setdefault(f"context:{context}", []).append(case)
    return {name: _summary(rows, observations) for name, rows in sorted(strata.items())}


def _absolute_findings(
    dataset: str, summary: Mapping[str, Any], thresholds: Mapping[str, Any]
) -> list[str]:
    findings: list[str] = []
    checks = {
        "serious_defect_recall": ("minimum", thresholds["minimum_serious_defect_recall"]),
        "overall_defect_recall": ("minimum", thresholds["minimum_overall_defect_recall"]),
        "precision": ("minimum", thresholds["minimum_precision"]),
        "false_pass_rate": ("maximum", thresholds["maximum_false_pass_rate"]),
        "correction_usefulness": ("minimum", thresholds["minimum_correction_usefulness"]),
    }
    for field, (direction, limit) in checks.items():
        if field == "serious_defect_recall" and not summary["serious_defect_count"]:
            continue
        if field in {"overall_defect_recall", "false_pass_rate"} and not summary["defect_count"]:
            continue
        if field == "correction_usefulness" and not summary["true_positive_count"]:
            continue
        actual = float(summary[field])
        if (direction == "minimum" and actual < limit) or (
            direction == "maximum" and actual > limit
        ):
            findings.append(f"{dataset}:{field}_{direction}_gate_failed")
    return findings


def _comparison(
    challenger: str,
    cases: Sequence[Mapping[str, Any]],
    observations: Mapping[str, Mapping[str, Mapping[str, Any]]],
    evidence: Mapping[str, Mapping[str, Any]],
    rollback: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    incumbent = policy["incumbent"]
    thresholds = policy["pass_requirements"]
    by_dataset = {name: [case for case in cases if case["dataset"] == name] for name in DATASETS}
    dataset_results = []
    findings: list[str] = []
    for dataset, rows in by_dataset.items():
        baseline = _summary(rows, observations[incumbent])
        candidate = _summary(rows, observations[challenger])
        recall_delta = candidate["overall_defect_recall"] - baseline["overall_defect_recall"]
        serious_delta = candidate["serious_defect_recall"] - baseline["serious_defect_recall"]
        time_reduction = _rate(
            baseline["median_reviewer_time_sec"] - candidate["median_reviewer_time_sec"],
            baseline["median_reviewer_time_sec"],
        )
        dataset_findings = _absolute_findings(dataset, candidate, thresholds)
        if serious_delta < 0:
            dataset_findings.append(f"{dataset}:serious_recall_regression")
        if candidate["median_reviewer_time_sec"] > baseline["median_reviewer_time_sec"]:
            dataset_findings.append(f"{dataset}:median_reviewer_time_regression")
        findings.extend(dataset_findings)
        dataset_results.append(
            {
                "dataset": dataset,
                "incumbent": baseline,
                "challenger": candidate,
                "recall_delta": recall_delta,
                "serious_recall_delta": serious_delta,
                "reviewer_time_reduction_fraction": time_reduction,
                "findings": sorted(dataset_findings),
            }
        )

    base_strata = _stratum_summaries(cases, observations[incumbent])
    candidate_strata = _stratum_summaries(cases, observations[challenger])
    stratum_regressions = []
    for name in base_strata:
        baseline, candidate = base_strata[name], candidate_strata[name]
        if baseline["defect_count"] and (
            candidate["overall_defect_recall"] < baseline["overall_defect_recall"]
            or candidate["false_pass_count"] > baseline["false_pass_count"]
        ):
            stratum_regressions.append(name)
    if stratum_regressions:
        findings.append("per_label_or_high_risk_regression")

    runtime = evidence[challenger]["runtime"]
    baseline_runtime = evidence[incumbent]["runtime"]
    latency_delta_fraction = _rate(
        runtime["warm_latency_ms"] - baseline_runtime["warm_latency_ms"],
        baseline_runtime["warm_latency_ms"],
    )
    if runtime["peak_vram_bytes"] > thresholds["maximum_peak_vram_bytes"]:
        findings.append("peak_vram_exceeds_8gb")
    if latency_delta_fraction > thresholds["maximum_warm_latency_regression_fraction"]:
        findings.append("warm_latency_regression")
    if runtime["oom_count"] or runtime["crash_count"]:
        findings.append("runtime_oom_or_crash")
    if runtime["repeat_count"] != thresholds["required_deterministic_repeats"]:
        findings.append("deterministic_repeat_count_mismatch")
    if rollback != {
        "challenger": challenger,
        "failure_injected": True,
        "incumbent_before": incumbent,
        "returned_provider": incumbent,
        "incumbent_after": incumbent,
        "returned_output_sha256": rollback["returned_output_sha256"],
    }:
        findings.append("rollback_drill_failed")

    incremental = next(row for row in dataset_results if row["dataset"] == "incremental_200")
    measured_win = (
        incremental["recall_delta"] >= thresholds["minimum_recall_improvement_over_incumbent"]
        or incremental["reviewer_time_reduction_fraction"]
        >= thresholds["minimum_reviewer_time_reduction_fraction"]
    )
    if not measured_win:
        findings.append("no_measured_quality_or_labor_win")
    return {
        "challenger": challenger,
        "dataset_results": dataset_results,
        "stratum_regressions": stratum_regressions,
        "runtime": {
            "incumbent_warm_latency_ms": baseline_runtime["warm_latency_ms"],
            "challenger_warm_latency_ms": runtime["warm_latency_ms"],
            "warm_latency_delta_fraction": latency_delta_fraction,
            "challenger_peak_vram_bytes": runtime["peak_vram_bytes"],
            "oom_count": runtime["oom_count"],
            "crash_count": runtime["crash_count"],
            "repeat_count": runtime["repeat_count"],
        },
        "measured_win": measured_win,
        "rollback": dict(rollback),
        "findings": sorted(set(findings)),
        "result": "pass" if not findings else "fail",
    }


def validate_cases(
    document: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    root: Path = ROOT,
    artifact_root: Path | None = None,
) -> tuple[
    list[Mapping[str, Any]], dict[str, dict[str, Mapping[str, Any]]], dict[str, Mapping[str, Any]]
]:
    _schema(document, "qwen_challenger_benchmark_cases")
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if document["sha256"] != canonical_sha256(payload):
        raise QwenBenchmarkError("Qwen benchmark source cases hash mismatch")
    if document["policy_sha256"] != policy["sha256"]:
        raise QwenBenchmarkError("Qwen benchmark cases reference the wrong policy")
    evaluated_at = _timestamp(document["evaluated_at"], "evaluated_at")
    if evaluated_at <= _timestamp(policy["frozen_at"], "policy.frozen_at"):
        raise QwenBenchmarkError("Qwen benchmark observations predate the frozen policy")
    cases = list(document["cases"])
    for case in cases:
        _validate_case(case)
    training_images = set(document["training_image_ids"])
    if len(training_images) != len(document["training_image_ids"]):
        raise QwenBenchmarkError("Qwen training image IDs are duplicated")
    _validate_populations(cases, training_images)
    references = document["dataset_manifests"]
    artifact_root = Path(artifact_root) if artifact_root is not None else Path(root)
    if set(references) != set(DATASETS):
        raise QwenBenchmarkError("Qwen benchmark dataset manifest set is incomplete")
    for dataset in DATASETS:
        rows = [case for case in cases if case["dataset"] == dataset]
        if evaluated_at <= _validate_manifest(
            references[dataset], dataset, rows, root=artifact_root
        ):
            raise QwenBenchmarkError(f"{dataset} observations predate its frozen manifest")
    provider_evidence = {row["provider"]: row for row in document["providers"]}
    if set(provider_evidence) != set(PROVIDERS) or len(provider_evidence) != len(
        document["providers"]
    ):
        raise QwenBenchmarkError("Qwen benchmark provider evidence set is invalid")
    observations = {
        provider: _validate_provider(provider_evidence[provider], cases, policy)
        for provider in PROVIDERS
    }
    drills = {row["challenger"]: row for row in document["rollback_drills"]}
    if set(drills) != set(CHALLENGERS) or len(drills) != len(document["rollback_drills"]):
        raise QwenBenchmarkError("Qwen benchmark rollback drill set is invalid")
    return cases, observations, provider_evidence


def build_report(
    document: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    root: Path = ROOT,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    policy = dict(policy or load_policy(root=Path(root)))
    validate_policy(policy, root=root)
    cases, observations, provider_evidence = validate_cases(
        document, policy, root=root, artifact_root=artifact_root
    )
    drills = {row["challenger"]: row for row in document["rollback_drills"]}
    comparisons = [
        _comparison(
            challenger,
            cases,
            observations,
            provider_evidence,
            drills[challenger],
            policy,
        )
        for challenger in CHALLENGERS
    ]
    passing = [row for row in comparisons if row["result"] == "pass"]
    passing.sort(
        key=lambda row: (
            -next(
                result["recall_delta"]
                for result in row["dataset_results"]
                if result["dataset"] == "incremental_200"
            ),
            -next(
                result["reviewer_time_reduction_fraction"]
                for result in row["dataset_results"]
                if result["dataset"] == "incremental_200"
            ),
            row["runtime"]["challenger_warm_latency_ms"],
            row["challenger"],
        )
    )
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "benchmark_id": document["benchmark_id"],
        "evaluated_at": document["evaluated_at"],
        "policy_sha256": policy["sha256"],
        "source_cases_sha256": document["sha256"],
        "dataset_manifest_hashes": {
            dataset: document["dataset_manifests"][dataset]["sha256"] for dataset in DATASETS
        },
        "comparisons": comparisons,
        "winner": passing[0]["challenger"] if passing else None,
        "result": "pass" if passing else "fail",
        "authority": "qwen_reviewer_role_benchmark_only_no_mask_gold_or_block_clearance_authority",
    }
    report["sha256"] = canonical_sha256(report)
    _schema(report, "qwen_challenger_benchmark_report")
    return report


def verify_report(
    report: Mapping[str, Any],
    document: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    root: Path = ROOT,
    artifact_root: Path | None = None,
    require_pass: bool = True,
) -> None:
    _schema(report, "qwen_challenger_benchmark_report")
    expected = build_report(document, policy=policy, root=root, artifact_root=artifact_root)
    if report != expected:
        raise QwenBenchmarkError("Qwen benchmark report differs from exact recomputation")
    if require_pass and report["result"] != "pass":
        raise QwenBenchmarkError("Qwen benchmark has no promotion-eligible measured winner")


__all__ = [
    "CHALLENGERS",
    "DATASETS",
    "HIGH_RISK_CONTEXTS",
    "POLICY_SHA256",
    "PROVIDERS",
    "QwenBenchmarkError",
    "build_report",
    "canonical_sha256",
    "load_policy",
    "validate_cases",
    "validate_policy",
    "verify_report",
]
