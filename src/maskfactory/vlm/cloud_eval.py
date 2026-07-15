"""Frozen human-truth evaluation for optional cloud teachers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class CloudTeacherEvalError(RuntimeError):
    """The teacher benchmark is invalid or cannot support a decision."""


@dataclass(frozen=True)
class CloudTeacherEvalReport:
    provider: str
    model: str
    corpus_sha256: str
    case_count: int
    serious_defect_recall: float
    overall_defect_recall: float
    precision: float
    false_pass_rate: float
    local_defect_recall: float
    incremental_recall_over_local: float
    correction_usefulness: float
    total_cost_usd: float
    cost_per_useful_correction_usd: float | None
    passed: bool
    failures: tuple[str, ...]


_CASE_KEYS = {
    "case_id",
    "image_id",
    "label",
    "severity",
    "human_verdict",
    "local_verdict",
    "teacher_verdict",
    "correction_useful",
    "cost_usd",
}


def evaluate_cloud_teacher_corpus(
    corpus_path: Path,
    *,
    thresholds: dict[str, Any],
) -> CloudTeacherEvalReport:
    """Score one provider against a frozen, image-disjoint human-truth corpus."""
    raw = Path(corpus_path).read_bytes()
    document = json.loads(raw)
    required = {"schema_version", "frozen", "provider", "model", "cases"}
    if not isinstance(document, dict) or set(document) != required:
        raise CloudTeacherEvalError(f"benchmark requires exactly {sorted(required)}")
    if document["schema_version"] != "1.0.0" or document["frozen"] is not True:
        raise CloudTeacherEvalError("benchmark must be schema 1.0.0 and frozen")
    cases = document["cases"]
    if not isinstance(cases, list) or not cases:
        raise CloudTeacherEvalError("benchmark has no cases")
    if len({case.get("case_id") for case in cases}) != len(cases):
        raise CloudTeacherEvalError("benchmark case IDs must be unique")
    for case in cases:
        _validate_case(case)

    defects = [case for case in cases if case["human_verdict"] == "fail"]
    serious = [case for case in defects if case["severity"] == "serious"]
    teacher_fail = [case for case in cases if case["teacher_verdict"] == "fail"]
    true_positive = [case for case in defects if case["teacher_verdict"] == "fail"]
    local_true_positive = [case for case in defects if case["local_verdict"] == "fail"]
    false_pass = [case for case in defects if case["teacher_verdict"] == "pass"]
    useful = [case for case in true_positive if case["correction_useful"] is True]
    correction_scored = [case for case in true_positive if case["correction_useful"] is not None]
    total_cost = sum(float(case["cost_usd"]) for case in cases)

    serious_recall = _ratio(
        len([case for case in serious if case["teacher_verdict"] == "fail"]), len(serious)
    )
    recall = _ratio(len(true_positive), len(defects))
    precision = _ratio(len(true_positive), len(teacher_fail))
    false_pass_rate = _ratio(len(false_pass), len(defects))
    local_recall = _ratio(len(local_true_positive), len(defects))
    incremental = recall - local_recall
    usefulness = _ratio(len(useful), len(correction_scored))
    cost_per_useful = total_cost / len(useful) if useful else None

    failures: list[str] = []
    _minimum(failures, "case_count", len(cases), int(thresholds["minimum_cases"]))
    _minimum(
        failures,
        "serious_defect_recall",
        serious_recall,
        float(thresholds["minimum_serious_defect_recall"]),
    )
    _minimum(
        failures,
        "overall_defect_recall",
        recall,
        float(thresholds["minimum_overall_defect_recall"]),
    )
    _minimum(failures, "precision", precision, float(thresholds["minimum_precision"]))
    _maximum(
        failures,
        "false_pass_rate",
        false_pass_rate,
        float(thresholds["maximum_false_pass_rate"]),
    )
    _minimum(
        failures,
        "incremental_recall_over_local",
        incremental,
        float(thresholds["minimum_incremental_recall_over_local"]),
    )
    _minimum(
        failures,
        "correction_usefulness",
        usefulness,
        float(thresholds["minimum_correction_usefulness"]),
    )
    if cost_per_useful is None:
        failures.append("cost_per_useful_correction_usd is undefined: no useful corrections")
    else:
        _maximum(
            failures,
            "cost_per_useful_correction_usd",
            cost_per_useful,
            float(thresholds["maximum_cost_per_useful_correction_usd"]),
        )
    if thresholds["require_frozen_human_truth"] is not True:
        raise CloudTeacherEvalError("evaluation must require frozen human truth")
    if thresholds["promotion_grants_mask_authority"] is not False:
        raise CloudTeacherEvalError("teacher evaluation may not grant mask authority")

    return CloudTeacherEvalReport(
        provider=str(document["provider"]),
        model=str(document["model"]),
        corpus_sha256=hashlib.sha256(raw).hexdigest(),
        case_count=len(cases),
        serious_defect_recall=serious_recall,
        overall_defect_recall=recall,
        precision=precision,
        false_pass_rate=false_pass_rate,
        local_defect_recall=local_recall,
        incremental_recall_over_local=incremental,
        correction_usefulness=usefulness,
        total_cost_usd=round(total_cost, 6),
        cost_per_useful_correction_usd=(
            round(cost_per_useful, 6) if cost_per_useful is not None else None
        ),
        passed=not failures,
        failures=tuple(failures),
    )


def write_cloud_teacher_eval_report(report: CloudTeacherEvalReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(report), indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def _validate_case(case: Any) -> None:
    if not isinstance(case, dict) or set(case) != _CASE_KEYS:
        raise CloudTeacherEvalError(f"benchmark case requires exactly {sorted(_CASE_KEYS)}")
    if case["human_verdict"] not in {"pass", "fail"}:
        raise CloudTeacherEvalError("human_verdict must be pass or fail")
    if case["local_verdict"] not in {"pass", "fail", "uncertain"}:
        raise CloudTeacherEvalError("local_verdict is invalid")
    if case["teacher_verdict"] not in {"pass", "fail", "uncertain"}:
        raise CloudTeacherEvalError("teacher_verdict is invalid")
    if case["severity"] not in {"none", "minor", "serious"}:
        raise CloudTeacherEvalError("severity is invalid")
    if (case["human_verdict"] == "pass") != (case["severity"] == "none"):
        raise CloudTeacherEvalError("human verdict and severity disagree")
    if case["correction_useful"] not in {True, False, None}:
        raise CloudTeacherEvalError("correction_useful must be true, false, or null")
    if float(case["cost_usd"]) < 0:
        raise CloudTeacherEvalError("cost_usd cannot be negative")


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _minimum(failures: list[str], name: str, actual: float, required: float) -> None:
    if actual < required:
        failures.append(f"{name} {actual:.6f} is below {required:.6f}")


def _maximum(failures: list[str], name: str, actual: float, allowed: float) -> None:
    if actual > allowed:
        failures.append(f"{name} {actual:.6f} exceeds {allowed:.6f}")
