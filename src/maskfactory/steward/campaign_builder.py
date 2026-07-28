"""Deterministic, lossless campaign batching for continuous autonomy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable

CAMPAIGN_KINDS = frozenset({"engineering", "mask"})
ACTIONABLE_STATUSES = frozenset({"open", "in_progress", "partially_complete", "failed"})


class CampaignBuildError(ValueError):
    """Campaign input or durable state is contradictory."""


@dataclass(frozen=True)
class CampaignCandidate:
    item_id: str
    work_kind: str
    compatibility_key: str
    payload_sha256: str
    estimated_context_tokens: int
    record_count: int = 1
    dependency_ids: tuple[str, ...] = ()
    status: str = "open"


@dataclass(frozen=True)
class CampaignBatch:
    campaign_id: str
    work_kind: str
    compatibility_key: str
    item_ids: tuple[str, ...]
    payload_sha256s: tuple[str, ...]
    total_context_tokens: int
    total_records: int


@dataclass(frozen=True)
class CampaignBuildResult:
    campaigns: tuple[CampaignBatch, ...]
    excluded: tuple[tuple[str, str], ...]
    input_count: int
    scheduled_count: int
    excluded_count: int


def _validate_candidate(candidate: CampaignCandidate) -> None:
    if candidate.work_kind not in CAMPAIGN_KINDS:
        raise CampaignBuildError(f"{candidate.item_id}: invalid work kind")
    if not candidate.item_id or not candidate.compatibility_key:
        raise CampaignBuildError("candidate identities must be non-empty")
    if len(candidate.payload_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in candidate.payload_sha256
    ):
        raise CampaignBuildError(f"{candidate.item_id}: invalid payload SHA-256")
    if candidate.estimated_context_tokens <= 0 or candidate.record_count <= 0:
        raise CampaignBuildError(
            f"{candidate.item_id}: resource estimates must be positive"
        )
    if len(candidate.dependency_ids) != len(set(candidate.dependency_ids)):
        raise CampaignBuildError(f"{candidate.item_id}: duplicate dependencies")


def _campaign_id(
    work_kind: str,
    compatibility_key: str,
    candidates: list[CampaignCandidate],
) -> str:
    canonical = json.dumps(
        {
            "work_kind": work_kind,
            "compatibility_key": compatibility_key,
            "items": [
                {
                    "item_id": candidate.item_id,
                    "payload_sha256": candidate.payload_sha256,
                    "record_count": candidate.record_count,
                    "estimated_context_tokens": candidate.estimated_context_tokens,
                }
                for candidate in candidates
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return f"{work_kind}-campaign-{digest[:20]}"


def build_campaigns(
    candidates: Iterable[CampaignCandidate],
    *,
    completed_dependency_ids: Iterable[str],
    active_item_ids: Iterable[str] = (),
    terminal_item_ids: Iterable[str] = (),
    ambiguous_item_ids: Iterable[str] = (),
    superseded_item_ids: Iterable[str] = (),
    context_token_cap: int,
    engineering_mission_cap: int = 25,
    mask_record_cap: int = 100,
) -> CampaignBuildResult:
    """Build compatible bounded campaigns with complete input accounting."""

    if context_token_cap <= 0 or engineering_mission_cap <= 0 or mask_record_cap <= 0:
        raise CampaignBuildError("campaign caps must be positive")
    rows = list(candidates)
    if len({candidate.item_id for candidate in rows}) != len(rows):
        raise CampaignBuildError("candidate item IDs must be unique")
    for candidate in rows:
        _validate_candidate(candidate)

    durable_sets = {
        "active": frozenset(active_item_ids),
        "terminal": frozenset(terminal_item_ids),
        "ambiguous": frozenset(ambiguous_item_ids),
        "superseded": frozenset(superseded_item_ids),
    }
    names = list(durable_sets)
    for index, left_name in enumerate(names):
        for right_name in names[index + 1 :]:
            overlap = durable_sets[left_name].intersection(durable_sets[right_name])
            if overlap:
                raise CampaignBuildError(
                    "contradictory durable state for " + ", ".join(sorted(overlap))
                )
    completed = frozenset(completed_dependency_ids)
    excluded: list[tuple[str, str]] = []
    eligible: list[CampaignCandidate] = []
    for candidate in sorted(
        rows, key=lambda row: (row.work_kind, row.compatibility_key, row.item_id)
    ):
        reason = None
        for state_name, item_ids in durable_sets.items():
            if candidate.item_id in item_ids:
                reason = state_name
                break
        if reason is None and candidate.status not in ACTIONABLE_STATUSES:
            reason = f"status:{candidate.status}"
        if reason is None and not set(candidate.dependency_ids).issubset(completed):
            reason = "blocked_dependency"
        if reason is None and candidate.estimated_context_tokens > context_token_cap:
            reason = "context_oversize"
        if reason is None and (
            candidate.work_kind == "mask" and candidate.record_count > mask_record_cap
        ):
            reason = "record_oversize"
        if reason is not None:
            excluded.append((candidate.item_id, reason))
        else:
            eligible.append(candidate)

    campaigns: list[CampaignBatch] = []
    current: list[CampaignCandidate] = []
    current_key: tuple[str, str] | None = None

    def flush() -> None:
        nonlocal current, current_key
        if not current or current_key is None:
            return
        work_kind, compatibility_key = current_key
        campaigns.append(
            CampaignBatch(
                campaign_id=_campaign_id(work_kind, compatibility_key, current),
                work_kind=work_kind,
                compatibility_key=compatibility_key,
                item_ids=tuple(candidate.item_id for candidate in current),
                payload_sha256s=tuple(
                    candidate.payload_sha256 for candidate in current
                ),
                total_context_tokens=sum(
                    candidate.estimated_context_tokens for candidate in current
                ),
                total_records=sum(candidate.record_count for candidate in current),
            )
        )
        current = []
        current_key = None

    for candidate in eligible:
        key = (candidate.work_kind, candidate.compatibility_key)
        candidate_units = candidate.record_count if candidate.work_kind == "mask" else 1
        current_units = sum(
            row.record_count if row.work_kind == "mask" else 1 for row in current
        )
        unit_cap = (
            mask_record_cap
            if candidate.work_kind == "mask"
            else engineering_mission_cap
        )
        would_exceed = bool(
            current
            and (
                key != current_key
                or current_units + candidate_units > unit_cap
                or sum(row.estimated_context_tokens for row in current)
                + candidate.estimated_context_tokens
                > context_token_cap
            )
        )
        if would_exceed:
            flush()
        if not current:
            current_key = key
        current.append(candidate)
    flush()

    scheduled_count = sum(len(campaign.item_ids) for campaign in campaigns)
    result = CampaignBuildResult(
        campaigns=tuple(campaigns),
        excluded=tuple(sorted(excluded)),
        input_count=len(rows),
        scheduled_count=scheduled_count,
        excluded_count=len(excluded),
    )
    if result.scheduled_count + result.excluded_count != result.input_count:
        raise CampaignBuildError("campaign accounting did not reconcile")
    return result


__all__ = [
    "CampaignBatch",
    "CampaignBuildError",
    "CampaignBuildResult",
    "CampaignCandidate",
    "build_campaigns",
]
