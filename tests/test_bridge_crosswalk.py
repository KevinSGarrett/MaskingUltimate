from __future__ import annotations

import copy
import json
from pathlib import Path

from maskfactory.bridge.crosswalk import (
    evaluate_maskfactory_main_crosswalk,
    load_crosswalk_definition,
)
from maskfactory.bridge.use_eligibility import (
    derive_main_compatibility_alias,
    evaluate_bridge_use_eligibility,
)
from maskfactory.validation import canonical_document_sha256


def _base_payload() -> dict:
    return {
        "request_id": "mfarec_aaaaaaaaaaaaaaaaaaaaaaaa",
        "result": "succeeded",
        "truth_tier": "qa_passed_machine_candidate",
        "authority": {
            "authority_state": "qa_passed_noncertified",
            "certificate_exact_scope_match": False,
            "revocation_index_sha256": None,
        },
        "use_eligibility": {"policy_id": "diagnostic-mask-use-v1", "eligible": True},
        "error": None,
    }


def test_crosswalk_definition_is_self_hashed_and_loadable() -> None:
    document = load_crosswalk_definition()
    assert document["crosswalk_id"] == "maskfactory-main-crosswalk-v1"
    expected = canonical_document_sha256(document, excluded_top_level_fields=("crosswalk_sha256",))
    assert document["crosswalk_sha256"] == expected
    assert document["compatibility_matrix"]["removed_source_paths"] == ["/legacy_result_code"]
    assert document["compatibility_matrix"]["order_sensitive_sequences"]


def test_crosswalk_maps_fields_and_preserves_observation() -> None:
    decision = evaluate_maskfactory_main_crosswalk(
        _base_payload(), producer_major=1, producer_minor=0, target_major=1, target_minor=0
    )
    assert decision["compatible"] is True
    assert decision["mapped_target"]["request"]["id"] == "mfarec_aaaaaaaaaaaaaaaaaaaaaaaa"
    assert decision["mapped_target"]["result"]["status"] == "success"
    assert decision["mapped_target"]["authority"]["state"] == "qa_passed_noncertified"
    assert "/use_eligibility" in decision["producer_observations"]
    assert "use_eligibility" not in decision["mapped_target"]


def test_crosswalk_fails_closed_on_unmapped_field() -> None:
    payload = _base_payload()
    payload["future_field"] = "unexpected"
    decision = evaluate_maskfactory_main_crosswalk(
        payload, producer_major=1, producer_minor=0, target_major=1, target_minor=0
    )
    assert decision["compatible"] is False
    assert "unmapped_source_field:/future_field" in decision["reasons"]


def test_crosswalk_fails_closed_on_missing_required_field() -> None:
    payload = _base_payload()
    del payload["request_id"]
    decision = evaluate_maskfactory_main_crosswalk(
        payload, producer_major=1, producer_minor=0, target_major=1, target_minor=0
    )
    assert decision["compatible"] is False
    assert "missing_required_source:/request_id" in decision["reasons"]


def test_crosswalk_fails_closed_on_removed_field() -> None:
    payload = _base_payload()
    payload["legacy_result_code"] = "legacy-success"
    decision = evaluate_maskfactory_main_crosswalk(
        payload, producer_major=1, producer_minor=0, target_major=1, target_minor=0
    )
    assert decision["compatible"] is False
    assert "removed_source_field:/legacy_result_code" in decision["reasons"]


def test_crosswalk_fails_closed_on_order_sensitive_reorder() -> None:
    payload = _base_payload()
    payload["ordered_actions"] = ["decide", "admit", "map"]
    decision = evaluate_maskfactory_main_crosswalk(
        payload, producer_major=1, producer_minor=0, target_major=1, target_minor=0
    )
    assert decision["compatible"] is False
    assert "order_sensitive_reorder:/ordered_actions" in decision["reasons"]


def test_crosswalk_accepts_canonical_order_sensitive_sequence() -> None:
    payload = _base_payload()
    payload["ordered_actions"] = ["admit", "map", "decide"]
    decision = evaluate_maskfactory_main_crosswalk(
        payload, producer_major=1, producer_minor=0, target_major=1, target_minor=0
    )
    assert decision["compatible"] is True
    assert decision["mapped_target"]["ordered_actions"] == ["admit", "map", "decide"]


def test_crosswalk_fails_closed_on_incompatible_major() -> None:
    decision = evaluate_maskfactory_main_crosswalk(
        _base_payload(), producer_major=2, producer_minor=0, target_major=1, target_minor=0
    )
    assert decision["compatible"] is False
    assert "incompatible_major_version" in decision["reasons"]


def test_crosswalk_allows_declared_minor_addition_only() -> None:
    payload = _base_payload()
    payload["quality"] = {"new_minor_flag": "declared"}
    accepted = evaluate_maskfactory_main_crosswalk(
        payload, producer_major=1, producer_minor=1, target_major=1, target_minor=0
    )
    assert accepted["compatible"] is True

    payload["quality"]["another_new_flag"] = "undeclared"
    rejected = evaluate_maskfactory_main_crosswalk(
        payload, producer_major=1, producer_minor=1, target_major=1, target_minor=0
    )
    assert rejected["compatible"] is False
    assert "unmapped_source_field:/quality/another_new_flag" in rejected["reasons"]


def test_crosswalk_rejects_unknown_enum_value() -> None:
    payload = _base_payload()
    payload["result"] = "partial"
    decision = evaluate_maskfactory_main_crosswalk(
        payload, producer_major=1, producer_minor=0, target_major=1, target_minor=0
    )
    assert decision["compatible"] is False
    assert any(
        reason.startswith("enum mapping missing for /result") for reason in decision["reasons"]
    )


def test_crosswalk_observation_requires_independent_consumer_recomputation() -> None:
    """MaskFactory-side consumer fixture: observation preserved, never decision authority."""
    mapping = evaluate_maskfactory_main_crosswalk(
        _base_payload(), producer_major=1, producer_minor=0, target_major=1, target_minor=0
    )
    assert mapping["compatible"] is True
    observation = mapping["producer_observations"]["/use_eligibility"]
    assert observation["eligible"] is True
    assert "use_eligibility" not in mapping["mapped_target"]

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
        # Producer observation claims eligible, but is incomplete relative to named policy.
        "use_eligibility": copy.deepcopy(observation),
    }
    certificate = {
        "certificate_payload_sha256": "3" * 64,
        "permitted_use_scopes": ["production_conditioning"],
        "owner_ids": ["person-1"],
        "intent_ids": ["intent-1"],
        "labels": ["left_hand"],
        "target_region_ids": ["body-1"],
    }
    recomputed = evaluate_bridge_use_eligibility(
        request, receipt, exact_use_scope="production_conditioning", certificate=certificate
    )
    assert recomputed["eligible"] is False
    assert (
        "producer_self_assertion" in recomputed["reasons"]
        or "policy_observation_disagrees" in recomputed["reasons"]
    )
    assert derive_main_compatibility_alias(recomputed) is False
    assert mapping["mapped_target"].get("producer_observation") is None


def test_crosswalk_golden_vectors() -> None:
    vectors = json.loads(
        Path("qa/governance/bridge/maskfactory_main_crosswalk_golden_vectors_v1.json").read_text(
            encoding="utf-8"
        )
    )
    for vector in vectors["vectors"]:
        producer_major, producer_minor, _ = (
            int(part) for part in vector["producer_version"].split(".")
        )
        target_major, target_minor, _ = (int(part) for part in vector["target_version"].split("."))
        decision = evaluate_maskfactory_main_crosswalk(
            vector["producer_payload"],
            producer_major=producer_major,
            producer_minor=producer_minor,
            target_major=target_major,
            target_minor=target_minor,
        )
        assert decision["compatible"] is vector["expected_compatible"]
        expected_reason = vector.get("expected_reason_contains")
        if expected_reason:
            assert expected_reason in decision["reasons"]
