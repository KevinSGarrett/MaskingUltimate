"""Separate multi-person autonomy strata; solo evidence never grants authority."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from ..validation import ArtifactValidationError, require_valid_document
from .risk_buckets import RiskBucketError, evaluate_exchangeability

MULTI_PERSON_BUCKETS = frozenset(
    {
        "duo_baseline",
        "small_group_baseline",
        "duo_overlap",
        "small_group_overlap",
        "contact",
        "occlusion",
        "scale_disparity",
        "truncation",
        "crowding",
        "identity_ambiguity",
    }
)
FEATURE_FIELDS = frozenset(
    {
        "instance_context",
        "overlap",
        "contact",
        "occlusion",
        "scale_disparity",
        "truncation",
        "crowding",
        "identity_ambiguity",
    }
)
POOL_RECORD_FIELDS = frozenset(
    {
        "record_id",
        "risk_bucket",
        "stratum",
        "source_instance_context",
        "human_defect",
        "serious_defect",
    }
)


class MultiPersonRiskError(ValueError):
    """Multi-person evidence attempts invalid assignment or solo authority reuse."""


def load_multi_person_risk_policy(
    path: Path = Path("configs/autonomy_multi_person_risk_buckets.yaml"),
) -> dict[str, Any]:
    try:
        policy = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        require_valid_document(policy, "autonomy_multi_person_risk_buckets")
    except (OSError, yaml.YAMLError, ArtifactValidationError) as exc:
        raise MultiPersonRiskError(f"invalid multi-person risk policy: {exc}") from exc
    if (
        set(policy["buckets"]) != MULTI_PERSON_BUCKETS
        or set(policy["assignment_priority"]) != MULTI_PERSON_BUCKETS
    ):
        raise MultiPersonRiskError("multi-person risk policy bucket coverage is incomplete")
    return policy


def assign_multi_person_risk_bucket(features: Mapping[str, Any], policy: Mapping[str, Any]) -> str:
    if set(features) != FEATURE_FIELDS:
        raise MultiPersonRiskError(
            f"multi-person risk features must contain exactly {sorted(FEATURE_FIELDS)}"
        )
    context = features["instance_context"]
    if context not in policy["allowed_instance_contexts"]:
        raise MultiPersonRiskError("solo or unknown context cannot use multi-person certification")
    for field in FEATURE_FIELDS - {"instance_context"}:
        if not isinstance(features[field], bool):
            raise MultiPersonRiskError(f"multi-person feature {field} must be boolean")
    applicable = {
        field
        for field in (
            "contact",
            "occlusion",
            "scale_disparity",
            "truncation",
            "crowding",
            "identity_ambiguity",
        )
        if features[field]
    }
    if features["overlap"]:
        applicable.add(f"{context}_overlap")
    applicable.add(f"{context}_baseline")
    for bucket in policy["assignment_priority"]:
        if bucket in applicable:
            return str(bucket)
    raise MultiPersonRiskError("multi-person risk policy did not assign a bucket")


def evaluate_multi_person_exchangeability(
    records: Sequence[Mapping[str, Any]],
    *,
    risk_bucket: str,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate within-bucket pooling while refusing any solo/context borrowing."""
    if risk_bucket not in MULTI_PERSON_BUCKETS:
        raise MultiPersonRiskError(f"unregistered multi-person risk bucket: {risk_bucket}")
    normalized = []
    for record in records:
        if not isinstance(record, Mapping) or set(record) != POOL_RECORD_FIELDS:
            raise MultiPersonRiskError(
                f"multi-person pooling records must contain exactly {sorted(POOL_RECORD_FIELDS)}"
            )
        context = record["source_instance_context"]
        if context not in policy["allowed_instance_contexts"]:
            raise MultiPersonRiskError("solo evidence cannot enter a multi-person certificate pool")
        expected_prefix = "duo_" if context == "duo" else "small_group_"
        if risk_bucket.endswith(("baseline", "overlap")) and not risk_bucket.startswith(
            expected_prefix
        ):
            raise MultiPersonRiskError("multi-person evidence context differs from bucket scope")
        normalized.append(
            {
                "record_id": record["record_id"],
                "risk_bucket": record["risk_bucket"],
                "stratum": f"{context}:{record['stratum']}",
                "human_defect": record["human_defect"],
                "serious_defect": record["serious_defect"],
            }
        )
    try:
        return evaluate_exchangeability(
            normalized,
            risk_bucket=risk_bucket,
            policy=policy,
        )
    except RiskBucketError as exc:
        raise MultiPersonRiskError(str(exc)) from exc


__all__ = [
    "MULTI_PERSON_BUCKETS",
    "MultiPersonRiskError",
    "assign_multi_person_risk_bucket",
    "evaluate_multi_person_exchangeability",
    "load_multi_person_risk_policy",
]
