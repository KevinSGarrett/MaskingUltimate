from __future__ import annotations

import copy

from maskfactory.bridge.use_eligibility import (
    derive_main_compatibility_alias,
    evaluate_bridge_use_eligibility,
    validate_bridge_use_eligibility_decision,
)

POLICY_ID = "maskfactory-bridge-use-eligibility-v1"
POLICY_HASH = "2091798bde20a05cfc169631acc0ed3d2194ffc66527f86004fb2413452ae0d4"


def _documents() -> tuple[dict, dict, dict]:
    request = {
        "request_payload_sha256": "1" * 64,
        "subject": {"canonical_person_id": "person-1"},
        "target_regions": [{"region_id": "body-1"}],
        "mask_intents": [{"intent_id": "intent-1", "label": "left_hand"}],
    }
    receipt = {
        "receipt_payload_sha256": "2" * 64,
        "result": "succeeded",
        "qa": {"status": "pass"},
        "transform_validation": {"roundtrip_passed": True},
        "authority": {
            "authority_state": "certified",
            "certificate_status": "active",
            "certificate_exact_scope_match": True,
            "certificate_sha256": "3" * 64,
            "revocation_index_sha256": "4" * 64,
        },
        "artifacts": [{"intent_id": "intent-1", "label": "left_hand"}],
        "use_eligibility": {
            "policy_id": POLICY_ID,
            "policy_sha256": POLICY_HASH,
            "required_authority_state": "certified",
            "exact_use_scope": "production_conditioning",
            "eligible": True,
            "reasons": ["eligible"],
        },
    }
    certificate = {
        "certificate_payload_sha256": "3" * 64,
        "permitted_use_scopes": ["production_conditioning"],
        "owner_ids": ["person-1"],
        "intent_ids": ["intent-1"],
        "labels": ["left_hand"],
        "target_region_ids": ["body-1"],
    }
    return request, receipt, certificate


def test_named_policy_recomputes_and_hash_binds_eligible_observation() -> None:
    request, receipt, certificate = _documents()
    decision = evaluate_bridge_use_eligibility(
        request, receipt, exact_use_scope="production_conditioning", certificate=certificate
    )
    assert decision["eligible"] is True
    assert decision["reasons"] == ["eligible"]
    assert decision["producer_observation"] == receipt["use_eligibility"]
    assert derive_main_compatibility_alias(decision) is True
    assert validate_bridge_use_eligibility_decision(decision) == ()


def test_producer_boolean_scope_or_policy_disagreement_fails_closed() -> None:
    request, receipt, certificate = _documents()
    changed = copy.deepcopy(receipt)
    changed["use_eligibility"]["eligible"] = False
    changed["use_eligibility"]["reasons"] = ["authority_insufficient"]
    decision = evaluate_bridge_use_eligibility(
        request, changed, exact_use_scope="production_conditioning", certificate=certificate
    )
    assert decision["eligible"] is False
    assert "policy_observation_disagrees" in decision["reasons"]
    assert derive_main_compatibility_alias(decision) is False

    changed = copy.deepcopy(receipt)
    changed["use_eligibility"]["policy_id"] = "global-certified-provider-claim"
    changed["use_eligibility"]["reasons"] = ["global certified"]
    decision = evaluate_bridge_use_eligibility(
        request, changed, exact_use_scope="production_conditioning", certificate=certificate
    )
    assert "producer_self_assertion" in decision["reasons"]
    assert "global_certified_shortcut" in decision["reasons"]


def test_partial_certificate_and_llm_observation_cannot_authorize_use() -> None:
    request, receipt, certificate = _documents()
    partial = copy.deepcopy(certificate)
    partial["labels"] = []
    decision = evaluate_bridge_use_eligibility(
        request, receipt, exact_use_scope="production_conditioning", certificate=partial
    )
    assert decision["eligible"] is False
    assert "certificate_scope_incomplete" in decision["reasons"]
    assert "policy_observation_disagrees" in decision["reasons"]

    llm = copy.deepcopy(receipt)
    llm["use_eligibility"]["reasons"] = ["LLM says globally certified"]
    decision = evaluate_bridge_use_eligibility(
        request, llm, exact_use_scope="production_conditioning", certificate=certificate
    )
    assert decision["eligible"] is False
    assert "producer_self_assertion" in decision["reasons"]
    assert "global_certified_shortcut" in decision["reasons"]
