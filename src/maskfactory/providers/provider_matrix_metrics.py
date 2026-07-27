"""Complete finite measurement compiler for the frozen provider matrix."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..training.bodypart.v2_contract import V2_CLASS_NAMES
from ..validation import ArtifactValidationError, require_valid_document
from .provider_matrix import (
    ROOT,
    ProviderMatrixError,
    canonical_sha256,
    load_policy,
    validate_manifest,
    validate_policy,
)

ARTIFACT_KEYS = (
    "determinism_outputs",
    "metric_observations",
    "prediction_manifest",
    "runtime_log",
)
COUNT_PAIRS = (
    ("small_part_eligible_count", "small_part_hit_count"),
    ("person_instance_eligible_count", "person_instance_hit_count"),
    ("part_instance_eligible_count", "part_instance_hit_count"),
    ("predicted_person_pixels", "cross_person_bleed_pixels"),
    ("side_eligible_count", "left_right_error_count"),
    ("front_back_eligible_count", "front_back_error_count"),
    ("anatomy_clothing_eligible_count", "anatomy_clothing_confusion_count"),
    ("expected_part_count", "missing_part_count"),
    ("predicted_part_count", "hallucinated_part_count"),
    ("hard_qa_eligible_count", "hard_qa_failure_count"),
    ("predicted_pixels", "correction_pixels"),
)
AGGREGATE_FIELDS = frozenset(
    {
        *(field for pair in COUNT_PAIRS for field in pair),
        "audit_case_count",
        "audit_seconds",
        "execution_attempt_count",
        "oom_count",
        "crash_count",
        "peak_vram_bytes",
        "cold_latency_ms",
        "warm_latency_ms",
        "deterministic_output_sha256",
    }
)
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class ProviderMatrixMetricsError(ValueError):
    """Matrix measurement evidence is incomplete, non-finite, or inconsistent."""


def _count(value: Any, field: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProviderMatrixMetricsError(f"{field} must be an integer")
    if value < (1 if positive else 0):
        qualifier = "positive" if positive else "nonnegative"
        raise ProviderMatrixMetricsError(f"{field} must be {qualifier}")
    return value


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderMatrixMetricsError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ProviderMatrixMetricsError(f"{field} must be finite and nonnegative")
    return number


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderMatrixMetricsError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ProviderMatrixMetricsError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC)


def _cell_sequence(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [*manifest["screening_cells"], *manifest["enrichment_cells"]]


def _validate_label_rows(
    cell_id: str, rows: Sequence[Mapping[str, Any]]
) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        name = row["name"]
        if name not in V2_CLASS_NAMES or name in indexed:
            raise ProviderMatrixMetricsError(f"{cell_id} label vocabulary is invalid")
        truth = _count(row["truth_pixels"], f"{cell_id}.{name}.truth_pixels", positive=True)
        predicted = _count(row["predicted_pixels"], f"{cell_id}.{name}.predicted_pixels")
        intersection = _count(row["intersection_pixels"], f"{cell_id}.{name}.intersection_pixels")
        union = _count(row["union_pixels"], f"{cell_id}.{name}.union_pixels", positive=True)
        if intersection > min(truth, predicted):
            raise ProviderMatrixMetricsError(f"{cell_id}.{name} intersection exceeds inputs")
        if union != truth + predicted - intersection:
            raise ProviderMatrixMetricsError(f"{cell_id}.{name} union identity failed")
        for field in ("boundary_tp", "boundary_fp", "boundary_fn"):
            _count(row[field], f"{cell_id}.{name}.{field}")
        indexed[name] = row
    if set(indexed) != set(V2_CLASS_NAMES):
        raise ProviderMatrixMetricsError(f"{cell_id} label coverage is incomplete")
    return indexed


def _validate_aggregate_counts(cell_id: str, counts: Mapping[str, Any]) -> None:
    if set(counts) != AGGREGATE_FIELDS:
        raise ProviderMatrixMetricsError(f"{cell_id} aggregate count contract is incomplete")
    for denominator, numerator in COUNT_PAIRS:
        denominator_value = _count(counts[denominator], f"{cell_id}.{denominator}", positive=True)
        numerator_value = _count(counts[numerator], f"{cell_id}.{numerator}")
        if numerator_value > denominator_value:
            raise ProviderMatrixMetricsError(f"{cell_id}.{numerator} exceeds explicit denominator")
    attempts = _count(
        counts["execution_attempt_count"],
        f"{cell_id}.execution_attempt_count",
        positive=True,
    )
    oom = _count(counts["oom_count"], f"{cell_id}.oom_count")
    crashes = _count(counts["crash_count"], f"{cell_id}.crash_count")
    if oom + crashes > attempts:
        raise ProviderMatrixMetricsError(f"{cell_id} runtime failures exceed attempts")
    audit_cases = _count(counts["audit_case_count"], f"{cell_id}.audit_case_count", positive=True)
    _finite(counts["audit_seconds"], f"{cell_id}.audit_seconds")
    if audit_cases <= 0:
        raise ProviderMatrixMetricsError(f"{cell_id} audit denominator is invalid")
    _count(counts["peak_vram_bytes"], f"{cell_id}.peak_vram_bytes")
    _finite(counts["cold_latency_ms"], f"{cell_id}.cold_latency_ms")
    _finite(counts["warm_latency_ms"], f"{cell_id}.warm_latency_ms")
    repeats = counts["deterministic_output_sha256"]
    if len(repeats) != 2 or any(
        not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None for value in repeats
    ):
        raise ProviderMatrixMetricsError(f"{cell_id} requires exactly two repeat hashes")


def _label_metrics(
    rows: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, float], dict[str, float]]:
    iou: dict[str, float] = {}
    boundary: dict[str, float] = {}
    for name in V2_CLASS_NAMES:
        row = rows[name]
        iou[name] = _rate(row["intersection_pixels"], row["union_pixels"])
        denominator = 2 * row["boundary_tp"] + row["boundary_fp"] + row["boundary_fn"]
        boundary[name] = _rate(2 * row["boundary_tp"], denominator)
    return iou, boundary


def _compile_metrics(
    rows: Mapping[str, Mapping[str, Any]], counts: Mapping[str, Any]
) -> dict[str, Any]:
    per_label_iou, boundary_f = _label_metrics(rows)
    attempts = counts["execution_attempt_count"]
    repeats = counts["deterministic_output_sha256"]
    return {
        "per_label_iou": per_label_iou,
        "boundary_f_2px": boundary_f,
        "small_part_recall": _rate(
            counts["small_part_hit_count"], counts["small_part_eligible_count"]
        ),
        "person_instance_recall": _rate(
            counts["person_instance_hit_count"], counts["person_instance_eligible_count"]
        ),
        "part_instance_recall": _rate(
            counts["part_instance_hit_count"], counts["part_instance_eligible_count"]
        ),
        "cross_person_bleed_rate": _rate(
            counts["cross_person_bleed_pixels"], counts["predicted_person_pixels"]
        ),
        "left_right_error_rate": _rate(
            counts["left_right_error_count"], counts["side_eligible_count"]
        ),
        "front_back_error_rate": _rate(
            counts["front_back_error_count"], counts["front_back_eligible_count"]
        ),
        "anatomy_clothing_confusion_rate": _rate(
            counts["anatomy_clothing_confusion_count"],
            counts["anatomy_clothing_eligible_count"],
        ),
        "missing_part_rate": _rate(counts["missing_part_count"], counts["expected_part_count"]),
        "hallucinated_part_rate": _rate(
            counts["hallucinated_part_count"], counts["predicted_part_count"]
        ),
        "hard_qa_failure_rate": _rate(
            counts["hard_qa_failure_count"], counts["hard_qa_eligible_count"]
        ),
        "correction_pixels_per_100k": 100000
        * _rate(counts["correction_pixels"], counts["predicted_pixels"]),
        "audit_seconds_per_case": counts["audit_seconds"] / counts["audit_case_count"],
        "peak_vram_bytes": counts["peak_vram_bytes"],
        "cold_latency_ms": float(counts["cold_latency_ms"]),
        "warm_latency_ms": float(counts["warm_latency_ms"]),
        "oom_crash_rate": _rate(counts["oom_count"] + counts["crash_count"], attempts),
        "deterministic_repeatability": 1.0 if len(set(repeats)) == 1 else 0.0,
    }


def _validate_cell(evidence: Mapping[str, Any], expected_cell: Mapping[str, Any]) -> dict[str, Any]:
    cell_id = expected_cell["cell_id"]
    if evidence["cell_id"] != cell_id:
        raise ProviderMatrixMetricsError("matrix result cell ordering or identity drifted")
    if evidence["cell_identity_sha256"] != canonical_sha256(expected_cell):
        raise ProviderMatrixMetricsError(f"{cell_id} matrix-cell identity hash mismatch")
    artifacts = evidence["artifact_hashes"]
    if tuple(sorted(artifacts)) != ARTIFACT_KEYS:
        raise ProviderMatrixMetricsError(f"{cell_id} metric artifact set is incomplete")
    observations = {
        "label_observations": evidence["label_observations"],
        "aggregate_counts": evidence["aggregate_counts"],
        "artifact_hashes": artifacts,
    }
    if evidence["observations_sha256"] != canonical_sha256(observations):
        raise ProviderMatrixMetricsError(f"{cell_id} observations hash mismatch")
    rows = _validate_label_rows(cell_id, evidence["label_observations"])
    _validate_aggregate_counts(cell_id, evidence["aggregate_counts"])
    return {
        "cell_id": cell_id,
        "cell_identity_sha256": evidence["cell_identity_sha256"],
        "observations_sha256": evidence["observations_sha256"],
        "artifact_hashes": artifacts,
        "metrics": _compile_metrics(rows, evidence["aggregate_counts"]),
    }


def build_report(
    observations_document: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    policy_document = dict(policy) if policy is not None else load_policy(root=root)
    try:
        validate_policy(policy_document, root=root)
        validate_manifest(manifest, policy=policy_document, root=root)
    except ProviderMatrixError as exc:
        raise ProviderMatrixMetricsError(str(exc)) from exc
    try:
        require_valid_document(observations_document, "provider_benchmark_matrix_observations")
    except ArtifactValidationError as exc:
        raise ProviderMatrixMetricsError(str(exc)) from exc
    payload = {key: value for key, value in observations_document.items() if key != "sha256"}
    if observations_document["sha256"] != canonical_sha256(payload):
        raise ProviderMatrixMetricsError("provider matrix observations hash mismatch")
    if observations_document["policy_sha256"] != policy_document["sha256"]:
        raise ProviderMatrixMetricsError("provider matrix observations policy hash mismatch")
    if observations_document["manifest_sha256"] != manifest["sha256"]:
        raise ProviderMatrixMetricsError("provider matrix observations manifest hash mismatch")
    if _timestamp(observations_document["results_opened_at"], "results_opened_at") <= _timestamp(
        manifest["opened_at"], "manifest.opened_at"
    ):
        raise ProviderMatrixMetricsError("provider matrix results predate the sealed manifest")
    expected_cells = _cell_sequence(manifest)
    evidence_cells = observations_document["cells"]
    if len(evidence_cells) != len(expected_cells):
        raise ProviderMatrixMetricsError("provider matrix result cell coverage is incomplete")
    compiled = [
        _validate_cell(evidence, expected)
        for evidence, expected in zip(evidence_cells, expected_cells, strict=True)
    ]
    required_metrics = set(policy_document["required_measurements"])
    if any(set(cell["metrics"]) != required_metrics for cell in compiled):
        raise ProviderMatrixMetricsError("provider matrix metric vocabulary drifted")
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "matrix_id": manifest["matrix_id"],
        "evaluated_at": observations_document["results_opened_at"],
        "policy_sha256": policy_document["sha256"],
        "source_manifest_sha256": manifest["sha256"],
        "source_observations_sha256": observations_document["sha256"],
        "shared_identity_sha256": canonical_sha256(manifest["shared_identity"]),
        "cell_count": len(compiled),
        "cells": compiled,
        "result": "complete_finite_measurements",
        "authority": "measurement_evidence_only_no_winner_promotion_serving_mask_or_gold_authority",
    }
    report["sha256"] = canonical_sha256(report)
    require_valid_document(report, "provider_benchmark_matrix_report")
    return report


def verify_report(
    report: Mapping[str, Any],
    observations_document: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    root: Path = ROOT,
) -> None:
    try:
        require_valid_document(report, "provider_benchmark_matrix_report")
    except ArtifactValidationError as exc:
        raise ProviderMatrixMetricsError(str(exc)) from exc
    expected = build_report(observations_document, manifest, policy=policy, root=root)
    if dict(report) != expected:
        raise ProviderMatrixMetricsError("provider matrix report recomputation mismatch")


__all__ = [
    "ARTIFACT_KEYS",
    "ProviderMatrixMetricsError",
    "build_report",
    "verify_report",
]
