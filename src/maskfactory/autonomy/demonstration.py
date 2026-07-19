"""Deterministic, no-touch operational authority demonstration.

This module exercises the governed contracts with synthetic fixtures.  It is
evidence of contract behavior only: the generated certificates deliberately
retain ``training_gold_claim=false`` and make no real-world accuracy claim.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PIL import Image

from maskfactory.authority.complete_map_hard_veto import (
    bind_complete_map_report,
    build_complete_map_hard_veto_report,
)
from maskfactory.authority.operational_certificate import (
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
from maskfactory.autonomy.repair import (
    decide_bounded_repair,
    evaluate_repair_candidate,
    repair_limits_from_policy,
)
from maskfactory.autonomy.risk_buckets import canonical_sha256
from maskfactory.autonomy.stability import evaluate_candidate_stability, load_stability_policy
from maskfactory.intelligence import CriticQuorumDecision, critic_quorum_sha256
from maskfactory.io.png_strict import write_binary_mask
from maskfactory.ontology import get_ontology
from maskfactory.qa.checks import QcResult
from maskfactory.validation import (
    artifact_identity_sha256,
    canonical_json_bytes,
    require_valid_document,
)

_ROOT = Path(__file__).resolve().parents[3]
_CERTIFICATE_FIXTURE = (
    _ROOT / "tests/fixtures/mask_bridge_contracts/positive_operational_autonomy_certificate_v1.json"
)
_ISSUER_ID = "maskfactory.operational_policy.v1"
_ISSUER_SHA256 = hashlib.sha256(b"autonomous-demonstration-policy-executor").hexdigest()
_VETO_ID = "maskfactory.complete_map_hard_veto.v1"
_VETO_SHA256 = hashlib.sha256(b"autonomous-demonstration-veto-executor").hexdigest()
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


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixed_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(
        hashlib.sha256(b"maskfactory-autonomous-demonstration-v1").digest()
    )


def _policy_report(
    root: Path, certificate: dict[str, Any], *, unstable: bool = False
) -> dict[str, Any]:
    label, bucket = certificate["bound_artifacts"][0]["label"], "large_parts"
    certificate["pipeline_policy_binding"]["seed"] = 1337
    certificate["qualified_route_scope"]["risk_buckets"] = [bucket]
    scope = {
        "candidate_id": f"demo-{certificate['subject_binding']['scene_instance_id']}",
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
            "case_id": f"demo-{kind}",
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
        report_id=f"demo-policy-{certificate['subject_binding']['person_index']}",
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
                f"demo_{qc_id.lower()}",
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


def _prepared_fixture(root: Path, *, context: str) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    certificate = json.loads(_CERTIFICATE_FIXTURE.read_text(encoding="utf-8"))
    person_index = 1 if context == "duo" else 0
    instance = f"demo-{context}-person-{person_index}"
    certificate["fixture_only"] = False
    certificate["evidence_context"] = "runtime_evidence"
    certificate["issued_at"], certificate["expires_at"] = (
        "2026-07-19T00:00:04Z",
        "2026-07-20T00:00:04Z",
    )
    certificate["subject_binding"].update(scene_instance_id=instance, person_index=person_index)
    artifact = certificate["bound_artifacts"][0]
    artifact.update(scene_instance_id=instance, person_index=person_index)
    certificate["certified_output_scope"]["owners"] = [instance]
    certificate["qualified_route_scope"]["contexts"] = [context]
    source = root / "source.png"
    mask = root / "candidate.png"
    Image.new("RGB", (4, 4), (24, 48, 96)).save(source)
    pixels = np.zeros((4, 4), dtype=np.uint8)
    pixels[1:3, 1:3] = 255
    Image.fromarray(pixels, mode="L").save(mask)
    source_binding = certificate["source_binding"]
    source_binding.update(
        encoded_sha256=_sha_file(source),
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
        encoded_sha256=_sha_file(mask),
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
    key_id, key_set = "mf-authority-demo", hashlib.sha256(b"demo-authority-keyset").hexdigest()
    trusted = {
        key_id: {
            "public_key_sha256": hashlib.sha256(public).hexdigest(),
            "roles": ["producer_authority"],
            "status": "active",
            "usage_scope": "production",
            "valid_from": "2026-07-01T00:00:00Z",
            "valid_until": "2027-07-01T00:00:00Z",
            "key_set_id": "demo-keyset",
            "key_set_version": "1.0.0",
            "key_set_sha256": key_set,
        }
    }
    certificate["release_binding"].update(
        signing_key_set_id="demo-keyset",
        signing_key_set_version="1.0.0",
        signing_key_set_sha256=key_set,
    )
    certificate["revocation"].update(checked_at="2026-07-19T00:00:05Z", is_revoked=False)
    critic = CriticQuorumDecision(
        "pass",
        ("demo-critic-a", "demo-critic-b"),
        ("a", "b"),
        (),
        {"demo-critic-a": "pass", "demo-critic-b": "pass"},
        (),
        False,
        hashlib.sha256(b"demo-critics").hexdigest(),
    )
    certificate["qa_evidence"]["critic_report_sha256"] = critic_quorum_sha256(critic)
    policy = _policy_report(root, certificate)
    certificate = bind_operational_policy_report(certificate, policy)
    veto = _veto_report(certificate, context)
    certificate = bind_complete_map_report(certificate, veto)
    return {
        "certificate": certificate,
        "source": source,
        "mask": mask,
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


def _issue(prepared: dict[str, Any]) -> dict[str, Any]:
    return issue_operational_autonomy_certificate(
        prepared["certificate"],
        source_path=prepared["source"],
        artifact_paths={"output-left-hand-predict": prepared["mask"]},
        authoritative_bindings=prepared["authoritative"],
        candidate_authority_state="qa_passed_noncertified",
        candidate_truth_tier="qa_passed_machine_candidate",
        journal_state=prepared["journal"],
        private_key_path=prepared["private"],
        signing_key_id=prepared["key_id"],
        trusted_signing_keys=prepared["trusted"],
        decision_time="2026-07-19T00:00:05Z",
        complete_map_hard_veto_report=prepared["veto"],
        trusted_hard_veto_evaluators={_VETO_ID: _VETO_SHA256},
        critic_quorum_decision=prepared["critic"],
        operational_policy_report=prepared["policy"],
        trusted_operational_policy_evaluators={_ISSUER_ID: _ISSUER_SHA256},
    )


def _current_state(
    certificate: dict[str, Any], *, revoke: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    private = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"demo-current-state").digest())
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
        "key_id": "demo-current-state",
        "value_base64": base64.b64encode(private.sign(canonical_json_bytes(state))).decode("ascii"),
    }
    return state, {
        "demo-current-state": {
            "status": "active",
            "public_key_base64": base64.b64encode(public).decode("ascii"),
        }
    }


def run_autonomous_gold_demonstration(workdir: Path) -> dict[str, Any]:
    """Run all deterministic branches and return a schema-validated report."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    accepted = _prepared_fixture(workdir / "accepted_single", context="solo")
    accepted_certificate = _issue(accepted)
    state, state_keys = _current_state(accepted_certificate, revoke=False)
    accepted_at_use = evaluate_operational_certificate_at_use(
        accepted_certificate,
        current_state=state,
        trusted_state_keys=state_keys,
        trusted_certificate_keys=accepted["trusted"],
        use_time="2026-07-19T00:00:05Z",
    )
    repaired = _prepared_fixture(workdir / "repaired_multi", context="duo")
    shape = (64, 64)
    current = np.zeros(shape, dtype=bool)
    candidate = current.copy()
    candidate[20:28, 20:28] = True
    guard = evaluate_repair_candidate(
        candidate,
        current_mask=current,
        protected_mask=np.zeros(shape, dtype=bool),
        label="left_hand",
        roi_xyxy=(8, 8, 56, 56),
        person_bbox_xyxy=(0, 0, 64, 64),
        ordinary_max_changed_fraction=500.0,
        reconstruction_max_changed_fraction=500.0,
        maximum_protected_overlap_fraction=0.0,
        maximum_outside_roi_fraction=0.0,
        expected_area_slack=1.0,
    )
    repair_decision = decide_bounded_repair(
        accepted_parent_id="demo-duo-parent",
        hypothesis_id="repair-v1",
        guard=guard,
        current_score_ppm=900000,
        attempt_elapsed_seconds=1.0,
        attempt_resource_units=1.0,
        limits=repair_limits_from_policy(
            {
                "maximum_attempts_per_label": 3,
                "maximum_elapsed_seconds_per_label": 300,
                "maximum_resource_units_per_label": 12,
                "maximum_no_progress_attempts": 2,
                "minimum_score_improvement_ppm": 1000,
            }
        ),
    )
    repaired_certificate = _issue(repaired)
    abstained = _prepared_fixture(workdir / "abstained_single", context="solo")
    unstable = _policy_report(workdir / "abstained_single", abstained["certificate"], unstable=True)
    unsafe = evaluate_repair_candidate(
        np.ones(shape, dtype=bool),
        current_mask=current,
        protected_mask=np.zeros(shape, dtype=bool),
        label="left_hand",
        roi_xyxy=(8, 8, 56, 56),
        person_bbox_xyxy=(0, 0, 64, 64),
        ordinary_max_changed_fraction=0.01,
        reconstruction_max_changed_fraction=0.01,
        maximum_protected_overlap_fraction=0.0,
        maximum_outside_roi_fraction=0.0,
        expected_area_slack=0.0,
    )
    abstain_decision = decide_bounded_repair(
        accepted_parent_id="demo-abstain-parent",
        hypothesis_id="unsafe-v1",
        guard=unsafe,
        current_score_ppm=0,
        attempt_elapsed_seconds=1.0,
        attempt_resource_units=1.0,
        limits=repair_limits_from_policy(
            {
                "maximum_attempts_per_label": 1,
                "maximum_elapsed_seconds_per_label": 300,
                "maximum_resource_units_per_label": 12,
                "maximum_no_progress_attempts": 2,
                "minimum_score_improvement_ppm": 1000,
            }
        ),
    )
    revoked = _prepared_fixture(workdir / "revoked_multi", context="duo")
    revoked_certificate = _issue(revoked)
    revoked_state, revoked_keys = _current_state(revoked_certificate, revoke=True)
    revoked_at_use = evaluate_operational_certificate_at_use(
        revoked_certificate,
        current_state=revoked_state,
        trusted_state_keys=revoked_keys,
        trusted_certificate_keys=revoked["trusted"],
        use_time="2026-07-19T00:00:05Z",
    )
    veto_cases = []
    for context, qc in (("solo", "QC-001"), ("duo", "QC-035")):
        fixture = _prepared_fixture(workdir / f"veto_{context}", context=context)
        report = _veto_report(fixture["certificate"], context, qc)
        fixture["veto"] = report
        try:
            _issue(fixture)
        except Exception as exc:  # The report preserves the typed issuer rejection.
            veto_cases.append(
                {
                    "context": context,
                    "failed_qc_id": qc,
                    "issuer_rejected": "complete_map_hard_veto_failed" in getattr(exc, "codes", ()),
                }
            )
    branches = [
        {
            "case_id": "accepted_single",
            "context": "solo",
            "outcome": "accepted_certified",
            "certificate_payload_sha256": accepted_certificate["certificate_payload_sha256"],
            "at_use_status": accepted_at_use["status"],
        },
        {
            "case_id": "repaired_multi",
            "context": "duo",
            "outcome": repair_decision.outcome,
            "certificate_payload_sha256": repaired_certificate["certificate_payload_sha256"],
            "at_use_status": "not_exercised",
            "repair": asdict(repair_decision),
        },
        {
            "case_id": "abstained_single",
            "context": "solo",
            "outcome": abstain_decision.outcome,
            "certificate_payload_sha256": None,
            "at_use_status": "not_applicable",
            "repair": asdict(abstain_decision),
            "policy_status": unstable["decision"]["status"],
        },
        {
            "case_id": "revoked_multi",
            "context": "duo",
            "outcome": "revoked_at_use",
            "certificate_payload_sha256": revoked_certificate["certificate_payload_sha256"],
            "at_use_status": revoked_at_use["status"],
            "at_use_reasons": revoked_at_use["reasons"],
        },
    ]
    report = {
        "schema_version": "1.0.0",
        "report_id": "mf-p6-08-08-autonomous-demonstration-v1",
        "fixture_truth_tier": "synthetic_contract_fixture",
        "manual_approval_used": False,
        "branches": branches,
        "hard_veto_cases": veto_cases,
        "zero_hard_veto_bypass": all(row["issuer_rejected"] for row in veto_cases),
    }
    report["report_sha256"] = canonical_sha256(report)
    require_valid_document(report, "autonomous_gold_demonstration_report")
    return report


def verify_autonomous_gold_demonstration(report: dict[str, Any]) -> None:
    require_valid_document(report, "autonomous_gold_demonstration_report")
    unsigned = {key: value for key, value in report.items() if key != "report_sha256"}
    if report["report_sha256"] != canonical_sha256(unsigned):
        raise ValueError("autonomous demonstration report hash mismatch")
    outcomes = {row["case_id"]: row["outcome"] for row in report["branches"]}
    if outcomes != {
        "accepted_single": "accepted_certified",
        "repaired_multi": "accepted_reversible_repair",
        "abstained_single": "rolled_back_abstain",
        "revoked_multi": "revoked_at_use",
    }:
        raise ValueError("autonomous demonstration branch coverage is incomplete")
    if report["manual_approval_used"] or not report["zero_hard_veto_bypass"]:
        raise ValueError("autonomous demonstration authority boundary failed")
