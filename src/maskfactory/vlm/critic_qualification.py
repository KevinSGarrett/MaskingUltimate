"""Measured, fail-closed qualification for self-hosted visual-critic roles."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .calibration_corpus import validate_calibration_corpus
from .critic_catalog import MODEL_ROLES, canonical_sha256, validate_catalog
from .live_calibration import CHECK_KEYS, CHECK_VALUES, EVIDENCE_BOARD_LAYOUT

SHA256 = re.compile(r"^[a-f0-9]{64}$")
VERDICTS = frozenset({"pass", "defect", "abstain"})
SERIOUS_DEFECTS = frozenset(
    {"anatomy", "ownership", "protected_region", "transform", "wrong_label", "wrong_side"}
)
EVIDENCE_KEYS = frozenset(
    {
        "schema_version",
        "role_id",
        "model_id",
        "family_id",
        "revision",
        "quantization",
        "artifact_tree_sha256",
        "prompt_sha256",
        "runtime_sha256",
        "corpus_sha256",
        "hardware",
        "predictions",
    }
)
HARDWARE_KEYS = frozenset({"gpu_name", "gpu_count", "vram_bytes"})
PREDICTION_KEYS = frozenset(
    {
        "case_id",
        "target_contract_sha256",
        "panel_set_sha256",
        "verdict",
        "defect_type",
        "cited_context_tags",
        "checks",
        "cited_evidence_panels",
        "schema_valid",
        "latency_ms",
        "peak_vram_bytes",
        "response_sha256",
        "deterministic_replay",
    }
)

# These thresholds are code-versioned and hashed into every report before a run.
# Small frozen corpora therefore require perfect serious-defect and valid-mask behavior.
ROLE_THRESHOLDS: dict[str, dict[str, float]] = {
    "fast_screener": {
        "minimum_valid_mask_pass_rate": 0.90,
        "minimum_defect_recall": 0.90,
        "minimum_precision": 0.80,
        "maximum_serious_false_pass_rate": 0.0,
        "maximum_abstention_rate": 0.10,
        "minimum_schema_compliance_rate": 1.0,
        "minimum_context_binding_rate": 1.0,
        "minimum_check_binding_rate": 1.0,
        "minimum_evidence_localization_rate": 1.0,
        "minimum_ownership_accuracy": 1.0,
        "minimum_label_accuracy": 1.0,
        "minimum_deterministic_replay_rate": 1.0,
        "maximum_p95_latency_ms": 3000.0,
        "maximum_peak_vram_fraction": 0.98,
    },
    "primary_visual_critic": {
        "minimum_valid_mask_pass_rate": 0.90,
        "minimum_defect_recall": 0.95,
        "minimum_precision": 0.80,
        "maximum_serious_false_pass_rate": 0.0,
        "maximum_abstention_rate": 0.05,
        "minimum_schema_compliance_rate": 1.0,
        "minimum_context_binding_rate": 1.0,
        "minimum_check_binding_rate": 1.0,
        "minimum_evidence_localization_rate": 1.0,
        "minimum_ownership_accuracy": 1.0,
        "minimum_label_accuracy": 1.0,
        "minimum_deterministic_replay_rate": 1.0,
        "maximum_p95_latency_ms": 6000.0,
        "maximum_peak_vram_fraction": 0.98,
    },
    "independent_juror": {
        "minimum_valid_mask_pass_rate": 0.90,
        "minimum_defect_recall": 0.95,
        "minimum_precision": 0.80,
        "maximum_serious_false_pass_rate": 0.0,
        "maximum_abstention_rate": 0.05,
        "minimum_schema_compliance_rate": 1.0,
        "minimum_context_binding_rate": 1.0,
        "minimum_check_binding_rate": 1.0,
        "minimum_evidence_localization_rate": 1.0,
        "minimum_ownership_accuracy": 1.0,
        "minimum_label_accuracy": 1.0,
        "minimum_deterministic_replay_rate": 1.0,
        "maximum_p95_latency_ms": 12000.0,
        "maximum_peak_vram_fraction": 0.98,
    },
    "senior_arbiter": {
        "minimum_valid_mask_pass_rate": 0.90,
        "minimum_defect_recall": 0.95,
        "minimum_precision": 0.80,
        "maximum_serious_false_pass_rate": 0.0,
        "maximum_abstention_rate": 0.10,
        "minimum_schema_compliance_rate": 1.0,
        "minimum_context_binding_rate": 1.0,
        "minimum_check_binding_rate": 1.0,
        "minimum_evidence_localization_rate": 1.0,
        "minimum_ownership_accuracy": 1.0,
        "minimum_label_accuracy": 1.0,
        "minimum_deterministic_replay_rate": 1.0,
        "maximum_p95_latency_ms": 20000.0,
        "maximum_peak_vram_fraction": 0.98,
    },
}


class CriticQualificationError(ValueError):
    """Qualification evidence is malformed, unbound, or names an invalid role/model."""


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise CriticQualificationError(f"{field} must be a SHA-256")
    return value


def _finite_nonnegative(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CriticQualificationError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise CriticQualificationError(f"{field} must be finite and nonnegative")
    return result


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        raise CriticQualificationError("qualification corpus has an empty required class")
    return numerator / denominator


def _precision(true_positive: int, predicted_positive: int) -> float:
    return 0.0 if predicted_positive == 0 else true_positive / predicted_positive


def _nearest_rank_p95(values: Sequence[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _threshold_failures(metrics: Mapping[str, float], thresholds: Mapping[str, float]) -> list[str]:
    failures: list[str] = []
    for metric in (
        "valid_mask_pass_rate",
        "defect_recall",
        "precision",
        "schema_compliance_rate",
        "context_binding_rate",
        "check_binding_rate",
        "evidence_localization_rate",
        "ownership_accuracy",
        "label_accuracy",
        "deterministic_replay_rate",
    ):
        if metrics[metric] < thresholds[f"minimum_{metric}"]:
            failures.append(f"{metric}_below_minimum")
    for metric in ("serious_false_pass_rate", "abstention_rate"):
        if metrics[metric] > thresholds[f"maximum_{metric}"]:
            failures.append(f"{metric}_above_maximum")
    if metrics["p95_latency_ms"] > thresholds["maximum_p95_latency_ms"]:
        failures.append("p95_latency_ms_above_maximum")
    # Peak VRAM is retained as telemetry only; it cannot fail role qualification.
    return failures


def evaluate_critic_qualification(
    evidence: Mapping[str, Any],
    corpus: Mapping[str, Any],
    catalog: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a hash-bound role report; measured gate failures are not exceptions."""

    validate_calibration_corpus(corpus)
    validate_catalog(catalog)
    if set(evidence) != EVIDENCE_KEYS or evidence.get("schema_version") != "1.0.0":
        raise CriticQualificationError("qualification evidence fields or schema are invalid")
    role_id = str(evidence["role_id"])
    if role_id not in MODEL_ROLES:
        raise CriticQualificationError("qualification role is unknown")
    thresholds = ROLE_THRESHOLDS[role_id]
    if evidence["corpus_sha256"] != corpus["corpus_sha256"]:
        raise CriticQualificationError("qualification corpus hash drifted")
    for field in ("artifact_tree_sha256", "prompt_sha256", "runtime_sha256"):
        _sha256(evidence[field], field)

    models = {str(model["model_id"]): model for model in catalog["models"]}
    model = models.get(str(evidence["model_id"]))
    if model is None or role_id not in model["candidate_roles"]:
        raise CriticQualificationError("qualification model is not a candidate for this role")
    for field in ("family_id", "revision", "quantization"):
        if evidence[field] != model[field]:
            raise CriticQualificationError(f"qualification {field} differs from catalog")
    if not model["hardware"]["single_gpu_48gb_feasible"]:
        raise CriticQualificationError("qualification model is infeasible on current hardware")

    hardware = evidence["hardware"]
    if not isinstance(hardware, Mapping) or set(hardware) != HARDWARE_KEYS:
        raise CriticQualificationError("qualification hardware fields are invalid")
    expected_hardware = catalog["current_hardware"]
    if (
        hardware["gpu_name"] != expected_hardware["gpu_name"]
        or hardware["gpu_count"] != expected_hardware["gpu_count"]
    ):
        raise CriticQualificationError("qualification hardware differs from catalog")

    cases = {str(case["case_id"]): case for case in corpus["cases"]}
    predictions = evidence["predictions"]
    if not isinstance(predictions, Sequence) or isinstance(predictions, (str, bytes)):
        raise CriticQualificationError("qualification predictions must be an array")
    observed: dict[str, Mapping[str, Any]] = {}
    latencies: list[float] = []
    peak_vram: list[float] = []
    context_bound = 0
    checks_bound = 0
    evidence_localized = 0
    schema_valid = 0
    deterministic = 0
    for prediction in predictions:
        if not isinstance(prediction, Mapping) or set(prediction) != PREDICTION_KEYS:
            raise CriticQualificationError("qualification prediction fields are invalid")
        case_id = str(prediction["case_id"])
        case = cases.get(case_id)
        if case is None or case_id in observed:
            raise CriticQualificationError("qualification prediction case is unknown or duplicated")
        observed[case_id] = prediction
        if prediction["target_contract_sha256"] != case["target_contract"]["contract_sha256"]:
            raise CriticQualificationError(f"{case_id} target contract hash drifted")
        if prediction["panel_set_sha256"] != case["panel_set_sha256"]:
            raise CriticQualificationError(f"{case_id} panel-set hash drifted")
        verdict = prediction["verdict"]
        defect_type = prediction["defect_type"]
        if verdict not in VERDICTS:
            raise CriticQualificationError(f"{case_id} verdict is invalid")
        if verdict == "defect" and defect_type not in corpus["defect_taxonomy"]:
            raise CriticQualificationError(f"{case_id} defect type is invalid")
        if verdict != "defect" and defect_type is not None:
            raise CriticQualificationError(f"{case_id} non-defect verdict carries a defect type")
        cited = prediction["cited_context_tags"]
        if (
            not isinstance(cited, Sequence)
            or isinstance(cited, (str, bytes))
            or len(set(cited)) != len(cited)
        ):
            raise CriticQualificationError(f"{case_id} cited contexts are invalid")
        if cited and set(cited) <= set(case["context_tags"]):
            context_bound += 1
        checks = prediction["checks"]
        if (
            isinstance(checks, Mapping)
            and set(checks) == set(CHECK_KEYS)
            and all(status in CHECK_VALUES for status in checks.values())
            and (verdict != "pass" or set(checks.values()) == {"pass"})
            and (verdict != "defect" or "defect" in checks.values())
            and (verdict != "abstain" or "uncertain" in checks.values())
        ):
            checks_bound += 1
        cited_panels = prediction["cited_evidence_panels"]
        if (
            isinstance(cited_panels, Sequence)
            and not isinstance(cited_panels, (str, bytes))
            and len(cited_panels) >= 2
            and len(set(cited_panels)) == len(cited_panels)
            and set(cited_panels) <= set(EVIDENCE_BOARD_LAYOUT)
        ):
            evidence_localized += 1
        if prediction["schema_valid"] is True:
            schema_valid += 1
        if prediction["deterministic_replay"] is True:
            deterministic += 1
        _sha256(prediction["response_sha256"], f"{case_id}.response_sha256")
        latencies.append(_finite_nonnegative(prediction["latency_ms"], "latency_ms"))
        peak_vram.append(_finite_nonnegative(prediction["peak_vram_bytes"], "peak_vram_bytes"))
    if set(observed) != set(cases):
        raise CriticQualificationError("qualification predictions do not cover the corpus exactly")

    valid = [case for case in cases.values() if case["expected_outcome"] == "valid_mask"]
    defects = [case for case in cases.values() if case["expected_outcome"] == "known_defect"]
    serious = [case for case in defects if case["defect_type"] in SERIOUS_DEFECTS]
    ownership_cases = [case for case in defects if case["defect_type"] == "ownership"]
    label_cases = [case for case in defects if case["defect_type"] in {"wrong_label", "wrong_side"}]
    predicted_defects = [row for row in predictions if row["verdict"] == "defect"]
    true_defect_calls = sum(observed[case["case_id"]]["verdict"] == "defect" for case in defects)
    metrics = {
        "valid_mask_pass_rate": _rate(
            sum(observed[case["case_id"]]["verdict"] == "pass" for case in valid), len(valid)
        ),
        "defect_recall": _rate(
            sum(observed[case["case_id"]]["verdict"] == "defect" for case in defects),
            len(defects),
        ),
        "precision": _precision(true_defect_calls, len(predicted_defects)),
        "serious_false_pass_rate": _rate(
            sum(observed[case["case_id"]]["verdict"] == "pass" for case in serious),
            len(serious),
        ),
        "abstention_rate": _rate(
            sum(row["verdict"] == "abstain" for row in predictions), len(predictions)
        ),
        "schema_compliance_rate": _rate(schema_valid, len(predictions)),
        "context_binding_rate": _rate(context_bound, len(predictions)),
        "check_binding_rate": _rate(checks_bound, len(predictions)),
        "evidence_localization_rate": _rate(evidence_localized, len(predictions)),
        "ownership_accuracy": _rate(
            sum(
                observed[case["case_id"]]["verdict"] == "defect"
                and observed[case["case_id"]]["defect_type"] == case["defect_type"]
                for case in ownership_cases
            ),
            len(ownership_cases),
        ),
        "label_accuracy": _rate(
            sum(
                observed[case["case_id"]]["verdict"] == "defect"
                and observed[case["case_id"]]["defect_type"] == case["defect_type"]
                for case in label_cases
            ),
            len(label_cases),
        ),
        "deterministic_replay_rate": _rate(deterministic, len(predictions)),
        "p95_latency_ms": _nearest_rank_p95(latencies),
        "peak_vram_fraction": max(peak_vram) / float(hardware["vram_bytes"]),
    }
    failures = _threshold_failures(metrics, thresholds)
    per_defect = Counter(
        case["defect_type"]
        for case in defects
        if observed[case["case_id"]]["verdict"] == "defect"
        and observed[case["case_id"]]["defect_type"] == case["defect_type"]
    )
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "status": "pass" if not failures else "fail",
        "authority_claimed": False,
        "role_id": role_id,
        "model_id": evidence["model_id"],
        "family_id": evidence["family_id"],
        "catalog_sha256": catalog["sha256"],
        "corpus_sha256": corpus["corpus_sha256"],
        "evidence_sha256": canonical_sha256(evidence),
        "thresholds": thresholds,
        "thresholds_sha256": canonical_sha256({"role_id": role_id, "thresholds": thresholds}),
        "metrics": metrics,
        "per_defect_exact_hits": dict(sorted(per_defect.items())),
        "failures": failures,
    }
    report["report_sha256"] = canonical_sha256(report)
    return report
