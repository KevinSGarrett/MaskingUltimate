from __future__ import annotations

import copy
import hashlib
import json
import runpy
from pathlib import Path

from maskfactory.bridge.identity import (
    assignment_evidence_sha256,
    build_bridge_identity_decision,
    validate_bridge_identity_decision,
    validate_bridge_identity_set,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "mask_bridge_contracts"
BUILDER = runpy.run_path(str(FIXTURES / "build_contract_fixtures.py"))


def _base_exchange() -> tuple[dict, dict]:
    documents = json.loads((FIXTURES / "positive_contract_set_v1.json").read_text(encoding="utf-8"))
    request = copy.deepcopy(documents["mask_acquisition_request"])
    receipt = copy.deepcopy(documents["mask_acquisition_receipt"])
    _resign_exchange(request, receipt)
    return request, receipt


def _resign_exchange(request: dict, receipt: dict) -> None:
    subject = request["subject"]
    subject["assignment_evidence"]["mapping_sha256"] = assignment_evidence_sha256(subject)
    BUILDER["sign"](
        request,
        "request_payload_sha256",
        "consumer_request",
        ("request_payload_sha256", "signature"),
    )
    receipt["request_id"] = request["request_id"]
    receipt["request_payload_sha256"] = request["request_payload_sha256"]
    receipt["idempotency_key"] = request["idempotency_key"]
    receipt["subject_binding"].update(
        {
            key: subject[key]
            for key in (
                "scene_id",
                "shot_id",
                "take_id",
                "character_id",
                "character_revision",
                "scene_instance_id",
                "canonical_person_id",
                "person_index",
                "provider_person_index",
            )
        }
    )
    receipt["subject_binding"]["assignment_evidence_sha256"] = subject["assignment_evidence"][
        "mapping_sha256"
    ]
    BUILDER["sign"](
        receipt,
        "receipt_payload_sha256",
        "producer_receipt",
        ("receipt_payload_sha256", "signature"),
    )


def _variant(request: dict, receipt: dict, suffix: str) -> tuple[dict, dict]:
    request, receipt = copy.deepcopy(request), copy.deepcopy(receipt)
    request["request_id"] = f"mfareq_{suffix:0>24}"[-31:]
    receipt["receipt_id"] = f"mfarec_{suffix:0>24}"[-31:]
    request["authentication"]["nonce"] = f"request-identity-{suffix}-nonce-0001"
    receipt["authentication"]["nonce"] = f"receipt-identity-{suffix}-nonce-0001"
    _resign_exchange(request, receipt)
    return request, receipt


def _retarget_subject(
    request: dict, receipt: dict, *, instance: str, person: str, index: int
) -> None:
    request["subject"].update(
        scene_instance_id=instance,
        canonical_person_id=person,
        person_index=index,
    )
    for row in request["protected_owner_roster"]:
        owner = row["owner"]
        if owner["scene_instance_id"] == "scene-instance-001":
            owner.update(scene_instance_id=instance, canonical_person_id=person, person_index=index)
    for artifact in receipt["artifacts"]:
        artifact["owner"].update(
            scene_instance_id=instance, canonical_person_id=person, person_index=index
        )


def _codes(exchanges: list[tuple[dict, dict]]) -> set[str]:
    decision, issues = build_bridge_identity_decision(exchanges)
    assert not issues
    assert validate_bridge_identity_decision(decision) == ()
    return {collision["code"] for collision in decision["collisions"]}


def test_canonical_identity_decision_accepts_still_video_and_exact_replay() -> None:
    request, receipt = _base_exchange()
    decision, issues = build_bridge_identity_decision([(request, receipt), (request, receipt)])
    assert issues == ()
    assert decision["status"] == "accepted"
    assert decision["replay_count"] == 1
    assert validate_bridge_identity_decision(decision) == ()

    video_request, video_receipt = _variant(request, receipt, "video")
    video_request["media_scope"].update(
        scope_kind="video_frame",
        source_video_sha256="9" * 64,
        decoded_frame_sha256=video_request["source"]["decoded_pixel_sha256"],
        frame_index=3,
        pts=3000,
        timebase_numerator=1,
        timebase_denominator=1000,
        timestamp_ns=3_000_000_000,
    )
    video_request["source"]["frame_extraction"] = {
        "source_video_sha256": "9" * 64,
        "frame_index": 3,
        "pts": 3000,
        "timebase_numerator": 1,
        "timebase_denominator": 1000,
        "extractor_sha256": "8" * 64,
    }
    _resign_exchange(video_request, video_receipt)
    decision, issues = build_bridge_identity_decision([(video_request, video_receipt)])
    assert issues == ()
    assert decision["status"] == "accepted"


def test_canonical_identity_rejects_required_cross_record_collisions() -> None:
    request, receipt = _base_exchange()

    altered_request, altered_receipt = _variant(request, receipt, "assign")
    altered_request["subject"]["assignment_evidence"]["bbox_sha256"] = "a" * 64
    _resign_exchange(altered_request, altered_receipt)
    assert "assignment_evidence_drift" in _codes(
        [(request, receipt), (altered_request, altered_receipt)]
    )

    altered_request, altered_receipt = _variant(request, receipt, "revision")
    altered_request["subject"]["character_revision"] = "2.0.0"
    _resign_exchange(altered_request, altered_receipt)
    assert "character_revision_collision" in _codes(
        [(request, receipt), (altered_request, altered_receipt)]
    )

    altered_request, altered_receipt = _variant(request, receipt, "intent")
    altered_request["idempotency_key"] = "identity-intent-second-record"
    _resign_exchange(altered_request, altered_receipt)
    assert "duplicate_intent_collision" in _codes(
        [(request, receipt), (altered_request, altered_receipt)]
    )

    altered_request, altered_receipt = _variant(request, receipt, "provider")
    _retarget_subject(
        altered_request,
        altered_receipt,
        instance="scene-instance-003",
        person="person-canonical-003",
        index=3,
    )
    _resign_exchange(altered_request, altered_receipt)
    assert "provider_person_index_collision" in _codes(
        [(request, receipt), (altered_request, altered_receipt)]
    )

    altered_request, altered_receipt = _variant(request, receipt, "artifact")
    _retarget_subject(
        altered_request,
        altered_receipt,
        instance="scene-instance-004",
        person="person-canonical-004",
        index=4,
    )
    altered_request["subject"]["provider_person_index"] = 4
    altered_receipt["artifacts"][0]["owner"]["entity_id"] = "character-fixture-004"
    _resign_exchange(altered_request, altered_receipt)
    assert "artifact_identity_collision" in _codes(
        [(request, receipt), (altered_request, altered_receipt)]
    )

    altered_request, altered_receipt = _variant(request, receipt, "replay")
    altered_request["idempotency_key"] = request["idempotency_key"]
    _resign_exchange(altered_request, altered_receipt)
    assert "idempotency_replay_collision" in _codes(
        [(request, receipt), (altered_request, altered_receipt)]
    )


def test_pixel_decoder_time_and_owner_fixtures_fail_closed() -> None:
    request, receipt = _base_exchange()

    pixel_request, pixel_receipt = _variant(request, receipt, "pixel")
    pixel_receipt["source_binding"]["decoded_pixel_sha256"] = "f" * 64
    _resign_exchange(pixel_request, pixel_receipt)
    pixel_reasons = {
        issue.validator for issue in validate_bridge_identity_set([(pixel_request, pixel_receipt)])
    }
    assert "identity_pixel_drift" in pixel_reasons

    decoder_request, decoder_receipt = _variant(request, receipt, "decoder")
    decoder_request["source"]["decoder"] = {
        "decoder_id": "other-decoder",
        "version": "9.9.9",
        "binary_sha256": "b" * 64,
    }
    _resign_exchange(decoder_request, decoder_receipt)
    decoder_reasons = {
        issue.validator
        for issue in validate_bridge_identity_set([(decoder_request, decoder_receipt)])
    }
    assert "identity_decoder_drift" in decoder_reasons

    time_request, time_receipt = _variant(request, receipt, "time")
    time_request["media_scope"].update(
        scope_kind="video_frame",
        source_video_sha256="9" * 64,
        decoded_frame_sha256=time_request["source"]["decoded_pixel_sha256"],
        frame_index=3,
        pts=3000,
        timebase_numerator=1,
        timebase_denominator=1000,
        timestamp_ns=3_000_000_000,
    )
    time_request["source"]["frame_extraction"] = {
        "source_video_sha256": "9" * 64,
        "frame_index": 7,
        "pts": 3000,
        "timebase_numerator": 1,
        "timebase_denominator": 1000,
        "extractor_sha256": "8" * 64,
    }
    _resign_exchange(time_request, time_receipt)
    time_reasons = {
        issue.validator for issue in validate_bridge_identity_set([(time_request, time_receipt)])
    }
    assert "identity_time_drift" in time_reasons

    omitted_request, omitted_receipt = _variant(request, receipt, "omitowner")
    omitted_request["protected_owner_roster"] = []
    _resign_exchange(omitted_request, omitted_receipt)
    omitted_reasons = {
        issue.validator
        for issue in validate_bridge_identity_set([(omitted_request, omitted_receipt)])
    }
    assert "identity_owner_omitted" in omitted_reasons

    ambiguous_request, ambiguous_receipt = _variant(request, receipt, "ambowner")
    ambiguous_receipt["artifacts"][0]["owner"] = {
        "owner_kind": "character_instance",
        "entity_id": "character-fixture-999",
        "scene_instance_id": "scene-instance-999",
        "canonical_person_id": "person-canonical-999",
        "person_index": 9,
    }
    _resign_exchange(ambiguous_request, ambiguous_receipt)
    ambiguous_reasons = {
        issue.validator
        for issue in validate_bridge_identity_set([(ambiguous_request, ambiguous_receipt)])
    }
    assert "identity_owner_ambiguous" in ambiguous_reasons


def test_identity_decision_is_order_invariant_and_assignment_is_recomputed() -> None:
    request, receipt = _base_exchange()
    second_request, second_receipt = _variant(request, receipt, "order")
    _retarget_subject(
        second_request,
        second_receipt,
        instance="scene-instance-005",
        person="person-canonical-005",
        index=5,
    )
    second_request["idempotency_key"] = "identity-order-independent-second"
    second_request["subject"]["provider_person_index"] = 5
    second_request["mask_intents"][0]["intent_id"] = "intent-other-hand"
    second_receipt["artifacts"][0]["intent_id"] = "intent-other-hand"
    second_receipt["artifacts"][0].update(
        artifact_id="package-other-hand",
        artifact_identity_sha256=hashlib.sha256(b"other-artifact").hexdigest(),
        encoded_sha256=hashlib.sha256(b"other-encoded").hexdigest(),
        decoded_mask_sha256=hashlib.sha256(b"other-mask").hexdigest(),
    )
    _resign_exchange(second_request, second_receipt)
    forward, issues = build_bridge_identity_decision(
        [(request, receipt), (second_request, second_receipt)]
    )
    backward, reverse_issues = build_bridge_identity_decision(
        [(second_request, second_receipt), (request, receipt)]
    )
    assert issues == reverse_issues == ()
    assert forward["status"] == backward["status"] == "accepted"
    assert forward["decision_sha256"] == backward["decision_sha256"]

    tampered = copy.deepcopy(request)
    tampered["subject"]["assignment_evidence"]["mapping_sha256"] = "f" * 64
    assert "assignment_evidence_recomputed" in {
        issue.validator for issue in validate_bridge_identity_set([(tampered, receipt)])
    }
