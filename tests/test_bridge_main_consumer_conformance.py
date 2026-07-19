"""Focused producer tests for Main-consumer conformance fixture packs."""

from __future__ import annotations

import json
from pathlib import Path

from maskfactory.bridge.external_adapter_conformance import (
    build_external_adapter_conformance_evidence,
)
from maskfactory.bridge.main_consumer_conformance import (
    evaluate_disagreement_vectors,
    load_adapter_observation_template,
    load_disagreement_vectors,
    load_fixture_pack,
    load_golden_vectors,
    load_receipt_shape,
    run_main_consumer_conformance_harness,
    validate_main_consumer_conformance_evidence,
)
from maskfactory.validation import ADOPTION_REVALIDATION_TRIGGERS, schema_validator

ROOT = Path(__file__).resolve().parents[1]


def _minimal_receipt(decision: str) -> dict:
    shape = load_receipt_shape(decision)
    checks = sorted(shape["required_compatibility_checks"])
    required_decision = "accepted" if decision in {"adopted", "partially_adopted"} else "rejected"
    optional_decision = "accepted" if decision == "adopted" else "rejected"
    return {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_adoption_receipt",
        "adoption_id": "mfadopt_0123456789abcdef01234567",
        "decided_at": "2026-07-19T00:00:00Z",
        "adoption_scope": shape["adoption_scope"],
        "evidence_context": shape["evidence_context"],
        "fixture_only": shape["fixture_only"],
        "production_use_authorized": shape["production_use_authorized"],
        "consumer": {
            "project": "Comfy_UI_Main",
            "controller_version": "1.0.0",
            "git_commit": "1" * 40,
        },
        "release_id": "mfr_20260719_0123456789ab",
        "release_payload_sha256": "a" * 64,
        "capability_snapshot_id": "mfcap_0123456789abcdef01234567",
        "capability_snapshot_sha256": "b" * 64,
        "consumer_requirements_id": "mfreq_0123456789abcdef01234567",
        "consumer_requirements_sha256": "c" * 64,
        "qualification_bundle_id": "mfqual_0123456789abcdef01234567",
        "qualification_bundle_sha256": "d" * 64,
        "trust_binding": {
            "producer_key_set_id": "producer",
            "producer_key_set_version": "1",
            "producer_key_set_sha256": "e" * 64,
            "producer_release_key_id": "producer-release",
            "producer_release_public_key_sha256": "f" * 64,
            "consumer_key_set_id": "consumer",
            "consumer_key_set_version": "1",
            "consumer_key_set_sha256": "1" * 64,
            "consumer_adoption_key_id": "comfy-main-adoption-prod",
            "consumer_adoption_public_key_sha256": "2" * 64,
            "rotation_policy_sha256": "3" * 64,
            "revocation_policy_sha256": "4" * 64,
        },
        "journal_checkpoint": {
            "stream_id": "stream",
            "genesis_event_id": "evt0",
            "genesis_event_sha256": "5" * 64,
            "first_sequence": 1,
            "last_sequence": 1,
            "event_count": 1,
            "head_event_id": "evt0",
            "head_event_sha256": "5" * 64,
            "revocation_state_sha256": "6" * 64,
            "active_revocation_count": 0,
            "validator_sha256": "7" * 64,
            "checkpointed_at": "2026-07-19T00:00:00Z",
            "fresh_until": "2026-07-20T00:00:00Z",
        },
        "decision": decision,
        "required_capabilities_satisfied": shape["required_capabilities_satisfied"],
        "compatibility_checks": [
            {"check": check, "result": "pass", "evidence_sha256": "8" * 64} for check in checks
        ],
        "capability_decisions": [
            {
                "capability_id": "mask.package.read",
                "requirement_class": "required",
                "decision": required_decision,
                "reason": "fixture",
                "evidence_sha256": "9" * 64,
            },
            {
                "capability_id": "mask.live.predict",
                "requirement_class": "optional",
                "decision": optional_decision,
                "reason": "fixture",
                "evidence_sha256": "0" * 64,
            },
        ],
        "pinned_artifacts": (
            [{"kind": "adapter", "sha256": "a" * 64}] if decision != "rejected" else []
        ),
        "accepted_capabilities": (["mask.package.read"] if required_decision == "accepted" else [])
        + (["mask.live.predict"] if optional_decision == "accepted" else []),
        "rejected_capabilities": (
            []
            if required_decision == "accepted" and optional_decision == "accepted"
            else (
                ["mask.live.predict"]
                if required_decision == "accepted"
                else ["mask.package.read", "mask.live.predict"]
            )
        ),
        "valid_until": "2026-07-20T00:00:00Z",
        "use_time_recheck_required": True,
        "revalidation_triggers": sorted(ADOPTION_REVALIDATION_TRIGGERS),
        "adoption_payload_sha256": "b" * 64,
        "signature": {
            "algorithm": "ed25519",
            "key_id": "comfy-main-adoption-prod",
            "public_key_base64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "signed_payload_sha256": "c" * 64,
            "signed_payload_format": "sha256_digest_bytes",
            "value_base64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        },
    }


def test_schema_registry_includes_main_consumer_conformance_evidence() -> None:
    assert schema_validator("main_consumer_conformance_evidence")


def test_fixture_pack_pins_receipt_shapes_and_adapter_templates() -> None:
    pack = load_fixture_pack()
    assert pack["status"] == "ready"
    assert pack["manifest"]["claim_boundary"]["main_adoption_complete"] is False

    adopted = load_receipt_shape("adopted", pack=pack)
    rejected = load_receipt_shape("rejected", pack=pack)
    partial = load_receipt_shape("partially_adopted", pack=pack)
    assert adopted["decision"] == "adopted"
    assert rejected["decision"] == "rejected"
    assert partial["decision"] == "partially_adopted"
    assert adopted["claim_boundary"]["shape_is_not_main_adoption_evidence"] is True

    accepted = load_adapter_observation_template("adapter_observation_accepted_v1", pack=pack)
    dirty = load_adapter_observation_template(
        "adapter_observation_rejected_dirty_worktree_v1", pack=pack
    )
    evidence = build_external_adapter_conformance_evidence(
        accepted["observation"], decided_at="2026-07-19T12:00:00Z"
    )
    assert evidence["status"] == "accepted"
    dirty_evidence = build_external_adapter_conformance_evidence(
        dirty["observation"], decided_at="2026-07-19T12:00:00Z"
    )
    assert dirty_evidence["status"] == "rejected"
    assert "adapter_dirty_worktree" in dirty_evidence["rejection_reasons"]


def test_disagreement_golden_vectors_pass_fail_closed_oracle() -> None:
    vectors = load_disagreement_vectors()
    assert len(vectors["vectors"]) == 7
    results = evaluate_disagreement_vectors()
    assert {row["status"] for row in results} == {"passed"}
    assert {row["vector_id"] for row in results} == {row["id"] for row in vectors["vectors"]}


def test_harness_awaits_main_and_never_fabricates_adoption(tmp_path: Path) -> None:
    evidence = run_main_consumer_conformance_harness(main_artifact_root=tmp_path)
    assert evidence["status"] == "awaiting_main"
    assert evidence["main_artifacts_present"] is False
    assert evidence["main_adoption_complete"] is False
    assert "main_artifact_missing" in evidence["rejection_reasons"]
    assert evidence["claim_boundary"]["producer_fixture_pack_is_not_main_adoption"] is True
    assert validate_main_consumer_conformance_evidence(evidence) == ()

    golden = load_golden_vectors()
    awaiting = next(
        row for row in golden["vectors"] if row["id"] == "producer_pack_ready_awaiting_main"
    )
    assert awaiting["expected_harness_status"] == evidence["status"]
    assert awaiting["expected_main_adoption_complete"] is evidence["main_adoption_complete"]


def test_harness_accepts_main_supplied_artifacts_without_claiming_adoption(tmp_path: Path) -> None:
    receipt = _minimal_receipt("adopted")
    observation = load_adapter_observation_template("adapter_observation_accepted_v1")[
        "observation"
    ]
    (tmp_path / "adoption_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (tmp_path / "adapter_observation.json").write_text(
        json.dumps(observation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    evidence = run_main_consumer_conformance_harness(main_artifact_root=tmp_path)
    assert evidence["status"] == "accepted"
    assert evidence["main_artifacts_present"] is True
    assert evidence["main_adoption_complete"] is False
    assert evidence["rejection_reasons"] == ["eligible"]
    assert validate_main_consumer_conformance_evidence(evidence) == ()


def test_harness_rejects_fabricated_fixture_only_adopted_receipt(tmp_path: Path) -> None:
    receipt = _minimal_receipt("adopted")
    receipt["fixture_only"] = True
    observation = load_adapter_observation_template("adapter_observation_accepted_v1")[
        "observation"
    ]
    (tmp_path / "adoption_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    (tmp_path / "adapter_observation.json").write_text(json.dumps(observation), encoding="utf-8")

    evidence = run_main_consumer_conformance_harness(main_artifact_root=tmp_path)
    assert evidence["status"] == "rejected"
    assert "main_adoption_receipt_shape_mismatch" in evidence["rejection_reasons"] or (
        "main_fabrication_claim_forbidden" in evidence["rejection_reasons"]
    )
    assert evidence["main_adoption_complete"] is False


def test_harness_rejects_dirty_adapter_observation(tmp_path: Path) -> None:
    receipt = _minimal_receipt("rejected")
    observation = load_adapter_observation_template(
        "adapter_observation_rejected_dirty_worktree_v1"
    )["observation"]
    (tmp_path / "adoption_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    (tmp_path / "adapter_observation.json").write_text(json.dumps(observation), encoding="utf-8")

    evidence = run_main_consumer_conformance_harness(main_artifact_root=tmp_path)
    assert evidence["status"] == "rejected"
    assert "main_adapter_observation_rejected" in evidence["rejection_reasons"]


def test_default_inbox_never_claims_main_adoption_complete() -> None:
    inbox = ROOT / "runtime_artifacts" / "main_consumer_conformance" / "inbox"
    assert inbox.is_dir()
    evidence = run_main_consumer_conformance_harness()
    # Empty inbox awaits Main; fixture_main synthetic artifacts may accept shapes.
    # Either way the claim firewall forbids main_adoption_complete.
    assert evidence["status"] in {"awaiting_main", "accepted"}
    assert evidence["main_adoption_complete"] is False
    if evidence["status"] == "accepted":
        claim = (
            ROOT
            / "runtime_artifacts"
            / "main_consumer_conformance"
            / ("fixture_main_claim_boundary.json")
        )
        assert claim.is_file()
        boundary = json.loads(claim.read_text(encoding="utf-8"))
        assert boundary.get("authority_kind") == "fixture_authority"
        assert boundary.get("consumer_kind") == "synthetic_main_consumer"
        assert boundary.get("production_main_adoption_complete") is False
