import json
from pathlib import Path

import pytest
import yaml

from maskfactory.external_supervision_evidence import (
    build_qualification_evidence_bundle,
    seal_payload,
    verify_qualification_evidence_bundle,
)
from maskfactory.external_supervision_hash_manifest import build_source_hash_manifest
from maskfactory.external_supervision_producers import (
    ExternalSupervisionProducerError,
    assess_materialize_capacity,
    build_alignment_evidence,
    build_deterministic_fixture_gate_set,
    build_license_evidence,
    build_qualification_gap_report,
    build_remap_evidence,
    materialize_sealed_artifact,
    produce_project_contained_evidence,
    publish_gate_artifact,
)
from maskfactory.external_supervision_qualification import (
    verify_external_qualification_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = ROOT / "configs" / "maskedwarehouse_provenance.yaml"
INVENTORY = ROOT / "configs" / "maskedwarehouse_inventory.json"
ALIGNMENT_MANIFEST = ROOT / "qa" / "reports" / "maskedwarehouse_alignment_manifest.json"
ALIGNMENT_REVIEW = ROOT / "qa" / "reports" / "maskedwarehouse_alignment_review.json"


def _provenance() -> dict:
    return yaml.safe_load(PROVENANCE.read_text(encoding="utf-8"))


def _inventory() -> dict:
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def test_license_and_remap_evidence_seal_never_gold_for_all_eligible_sources():
    provenance = _provenance()
    inventory = _inventory()
    for source in ("celebamask_hq", "lapa", "lv_mhp_v1"):
        license_artifact = build_license_evidence(
            source=source, provenance=provenance, inventory=inventory
        )
        assert license_artifact["status"] == "PASS"
        assert license_artifact["source_masks_are_gold"] is False
        assert license_artifact["seal_sha256"] == seal_payload(license_artifact)

        remap_path = ROOT / "configs" / "remap" / f"{source}.yaml"
        remap_artifact = build_remap_evidence(
            source=source,
            remap_plan=yaml.safe_load(remap_path.read_text(encoding="utf-8")),
            remap_path=Path(f"configs/remap/{source}.yaml"),
            project_root=ROOT,
        )
        assert remap_artifact["source_masks_are_gold"] is False
        assert "never_gold" in remap_artifact["source_authority"]
        assert remap_artifact["remap_plan_path"] == f"configs/remap/{source}.yaml"


def test_alignment_evidence_pass_for_lapa_lv_and_celeba():
    manifest = json.loads(ALIGNMENT_MANIFEST.read_text(encoding="utf-8"))
    review = json.loads(ALIGNMENT_REVIEW.read_text(encoding="utf-8"))
    celeba_manifest = json.loads(
        (ROOT / "qa/reports/celebamask_hq_alignment_manifest.json").read_text(encoding="utf-8")
    )
    celeba_review = json.loads(
        (ROOT / "qa/reports/celebamask_hq_alignment_review.json").read_text(encoding="utf-8")
    )

    lapa = build_alignment_evidence(
        source="lapa", alignment_manifest=manifest, alignment_review=review
    )
    lv = build_alignment_evidence(
        source="lv_mhp_v1", alignment_manifest=manifest, alignment_review=review
    )
    celeba = build_alignment_evidence(
        source="celebamask_hq",
        alignment_manifest=celeba_manifest,
        alignment_review=celeba_review,
    )
    assert lapa["panel_count"] == 5
    assert lv["panel_count"] == 5
    assert celeba["panel_count"] == 5
    assert lapa["source_masks_are_gold"] is False
    assert celeba["source_masks_are_gold"] is False
    assert celeba["status"] == "PASS"


def test_gold_claim_rejected_on_publish_and_bundle_verify(tmp_path: Path):
    artifact = {
        "schema_version": "1.0.0",
        "artifact_type": "external_supervision_license_evidence",
        "source": "lapa",
        "gate": "official_license_recorded",
        "status": "PASS",
        "source_masks_are_gold": True,
    }
    artifact["seal_sha256"] = seal_payload(artifact)
    with pytest.raises(ExternalSupervisionProducerError, match="source_masks_are_gold"):
        publish_gate_artifact(artifact, tmp_path / "bad.json")

    paths = build_deterministic_fixture_gate_set(tmp_path, "lapa")
    bad_path = tmp_path / "lapa" / "official_license_recorded.json"
    bad = json.loads(bad_path.read_text(encoding="utf-8"))
    bad["source_masks_are_gold"] = True
    bad["seal_sha256"] = seal_payload(bad)
    bad_path.write_text(json.dumps(bad, sort_keys=True) + "\n", encoding="utf-8")
    paths["official_license_recorded"] = bad_path.relative_to(tmp_path)
    from maskfactory.external_supervision_evidence import ExternalSupervisionEvidenceError

    with pytest.raises(ExternalSupervisionEvidenceError, match="cannot be bound"):
        build_qualification_evidence_bundle(
            source="lapa",
            gate_artifact_paths=paths,
            project_root=tmp_path,
        )


def test_materialize_and_gap_report_fixture_flow(tmp_path: Path):
    source_root = tmp_path / "raw"
    (source_root / "images").mkdir(parents=True)
    (source_root / "images" / "a.jpg").write_bytes(b"image-a")
    manifest = build_source_hash_manifest(source="lapa", source_root=source_root)
    off = tmp_path / "off" / "lapa_source_hash_manifest_v1.json"
    off.parent.mkdir(parents=True)
    publish_gate_artifact(manifest, off)

    project = tmp_path / "project"
    project.mkdir()
    # Minimal registry copies for producer orchestration are not required for materialize.
    dest = (
        project
        / "runtime_artifacts"
        / "external_supervision"
        / "lapa"
        / "source_hash_manifested.json"
    )
    result = materialize_sealed_artifact(
        source="lapa",
        gate="source_hash_manifested",
        source_path=off,
        destination=dest,
    )
    assert dest.is_file()
    assert len(result.file_sha256) == 64
    assert result.seal_sha256 == manifest["seal_sha256"]

    fixture_paths = build_deterministic_fixture_gate_set(
        project / "qa" / "external_supervision", "lapa"
    )
    # Place fixture gates where the gap reporter looks.
    for gate, relative in fixture_paths.items():
        src = project / "qa" / "external_supervision" / relative
        assert src.is_file()

    gap = build_qualification_gap_report(
        project_root=project,
        evidence_root=Path("qa/external_supervision"),
        live_artifact_root=Path("runtime_artifacts/external_supervision"),
        off_project_manifest_root=tmp_path / "off",
    )
    assert gap["source_masks_are_gold"] is False
    assert gap["any_source_admitted"] is False
    assert gap["sources"]["lapa"]["admission_ready"] is True
    assert "celebamask_hq:missing_gate:" in " ".join(gap["blockers"])


def test_fixture_bundle_admits_under_registry_but_live_gap_stays_honest(tmp_path: Path):
    paths = build_deterministic_fixture_gate_set(tmp_path, "lv_mhp_v1")
    bundle = build_qualification_evidence_bundle(
        source="lv_mhp_v1",
        gate_artifact_paths=paths,
        project_root=tmp_path,
    )
    verification = verify_qualification_evidence_bundle(
        bundle, source="lv_mhp_v1", project_root=tmp_path
    )
    assert verification.passed is True
    decision = verify_external_qualification_evidence(
        _provenance(),
        _inventory(),
        source="lv_mhp_v1",
        evidence_bundle=bundle,
        project_root=tmp_path,
    )
    assert decision.admitted is True
    assert decision.evidence_tokens == ()

    # Capacity helper remains fail-closed for absurd requirements.
    assessment = assess_materialize_capacity(tmp_path, required_bytes=10**18)
    assert assessment.feasible is False


def test_gap_reports_verified_non_fixture_bundle_as_admitted(tmp_path: Path):
    project = tmp_path / "project"
    evidence_root = project / "qa" / "external_supervision"
    fixture_paths = build_deterministic_fixture_gate_set(evidence_root, "lapa")
    project_paths: dict[str, Path] = {}
    for gate, relative in fixture_paths.items():
        path = evidence_root / relative
        artifact = json.loads(path.read_text(encoding="utf-8"))
        artifact.pop("fixture")
        artifact["seal_sha256"] = seal_payload(artifact)
        path.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")
        project_paths[gate] = Path("qa/external_supervision") / relative
    bundle = build_qualification_evidence_bundle(
        source="lapa", gate_artifact_paths=project_paths, project_root=project
    )
    bundle_path = (
        project
        / "runtime_artifacts"
        / "external_supervision"
        / "lapa"
        / "qualification_evidence_bundle.json"
    )
    bundle_path.parent.mkdir(parents=True)
    bundle_path.write_text(json.dumps(bundle, sort_keys=True), encoding="utf-8")

    gap = build_qualification_gap_report(
        project_root=project,
        evidence_root=Path("qa/external_supervision"),
        live_artifact_root=Path("runtime_artifacts/external_supervision"),
        off_project_manifest_root=tmp_path / "off",
    )

    assert gap["sources"]["lapa"]["admission_ready"] is True
    assert gap["sources"]["lapa"]["qualification_bundle_verified"] is True
    assert gap["any_source_admitted"] is True


def test_produce_project_contained_evidence_writes_gap_without_claiming_admission(tmp_path: Path):
    # Tiny off-project stand-ins so materialize path is exercised without multi-GB trees.
    off = tmp_path / "off"
    off.mkdir()
    for source, filename in (
        ("celebamask_hq", "celebamask_hq_source_hash_manifest_v1.json"),
        ("lapa", "lapa_source_hash_manifest_v1.json"),
        ("lv_mhp_v1", "lv_mhp_v1_source_hash_manifest_v1.json"),
    ):
        root = tmp_path / f"src_{source}"
        (root / "f.bin").parent.mkdir(parents=True, exist_ok=True)
        (root / "f.bin").write_bytes(f"{source}-bytes".encode("utf-8"))
        manifest = build_source_hash_manifest(source=source, source_root=root)
        publish_gate_artifact(manifest, off / filename)

    identity = {
        "schema_version": "1.0.0",
        "artifact_type": "external_supervision_identity_evidence",
        "source": "lv_mhp_v1",
        "gate": "instance_identity_validated",
        "status": "PASS",
        "source_masks_are_gold": False,
        "image_count": 1,
        "annotation_count": 1,
    }
    identity["seal_sha256"] = seal_payload(identity)
    publish_gate_artifact(identity, off / "lv_mhp_v1_identity_evidence_v1.json")

    project = tmp_path / "proj"
    # Reuse real configs/qa reports via produce against ROOT paths by copying minimal tree.
    for relative in (
        "configs/maskedwarehouse_provenance.yaml",
        "configs/maskedwarehouse_inventory.json",
        "configs/remap/celebamask_hq.yaml",
        "configs/remap/lapa.yaml",
        "configs/remap/lv_mhp_v1.yaml",
        "qa/reports/maskedwarehouse_alignment_manifest.json",
        "qa/reports/maskedwarehouse_alignment_review.json",
    ):
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())

    result = produce_project_contained_evidence(
        project_root=project,
        off_project_manifest_root=off,
    )
    assert result["source_masks_are_gold"] is False
    assert result["any_source_admitted"] is False
    gap_path = project / result["gap_report_path"]
    gap = json.loads(gap_path.read_text(encoding="utf-8"))
    assert gap["seal_sha256"] == seal_payload(gap)
    assert gap["sources"]["lapa"]["present_gates"].keys() >= {
        "official_license_recorded",
        "deterministic_remap_tested",
        "visual_alignment_qa_passed",
        "source_hash_manifested",
    }
    assert "visual_alignment_qa_passed" in gap["sources"]["celebamask_hq"]["missing_gates"]
    assert "split_dedup_passed" in gap["sources"]["lapa"]["missing_gates"]
