"""Producer Mode A vertical slice: adopted package through adapter handoff.

MF-P6-12.02 producer-side unit. This module:
- reads an adopted immutable Mode A package under an active exact wrapper
- binds adapter-contract conformance evidence
- recomputes independent use-eligibility for production_conditioning
- journals admit→route→submit handoff state with a signed checkpoint
- builds a deterministic intended ComfyUI inpaint/edit evidence envelope
- rejects fabricated Main/ComfyUI result/history receipts
- probes submitted_unknown recovery without claiming Main durable retention

Fixture/deterministic evidence is preferred. Real Main adapter invocation and
ComfyUI inpaint/edit execution remain external completion blockers.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator

from maskfactory.bridge.external_adapter_conformance import (
    build_external_adapter_conformance_evidence,
    validate_external_adapter_conformance_evidence,
)
from maskfactory.bridge.journal import (
    append_bridge_journal_event,
    checkpoint_bridge_journal,
    validate_bridge_journal_history,
)
from maskfactory.bridge.mode_a_package_read import (
    evaluate_mode_a_package_read,
    validate_mode_a_package_read_evidence,
)
from maskfactory.bridge.recovery import simulate_kill_at_boundary
from maskfactory.bridge.use_eligibility import (
    evaluate_bridge_use_eligibility,
    validate_bridge_use_eligibility_decision,
)
from maskfactory.validation import canonical_document_sha256

POLICY_PATH = Path(__file__).parents[3] / "configs" / "mode_a_vertical_slice_policy.yaml"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "mode_a_vertical_slice_evidence.schema.json"
POLICY_ID = "maskfactory-bridge-mode-a-vertical-slice-v1"
ADAPTER_FIXTURE = (
    Path(__file__).parents[3]
    / "tests/fixtures/external_adapter_conformance/accepted_observation_v1.json"
)
USE_ELIGIBILITY_POLICY_ID = "maskfactory-bridge-use-eligibility-v1"
USE_ELIGIBILITY_POLICY_HASH = "2091798bde20a05cfc169631acc0ed3d2194ffc66527f86004fb2413452ae0d4"
DECIDED_AT_DEFAULT = "2026-07-19T14:00:00Z"
_LABEL = "left_forearm"
_CHARACTER_ID = "character-demo-single-0"
_JOURNAL_ID = "mode-a-vertical-slice-handoff-v1"
_SIGNING_KEY_ID = "mf-mode-a-slice-journal"


class ModeAVerticalSliceError(ValueError):
    """Raised when Mode A vertical-slice policy or inputs are unusable."""


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ModeAVerticalSliceError("mode a vertical slice policy unavailable") from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise ModeAVerticalSliceError("unexpected mode a vertical slice policy")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise ModeAVerticalSliceError("mode a vertical slice policy hash mismatch")
    return dict(policy)


def _ordered(policy: Mapping[str, Any], reasons: set[str]) -> list[str]:
    return [code for code in policy["reason_codes"] if code in reasons]


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _step(
    sequence: int,
    operation: str,
    source: dict[str, Any],
    output: dict[str, Any],
    parameters: dict[str, Any],
) -> dict[str, Any]:
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


def _transform_chain() -> dict[str, Any]:
    source = {"coordinate_space": "source_pixel", "width": 10, "height": 8}
    crop = {"coordinate_space": "crop_pixel", "width": 8, "height": 6}
    steps = [
        _step(
            0,
            "crop",
            source,
            crop,
            {"parameter_type": "crop", "x": 1, "y": 1, "width": 8, "height": 6},
        )
    ]
    chain = {
        "chain_id": "mode-a-slice-crop-v1",
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


def _revocation_bytes() -> bytes:
    token = "a" * 64
    record = {
        "event_payload_sha256": token,
        "trust_binding": {"key_role": "producer_journal"},
        "signature": {"signed_payload_sha256": token},
    }
    return json.dumps(record, separators=(",", ":")).encode("utf-8")


def build_fixture_adopted_package(
    *, person_index: int = 0
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build one adopted single-person Mode A package request/evidence pair."""
    source_encoded, source_pixels = b"mode-a-slice-source-png", b"mode-a-slice-source-rgb"
    mask_encoded, mask_pixels = b"mode-a-slice-mask-png", b"mode-a-slice-mask-l"
    manifest = b'{"parts":{"left_forearm":{"status":"human_approved_gold"}}}'
    ontology = b"ontology-body-parts-v1"
    release = b"adopted-integration-release-bytes"
    capability = b"adopted-capability-snapshot-bytes"
    revocation = _revocation_bytes()
    chain = _transform_chain()
    label = _LABEL
    package_material = {
        "source_encoded_sha256": _sha256_bytes(source_encoded),
        "source_decoded_pixel_sha256": _sha256_bytes(source_pixels),
        "mask_encoded_sha256": _sha256_bytes(mask_encoded),
        "mask_decoded_sha256": _sha256_bytes(mask_pixels),
        "manifest_sha256": _sha256_bytes(manifest),
        "ontology_sha256": _sha256_bytes(ontology),
        "image_id": "img_mode_a_slice",
        "person_index": person_index,
        "label": label,
    }
    package_sha256 = canonical_document_sha256(package_material)
    entry = {
        "image_id": "img_mode_a_slice",
        "person_index": person_index,
        "label": label,
        "package_id": f"pkg-mode-a-slice-p{person_index}",
        "package_revision": "rev-mode-a-slice-1",
        "artifact_id": f"artifact-mode-a-slice-p{person_index}-{label}",
        "owner_id": f"person-{person_index}",
        "scene_instance_id": f"scene-instance-{person_index}",
        "character_revision": "char-rev-mode-a-1",
        "raw_part_status": "human_approved_gold",
        "ontology_version": "body_parts_v1",
        "ontology_sha256": _sha256_bytes(ontology),
        "source_encoded_sha256": _sha256_bytes(source_encoded),
        "source_decoded_pixel_sha256": _sha256_bytes(source_pixels),
        "mask_encoded_sha256": _sha256_bytes(mask_encoded),
        "mask_decoded_sha256": _sha256_bytes(mask_pixels),
        "manifest_sha256": _sha256_bytes(manifest),
        "package_sha256": package_sha256,
        "transform_chain_sha256": chain["chain_sha256"],
    }
    request = {
        "image_id": "img_mode_a_slice",
        "person_index": person_index,
        "label": label,
        "exact_use_scope": "production_conditioning",
        "artifact_kind": "atomic",
        "ontology_version": "body_parts_v1",
        "raw_part_status": "human_approved_gold",
        "subject": {
            "canonical_person_id": f"person-{person_index}",
            "scene_instance_id": f"scene-instance-{person_index}",
            "character_revision": "char-rev-mode-a-1",
            "character_id": _CHARACTER_ID,
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
            "release_payload_sha256": _sha256_bytes(release),
            "capability_snapshot_sha256": _sha256_bytes(capability),
            "packages": [entry],
        },
        "package_root": str(Path("C:/adopted/mode_a_slice_packages").resolve()),
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
    preview = evaluate_mode_a_package_read(request, evidence, decided_at=DECIDED_AT_DEFAULT)
    observed = preview["observed"]
    evidence["wrapper"] = {
        "status": "active",
        "valid_until": "2026-07-20T00:00:00Z",
        "revocation_status": "none",
        "certificate_payload_sha256": "c" * 64,
        "permitted_use_scopes": ["production_conditioning"],
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
            "exact_use_scope": "production_conditioning",
        },
    }
    return request, evidence


def build_fixture_adapter_observation() -> dict[str, Any]:
    """Load the accepted external-adapter conformance observation fixture."""
    try:
        payload = json.loads(ADAPTER_FIXTURE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModeAVerticalSliceError("adapter conformance fixture unavailable") from exc
    if not isinstance(payload, Mapping):
        raise ModeAVerticalSliceError("adapter conformance fixture shape invalid")
    return dict(payload)


def build_intended_inpaint_workflow(
    *, package_sha256: str, mask_encoded_sha256: str
) -> dict[str, Any]:
    """Deterministic intended ComfyUI inpaint/edit graph (not an execution receipt)."""
    workflow = {
        "schema_version": "1.0.0",
        "workflow_id": "wf_mode_a_slice_inpaint_edit_v1",
        "operation": "comfyui_inpaint_edit",
        "person_mode": "single_person",
        "nodes": [
            {
                "id": 1,
                "class_type": "MaskFactoryLoadSource",
                "inputs": {"package_sha256": package_sha256},
            },
            {
                "id": 2,
                "class_type": "MaskFactoryLoadInpaintMask",
                "inputs": {"mask_encoded_sha256": mask_encoded_sha256, "label": _LABEL},
            },
            {
                "id": 3,
                "class_type": "VAEEncodeForInpaint",
                "inputs": {"pixels": [1, 0], "mask": [2, 0]},
            },
            {"id": 4, "class_type": "KSampler", "inputs": {"latent": [3, 0]}},
            {"id": 5, "class_type": "VAEDecode", "inputs": {"samples": [4, 0]}},
        ],
    }
    workflow["workflow_sha256"] = canonical_document_sha256(
        workflow, excluded_top_level_fields=("workflow_sha256",)
    )
    return workflow


def reject_fabricated_downstream_receipt(claim: Mapping[str, Any] | None) -> dict[str, Any]:
    """Fail closed when a caller asserts Main/ComfyUI success without real receipts."""
    claim_map = _mapping(claim)
    fabricated = bool(
        claim_map.get("main_adapter_execution_receipt_present") is True
        or claim_map.get("comfyui_inpaint_result_present") is True
        or claim_map.get("comfyui_history_present") is True
        or isinstance(claim_map.get("result_sha256"), str)
        or isinstance(claim_map.get("history_sha256"), str)
        or claim_map.get("claim_mf_p6_12_02_complete") is True
    )
    return {
        "attempted": fabricated,
        "rejected": fabricated,
        "reason_codes": ["downstream_receipt_fabricated"] if fabricated else [],
    }


def _offset_utc(decided_at: str, seconds: int) -> str:
    try:
        parsed = datetime.fromisoformat(decided_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (
            (parsed + timedelta(seconds=seconds))
            .astimezone(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    except ValueError as exc:
        raise ModeAVerticalSliceError("invalid decided_at timestamp") from exc


def build_producer_handoff_journal(
    *,
    package_read_decision_sha256: str,
    adapter_decision_sha256: str,
    eligibility_decision_sha256: str,
    workflow_sha256: str,
    private_key: Ed25519PrivateKey | None = None,
    decided_at: str = DECIDED_AT_DEFAULT,
) -> dict[str, Any]:
    """Append admit→route→submit journal events and checkpoint the head."""
    key = private_key or Ed25519PrivateKey.from_private_bytes(bytes.fromhex("11" * 32))
    public = key.public_key().public_bytes_raw()
    trusted = {
        _SIGNING_KEY_ID: {
            "public_key_sha256": hashlib.sha256(public).hexdigest(),
            "roles": ["producer_journal"],
            "status": "active",
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": "2027-01-01T00:00:00Z",
        }
    }
    entries: tuple[dict[str, Any], ...] = ()
    body_admit = {
        "phase": "admit",
        "package_read_decision_sha256": package_read_decision_sha256,
    }
    entries, _, _ = append_bridge_journal_event(
        entries,
        journal_id=_JOURNAL_ID,
        state="admit",
        idempotency_key="mode-a-slice-admit-001",
        event_body=body_admit,
        occurred_at=_offset_utc(decided_at, 0),
        private_key=key,
        signing_key_id=_SIGNING_KEY_ID,
    )
    body_route = {
        "phase": "route",
        "adapter_conformance_decision_sha256": adapter_decision_sha256,
        "use_eligibility_decision_sha256": eligibility_decision_sha256,
    }
    entries, _, _ = append_bridge_journal_event(
        entries,
        journal_id=_JOURNAL_ID,
        state="route",
        idempotency_key="mode-a-slice-route-001",
        event_body=body_route,
        occurred_at=_offset_utc(decided_at, 1),
        private_key=key,
        signing_key_id=_SIGNING_KEY_ID,
    )
    body_submit = {
        "phase": "submit",
        "intended_workflow_sha256": workflow_sha256,
        "downstream_operation": "comfyui_inpaint_edit",
        "awaiting_main_execution": True,
    }
    entries, head, _ = append_bridge_journal_event(
        entries,
        journal_id=_JOURNAL_ID,
        state="submit",
        idempotency_key="mode-a-slice-submit-001",
        event_body=body_submit,
        occurred_at=_offset_utc(decided_at, 2),
        private_key=key,
        signing_key_id=_SIGNING_KEY_ID,
    )
    checkpoint = checkpoint_bridge_journal(
        entries,
        journal_id=_JOURNAL_ID,
        checkpoint_id="mode-a-slice-checkpoint-001",
        created_at=_offset_utc(decided_at, 3),
        private_key=key,
        signing_key_id=_SIGNING_KEY_ID,
    )
    history_issues = validate_bridge_journal_history(
        entries, checkpoints=(checkpoint,), trusted_signing_keys=trusted
    )
    return {
        "journal_id": _JOURNAL_ID,
        "head_state": head["state"],
        "entry_count": len(entries),
        "head_entry_sha256": head["entry_sha256"],
        "checkpoint_sha256": checkpoint["checkpoint_sha256"],
        "history_valid": history_issues == (),
        "history_issues": list(history_issues),
        "entries": list(entries),
        "checkpoint": checkpoint,
    }


def _use_eligibility_documents(
    package_read: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    observed = _mapping(package_read.get("observed"))
    wrapper_cert = observed.get("wrapper_certificate_sha256")
    request_doc = {
        "request_payload_sha256": canonical_document_sha256(
            {
                "image_id": request.get("image_id"),
                "person_index": request.get("person_index"),
                "label": request.get("label"),
                "exact_use_scope": "production_conditioning",
                "package_sha256": observed.get("package_sha256"),
            }
        ),
        "subject": {
            "canonical_person_id": observed.get("owner_id"),
        },
        "target_regions": [{"region_id": f"body-{observed.get('person_index', 0)}"}],
        "mask_intents": [
            {
                "intent_id": f"intent-{_LABEL}",
                "label": _LABEL,
            }
        ],
    }
    receipt = {
        "receipt_payload_sha256": package_read["decision_sha256"],
        "result": "succeeded" if package_read.get("status") == "accepted" else "failed",
        "qa": {"status": "pass"},
        "transform_validation": {
            "roundtrip_passed": observed.get("transform_roundtrip_passed") is True
        },
        "authority": {
            "authority_state": package_read.get("authority_ceiling"),
            "certificate_status": (
                "active" if observed.get("wrapper_status") == "active" else "missing"
            ),
            "certificate_exact_scope_match": observed.get("wrapper_status") == "active",
            "certificate_sha256": wrapper_cert,
            "revocation_index_sha256": observed.get("revocation_head_sha256"),
        },
        "artifacts": [{"intent_id": f"intent-{_LABEL}", "label": _LABEL}],
        "use_eligibility": {
            "policy_id": USE_ELIGIBILITY_POLICY_ID,
            "policy_sha256": USE_ELIGIBILITY_POLICY_HASH,
            "required_authority_state": "certified",
            "exact_use_scope": "production_conditioning",
            "eligible": True,
            "reasons": ["eligible"],
        },
    }
    certificate = {
        "certificate_payload_sha256": wrapper_cert,
        "permitted_use_scopes": ["production_conditioning"],
        "owner_ids": [observed.get("owner_id")],
        "intent_ids": [f"intent-{_LABEL}"],
        "labels": [_LABEL],
        "target_region_ids": [f"body-{observed.get('person_index', 0)}"],
    }
    return request_doc, receipt, certificate


def run_mode_a_vertical_slice(
    workdir: Path | None = None,
    *,
    decided_at: str = DECIDED_AT_DEFAULT,
    fabricated_downstream_claim: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the producer-side single-person Mode A vertical slice.

    ``workdir`` is reserved for future on-disk package materialization; fixture
    evaluation is in-memory and deterministic.
    """
    del workdir  # reserved; fixtures remain in-memory
    policy = _policy()
    reasons: set[str] = set()

    request, package_evidence = build_fixture_adopted_package(person_index=0)
    package_read = evaluate_mode_a_package_read(request, package_evidence, decided_at=decided_at)
    package_issues = validate_mode_a_package_read_evidence(package_read)
    if package_issues or package_read.get("status") != "accepted":
        reasons.add("package_read_rejected")
    if _mapping(package_read.get("observed")).get("wrapper_status") != "active":
        reasons.add("wrapper_not_active")
    if (
        package_read.get("authority_ceiling") != "certified"
        or package_read.get("production_eligible") is not True
    ):
        reasons.add("package_read_rejected")

    adapter_observation = build_fixture_adapter_observation()
    adapter = build_external_adapter_conformance_evidence(
        adapter_observation, decided_at=decided_at
    )
    adapter_issues = validate_external_adapter_conformance_evidence(adapter)
    if adapter_issues or adapter.get("status") != "accepted":
        reasons.add("adapter_conformance_rejected")

    eligibility_request, eligibility_receipt, certificate = _use_eligibility_documents(
        package_read, request=request
    )
    # Producer observation must match the independent recomputation; seed eligible first,
    # then let evaluate_bridge_use_eligibility recompute and detect disagreement.
    eligibility = evaluate_bridge_use_eligibility(
        eligibility_request,
        eligibility_receipt,
        exact_use_scope="production_conditioning",
        certificate=certificate,
    )
    eligibility_issues = validate_bridge_use_eligibility_decision(eligibility)
    if eligibility_issues or eligibility.get("eligible") is not True:
        reasons.add("use_eligibility_rejected")

    observed = _mapping(package_read.get("observed"))
    workflow = build_intended_inpaint_workflow(
        package_sha256=str(observed.get("package_sha256") or ""),
        mask_encoded_sha256=str(observed.get("mask_encoded_sha256") or ""),
    )
    identity = {
        "source_image_sha256": observed.get("source_encoded_sha256"),
        "character_id": _CHARACTER_ID,
        "character_revision": observed.get("character_revision"),
        "character_instance_id": observed.get("scene_instance_id"),
        "person_index": observed.get("person_index"),
        "package_revision": _mapping(package_read.get("immutable_handles")).get("package_revision"),
        "mask_encoded_sha256": observed.get("mask_encoded_sha256"),
        "mask_decoded_pixel_sha256": observed.get("mask_decoded_sha256"),
        "transform_chain_sha256": observed.get("transform_chain_sha256"),
        "ontology_sha256": observed.get("ontology_sha256"),
        "workflow_sha256": workflow["workflow_sha256"],
        "result_sha256": None,
        "history_sha256": None,
        "authority_decision_sha256": package_read.get("decision_sha256"),
        "complete_producer_bindings": False,
        "complete_downstream_bindings": False,
    }
    producer_fields = (
        identity["source_image_sha256"],
        identity["character_id"],
        identity["character_revision"],
        identity["character_instance_id"],
        identity["person_index"],
        identity["package_revision"],
        identity["mask_encoded_sha256"],
        identity["mask_decoded_pixel_sha256"],
        identity["transform_chain_sha256"],
        identity["ontology_sha256"],
        identity["workflow_sha256"],
        identity["authority_decision_sha256"],
    )
    identity["complete_producer_bindings"] = all(
        field is not None and field != "" for field in producer_fields
    ) and isinstance(identity["person_index"], int)
    if not identity["complete_producer_bindings"]:
        reasons.add("identity_chain_incomplete")

    journal = build_producer_handoff_journal(
        package_read_decision_sha256=str(package_read["decision_sha256"]),
        adapter_decision_sha256=str(adapter["decision_sha256"]),
        eligibility_decision_sha256=str(eligibility["decision_sha256"]),
        workflow_sha256=str(workflow["workflow_sha256"]),
        decided_at=decided_at,
    )
    if not journal["history_valid"] or journal["head_state"] != "submit":
        reasons.add("handoff_journal_invalid")

    fabrication = reject_fabricated_downstream_receipt(fabricated_downstream_claim)
    if fabrication["rejected"]:
        reasons.add("downstream_receipt_fabricated")

    # Honest absence of Main/ComfyUI execution is always recorded for fixture runs.
    reasons.add("main_adapter_execution_absent")
    reasons.add("comfyui_result_history_absent")

    recovery = simulate_kill_at_boundary(
        kill_boundary="submitted_unknown",
        request_id="mfareq_mode_a_slice_00000001",
        decided_at=decided_at,
    )
    recon = _mapping(recovery.get("reconciliation"))
    recovery_probe = {
        "kill_boundary": "submitted_unknown",
        "status": recovery.get("status"),
        "outcome_unknown_reconciled": bool(
            recon.get("required") is True
            and recon.get("outcome") == "not_found"
            and recon.get("evidence_valid") is True
        ),
        "decision_sha256": recovery.get("decision_sha256"),
    }

    external_blockers = {"main_adapter_execution_absent", "comfyui_result_history_absent"}
    producer_ok = not (reasons - external_blockers)
    if fabrication["rejected"]:
        status = "rejected"
        binding_status = "rejected_fabricated"
    elif producer_ok:
        status = "producer_partial"
        binding_status = "producer_ready_awaiting_main"
    else:
        status = "rejected"
        binding_status = "rejected"

    ordered = _ordered(policy, reasons)
    evidence = {
        "schema_version": "1.0.0",
        "record_type": "mode_a_vertical_slice_evidence",
        "decided_at": decided_at,
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "fixture_truth_tier": "synthetic_contract_fixture",
        "status": status,
        "rejection_reasons": ordered,
        "package_read": {
            "status": package_read["status"],
            "authority_ceiling": package_read["authority_ceiling"],
            "production_eligible": package_read["production_eligible"],
            "wrapper_status": observed.get("wrapper_status"),
            "decision_sha256": package_read["decision_sha256"],
            "package_revision": identity["package_revision"],
            "transform_roundtrip_passed": observed.get("transform_roundtrip_passed"),
        },
        "adapter_conformance": {
            "status": adapter["status"],
            "decision_sha256": adapter["decision_sha256"],
            "adapter_package_sha256": _mapping(adapter.get("adapter_identity")).get(
                "package_sha256"
            ),
            "bridge_contract": _mapping(adapter.get("contract_bindings")).get("bridge_contract"),
        },
        "use_eligibility": {
            "eligible": eligibility["eligible"],
            "exact_use_scope": "production_conditioning",
            "decision_sha256": eligibility["decision_sha256"],
            "reasons": list(eligibility["reasons"]),
        },
        "identity_chain": identity,
        "handoff_journal": {
            "journal_id": journal["journal_id"],
            "head_state": journal["head_state"],
            "entry_count": journal["entry_count"],
            "head_entry_sha256": journal["head_entry_sha256"],
            "checkpoint_sha256": journal["checkpoint_sha256"],
            "history_valid": journal["history_valid"],
        },
        "downstream_envelope": {
            "intended_workflow_sha256": workflow["workflow_sha256"],
            "intended_operation": "comfyui_inpaint_edit",
            "main_adapter_execution_receipt_present": False,
            "comfyui_inpaint_result_present": False,
            "comfyui_history_present": False,
            # Always true on the producer path: fabrication is refused, and honest
            # absence is not treated as a successful Main/ComfyUI receipt.
            "fabricated_receipt_rejected": True,
            "binding_status": binding_status,
        },
        "recovery_probe": recovery_probe,
        "claim_boundary": {
            "producer_fixture_slice_complete": producer_ok and status == "producer_partial",
            "adopted_integration_release_complete": False,
            "main_adapter_execution_complete": False,
            "comfyui_inpaint_edit_complete": False,
            "mf_p6_12_02_complete": False,
            "notes": (
                "Producer fixture path covers adopted Mode A package read with active "
                "wrapper, adapter conformance binding, independent use-eligibility, "
                "complete producer identity hashes, signed handoff journal through submit, "
                "intended inpaint workflow hash, fabricated-receipt refusal, and "
                "submitted_unknown recovery probe. Real adopted integration-release "
                "clean-install, pinned Main adapter execution, and ComfyUI inpaint/edit "
                "result/history receipts remain open external blockers."
            ),
        },
        "decision_sha256": "",
    }
    evidence["decision_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("decision_sha256",)
    )
    return evidence


def validate_mode_a_vertical_slice_evidence(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate schema, policy binding, hash, and producer claim boundaries."""
    issues: list[str] = []
    try:
        policy = _policy()
    except ModeAVerticalSliceError as exc:
        return (str(exc),)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    issues.extend(
        f"schema:{error.validator}"
        for error in Draft202012Validator(schema).iter_errors(dict(evidence))
    )
    if (
        evidence.get("policy_id") != policy["policy_id"]
        or evidence.get("policy_sha256") != policy["policy_sha256"]
    ):
        issues.append("policy_drift")
    expected = canonical_document_sha256(evidence, excluded_top_level_fields=("decision_sha256",))
    if evidence.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")
    allowed = set(policy["reason_codes"])
    reasons = evidence.get("rejection_reasons")
    if not isinstance(reasons, list) or not set(reasons).issubset(allowed):
        issues.append("decision_reason_code")
    claim = _mapping(evidence.get("claim_boundary"))
    if claim.get("mf_p6_12_02_complete") is True:
        issues.append("completion_overclaim")
    if claim.get("main_adapter_execution_complete") is True:
        issues.append("main_execution_overclaim")
    if claim.get("comfyui_inpaint_edit_complete") is True:
        issues.append("comfyui_execution_overclaim")
    identity = _mapping(evidence.get("identity_chain"))
    if identity.get("complete_downstream_bindings") is True:
        issues.append("downstream_binding_overclaim")
    if identity.get("result_sha256") is not None or identity.get("history_sha256") is not None:
        issues.append("fabricated_downstream_identity")
    envelope = _mapping(evidence.get("downstream_envelope"))
    if envelope.get("main_adapter_execution_receipt_present") is True:
        issues.append("main_receipt_overclaim")
    if envelope.get("comfyui_inpaint_result_present") is True:
        issues.append("comfyui_result_overclaim")
    if envelope.get("comfyui_history_present") is True:
        issues.append("comfyui_history_overclaim")
    package = _mapping(evidence.get("package_read"))
    if evidence.get("status") == "producer_partial":
        if package.get("status") != "accepted" or package.get("wrapper_status") != "active":
            issues.append("partial_without_package_read")
        if _mapping(evidence.get("adapter_conformance")).get("status") != "accepted":
            issues.append("partial_without_adapter")
        if _mapping(evidence.get("use_eligibility")).get("eligible") is not True:
            issues.append("partial_without_eligibility")
    return tuple(sorted(set(issues)))


def prove_raw_status_escalation_is_rejected(
    *, decided_at: str = DECIDED_AT_DEFAULT
) -> dict[str, Any]:
    """Seeded negative: raw gold status cannot escalate without an active wrapper."""
    request, evidence = build_fixture_adopted_package()
    evidence = copy.deepcopy(evidence)
    evidence["wrapper"] = None
    request = copy.deepcopy(request)
    request["claimed_authority_state"] = "certified"
    request["escalate_raw_status"] = True
    decision = evaluate_mode_a_package_read(request, evidence, decided_at=decided_at)
    return {
        "status": decision["status"],
        "rejection_reasons": list(decision["rejection_reasons"]),
        "production_eligible": decision["production_eligible"],
        "raw_status_escalation_rejected": "raw_status_escalation" in decision["rejection_reasons"],
    }


__all__ = [
    "ModeAVerticalSliceError",
    "build_fixture_adapter_observation",
    "build_fixture_adopted_package",
    "build_intended_inpaint_workflow",
    "build_producer_handoff_journal",
    "prove_raw_status_escalation_is_rejected",
    "reject_fabricated_downstream_receipt",
    "run_mode_a_vertical_slice",
    "validate_mode_a_vertical_slice_evidence",
]
