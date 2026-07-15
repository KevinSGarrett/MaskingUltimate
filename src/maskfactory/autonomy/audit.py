"""Deterministic sparse audit sampling and immediate autonomy-certificate revocation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from math import ceil
from typing import Any


@dataclass(frozen=True)
class AuditSelection:
    selected_record_ids: tuple[str, ...]
    population_count: int
    selected_count: int
    fraction: float
    minimum_applied: int


@dataclass(frozen=True)
class MixedAuditSelection:
    selected_record_ids: tuple[str, ...]
    random_record_ids: tuple[str, ...]
    risk_record_ids: tuple[str, ...]
    population_count: int


@dataclass(frozen=True)
class MultiPersonAuditSelection:
    selected_record_ids: tuple[str, ...]
    selected_image_ids: tuple[str, ...]
    random_image_ids: tuple[str, ...]
    risk_image_ids: tuple[str, ...]
    population_image_count: int


def select_sparse_human_audits(
    records: tuple[dict[str, Any], ...],
    *,
    fraction: float,
    minimum: int,
    period_id: str,
) -> AuditSelection:
    """Select before outcomes are known using stable hash ranking, never model confidence."""
    if not 0 < fraction <= 1 or minimum < 0 or not period_id:
        raise ValueError("audit selection policy is invalid")
    required = {"record_id", "image_id", "label", "context", "pipeline_fingerprint"}
    if any(not isinstance(record, dict) or not required <= set(record) for record in records):
        raise ValueError("audit selection record is invalid")
    if len({record["record_id"] for record in records}) != len(records):
        raise ValueError("audit selection record IDs must be unique")
    target = min(len(records), max(minimum, int(len(records) * fraction + 0.999999)))
    ranked = sorted(
        records,
        key=lambda record: hashlib.sha256(
            (
                f"{period_id}:{record['record_id']}:{record['image_id']}:"
                f"{record['label']}:{record['context']}:{record['pipeline_fingerprint']}"
            ).encode()
        ).hexdigest(),
    )
    return AuditSelection(
        tuple(str(record["record_id"]) for record in ranked[:target]),
        len(records),
        target,
        fraction,
        min(minimum, len(records)),
    )


def select_mixed_human_audits(
    records: tuple[dict[str, Any], ...],
    *,
    random_fraction: float,
    minimum_random: int,
    risk_oversample_fraction: float,
    minimum_per_high_risk_bucket: int,
    period_id: str,
) -> MixedAuditSelection:
    """Combine an unbiased deterministic-random sample with risk oversampling."""
    if (
        not 0 < random_fraction <= 1
        or not 0 <= risk_oversample_fraction <= 1
        or minimum_random < 0
        or minimum_per_high_risk_bucket < 1
        or not period_id
    ):
        raise ValueError("mixed audit selection policy is invalid")
    required = {
        "record_id",
        "image_id",
        "label",
        "context",
        "pipeline_fingerprint",
        "risk_bucket",
        "risk_priority",
    }
    if any(not isinstance(record, dict) or not required <= set(record) for record in records):
        raise ValueError("mixed audit selection record is invalid")
    if len({record["record_id"] for record in records}) != len(records):
        raise ValueError("mixed audit selection record IDs must be unique")
    if any(
        not isinstance(record["risk_bucket"], str)
        or not record["risk_bucket"]
        or not isinstance(record["risk_priority"], (int, float))
        or not 0 <= float(record["risk_priority"]) <= 1
        for record in records
    ):
        raise ValueError("mixed audit risk metadata is invalid")

    random_selection = select_sparse_human_audits(
        records,
        fraction=random_fraction,
        minimum=minimum_random,
        period_id=f"{period_id}:random",
    )
    random_ids = set(random_selection.selected_record_ids)

    def rank(record: dict[str, Any], lane: str) -> str:
        return hashlib.sha256(
            f"{period_id}:{lane}:{record['record_id']}:{record['image_id']}".encode()
        ).hexdigest()

    risk_ids: set[str] = set()
    buckets = sorted({str(record["risk_bucket"]) for record in records})
    for bucket in buckets:
        candidates = [record for record in records if record["risk_bucket"] == bucket]
        candidates.sort(key=lambda record: (-float(record["risk_priority"]), rank(record, bucket)))
        target = min(
            len(candidates),
            max(
                minimum_per_high_risk_bucket,
                ceil(len(candidates) * risk_oversample_fraction),
            ),
        )
        risk_ids.update(str(record["record_id"]) for record in candidates[:target])

    ordered = tuple(
        str(record["record_id"])
        for record in sorted(records, key=lambda record: rank(record, "combined"))
        if str(record["record_id"]) in random_ids | risk_ids
    )
    return MixedAuditSelection(
        selected_record_ids=ordered,
        random_record_ids=tuple(sorted(random_ids)),
        risk_record_ids=tuple(sorted(risk_ids)),
        population_count=len(records),
    )


def evaluate_immediate_revocation(
    outcomes: tuple[dict[str, Any], ...],
    *,
    revoke_on_first_serious_false_accept: bool,
) -> tuple[bool, tuple[str, ...]]:
    """Revoke before the next autoaccept when an audited serious failure is found."""
    required = {"record_id", "human_defect", "serious_defect", "distribution_drift"}
    if any(not isinstance(outcome, dict) or set(outcome) != required for outcome in outcomes):
        raise ValueError("audit outcome has the wrong shape")
    if any(
        not isinstance(outcome["human_defect"], bool)
        or not isinstance(outcome["serious_defect"], bool)
        or not isinstance(outcome["distribution_drift"], bool)
        or outcome["serious_defect"] is True
        and outcome["human_defect"] is not True
        for outcome in outcomes
    ):
        raise ValueError("audit outcome booleans are invalid")
    reasons = []
    if revoke_on_first_serious_false_accept and any(
        outcome["serious_defect"] is True for outcome in outcomes
    ):
        reasons.append("serious_false_accept")
    if any(outcome["distribution_drift"] is True for outcome in outcomes):
        reasons.append("distribution_drift")
    return bool(reasons), tuple(reasons)


def select_mixed_multi_person_audits(
    records: tuple[dict[str, Any], ...],
    *,
    random_fraction: float,
    minimum_random: int,
    risk_oversample_fraction: float,
    minimum_per_high_risk_bucket: int,
    period_id: str,
) -> MultiPersonAuditSelection:
    """Select complete multi-person images using mixed pre-outcome sampling."""
    required = {
        "record_id",
        "image_id",
        "instance_id",
        "label",
        "context",
        "pipeline_fingerprint",
        "risk_bucket",
        "risk_priority",
    }
    if any(not isinstance(record, dict) or not required <= set(record) for record in records):
        raise ValueError("multi-person audit selection record is invalid")
    if len({str(record["record_id"]) for record in records}) != len(records):
        raise ValueError("multi-person audit record IDs must be unique")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if record["context"] not in {"duo", "small_group"}:
            raise ValueError("solo evidence cannot enter a multi-person audit queue")
        grouped.setdefault(str(record["image_id"]), []).append(record)
    image_records = []
    for image_id, group in sorted(grouped.items()):
        contexts = {str(row["context"]) for row in group}
        fingerprints = {str(row["pipeline_fingerprint"]) for row in group}
        buckets = {str(row["risk_bucket"]) for row in group}
        instances = {str(row["instance_id"]) for row in group}
        if len(contexts) != 1 or len(fingerprints) != 1 or len(buckets) != 1:
            raise ValueError("one multi-person image cannot span audit strata")
        context = next(iter(contexts))
        expected_count = 2 if context == "duo" else len(instances)
        if instances != {f"p{index}" for index in range(expected_count)} or (
            context == "small_group" and len(instances) < 3
        ):
            raise ValueError("multi-person audit image does not contain a complete pN group")
        fingerprint = next(iter(fingerprints))
        bucket = next(iter(buckets))
        image_records.append(
            {
                "record_id": hashlib.sha256(
                    f"{image_id}:{fingerprint}:{bucket}".encode()
                ).hexdigest(),
                "image_id": image_id,
                "label": "__multi_person_image__",
                "context": context,
                "pipeline_fingerprint": fingerprint,
                "risk_bucket": bucket,
                "risk_priority": max(float(row["risk_priority"]) for row in group),
            }
        )
    selection = select_mixed_human_audits(
        tuple(image_records),
        random_fraction=random_fraction,
        minimum_random=minimum_random,
        risk_oversample_fraction=risk_oversample_fraction,
        minimum_per_high_risk_bucket=minimum_per_high_risk_bucket,
        period_id=period_id,
    )
    by_group_id = {row["record_id"]: row["image_id"] for row in image_records}
    random_images = {by_group_id[record_id] for record_id in selection.random_record_ids}
    risk_images = {by_group_id[record_id] for record_id in selection.risk_record_ids}
    selected_images = random_images | risk_images
    return MultiPersonAuditSelection(
        tuple(
            str(record["record_id"])
            for record in records
            if str(record["image_id"]) in selected_images
        ),
        tuple(sorted(selected_images)),
        tuple(sorted(random_images)),
        tuple(sorted(risk_images)),
        len(image_records),
    )


__all__ = [
    "AuditSelection",
    "MixedAuditSelection",
    "MultiPersonAuditSelection",
    "evaluate_immediate_revocation",
    "select_mixed_human_audits",
    "select_mixed_multi_person_audits",
    "select_sparse_human_audits",
]
