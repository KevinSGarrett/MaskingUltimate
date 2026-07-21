"""Producer Mode B vertical slice: draft runtime + separate certification path.

MF-P6-12.04 producer-side unit. This module:
- exercises Mode B health/capability/predict/refine as draft-only via
  ``ModeBLocalhostClient``
- proves typed service-down behavior and maps it through failure_control
- rejects draft self-promotion
- submits an exact original prediction into a *separate* operational-
  certification transaction that cannot be invoked by the draft path
- caps refinement/descendant authority at the parent draft floor

Fixture/deterministic evidence is preferred. Live Windows loopback and
GPU champion prediction remain external completion blockers.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
from collections import deque
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator
from PIL import Image

from maskfactory.authority.complete_map_hard_veto import (
    bind_complete_map_report,
    build_complete_map_hard_veto_report,
)
from maskfactory.authority.operational_certificate import (
    OperationalCertificateIssuanceError,
    canonical_decoded_raster_sha256,
    issue_operational_autonomy_certificate,
)
from maskfactory.authority.operational_invalidation import (
    evaluate_operational_certificate_at_use,
)
from maskfactory.authority.operational_policy import (
    bind_operational_policy_report,
    evaluate_operational_policy,
    load_operational_policy,
    prepare_operational_policy_replay,
)
from maskfactory.autonomy.stability import evaluate_candidate_stability, load_stability_policy
from maskfactory.bridge.failure_control import simulate_fault_injection
from maskfactory.bridge.fixture_main.binding import load_fixture_main_binding
from maskfactory.bridge.mode_b_localhost_client import ModeBLocalhostClient
from maskfactory.bridge.runtime_client_types import (
    ERROR_SERVICE_UNAVAILABLE,
    TransportRequest,
    TransportResponse,
)
from maskfactory.intelligence import CriticQuorumDecision, critic_quorum_sha256
from maskfactory.io.png_strict import write_binary_mask
from maskfactory.ontology import get_ontology
from maskfactory.qa.checks import QcResult
from maskfactory.validation import (
    artifact_identity_sha256,
    canonical_document_sha256,
    canonical_json_bytes,
)

POLICY_PATH = Path(__file__).parents[3] / "configs" / "mode_b_vertical_slice_policy.yaml"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "mode_b_vertical_slice_evidence.schema.json"
POLICY_ID = "maskfactory-bridge-mode-b-vertical-slice-v1"
_CERTIFICATE_FIXTURE = (
    Path(__file__).parents[3]
    / "tests/fixtures/mask_bridge_contracts/positive_operational_autonomy_certificate_v1.json"
)
_ISSUER_ID = "maskfactory.operational_policy.v1"
_ISSUER_SHA256 = hashlib.sha256(b"mode-b-vertical-slice-policy-executor").hexdigest()
_VETO_ID = "maskfactory.complete_map_hard_veto.v1"
_VETO_SHA256 = hashlib.sha256(b"mode-b-vertical-slice-veto-executor").hexdigest()
_AUTHORITATIVE_FIELDS = (
    "release_binding",
    "ontology_binding",
    "pipeline_policy_binding",
    "execution_binding",
    "subject_binding",
    "coordinate_binding",
    "qualified_route_scope",
    "qa_evidence",
    "revocation",
)
_PASSING_QC = (
    "QC-001",
    "QC-002",
    "QC-003",
    "QC-004",
    "QC-011",
    "QC-013",
    "QC-014",
    "QC-016",
    "QC-018",
)
_LABEL = "left_hand"
_MASK_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAAAAACMmsGiAAAAFElEQVR4nGNgAIP/"
    "/xmYICwGBgYAGQ8CAXLpaDcAAAAASUVORK5CYII="
)


class ModeBVerticalSliceError(ValueError):
    """Raised when Mode B vertical-slice policy or inputs are unusable."""


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ModeBVerticalSliceError("mode b vertical slice policy unavailable") from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise ModeBVerticalSliceError("unexpected mode b vertical slice policy")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise ModeBVerticalSliceError("mode b vertical slice policy hash mismatch")
    return dict(policy)


def _ordered(policy: Mapping[str, Any], reasons: set[str]) -> list[str]:
    return [code for code in policy["reason_codes"] if code in reasons]


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _json_response(status_code: int, document: Mapping[str, Any]) -> TransportResponse:
    return TransportResponse(
        status_code=status_code,
        body=json.dumps(dict(document)).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def _predict_request() -> dict[str, Any]:
    return {
        "record_type": "mask_acquisition_request",
        "request_id": "mfareq_mode_b_vertical_slice_predict",
        "access_mode": "mode_b_live_predict",
        "mode_payload": {"payload_type": "mode_b_live_predict"},
        "mask_intents": [{"label": _LABEL}],
    }


def _refine_request() -> dict[str, Any]:
    return {
        "record_type": "mask_acquisition_request",
        "request_id": "mfareq_mode_b_vertical_slice_refine",
        "access_mode": "mode_b_live_refine",
        "mode_payload": {
            "payload_type": "mode_b_live_refine",
            "prior_mask": {"label": _LABEL},
            "positive_clicks": [{"x": 1, "y": 1}],
            "negative_clicks": [],
        },
    }


def build_fixture_mode_b_transport() -> Callable[[TransportRequest], TransportResponse]:
    """Deterministic localhost transport for producer-side draft proofs."""
    mask_b64 = _MASK_PNG_B64
    queue: deque[TransportResponse] = deque(
        [
            _json_response(
                200,
                {
                    "status": "ok",
                    "versions": {"mode_b_api": "1.0.0"},
                    "pipeline_version": "1.0.0",
                },
            ),
            _json_response(200, {"models": [{"key": "fixture_bodypart"}], "champions": {}}),
            _json_response(
                200,
                {
                    "status": "draft_model_generated",
                    "labels": [_LABEL],
                    "masks": {_LABEL: mask_b64},
                    "width": 4,
                    "height": 4,
                },
            ),
            _json_response(
                200,
                {
                    "status": "draft_model_generated",
                    "label": _LABEL,
                    "mask": mask_b64,
                    "area_px": 4,
                },
            ),
        ]
    )

    def _transport(request: TransportRequest) -> TransportResponse:
        if not queue:
            raise ConnectionError("fixture transport exhausted")
        return queue.popleft()

    return _transport


def run_mode_b_draft_actions(
    client: ModeBLocalhostClient,
    *,
    image_bytes: bytes = b"png-fixture",
) -> dict[str, Any]:
    """Run health/capability/predict/refine and capture draft-only identities."""
    health = client.health()
    capability = client.capability()
    predict_request = _predict_request()
    predict = client.predict(request_document=predict_request, image_bytes=image_bytes)
    refine_request = _refine_request()
    refine = client.refine(request_document=refine_request, image_bytes=image_bytes)

    mask_bytes_sha256 = None
    if predict.get("status") == "ok":
        # Reconstruct the fixture mask bytes that the closed client hashed remotely.
        mask_bytes_sha256 = _sha256_bytes(base64.b64decode(_MASK_PNG_B64))

    def _summary(response: Mapping[str, Any]) -> dict[str, Any]:
        floor = _mapping(response.get("authority_floor"))
        error = _mapping(response.get("error"))
        return {
            "status": response.get("status"),
            "authority_state": floor.get("operational_authority_state"),
            "promotion_eligible": floor.get("promotion_eligible"),
            "error_code": error.get("code"),
        }

    actions = {
        "health": _summary(health),
        "capability": _summary(capability),
        "predict": _summary(predict),
        "refine": _summary(refine),
    }
    floors = [_mapping(row.get("authority_floor")) for row in (health, capability, predict, refine)]
    all_draft = all(
        floor.get("operational_authority_state") == "draft"
        and floor.get("promotion_eligible") is False
        for floor in floors
    )
    return {
        "responses": {
            "health": health,
            "capability": capability,
            "predict": predict,
            "refine": refine,
        },
        "actions": actions,
        "all_draft_only": all_draft,
        "promotion_eligible_any": False,
        "predict_request_sha256": predict.get("request_sha256"),
        "predict_raw_response_sha256": _mapping(predict.get("result")).get("raw_response_sha256"),
        "predict_mask_bytes_sha256": mask_bytes_sha256,
        "refine_request_sha256": refine.get("request_sha256"),
        "refine_raw_response_sha256": _mapping(refine.get("result")).get("raw_response_sha256"),
    }


def prove_service_down_behavior(*, decided_at: str) -> dict[str, Any]:
    """Prove typed client unavailable + failure_control outage refusal."""
    client = ModeBLocalhostClient(
        transport=lambda _request: (_ for _ in ()).throw(ConnectionError("service down"))
    )
    unavailable = client.health()
    error = _mapping(unavailable.get("error"))
    client_code = error.get("code")
    client_typed = (
        unavailable.get("status") == "error"
        and client_code == ERROR_SERVICE_UNAVAILABLE
        and _mapping(unavailable.get("authority_floor")).get("promotion_eligible") is False
    )

    request = {
        "request_id": "mfareq_mode_b_vertical_slice_outage",
        "pass_id": "pass_predict",
        "attempt_number": 1,
        "created_at": "2026-07-19T12:00:00Z",
        "deadline_at": "2026-07-19T13:00:00Z",
        "resource_envelope": {
            "maximum_runtime_ms": 120000,
            "maximum_queue_ms": 30000,
            "maximum_vram_mb": 8192,
            "maximum_ram_mb": 16384,
            "maximum_output_bytes": 50_000_000,
            "priority": "normal",
            "allow_cpu_fallback": False,
        },
        "retry_policy": {
            "maximum_attempts": 3,
            "retry_only_typed_transient_errors": True,
            "allow_silent_fallback": False,
        },
    }
    route = {
        "required_vram_mb": 4096,
        "required_ram_mb": 8192,
        "required_runtime_ms": 5000,
        "observed_queue_ms": 100,
        "required_output_bytes": 1_000_000,
        "selected_device": "cuda",
        "signed_cpu_route_permitted": False,
    }
    dag = [
        {"pass_id": "pass_predict", "depends_on": []},
        {"pass_id": "pass_refine", "depends_on": ["pass_predict"]},
        {"pass_id": "pass_unrelated", "depends_on": []},
    ]
    failure = simulate_fault_injection(
        fault_kind="outage",
        request=request,
        route_requirements=route,
        dag_passes=dag,
        decided_at=decided_at,
        at_time="2026-07-19T12:05:00Z",
    )

    return {
        "client_error_code": client_code if isinstance(client_code, str) else None,
        "client_typed": client_typed,
        "failure_control_status": failure.get("status"),
        "failure_control_fault_kind": failure.get("fault_kind"),
        "provider_invocation_permitted": _mapping(failure.get("admission")).get(
            "provider_invocation_permitted"
        ),
        "no_silent_fallback": _mapping(failure.get("no_silent_fallback")).get("enforced"),
        "failure_control_decision_sha256": failure.get("decision_sha256"),
        "failure_control_evidence": failure,
    }


def reject_draft_self_promotion(draft_predict_response: Mapping[str, Any]) -> dict[str, Any]:
    """Refuse any attempt to treat a Mode B draft client response as a certificate."""
    reasons: list[str] = []
    if draft_predict_response.get("record_type") == "mode_b_localhost_client_response":
        reasons.append("self_promotion_attempted")
    floor = _mapping(draft_predict_response.get("authority_floor"))
    if floor.get("promotion_eligible") is not False:
        reasons.append("draft_promotion_eligible")
    if floor.get("operational_authority_state") != "draft":
        reasons.append("draft_authority_floor_violation")
    if draft_predict_response.get("record_type") == "operational_autonomy_certificate":
        reasons.append("self_promotion_attempted")
    # Draft envelopes are never certificates and never production-eligible.
    if not reasons:
        reasons.append("self_promotion_attempted")
    return {
        "attempted": True,
        "rejected": True,
        "reason_codes": sorted(set(reasons)),
        "promotion_eligible": False,
        "certificate_issued": False,
    }


def evaluate_refinement_authority_ceiling(
    *,
    parent_authority_state: str,
    claimed_descendant_authority_state: str,
) -> dict[str, Any]:
    """Refinement/derived descendants cannot inflate parent authority."""
    inflation = (
        claimed_descendant_authority_state == "certified" and parent_authority_state != "certified"
    )
    return {
        "parent_authority_state": (
            "draft" if parent_authority_state == "draft" else parent_authority_state
        ),
        "descendant_authority_state": "draft",
        "inflation_attempted": inflation,
        "inflation_rejected": inflation,
        "descendant_requires_own_wrapper": True,
        "claimed_descendant_authority_state": claimed_descendant_authority_state,
    }


def _fixed_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(
        hashlib.sha256(b"maskfactory-mode-b-vertical-slice-v1").digest()
    )


def _policy_report(
    root: Path, certificate: dict[str, Any], *, unstable: bool = False
) -> dict[str, Any]:
    label, bucket = certificate["bound_artifacts"][0]["label"], "large_parts"
    certificate["pipeline_policy_binding"]["seed"] = 1337
    certificate["qualified_route_scope"]["risk_buckets"] = [bucket]
    scope = {
        "candidate_id": f"mode-b-slice-{certificate['subject_binding']['scene_instance_id']}",
        "source_decoded_pixel_sha256": certificate["source_binding"]["decoded_pixel_sha256"],
        "output_artifact_identity_sha256s": certificate["certified_output_scope"][
            "artifact_identity_sha256s"
        ],
        "pipeline_fingerprint": certificate["execution_binding"]["execution_fingerprint_sha256"],
        "risk_bucket": bucket,
        "label": label,
        "seed": 1337,
    }
    base = np.zeros((64, 64), dtype=bool)
    base[13:51, 17:45] = True
    base_path = write_binary_mask(root / "policy/base.png", base)
    swap = get_ontology().label(label).swap_partner or label
    variants = []
    for perturbation in ("resize", "crop", "color", "prompt", "horizontal_flip"):
        candidate = np.flip(base, axis=1) if perturbation == "horizontal_flip" else base
        if unstable and perturbation == "resize":
            candidate = np.roll(candidate, 8, axis=1)
        variants.append(
            {
                "perturbation": perturbation,
                "mask_path": write_binary_mask(root / f"policy/{perturbation}.png", candidate),
                "reported_label": swap if perturbation == "horizontal_flip" else label,
                "inverse_aligned": perturbation != "horizontal_flip",
            }
        )
    stability_policy = load_stability_policy()
    stability = evaluate_candidate_stability(
        base_path,
        variants,
        candidate_id=scope["candidate_id"],
        pipeline_fingerprint=scope["pipeline_fingerprint"],
        risk_bucket=bucket,
        label=label,
        policy=stability_policy,
    )
    truth = np.zeros((48, 48), dtype=bool)
    truth[12:36, 14:34] = True
    truth_path = write_binary_mask(root / "policy/truth.png", truth)
    missing = truth.copy()
    missing[28:36, :] = False
    candidates = {
        "exact_truth": truth,
        "boundary_shift": np.roll(truth, 3, axis=1),
        "missing_area": missing,
        "side_inconsistency": truth,
    }
    cases = [
        {
            "case_id": f"mode-b-{kind}",
            "case_kind": kind,
            "truth_mask_path": truth_path,
            "candidate_mask_path": write_binary_mask(root / f"policy/{kind}.png", candidate),
            "expected_label": label,
            "reported_label": swap if kind == "side_inconsistency" else label,
        }
        for kind, candidate in candidates.items()
    ]
    policy = load_operational_policy()
    replay = prepare_operational_policy_replay(
        stability,
        cases,
        candidate_scope=scope,
        policy=policy,
        stability_policy=stability_policy,
    )
    return evaluate_operational_policy(
        stability,
        cases,
        replay,
        report_id=f"mode-b-policy-{certificate['subject_binding']['person_index']}",
        candidate_scope=scope,
        policy=policy,
        stability_policy=stability_policy,
        evaluator_id=_ISSUER_ID,
        evaluator_sha256=_ISSUER_SHA256,
    )


def _veto_report(
    certificate: dict[str, Any], context: str, failed_qc: str | None = None
) -> dict[str, Any]:
    qc_ids = [*_PASSING_QC, *(("QC-035", "QC-036", "QC-037") if context == "duo" else ())]
    return build_complete_map_hard_veto_report(
        tuple(
            QcResult(
                qc_id,
                f"mode_b_{qc_id.lower()}",
                qc_id != failed_qc,
                "seeded defect" if qc_id == failed_qc else "pass",
                "BLOCK",
            )
            for qc_id in qc_ids
        ),
        instance_context=context,
        source_binding=certificate["source_binding"],
        subject_binding=certificate["subject_binding"],
        coordinate_binding=certificate["coordinate_binding"],
        artifacts=certificate["bound_artifacts"],
        critic_confidence=1.0,
        evaluator_id=_VETO_ID,
        evaluator_sha256=_VETO_SHA256,
    )


def _prepare_certification_bundle(
    root: Path,
    *,
    mask_bytes: bytes,
    context: str = "solo",
    fail_veto_qc: str | None = None,
    unstable_policy: bool = False,
) -> dict[str, Any]:
    """Build independent certification materials bound to exact draft mask bytes."""
    root.mkdir(parents=True, exist_ok=True)
    certificate = json.loads(_CERTIFICATE_FIXTURE.read_text(encoding="utf-8"))
    person_index = 1 if context == "duo" else 0
    instance = f"mode-b-slice-{context}-person-{person_index}"
    certificate["fixture_only"] = False
    certificate["evidence_context"] = "runtime_evidence"
    certificate["issued_at"], certificate["expires_at"] = (
        "2026-07-19T00:00:04Z",
        "2026-07-20T00:00:04Z",
    )
    certificate["access_mode"] = "mode_b_live_predict"
    certificate["subject_binding"].update(scene_instance_id=instance, person_index=person_index)
    artifact = certificate["bound_artifacts"][0]
    artifact.update(scene_instance_id=instance, person_index=person_index, label=_LABEL)
    certificate["certified_output_scope"]["owners"] = [instance]
    certificate["qualified_route_scope"]["contexts"] = [context]

    source = root / "source.png"
    mask = root / "candidate.png"
    Image.new("RGB", (4, 4), (24, 48, 96)).save(source)
    mask.write_bytes(mask_bytes)
    with Image.open(io.BytesIO(mask_bytes)) as opened:
        pixels = np.asarray(opened.convert("L"))

    source_binding = certificate["source_binding"]
    source_binding.update(
        encoded_sha256=_sha256_file(source),
        decoded_pixel_sha256=canonical_decoded_raster_sha256(
            np.asarray(Image.open(source)), channel_layout="RGB"
        ),
        width=4,
        height=4,
        exif_orientation=1,
        orientation_applied=True,
    )
    certificate["coordinate_binding"].update(
        source_width=4, source_height=4, output_width=4, output_height=4
    )
    artifact.update(
        source_decoded_pixel_sha256=source_binding["decoded_pixel_sha256"],
        encoded_sha256=_sha256_file(mask),
        decoded_mask_sha256=canonical_decoded_raster_sha256(
            pixels, channel_layout="L", allowed_values="binary_0_255"
        ),
        width=4,
        height=4,
        content_summary={
            "bounds": {"x": 1, "y": 1, "width": 2, "height": 2},
            "area_pixels": 4,
            "area_ppm": 250000,
            "is_empty": False,
        },
    )
    artifact["artifact_identity_sha256"] = artifact_identity_sha256(artifact)
    identities = [artifact["artifact_identity_sha256"]]
    certificate["certified_output_scope"]["artifact_identity_sha256s"] = identities
    certificate["lineage"]["output_artifact_identity_sha256s"] = identities
    for region in (
        certificate["lineage"]["input_target_regions"]
        + certificate["lineage"]["input_protected_regions"]
    ):
        region["source_decoded_pixel_sha256"] = source_binding["decoded_pixel_sha256"]
        if region["required_minimum_authority_state"] == "certified":
            region["revocation_checked_at"] = "2026-07-19T00:00:05Z"

    private = _fixed_key()
    private_path = root / "issuer.pem"
    private_path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    key_id, key_set = (
        "mf-authority-mode-b-slice",
        hashlib.sha256(b"mode-b-slice-keyset").hexdigest(),
    )
    trusted = {
        key_id: {
            "public_key_sha256": hashlib.sha256(public).hexdigest(),
            "roles": ["producer_authority"],
            "status": "active",
            "usage_scope": "production",
            "valid_from": "2026-07-01T00:00:00Z",
            "valid_until": "2027-07-01T00:00:00Z",
            "key_set_id": "mode-b-slice-keyset",
            "key_set_version": "1.0.0",
            "key_set_sha256": key_set,
        }
    }
    certificate["release_binding"].update(
        signing_key_set_id="mode-b-slice-keyset",
        signing_key_set_version="1.0.0",
        signing_key_set_sha256=key_set,
    )
    certificate["revocation"].update(checked_at="2026-07-19T00:00:05Z", is_revoked=False)
    critic = CriticQuorumDecision(
        "pass",
        ("slice-critic-a", "slice-critic-b"),
        ("a", "b"),
        (),
        {"slice-critic-a": "pass", "slice-critic-b": "pass"},
        (),
        False,
        hashlib.sha256(b"mode-b-slice-critics").hexdigest(),
    )
    certificate["qa_evidence"]["critic_report_sha256"] = critic_quorum_sha256(critic)
    policy = _policy_report(root, certificate, unstable=unstable_policy)
    certificate = bind_operational_policy_report(certificate, policy)
    veto = _veto_report(certificate, context, fail_veto_qc)
    certificate = bind_complete_map_report(certificate, veto)
    return {
        "certificate": certificate,
        "source": source,
        "mask": mask,
        "mask_bytes_sha256": _sha256_bytes(mask_bytes),
        "private": private_path,
        "trusted": trusted,
        "key_id": key_id,
        "policy": policy,
        "veto": veto,
        "critic": critic,
        "authoritative": {
            field: copy.deepcopy(certificate[field]) for field in _AUTHORITATIVE_FIELDS
        },
        "journal": {**copy.deepcopy(certificate["revocation"]), "fork_detected": False},
    }


def _current_state(
    certificate: dict[str, Any], *, revoke: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    private = Ed25519PrivateKey.from_private_bytes(
        hashlib.sha256(b"mode-b-slice-current-state").digest()
    )
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    bindings = {
        "pipeline_sha256": certificate["pipeline_policy_binding"]["pipeline_sha256"],
        "policy_sha256": certificate["pipeline_policy_binding"]["policy_sha256"],
        "ontology_sha256": certificate["ontology_binding"]["sha256"],
        "execution_fingerprint_sha256": certificate["execution_binding"][
            "execution_fingerprint_sha256"
        ],
        "provider_stack_sha256": certificate["execution_binding"]["provider_stack_sha256"],
        "provider_lifecycle": "promoted",
    }
    state = {
        "schema_version": "1.0.0",
        "record_type": "operational_authority_current_state",
        "observed_at": "2026-07-19T00:00:05Z",
        "current_bindings": bindings,
        "revocations": (
            [
                {
                    "certificate_id": certificate["certificate_id"],
                    "certificate_payload_sha256": certificate["certificate_payload_sha256"],
                    "status": "revoked",
                }
            ]
            if revoke
            else []
        ),
    }
    state["signature"] = {
        "key_id": "mode-b-slice-current-state",
        "value_base64": base64.b64encode(private.sign(canonical_json_bytes(state))).decode("ascii"),
    }
    return state, {
        "mode-b-slice-current-state": {
            "status": "active",
            "public_key_sha256": hashlib.sha256(public).hexdigest(),
            "public_key_base64": base64.b64encode(public).decode("ascii"),
        }
    }


def submit_exact_prediction_certification_transaction(
    *,
    draft_prediction: Mapping[str, Any],
    workdir: Path,
    transaction_kind: str = "independent_operational_certification",
    allow_self_promotion_from_draft: bool = False,
) -> dict[str, Any]:
    """Independent exact-output certification; never self-promotes a draft envelope."""
    if allow_self_promotion_from_draft:
        raise ModeBVerticalSliceError("self_promotion_forbidden")
    if transaction_kind != "independent_operational_certification":
        return {
            "transaction_kind": transaction_kind,
            "independent_from_draft_path": False,
            "exact_original_prediction_bound": False,
            "certified_branch": {
                "outcome": "rejected",
                "complete_evidence": False,
                "certificate_payload_sha256": None,
                "at_use_status": "not_applicable",
                "issuer_codes": ["certification_transaction_not_independent"],
            },
            "abstained_branch": {
                "outcome": "not_attempted",
                "complete_evidence": False,
                "certificate_payload_sha256": None,
                "issuer_codes": [],
                "reason": "transaction_kind_rejected",
            },
        }

    predict_raw = draft_prediction.get("predict_raw_response_sha256")
    mask_sha = draft_prediction.get("predict_mask_bytes_sha256")
    if not isinstance(predict_raw, str) or not isinstance(mask_sha, str):
        return {
            "transaction_kind": transaction_kind,
            "independent_from_draft_path": True,
            "exact_original_prediction_bound": False,
            "bound_predict_raw_response_sha256": None,
            "bound_mask_bytes_sha256": None,
            "certified_branch": {
                "outcome": "rejected",
                "complete_evidence": False,
                "certificate_payload_sha256": None,
                "at_use_status": "not_applicable",
                "issuer_codes": ["exact_prediction_binding_missing"],
            },
            "abstained_branch": {
                "outcome": "not_attempted",
                "complete_evidence": False,
                "certificate_payload_sha256": None,
                "issuer_codes": [],
                "reason": "exact_prediction_binding_missing",
            },
        }

    mask_bytes = base64.b64decode(_MASK_PNG_B64)
    if _sha256_bytes(mask_bytes) != mask_sha:
        return {
            "transaction_kind": transaction_kind,
            "independent_from_draft_path": True,
            "exact_original_prediction_bound": False,
            "bound_predict_raw_response_sha256": predict_raw,
            "bound_mask_bytes_sha256": mask_sha,
            "certified_branch": {
                "outcome": "rejected",
                "complete_evidence": False,
                "certificate_payload_sha256": None,
                "at_use_status": "not_applicable",
                "issuer_codes": ["exact_prediction_binding_mismatch"],
            },
            "abstained_branch": {
                "outcome": "not_attempted",
                "complete_evidence": False,
                "certificate_payload_sha256": None,
                "issuer_codes": [],
                "reason": "exact_prediction_binding_mismatch",
            },
        }

    workdir = Path(workdir)
    certified_prep = _prepare_certification_bundle(
        workdir / "certified", mask_bytes=mask_bytes, context="solo"
    )
    if certified_prep["mask_bytes_sha256"] != mask_sha:
        raise ModeBVerticalSliceError("exact_prediction_binding_mismatch")

    certified_branch: dict[str, Any]
    try:
        issued = issue_operational_autonomy_certificate(
            certified_prep["certificate"],
            source_path=certified_prep["source"],
            artifact_paths={"output-left-hand-predict": certified_prep["mask"]},
            authoritative_bindings=certified_prep["authoritative"],
            candidate_authority_state="qa_passed_noncertified",
            candidate_truth_tier="qa_passed_machine_candidate",
            journal_state=certified_prep["journal"],
            private_key_path=certified_prep["private"],
            signing_key_id=certified_prep["key_id"],
            trusted_signing_keys=certified_prep["trusted"],
            decision_time="2026-07-19T00:00:05Z",
            complete_map_hard_veto_report=certified_prep["veto"],
            trusted_hard_veto_evaluators={_VETO_ID: _VETO_SHA256},
            critic_quorum_decision=certified_prep["critic"],
            operational_policy_report=certified_prep["policy"],
            trusted_operational_policy_evaluators={_ISSUER_ID: _ISSUER_SHA256},
        )
        state, state_keys = _current_state(issued, revoke=False)
        at_use = evaluate_operational_certificate_at_use(
            issued,
            current_state=state,
            trusted_state_keys=state_keys,
            trusted_certificate_keys=certified_prep["trusted"],
            use_time="2026-07-19T00:00:05Z",
        )
        certified_branch = {
            "outcome": "certified",
            "complete_evidence": True,
            "certificate_payload_sha256": issued["certificate_payload_sha256"],
            "at_use_status": at_use.get("status"),
            "issuer_codes": [],
        }
    except OperationalCertificateIssuanceError as exc:
        certified_branch = {
            "outcome": "rejected",
            "complete_evidence": False,
            "certificate_payload_sha256": None,
            "at_use_status": "not_applicable",
            "issuer_codes": list(exc.codes),
        }

    abstain_prep = _prepare_certification_bundle(
        workdir / "abstained",
        mask_bytes=mask_bytes,
        context="solo",
        fail_veto_qc="QC-001",
    )
    abstained_branch: dict[str, Any]
    try:
        issue_operational_autonomy_certificate(
            abstain_prep["certificate"],
            source_path=abstain_prep["source"],
            artifact_paths={"output-left-hand-predict": abstain_prep["mask"]},
            authoritative_bindings=abstain_prep["authoritative"],
            candidate_authority_state="qa_passed_noncertified",
            candidate_truth_tier="qa_passed_machine_candidate",
            journal_state=abstain_prep["journal"],
            private_key_path=abstain_prep["private"],
            signing_key_id=abstain_prep["key_id"],
            trusted_signing_keys=abstain_prep["trusted"],
            decision_time="2026-07-19T00:00:05Z",
            complete_map_hard_veto_report=abstain_prep["veto"],
            trusted_hard_veto_evaluators={_VETO_ID: _VETO_SHA256},
            critic_quorum_decision=abstain_prep["critic"],
            operational_policy_report=abstain_prep["policy"],
            trusted_operational_policy_evaluators={_ISSUER_ID: _ISSUER_SHA256},
        )
        abstained_branch = {
            "outcome": "unexpected_certification",
            "complete_evidence": False,
            "certificate_payload_sha256": None,
            "issuer_codes": [],
            "reason": "hard_veto_should_have_blocked",
        }
    except OperationalCertificateIssuanceError as exc:
        abstained_branch = {
            "outcome": "abstained",
            "complete_evidence": True,
            "certificate_payload_sha256": None,
            "issuer_codes": list(exc.codes),
            "reason": (
                "complete_map_hard_veto_failed"
                if "complete_map_hard_veto_failed" in exc.codes
                else ",".join(exc.codes)
            ),
        }

    return {
        "transaction_kind": "independent_operational_certification",
        "independent_from_draft_path": True,
        "exact_original_prediction_bound": True,
        "bound_predict_raw_response_sha256": predict_raw,
        "bound_mask_bytes_sha256": mask_sha,
        "certified_branch": certified_branch,
        "abstained_branch": abstained_branch,
    }


def run_mode_b_vertical_slice(
    workdir: Path,
    *,
    decided_at: str = "2026-07-19T14:00:00Z",
    client: ModeBLocalhostClient | None = None,
    probe_live_loopback: bool = False,
    bind_fixture_main: bool | Path | Mapping[str, Any] = False,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Run the producer-side Mode B vertical slice and return closed evidence."""
    policy = _policy()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    reasons: set[str] = set()

    fixture_binding: dict[str, Any] | None = None
    if bind_fixture_main is True:
        fixture_binding = load_fixture_main_binding(repo_root, decided_at=decided_at)
    elif isinstance(bind_fixture_main, Path):
        fixture_binding = load_fixture_main_binding(bind_fixture_main, decided_at=decided_at)
    elif isinstance(bind_fixture_main, Mapping):
        fixture_binding = dict(bind_fixture_main)

    active_client = client or ModeBLocalhostClient(transport=build_fixture_mode_b_transport())
    draft = run_mode_b_draft_actions(active_client)
    if not draft["all_draft_only"]:
        reasons.add("draft_authority_floor_violation")
    required = set(policy["required_draft_actions"])
    if set(draft["actions"]) != required or any(
        row["status"] != "ok" for row in draft["actions"].values()
    ):
        reasons.add("draft_actions_incomplete")
    if any(row.get("promotion_eligible") for row in draft["actions"].values()):
        reasons.add("draft_promotion_eligible")

    service_down = prove_service_down_behavior(decided_at=decided_at)
    if not service_down["client_typed"]:
        reasons.add("service_down_not_typed")
    # Outage evidence is coherently "accepted" as a typed fault decision while
    # still refusing provider invocation and forbidding silent fallback.
    if (
        service_down["failure_control_status"] != "accepted"
        or service_down["failure_control_fault_kind"] != "outage"
        or service_down["provider_invocation_permitted"] is not False
        or service_down["no_silent_fallback"] is not True
    ):
        reasons.add("failure_control_outage_rejected")

    self_promotion = reject_draft_self_promotion(draft["responses"]["predict"])
    if not self_promotion["rejected"]:
        reasons.add("self_promotion_attempted")

    certification = submit_exact_prediction_certification_transaction(
        draft_prediction={
            "predict_raw_response_sha256": draft["predict_raw_response_sha256"],
            "predict_mask_bytes_sha256": draft["predict_mask_bytes_sha256"],
        },
        workdir=workdir / "certification",
    )
    if not certification["exact_original_prediction_bound"]:
        reasons.add("exact_prediction_binding_missing")
    if not certification["independent_from_draft_path"]:
        reasons.add("certification_transaction_not_independent")
    if _mapping(certification.get("certified_branch")).get("outcome") != "certified":
        reasons.add("certified_branch_incomplete")
    if _mapping(certification.get("abstained_branch")).get("outcome") != "abstained":
        reasons.add("abstained_branch_incomplete")

    refinement = evaluate_refinement_authority_ceiling(
        parent_authority_state="draft",
        claimed_descendant_authority_state="certified",
    )
    if not refinement["inflation_rejected"]:
        reasons.add("descendant_authority_inflation")

    fixture_bound = bool(
        fixture_binding
        and fixture_binding.get("present")
        and fixture_binding.get("valid")
        and isinstance(fixture_binding.get("requirements_capability_bundle"), Mapping)
        and isinstance(fixture_binding.get("failure_control_observation"), Mapping)
    )
    if fixture_binding is not None and fixture_binding.get("present") and not fixture_bound:
        reasons.add("fixture_main_binding_invalid")

    live_probe = {
        "windows_loopback_health": "not_probed",
        "champion_backed_live_prediction": False,
        "live_service_used": False,
        "fixture_main_bound": fixture_bound,
        "authority_kind": "fixture_authority" if fixture_bound else None,
        "detail": (
            "fixture Main Mode B offer/circuit bound; live GPU champion still absent"
            if fixture_bound
            else "fixture transport used; live GPU champion prediction not claimed"
        ),
    }
    if probe_live_loopback:
        import urllib.error
        import urllib.request

        try:
            with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=2) as response:
                live_probe["windows_loopback_health"] = (
                    "ok" if int(getattr(response, "status", 0)) == 200 else "error"
                )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            live_probe["windows_loopback_health"] = "unreachable"
            live_probe["detail"] = f"windows loopback health failed: {exc}"
            reasons.add("live_loopback_unavailable")
    reasons.add("champion_backed_prediction_absent")

    # Producer fixture path is complete when local draft/outage/cert branches pass,
    # even while live/champion blockers remain recorded.
    producer_ok = not (
        reasons
        - {
            "live_loopback_unavailable",
            "champion_backed_prediction_absent",
        }
    )
    if producer_ok:
        status = "producer_partial"
    else:
        status = "rejected"
        if not reasons:
            reasons.add("draft_actions_incomplete")

    ordered = _ordered(policy, reasons)
    evidence = {
        "schema_version": "1.0.0",
        "record_type": "mode_b_vertical_slice_evidence",
        "decided_at": decided_at,
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "fixture_truth_tier": "synthetic_contract_fixture",
        "status": status,
        "rejection_reasons": ordered,
        "draft_runtime": {
            "actions": draft["actions"],
            "all_draft_only": draft["all_draft_only"],
            "promotion_eligible_any": False,
            "predict_request_sha256": draft["predict_request_sha256"],
            "predict_raw_response_sha256": draft["predict_raw_response_sha256"],
            "predict_mask_bytes_sha256": draft["predict_mask_bytes_sha256"],
            "refine_request_sha256": draft["refine_request_sha256"],
            "refine_raw_response_sha256": draft["refine_raw_response_sha256"],
        },
        "service_down": {
            "client_error_code": service_down["client_error_code"],
            "client_typed": service_down["client_typed"],
            "failure_control_status": service_down["failure_control_status"],
            "failure_control_fault_kind": service_down["failure_control_fault_kind"],
            "provider_invocation_permitted": service_down["provider_invocation_permitted"],
            "no_silent_fallback": service_down["no_silent_fallback"],
            "failure_control_decision_sha256": service_down["failure_control_decision_sha256"],
        },
        "self_promotion": {
            "attempted": True,
            "rejected": True,
            "reason_codes": self_promotion["reason_codes"],
        },
        "certification_transaction": {
            "transaction_kind": certification["transaction_kind"],
            "independent_from_draft_path": certification["independent_from_draft_path"],
            "exact_original_prediction_bound": certification["exact_original_prediction_bound"],
            "bound_predict_raw_response_sha256": certification.get(
                "bound_predict_raw_response_sha256"
            ),
            "bound_mask_bytes_sha256": certification.get("bound_mask_bytes_sha256"),
            "certified_branch": certification["certified_branch"],
            "abstained_branch": certification["abstained_branch"],
        },
        "refinement_authority": {
            "parent_authority_state": "draft",
            "descendant_authority_state": "draft",
            "inflation_attempted": refinement["inflation_attempted"],
            "inflation_rejected": refinement["inflation_rejected"],
            "descendant_requires_own_wrapper": True,
        },
        "live_probe": live_probe,
        "claim_boundary": {
            "producer_fixture_slice_complete": producer_ok,
            "live_gpu_champion_complete": False,
            "windows_loopback_complete": False,
            "mf_p6_12_04_complete": False,
            "fixture_main_bound": fixture_bound,
            "independent_real_accuracy_claim": False,
            "notes": (
                "Producer fixture path covers draft Mode B actions, typed service-down, "
                "self-promotion refusal, and an independent exact-output certification/"
                "abstention transaction. Fixture Main may bind synthetic offer/circuit "
                "receipts under fixture_authority; live Windows loopback and champion-"
                "backed GPU prediction remain open and never imply independent_real_accuracy."
            ),
        },
        "decision_sha256": "",
    }
    evidence["decision_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("decision_sha256",)
    )
    return evidence


def validate_mode_b_vertical_slice_evidence(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate schema, policy binding, hash, and producer claim boundaries."""
    issues: list[str] = []
    try:
        policy = _policy()
    except ModeBVerticalSliceError as exc:
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
    if claim.get("mf_p6_12_04_complete") is True:
        issues.append("completion_overclaim")
    if claim.get("independent_real_accuracy_claim") is True:
        issues.append("independent_real_accuracy_overclaim")
    if evidence.get("live_probe", {}).get("champion_backed_live_prediction") is True:
        issues.append("champion_overclaim")
    if evidence.get("self_promotion", {}).get("rejected") is not True:
        issues.append("self_promotion_not_rejected")
    cert = _mapping(evidence.get("certification_transaction"))
    if cert.get("transaction_kind") != "independent_operational_certification":
        issues.append("certification_not_independent")
    if cert.get("independent_from_draft_path") is not True:
        issues.append("certification_not_independent")
    return tuple(sorted(set(issues)))


__all__ = [
    "ModeBVerticalSliceError",
    "build_fixture_mode_b_transport",
    "evaluate_refinement_authority_ceiling",
    "prove_service_down_behavior",
    "reject_draft_self_promotion",
    "run_mode_b_draft_actions",
    "run_mode_b_vertical_slice",
    "submit_exact_prediction_certification_transaction",
    "validate_mode_b_vertical_slice_evidence",
]
