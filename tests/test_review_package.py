import json
import zipfile
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.cvat_bridge.push import _discover_instances, _review_archive
from maskfactory.derive import derive_package
from maskfactory.io.png_strict import write_binary_mask, write_grayscale, write_label_map
from maskfactory.ontology import get_ontology
from maskfactory.packager import verify_packages
from maskfactory.review_package import (
    assemble_review_package,
    ensure_parent_source_identity,
    finalize_image_package_index,
    update_package_workflow_status,
)
from maskfactory.stages.s09_5_instance_recon import (
    ReconciliationInstance,
    reconcile_instances,
)
from maskfactory.validation import validate_document


def test_review_package_is_schema_valid_complete_and_cvat_discoverable(tmp_path: Path) -> None:
    image_id = "img_a3f9c2e17b04"
    source = tmp_path / "source.png"
    Image.new("RGB", (64, 48), "gray").save(source)
    part = np.zeros((48, 64), dtype=np.uint16)
    part[10:38, 10:30] = 18
    material = np.zeros((48, 64), dtype=np.uint8)
    material[10:38, 10:30] = 1
    part_path = write_label_map(tmp_path / "part.png", part, bits=16)
    material_path = write_label_map(tmp_path / "material.png", material, bits=8)
    ambiguity_path = write_grayscale(
        tmp_path / "ambiguous_do_not_use.png",
        np.pad(np.full((4, 4), 255, dtype=np.uint8), ((12, 32), (12, 48))),
        source_size=(64, 48),
    )
    s09 = tmp_path / "s09"
    write_grayscale(
        s09 / "work/s09/disagreement.png",
        np.zeros((48, 64), dtype=np.uint8),
        source_size=(64, 48),
    )
    s11 = tmp_path / "s11"
    (s11 / "qa_panels").mkdir(parents=True)
    Image.new("RGB", (64, 48), "gray").save(s11 / "qa_panels/all_parts.png")
    report = {
        "image_id": image_id,
        "run_id": "qa_20260711_2300_fixture",
        "pipeline_version": "maskfactory 0.0.1",
        "created_at": "2026-07-11T23:00:00Z",
        "checks": [],
        "metrics_per_part": {},
        "consensus": {"method": "weighted_vote_v1", "sources": ["sam2"]},
        "vlm_review": {"model": "qwen2.5vl:7b", "verdicts": []},
        "overall": "needs_human",
        "score": 0.8,
    }
    (s11 / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
    pose = {
        "view": "front",
        "pose_tags": ["standing"],
    }
    (tmp_path / "pose.json").write_text(json.dumps(pose), encoding="utf-8")
    packages = tmp_path / "packages"
    package = assemble_review_package(
        image_id=image_id,
        instance_index=0,
        source_crop_path=source,
        part_map_path=part_path,
        material_map_path=material_path,
        s09_dir=s09,
        s11_dir=s11,
        pose_path=tmp_path / "pose.json",
        person_bbox_xyxy=(5, 5, 55, 43),
        context_bbox_xyxy=(0, 0, 64, 48),
        person_count=1,
        intake_source={
            "source_sha256": "a" * 64,
            "source_origin": "owned_photo",
            "original_name": "owned.png",
            "ingested_at": "2026-07-11T22:00:00Z",
        },
        package_root=packages / image_id / "instances/p0",
        ambiguity_path=ambiguity_path,
    )
    manifest = json.loads((package / "manifest.json").read_text())
    assert validate_document(manifest, "manifest") == ()
    assert manifest["workflow_status"] == "drafted"
    assert manifest["source"]["parent_source_sha256"] == "a" * 64
    manifest["source"].pop("parent_source_sha256")
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert ensure_parent_source_identity(package, "a" * 64)
    assert not ensure_parent_source_identity(package, "a" * 64)
    with pytest.raises(RuntimeError, match="conflicting parent"):
        ensure_parent_source_identity(package, "b" * 64)
    assert update_package_workflow_status(package, "in_review", updated_at="2026-07-12T15:00:00Z")
    assert not update_package_workflow_status(package, "drafted")
    manifest = json.loads((package / "manifest.json").read_text())
    assert manifest["workflow_status"] == "in_review"
    assert manifest["workflow_updated_at"] == "2026-07-12T15:00:00Z"
    expected = {
        label.name
        for label in get_ontology().labels_for_map("part", enabled_only=True)
        if label.id != 0
    }
    assert set(manifest["parts"]) == expected
    left_forearm = manifest["parts"]["left_forearm"]
    assert left_forearm["visibility"] == "ambiguous_do_not_use"
    assert left_forearm["status"] == "n/a"
    assert left_forearm["mask_file"] is None
    assert "careful human review" in left_forearm["notes"]
    assert manifest["parts"]["right_forearm"]["status"] == "n/a"
    baseline = json.loads(
        (package / "annotations/draft_baseline/baseline_manifest.json").read_text()
    )
    assert baseline["image_id"] == image_id and baseline["instance_id"] == "p0"
    assert baseline["source_stage"] == "S09_weighted_consensus"
    assert (
        manifest["files"]["annotations/draft_baseline/label_map_part.png"]
        == baseline["part_map_sha256"]
    )
    instances = _discover_instances(packages, image_id)
    assert len(instances) == 1 and instances[0].package_root == package
    archive, frames = _review_archive(list(instances))
    with zipfile.ZipFile(BytesIO(archive)) as opened:
        names = opened.namelist()
    assert frames[0]["context"] == ["all_parts_overlay.png", "disagreement_heatmap.png"]
    assert any("all_parts_overlay.png" in name for name in names)


def test_multi_instance_package_index_round_trip_and_trivial_n1(tmp_path: Path) -> None:
    image_id = "img_b3f9c2e17b04"
    image_root = tmp_path / "packages" / image_id
    packages = tuple(
        _minimal_review_package(tmp_path / f"build{index}", image_root, image_id, index, 2)
        for index in range(2)
    )
    first = np.zeros((40, 80), dtype=bool)
    second = np.zeros_like(first)
    first[5:35, 5:35] = True
    second[5:35, 35:65] = True
    reconciliation = reconcile_instances(
        image_id=image_id,
        source_file="source.png",
        instances=(
            ReconciliationInstance("p0", first, (0, 0, 40, 40), packages[0]),
            ReconciliationInstance("p1", second, (30, 0, 70, 40), packages[1]),
        ),
        output_dir=tmp_path / "reconciliation",
        background_person_count=0,
        crowd_scene=False,
    )
    index_path = finalize_image_package_index(image_root, reconciliation.image_manifest_path)
    assert index_path == image_root / "image_manifest.json"
    for instance_id, other_id in (("p0", "p1"), ("p1", "p0")):
        manifest = json.loads((image_root / f"instances/{instance_id}/manifest.json").read_text())
        assert manifest["interperson"] == [
            {
                "other_instance_id": f"{image_id}_{other_id}",
                "relationship": "contact",
                "contact_band_file": "masks_regions/interperson_contact_boundary.png",
            }
        ]
    verified = verify_packages(image_root)
    assert len(verified) == 2 and all(item.passed for item in verified)

    solo_id = "img_c3f9c2e17b04"
    solo_root = tmp_path / "packages" / solo_id
    solo = _minimal_review_package(tmp_path / "solo", solo_root, solo_id, 0, 1)
    solo_reconciliation = reconcile_instances(
        image_id=solo_id,
        source_file="source.png",
        instances=(
            ReconciliationInstance("p0", np.ones((40, 40), dtype=bool), (0, 0, 40, 40), solo),
        ),
        output_dir=tmp_path / "solo_reconciliation",
        background_person_count=0,
        crowd_scene=False,
    )
    finalize_image_package_index(solo_root, solo_reconciliation.image_manifest_path)
    solo_manifest = json.loads((solo / "manifest.json").read_text())
    assert solo_manifest["interperson"] == []
    assert len(verify_packages(solo_root)) == 1


def _minimal_review_package(
    build_root: Path,
    image_root: Path,
    image_id: str,
    instance_index: int,
    person_count: int,
) -> Path:
    build_root.mkdir(parents=True)
    source = build_root / "source.png"
    Image.new("RGB", (40, 40), "gray").save(source)
    part = np.zeros((40, 40), dtype=np.uint16)
    part[8:32, 8:28] = 18
    material = np.zeros((40, 40), dtype=np.uint8)
    material[8:32, 8:28] = 1
    part_path = write_label_map(build_root / "part.png", part, bits=16)
    material_path = write_label_map(build_root / "material.png", material, bits=8)
    s09 = build_root / "s09"
    write_grayscale(
        s09 / "work/s09/disagreement.png",
        np.zeros((40, 40), dtype=np.uint8),
        source_size=(40, 40),
    )
    s11 = build_root / "s11"
    (s11 / "qa_panels").mkdir(parents=True)
    Image.new("RGB", (40, 40), "gray").save(s11 / "qa_panels/all_parts.png")
    report = {
        "image_id": image_id,
        "run_id": "qa_20260712_0400_fixture",
        "pipeline_version": "maskfactory 0.0.1",
        "created_at": "2026-07-12T04:00:00Z",
        "checks": [],
        "metrics_per_part": {},
        "consensus": {"method": "weighted_vote_v1", "sources": ["sam2"]},
        "vlm_review": {"model": "qwen2.5vl:7b", "verdicts": []},
        "overall": "needs_human",
        "score": 0.8,
    }
    (s11 / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
    pose = build_root / "pose.json"
    pose.write_text(json.dumps({"view": "front", "pose_tags": ["standing"]}))
    package = assemble_review_package(
        image_id=image_id,
        instance_index=instance_index,
        source_crop_path=source,
        part_map_path=part_path,
        material_map_path=material_path,
        s09_dir=s09,
        s11_dir=s11,
        pose_path=pose,
        person_bbox_xyxy=(0, 0, 40, 40),
        context_bbox_xyxy=(0, 0, 40, 40),
        person_count=person_count,
        intake_source={
            "source_sha256": "a" * 64,
            "source_origin": "owned_photo",
            "original_name": "owned.png",
            "ingested_at": "2026-07-12T04:00:00Z",
        },
        package_root=image_root / f"instances/p{instance_index}",
    )
    derive_package(package)
    write_binary_mask(
        package / "masks_regions/waist.png",
        np.zeros((40, 40), dtype=np.uint8),
        source_size=(40, 40),
    )
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for label in get_ontology().labels:
        if label.enabled and label.map != "material" and label.name not in manifest["parts"]:
            manifest["parts"][label.name] = {
                "mask_type": label.mask_type,
                "visibility": label.visibility_default,
                "mask_file": None,
                "status": "n/a",
            }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return package
