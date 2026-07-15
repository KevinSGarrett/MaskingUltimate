"""Frozen, pre-result specialist non-inferiority policy and result verification."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..validation import ArtifactValidationError, require_valid_document

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SPECIALIST_MARGIN_MANIFEST = (
    ROOT / "qa" / "governance" / "benchmark_matrices" / "specialist_margins_v1.json"
)
SPECIALIST_MARGIN_MANIFEST_SHA256 = (
    "605f79e0d4f8354a7a4d445a0a5725af829cd78b85e2e36f91b065576553a739"
)
SPECIALIST_ROLES = frozenset(
    {
        "chest_pelvic_segmentation",
        "clothing_accessory_segmentation",
        "foot_toe_segmentation",
        "geometry_provider",
        "hair_matting",
        "hand_finger_segmentation",
        "pose_provider",
        "repeated_instance_segmentation",
        "silhouette_provider",
    }
)
SOURCE_FILES = (
    "configs/anatomy_v2_qa.yaml",
    "configs/autonomy_multi_person_risk_buckets.yaml",
    "configs/autonomy_risk_buckets.yaml",
    "configs/ontology.yaml",
    "configs/ontology_v2.yaml",
    "configs/qa.yaml",
)


class SpecialistBenchmarkPolicyError(ValueError):
    """Specialist margins or results violate the frozen pre-result contract."""


def _canonical_sha256(document: Mapping[str, Any]) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_yaml(path: Path) -> Mapping[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise SpecialistBenchmarkPolicyError(f"governing source is not a mapping: {path}")
    return document


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SpecialistBenchmarkPolicyError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise SpecialistBenchmarkPolicyError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC)


def _sorted_unique(values: Any, field: str) -> tuple[str, ...]:
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(value, str) and value for value in values)
        or values != sorted(set(values))
    ):
        raise SpecialistBenchmarkPolicyError(f"{field} must be a sorted unique nonempty list")
    return tuple(values)


def _governing_coverage(root: Path) -> tuple[set[str], set[str], set[str]]:
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
    multi_person = set(multi["buckets"])
    return hard_labels, high_risk, multi_person


def validate_specialist_margin_manifest(
    document: Mapping[str, Any],
    *,
    root: Path = ROOT,
    expected_sha256: str | None = SPECIALIST_MARGIN_MANIFEST_SHA256,
) -> dict[str, dict[str, float]]:
    """Validate source coverage, immutable hashes, and expand every governed bucket margin."""
    try:
        require_valid_document(document, "specialist_benchmark_margins")
    except ArtifactValidationError as exc:
        raise SpecialistBenchmarkPolicyError(str(exc)) from exc
    claimed = str(document["sha256"])
    payload = {key: value for key, value in document.items() if key != "sha256"}
    actual = _canonical_sha256(payload)
    if claimed != actual:
        raise SpecialistBenchmarkPolicyError("specialist margin manifest hash mismatch")
    if expected_sha256 is not None and claimed != expected_sha256:
        raise SpecialistBenchmarkPolicyError("specialist margin manifest differs from locked hash")
    _timestamp(document["frozen_at"], "frozen_at")

    source_hashes = document["source_hashes"]
    if set(source_hashes) != set(SOURCE_FILES):
        raise SpecialistBenchmarkPolicyError("specialist margin source hash set is incomplete")
    for relative in SOURCE_FILES:
        path = Path(root) / relative
        if not path.is_file() or _file_sha256(path) != source_hashes[relative]:
            raise SpecialistBenchmarkPolicyError(f"governing source hash drift: {relative}")

    roles = document["roles"]
    if set(roles) != SPECIALIST_ROLES:
        raise SpecialistBenchmarkPolicyError("specialist role set is incomplete or contains extras")
    expanded: dict[str, dict[str, float]] = {}
    all_labels: set[str] = set()
    all_contexts: set[str] = set()
    for role_name in sorted(roles):
        role = roles[role_name]
        labels = _sorted_unique(role["hard_labels"], f"{role_name}.hard_labels")
        contexts = _sorted_unique(role["high_risk_contexts"], f"{role_name}.high_risk_contexts")
        zero_metrics = _sorted_unique(
            role["zero_regression_metrics"], f"{role_name}.zero_regression_metrics"
        )
        all_labels.update(labels)
        all_contexts.update(contexts)
        buckets: dict[str, float] = {}
        for label in labels:
            for metric, margin in sorted(role["label_margins"].items()):
                buckets[f"label:{label}:{metric}"] = float(margin)
        for context in contexts:
            for metric, margin in sorted(role["context_margins"].items()):
                buckets[f"context:{context}:{metric}"] = float(margin)
        for metric in zero_metrics:
            buckets[f"zero_regression:{metric}"] = 0.0
        expanded[role_name] = buckets

    required_labels, required_contexts, multi_contexts = _governing_coverage(Path(root))
    missing_labels = sorted(required_labels - all_labels)
    missing_contexts = sorted(required_contexts - all_contexts)
    repeated = set(roles["repeated_instance_segmentation"]["high_risk_contexts"])
    missing_multi = sorted(multi_contexts - repeated)
    if missing_labels:
        raise SpecialistBenchmarkPolicyError(
            "hard specialist labels lack margins: " + ", ".join(missing_labels)
        )
    if missing_contexts:
        raise SpecialistBenchmarkPolicyError(
            "high-risk contexts lack margins: " + ", ".join(missing_contexts)
        )
    if missing_multi:
        raise SpecialistBenchmarkPolicyError(
            "multi-person contexts lack repeated-instance margins: " + ", ".join(missing_multi)
        )
    return expanded


def load_specialist_margin_manifest(
    path: Path = DEFAULT_SPECIALIST_MARGIN_MANIFEST,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], dict[str, dict[str, float]]]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SpecialistBenchmarkPolicyError("specialist margin manifest is not an object")
    expanded = validate_specialist_margin_manifest(document, root=root)
    return document, expanded


def validate_specialist_benchmark_results(
    results: Mapping[str, Any],
    *,
    margin_manifest: Mapping[str, Any],
    root: Path = ROOT,
) -> None:
    """Require exact frozen buckets; a favorable aggregate cannot hide one regression."""
    required = {
        "schema_version",
        "benchmark_id",
        "role",
        "margin_manifest_sha256",
        "results_opened_at",
        "primary_win_or_labor_reduction",
        "rows",
        "sha256",
    }
    if set(results) != required or results.get("schema_version") != "1.0.0":
        raise SpecialistBenchmarkPolicyError("specialist benchmark result structure is invalid")
    expanded = validate_specialist_margin_manifest(margin_manifest, root=root)
    role = results.get("role")
    if role not in expanded:
        raise SpecialistBenchmarkPolicyError("specialist benchmark result role is unknown")
    if results.get("margin_manifest_sha256") != margin_manifest["sha256"]:
        raise SpecialistBenchmarkPolicyError("specialist benchmark margin hash mismatch")
    if results.get("primary_win_or_labor_reduction") is not True:
        raise SpecialistBenchmarkPolicyError("specialist benchmark lacks a primary win")
    if _timestamp(results["results_opened_at"], "results_opened_at") <= _timestamp(
        margin_manifest["frozen_at"], "frozen_at"
    ):
        raise SpecialistBenchmarkPolicyError("specialist results predate frozen margins")
    payload = {key: value for key, value in results.items() if key != "sha256"}
    if results["sha256"] != _canonical_sha256(payload):
        raise SpecialistBenchmarkPolicyError("specialist benchmark result hash mismatch")

    rows = results["rows"]
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise SpecialistBenchmarkPolicyError("specialist benchmark rows are invalid")
    expected = expanded[str(role)]
    observed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "bucket",
            "observed_delta",
            "noninferiority_margin",
            "passed",
        }:
            raise SpecialistBenchmarkPolicyError("specialist benchmark row structure is invalid")
        bucket = row["bucket"]
        if not isinstance(bucket, str) or bucket in observed:
            raise SpecialistBenchmarkPolicyError(
                "specialist benchmark bucket is invalid or duplicated"
            )
        observed[bucket] = row
    if set(observed) != set(expected):
        raise SpecialistBenchmarkPolicyError("specialist benchmark bucket coverage is incomplete")
    for bucket, margin in expected.items():
        row = observed[bucket]
        delta = row["observed_delta"]
        if (
            isinstance(delta, bool)
            or not isinstance(delta, (int, float))
            or float(row["noninferiority_margin"]) != margin
        ):
            raise SpecialistBenchmarkPolicyError(f"specialist benchmark margin drift for {bucket}")
        passed = float(delta) >= -margin
        if row["passed"] is not passed or not passed:
            raise SpecialistBenchmarkPolicyError(
                f"specialist benchmark non-inferiority failed for {bucket}"
            )


__all__ = [
    "DEFAULT_SPECIALIST_MARGIN_MANIFEST",
    "SPECIALIST_MARGIN_MANIFEST_SHA256",
    "SPECIALIST_ROLES",
    "SpecialistBenchmarkPolicyError",
    "load_specialist_margin_manifest",
    "validate_specialist_benchmark_results",
    "validate_specialist_margin_manifest",
]
