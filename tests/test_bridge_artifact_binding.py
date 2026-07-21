from __future__ import annotations

import copy
import hashlib
import json

from maskfactory.bridge.artifact_binding import (
    build_artifact_consumption_decision,
    validate_artifact_consumption_decision,
)
from maskfactory.validation import canonical_document_sha256


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _revocation(token: str = "a") -> bytes:
    record = {
        "event_payload_sha256": token * 64,
        "trust_binding": {"key_role": "producer_journal"},
        "signature": {"signed_payload_sha256": token * 64},
    }
    return json.dumps(record, separators=(",", ":")).encode()


def _documents() -> tuple[dict, dict, dict]:
    source_encoded, source_pixels = b"source-png", b"source-canonical-rgb"
    mask_encoded, mask_pixels = b"mask-png", b"mask-canonical-l"
    qa, selection, revocation = b"qa-report", b"route-selection", _revocation()
    request = {
        "request_payload_sha256": "1" * 64,
        "source": {
            "encoded_sha256": _sha(source_encoded),
            "decoded_pixel_sha256": _sha(source_pixels),
            "decoder": {"decoder_id": "decoder", "version": "1", "binary_sha256": "2" * 64},
            "exif_orientation": 1,
            "orientation_applied": True,
            "channel_layout": "RGB",
            "alpha_mode": "none",
            "bit_depth": 8,
            "dtype": "uint8",
            "color_space": "sRGB",
            "icc_profile_sha256": None,
            "color_transform": {"transform_id": "sRGB", "transform_sha256": "3" * 64},
            "frame_extraction": None,
        },
        "media_scope": {"scope_kind": "still_image", "frame_index": None},
        "subject": {"canonical_person_id": "person-1", "scene_instance_id": "scene-1"},
        "compatibility": {"ontology_version": "body-v1", "ontology_sha256": "4" * 64},
        "protected_regions": [{"region_id": "protected-1"}],
        "protected_owner_roster": [{"owner": {"canonical_person_id": "person-2"}}],
        "transform_chain": {"chain_sha256": "5" * 64},
    }
    artifact = {
        "artifact_id": "mask-1",
        "intent_id": "intent-1",
        "label": "left_hand",
        "artifact_kind": "atomic_visible",
        "mask_type": "atomic",
        "owner": {"canonical_person_id": "person-1"},
        "encoded_sha256": _sha(mask_encoded),
        "decoded_mask_sha256": _sha(mask_pixels),
        "source_decoded_pixel_sha256": _sha(source_pixels),
        "width": 2,
        "height": 2,
        "coordinate_space": "output_pixel",
        "transform_chain_sha256": "5" * 64,
    }
    artifact["artifact_identity_sha256"] = canonical_document_sha256(
        {
            key: artifact.get(key)
            for key in (
                "artifact_id",
                "intent_id",
                "label",
                "artifact_kind",
                "mask_type",
                "owner",
                "encoded_sha256",
                "decoded_mask_sha256",
                "source_decoded_pixel_sha256",
                "width",
                "height",
                "coordinate_space",
                "transform_chain_sha256",
            )
        }
    )
    provider = {
        "stack_id": "stack-1",
        "model_artifacts": [{"model_id": "model-1", "sha256": "6" * 64}],
        "workflow": {"workflow_id": "workflow-1", "sha256": "7" * 64},
        "runtime": {"runtime_id": "runtime-1", "environment_lock_sha256": "8" * 64},
    }
    provider["stack_sha256"] = canonical_document_sha256(
        {key: provider[key] for key in ("stack_id", "model_artifacts", "workflow", "runtime")}
    )
    route = {"selected_route_id": "route-1", "selection_evidence_sha256": _sha(selection)}
    provider["execution_fingerprint_sha256"] = canonical_document_sha256(
        {
            "provider_stack_sha256": provider["stack_sha256"],
            "route_selection": route,
            "source_binding": {"decoded_pixel_sha256": _sha(source_pixels)},
        }
    )
    receipt = {
        "receipt_payload_sha256": "9" * 64,
        "source_binding": {"decoded_pixel_sha256": _sha(source_pixels)},
        "artifacts": [artifact],
        "qa": {"report_sha256": _sha(qa)},
        "execution_observation": {"route_selection": route},
        "authority": {
            "authority_state": "qa_passed_noncertified",
            "certificate_status": "none",
            "certificate_sha256": None,
            "revocation_index_sha256": _sha(revocation),
        },
        "provider_binding": provider,
        "release_binding": {"release_payload_sha256": "a" * 64},
        "lineage": {"operation_kind": "original_prediction"},
    }
    evidence = {
        "source": {"encoded": source_encoded, "decoded_pixels": source_pixels},
        "artifacts": {"mask-1": {"encoded": mask_encoded, "decoded_pixels": mask_pixels}},
        "qa_report": qa,
        "selection_evidence": selection,
        "revocation_identity": revocation,
    }
    return request, receipt, evidence


def test_consumption_binds_actual_bytes_and_reuses_only_exact_cache() -> None:
    request, receipt, evidence = _documents()
    decision = build_artifact_consumption_decision(request, receipt, evidence)
    assert decision["status"] == "accepted"
    assert validate_artifact_consumption_decision(decision) == ()
    reused = build_artifact_consumption_decision(
        request, receipt, evidence, cached_decision=decision
    )
    assert reused["status"] == "accepted"
    assert reused["cache_reused"] is True


def test_omission_ambiguity_and_byte_drift_fail_closed() -> None:
    request, receipt, evidence = _documents()
    omitted = copy.deepcopy(evidence)
    del omitted["qa_report"]
    assert (
        "qa_report_missing"
        in build_artifact_consumption_decision(request, receipt, omitted)["rejection_reasons"]
    )
    ambiguous = copy.deepcopy(evidence)
    ambiguous["artifacts"]["unexpected"] = {"encoded": b"x", "decoded_pixels": b"y"}
    assert (
        "output_artifact_evidence_ambiguous"
        in build_artifact_consumption_decision(request, receipt, ambiguous)["rejection_reasons"]
    )
    drifted = copy.deepcopy(evidence)
    drifted["artifacts"]["mask-1"]["decoded_pixels"] = b"tampered"
    assert (
        "output_decoded_pixels_drift"
        in build_artifact_consumption_decision(request, receipt, drifted)["rejection_reasons"]
    )


def test_provider_drift_and_revocation_cache_reuse_fail_closed() -> None:
    request, receipt, evidence = _documents()
    provider_drift = copy.deepcopy(receipt)
    provider_drift["provider_binding"]["model_artifacts"][0]["sha256"] = "f" * 64
    assert (
        "provider_runtime_workflow_drift"
        in build_artifact_consumption_decision(request, provider_drift, evidence)[
            "rejection_reasons"
        ]
    )
    accepted = build_artifact_consumption_decision(request, receipt, evidence)
    newer = copy.deepcopy(evidence)
    newer["revocation_identity"] = _revocation("b")
    refreshed = copy.deepcopy(receipt)
    refreshed["authority"]["revocation_index_sha256"] = _sha(newer["revocation_identity"])
    rejected = build_artifact_consumption_decision(
        request, refreshed, newer, cached_decision=accepted
    )
    assert "cache_reuse_stale_or_ambiguous" in rejected["rejection_reasons"]
    assert rejected["cache_reused"] is False
