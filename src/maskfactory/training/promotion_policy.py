"""Frozen custom-segmenter margins, result gate, and identity-bound certificate."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..validation import ArtifactValidationError, require_valid_document

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CUSTOM_SEGMENTER_MARGIN_MANIFEST = (
    ROOT / "qa" / "governance" / "benchmark_matrices" / "custom_segmenter_margins_v1.json"
)
CUSTOM_SEGMENTER_MARGIN_MANIFEST_SHA256 = (
    "d009abe2667092e5d990a05f92ba39072e6b25022f0c1116c5ed93bcb7adad90"
)
CERTIFICATE_AUTHORITY = "custom_segmenter_role_promotion_gate"
SOURCE_FILES = (
    "configs/anatomy_v2_qa.yaml",
    "configs/autonomy_multi_person_risk_buckets.yaml",
    "configs/autonomy_risk_buckets.yaml",
    "configs/ontology.yaml",
    "configs/ontology_v2.yaml",
    "configs/qa.yaml",
)
REQUIRED_RESULT_INPUT_HASHES = {
    "dataset_manifest_sha256",
    "evaluation_set_sha256",
    "hardware_profile_sha256",
    "measurement_code_sha256",
    "prompt_manifest_sha256",
    "qa_config_sha256",
}
REQUIRED_CERTIFICATE_IDENTITY_HASHES = {
    "benchmark_results_sha256",
    "checkpoint_sha256",
    "dataset_manifest_sha256",
    "evaluation_set_sha256",
    "hardware_profile_sha256",
    "license_evidence_sha256",
    "measurement_code_sha256",
    "prompt_manifest_sha256",
    "qa_config_sha256",
    "runtime_lock_sha256",
    "source_tree_sha256",
}


class CustomSegmenterPromotionError(ValueError):
    """A margin manifest, result, or certificate violates promotion policy."""


def _canonical_sha256(document: Mapping[str, Any]) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise CustomSegmenterPromotionError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise CustomSegmenterPromotionError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC)


def _sorted_unique(values: Any, field: str) -> tuple[str, ...]:
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(value, str) and value for value in values)
        or values != sorted(set(values))
    ):
        raise CustomSegmenterPromotionError(f"{field} must be a sorted unique nonempty list")
    return tuple(values)


def _load_yaml(path: Path) -> Mapping[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise CustomSegmenterPromotionError(f"governing source is not a mapping: {path}")
    return document


def _governing_coverage(root: Path) -> tuple[set[str], set[str]]:
    qa = _load_yaml(root / "configs" / "qa.yaml")
    anatomy = _load_yaml(root / "configs" / "anatomy_v2_qa.yaml")
    risk = _load_yaml(root / "configs" / "autonomy_risk_buckets.yaml")
    multi = _load_yaml(root / "configs" / "autonomy_multi_person_risk_buckets.yaml")
    hard_labels = set(qa["metrics"]["hard_classes"])
    hard_labels.update(anatomy["vlm"]["canonical_anatomy_vocabulary"])
    high_risk = {
        str(name)
        for name, entry in risk["buckets"].items()
        if entry.get("high_risk") is True and entry.get("in_distribution") is True
    }
    high_risk.update(str(name) for name in multi["buckets"])
    return hard_labels, high_risk


def _validate_hash_set(value: Any, required: set[str], field: str) -> None:
    if not isinstance(value, Mapping) or set(value) != required:
        raise CustomSegmenterPromotionError(f"{field} hash set is incomplete")
    if any(not _is_sha256(digest) for digest in value.values()):
        raise CustomSegmenterPromotionError(f"{field} contains an invalid SHA-256")


def validate_custom_segmenter_margin_manifest(
    document: Mapping[str, Any],
    *,
    root: Path = ROOT,
    expected_sha256: str | None = CUSTOM_SEGMENTER_MARGIN_MANIFEST_SHA256,
) -> dict[str, float]:
    """Validate and expand every predeclared hard-label/high-risk margin."""
    try:
        require_valid_document(document, "custom_segmenter_benchmark_margins")
    except ArtifactValidationError as exc:
        raise CustomSegmenterPromotionError(str(exc)) from exc
    payload = {key: value for key, value in document.items() if key != "sha256"}
    claimed = str(document["sha256"])
    if claimed != _canonical_sha256(payload):
        raise CustomSegmenterPromotionError("custom segmenter margin manifest hash mismatch")
    if expected_sha256 is not None and claimed != expected_sha256:
        raise CustomSegmenterPromotionError(
            "custom segmenter margin manifest differs from locked hash"
        )
    _timestamp(document["frozen_at"], "frozen_at")

    source_hashes = document["source_hashes"]
    if set(source_hashes) != set(SOURCE_FILES):
        raise CustomSegmenterPromotionError("custom segmenter source hash set is incomplete")
    for relative in SOURCE_FILES:
        path = Path(root) / relative
        if not path.is_file() or _file_sha256(path) != source_hashes[relative]:
            raise CustomSegmenterPromotionError(f"governing source hash drift: {relative}")

    role = document["role"]
    labels = _sorted_unique(role["hard_labels"], "role.hard_labels")
    contexts = _sorted_unique(role["high_risk_contexts"], "role.high_risk_contexts")
    zero_metrics = _sorted_unique(role["zero_regression_metrics"], "role.zero_regression_metrics")
    required_labels, required_contexts = _governing_coverage(Path(root))
    if set(labels) != required_labels:
        raise CustomSegmenterPromotionError("custom segmenter hard-label margins are incomplete")
    if set(contexts) != required_contexts:
        raise CustomSegmenterPromotionError("custom segmenter high-risk margins are incomplete")

    expanded: dict[str, float] = {}
    for label in labels:
        for metric, margin in sorted(role["label_margins"].items()):
            expanded[f"label:{label}:{metric}"] = float(margin)
    for context in contexts:
        for metric, margin in sorted(role["context_margins"].items()):
            expanded[f"context:{context}:{metric}"] = float(margin)
    for metric in zero_metrics:
        expanded[f"zero_regression:{metric}"] = 0.0
    return expanded


def load_custom_segmenter_margin_manifest(
    path: Path = DEFAULT_CUSTOM_SEGMENTER_MARGIN_MANIFEST,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], dict[str, float]]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise CustomSegmenterPromotionError("custom segmenter margin manifest is not an object")
    return document, validate_custom_segmenter_margin_manifest(document, root=root)


def _objective_passed(result: Any, objective: Mapping[str, Any], field: str) -> bool:
    required = {"metric", "observed_improvement", "minimum_improvement", "passed"}
    if not isinstance(result, Mapping) or set(result) != required:
        raise CustomSegmenterPromotionError(f"{field} result structure is invalid")
    observed = result["observed_improvement"]
    if (
        result["metric"] != objective["metric"]
        or float(result["minimum_improvement"]) != float(objective["minimum_improvement"])
        or isinstance(observed, bool)
        or not isinstance(observed, (int, float))
        or not math.isfinite(float(observed))
    ):
        raise CustomSegmenterPromotionError(f"{field} result does not match its frozen objective")
    passed = float(observed) >= float(objective["minimum_improvement"])
    if result["passed"] is not passed:
        raise CustomSegmenterPromotionError(f"{field} result pass flag is inconsistent")
    return passed


def validate_custom_segmenter_benchmark_results(
    results: Mapping[str, Any],
    *,
    margin_manifest: Mapping[str, Any],
    root: Path = ROOT,
) -> None:
    """Reject aggregate wins that hide any hard bucket or zero-regression loss."""
    required = {
        "schema_version",
        "benchmark_id",
        "role",
        "margin_manifest_sha256",
        "results_opened_at",
        "input_hashes",
        "primary_objective_result",
        "labor_objective_result",
        "rows",
        "sha256",
    }
    if set(results) != required or results.get("schema_version") != "1.0.0":
        raise CustomSegmenterPromotionError("custom segmenter result structure is invalid")
    if results.get("role") != "custom_segmenter":
        raise CustomSegmenterPromotionError("custom segmenter result role is invalid")
    expanded = validate_custom_segmenter_margin_manifest(margin_manifest, root=root)
    if results.get("margin_manifest_sha256") != margin_manifest["sha256"]:
        raise CustomSegmenterPromotionError("custom segmenter margin hash mismatch")
    if _timestamp(results["results_opened_at"], "results_opened_at") <= _timestamp(
        margin_manifest["frozen_at"], "frozen_at"
    ):
        raise CustomSegmenterPromotionError("custom segmenter results predate frozen margins")
    _validate_hash_set(results["input_hashes"], REQUIRED_RESULT_INPUT_HASHES, "result input")

    role = margin_manifest["role"]
    primary_passed = _objective_passed(
        results["primary_objective_result"], role["primary_objective"], "primary objective"
    )
    labor_passed = _objective_passed(
        results["labor_objective_result"], role["labor_objective"], "labor objective"
    )
    if not primary_passed and not labor_passed:
        raise CustomSegmenterPromotionError(
            "custom segmenter lacks a primary win or material labor reduction"
        )

    payload = {key: value for key, value in results.items() if key != "sha256"}
    if results["sha256"] != _canonical_sha256(payload):
        raise CustomSegmenterPromotionError("custom segmenter result hash mismatch")
    rows = results["rows"]
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise CustomSegmenterPromotionError("custom segmenter result rows are invalid")
    observed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "bucket",
            "observed_delta",
            "noninferiority_margin",
            "passed",
        }:
            raise CustomSegmenterPromotionError("custom segmenter row structure is invalid")
        bucket = row["bucket"]
        if not isinstance(bucket, str) or bucket in observed:
            raise CustomSegmenterPromotionError("custom segmenter bucket is invalid or duplicated")
        observed[bucket] = row
    if set(observed) != set(expanded):
        raise CustomSegmenterPromotionError("custom segmenter bucket coverage is incomplete")
    for bucket, margin in expanded.items():
        row = observed[bucket]
        delta = row["observed_delta"]
        if (
            isinstance(delta, bool)
            or not isinstance(delta, (int, float))
            or not math.isfinite(float(delta))
            or float(row["noninferiority_margin"]) != margin
        ):
            raise CustomSegmenterPromotionError(f"custom segmenter margin drift for {bucket}")
        passed = float(delta) >= -margin
        if row["passed"] is not passed or not passed:
            raise CustomSegmenterPromotionError(
                f"custom segmenter non-inferiority failed for {bucket}"
            )


def _validate_content_and_license(certificate: Mapping[str, Any]) -> None:
    license_gate = certificate.get("license_gate")
    if not isinstance(license_gate, Mapping) or set(license_gate) != {
        "verify_license",
        "checkpoint_decision",
    }:
        raise CustomSegmenterPromotionError("certificate license gate is incomplete")
    if (
        license_gate["verify_license"] is not False
        or license_gate["checkpoint_decision"] != "allowed"
    ):
        raise CustomSegmenterPromotionError("certificate license gate is unresolved")


def _validate_rollback(value: Any, candidate_key: str) -> None:
    required = {
        "candidate_provider",
        "incumbent_provider",
        "target_role",
        "one_command",
        "rollback_observed",
        "restore_observed",
        "result",
        "tested_at",
        "evidence_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise CustomSegmenterPromotionError("certificate rollback evidence is incomplete")
    incumbent = value["incumbent_provider"]
    if (
        value["candidate_provider"] != candidate_key
        or value["target_role"] != "custom_segmenter"
        or not isinstance(incumbent, str)
        or not incumbent
        or incumbent == candidate_key
        or not isinstance(value["one_command"], str)
        or not value["one_command"]
        or value["rollback_observed"] is not True
        or value["restore_observed"] is not True
        or value["result"] != "pass"
        or not _is_sha256(value["evidence_sha256"])
    ):
        raise CustomSegmenterPromotionError("certificate rollback evidence did not pass")
    _timestamp(value["tested_at"], "rollback_evidence.tested_at")


def validate_custom_segmenter_promotion_certificate(
    certificate: Mapping[str, Any],
    *,
    expected_identity_hashes: Mapping[str, Any],
    margin_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a current certificate without mutating any role or lifecycle."""
    required = {
        "schema_version",
        "authority",
        "candidate_key",
        "target_role",
        "lifecycle_state",
        "identity_hashes",
        "license_gate",
        "benchmark_results",
        "rollback_evidence",
        "sha256",
    }
    if set(certificate) != required:
        raise CustomSegmenterPromotionError("custom segmenter certificate structure is invalid")
    if (
        certificate["schema_version"] != "1.0.0"
        or certificate["authority"] != CERTIFICATE_AUTHORITY
        or certificate["target_role"] != "custom_segmenter"
        or certificate["lifecycle_state"] != "benchmarked"
    ):
        raise CustomSegmenterPromotionError(
            "custom segmenter certificate identity or lifecycle is invalid"
        )
    candidate_key = certificate["candidate_key"]
    if not isinstance(candidate_key, str) or not candidate_key:
        raise CustomSegmenterPromotionError("custom segmenter candidate key is invalid")

    _validate_hash_set(
        certificate["identity_hashes"],
        REQUIRED_CERTIFICATE_IDENTITY_HASHES,
        "certificate identity",
    )
    _validate_hash_set(
        expected_identity_hashes,
        REQUIRED_CERTIFICATE_IDENTITY_HASHES,
        "current identity",
    )
    if dict(certificate["identity_hashes"]) != dict(expected_identity_hashes):
        raise CustomSegmenterPromotionError("custom segmenter certificate identity is stale")
    _validate_content_and_license(certificate)
    if margin_manifest is None:
        margin_manifest, _ = load_custom_segmenter_margin_manifest()
    benchmark_results = certificate["benchmark_results"]
    if not isinstance(benchmark_results, Mapping):
        raise CustomSegmenterPromotionError("custom segmenter benchmark results are missing")
    validate_custom_segmenter_benchmark_results(
        benchmark_results,
        margin_manifest=margin_manifest,
    )
    if certificate["identity_hashes"]["benchmark_results_sha256"] != benchmark_results["sha256"]:
        raise CustomSegmenterPromotionError(
            "custom segmenter certificate does not bind benchmark results"
        )
    for result_key, identity_key in (
        ("dataset_manifest_sha256", "dataset_manifest_sha256"),
        ("evaluation_set_sha256", "evaluation_set_sha256"),
        ("hardware_profile_sha256", "hardware_profile_sha256"),
        ("measurement_code_sha256", "measurement_code_sha256"),
        ("prompt_manifest_sha256", "prompt_manifest_sha256"),
        ("qa_config_sha256", "qa_config_sha256"),
    ):
        if (
            benchmark_results["input_hashes"][result_key]
            != certificate["identity_hashes"][identity_key]
        ):
            raise CustomSegmenterPromotionError(
                f"custom segmenter certificate input binding is stale: {result_key}"
            )
    _validate_rollback(certificate["rollback_evidence"], candidate_key)
    payload = {key: value for key, value in certificate.items() if key != "sha256"}
    if certificate["sha256"] != _canonical_sha256(payload):
        raise CustomSegmenterPromotionError("custom segmenter certificate hash mismatch")
    return {
        "candidate_key": candidate_key,
        "target_role": "custom_segmenter",
        "lifecycle_state": "benchmarked",
        "rollback_provider": certificate["rollback_evidence"]["incumbent_provider"],
        "certificate_sha256": certificate["sha256"],
        "authority": "validated_prerequisites_only_no_role_serving_or_gold_authority",
    }


__all__ = [
    "CERTIFICATE_AUTHORITY",
    "CUSTOM_SEGMENTER_MARGIN_MANIFEST_SHA256",
    "CustomSegmenterPromotionError",
    "DEFAULT_CUSTOM_SEGMENTER_MARGIN_MANIFEST",
    "REQUIRED_CERTIFICATE_IDENTITY_HASHES",
    "REQUIRED_RESULT_INPUT_HASHES",
    "load_custom_segmenter_margin_manifest",
    "validate_custom_segmenter_benchmark_results",
    "validate_custom_segmenter_margin_manifest",
    "validate_custom_segmenter_promotion_certificate",
]
