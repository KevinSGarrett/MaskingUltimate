from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PIL import Image

from maskfactory.authority import (
    OperationalCertificateIssuanceError,
    bind_complete_map_report,
    build_complete_map_hard_veto_report,
    canonical_decoded_raster_sha256,
    issue_operational_autonomy_certificate,
)
from maskfactory.qa.checks import QcResult
from maskfactory.validation import (
    artifact_identity_sha256,
    canonical_json_bytes,
    validate_operational_autonomy_certificate,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "mask_bridge_contracts"
    / "positive_operational_autonomy_certificate_v1.json"
)
AUTHORITATIVE_BINDINGS = (
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

PASSING_COMPLETE_MAP_QC = (
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


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _complete_map_report(
    certificate: dict,
    *,
    instance_context: str = "solo",
    failed_qc_id: str | None = None,
) -> dict:
    qc_ids = list(PASSING_COMPLETE_MAP_QC)
    if instance_context != "solo":
        qc_ids.extend(("QC-035", "QC-036", "QC-037"))
    return build_complete_map_hard_veto_report(
        tuple(
            QcResult(
                qc_id,
                f"fixture_{qc_id.lower()}",
                qc_id != failed_qc_id,
                "seeded defect" if qc_id == failed_qc_id else "verified pass",
                "BLOCK",
            )
            for qc_id in qc_ids
        ),
        instance_context=instance_context,
        source_binding=certificate["source_binding"],
        subject_binding=certificate["subject_binding"],
        coordinate_binding=certificate["coordinate_binding"],
        artifacts=certificate["bound_artifacts"],
        critic_confidence=1.0,
        evaluator_id="maskfactory.complete_map_hard_veto.v1",
        evaluator_sha256=hashlib.sha256(b"complete-map-hard-veto-test-executor").hexdigest(),
    )


def _prepare(tmp_path: Path, *, instance_context: str = "solo") -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    certificate = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = tmp_path / "source.png"
    mask = tmp_path / "mask.png"
    Image.new("RGB", (4, 4), (24, 48, 96)).save(source)
    mask_pixels = np.zeros((4, 4), dtype=np.uint8)
    mask_pixels[1:3, 1:3] = 255
    Image.fromarray(mask_pixels, mode="L").save(mask)

    certificate.update(
        fixture_only=False,
        evidence_context="runtime_evidence",
        issued_at="2026-07-17T00:00:04Z",
        expires_at="2026-07-18T00:00:04Z",
    )
    source_binding = certificate["source_binding"]
    source_binding.update(
        encoded_sha256=_sha(source),
        decoded_pixel_sha256=canonical_decoded_raster_sha256(
            np.asarray(Image.open(source)), channel_layout="RGB"
        ),
        width=4,
        height=4,
        exif_orientation=1,
        orientation_applied=True,
    )
    coordinate = certificate["coordinate_binding"]
    coordinate.update(source_width=4, source_height=4, output_width=4, output_height=4)
    artifact = certificate["bound_artifacts"][0]
    artifact.update(
        source_decoded_pixel_sha256=source_binding["decoded_pixel_sha256"],
        encoded_sha256=_sha(mask),
        decoded_mask_sha256=canonical_decoded_raster_sha256(
            mask_pixels, channel_layout="L", allowed_values="binary_0_255"
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

    private_key = Ed25519PrivateKey.generate()
    private_path = tmp_path / "authority.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    key_id = "mf-authority-runtime-test"
    key_set_sha256 = hashlib.sha256(b"runtime-authority-key-set").hexdigest()
    trusted = {
        key_id: {
            "public_key_sha256": hashlib.sha256(public).hexdigest(),
            "roles": ["producer_authority"],
            "status": "active",
            "usage_scope": "production",
            "valid_from": "2026-07-01T00:00:00Z",
            "valid_until": "2027-07-01T00:00:00Z",
            "key_set_id": "maskfactory-runtime-authority",
            "key_set_version": "1.0.0",
            "key_set_sha256": key_set_sha256,
        }
    }
    certificate["release_binding"].update(
        signing_key_set_id="maskfactory-runtime-authority",
        signing_key_set_version="1.0.0",
        signing_key_set_sha256=key_set_sha256,
    )
    certificate["revocation"].update(
        checked_at="2026-07-17T00:00:05Z",
        is_revoked=False,
    )
    for region in certificate["lineage"]["input_protected_regions"]:
        region["revocation_checked_at"] = "2026-07-17T00:00:05Z"
    report = _complete_map_report(certificate, instance_context=instance_context)
    certificate = bind_complete_map_report(certificate, report)
    authoritative = {field: copy.deepcopy(certificate[field]) for field in AUTHORITATIVE_BINDINGS}
    journal = {
        **copy.deepcopy(certificate["revocation"]),
        "fork_detected": False,
    }
    return {
        "certificate": certificate,
        "source": source,
        "mask": mask,
        "private_path": private_path,
        "key_id": key_id,
        "trusted": trusted,
        "authoritative": authoritative,
        "journal": journal,
        "complete_map_report": report,
    }


def _issue(prepared: dict, **overrides):
    arguments = {
        "source_path": prepared["source"],
        "artifact_paths": {"output-left-hand-predict": prepared["mask"]},
        "authoritative_bindings": prepared["authoritative"],
        "candidate_authority_state": "qa_passed_noncertified",
        "candidate_truth_tier": "qa_passed_machine_candidate",
        "journal_state": prepared["journal"],
        "private_key_path": prepared["private_path"],
        "signing_key_id": prepared["key_id"],
        "trusted_signing_keys": prepared["trusted"],
        "decision_time": "2026-07-17T00:00:05Z",
        "complete_map_hard_veto_report": prepared["complete_map_report"],
        "trusted_hard_veto_evaluators": {
            "maskfactory.complete_map_hard_veto.v1": hashlib.sha256(
                b"complete-map-hard-veto-test-executor"
            ).hexdigest()
        },
    }
    arguments.update(overrides)
    return issue_operational_autonomy_certificate(prepared["certificate"], **arguments)


def test_issuer_recomputes_exact_bytes_and_is_deterministic(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)
    first = _issue(prepared)
    second = _issue(prepared)
    assert first == second
    assert first["fixture_only"] is False
    assert first["evidence_context"] == "runtime_evidence"
    assert first["truth_tier"] == "operationally_certified_artifact"
    assert first["claim_limits"]["training_gold_claim"] is False
    assert first["claim_limits"]["independent_real_accuracy_claim"] is False
    assert (
        validate_operational_autonomy_certificate(
            first,
            trusted_signing_keys=prepared["trusted"],
            production_required=True,
            at_time="2026-07-17T00:00:05Z",
        )
        == ()
    )


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"candidate_authority_state": "draft"}, "candidate_not_qa_passed_noncertified"),
        ({"candidate_truth_tier": "machine_candidate"}, "candidate_not_qa_passed_noncertified"),
    ],
)
def test_issuer_refuses_draft_or_unqualified_candidate(
    tmp_path: Path, override: dict, code: str
) -> None:
    prepared = _prepare(tmp_path)
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared, **override)
    assert code in caught.value.codes


def test_issuer_refuses_source_or_mask_byte_drift(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)
    Image.new("RGB", (4, 4), (1, 2, 3)).save(prepared["source"])
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "source_encoded_hash_mismatch" in caught.value.codes

    prepared = _prepare(tmp_path / "mask-drift")
    Image.new("L", (4, 4), 255).save(prepared["mask"])
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "mask_content_summary_mismatch" in caught.value.codes


def test_issuer_refuses_authority_journal_and_key_failures(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)
    prepared["certificate"]["execution_binding"]["provider_stack_id"] = "substituted"
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "authoritative_execution_binding_mismatch" in caught.value.codes

    prepared = _prepare(tmp_path / "fork")
    prepared["journal"]["fork_detected"] = True
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "signed_journal_fork" in caught.value.codes

    prepared = _prepare(tmp_path / "role")
    prepared["trusted"][prepared["key_id"]]["roles"] = ["producer_receipt"]
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "signing_key_wrong_role" in caught.value.codes

    prepared = _prepare(tmp_path / "substituted-key")
    replacement = Ed25519PrivateKey.generate()
    prepared["private_path"].write_bytes(
        replacement.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "signing_key_substituted" in caught.value.codes


def test_issuer_refuses_stale_protected_input_or_blocking_qa(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared, decision_time="2026-07-17T00:10:05Z")
    assert "protected_input_revocation_stale" in caught.value.codes

    prepared = _prepare(tmp_path / "qa")
    prepared["certificate"]["qa_evidence"]["gate_results"][0]["status"] = "fail"
    prepared["authoritative"]["qa_evidence"] = copy.deepcopy(prepared["certificate"]["qa_evidence"])
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "operational_qa_gate_pass" in caught.value.codes


def test_issuer_refuses_scope_validity_revocation_and_ownership_drift(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)
    prepared["certificate"]["certified_output_scope"]["artifact_identity_sha256s"] = ["0" * 64]
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "certified_output_scope_mismatch" in caught.value.codes

    prepared = _prepare(tmp_path / "future")
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared, decision_time="2026-07-17T00:00:03Z")
    assert "certificate_validity_rejected" in caught.value.codes

    prepared = _prepare(tmp_path / "revoked")
    prepared["certificate"]["revocation"]["is_revoked"] = True
    prepared["authoritative"]["revocation"] = copy.deepcopy(prepared["certificate"]["revocation"])
    prepared["journal"]["is_revoked"] = True
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "certificate_scope_revoked" in caught.value.codes

    prepared = _prepare(tmp_path / "owner")
    prepared["certificate"]["subject_binding"]["scene_instance_id"] = "ambiguous-owner"
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "authoritative_subject_binding_mismatch" in caught.value.codes


def test_issuer_refuses_weak_or_stale_protected_authority(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)
    protected = prepared["certificate"]["lineage"]["input_protected_regions"][0]
    protected.update(
        authority_state="draft",
        certificate_kind="none",
        certificate_status="none",
        certificate_exact_scope_match=False,
    )
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "protected_input_authority_too_weak" in caught.value.codes

    prepared = _prepare(tmp_path / "stale-certificate")
    prepared["certificate"]["lineage"]["input_protected_regions"][0][
        "revocation_checked_at"
    ] = "2026-07-17T00:10:05Z"
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared, decision_time="2026-07-17T00:10:05Z")
    assert "certificate_revocation_fresh_at_use" in caught.value.codes


@pytest.mark.parametrize(
    "failed_qc_id",
    [
        "QC-001",  # dimensions
        "QC-002",  # binary format
        "QC-003",  # PNG/channel format
        "QC-004",  # ontology
        "QC-011",  # atomic exclusivity
        "QC-013",  # protected regions
        "QC-014",  # left/right semantics
        "QC-016",  # visibility
        "QC-018",  # transform round trip
    ],
)
def test_complete_map_seeded_single_person_defects_override_unanimous_critic(
    tmp_path: Path, failed_qc_id: str
) -> None:
    prepared = _prepare(tmp_path)
    report = _complete_map_report(prepared["certificate"], failed_qc_id=failed_qc_id)
    assert report["critic_confidence_observed"] == 1.0
    prepared["complete_map_report"] = report
    prepared["certificate"] = bind_complete_map_report(prepared["certificate"], report)
    prepared["authoritative"]["qa_evidence"] = copy.deepcopy(prepared["certificate"]["qa_evidence"])
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "complete_map_hard_veto_failed" in caught.value.codes


@pytest.mark.parametrize("failed_qc_id", ["QC-035", "QC-036", "QC-037"])
def test_complete_map_seeded_multi_person_defects_override_unanimous_critic(
    tmp_path: Path, failed_qc_id: str
) -> None:
    prepared = _prepare(tmp_path, instance_context="duo")
    report = _complete_map_report(
        prepared["certificate"], instance_context="duo", failed_qc_id=failed_qc_id
    )
    assert report["critic_confidence_observed"] == 1.0
    prepared["complete_map_report"] = report
    prepared["certificate"] = bind_complete_map_report(prepared["certificate"], report)
    prepared["authoritative"]["qa_evidence"] = copy.deepcopy(prepared["certificate"]["qa_evidence"])
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "complete_map_hard_veto_failed" in caught.value.codes


def test_complete_map_owner_character_and_transform_binding_defects_block_issuance(
    tmp_path: Path,
) -> None:
    prepared = _prepare(tmp_path)
    prepared["certificate"]["bound_artifacts"][0]["entity_id"] = "wrong-character"
    report = _complete_map_report(prepared["certificate"])
    prepared["complete_map_report"] = report
    prepared["certificate"] = bind_complete_map_report(prepared["certificate"], report)
    prepared["authoritative"]["qa_evidence"] = copy.deepcopy(prepared["certificate"]["qa_evidence"])
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "complete_map_hard_veto_failed" in caught.value.codes

    prepared = _prepare(tmp_path / "transform")
    prepared["certificate"]["coordinate_binding"]["roundtrip_passed"] = False
    report = _complete_map_report(prepared["certificate"])
    prepared["complete_map_report"] = report
    prepared["certificate"] = bind_complete_map_report(prepared["certificate"], report)
    prepared["authoritative"]["qa_evidence"] = copy.deepcopy(prepared["certificate"]["qa_evidence"])
    prepared["authoritative"]["coordinate_binding"] = copy.deepcopy(
        prepared["certificate"]["coordinate_binding"]
    )
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "complete_map_hard_veto_failed" in caught.value.codes


def test_complete_map_report_cannot_relabel_a_failed_check_or_drift_its_hash(
    tmp_path: Path,
) -> None:
    prepared = _prepare(tmp_path)
    report = copy.deepcopy(prepared["complete_map_report"])
    format_row = next(row for row in report["categories"] if row["category"] == "format")
    format_row["checks"][0]["passed"] = False
    prepared["complete_map_report"] = report
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "complete_map_category_hash:format" in caught.value.codes
    assert "complete_map_category_outcome:format" in caught.value.codes

    prepared = _prepare(tmp_path / "report-hash")
    prepared["certificate"]["qa_evidence"]["deterministic_report_sha256"] = "0" * 64
    prepared["authoritative"]["qa_evidence"] = copy.deepcopy(prepared["certificate"]["qa_evidence"])
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "complete_map_report_hash_mismatch" in caught.value.codes


def test_complete_map_report_requires_trusted_evaluator_and_exact_multi_qc_coverage(
    tmp_path: Path,
) -> None:
    prepared = _prepare(tmp_path)
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared, trusted_hard_veto_evaluators={})
    assert "complete_map_evaluator_untrusted" in caught.value.codes

    prepared = _prepare(tmp_path / "artifact-drift")
    prepared["certificate"]["bound_artifacts"][0]["label"] = "right_hand"
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "complete_map_artifact_set_binding_sha256" in caught.value.codes

    prepared = _prepare(tmp_path / "multi", instance_context="duo")
    report = copy.deepcopy(prepared["complete_map_report"])
    contact = next(row for row in report["categories"] if row["category"] == "contact")
    contact.update(
        status="not_applicable",
        required_qc_ids=[],
        missing_qc_ids=[],
        failed_qc_ids=[],
        checks=[],
        reason="forged applicability",
    )
    unsigned_contact = {key: value for key, value in contact.items() if key != "evidence_sha256"}
    contact["evidence_sha256"] = hashlib.sha256(canonical_json_bytes(unsigned_contact)).hexdigest()
    prepared["complete_map_report"] = report
    prepared["certificate"] = bind_complete_map_report(prepared["certificate"], report)
    prepared["authoritative"]["qa_evidence"] = copy.deepcopy(prepared["certificate"]["qa_evidence"])
    with pytest.raises(OperationalCertificateIssuanceError) as caught:
        _issue(prepared)
    assert "complete_map_required_qc:contact" in caught.value.codes
