"""Frozen BiRefNet/ViTMatte silhouette, hair-edge, and matting benchmark."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..validation import ArtifactValidationError, require_valid_document

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY_PATH = (
    ROOT / "qa" / "governance" / "benchmark_matrices" / "silhouette_variant_benchmark_v1.json"
)
POLICY_SHA256 = "07bfddf8897826af6efae11ad4858d1a00492aab0ac6e0403bce3730b454e22d"
CONTEXTS = (
    "hair_boundaries",
    "multi_person_overlap",
    "occlusion_contact",
    "small_parts",
    "truncation",
)
ROLE_MATRIX = {
    "silhouette": {
        "baseline": "birefnet_general",
        "challengers": (
            "birefnet_dynamic",
            "birefnet_hr",
            "birefnet_hr_matting",
        ),
        "labels": ("person_silhouette",),
        "requires_alpha": False,
    },
    "hair_edge": {
        "baseline": "birefnet_general",
        "challengers": (
            "birefnet_dynamic",
            "birefnet_hr",
            "birefnet_hr_matting",
        ),
        "labels": ("hair", "head_face"),
        "requires_alpha": False,
    },
    "matting": {
        "baseline": "vitmatte_small",
        "challengers": ("birefnet_dynamic", "birefnet_hr_matting"),
        "labels": ("hair", "lace_or_sheer"),
        "requires_alpha": True,
    },
}
PROVIDER_CAPABILITIES = {
    "birefnet_general": ("silhouette", "hair_edge"),
    "vitmatte_small": ("matting",),
    "birefnet_dynamic": ("silhouette", "hair_edge", "matting"),
    "birefnet_hr": ("silhouette", "hair_edge"),
    "birefnet_hr_matting": ("silhouette", "hair_edge", "matting"),
}
SOURCE_FILES = (
    "configs/pipeline.yaml",
    "env/birefnet_variants.lock.json",
    "models/model_registry.json",
    "qa/governance/benchmark_matrices/specialist_margins_v1.json",
    "src/maskfactory/lanes/hair.py",
    "src/maskfactory/providers/birefnet_variants.py",
)


class SilhouetteBenchmarkError(ValueError):
    """The frozen silhouette policy, observations, or report are invalid."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SilhouetteBenchmarkError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise SilhouetteBenchmarkError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC)


def _count(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SilhouetteBenchmarkError(f"{field} must be a nonnegative integer")
    return value


def _finite(value: Any, field: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SilhouetteBenchmarkError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise SilhouetteBenchmarkError(f"{field} must be finite and >= {minimum}")
    return result


def _rate(numerator: float, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def validate_policy(
    document: Mapping[str, Any],
    *,
    root: Path = ROOT,
    expected_sha256: str | None = POLICY_SHA256,
) -> None:
    """Validate the pre-result policy, locked hash, and every governing source byte."""
    try:
        require_valid_document(document, "silhouette_variant_benchmark_policy")
    except ArtifactValidationError as exc:
        raise SilhouetteBenchmarkError(str(exc)) from exc
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if document["sha256"] != _canonical_sha256(payload):
        raise SilhouetteBenchmarkError("silhouette benchmark policy hash mismatch")
    if expected_sha256 is not None and document["sha256"] != expected_sha256:
        raise SilhouetteBenchmarkError("silhouette benchmark policy differs from locked hash")
    _timestamp(document["frozen_at"], "frozen_at")
    if document["eligible_truth"] != {
        "partition": "holdout",
        "tier": "human_anchor_gold",
    }:
        raise SilhouetteBenchmarkError("only human-anchor holdout truth is eligible")
    if tuple(document["required_contexts"]) != CONTEXTS:
        raise SilhouetteBenchmarkError("silhouette benchmark contexts drifted")
    expected_roles = {
        role: {
            "baseline": spec["baseline"],
            "challengers": list(spec["challengers"]),
            "labels": list(spec["labels"]),
            "requires_alpha": spec["requires_alpha"],
        }
        for role, spec in ROLE_MATRIX.items()
    }
    if document["roles"] != expected_roles:
        raise SilhouetteBenchmarkError("silhouette benchmark role matrix drifted")
    if set(document["providers"]) != set(PROVIDER_CAPABILITIES):
        raise SilhouetteBenchmarkError("silhouette benchmark provider set drifted")
    for provider, capabilities in PROVIDER_CAPABILITIES.items():
        if document["providers"][provider]["capabilities"] != list(capabilities):
            raise SilhouetteBenchmarkError(f"{provider} capability matrix drifted")
    if document["specialist_margin_sha256"] != (
        "605f79e0d4f8354a7a4d445a0a5725af829cd78b85e2e36f91b065576553a739"
    ):
        raise SilhouetteBenchmarkError("specialist noninferiority binding drifted")
    if document["pass_requirements"] != {
        "max_alpha_mse_increase": 0.0,
        "max_boundary_f_2px_drop": 0.015,
        "max_foreground_iou_drop": 0.01,
        "max_foreground_leakage_rate_increase": 0.005,
        "max_oom_or_crash_count": 0,
        "max_peak_vram_bytes": 8589410304,
        "require_deterministic_repeats": 2,
    }:
        raise SilhouetteBenchmarkError("silhouette benchmark pass requirements drifted")
    if set(document["source_hashes"]) != set(SOURCE_FILES):
        raise SilhouetteBenchmarkError("silhouette benchmark source hash set is incomplete")
    for relative in SOURCE_FILES:
        source = Path(root) / relative
        if not source.is_file() or _file_sha256(source) != document["source_hashes"][relative]:
            raise SilhouetteBenchmarkError(f"governing source hash drift: {relative}")


def load_policy(path: Path = DEFAULT_POLICY_PATH, *, root: Path = ROOT) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SilhouetteBenchmarkError("silhouette benchmark policy is not an object")
    validate_policy(document, root=root)
    return document


def _validate_observation(observation: Mapping[str, Any], provider: str) -> tuple[str, str, str]:
    role = observation["role"]
    context = observation["context"]
    label = observation["label"]
    if role not in PROVIDER_CAPABILITIES[provider]:
        raise SilhouetteBenchmarkError(f"{provider} observation uses unsupported role")
    if context not in CONTEXTS or label not in ROLE_MATRIX[role]["labels"]:
        raise SilhouetteBenchmarkError(f"{provider} observation vocabulary is invalid")
    counts = {
        field: _count(observation[field], field)
        for field in (
            "case_count",
            "total_pixels",
            "predicted_foreground_pixels",
            "truth_foreground_pixels",
            "intersection_pixels",
            "truth_background_pixels",
            "false_positive_background_pixels",
            "boundary_true_positive",
            "boundary_false_positive",
            "boundary_false_negative",
            "correction_pixels",
            "alpha_reference_pixels",
        )
    }
    if counts["case_count"] < 1 or counts["total_pixels"] < 1:
        raise SilhouetteBenchmarkError("benchmark observation denominator is empty")
    if (
        counts["truth_foreground_pixels"] + counts["truth_background_pixels"]
        != counts["total_pixels"]
    ):
        raise SilhouetteBenchmarkError("foreground/background truth pixels do not reconcile")
    if counts["intersection_pixels"] > min(
        counts["predicted_foreground_pixels"], counts["truth_foreground_pixels"]
    ):
        raise SilhouetteBenchmarkError("intersection exceeds foreground denominator")
    if counts["false_positive_background_pixels"] > counts["truth_background_pixels"]:
        raise SilhouetteBenchmarkError("leakage numerator exceeds truth background")
    if counts["correction_pixels"] > counts["total_pixels"]:
        raise SilhouetteBenchmarkError("correction pixels exceed total pixels")
    abs_error = _finite(observation["alpha_absolute_error_sum"], "alpha_absolute_error_sum")
    squared_error = _finite(observation["alpha_squared_error_sum"], "alpha_squared_error_sum")
    if ROLE_MATRIX[role]["requires_alpha"]:
        if counts["alpha_reference_pixels"] != counts["total_pixels"]:
            raise SilhouetteBenchmarkError("matting alpha denominator must equal total pixels")
        if (
            abs_error > counts["alpha_reference_pixels"]
            or squared_error > counts["alpha_reference_pixels"]
        ):
            raise SilhouetteBenchmarkError("alpha error sums exceed normalized bounds")
    elif counts["alpha_reference_pixels"] or abs_error or squared_error:
        raise SilhouetteBenchmarkError("binary role carries alpha-only measurements")
    return role, context, label


def _aggregate(
    observations: Sequence[Mapping[str, Any]], *, requires_alpha: bool
) -> dict[str, Any]:
    values = {
        field: sum(int(row[field]) for row in observations)
        for field in (
            "case_count",
            "total_pixels",
            "predicted_foreground_pixels",
            "truth_foreground_pixels",
            "intersection_pixels",
            "truth_background_pixels",
            "false_positive_background_pixels",
            "boundary_true_positive",
            "boundary_false_positive",
            "boundary_false_negative",
            "correction_pixels",
            "alpha_reference_pixels",
        )
    }
    alpha_abs = sum(float(row["alpha_absolute_error_sum"]) for row in observations)
    alpha_squared = sum(float(row["alpha_squared_error_sum"]) for row in observations)
    union = (
        values["predicted_foreground_pixels"]
        + values["truth_foreground_pixels"]
        - values["intersection_pixels"]
    )
    boundary_denominator = (
        2 * values["boundary_true_positive"]
        + values["boundary_false_positive"]
        + values["boundary_false_negative"]
    )
    return {
        **values,
        "alpha_absolute_error_sum": alpha_abs,
        "alpha_squared_error_sum": alpha_squared,
        "foreground_iou": _rate(values["intersection_pixels"], union),
        "foreground_leakage_rate": _rate(
            values["false_positive_background_pixels"], values["truth_background_pixels"]
        ),
        "boundary_f_2px": _rate(2 * values["boundary_true_positive"], boundary_denominator),
        "correction_pixels_per_100k": _rate(
            100000 * values["correction_pixels"], values["total_pixels"]
        ),
        "alpha_mae": _rate(alpha_abs, values["alpha_reference_pixels"]) if requires_alpha else None,
        "alpha_mse": (
            _rate(alpha_squared, values["alpha_reference_pixels"]) if requires_alpha else None
        ),
    }


def _validate_runtime(
    provider: str, evidence: Mapping[str, Any], policy: Mapping[str, Any]
) -> None:
    spec = policy["providers"][provider]
    if evidence["artifact_hashes"] != spec["artifact_hashes"]:
        raise SilhouetteBenchmarkError(f"{provider} artifact identity mismatch")
    if evidence["runtime_fingerprint"] != spec["runtime_fingerprint"]:
        raise SilhouetteBenchmarkError(f"{provider} runtime identity mismatch")
    if evidence["governed_resolution"] != spec["governed_resolution"]:
        raise SilhouetteBenchmarkError(f"{provider} governed resolution mismatch")
    runtime = evidence["runtime_metrics"]
    for field in ("cold_latency_ms", "warm_latency_ms", "peak_vram_bytes"):
        _finite(runtime[field], f"{provider}.{field}")
    for field in ("oom_count", "crash_count", "repeat_count"):
        _count(runtime[field], f"{provider}.{field}")
    hashes = runtime["deterministic_output_sha256"]
    if len(hashes) != runtime["repeat_count"] or len(set(hashes)) != 1:
        raise SilhouetteBenchmarkError(f"{provider} deterministic repeat evidence failed")


def _validate_provider(
    provider: str, evidence: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    _validate_runtime(provider, evidence, policy)
    mapped: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for observation in evidence["observations"]:
        key = _validate_observation(observation, provider)
        if key in mapped:
            raise SilhouetteBenchmarkError(f"duplicate {provider} role/context/label observation")
        mapped[key] = observation
    expected = {
        (role, context, label)
        for role in PROVIDER_CAPABILITIES[provider]
        for context in CONTEXTS
        for label in ROLE_MATRIX[role]["labels"]
    }
    if set(mapped) != expected:
        raise SilhouetteBenchmarkError(f"{provider} role/context/label coverage is incomplete")
    return mapped


def build_report(
    cases_document: Mapping[str, Any],
    *,
    truth_manifest_path: Path,
    policy: Mapping[str, Any] | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Recompute every binary, boundary, leakage, alpha, and runtime gate."""
    policy_document = dict(policy) if policy is not None else load_policy(root=root)
    validate_policy(policy_document, root=root)
    try:
        require_valid_document(cases_document, "silhouette_variant_benchmark_cases")
    except ArtifactValidationError as exc:
        raise SilhouetteBenchmarkError(str(exc)) from exc
    payload = {key: value for key, value in cases_document.items() if key != "sha256"}
    if cases_document["sha256"] != _canonical_sha256(payload):
        raise SilhouetteBenchmarkError("silhouette benchmark cases hash mismatch")
    if cases_document["policy_sha256"] != policy_document["sha256"]:
        raise SilhouetteBenchmarkError("silhouette benchmark cases policy hash mismatch")
    if (cases_document["truth_tier"], cases_document["truth_partition"]) != (
        "human_anchor_gold",
        "holdout",
    ):
        raise SilhouetteBenchmarkError("only human-anchor holdout truth is eligible")
    if _timestamp(cases_document["results_opened_at"], "results_opened_at") <= _timestamp(
        policy_document["frozen_at"], "frozen_at"
    ):
        raise SilhouetteBenchmarkError("silhouette benchmark results predate frozen policy")
    truth_manifest_path = Path(truth_manifest_path)
    if (
        not truth_manifest_path.is_file()
        or _file_sha256(truth_manifest_path) != cases_document["truth_manifest_sha256"]
    ):
        raise SilhouetteBenchmarkError("human-anchor truth manifest hash mismatch")
    if set(cases_document["providers"]) != set(PROVIDER_CAPABILITIES):
        raise SilhouetteBenchmarkError("silhouette benchmark evidence provider set is incomplete")

    observations: dict[str, dict[tuple[str, str, str], Mapping[str, Any]]] = {}
    provider_reports: dict[str, dict[str, Any]] = {}
    for provider in PROVIDER_CAPABILITIES:
        evidence = cases_document["providers"][provider]
        mapped = _validate_provider(provider, evidence, policy_document)
        observations[provider] = mapped
        role_metrics = []
        for role in PROVIDER_CAPABILITIES[provider]:
            role_rows = [row for (name, _context, _label), row in mapped.items() if name == role]
            context_metrics = [
                {
                    "context": context,
                    **_aggregate(
                        [mapped[(role, context, label)] for label in ROLE_MATRIX[role]["labels"]],
                        requires_alpha=bool(ROLE_MATRIX[role]["requires_alpha"]),
                    ),
                }
                for context in CONTEXTS
            ]
            label_metrics = [
                {
                    "label": label,
                    **_aggregate(
                        [mapped[(role, context, label)] for context in CONTEXTS],
                        requires_alpha=bool(ROLE_MATRIX[role]["requires_alpha"]),
                    ),
                }
                for label in ROLE_MATRIX[role]["labels"]
            ]
            role_metrics.append(
                {
                    "role": role,
                    "overall": _aggregate(
                        role_rows,
                        requires_alpha=bool(ROLE_MATRIX[role]["requires_alpha"]),
                    ),
                    "contexts": context_metrics,
                    "labels": label_metrics,
                }
            )
        provider_reports[provider] = {
            "provider": provider,
            "capabilities": list(PROVIDER_CAPABILITIES[provider]),
            "role_metrics": role_metrics,
            "runtime_metrics": evidence["runtime_metrics"],
            "governed_resolution": evidence["governed_resolution"],
        }

    requirements = policy_document["pass_requirements"]
    expected_fallbacks = {
        (role, challenger, str(spec["baseline"]))
        for role, spec in ROLE_MATRIX.items()
        for challenger in spec["challengers"]
    }
    actual_fallbacks = {
        (row["role"], row["challenger"], row["expected_provider"])
        for row in cases_document["fallback_drills"]
    }
    if len(cases_document["fallback_drills"]) != len(expected_fallbacks) or (
        actual_fallbacks != expected_fallbacks
    ):
        raise SilhouetteBenchmarkError("fallback drill matrix is incomplete")

    comparisons: list[dict[str, Any]] = []
    findings: list[str] = []
    for role, spec in ROLE_MATRIX.items():
        baseline = str(spec["baseline"])
        baseline_metrics = next(
            row for row in provider_reports[baseline]["role_metrics"] if row["role"] == role
        )["overall"]
        for challenger in spec["challengers"]:
            challenger_metrics = next(
                row
                for row in provider_reports[str(challenger)]["role_metrics"]
                if row["role"] == role
            )["overall"]
            boundary_delta = (
                challenger_metrics["boundary_f_2px"] - baseline_metrics["boundary_f_2px"]
            )
            iou_delta = challenger_metrics["foreground_iou"] - baseline_metrics["foreground_iou"]
            leakage_delta = (
                challenger_metrics["foreground_leakage_rate"]
                - baseline_metrics["foreground_leakage_rate"]
            )
            alpha_mse_delta = None
            if spec["requires_alpha"]:
                alpha_mse_delta = challenger_metrics["alpha_mse"] - baseline_metrics["alpha_mse"]
            row_findings: list[str] = []
            if boundary_delta < -float(requirements["max_boundary_f_2px_drop"]):
                row_findings.append("boundary_f_2px_noninferiority_failed")
            if iou_delta < -float(requirements["max_foreground_iou_drop"]):
                row_findings.append("foreground_iou_noninferiority_failed")
            if leakage_delta > float(requirements["max_foreground_leakage_rate_increase"]):
                row_findings.append("foreground_leakage_regression")
            if alpha_mse_delta is not None and alpha_mse_delta > float(
                requirements["max_alpha_mse_increase"]
            ):
                row_findings.append("alpha_mse_regression")
            runtime = provider_reports[str(challenger)]["runtime_metrics"]
            if runtime["oom_count"] + runtime["crash_count"] > int(
                requirements["max_oom_or_crash_count"]
            ):
                row_findings.append("runtime_failure")
            if runtime["peak_vram_bytes"] > int(requirements["max_peak_vram_bytes"]):
                row_findings.append("peak_vram_budget_exceeded")
            if runtime["repeat_count"] != int(requirements["require_deterministic_repeats"]):
                row_findings.append("determinism_repeat_count_failed")
            fallback = next(
                row
                for row in cases_document["fallback_drills"]
                if row["role"] == role and row["challenger"] == challenger
            )
            if (
                fallback["observed_provider"] != baseline
                or fallback["active_provider_after"] != baseline
                or fallback["rollback_provider_after"] != baseline
            ):
                row_findings.append("fallback_drill_failed")
            findings.extend(f"{role}:{challenger}:{finding}" for finding in row_findings)
            comparisons.append(
                {
                    "role": role,
                    "baseline": baseline,
                    "challenger": challenger,
                    "boundary_f_2px_delta": boundary_delta,
                    "foreground_iou_delta": iou_delta,
                    "foreground_leakage_rate_delta": leakage_delta,
                    "alpha_mse_delta": alpha_mse_delta,
                    "correction_pixels_per_100k_delta": (
                        challenger_metrics["correction_pixels_per_100k"]
                        - baseline_metrics["correction_pixels_per_100k"]
                    ),
                    "findings": row_findings,
                    "result": "pass" if not row_findings else "fail",
                }
            )

    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "benchmark_id": cases_document["benchmark_id"],
        "evaluated_at": cases_document["results_opened_at"],
        "policy_sha256": policy_document["sha256"],
        "source_cases_sha256": cases_document["sha256"],
        "truth_manifest_sha256": cases_document["truth_manifest_sha256"],
        "pipeline_fingerprint_sha256": cases_document["pipeline_fingerprint_sha256"],
        "hardware_fingerprint_sha256": cases_document["hardware_fingerprint_sha256"],
        "providers": [provider_reports[name] for name in PROVIDER_CAPABILITIES],
        "comparisons": comparisons,
        "fallback_drills": cases_document["fallback_drills"],
        "findings": findings,
        "result": "pass" if not findings else "fail",
        "authority": "benchmark_evidence_only_no_gold_or_production_authority",
    }
    report["sha256"] = _canonical_sha256(report)
    require_valid_document(report, "silhouette_variant_benchmark_report")
    return report


def verify_report(
    report: Mapping[str, Any],
    cases_document: Mapping[str, Any],
    *,
    truth_manifest_path: Path,
    policy: Mapping[str, Any] | None = None,
    root: Path = ROOT,
    require_pass: bool = True,
) -> None:
    """Recompute the complete report and optionally require every frozen gate."""
    try:
        require_valid_document(report, "silhouette_variant_benchmark_report")
    except ArtifactValidationError as exc:
        raise SilhouetteBenchmarkError(str(exc)) from exc
    expected = build_report(
        cases_document,
        truth_manifest_path=truth_manifest_path,
        policy=policy,
        root=root,
    )
    if dict(report) != expected:
        raise SilhouetteBenchmarkError("silhouette benchmark report recomputation mismatch")
    if require_pass and report["result"] != "pass":
        raise SilhouetteBenchmarkError(
            "silhouette benchmark gates failed: " + ", ".join(report["findings"])
        )


__all__ = [
    "CONTEXTS",
    "DEFAULT_POLICY_PATH",
    "POLICY_SHA256",
    "PROVIDER_CAPABILITIES",
    "ROLE_MATRIX",
    "SilhouetteBenchmarkError",
    "build_report",
    "load_policy",
    "validate_policy",
    "verify_report",
]
