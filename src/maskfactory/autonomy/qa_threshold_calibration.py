"""Build fail-closed empirical QA-threshold calibration evidence.

The compiler measures evidence coverage and split integrity.  It deliberately
cannot promote a threshold registry: qualification and immutable publication
remain separate authority-controlled operations.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..validation import ArtifactValidationError, require_valid_document
from .qa_thresholds import DEFAULT_REGISTRY, expand_registry, load_qa_threshold_registry


class QaThresholdCalibrationError(ValueError):
    """Calibration evidence is malformed, leaked, stale, or ambiguous."""


def _sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise QaThresholdCalibrationError(f"invalid RFC3339 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise QaThresholdCalibrationError("calibration timestamps must include a timezone")
    return parsed


def _validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "policy_id",
        "policy_sha256",
        "frozen_at",
        "minimum_calibration_positive_per_label",
        "minimum_calibration_negative_per_label",
        "minimum_holdout_positive_per_label",
        "minimum_holdout_negative_per_label",
        "required_domains",
        "required_risks",
        "required_size_buckets",
    }
    if set(policy) != required:
        raise QaThresholdCalibrationError("calibration policy has the wrong closed contract")
    normalized = dict(policy)
    claimed = normalized.pop("policy_sha256")
    if claimed != _sha256(normalized):
        raise QaThresholdCalibrationError("calibration policy hash mismatch")
    _parse_time(str(policy["frozen_at"]))
    for field in (
        "minimum_calibration_positive_per_label",
        "minimum_calibration_negative_per_label",
        "minimum_holdout_positive_per_label",
        "minimum_holdout_negative_per_label",
    ):
        if (
            not isinstance(policy[field], int)
            or isinstance(policy[field], bool)
            or policy[field] < 1
        ):
            raise QaThresholdCalibrationError(f"invalid calibration minimum: {field}")
    for field in ("required_domains", "required_risks", "required_size_buckets"):
        values = policy[field]
        if (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(values))
            or any(not isinstance(value, str) or not value for value in values)
        ):
            raise QaThresholdCalibrationError(f"invalid calibration stratum: {field}")
    if set(policy["required_size_buckets"]) - {"tiny", "small", "medium", "large"}:
        raise QaThresholdCalibrationError("unknown calibration size bucket")
    return dict(policy)


def build_calibration_report(
    *,
    calibration_run_id: str,
    policy: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    registry_path: Path = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    """Compile exact coverage evidence without granting threshold authority."""

    checked_policy = _validate_policy(policy)
    registry = load_qa_threshold_registry(registry_path)
    expanded = expand_registry(registry_path=registry_path)
    labels = {row["label"] for row in expanded["labels"]}
    contexts = set(registry["contexts"])
    frozen_at = _parse_time(str(checked_policy["frozen_at"]))

    normalized_records: list[dict[str, Any]] = []
    record_ids: set[str] = set()
    partition_by_source: dict[str, set[str]] = defaultdict(set)
    partition_by_package: dict[str, set[str]] = defaultdict(set)
    counts_by_label: dict[str, Counter[str]] = {label: Counter() for label in labels}
    context_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    risk_counts: Counter[str] = Counter()
    size_counts: Counter[str] = Counter()

    for source in records:
        record = dict(source)
        probe = {
            "schema_version": "1.0.0",
            "calibration_run_id": calibration_run_id,
            "registry_binding": {
                "registry_id": registry["registry_id"],
                "registry_file_sha256": registry["registry_file_sha256"],
                "resolved_registry_sha256": expanded["resolved_registry_sha256"],
                "ontology_sha256": expanded["ontology_sha256"],
                "qualification_status": registry["qualification_status"],
                "authority_eligible": False,
            },
            "policy": checked_policy,
            "records": [record],
            "report": {
                "status": "insufficient_evidence",
                "authority_claim": "calibration_candidate_only_not_gold_authority",
                "record_count": 1,
                "calibration_record_count": 0,
                "holdout_record_count": 0,
                "coverage": {
                    "labels": {},
                    "contexts": {},
                    "domains": {},
                    "risks": {},
                    "size_buckets": {},
                },
                "missing": {
                    "labels": [],
                    "contexts": [],
                    "domains": [],
                    "risks": [],
                    "size_buckets": [],
                    "label_partition_counts": [],
                },
                "leakage_count": 0,
                "after_freeze_violation_count": 0,
                "records_sha256": "0" * 64,
                "report_sha256": "0" * 64,
            },
        }
        try:
            require_valid_document(probe, "autonomous_gold_qa_threshold_calibration")
        except ArtifactValidationError as exc:
            raise QaThresholdCalibrationError(
                f"calibration record has an invalid closed contract: {record.get('record_id')}"
            ) from exc
        record_id = record["record_id"]
        if record_id in record_ids:
            raise QaThresholdCalibrationError(f"duplicate calibration record_id: {record_id}")
        record_ids.add(record_id)
        if record["label"] not in labels:
            raise QaThresholdCalibrationError(f"unknown enabled label: {record['label']}")
        unknown_contexts = set(record["contexts"]) - contexts
        if unknown_contexts:
            raise QaThresholdCalibrationError(
                f"unregistered calibration contexts: {sorted(unknown_contexts)}"
            )
        measured_at = _parse_time(record["measured_at"])
        if record["partition"] == "qualification_holdout" and measured_at < frozen_at:
            raise QaThresholdCalibrationError(
                "qualification holdout was measured before the threshold policy was frozen"
            )
        partition_by_source[record["source_sha256"]].add(record["partition"])
        partition_by_package[record["package_sha256"]].add(record["partition"])
        key = f"{record['partition']}_{record['expected_outcome']}"
        counts_by_label[record["label"]][key] += 1
        context_counts.update(record["contexts"])
        domain_counts[record["domain"]] += 1
        risk_counts.update(record["risks"])
        size_counts[record["size_bucket"]] += 1
        normalized_records.append(record)

    leaked_sources = sorted(key for key, value in partition_by_source.items() if len(value) > 1)
    leaked_packages = sorted(key for key, value in partition_by_package.items() if len(value) > 1)
    if leaked_sources or leaked_packages:
        raise QaThresholdCalibrationError(
            "calibration/qualification holdout leakage detected "
            f"(sources={len(leaked_sources)}, packages={len(leaked_packages)})"
        )

    missing_label_counts: list[str] = []
    count_fields = {
        "calibration_positive": "minimum_calibration_positive_per_label",
        "calibration_negative": "minimum_calibration_negative_per_label",
        "qualification_holdout_positive": "minimum_holdout_positive_per_label",
        "qualification_holdout_negative": "minimum_holdout_negative_per_label",
    }
    coverage_labels: dict[str, dict[str, int]] = {}
    for label in sorted(labels):
        row = {
            "calibration_positive": counts_by_label[label]["calibration_positive"],
            "calibration_negative": counts_by_label[label]["calibration_negative"],
            "holdout_positive": counts_by_label[label]["qualification_holdout_positive"],
            "holdout_negative": counts_by_label[label]["qualification_holdout_negative"],
        }
        coverage_labels[label] = row
        for source_field, policy_field in count_fields.items():
            report_field = source_field.replace("qualification_", "")
            if row[report_field] < checked_policy[policy_field]:
                missing_label_counts.append(f"{label}:{report_field}")

    missing_labels = sorted(
        label for label, row in coverage_labels.items() if not any(row.values())
    )
    missing_contexts = sorted(contexts - set(context_counts))
    missing_domains = sorted(set(checked_policy["required_domains"]) - set(domain_counts))
    missing_risks = sorted(set(checked_policy["required_risks"]) - set(risk_counts))
    missing_sizes = sorted(set(checked_policy["required_size_buckets"]) - set(size_counts))
    incomplete = any(
        (
            missing_label_counts,
            missing_contexts,
            missing_domains,
            missing_risks,
            missing_sizes,
        )
    )

    report = {
        "status": ("insufficient_evidence" if incomplete else "ready_for_qualification_holdout"),
        "authority_claim": "calibration_candidate_only_not_gold_authority",
        "record_count": len(normalized_records),
        "calibration_record_count": sum(
            record["partition"] == "calibration" for record in normalized_records
        ),
        "holdout_record_count": sum(
            record["partition"] == "qualification_holdout" for record in normalized_records
        ),
        "coverage": {
            "labels": coverage_labels,
            "contexts": dict(sorted(context_counts.items())),
            "domains": dict(sorted(domain_counts.items())),
            "risks": dict(sorted(risk_counts.items())),
            "size_buckets": dict(sorted(size_counts.items())),
        },
        "missing": {
            "labels": missing_labels,
            "contexts": missing_contexts,
            "domains": missing_domains,
            "risks": missing_risks,
            "size_buckets": missing_sizes,
            "label_partition_counts": sorted(missing_label_counts),
        },
        "leakage_count": 0,
        "after_freeze_violation_count": 0,
        "records_sha256": _sha256(normalized_records),
    }
    report["report_sha256"] = _sha256(report)
    result = {
        "schema_version": "1.0.0",
        "calibration_run_id": calibration_run_id,
        "registry_binding": {
            "registry_id": registry["registry_id"],
            "registry_file_sha256": registry["registry_file_sha256"],
            "resolved_registry_sha256": expanded["resolved_registry_sha256"],
            "ontology_sha256": expanded["ontology_sha256"],
            "qualification_status": registry["qualification_status"],
            "authority_eligible": False,
        },
        "policy": checked_policy,
        "records": normalized_records,
        "report": report,
    }
    try:
        require_valid_document(result, "autonomous_gold_qa_threshold_calibration")
    except ArtifactValidationError as exc:
        raise QaThresholdCalibrationError("calibration report failed schema validation") from exc
    return result


__all__ = [
    "QaThresholdCalibrationError",
    "build_calibration_report",
]
