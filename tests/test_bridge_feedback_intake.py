from __future__ import annotations

import copy
import json
import runpy
from pathlib import Path

from maskfactory.bridge.feedback_intake import (
    FeedbackIntakeLedger,
    intake_bridge_feedback,
    validate_feedback_intake_evidence,
)
from maskfactory.validation import canonical_document_sha256

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/mask_bridge_contracts/positive_contract_set_v1.json"
REQUEST = ROOT / "tests/fixtures/mask_bridge_contracts/positive_mode_b_predict_request_v1.json"
RECEIPT = ROOT / "tests/fixtures/mask_bridge_contracts/positive_certified_mode_b_receipt_v1.json"
CERTIFICATE = (
    ROOT / "tests/fixtures/mask_bridge_contracts/positive_operational_autonomy_certificate_v1.json"
)
BUILDER = runpy.run_path(
    str(ROOT / "tests/fixtures/mask_bridge_contracts/build_contract_fixtures.py")
)
TRUSTED_KEYS = BUILDER["TRUSTED_KEYS"]


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sign(document: dict, field: str = "feedback_payload_sha256") -> None:
    BUILDER["sign"](document, field, "consumer_feedback", (field, "signature"))


def _base_bundle() -> dict:
    docs = _json(FIXTURES)
    request = _json(REQUEST)
    receipt = _json(RECEIPT)
    certificate = _json(CERTIFICATE)
    feedback = copy.deepcopy(docs["mask_repair_feedback"])
    return {
        "feedback": feedback,
        "parent_request": request,
        "parent_receipt": receipt,
        "certificate": certificate,
        "release_snapshot": docs["maskfactory_release_snapshot"],
        "capability_snapshot": docs["maskfactory_capability_snapshot"],
        "semantic_profile": {
            "profile_sha256": feedback["release_binding"]["semantic_profile_sha256"],
        },
        "current_policy": {
            "policy_id": receipt["use_eligibility"]["policy_id"],
            "policy_sha256": receipt["use_eligibility"]["policy_sha256"],
        },
        "qa_report": {
            "report_sha256": receipt["qa"]["report_sha256"],
            "blocking_failure_ids": ["boundary-softness"],
        },
        "current_parent_heads": {
            "request_payload_sha256": request["request_payload_sha256"],
            "receipt_payload_sha256": receipt["receipt_payload_sha256"],
            "certificate_payload_sha256": certificate["certificate_payload_sha256"],
        },
        "parent_bytes_before": {
            "parent_package_sha256": receipt["receipt_payload_sha256"],
            "parent_certificate_sha256": certificate["certificate_payload_sha256"],
        },
        "trusted_signing_keys": TRUSTED_KEYS,
        "decided_at": "2026-07-17T00:00:06Z",
    }


def _intake(bundle: dict, *, ledger: FeedbackIntakeLedger | None = None, **overrides):
    payload = {**bundle, **overrides}
    return intake_bridge_feedback(
        payload["feedback"],
        decided_at=payload["decided_at"],
        trusted_signing_keys=payload["trusted_signing_keys"],
        parent_request=payload["parent_request"],
        parent_receipt=payload["parent_receipt"],
        certificate=payload["certificate"],
        ledger=ledger if ledger is not None else FeedbackIntakeLedger(),
        release_snapshot=payload.get("release_snapshot"),
        capability_snapshot=payload.get("capability_snapshot"),
        semantic_profile=payload.get("semantic_profile"),
        current_policy=payload.get("current_policy"),
        qa_report=payload.get("qa_report"),
        current_parent_heads=payload.get("current_parent_heads"),
        revocation_status=payload.get("revocation_status"),
        write_attempt=payload.get("write_attempt"),
        parent_bytes_before=payload.get("parent_bytes_before"),
        parent_bytes_after=payload.get("parent_bytes_after"),
    )


def test_eligible_feedback_creates_immutable_child_candidate() -> None:
    bundle = _base_bundle()
    evidence = _intake(bundle)
    assert evidence["outcome"] == "candidate_created"
    assert evidence["status"] == "accepted"
    assert evidence["rejection_reasons"] == ["eligible"]
    assert evidence["child_candidate"]["mutates_parent"] is False
    assert evidence["child_candidate"]["creates_truth"] is False
    assert evidence["parent_preservation"]["parent_bytes_unchanged"] is True
    assert evidence["operational_repair_handoff"]["eligible_for_durable_repair"] is True
    assert validate_feedback_intake_evidence(evidence) == ()


def test_duplicate_hypothesis_rejected() -> None:
    bundle = _base_bundle()
    ledger = FeedbackIntakeLedger()
    first = _intake(bundle, ledger=ledger)
    assert first["outcome"] == "candidate_created"
    second_feedback = copy.deepcopy(bundle["feedback"])
    second_feedback["feedback_id"] = "mffb_0123456789abcdef01234568"
    second_feedback["authentication"]["nonce"] = "feedback-fixture-nonce-0002"
    second_feedback["defects"][0]["observation_sha256"] = "a" * 64
    _sign(second_feedback)
    second = _intake({**bundle, "feedback": second_feedback}, ledger=ledger)
    assert second["outcome"] == "rejected"
    assert "duplicate_hypothesis" in second["rejection_reasons"]
    assert "immaterial_hypothesis" in second["rejection_reasons"]


def test_no_progress_and_attempt_cap_quarantine() -> None:
    bundle = _base_bundle()
    feedback = copy.deepcopy(bundle["feedback"])
    feedback["progress_guard"]["no_progress_count"] = 2
    feedback["progress_guard"]["maximum_no_progress_count"] = 2
    feedback["requested_action"] = "quarantine_and_abstain"
    _sign(feedback)
    evidence = _intake({**bundle, "feedback": feedback})
    assert evidence["outcome"] == "quarantine_and_abstain"
    assert "no_progress_exhausted" in evidence["rejection_reasons"]

    capped = copy.deepcopy(bundle["feedback"])
    capped["feedback_id"] = "mffb_0123456789abcdef01234569"
    capped["authentication"]["nonce"] = "feedback-fixture-nonce-0003"
    capped["retry_budget"]["attempt"] = 3
    capped["retry_budget"]["maximum_attempts"] = 3
    capped["retry_budget"]["remaining_attempts"] = 0
    capped["requested_action"] = "quarantine_and_abstain"
    capped["hypothesis"]["hypothesis_id"] = "hypothesis-cap"
    capped["hypothesis"]["material_change_sha256"] = "b" * 64
    _sign(capped)
    cap_evidence = _intake({**bundle, "feedback": capped})
    assert cap_evidence["outcome"] == "quarantine_and_abstain"
    assert "attempt_cap_exhausted" in cap_evidence["rejection_reasons"]


def test_nonce_replay_and_feedback_id_collision() -> None:
    bundle = _base_bundle()
    ledger = FeedbackIntakeLedger()
    first = _intake(bundle, ledger=ledger)
    assert first["outcome"] == "candidate_created"

    replay = _intake(bundle, ledger=ledger)
    assert replay["outcome"] == "idempotent_replay"

    colliding = copy.deepcopy(bundle["feedback"])
    colliding["authentication"]["nonce"] = "feedback-fixture-nonce-0004"
    colliding["defects"][0]["severity"] = "high"
    _sign(colliding)
    collision = _intake({**bundle, "feedback": colliding}, ledger=ledger)
    assert collision["outcome"] == "rejected"
    assert "feedback_id_body_collision" in collision["rejection_reasons"]

    nonce_replay = copy.deepcopy(bundle["feedback"])
    nonce_replay["feedback_id"] = "mffb_0123456789abcdef0123456a"
    nonce_replay["hypothesis"]["hypothesis_id"] = "hypothesis-nonce"
    nonce_replay["hypothesis"]["material_change_sha256"] = "c" * 64
    # Reuse original nonce with a different body.
    nonce_replay["authentication"]["nonce"] = bundle["feedback"]["authentication"]["nonce"]
    _sign(nonce_replay)
    replayed = _intake({**bundle, "feedback": nonce_replay}, ledger=ledger)
    assert replayed["outcome"] == "rejected"
    assert "authentication_nonce_replay" in replayed["rejection_reasons"]


def test_forgery_rejected() -> None:
    bundle = _base_bundle()
    feedback = copy.deepcopy(bundle["feedback"])
    feedback["signature"]["value_base64"] = ("A" * 86) + "=="
    evidence = _intake({**bundle, "feedback": feedback})
    assert evidence["outcome"] == "rejected"
    assert (
        "feedback_forgery" in evidence["rejection_reasons"]
        or "feedback_document_invalid" in evidence["rejection_reasons"]
    )


def test_stale_parent_rejected() -> None:
    bundle = _base_bundle()
    heads = copy.deepcopy(bundle["current_parent_heads"])
    heads["receipt_payload_sha256"] = "f" * 64
    evidence = _intake(bundle, current_parent_heads=heads)
    assert evidence["outcome"] == "rejected"
    assert "stale_parent" in evidence["rejection_reasons"]


def test_unauthorized_write_and_parent_mutation_blocked() -> None:
    bundle = _base_bundle()
    evidence = _intake(
        bundle,
        write_attempt={"target_kind": "parent_certificate", "path": "frozen/cert.json"},
    )
    assert evidence["outcome"] == "rejected"
    assert "unauthorized_write_attempt" in evidence["rejection_reasons"]

    mutated = _intake(
        bundle,
        parent_bytes_after={
            "parent_package_sha256": "e" * 64,
            "parent_certificate_sha256": bundle["certificate"]["certificate_payload_sha256"],
        },
    )
    assert mutated["outcome"] == "rejected"
    assert "parent_mutation_blocked" in mutated["rejection_reasons"]


def test_conflicting_observation_rejected() -> None:
    bundle = _base_bundle()
    ledger = FeedbackIntakeLedger()
    first_feedback = copy.deepcopy(bundle["feedback"])
    first_feedback["requested_action"] = "package_revalidation"
    _sign(first_feedback)
    first = _intake({**bundle, "feedback": first_feedback}, ledger=ledger)
    assert first["outcome"] == "mining_only"

    conflict = copy.deepcopy(first_feedback)
    conflict["feedback_id"] = "mffb_0123456789abcdef0123456b"
    conflict["authentication"]["nonce"] = "feedback-fixture-nonce-0005"
    conflict["hypothesis"]["hypothesis_id"] = "hypothesis-conflict"
    conflict["hypothesis"]["material_change_sha256"] = "d" * 64
    conflict["defects"][0]["observation_sha256"] = "e" * 64
    _sign(conflict)
    evidence = _intake({**bundle, "feedback": conflict}, ledger=ledger)
    assert evidence["outcome"] == "rejected"
    assert "conflicting_observation" in evidence["rejection_reasons"]


def test_provider_subject_policy_protected_qa_drift_fail_closed() -> None:
    bundle = _base_bundle()

    provider = copy.deepcopy(bundle["feedback"])
    provider["provider_binding"]["stack_sha256"] = "1" * 64
    _sign(provider)
    assert (
        "provider_binding_drift" in _intake({**bundle, "feedback": provider})["rejection_reasons"]
    )

    subject = copy.deepcopy(bundle["feedback"])
    subject["subject_binding"]["scene_instance_id"] = "wrong-instance"
    _sign(subject)
    assert "subject_binding_drift" in _intake({**bundle, "feedback": subject})["rejection_reasons"]

    policy = copy.deepcopy(bundle["feedback"])
    policy["policy_binding"]["policy_sha256"] = "2" * 64
    _sign(policy)
    assert "policy_binding_drift" in _intake({**bundle, "feedback": policy})["rejection_reasons"]

    protected = copy.deepcopy(bundle["feedback"])
    protected["protected_artifact_bindings"] = []
    _sign(protected)
    assert (
        "protected_scope_mismatch"
        in _intake({**bundle, "feedback": protected})["rejection_reasons"]
    )

    qa = copy.deepcopy(bundle["feedback"])
    qa["qa_binding"]["blocking_failure_ids"] = ["invented-defect"]
    _sign(qa)
    assert "qa_failure_id_mismatch" in _intake({**bundle, "feedback": qa})["rejection_reasons"]


def test_policy_hash_and_schema_are_bound() -> None:
    import yaml

    policy = yaml.safe_load(
        (ROOT / "configs/bridge_feedback_intake_policy.yaml").read_text(encoding="utf-8")
    )
    assert policy["policy_sha256"] == canonical_document_sha256(
        policy, excluded_top_level_fields=("policy_sha256",)
    )
    bundle = _base_bundle()
    evidence = _intake(bundle)
    assert evidence["policy_id"] == "maskfactory-bridge-feedback-intake-v1"
    assert validate_feedback_intake_evidence(evidence) == ()
