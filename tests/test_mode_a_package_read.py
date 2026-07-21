from __future__ import annotations

import copy
import hashlib
import inspect
import json
from pathlib import Path

import maskfactory.bridge.mode_a_package_read as mode_a_mod
from maskfactory.bridge.mode_a_package_read import (
    evaluate_mode_a_package_read,
    validate_mode_a_package_read_evidence,
)
from maskfactory.validation import canonical_document_sha256

POLICY_HASH = "2b6bf03ff91d1f376232806e19d15613e57bff85a7f8a0bf1dc0dbd0758be27a"
DECIDED_AT = "2026-07-19T12:00:00Z"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _step(sequence: int, operation: str, source: dict, output: dict, parameters: dict) -> dict:
    step = {
        "sequence": sequence,
        "operation": operation,
        "input": source,
        "output": output,
        "parameters": parameters,
        "inverse_strategy": "exact_inverse",
        "step_sha256": "",
    }
    step["step_sha256"] = canonical_document_sha256(
        step, excluded_top_level_fields=("step_sha256",)
    )
    return step


def _chain() -> dict:
    source = {"coordinate_space": "source_pixel", "width": 10, "height": 8}
    crop = {"coordinate_space": "crop_pixel", "width": 8, "height": 6}
    steps = [
        _step(
            0,
            "crop",
            source,
            crop,
            {"parameter_type": "crop", "x": 1, "y": 1, "width": 8, "height": 6},
        ),
    ]
    chain = {
        "chain_id": "mode-a-crop-v1",
        "chain_sha256": "",
        "source": source,
        "output": crop,
        "steps": steps,
        "roundtrip_policy": {
            "required": True,
            "maximum_error_px": 0.0,
            "reject_noninvertible": True,
        },
    }
    chain["chain_sha256"] = canonical_document_sha256(
        chain, excluded_top_level_fields=("chain_sha256",)
    )
    return chain


def _revocation(token: str = "a") -> bytes:
    record = {
        "event_payload_sha256": token * 64,
        "trust_binding": {"key_role": "producer_journal"},
        "signature": {"signed_payload_sha256": token * 64},
    }
    return json.dumps(record, separators=(",", ":")).encode()


def _documents(*, person_index: int = 0, label: str = "left_forearm") -> tuple[dict, dict]:
    source_encoded, source_pixels = b"source-png", b"source-canonical-rgb"
    mask_encoded, mask_pixels = b"mask-png", b"mask-canonical-l"
    manifest = b'{"parts":{"left_forearm":{"status":"human_approved_gold"}}}'
    ontology = b"ontology-v1"
    release = b"release-bytes"
    capability = b"capability-bytes"
    revocation = _revocation()
    chain = _chain()
    package_material = {
        "source_encoded_sha256": _sha(source_encoded),
        "source_decoded_pixel_sha256": _sha(source_pixels),
        "mask_encoded_sha256": _sha(mask_encoded),
        "mask_decoded_sha256": _sha(mask_pixels),
        "manifest_sha256": _sha(manifest),
        "ontology_sha256": _sha(ontology),
        "image_id": "img_demo",
        "person_index": person_index,
        "label": label,
    }
    package_sha256 = canonical_document_sha256(package_material)
    entry = {
        "image_id": "img_demo",
        "person_index": person_index,
        "label": label,
        "package_id": f"pkg-demo-p{person_index}",
        "package_revision": "rev-1",
        "artifact_id": f"artifact-p{person_index}-{label}",
        "owner_id": f"person-{person_index}",
        "scene_instance_id": f"scene-{person_index}",
        "character_revision": "char-rev-1",
        "raw_part_status": "human_approved_gold",
        "ontology_version": "body_parts_v1",
        "ontology_sha256": _sha(ontology),
        "source_encoded_sha256": _sha(source_encoded),
        "source_decoded_pixel_sha256": _sha(source_pixels),
        "mask_encoded_sha256": _sha(mask_encoded),
        "mask_decoded_sha256": _sha(mask_pixels),
        "manifest_sha256": _sha(manifest),
        "package_sha256": package_sha256,
        "transform_chain_sha256": chain["chain_sha256"],
    }
    request = {
        "image_id": "img_demo",
        "person_index": person_index,
        "label": label,
        "exact_use_scope": "diagnostic",
        "artifact_kind": "atomic",
        "ontology_version": "body_parts_v1",
        "raw_part_status": "human_approved_gold",
        "subject": {
            "canonical_person_id": f"person-{person_index}",
            "scene_instance_id": f"scene-{person_index}",
            "character_revision": "char-rev-1",
        },
        "transform_chain": chain,
        "transform_probes": [{"x": 4, "y": 3, "coordinate_space": "source_pixel"}],
        "protected_regions": [],
        "expected_protected_regions": [],
    }
    evidence = {
        "catalog": {
            "adoption_decision": "adopted",
            "release_status": "adopted",
            "release_payload_sha256": _sha(release),
            "capability_snapshot_sha256": _sha(capability),
            "packages": [entry],
        },
        "package_root": str(Path("C:/adopted/packages").resolve()),
        "relative_paths": {
            "source": "source.png",
            "mask": f"masks/{label}.png",
            "manifest": "manifest.json",
        },
        "bytes": {
            "source_encoded": source_encoded,
            "source_decoded_pixels": source_pixels,
            "mask_encoded": mask_encoded,
            "mask_decoded_pixels": mask_pixels,
            "manifest": manifest,
            "ontology": ontology,
            "release": release,
            "capability": capability,
            "revocation_identity": revocation,
        },
        "wrapper": None,
    }
    return request, evidence


def _active_wrapper(request: dict, evidence: dict, decision_preview: dict | None = None) -> dict:
    preview = decision_preview or evaluate_mode_a_package_read(
        request, evidence, decided_at=DECIDED_AT
    )
    observed = preview["observed"]
    return {
        "status": "active",
        "valid_until": "2026-07-20T00:00:00Z",
        "revocation_status": "none",
        "certificate_payload_sha256": "c" * 64,
        "permitted_use_scopes": [request["exact_use_scope"]],
        "exact_output_bindings": {
            "source_encoded_sha256": observed["source_encoded_sha256"],
            "source_decoded_pixel_sha256": observed["source_decoded_pixel_sha256"],
            "mask_encoded_sha256": observed["mask_encoded_sha256"],
            "mask_decoded_sha256": observed["mask_decoded_sha256"],
            "package_sha256": observed["package_sha256"],
            "manifest_sha256": observed["manifest_sha256"],
            "ontology_sha256": observed["ontology_sha256"],
            "transform_chain_sha256": observed["transform_chain_sha256"],
            "owner_id": observed["owner_id"],
            "scene_instance_id": observed["scene_instance_id"],
            "person_index": observed["person_index"],
            "label": observed["label"],
            "exact_use_scope": request["exact_use_scope"],
        },
    }


def test_diagnostic_single_and_multi_person_reads_accept_noncertified() -> None:
    request, evidence = _documents(person_index=0)
    decision = evaluate_mode_a_package_read(request, evidence, decided_at=DECIDED_AT)
    assert decision["status"] == "accepted"
    assert decision["authority_ceiling"] == "qa_passed_noncertified"
    assert decision["production_eligible"] is False
    assert decision["policy_sha256"] == POLICY_HASH
    assert decision["write_methods_exposed"] is False
    assert validate_mode_a_package_read_evidence(decision) == ()

    request_p1, evidence_p1 = _documents(person_index=1)
    decision_p1 = evaluate_mode_a_package_read(request_p1, evidence_p1, decided_at=DECIDED_AT)
    assert decision_p1["status"] == "accepted"
    assert decision_p1["observed"]["person_index"] == 1
    assert decision_p1["observed"]["owner_id"] == "person-1"
    assert (
        decision_p1["immutable_handles"]["package_id"]
        != decision["immutable_handles"]["package_id"]
    )


def test_production_requires_active_exact_wrapper() -> None:
    request, evidence = _documents()
    request["exact_use_scope"] = "production_conditioning"
    rejected = evaluate_mode_a_package_read(request, evidence, decided_at=DECIDED_AT)
    assert rejected["status"] == "rejected"
    assert "wrapper_missing" in rejected["rejection_reasons"]
    assert rejected["production_eligible"] is False
    assert rejected["authority_ceiling"] == "qa_passed_noncertified"

    evidence["wrapper"] = _active_wrapper(request, evidence, rejected)
    accepted = evaluate_mode_a_package_read(request, evidence, decided_at=DECIDED_AT)
    assert accepted["status"] == "accepted"
    assert accepted["authority_ceiling"] == "certified"
    assert accepted["production_eligible"] is True
    assert accepted["observed"]["wrapper_status"] == "active"
    assert validate_mode_a_package_read_evidence(accepted) == ()


def test_rejected_status_and_raw_escalation_fail_closed() -> None:
    request, evidence = _documents()
    request["raw_part_status"] = "rejected_needs_fix"
    decision = evaluate_mode_a_package_read(request, evidence, decided_at=DECIDED_AT)
    assert decision["status"] == "rejected"
    assert "rejected_part_status" in decision["rejection_reasons"]

    request, evidence = _documents()
    request["exact_use_scope"] = "production_conditioning"
    request["claimed_authority_state"] = "certified"
    request["escalate_raw_status"] = True
    decision = evaluate_mode_a_package_read(request, evidence, decided_at=DECIDED_AT)
    assert "raw_status_escalation" in decision["rejection_reasons"]
    assert "wrapper_missing" in decision["rejection_reasons"]


def test_path_escape_hash_drift_and_mutation_fail_closed() -> None:
    request, evidence = _documents()
    escaped = copy.deepcopy(evidence)
    escaped["relative_paths"]["mask"] = "../secrets/mask.png"
    decision = evaluate_mode_a_package_read(request, escaped, decided_at=DECIDED_AT)
    assert "path_escape" in decision["rejection_reasons"]

    drifted = copy.deepcopy(evidence)
    drifted["bytes"]["mask_decoded_pixels"] = b"tampered-same-size-ish"
    decision = evaluate_mode_a_package_read(request, drifted, decided_at=DECIDED_AT)
    assert "mask_hash_drift" in decision["rejection_reasons"]

    mutated = copy.deepcopy(evidence)
    mutated["write_requested"] = True
    mutated["mutation_target"] = "masks/left_forearm.png"
    decision = evaluate_mode_a_package_read(request, mutated, decided_at=DECIDED_AT)
    assert "mutation_attempt" in decision["rejection_reasons"]
    assert "write_path_forbidden" in decision["rejection_reasons"]


def test_stale_out_of_scope_revoked_wrapper_and_wrong_owner_fail_closed() -> None:
    request, evidence = _documents()
    request["exact_use_scope"] = "production_conditioning"
    base = evaluate_mode_a_package_read(request, evidence, decided_at=DECIDED_AT)
    wrapper = _active_wrapper(request, evidence, base)

    stale = copy.deepcopy(evidence)
    stale["wrapper"] = copy.deepcopy(wrapper)
    stale["wrapper"]["valid_until"] = "2026-07-18T00:00:00Z"
    assert (
        "wrapper_stale"
        in evaluate_mode_a_package_read(request, stale, decided_at=DECIDED_AT)["rejection_reasons"]
    )

    out_of_scope = copy.deepcopy(evidence)
    out_of_scope["wrapper"] = copy.deepcopy(wrapper)
    out_of_scope["wrapper"]["exact_output_bindings"]["owner_id"] = "wrong-person"
    assert (
        "wrapper_out_of_scope"
        in evaluate_mode_a_package_read(request, out_of_scope, decided_at=DECIDED_AT)[
            "rejection_reasons"
        ]
    )

    revoked = copy.deepcopy(evidence)
    revoked["wrapper"] = copy.deepcopy(wrapper)
    revoked["wrapper"]["revocation_status"] = "revoked"
    assert (
        "wrapper_revoked"
        in evaluate_mode_a_package_read(request, revoked, decided_at=DECIDED_AT)[
            "rejection_reasons"
        ]
    )

    wrong_owner = copy.deepcopy(request)
    wrong_owner["subject"] = dict(request["subject"])
    wrong_owner["subject"]["canonical_person_id"] = "person-99"
    assert (
        "wrong_owner"
        in evaluate_mode_a_package_read(wrong_owner, evidence, decided_at=DECIDED_AT)[
            "rejection_reasons"
        ]
    )


def test_derived_escalation_and_module_has_no_write_api() -> None:
    request, evidence = _documents()
    request["exact_use_scope"] = "production_conditioning"
    request["artifact_kind"] = "derived_union"
    request["parent_authority_state"] = "certified"
    request["claim_parent_authority"] = True
    decision = evaluate_mode_a_package_read(request, evidence, decided_at=DECIDED_AT)
    assert "derived_authority_escalation" in decision["rejection_reasons"]

    write_names = [
        name
        for name, value in inspect.getmembers(mode_a_mod, inspect.isfunction)
        if name.startswith(("write_", "save_", "mutate_", "update_package"))
    ]
    assert write_names == []
    assert not hasattr(mode_a_mod, "write_package")
    assert not hasattr(mode_a_mod, "mutate_package")
