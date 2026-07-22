import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.autonomy.calibration import verify_human_gold_audit_record
from maskfactory.autonomy.package_semantic_alignment import (
    semantic_alignment_report_sha256,
)
from maskfactory.derive import derive_package
from maskfactory.fusion.mapbuild import export_binaries
from maskfactory.io.png_strict import read_mask, write_binary_mask, write_label_map
from maskfactory.ontology import get_ontology
from maskfactory.packager import (
    ApprovalRequiredError,
    PackageBlockedError,
    approve_package,
    approve_packages_atomically,
    certify_autonomous_package,
    verify_packages,
)
from maskfactory.qa.checks import run_qc001_010
from test_manifest_schema import valid_manifest


def _refresh_hashes(package: Path) -> None:
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = {
        path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in package.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.fixture
def clean_package(tmp_path: Path) -> Path:
    package = tmp_path / "clean"
    package.mkdir()
    source = package / "source.png"
    Image.fromarray(np.zeros((96, 128, 3), dtype=np.uint8)).save(source)
    part = np.zeros((96, 128), dtype=np.uint16)
    material = np.zeros((96, 128), dtype=np.uint8)
    part[20:70, 30:55] = 18
    material[20:70, 30:55] = 1
    write_label_map(package / "label_map_part.png", part, bits=16)
    write_label_map(package / "label_map_material.png", material, bits=8)
    export_binaries(package)
    derive_package(package)
    waist = np.zeros((96, 128), dtype=np.uint8)
    waist[45:50, 20:100] = 255
    write_binary_mask(package / "masks_regions" / "waist.png", waist)
    manifest = valid_manifest()
    manifest["workflow_status"] = "corrected"
    manifest["source"].update(
        {
            "source_file": "source.png",
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_width": 128,
            "source_height": 96,
        }
    )
    manifest["parts"] = {
        label.name: {
            "mask_type": label.mask_type,
            "visibility": label.visibility_default,
            "mask_file": None,
            "status": "n/a",
        }
        for label in get_ontology().labels
        if label.enabled and label.map != "material"
    }
    manifest["files"] = {}
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _refresh_hashes(package)
    results = run_qc001_010(package)
    assert all(result.passed for result in results), results
    return package


def _seed(package: Path, qc_id: str) -> None:
    waist = package / "masks_regions" / "waist.png"
    if qc_id == "QC-001":
        write_binary_mask(waist, np.zeros((95, 128), dtype=np.uint8))
    elif qc_id == "QC-002":
        array = read_mask(waist)
        array[0, 0] = 128
        Image.fromarray(array, mode="L").save(waist)
    elif qc_id == "QC-003":
        array = read_mask(waist)
        palette = Image.frombytes("P", (array.shape[1], array.shape[0]), array.tobytes())
        palette.putpalette([value for index in range(256) for value in (index, index, index)])
        palette.save(waist)
    elif qc_id == "QC-004":
        write_binary_mask(package / "masks_regions" / "invented_label.png", read_mask(waist))
    elif qc_id == "QC-005":
        path = package / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        del manifest["tooling"]
        path.write_text(json.dumps(manifest), encoding="utf-8")
    elif qc_id == "QC-006":
        with (package / "source.png").open("ab") as handle:
            handle.write(b"hash-defect")
    elif qc_id == "QC-007":
        path = package / "masks" / "left_forearm.png"
        array = read_mask(path)
        array[0, 0] = 255
        write_binary_mask(path, array)
    elif qc_id == "QC-008":
        path = package / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        del manifest["parts"]["left_forearm"]
        path.write_text(json.dumps(manifest), encoding="utf-8")
    elif qc_id == "QC-009":
        path = package / "masks_derived" / "left_hand.png"
        array = read_mask(path)
        array[0, 0] = 255
        write_binary_mask(path, array)
    elif qc_id == "QC-010":
        path = package / "crops" / "crop_to_full_transform.json"
        path.parent.mkdir()
        path.write_text(
            json.dumps(
                {
                    "part": "left_forearm",
                    "x0": 120,
                    "y0": 90,
                    "scale": 1.0,
                    "crop_size": 64,
                    "source_sha256": "a" * 64,
                }
            ),
            encoding="utf-8",
        )
    else:
        raise AssertionError(qc_id)
    if qc_id not in {"QC-005", "QC-006", "QC-008"}:
        _refresh_hashes(package)


@pytest.mark.parametrize("qc_id", [f"QC-{number:03d}" for number in range(1, 11)])
def test_each_seeded_defect_trips_exactly_its_qc(
    clean_package: Path, tmp_path: Path, qc_id: str
) -> None:
    package = tmp_path / qc_id
    shutil.copytree(clean_package, package)
    _seed(package, qc_id)
    results = run_qc001_010(package)
    failed = [result.qc_id for result in results if not result.passed]
    assert failed == [qc_id], results


def test_human_approval_cannot_override_block(clean_package: Path, tmp_path: Path) -> None:
    package = tmp_path / "blocked"
    shutil.copytree(clean_package, package)
    _seed(package, "QC-002")
    dvc_calls = []
    with pytest.raises(PackageBlockedError, match="QC-002"):
        approve_package(
            package,
            reviewer="kevin",
            review_minutes=12,
            approved=True,
            dvc_add=dvc_calls.append,
        )
    assert dvc_calls == []
    assert not (package / ".maskfactory_frozen.json").exists()
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["qa"]["qa_overall"] == "fail"
    assert manifest["workflow_status"] == "in_review"


def test_clean_package_requires_confirmation_then_freezes_hashes_and_dvc_adds(
    clean_package: Path, tmp_path: Path
) -> None:
    package = tmp_path / "approved"
    shutil.copytree(clean_package, package)
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    gold_mask = package / "masks" / "left_forearm.png"
    manifest["parts"]["left_forearm"].update(
        {
            "mask_file": "masks/left_forearm.png",
            "mask_sha256": hashlib.sha256(gold_mask.read_bytes()).hexdigest(),
            "status": "human_corrected",
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ApprovalRequiredError):
        approve_package(
            package,
            reviewer="kevin",
            review_minutes=12,
            approved=False,
            dvc_add=lambda _path: None,
        )
    dvc_calls = []
    result = approve_package(
        package,
        reviewer="kevin",
        review_minutes=12,
        approved=True,
        dvc_add=dvc_calls.append,
    )
    assert result.passed
    assert dvc_calls == [package]
    assert (package / ".maskfactory_frozen.json").is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["parts"]["left_forearm"]["status"] == "human_approved_gold"
    assert manifest["review"]["reviewer"] == "kevin"
    assert manifest["review"]["review_time_sec"] == 720
    assert manifest["qa"]["qa_overall"] == "pass"
    assert manifest["workflow_status"] == "approved_gold"
    assert {record["label"] for record in manifest["inpaint_derivatives"]} == {
        "left_hand",
        "right_hand",
        "left_foot",
        "right_foot",
        "hair",
        "both_breasts",
        "abdomen_full",
    }
    assert (package / "overlays/all_parts.png").is_file()
    assert (package / "qa_panels/left_forearm.png").is_file()
    assert verify_packages(package)[0].passed
    verify_human_gold_audit_record(
        {
            "image_id": manifest["image_id"],
            "label": "left_forearm",
            "gold_package_path": package.relative_to(tmp_path).as_posix(),
            "gold_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "gold_freeze_sha256": hashlib.sha256(
                (package / ".maskfactory_frozen.json").read_bytes()
            ).hexdigest(),
            "gold_mask_sha256": hashlib.sha256(gold_mask.read_bytes()).hexdigest(),
        },
        tmp_path,
    )
    sample_root = tmp_path / "sample_root"
    shutil.copytree(package, sample_root / "approved_first")
    shutil.copytree(package, sample_root / "approved_second")
    sampled = verify_packages(sample_root, sample=1)
    assert len(sampled) == 1 and sampled[0].passed


def test_autonomous_certification_freezes_explicit_machine_truth_without_human_relabel(
    clean_package: Path, tmp_path: Path, monkeypatch
) -> None:
    package = tmp_path / "autonomous"
    shutil.copytree(clean_package, package)
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mask = package / "masks" / "left_forearm.png"
    manifest["parts"]["left_forearm"].update(
        {
            "mask_file": "masks/left_forearm.png",
            "mask_sha256": hashlib.sha256(mask.read_bytes()).hexdigest(),
            "status": "draft_model_generated",
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _refresh_hashes(package)
    issued = "2026-07-14T12:00:00+00:00"
    certificate = {
        "schema_version": "2.0.0",
        "audit_authority": "human_anchor_gold",
        "certificate_id": "cert_small_parts_fixture",
        "risk_bucket": "small_parts",
        "covered_labels": ["left_forearm"],
        "covered_contexts": ["solo"],
        "pipeline_fingerprint": "pipeline-v2",
        "expires_at": "2026-08-14T12:00:00Z",
        "passed": True,
    }
    certificate["sha256"] = hashlib.sha256(
        json.dumps(certificate, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    evidence = tmp_path / "autonomy_evidence.json"
    evidence.write_text('{"hard_gates":"pass"}\n', encoding="utf-8")
    semantic_alignment_document = {"schema_version": "fixture"}
    semantic_report_sha256 = semantic_alignment_report_sha256(semantic_alignment_document)
    semantic_alignment_document["report_sha256"] = semantic_report_sha256
    semantic_alignment = tmp_path / "semantic_alignment.json"
    semantic_alignment.write_text(json.dumps(semantic_alignment_document), encoding="utf-8")
    monkeypatch.setattr(
        "maskfactory.packager.validate_package_semantic_alignment",
        lambda *_args, **_kwargs: {
            "status": "pass",
            "report_sha256": semantic_report_sha256,
            "quorum_sha256": "e" * 64,
        },
    )
    dvc_calls = []

    result = certify_autonomous_package(
        package,
        certificates=(certificate,),
        context="solo",
        pipeline_fingerprint="pipeline-v2",
        evidence_path=evidence,
        semantic_alignment_path=semantic_alignment,
        critic_role_certificates=({"certificate_sha256": "f" * 64},),
        critic_catalog={"schema_version": "fixture"},
        dvc_add=dvc_calls.append,
        now=lambda: datetime.fromisoformat(issued),
    )

    assert result.passed and dvc_calls == [package]
    sealed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert sealed["truth_tier"] == "autonomous_certified_gold"
    assert sealed["truth_partition"] == "train"
    assert sealed["training_loss_weight"] == 0.65
    assert sealed["workflow_status"] == "autonomous_certified"
    assert sealed["parts"]["left_forearm"]["status"] == "autonomous_certified_gold"
    assert sealed["parts"]["left_forearm"]["status"] != "human_approved_gold"
    assert sealed["review"]["reviewer"] is None
    assert sealed["certification"]["certificates"][0]["risk_bucket"] == "small_parts"
    assert sealed["certification"]["semantic_alignment_report_sha256"] == semantic_report_sha256
    assert sealed["certification"]["critic_quorum_sha256"] == "e" * 64
    freeze = json.loads((package / ".maskfactory_frozen.json").read_text(encoding="utf-8"))
    assert freeze["authority"] == "autonomous_certified_gold"
    assert verify_packages(package)[0].passed


@pytest.mark.parametrize(
    "failure_mode",
    [
        "dvc_exception",
        "evidence_drift",
        "semantic_drift",
        "semantic_content_drift",
        "mask_drift",
    ],
)
def test_autonomous_certification_interruption_or_hash_drift_restores_exact_package(
    clean_package: Path, tmp_path: Path, failure_mode: str, monkeypatch
) -> None:
    package = tmp_path / f"autonomous_{failure_mode}"
    shutil.copytree(clean_package, package)
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mask = package / "masks" / "left_forearm.png"
    manifest["parts"]["left_forearm"].update(
        {
            "mask_file": "masks/left_forearm.png",
            "mask_sha256": hashlib.sha256(mask.read_bytes()).hexdigest(),
            "status": "draft_model_generated",
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _refresh_hashes(package)
    before = _tree_bytes(package)
    certificate = {
        "schema_version": "2.0.0",
        "audit_authority": "human_anchor_gold",
        "certificate_id": "cert_atomic_fixture",
        "risk_bucket": "small_parts",
        "covered_labels": ["left_forearm"],
        "covered_contexts": ["solo"],
        "pipeline_fingerprint": "pipeline-v2",
        "expires_at": "2026-08-14T12:00:00Z",
        "passed": True,
    }
    certificate["sha256"] = hashlib.sha256(
        json.dumps(certificate, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    evidence = tmp_path / f"evidence_{failure_mode}.json"
    evidence.write_text('{"hard_gates":"pass"}\n', encoding="utf-8")
    semantic_alignment_document = {"schema_version": "fixture"}
    semantic_report_sha256 = semantic_alignment_report_sha256(semantic_alignment_document)
    semantic_alignment_document["report_sha256"] = semantic_report_sha256
    semantic_alignment = tmp_path / f"semantic_{failure_mode}.json"
    semantic_alignment.write_text(json.dumps(semantic_alignment_document), encoding="utf-8")
    monkeypatch.setattr(
        "maskfactory.packager.validate_package_semantic_alignment",
        lambda *_args, **_kwargs: {
            "status": "pass",
            "report_sha256": semantic_report_sha256,
            "quorum_sha256": "e" * 64,
        },
    )

    def seeded_failure(_path: Path) -> None:
        if failure_mode == "dvc_exception":
            raise RuntimeError("seeded autonomous DVC interruption")
        if failure_mode == "evidence_drift":
            evidence.write_text('{"hard_gates":"drifted"}\n', encoding="utf-8")
        elif failure_mode == "semantic_drift":
            semantic_alignment.write_text(json.dumps({"report_sha256": "0" * 64}), encoding="utf-8")
        elif failure_mode == "semantic_content_drift":
            semantic_alignment.write_text(
                json.dumps(
                    {
                        "report_sha256": semantic_report_sha256,
                        "unbound_change": True,
                    }
                ),
                encoding="utf-8",
            )
        else:
            mask.write_bytes(b"seeded post-QA mask drift")

    expected = "DVC interruption" if failure_mode == "dvc_exception" else "drifted"
    with pytest.raises(RuntimeError, match=expected):
        certify_autonomous_package(
            package,
            certificates=(certificate,),
            context="solo",
            pipeline_fingerprint="pipeline-v2",
            evidence_path=evidence,
            semantic_alignment_path=semantic_alignment,
            critic_role_certificates=({"certificate_sha256": "f" * 64},),
            critic_catalog={"schema_version": "fixture"},
            dvc_add=seeded_failure,
            now=lambda: datetime.fromisoformat("2026-07-14T12:00:00+00:00"),
        )

    assert _tree_bytes(package) == before
    assert not (package / ".maskfactory_frozen.json").exists()
    assert not tuple(package.parent.glob(f".{package.name}.*"))


def test_single_package_dvc_failure_restores_prepared_package_exactly(
    clean_package: Path, tmp_path: Path
) -> None:
    package = tmp_path / "dvc_failure"
    shutil.copytree(clean_package, package)
    with pytest.raises(ApprovalRequiredError):
        approve_package(
            package,
            reviewer="kevin",
            review_minutes=9,
            approved=False,
            dvc_add=lambda _path: None,
        )
    before = _tree_bytes(package)

    def fail_dvc(_path: Path) -> None:
        raise RuntimeError("seeded DVC failure")

    with pytest.raises(RuntimeError, match="seeded DVC failure"):
        approve_package(
            package,
            reviewer="kevin",
            review_minutes=9,
            approved=True,
            dvc_add=fail_dvc,
        )

    assert _tree_bytes(package) == before
    assert not (package / ".maskfactory_frozen.json").exists()
    assert not tuple(package.parent.glob(f".{package.name}.*"))


def test_multi_instance_dvc_failure_restores_every_prepared_instance(
    clean_package: Path, tmp_path: Path
) -> None:
    image_root = tmp_path / "img_a3f9c2e17b04"
    roots = tuple(image_root / "instances" / f"p{index}" for index in range(2))
    for root in roots:
        shutil.copytree(clean_package, root)
        with pytest.raises(ApprovalRequiredError):
            approve_package(
                root,
                reviewer="kevin",
                review_minutes=12,
                approved=False,
                dvc_add=lambda _path: None,
            )
    before = {root: _tree_bytes(root) for root in roots}
    dvc_calls = []

    def fail_dvc(path: Path) -> None:
        dvc_calls.append(path)
        raise RuntimeError("seeded image-level DVC failure")

    with pytest.raises(RuntimeError, match="image-level DVC failure"):
        approve_packages_atomically(
            roots,
            reviewer="kevin",
            review_minutes=12,
            approved=True,
            dvc_add=fail_dvc,
        )

    assert dvc_calls == [image_root]
    assert {root: _tree_bytes(root) for root in roots} == before
    assert not any((root / ".maskfactory_frozen.json").exists() for root in roots)
    assert not tuple((image_root / "instances").glob(".*.image-approval-*"))


def test_multi_instance_approval_freezes_all_and_registers_image_once(
    clean_package: Path, tmp_path: Path
) -> None:
    image_root = tmp_path / "img_b4e8d3f26c15"
    roots = tuple(image_root / "instances" / f"p{index}" for index in range(2))
    for root in roots:
        shutil.copytree(clean_package, root)
    dvc_calls = []

    results = approve_packages_atomically(
        roots,
        reviewer="kevin",
        review_minutes=15,
        approved=True,
        dvc_add=dvc_calls.append,
    )

    assert tuple(result.package_root for result in results) == roots
    assert all(result.passed for result in results)
    assert dvc_calls == [image_root]
    assert all((root / ".maskfactory_frozen.json").is_file() for root in roots)
    assert all(
        json.loads((root / "manifest.json").read_text())["workflow_status"] == "approved_gold"
        for root in roots
    )
    assert not tuple((image_root / "instances").glob(".*.image-approval-*"))
