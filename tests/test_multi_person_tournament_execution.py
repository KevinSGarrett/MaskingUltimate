from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.autonomy.multi_person_evidence import (
    MultiPersonCandidateRecord,
    MultiPersonEvidenceError,
    MultiPersonTournamentTarget,
    ProviderContribution,
    write_multi_person_tournament_evidence,
)
from maskfactory.autonomy.multi_person_execution import (
    EXECUTION_AUTHORITY,
    MultiPersonExecutionError,
    TargetTournamentControl,
    verify_multi_person_tournament_execution,
    write_multi_person_tournament_execution,
)
from maskfactory.autonomy.multi_person_gate import (
    MultiPersonCandidateGateResult,
    MultiPersonGateCheck,
)
from maskfactory.autonomy.multi_person_scope import MultiPersonCertificationScopeResult
from maskfactory.autonomy.tournament import CandidateEvidence
from maskfactory.io.hashing import sha256_file
from maskfactory.io.png_strict import write_binary_mask
from maskfactory.providers.contracts import ProviderIdentity
from maskfactory.providers.provider_matrix import canonical_sha256
from maskfactory.validation import validate_document

PIPELINE = "f" * 64
FAMILIES = {
    "deterministic_repair": ("deterministic_repair", "repair", "deterministic"),
    "fusion": ("s09_fusion", "fusion", "fusion"),
    "geometry": ("densepose_rcnn_r50_fpn_s1x", "geometry_provider", "densepose"),
    "pose": ("dwpose_133", "pose_provider", "dwpose"),
    "rf_detr_detection": ("rfdetr", "person_detector", "rfdetr"),
    "sam21_refinement": ("sam2_1_hiera_large", "interactive_segmenter", "sam2"),
    "silhouette": ("birefnet_general", "silhouette_provider", "birefnet"),
    "specialist": ("sapiens_0_6b_seg", "specialist", "sapiens"),
}


def _provider(family: str) -> ProviderIdentity:
    key, role, model_family = FAMILIES[family]
    return ProviderIdentity(
        key, role, model_family, "a" * 40, hashlib.sha256(key.encode()).hexdigest()
    )


def _candidate(root: Path, candidate_id: str, offset: int) -> MultiPersonCandidateRecord:
    mask = np.zeros((24, 32), dtype=bool)
    mask[3 + offset : 12 + offset, 4 + offset : 16 + offset] = True
    path = write_binary_mask(root / "masks" / f"{candidate_id}.png", mask, source_size=(32, 24))
    contributions = tuple(ProviderContribution(family, _provider(family)) for family in FAMILIES)
    providers = tuple(sorted({row.provider.provider_key for row in contributions}))
    models = tuple(sorted({row.provider.model_family for row in contributions}))
    evidence = CandidateEvidence(
        candidate_id=candidate_id,
        mask_path=str(path),
        mask_sha256=sha256_file(path),
        independent_sources=len(models),
        consensus_iou=0.99,
        boundary_agreement=0.99,
        pose_consistency=0.99,
        critic_pass_weight=1.0,
        critic_disagreement=False,
        protected_overlap=0.0,
        exclusive_overlap=0.0,
        component_count=1,
        ontology_max_components=1,
        format_valid=True,
        block_qc_ids=(),
        source_provider_keys=providers,
        source_model_families=models,
    )
    return MultiPersonCandidateRecord("fusion", 0, None, contributions, evidence)


def _certificate() -> dict:
    payload = {
        "schema_version": "2.0.0",
        "audit_authority": "human_anchor_gold",
        "passed": True,
        "risk_bucket": "contact",
        "instance_context": "duo",
        "covered_labels": ["hair"],
        "covered_contexts": ["contact"],
        "pipeline_fingerprint": PIPELINE,
        "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
    }
    payload["sha256"] = canonical_sha256(payload)
    return payload


def _fixture(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = tmp_path / "artifacts"
    source = tmp_path / "source.png"
    Image.fromarray(np.zeros((24, 32, 3), dtype=np.uint8), "RGB").save(source)
    targets = (
        MultiPersonTournamentTarget(
            "person-0", "part-instance-0", "hair", (_candidate(root, "p0-hair", 0),)
        ),
        MultiPersonTournamentTarget(
            "person-1", "part-instance-1", "hair", (_candidate(root, "p1-hair", 5),)
        ),
    )
    evidence = write_multi_person_tournament_evidence(
        image_id="img_execution_fixture",
        source_image_path=source,
        instance_context="duo",
        pipeline_fingerprint=PIPELINE,
        targets=targets,
        artifact_root=root,
        output_path=tmp_path / "evidence.json",
    )
    scope = MultiPersonCertificationScopeResult("duo", "contact", PIPELINE, ())
    certificate = _certificate()
    controls = {
        ("person-0", "part-instance-0", "hair"): TargetTournamentControl(
            "p0", "contact", scope, certificate
        ),
        ("person-1", "part-instance-1", "hair"): TargetTournamentControl(
            "p1", "contact", scope, certificate
        ),
    }
    checks = tuple(
        MultiPersonGateCheck(check_id, True, "fixture pass")
        for check_id in ("QC-035", "QC-036", "AUT-MP-001", "AUT-MP-002", "AUT-MP-003")
    )
    gate = MultiPersonCandidateGateResult("duo", ("p0", "p1"), checks)
    return evidence, root, source, controls, gate


def _write(tmp_path: Path):
    evidence, root, source, controls, gate = _fixture(tmp_path)
    report = write_multi_person_tournament_execution(
        evidence_manifest_path=evidence,
        artifact_root=root,
        expected_pipeline_fingerprint=PIPELINE,
        controls=controls,
        gate=gate,
        source_image_path=source,
        output_path=tmp_path / "execution.json",
    )
    return report, evidence, root, source, controls, gate


def test_exact_target_execution_can_produce_certificate_scoped_decisions(tmp_path: Path) -> None:
    report, evidence, root, source, controls, gate = _write(tmp_path)
    document = json.loads(report.read_text(encoding="utf-8"))
    assert not validate_document(document, "multi_person_tournament_execution")
    assert document["status_counts"] == {"calibrated_auto_accepted": 2}
    assert {row["promoted_instance_id"] for row in document["targets"]} == {"p0", "p1"}
    assert all(row["decision"]["certificate_valid"] for row in document["targets"])
    assert all(
        row["decision"]["truth_tier"] == "autonomous_certified_gold" for row in document["targets"]
    )
    assert all(row["certificate_document_sha256"] for row in document["targets"])
    assert all(row["certificate_claimed_sha256"] for row in document["targets"])
    summary = verify_multi_person_tournament_execution(
        report,
        evidence_manifest_path=evidence,
        artifact_root=root,
        expected_pipeline_fingerprint=PIPELINE,
        controls=controls,
        gate=gate,
        source_image_path=source,
    )
    assert summary["target_count"] == 2 and summary["authority"] == EXECUTION_AUTHORITY


def test_failed_gate_and_missing_certificates_route_every_target_residual(tmp_path: Path) -> None:
    evidence, root, source, controls, gate = _fixture(tmp_path)
    failed_checks = tuple(
        MultiPersonGateCheck(check.check_id, check.check_id != "QC-035", "fixture")
        for check in gate.checks
    )
    failed_gate = MultiPersonCandidateGateResult("duo", gate.promoted_instances, failed_checks)
    no_certificates = {
        key: TargetTournamentControl(
            value.promoted_instance_id, value.semantic_context, value.scope, None
        )
        for key, value in controls.items()
    }
    for index, (selected_gate, selected_controls) in enumerate(
        ((failed_gate, controls), (gate, no_certificates))
    ):
        report = write_multi_person_tournament_execution(
            evidence_manifest_path=evidence,
            artifact_root=root,
            expected_pipeline_fingerprint=PIPELINE,
            controls=selected_controls,
            gate=selected_gate,
            source_image_path=source,
            output_path=tmp_path / f"residual-{index}.json",
        )
        document = json.loads(report.read_text(encoding="utf-8"))
        assert document["status_counts"] == {"residual_human_queue": 2}
        assert all(row["decision"]["human_audit_required"] for row in document["targets"])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda controls: controls.pop(next(iter(controls))),
        lambda controls: controls.update(
            {("extra", "extra", "hair"): next(iter(controls.values()))}
        ),
        lambda controls: controls.update(
            {
                list(controls)[1]: TargetTournamentControl(
                    "p0",
                    controls[list(controls)[1]].semantic_context,
                    controls[list(controls)[1]].scope,
                    controls[list(controls)[1]].certificate,
                )
            }
        ),
        lambda controls: controls.update(
            {
                list(controls)[0]: TargetTournamentControl(
                    controls[list(controls)[0]].promoted_instance_id,
                    "",
                    controls[list(controls)[0]].scope,
                    controls[list(controls)[0]].certificate,
                )
            }
        ),
        lambda controls: controls.update(
            {
                list(controls)[0]: TargetTournamentControl(
                    controls[list(controls)[0]].promoted_instance_id,
                    controls[list(controls)[0]].semantic_context,
                    MultiPersonCertificationScopeResult("duo", "contact", "stale", ()),
                    controls[list(controls)[0]].certificate,
                )
            }
        ),
    ],
)
def test_missing_extra_rebound_empty_and_stale_target_controls_fail(
    tmp_path: Path, mutation
) -> None:
    evidence, root, source, controls, gate = _fixture(tmp_path)
    controls = dict(controls)
    mutation(controls)
    with pytest.raises(MultiPersonExecutionError):
        write_multi_person_tournament_execution(
            evidence_manifest_path=evidence,
            artifact_root=root,
            expected_pipeline_fingerprint=PIPELINE,
            controls=controls,
            gate=gate,
            source_image_path=source,
            output_path=tmp_path / "bad-controls.json",
        )


def test_gate_context_and_promoted_identity_rebinding_fail(tmp_path: Path) -> None:
    evidence, root, source, controls, gate = _fixture(tmp_path)
    gates = (
        MultiPersonCandidateGateResult("small_group", gate.promoted_instances, gate.checks),
        MultiPersonCandidateGateResult("duo", ("p0", "p0"), gate.checks),
        MultiPersonCandidateGateResult("duo", ("p0", "p2"), gate.checks),
        MultiPersonCandidateGateResult("duo", gate.promoted_instances, gate.checks[:-1]),
    )
    for index, rebound in enumerate(gates):
        with pytest.raises(MultiPersonExecutionError):
            write_multi_person_tournament_execution(
                evidence_manifest_path=evidence,
                artifact_root=root,
                expected_pipeline_fingerprint=PIPELINE,
                controls=controls,
                gate=rebound,
                source_image_path=source,
                output_path=tmp_path / f"gate-{index}.json",
            )


def test_report_seal_recomputation_and_evidence_binding_fail_closed(tmp_path: Path) -> None:
    report, evidence, root, source, controls, gate = _write(tmp_path)
    document = json.loads(report.read_text(encoding="utf-8"))
    document["targets"][0]["decision"]["status"] = "residual_human_queue"
    report.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(MultiPersonExecutionError, match="hash mismatch"):
        verify_multi_person_tournament_execution(
            report,
            evidence_manifest_path=evidence,
            artifact_root=root,
            expected_pipeline_fingerprint=PIPELINE,
            controls=controls,
            gate=gate,
            source_image_path=source,
        )

    report, evidence, root, source, controls, gate = _write(tmp_path / "recompute")
    document = json.loads(report.read_text(encoding="utf-8"))
    document["targets"][0]["decision"]["reason"] = "rebound"
    document["sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    report.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(MultiPersonExecutionError, match="recomputation mismatch"):
        verify_multi_person_tournament_execution(
            report,
            evidence_manifest_path=evidence,
            artifact_root=root,
            expected_pipeline_fingerprint=PIPELINE,
            controls=controls,
            gate=gate,
            source_image_path=source,
        )

    report, evidence, root, source, controls, gate = _write(tmp_path / "evidence-drift")
    evidence_document = json.loads(evidence.read_text(encoding="utf-8"))
    evidence_document["image_id"] = "rebound"
    evidence.write_text(json.dumps(evidence_document), encoding="utf-8")
    with pytest.raises(MultiPersonEvidenceError):
        verify_multi_person_tournament_execution(
            report,
            evidence_manifest_path=evidence,
            artifact_root=root,
            expected_pipeline_fingerprint=PIPELINE,
            controls=controls,
            gate=gate,
            source_image_path=source,
        )
