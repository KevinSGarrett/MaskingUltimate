"""Focused producer tests for MF-P6-12.04 Mode B vertical slice."""

from __future__ import annotations

from pathlib import Path

import pytest

from maskfactory.bridge.mode_b_localhost_client import ModeBLocalhostClient
from maskfactory.bridge.mode_b_vertical_slice import (
    ModeBVerticalSliceError,
    build_fixture_mode_b_transport,
    evaluate_refinement_authority_ceiling,
    prove_service_down_behavior,
    reject_draft_self_promotion,
    run_mode_b_draft_actions,
    run_mode_b_vertical_slice,
    submit_exact_prediction_certification_transaction,
    validate_mode_b_vertical_slice_evidence,
)
from maskfactory.bridge.runtime_client_types import ERROR_SERVICE_UNAVAILABLE
from maskfactory.validation import schema_validator


def test_schema_registry_loads_mode_b_vertical_slice_evidence() -> None:
    assert schema_validator("mode_b_vertical_slice_evidence")


def test_draft_actions_are_closed_and_non_promotable() -> None:
    client = ModeBLocalhostClient(transport=build_fixture_mode_b_transport())
    draft = run_mode_b_draft_actions(client)
    assert draft["all_draft_only"] is True
    assert draft["promotion_eligible_any"] is False
    for action in ("health", "capability", "predict", "refine"):
        assert draft["actions"][action]["status"] == "ok"
        assert draft["actions"][action]["authority_state"] == "draft"
        assert draft["actions"][action]["promotion_eligible"] is False
    assert draft["predict_request_sha256"]
    assert draft["predict_raw_response_sha256"]
    assert draft["predict_mask_bytes_sha256"]


def test_service_down_is_typed_and_failure_control_blocks_provider() -> None:
    evidence = prove_service_down_behavior(decided_at="2026-07-19T12:05:00Z")
    assert evidence["client_typed"] is True
    assert evidence["client_error_code"] == ERROR_SERVICE_UNAVAILABLE
    assert evidence["failure_control_status"] == "accepted"
    assert evidence["failure_control_fault_kind"] == "outage"
    assert evidence["provider_invocation_permitted"] is False
    assert evidence["no_silent_fallback"] is True


def test_draft_cannot_self_promote() -> None:
    client = ModeBLocalhostClient(transport=build_fixture_mode_b_transport())
    draft = run_mode_b_draft_actions(client)
    refusal = reject_draft_self_promotion(draft["responses"]["predict"])
    assert refusal["attempted"] is True
    assert refusal["rejected"] is True
    assert refusal["certificate_issued"] is False
    assert "self_promotion_attempted" in refusal["reason_codes"]


def test_refinement_cannot_inflate_parent_authority() -> None:
    ceiling = evaluate_refinement_authority_ceiling(
        parent_authority_state="draft",
        claimed_descendant_authority_state="certified",
    )
    assert ceiling["inflation_attempted"] is True
    assert ceiling["inflation_rejected"] is True
    assert ceiling["descendant_authority_state"] == "draft"
    assert ceiling["descendant_requires_own_wrapper"] is True


def test_independent_certification_binds_exact_prediction_and_abstains_on_veto(
    tmp_path: Path,
) -> None:
    client = ModeBLocalhostClient(transport=build_fixture_mode_b_transport())
    draft = run_mode_b_draft_actions(client)
    result = submit_exact_prediction_certification_transaction(
        draft_prediction={
            "predict_raw_response_sha256": draft["predict_raw_response_sha256"],
            "predict_mask_bytes_sha256": draft["predict_mask_bytes_sha256"],
        },
        workdir=tmp_path / "cert",
    )
    assert result["transaction_kind"] == "independent_operational_certification"
    assert result["independent_from_draft_path"] is True
    assert result["exact_original_prediction_bound"] is True
    assert result["certified_branch"]["outcome"] == "certified"
    assert result["certified_branch"]["complete_evidence"] is True
    assert result["certified_branch"]["certificate_payload_sha256"]
    assert result["abstained_branch"]["outcome"] == "abstained"
    assert result["abstained_branch"]["complete_evidence"] is True
    assert result["abstained_branch"]["certificate_payload_sha256"] is None


def test_self_promotion_flag_is_hard_rejected(tmp_path: Path) -> None:
    with pytest.raises(ModeBVerticalSliceError, match="self_promotion_forbidden"):
        submit_exact_prediction_certification_transaction(
            draft_prediction={
                "predict_raw_response_sha256": "0" * 64,
                "predict_mask_bytes_sha256": "1" * 64,
            },
            workdir=tmp_path,
            allow_self_promotion_from_draft=True,
        )


def test_full_producer_slice_is_partial_with_honest_blockers(tmp_path: Path) -> None:
    evidence = run_mode_b_vertical_slice(tmp_path / "slice")
    issues = validate_mode_b_vertical_slice_evidence(evidence)
    assert issues == ()
    assert evidence["status"] == "producer_partial"
    assert evidence["claim_boundary"]["producer_fixture_slice_complete"] is True
    assert evidence["claim_boundary"]["live_gpu_champion_complete"] is False
    assert evidence["claim_boundary"]["windows_loopback_complete"] is False
    assert evidence["claim_boundary"]["mf_p6_12_04_complete"] is False
    assert evidence["live_probe"]["champion_backed_live_prediction"] is False
    assert evidence["live_probe"]["live_service_used"] is False
    assert "champion_backed_prediction_absent" in evidence["rejection_reasons"]
    assert evidence["draft_runtime"]["all_draft_only"] is True
    assert evidence["service_down"]["client_typed"] is True
    assert evidence["self_promotion"]["rejected"] is True
    assert evidence["certification_transaction"]["certified_branch"]["outcome"] == "certified"
    assert evidence["certification_transaction"]["abstained_branch"]["outcome"] == "abstained"
    assert evidence["refinement_authority"]["inflation_rejected"] is True
