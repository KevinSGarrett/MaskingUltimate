"""Versioned risk buckets and empirical pooling evidence for autonomous gold."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from statistics import NormalDist
from typing import Any

import yaml

from ..validation import ArtifactValidationError, require_valid_document

RISK_BUCKET_NAMES = frozenset(
    {
        "large_parts",
        "small_parts",
        "hands_feet",
        "hair_boundaries",
        "clothing_materials",
        "sensitive_anatomy",
        "occlusion_contact",
        "multi_person_overlap",
        "out_of_distribution",
    }
)
FEATURE_FIELDS = frozenset(
    {
        "label_family",
        "occlusion_or_contact",
        "multi_person_overlap",
        "out_of_distribution",
    }
)
RECORD_FIELDS = frozenset({"record_id", "risk_bucket", "stratum", "human_defect", "serious_defect"})


class RiskBucketError(ValueError):
    """Risk-bucket policy or exchangeability evidence is unsafe or incomplete."""


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_risk_bucket_policy(
    path: Path = Path("configs/autonomy_risk_buckets.yaml"),
) -> dict[str, Any]:
    """Load the exact versioned policy and reject incomplete bucket coverage."""
    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        require_valid_document(document, "autonomy_risk_buckets")
    except (OSError, yaml.YAMLError, ArtifactValidationError) as exc:
        raise RiskBucketError(f"invalid autonomy risk-bucket policy: {exc}") from exc
    if set(document["buckets"]) != RISK_BUCKET_NAMES:
        raise RiskBucketError("risk-bucket policy does not define the exact governed bucket set")
    priority = document["assignment_priority"]
    if set(priority) != RISK_BUCKET_NAMES or len(priority) != len(RISK_BUCKET_NAMES):
        raise RiskBucketError("risk-bucket assignment priority is not an exact permutation")
    if document["buckets"]["out_of_distribution"]["in_distribution"] is not False:
        raise RiskBucketError("out-of-distribution bucket cannot be marked in-distribution")
    return document


def assign_risk_bucket(features: Mapping[str, Any], policy: Mapping[str, Any]) -> str:
    """Assign exactly one bucket using the policy's explicit worst-risk precedence."""
    if set(features) != FEATURE_FIELDS:
        raise RiskBucketError(f"risk features must contain exactly {sorted(FEATURE_FIELDS)}")
    family = features["label_family"]
    if family not in RISK_BUCKET_NAMES - {
        "occlusion_contact",
        "multi_person_overlap",
        "out_of_distribution",
    }:
        raise RiskBucketError(f"unknown label-family risk bucket: {family!r}")
    for field in ("occlusion_or_contact", "multi_person_overlap", "out_of_distribution"):
        if not isinstance(features[field], bool):
            raise RiskBucketError(f"risk feature {field} must be boolean")
    applicable = {str(family)}
    if features["occlusion_or_contact"]:
        applicable.add("occlusion_contact")
    if features["multi_person_overlap"]:
        applicable.add("multi_person_overlap")
    if features["out_of_distribution"]:
        applicable.add("out_of_distribution")
    for bucket in policy["assignment_priority"]:
        if bucket in applicable:
            return str(bucket)
    raise RiskBucketError("risk-bucket policy did not assign an applicable bucket")


def _wilson_interval(failures: int, sample_count: int, confidence: float) -> tuple[float, float]:
    if sample_count <= 0:
        return (0.0, 1.0)
    z = NormalDist().inv_cdf(0.5 + confidence / 2.0)
    proportion = failures / sample_count
    denominator = 1.0 + z * z / sample_count
    center = (proportion + z * z / (2.0 * sample_count)) / denominator
    spread = (
        z
        * ((proportion * (1.0 - proportion) / sample_count + z * z / (4 * sample_count**2)) ** 0.5)
        / denominator
    )
    return (max(0.0, center - spread), min(1.0, center + spread))


def _intervals_overlap(left: Sequence[float], right: Sequence[float]) -> bool:
    return max(float(left[0]), float(right[0])) <= min(float(left[1]), float(right[1]))


def evaluate_exchangeability(
    records: Sequence[Mapping[str, Any]],
    *,
    risk_bucket: str,
    policy: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Decide pool/split/abstain from predeclared pairwise empirical checks."""
    if risk_bucket not in policy.get("buckets", {}):
        raise RiskBucketError(f"risk bucket is not registered: {risk_bucket!r}")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in records:
        if not isinstance(raw, Mapping) or set(raw) != RECORD_FIELDS:
            raise RiskBucketError(
                f"exchangeability records must contain exactly {sorted(RECORD_FIELDS)}"
            )
        record = dict(raw)
        record_id = record["record_id"]
        stratum = record["stratum"]
        if not isinstance(record_id, str) or not record_id or record_id in seen_ids:
            raise RiskBucketError("exchangeability record IDs must be nonempty and unique")
        if record["risk_bucket"] != risk_bucket:
            raise RiskBucketError("exchangeability record escaped the requested risk bucket")
        if not isinstance(stratum, str) or not stratum:
            raise RiskBucketError("exchangeability record stratum is empty")
        if not isinstance(record["human_defect"], bool) or not isinstance(
            record["serious_defect"], bool
        ):
            raise RiskBucketError("exchangeability defect outcomes must be boolean")
        if record["serious_defect"] and not record["human_defect"]:
            raise RiskBucketError("a serious defect must also be a human defect")
        seen_ids.add(record_id)
        normalized.append(record)
    if not normalized:
        raise RiskBucketError("exchangeability evaluation requires audit records")
    normalized.sort(key=lambda item: item["record_id"])
    exchange = policy["exchangeability"]
    confidence = float(exchange["confidence_level"])
    by_stratum: dict[str, list[dict[str, Any]]] = {}
    for record in normalized:
        by_stratum.setdefault(str(record["stratum"]), []).append(record)
    strata = []
    for name, rows in sorted(by_stratum.items()):
        count = len(rows)
        defects = sum(row["human_defect"] for row in rows)
        serious = sum(row["serious_defect"] for row in rows)
        strata.append(
            {
                "stratum": name,
                "sample_count": count,
                "false_accept_count": defects,
                "serious_failure_count": serious,
                "false_accept_rate": defects / count,
                "serious_failure_rate": serious / count,
                "false_accept_wilson_interval": list(_wilson_interval(defects, count, confidence)),
                "serious_failure_wilson_interval": list(
                    _wilson_interval(serious, count, confidence)
                ),
            }
        )
    minimum = int(exchange["minimum_records_per_stratum"])
    sparse = [row["stratum"] for row in strata if row["sample_count"] < minimum]
    comparisons = []
    nonexchangeable = False
    for left, right in combinations(strata, 2):
        false_delta = abs(left["false_accept_rate"] - right["false_accept_rate"])
        serious_delta = abs(left["serious_failure_rate"] - right["serious_failure_rate"])
        false_overlap = _intervals_overlap(
            left["false_accept_wilson_interval"], right["false_accept_wilson_interval"]
        )
        serious_overlap = _intervals_overlap(
            left["serious_failure_wilson_interval"],
            right["serious_failure_wilson_interval"],
        )
        passed = (
            false_delta <= float(exchange["maximum_false_accept_rate_delta"])
            and serious_delta <= float(exchange["maximum_serious_failure_rate_delta"])
            and (
                not exchange["require_wilson_interval_overlap"] or false_overlap and serious_overlap
            )
        )
        nonexchangeable = nonexchangeable or not passed
        comparisons.append(
            {
                "left": left["stratum"],
                "right": right["stratum"],
                "false_accept_rate_delta": false_delta,
                "serious_failure_rate_delta": serious_delta,
                "false_accept_intervals_overlap": false_overlap,
                "serious_failure_intervals_overlap": serious_overlap,
                "passed": passed,
            }
        )
    if sparse:
        decision = str(exchange["sparse_action"])
        pooling_allowed = False
        reasons = [f"sparse_stratum:{name}" for name in sparse]
    elif len(strata) == 1:
        decision = "not_required_single_stratum"
        pooling_allowed = True
        reasons = []
    elif nonexchangeable:
        decision = str(exchange["nonexchangeable_action"])
        pooling_allowed = False
        reasons = [
            f"nonexchangeable:{row['left']}:{row['right']}"
            for row in comparisons
            if not row["passed"]
        ]
    else:
        decision = "pool"
        pooling_allowed = True
        reasons = []
    timestamp = (generated_at or datetime.now(UTC)).astimezone(UTC)
    evidence = {
        "schema_version": "1.0.0",
        "policy_id": policy["policy_id"],
        "policy_sha256": canonical_sha256(policy),
        "risk_bucket": risk_bucket,
        "records_sha256": canonical_sha256(normalized),
        "strata": strata,
        "comparisons": comparisons,
        "decision": decision,
        "pooling_allowed": pooling_allowed,
        "reasons": reasons,
        "generated_at": timestamp.isoformat().replace("+00:00", "Z"),
    }
    evidence["sha256"] = canonical_sha256(evidence)
    return evidence


def verify_exchangeability_evidence(
    evidence: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    risk_bucket: str,
    policy: Mapping[str, Any],
) -> None:
    """Recompute evidence exactly; a report cannot self-assert exchangeability."""
    if evidence.get("sha256") != canonical_sha256(
        {key: value for key, value in evidence.items() if key != "sha256"}
    ):
        raise RiskBucketError("exchangeability evidence hash mismatch")
    try:
        generated_at = datetime.fromisoformat(
            str(evidence.get("generated_at")).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise RiskBucketError("exchangeability evidence timestamp is invalid") from exc
    if generated_at.tzinfo is None:
        raise RiskBucketError("exchangeability evidence timestamp lacks a timezone")
    expected = evaluate_exchangeability(
        records,
        risk_bucket=risk_bucket,
        policy=policy,
        generated_at=generated_at,
    )
    if dict(evidence) != expected:
        raise RiskBucketError("exchangeability evidence differs from recomputed audit evidence")
    if evidence.get("pooling_allowed") is not True or evidence.get("decision") not in {
        "pool",
        "not_required_single_stratum",
    }:
        raise RiskBucketError(f"risk bucket cannot pool: decision={evidence.get('decision')!r}")


__all__ = [
    "RISK_BUCKET_NAMES",
    "RiskBucketError",
    "assign_risk_bucket",
    "canonical_sha256",
    "evaluate_exchangeability",
    "load_risk_bucket_policy",
    "verify_exchangeability_evidence",
]
