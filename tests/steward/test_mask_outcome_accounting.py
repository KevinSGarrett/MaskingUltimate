from __future__ import annotations

import copy
import hashlib
import json

import pytest

from maskfactory.steward.mask_outcome_accounting import (
    MaskOutcomeAccountingError,
    build_terminal_mask_record,
    reconcile_mask_outcome_campaign,
    validate_mask_outcome_campaign,
)

ZERO_SHA256 = "0" * 64


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _input(index: int) -> dict[str, str]:
    return {
        "record_id": f"record-{index:03d}",
        "input_sha256": _digest(f"input-{index}"),
    }


def _terminal(index: int, outcome: str) -> dict:
    input_record = _input(index)
    parent = _digest(f"parent-{index}")
    final = _digest(f"final-{index}")
    visual_sha = _digest(f"visual-{index}")
    common = {
        "record_id": input_record["record_id"],
        "input_sha256": input_record["input_sha256"],
        "parent_mask_sha256": parent,
        "hard_qa_result_sha256": _digest(f"hard-qa-{index}"),
        "authority_claimed": False,
        "promotion_claimed": False,
    }
    if outcome == "accept":
        return build_terminal_mask_record(
            **common,
            final_mask_sha256=final,
            hard_qa_outcome="PASS",
            visual_quorum_sha256=visual_sha,
            visual_outcome="VISUAL_QA_PASS_BOUNDED",
            repair_result_sha256s=[],
            terminal_outcome="accept",
            reason_code="bounded_visual_quorum_pass",
        )
    if outcome == "repair":
        return build_terminal_mask_record(
            **common,
            final_mask_sha256=final,
            hard_qa_outcome="PASS_AFTER_REPAIR",
            visual_quorum_sha256=visual_sha,
            visual_outcome="ABSTAIN_VISUAL_DISAGREEMENT",
            repair_result_sha256s=[_digest(f"repair-{index}")],
            terminal_outcome="repair",
            reason_code="additional_bounded_repair_required",
        )
    if outcome == "reject":
        return build_terminal_mask_record(
            **common,
            final_mask_sha256=None,
            hard_qa_outcome="VETO",
            visual_quorum_sha256=None,
            visual_outcome=None,
            repair_result_sha256s=[],
            terminal_outcome="reject",
            reason_code="hard_qa_veto",
        )
    if outcome == "quarantine":
        return build_terminal_mask_record(
            **common,
            final_mask_sha256=final,
            hard_qa_outcome="PASS",
            visual_quorum_sha256=visual_sha,
            visual_outcome="VISUAL_CRITIC_BLOCKED",
            repair_result_sha256s=[],
            terminal_outcome="quarantine",
            reason_code="critic_evidence_unavailable",
        )
    return build_terminal_mask_record(
        **common,
        final_mask_sha256=final,
        hard_qa_outcome="PASS",
        visual_quorum_sha256=visual_sha,
        visual_outcome="ABSTAIN_VISUAL_DISAGREEMENT",
        repair_result_sha256s=[],
        terminal_outcome="abstain",
        reason_code="visual_roles_disagreed",
    )


def _campaign() -> tuple[list[dict], list[dict]]:
    inputs = [_input(index) for index in range(100)]
    outcomes = ("accept", "repair", "abstain", "reject", "quarantine")
    terminals = [
        _terminal(index, outcomes[index % len(outcomes)]) for index in range(100)
    ]
    return inputs, terminals


def _reseal(value: dict, field: str) -> dict:
    value = copy.deepcopy(value)
    value[field] = ZERO_SHA256
    value[field] = hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    return value


def test_100_record_campaign_reconciles_every_terminal_outcome() -> None:
    inputs, terminals = _campaign()

    result = reconcile_mask_outcome_campaign(
        campaign_id="campaign-100",
        inputs=inputs,
        terminal_records=terminals,
    )

    assert result["input_count"] == 100
    assert result["terminal_record_count"] == 100
    assert result["outcome_counts"] == {
        "accept": 20,
        "repair": 20,
        "abstain": 20,
        "reject": 20,
        "quarantine": 20,
    }
    assert result["zero_loss"] is True
    assert result["zero_duplicate_promotion"] is True
    assert result["complete_accounting"] is True
    assert result["authority_granted"] is False
    validate_mask_outcome_campaign(
        result,
        inputs=inputs,
        terminal_records=terminals,
    )


def test_missing_terminal_record_fails_closed() -> None:
    inputs, terminals = _campaign()

    with pytest.raises(MaskOutcomeAccountingError, match="count mismatch"):
        reconcile_mask_outcome_campaign(
            campaign_id="campaign-100",
            inputs=inputs,
            terminal_records=terminals[:-1],
        )


def test_duplicate_terminal_record_fails_closed() -> None:
    inputs, terminals = _campaign()
    terminals[-1] = terminals[0]

    with pytest.raises(MaskOutcomeAccountingError, match="duplicate terminal"):
        reconcile_mask_outcome_campaign(
            campaign_id="campaign-100",
            inputs=inputs,
            terminal_records=terminals,
        )


def test_input_binding_drift_fails_closed() -> None:
    inputs, terminals = _campaign()
    inputs[5]["input_sha256"] = _digest("drift")

    with pytest.raises(MaskOutcomeAccountingError, match="input binding mismatch"):
        reconcile_mask_outcome_campaign(
            campaign_id="campaign-100",
            inputs=inputs,
            terminal_records=terminals,
        )


def test_accept_requires_hard_qa_and_visual_pass() -> None:
    with pytest.raises(MaskOutcomeAccountingError, match="accept requires"):
        build_terminal_mask_record(
            record_id="record-000",
            input_sha256=_digest("input"),
            parent_mask_sha256=_digest("parent"),
            final_mask_sha256=_digest("final"),
            hard_qa_result_sha256=_digest("hard-qa"),
            hard_qa_outcome="VETO",
            visual_quorum_sha256=_digest("visual"),
            visual_outcome="VISUAL_QA_PASS_BOUNDED",
            repair_result_sha256s=[],
            terminal_outcome="accept",
            reason_code="invalid_accept",
        )


def test_repair_requires_distinct_mask_and_repair_evidence() -> None:
    parent = _digest("parent")

    with pytest.raises(MaskOutcomeAccountingError, match="repair requires"):
        build_terminal_mask_record(
            record_id="record-000",
            input_sha256=_digest("input"),
            parent_mask_sha256=parent,
            final_mask_sha256=parent,
            hard_qa_result_sha256=_digest("hard-qa"),
            hard_qa_outcome="PASS_AFTER_REPAIR",
            visual_quorum_sha256=_digest("visual"),
            visual_outcome="ABSTAIN_VISUAL_DISAGREEMENT",
            repair_result_sha256s=[],
            terminal_outcome="repair",
            reason_code="invalid_repair",
        )


def test_terminal_record_cannot_claim_promotion_or_authority() -> None:
    with pytest.raises(MaskOutcomeAccountingError, match="claim authority"):
        build_terminal_mask_record(
            record_id="record-000",
            input_sha256=_digest("input"),
            parent_mask_sha256=_digest("parent"),
            final_mask_sha256=_digest("final"),
            hard_qa_result_sha256=_digest("hard-qa"),
            hard_qa_outcome="PASS",
            visual_quorum_sha256=_digest("visual"),
            visual_outcome="VISUAL_QA_PASS_BOUNDED",
            repair_result_sha256s=[],
            terminal_outcome="accept",
            reason_code="invalid_authority",
            authority_claimed=True,
        )


def test_rehashed_campaign_semantic_drift_is_rejected() -> None:
    inputs, terminals = _campaign()
    result = reconcile_mask_outcome_campaign(
        campaign_id="campaign-100",
        inputs=inputs,
        terminal_records=terminals,
    )
    tampered = copy.deepcopy(result)
    tampered["outcome_counts"]["accept"] = 100
    tampered = _reseal(tampered, "campaign_sha256")

    with pytest.raises(MaskOutcomeAccountingError, match="replay mismatch"):
        validate_mask_outcome_campaign(
            tampered,
            inputs=inputs,
            terminal_records=terminals,
        )
