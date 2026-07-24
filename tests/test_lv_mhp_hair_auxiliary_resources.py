from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.external_supervision_evidence import seal_payload
from maskfactory.vlm.canonical_polygon_source_candidates import sha256_file
from maskfactory.vlm.lv_mhp_hair_auxiliary_resources import (
    LvMhpHairAuxiliaryResourceError,
    materialize_lv_mhp_hair_auxiliary_resources,
    verify_lv_mhp_hair_auxiliary_resource_report,
)


def _write_input(root: Path, *, face: bool = True) -> dict[str, Path]:
    content = root / "source" / "LV-MHP-v1"
    (content / "images").mkdir(parents=True)
    (content / "annotations").mkdir()
    source_files, identities, selected = [], [], []
    for index, split in enumerate(("train", "test"), start=1):
        image_id = f"{index:04d}"
        image_path = content / "images" / f"{image_id}.jpg"
        Image.fromarray(np.zeros((20, 20, 3), dtype=np.uint8), mode="RGB").save(image_path)
        first = np.zeros((20, 20), dtype=np.uint8)
        first[2:5, 2:6] = 2
        if face:
            first[7:12, 3:8] = 11
        second = np.zeros((20, 20), dtype=np.uint8)
        second[2:5, 14:18] = 2
        paths = []
        for instance, raster in ((1, first), (2, second)):
            relative = f"annotations/{image_id}_02_{instance:02d}.png"
            path = content / relative
            Image.fromarray(raster, mode="L").save(path)
            paths.append(relative)
            source_files.append(
                {"path": relative, "size": path.stat().st_size, "sha256": sha256_file(path)}
            )
        source_files.append(
            {
                "path": f"images/{image_id}.jpg",
                "size": image_path.stat().st_size,
                "sha256": sha256_file(image_path),
            }
        )
        identities.append(
            {
                "image_id": image_id,
                "image_path": f"images/{image_id}.jpg",
                "annotation_paths": paths,
                "instance_ids": [1, 2],
                "person_count": 2,
            }
        )
        selected.append(
            {
                "sample_id": f"hair-{image_id}",
                "source_image_id": f"lv_mhp_v1_{image_id}",
                "source_instance_id": 1,
                "declared_person_count": 2,
                "source_relative_path": f"images/{image_id}.jpg",
                "source_sha256": sha256_file(image_path),
                "source_dimensions": [20, 20],
                "instance_annotation_relative_path": paths[0],
                "instance_annotation_sha256": sha256_file(content / paths[0]),
                "mask_pixel_count": 12,
                "split": split,
            }
        )
    manifest = {
        "schema_version": "1.0.0",
        "artifact_type": "external_supervision_source_hash_manifest",
        "source": "lv_mhp_v1",
        "gate": "source_hash_manifested",
        "status": "PASS",
        "file_count": len(source_files),
        "files": sorted(source_files, key=lambda item: item["path"]),
    }
    manifest["seal_sha256"] = seal_payload(manifest)
    identity = {
        "schema_version": "1.0.0",
        "artifact_type": "external_supervision_identity_evidence",
        "source": "lv_mhp_v1",
        "gate": "instance_identity_validated",
        "status": "PASS",
        "image_count": len(identities),
        "annotation_count": len(identities) * 2,
        "records": identities,
    }
    identity["seal_sha256"] = seal_payload(identity)
    manifest_path, identity_path, remap_path = (
        root / "manifest.json",
        root / "identity.json",
        root / "remap.yaml",
    )
    manifest_path.write_text(json.dumps(manifest))
    identity_path.write_text(json.dumps(identity))
    remap_path.write_text(
        "source: lv_mhp_v1\nmappings:\n"
        "  2: {source_label: hair, action: direct, part: [hair]}\n"
        "  11: {source_label: face, action: direct, part: [head_face]}\n"
    )
    candidate = {
        "self_sha256": "a" * 64,
        "input_bindings": {
            "source_hash_manifest_sha256": sha256_file(manifest_path),
            "identity_evidence_sha256": sha256_file(identity_path),
            "remap_sha256": sha256_file(remap_path),
        },
        "selected": selected,
    }
    candidate_path = root / "candidate.json"
    candidate_path.write_text(json.dumps(candidate))
    return {
        "source_root": content.parent,
        "candidate_path": candidate_path,
        "manifest_path": manifest_path,
        "identity_path": identity_path,
        "remap_path": remap_path,
    }


def _materialize(
    inputs: dict[str, Path], output: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, object]:
    monkeypatch.setattr(
        "maskfactory.vlm.lv_mhp_hair_auxiliary_resources.verify_lv_mhp_hair_control_candidates",
        lambda _: None,
    )
    return materialize_lv_mhp_hair_auxiliary_resources(
        source_root=inputs["source_root"],
        candidate_document=json.loads(inputs["candidate_path"].read_text()),
        source_hash_manifest_path=inputs["manifest_path"],
        identity_evidence_path=inputs["identity_path"],
        remap_path=inputs["remap_path"],
        output_root=output,
    )


def test_direct_resources_are_sealed_but_laterality_blocks_defect_emission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _materialize(_write_input(tmp_path), tmp_path / "output", monkeypatch)
    assert report["record_count"] == 2
    assert report["materialized_resource_roles"] == [
        "neighbor_mask",
        "other_owner_mask",
        "protected_region_mask",
        "wrong_label_mask",
    ]
    assert report["all_seeded_defect_resources_materialized"] is False
    assert report["seeded_defect_taxonomy_emission_allowed"] is False
    assert report["seeded_defect_controls_emitted"] is False
    verify_lv_mhp_hair_auxiliary_resource_report(report, tmp_path / "output")


def test_missing_direct_face_aborts_without_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output"
    with pytest.raises(LvMhpHairAuxiliaryResourceError, match="direct face resource unavailable"):
        _materialize(_write_input(tmp_path, face=False), output, monkeypatch)
    assert not output.exists()


def test_verifier_rejects_resource_byte_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _materialize(_write_input(tmp_path), tmp_path / "output", monkeypatch)
    path = tmp_path / "output" / report["records"][0]["resource_roles"]["neighbor_mask"]["path"]
    Image.fromarray(np.zeros((20, 20), dtype=np.uint8), mode="L").save(path)
    with pytest.raises(LvMhpHairAuxiliaryResourceError, match="encoded hash drift"):
        verify_lv_mhp_hair_auxiliary_resource_report(report, tmp_path / "output")
