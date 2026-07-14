"""Deterministic sparse audit sampling and immediate autonomy-certificate revocation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AuditSelection:
    selected_record_ids: tuple[str, ...]
    population_count: int
    selected_count: int
    fraction: float
    minimum_applied: int


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


__all__ = ["AuditSelection", "evaluate_immediate_revocation", "select_sparse_human_audits"]
