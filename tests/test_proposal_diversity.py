from __future__ import annotations

from copy import deepcopy

import pytest

from maskfactory.providers.proposal_diversity import (
    ProposalDiversityError,
    resolve_proposal_diversity,
)


def _proposal(index: int, family: str, *, lifecycle: str = "promoted") -> dict:
    return {
        "proposal_id": f"proposal-{index}",
        "provider_id": f"provider-{index}",
        "family_id": family,
        "source_sha256": "a" * 64,
        "normalized_mask_sha256": f"{index:x}" * 64,
        "target_contract_sha256": "b" * 64,
        "provider_certificate_sha256": f"{index + 5:x}" * 64,
        "lifecycle": lifecycle,
        "status": "candidate",
    }


def test_three_independent_promoted_families_enable_high_risk_route() -> None:
    result = resolve_proposal_diversity(
        [_proposal(1, "sam"), _proposal(2, "matting"), _proposal(3, "parsing")],
        high_risk=True,
    )
    assert result["status"] == "ready"
    assert result["independent_family_count"] == 3
    assert len(result["route_sha256"]) == 64


def test_correlated_variants_cannot_satisfy_family_count() -> None:
    result = resolve_proposal_diversity(
        [_proposal(1, "sam"), _proposal(2, "sam"), _proposal(3, "sam")],
        high_risk=True,
    )
    assert result["status"] == "abstain"
    assert result["reason"] == "proposal_family_diversity_unavailable"
    assert result["independent_family_count"] == 1


def test_missing_optional_families_produces_typed_abstention() -> None:
    result = resolve_proposal_diversity(
        [_proposal(1, "sam"), _proposal(2, "matting")], high_risk=True
    )
    assert result["status"] == "abstain"
    assert result["eligible_proposal_ids"] == ["proposal-1", "proposal-2"]


def test_low_risk_route_can_use_available_promoted_evidence_without_inflation() -> None:
    result = resolve_proposal_diversity([_proposal(1, "sam")], high_risk=False)
    assert result["status"] == "ready"
    assert result["independent_family_ids"] == ["sam"]


def test_unpromoted_or_failed_candidates_never_count() -> None:
    installed = _proposal(2, "matting", lifecycle="installed")
    failed = _proposal(3, "parsing")
    failed["status"] = "failed"
    result = resolve_proposal_diversity([_proposal(1, "sam"), installed, failed], high_risk=True)
    assert result["status"] == "abstain"
    assert result["independent_family_ids"] == ["sam"]


def test_no_eligible_candidate_is_typed_abstention() -> None:
    result = resolve_proposal_diversity([], high_risk=True)
    assert result["status"] == "abstain"
    assert result["reason"] == "no_eligible_promoted_proposals"


@pytest.mark.parametrize("field", ["source_sha256", "target_contract_sha256"])
def test_source_or_target_drift_fails_closed(field: str) -> None:
    proposals = [_proposal(1, "sam"), _proposal(2, "matting"), _proposal(3, "parsing")]
    proposals[2][field] = "f" * 64
    with pytest.raises(ProposalDiversityError, match="source and target identity"):
        resolve_proposal_diversity(proposals, high_risk=True)


def test_duplicate_candidate_bytes_are_rejected() -> None:
    proposals = [_proposal(1, "sam"), _proposal(2, "matting")]
    proposals[1]["normalized_mask_sha256"] = proposals[0]["normalized_mask_sha256"]
    with pytest.raises(ProposalDiversityError, match="duplicated"):
        resolve_proposal_diversity(proposals, high_risk=True)


def test_missing_provenance_field_is_rejected() -> None:
    proposal = deepcopy(_proposal(1, "sam"))
    del proposal["provider_certificate_sha256"]
    with pytest.raises(ProposalDiversityError, match="fields are incomplete"):
        resolve_proposal_diversity([proposal], high_risk=False)
