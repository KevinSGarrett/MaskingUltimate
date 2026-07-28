"""Exact proposal-family diversity routing for high-risk autonomous masks."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from maskfactory.vlm.critic_catalog import canonical_sha256

SHA256 = re.compile(r"^[a-f0-9]{64}$")
PROPOSAL_KEYS = frozenset(
    {
        "proposal_id",
        "provider_id",
        "family_id",
        "source_sha256",
        "normalized_mask_sha256",
        "target_contract_sha256",
        "provider_certificate_sha256",
        "lifecycle",
        "status",
    }
)


class ProposalDiversityError(ValueError):
    """Proposal provenance is malformed, duplicated, or internally inconsistent."""


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ProposalDiversityError(f"{field} must be a SHA-256")
    return value


def _validate_proposal(proposal: Mapping[str, Any]) -> None:
    if set(proposal) != PROPOSAL_KEYS:
        raise ProposalDiversityError("proposal fields are incomplete or unknown")
    for field in ("proposal_id", "provider_id", "family_id"):
        if not isinstance(proposal[field], str) or not proposal[field].strip():
            raise ProposalDiversityError(f"proposal {field} is empty")
    for field in (
        "source_sha256",
        "normalized_mask_sha256",
        "target_contract_sha256",
        "provider_certificate_sha256",
    ):
        _sha256(proposal[field], field)
    if proposal["lifecycle"] not in {"planned", "installed", "smoked", "promoted", "revoked"}:
        raise ProposalDiversityError("proposal lifecycle is invalid")
    if proposal["status"] not in {"candidate", "failed", "abstained"}:
        raise ProposalDiversityError("proposal status is invalid")


def resolve_proposal_diversity(
    proposals: Sequence[Mapping[str, Any]],
    *,
    high_risk: bool,
    required_independent_families: int = 3,
) -> dict[str, Any]:
    """Return a hash-bound route or typed abstention without inflating variants."""

    if isinstance(proposals, (str, bytes)) or not isinstance(proposals, Sequence):
        raise ProposalDiversityError("proposals must be a sequence")
    if required_independent_families < 1:
        raise ProposalDiversityError("required family count must be positive")
    proposal_ids: set[str] = set()
    mask_hashes: set[str] = set()
    for proposal in proposals:
        if not isinstance(proposal, Mapping):
            raise ProposalDiversityError("proposal must be an object")
        _validate_proposal(proposal)
        proposal_id = str(proposal["proposal_id"])
        mask_hash = str(proposal["normalized_mask_sha256"])
        if proposal_id in proposal_ids or mask_hash in mask_hashes:
            raise ProposalDiversityError("proposal ID or normalized mask is duplicated")
        proposal_ids.add(proposal_id)
        mask_hashes.add(mask_hash)

    eligible = [
        proposal
        for proposal in proposals
        if proposal["status"] == "candidate" and proposal["lifecycle"] == "promoted"
    ]
    source_hashes = {proposal["source_sha256"] for proposal in eligible}
    target_hashes = {proposal["target_contract_sha256"] for proposal in eligible}
    if len(source_hashes) > 1 or len(target_hashes) > 1:
        raise ProposalDiversityError("eligible proposals do not share source and target identity")
    families = sorted({str(proposal["family_id"]) for proposal in eligible})
    candidate_ids = sorted(str(proposal["proposal_id"]) for proposal in eligible)
    core = {
        "schema_version": "1.0.0",
        "high_risk": bool(high_risk),
        "required_independent_families": required_independent_families,
        "independent_family_count": len(families),
        "independent_family_ids": families,
        "eligible_proposal_ids": candidate_ids,
        "source_sha256": next(iter(source_hashes), None),
        "target_contract_sha256": next(iter(target_hashes), None),
    }
    if not eligible:
        result = core | {"status": "abstain", "reason": "no_eligible_promoted_proposals"}
    elif high_risk and len(families) < required_independent_families:
        result = core | {"status": "abstain", "reason": "proposal_family_diversity_unavailable"}
    else:
        result = core | {"status": "ready", "reason": None}
    result["route_sha256"] = canonical_sha256(result)
    return result
