from __future__ import annotations

import copy

import pytest

from maskfactory.steward.campaign_builder import (
    CampaignBuildError,
    CampaignCandidate,
    build_campaigns,
)


def _candidate(
    item_id: str,
    *,
    kind: str = "engineering",
    key: str = "python-steward",
    tokens: int = 100,
    records: int = 1,
    dependencies: tuple[str, ...] = (),
) -> CampaignCandidate:
    suffix = int(item_id.rsplit("-", 1)[-1])
    return CampaignCandidate(
        item_id=item_id,
        work_kind=kind,
        compatibility_key=key,
        payload_sha256=f"{suffix:064x}",
        estimated_context_tokens=tokens,
        record_count=records,
        dependency_ids=dependencies,
    )


def test_engineering_campaign_splits_at_25_without_drops() -> None:
    candidates = [_candidate(f"work-{index}") for index in range(1, 31)]

    result = build_campaigns(
        candidates,
        completed_dependency_ids=(),
        context_token_cap=100_000,
    )

    assert [len(campaign.item_ids) for campaign in result.campaigns] == [25, 5]
    assert result.scheduled_count == 30
    assert result.excluded_count == 0


def test_mask_campaign_splits_at_100_records() -> None:
    candidates = [
        _candidate(
            f"work-{index}",
            kind="mask",
            key="owner-side-policy-v1",
            records=10,
        )
        for index in range(1, 13)
    ]

    result = build_campaigns(
        candidates,
        completed_dependency_ids=(),
        context_token_cap=100_000,
    )

    assert [campaign.total_records for campaign in result.campaigns] == [100, 20]


def test_compatibility_and_context_caps_split_deterministically() -> None:
    candidates = [
        _candidate("work-1", key="a", tokens=60),
        _candidate("work-2", key="a", tokens=60),
        _candidate("work-3", key="b", tokens=10),
    ]

    result = build_campaigns(
        candidates,
        completed_dependency_ids=(),
        context_token_cap=100,
    )

    assert [campaign.item_ids for campaign in result.campaigns] == [
        ("work-1",),
        ("work-2",),
        ("work-3",),
    ]


def test_dependency_and_durable_states_are_accounted_not_silently_dropped() -> None:
    candidates = [
        _candidate("work-1", dependencies=("dep-1",)),
        _candidate("work-2"),
        _candidate("work-3"),
        _candidate("work-4"),
        _candidate("work-5"),
    ]

    result = build_campaigns(
        candidates,
        completed_dependency_ids=(),
        active_item_ids={"work-2"},
        terminal_item_ids={"work-3"},
        ambiguous_item_ids={"work-4"},
        superseded_item_ids={"work-5"},
        context_token_cap=1000,
    )

    assert result.campaigns == ()
    assert dict(result.excluded) == {
        "work-1": "blocked_dependency",
        "work-2": "active",
        "work-3": "terminal",
        "work-4": "ambiguous",
        "work-5": "superseded",
    }
    assert result.input_count == result.excluded_count == 5


def test_oversize_candidate_fails_closed_with_accounting() -> None:
    result = build_campaigns(
        [_candidate("work-1", tokens=101)],
        completed_dependency_ids=(),
        context_token_cap=100,
    )

    assert result.excluded == (("work-1", "context_oversize"),)
    assert result.scheduled_count + result.excluded_count == result.input_count


def test_contradictory_states_and_duplicate_candidates_fail_closed() -> None:
    candidate = _candidate("work-1")
    with pytest.raises(CampaignBuildError, match="contradictory"):
        build_campaigns(
            [candidate],
            completed_dependency_ids=(),
            active_item_ids={"work-1"},
            terminal_item_ids={"work-1"},
            context_token_cap=1000,
        )
    with pytest.raises(CampaignBuildError, match="unique"):
        build_campaigns(
            [candidate, copy.deepcopy(candidate)],
            completed_dependency_ids=(),
            context_token_cap=1000,
        )


def test_identical_inputs_produce_identical_campaign_ids() -> None:
    candidates = [_candidate("work-2"), _candidate("work-1")]
    kwargs = {
        "completed_dependency_ids": (),
        "context_token_cap": 1000,
    }

    first = build_campaigns(copy.deepcopy(candidates), **kwargs)
    second = build_campaigns(copy.deepcopy(candidates), **kwargs)

    assert first == second
