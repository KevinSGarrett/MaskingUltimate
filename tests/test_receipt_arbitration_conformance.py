from __future__ import annotations

import copy
from pathlib import Path

import yaml

from maskfactory.bridge.receipt_arbitration_conformance import (
    build_receipt_arbitration_conformance_evidence,
    comparable_scope_sha256,
    normalize_and_arbitrate_receipts,
    validate_receipt_arbitration_conformance_evidence,
)
from maskfactory.validation import canonical_document_sha256

POLICY_PATH = Path("configs/bridge_receipt_arbitration_conformance_policy.yaml")
RELEASE = "ffbef9cea69a8bbe7c51bf464d127c0d3ffbc9cdc24798d5ccb8eb1b969f215a"
CAPABILITY = "0515eaeff6a2242c1877d7ae7bce072736a8cebddb249bf28b25e119857fd230"
REVOCATION = "4444444444444444444444444444444444444444444444444444444444444444"
SOURCE = "3333333333333333333333333333333333333333333333333333333333333333"
TRANSFORM = "361555fb909a4648d3c4efc6e65458d9f4e50c7bd711b7aabc4495c1b09fae1f"


def _policy() -> dict:
    return yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))


def _heads(**overrides) -> dict:
    base = {
        "release_payload_sha256": RELEASE,
        "capability_snapshot_sha256": CAPABILITY,
        "revocation_index_sha256": REVOCATION,
        "ontology_version": "body_parts_v1",
        "required_authority_floor": "draft",
        "required_qa_status": "pass",
        "max_preservation_risk": 0.5,
        "max_total_ms": 60000,
        "max_peak_vram_mb": 24576,
        "max_uncertainty": 0.2,
    }
    base.update(overrides)
    return base


def _region(region_id: str, *, authority_state: str = "certified") -> dict:
    return {
        "region_id": region_id,
        "artifact_identity_sha256": "a" * 64,
        "encoded_sha256": "b" * 64,
        "decoded_mask_sha256": "c" * 64,
        "source_decoded_pixel_sha256": SOURCE,
        "artifact_type": "atomic",
        "owner_identity_sha256": "d" * 64,
        "coordinate_space": "output_pixel",
        "width": 512,
        "height": 512,
        "transform_chain_sha256": TRANSFORM,
        "transform_step_sequence": 0,
        "required_minimum_authority_state": authority_state,
        "authority_state": authority_state,
        "issuer_kind": "maskfactory_autonomous",
        "certificate_kind": (
            "exact_serving_route_output" if authority_state == "certified" else "none"
        ),
        "certificate_id": (
            "mfac_aaaaaaaaaaaaaaaaaaaaaaaa" if authority_state == "certified" else None
        ),
        "certificate_sha256": "e" * 64 if authority_state == "certified" else None,
        "certificate_scope_sha256": "f" * 64 if authority_state == "certified" else None,
        "certificate_status": "active" if authority_state == "certified" else "none",
        "certificate_exact_scope_match": authority_state == "certified",
        "revocation_checked_at": "2026-07-19T00:00:00Z" if authority_state == "certified" else None,
        "revocation_checkpoint_sha256": REVOCATION if authority_state == "certified" else None,
    }


def _receipt(
    *,
    access_mode: str,
    authority_state: str,
    receipt_suffix: str,
    total_ms: int = 4000,
    peak_vram_mb: int = 2048,
    uncertainty: float = 0.01,
    completed_at: str = "2026-07-19T00:00:05Z",
    artifact_kind: str = "atomic_visible",
    representation_class: str | None = None,
    package_certificate_active: bool = True,
    certificate_active: bool = True,
    person_index: int = 0,
) -> dict:
    certified = authority_state == "certified"
    receipt = {
        "schema_version": "1.0.0",
        "record_type": "mask_acquisition_receipt",
        "receipt_id": f"mfarec_{receipt_suffix}",
        "request_id": f"mfareq_{receipt_suffix}",
        "request_payload_sha256": "1" * 64,
        "project_id": "comfy-main-fixture",
        "run_id": "run-fixture",
        "job_id": "job-fixture",
        "pass_id": "pass-mask-fixture",
        "attempt_id": "attempt-1",
        "result": "succeeded",
        "access_mode": access_mode,
        "completed_at": completed_at,
        "media_scope": {
            "scope_kind": "still_image",
            "sequence_id": "sequence-fixture",
            "shot_id": "shot-fixture",
            "take_id": "take-fixture",
            "source_video_sha256": None,
            "decoded_frame_sha256": None,
            "frame_index": None,
        },
        "release_binding": {
            "release_payload_sha256": RELEASE,
            "capability_snapshot_sha256": CAPABILITY,
        },
        "source_binding": {"decoded_pixel_sha256": SOURCE},
        "subject_binding": {
            "character_id": "character-fixture",
            "character_revision": "1.0.0",
            "scene_instance_id": "scene-instance-001",
            "canonical_person_id": "person-canonical-001",
            "person_index": person_index,
        },
        "execution_observation": {
            "total_ms": total_ms,
            "resources": {"peak_vram_mb": peak_vram_mb},
        },
        "artifacts": [
            {
                "intent_id": "intent-left-hand",
                "label": "left_hand",
                "artifact_kind": artifact_kind,
                "mask_type": "atomic",
                "coordinate_space": "output_pixel",
                "decoded_mask_sha256": "9" * 64,
                **(
                    {"representation_class": representation_class}
                    if representation_class is not None
                    else {}
                ),
            }
        ],
        "transform_validation": {
            "transform_chain_sha256": TRANSFORM,
            "output_coordinate_space": "output_pixel",
        },
        "qa": {
            "status": "pass",
            "uncertainty": uncertainty,
            "blocking_failures": [],
        },
        "authority": {
            "authority_state": authority_state,
            "certificate_status": "active" if certified and certificate_active else "none",
            "certificate_exact_scope_match": bool(certified and certificate_active),
            "certificate_sha256": "8" * 64 if certified else None,
            "revocation_index_sha256": REVOCATION if certified else None,
        },
        "lineage": {
            "operation_kind": (
                "package_read" if access_mode == "mode_a_package_read" else "original_prediction"
            ),
            "package_certificate_status": (
                "active"
                if access_mode == "mode_a_package_read" and package_certificate_active
                else "none"
            ),
            "package_certificate_exact_scope_match": bool(
                access_mode == "mode_a_package_read" and package_certificate_active
            ),
            "input_target_regions": [_region("target-left-hand")],
            "input_protected_regions": [_region("protected-other-torso")],
        },
        "use_eligibility": {
            "exact_use_scope": "production_conditioning",
            "required_authority_state": "certified",
        },
        "receipt_payload_sha256": canonical_document_sha256(
            {"receipt_suffix": receipt_suffix, "access_mode": access_mode}
        ),
    }
    return receipt


def _candidate(candidate_id: str, receipt: dict, *, preservation_risk: float = 0.1) -> dict:
    return {
        "candidate_id": candidate_id,
        "receipt": receipt,
        "receipt_payload_sha256": receipt["receipt_payload_sha256"],
        "preservation_risk": preservation_risk,
    }


def _main_decision(arbitration: dict, *, outcome=None, selected=None, mutate=None) -> dict:
    policy = _policy()
    decision = {
        "outcome": outcome or arbitration["oracle_decision"]["outcome"],
        "selected_candidate_ids": list(
            selected
            if selected is not None
            else arbitration["oracle_decision"]["selected_candidate_ids"]
        ),
        "comparable_scope_sha256": arbitration["comparable_scope_sha256"],
        "receipt_payload_sha256s": sorted(
            row["receipt_payload_sha256"] for row in arbitration["evaluated"]
        ),
        "policy_sha256": policy["policy_sha256"],
        "signature": {
            "key_id": "comfy-main-arbitration-prod",
            "public_key_base64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "signed_payload_sha256": "b" * 64,
            "value_base64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        },
    }
    if mutate:
        mutate(decision)
    return decision


def test_policy_hash_is_self_consistent() -> None:
    policy = _policy()
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    assert policy["policy_sha256"] == expected


def test_wrapper_certified_mode_a_dominates_uncertified_mode_b_draft() -> None:
    mode_a = _receipt(
        access_mode="mode_a_package_read",
        authority_state="certified",
        receipt_suffix="aaaaaaaaaaaaaaaaaaaaaaaa",
        total_ms=9000,
    )
    mode_b = _receipt(
        access_mode="mode_b_live_predict",
        authority_state="draft",
        receipt_suffix="bbbbbbbbbbbbbbbbbbbbbbbb",
        total_ms=1000,
    )
    candidates = [
        _candidate("mode-b-draft", mode_b, preservation_risk=0.05),
        _candidate("mode-a-certified", mode_a, preservation_risk=0.2),
    ]
    # Input order puts cheaper draft first; oracle must still choose Mode A.
    arbitration = normalize_and_arbitrate_receipts(
        candidates, decided_at="2026-07-19T12:00:00Z", producer_heads=_heads()
    )
    assert arbitration["oracle_decision"]["outcome"] == "choose"
    assert arbitration["oracle_decision"]["selected_candidate_ids"] == ["mode-a-certified"]
    assert any(
        row["reason"] == "wrapper_mode_a_dominates_draft"
        for row in arbitration["dominance_eliminations"]
    )

    main = _main_decision(arbitration)
    evidence = build_receipt_arbitration_conformance_evidence(
        candidates, main, decided_at="2026-07-19T12:00:00Z", producer_heads=_heads()
    )
    assert evidence["status"] == "accepted"
    assert validate_receipt_arbitration_conformance_evidence(evidence) == ()


def test_mode_a_access_alone_does_not_outrank_certified_mode_b() -> None:
    mode_a_raw = _receipt(
        access_mode="mode_a_package_read",
        authority_state="qa_passed_noncertified",
        receipt_suffix="cccccccccccccccccccccccc",
        package_certificate_active=True,
        certificate_active=False,
    )
    mode_b = _receipt(
        access_mode="mode_b_live_predict",
        authority_state="certified",
        receipt_suffix="dddddddddddddddddddddddd",
    )
    candidates = [
        _candidate("mode-a-access-only", mode_a_raw),
        _candidate("mode-b-certified", mode_b),
    ]
    arbitration = normalize_and_arbitrate_receipts(
        candidates,
        decided_at="2026-07-19T12:00:00Z",
        producer_heads=_heads(required_authority_floor="qa_passed_noncertified"),
    )
    assert arbitration["oracle_decision"]["selected_candidate_ids"] == ["mode-b-certified"]


def test_close_alternatives_branch_or_abstain_deterministically() -> None:
    left = _receipt(
        access_mode="mode_b_live_predict",
        authority_state="certified",
        receipt_suffix="eeeeeeeeeeeeeeeeeeeeeeee",
        total_ms=4000,
    )
    right = _receipt(
        access_mode="mode_b_live_refine",
        authority_state="certified",
        receipt_suffix="ffffffffffffffffffffffff",
        total_ms=4000,
    )
    candidates = [_candidate("alt-b", right), _candidate("alt-a", left)]
    branched = normalize_and_arbitrate_receipts(
        candidates, decided_at="2026-07-19T12:00:00Z", producer_heads=_heads()
    )
    assert branched["oracle_decision"]["outcome"] == "branch"
    assert branched["oracle_decision"]["selected_candidate_ids"] == ["alt-a", "alt-b"]

    third = _receipt(
        access_mode="mode_b_live_predict",
        authority_state="certified",
        receipt_suffix="111111111111111111111111",
        total_ms=4000,
    )
    # Force a third same-scope candidate by cloning scope fields; distinct receipt hash.
    three = [
        _candidate("c1", left),
        _candidate("c2", right),
        _candidate("c3", third),
    ]
    abstained = normalize_and_arbitrate_receipts(
        three, decided_at="2026-07-19T12:00:00Z", producer_heads=_heads()
    )
    assert abstained["oracle_decision"]["outcome"] == "abstain"
    assert abstained["oracle_decision"]["selected_candidate_ids"] == []


def test_incompatible_scope_and_latent_never_rank() -> None:
    base = _receipt(
        access_mode="mode_b_live_predict",
        authority_state="certified",
        receipt_suffix="222222222222222222222222",
    )
    other_scope = copy.deepcopy(base)
    other_scope["subject_binding"]["person_index"] = 1
    other_scope["receipt_payload_sha256"] = "2" * 64
    latent = copy.deepcopy(base)
    latent["artifacts"][0]["representation_class"] = "engine_private_latent"
    latent["receipt_payload_sha256"] = "3" * 64

    scope_a = comparable_scope_sha256(base, ontology_version="body_parts_v1")
    scope_b = comparable_scope_sha256(other_scope, ontology_version="body_parts_v1")
    assert scope_a != scope_b

    try:
        normalize_and_arbitrate_receipts(
            [_candidate("a", base), _candidate("b", other_scope)],
            decided_at="2026-07-19T12:00:00Z",
            producer_heads=_heads(),
        )
        raised = False
    except Exception:
        raised = True
    assert raised

    same_scope_latent = normalize_and_arbitrate_receipts(
        [_candidate("latent", latent), _candidate("decoded", base)],
        decided_at="2026-07-19T12:00:00Z",
        producer_heads=_heads(),
    )
    assert same_scope_latent["oracle_decision"]["selected_candidate_ids"] == ["decoded"]
    latent_row = next(
        row for row in same_scope_latent["evaluated"] if row["candidate_id"] == "latent"
    )
    assert "incompatible_latent" in latent_row["ineligibility_reasons"]


def test_freshness_preservation_cost_and_no_silent_weakening() -> None:
    strong = _receipt(
        access_mode="mode_a_package_read",
        authority_state="certified",
        receipt_suffix="333333333333333333333333",
        total_ms=8000,
        completed_at="2026-07-19T00:00:05Z",
    )
    weak_cheap = _receipt(
        access_mode="mode_b_live_predict",
        authority_state="draft",
        receipt_suffix="444444444444444444444444",
        total_ms=500,
        completed_at="2026-07-19T11:59:00Z",
    )
    stale = _receipt(
        access_mode="mode_b_live_predict",
        authority_state="certified",
        receipt_suffix="555555555555555555555555",
        completed_at="2026-07-01T00:00:00Z",
    )
    candidates = [
        _candidate("strong", strong, preservation_risk=0.2),
        _candidate("weak-cheap", weak_cheap, preservation_risk=0.01),
        _candidate("stale", stale, preservation_risk=0.1),
    ]
    arbitration = normalize_and_arbitrate_receipts(
        candidates, decided_at="2026-07-19T12:00:00Z", producer_heads=_heads()
    )
    assert arbitration["oracle_decision"]["selected_candidate_ids"] == ["strong"]
    stale_row = next(row for row in arbitration["evaluated"] if row["candidate_id"] == "stale")
    assert "freshness_stale" in stale_row["ineligibility_reasons"]

    # Main tries to select the cheap draft anyway -> rejected as silent weakening.
    bad_main = _main_decision(
        arbitration,
        outcome="choose",
        selected=["weak-cheap"],
    )
    evidence = build_receipt_arbitration_conformance_evidence(
        candidates, bad_main, decided_at="2026-07-19T12:00:00Z", producer_heads=_heads()
    )
    assert evidence["status"] == "rejected"
    assert "main_decision_disagrees" in evidence["rejection_reasons"]
    assert "pass_requirement_weakened" in evidence["rejection_reasons"]


def test_order_invariance_and_shared_fixture_scope_probe() -> None:
    mode_a = _receipt(
        access_mode="mode_a_package_read",
        authority_state="certified",
        receipt_suffix="666666666666666666666666",
    )
    mode_b = _receipt(
        access_mode="mode_b_live_predict",
        authority_state="draft",
        receipt_suffix="777777777777777777777777",
    )
    forward = [
        _candidate("a", mode_a),
        _candidate("b", mode_b),
    ]
    reverse = list(reversed(forward))
    first = normalize_and_arbitrate_receipts(
        forward, decided_at="2026-07-19T12:00:00Z", producer_heads=_heads()
    )
    second = normalize_and_arbitrate_receipts(
        reverse, decided_at="2026-07-19T12:00:00Z", producer_heads=_heads()
    )
    assert first["oracle_decision"] == second["oracle_decision"]
    assert first["comparable_scope_sha256"] == second["comparable_scope_sha256"]

    # Shared frozen fixtures remain readable for scope identity without Mode A loader work.
    fixture_root = Path("tests/fixtures/mask_bridge_contracts")
    contract_set = __import__("json").loads(
        (fixture_root / "positive_contract_set_v1.json").read_text(encoding="utf-8")
    )
    mode_b_fixture = __import__("json").loads(
        (fixture_root / "positive_certified_mode_b_receipt_v1.json").read_text(encoding="utf-8")
    )
    mode_a_fixture = contract_set["mask_acquisition_receipt"]
    assert (
        mode_a_fixture["source_binding"]["decoded_pixel_sha256"]
        == mode_b_fixture["source_binding"]["decoded_pixel_sha256"]
    )
    assert (
        mode_a_fixture["transform_validation"]["transform_chain_sha256"]
        == mode_b_fixture["transform_validation"]["transform_chain_sha256"]
    )


def test_high_preservation_risk_and_authority_floor_reject() -> None:
    receipt = _receipt(
        access_mode="mode_b_live_predict",
        authority_state="draft",
        receipt_suffix="888888888888888888888888",
    )
    candidates = [_candidate("risky", receipt, preservation_risk=0.9)]
    arbitration = normalize_and_arbitrate_receipts(
        candidates,
        decided_at="2026-07-19T12:00:00Z",
        producer_heads=_heads(required_authority_floor="certified", max_preservation_risk=0.5),
    )
    assert arbitration["oracle_decision"]["outcome"] == "abstain"
    row = arbitration["evaluated"][0]
    assert "authority_insufficient" in row["ineligibility_reasons"]
    assert "preservation_risk_exceeds_budget" in row["ineligibility_reasons"]
