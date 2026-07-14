import json
from pathlib import Path

import numpy as np
from PIL import Image

from maskfactory.derive import derive_package
from maskfactory.fusion.mapbuild import export_binaries
from maskfactory.io.png_strict import read_mask, write_binary_mask, write_label_map
from maskfactory.ontology import get_ontology
from maskfactory.qa.checks import run_qc001_010


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "package"
    package.mkdir()
    Image.fromarray(np.zeros((64, 80, 3), dtype=np.uint8)).save(package / "source.png")
    part = np.zeros((64, 80), dtype=np.uint16)
    material = np.zeros((64, 80), dtype=np.uint8)
    part[10:40, 15:30] = 18
    material[10:40, 15:30] = 1
    write_label_map(package / "label_map_part.png", part, bits=16)
    write_label_map(package / "label_map_material.png", material, bits=8)
    export_binaries(package)
    derive_package(package)
    parts = {
        label.name: {"visibility": label.visibility_default}
        for label in get_ontology().labels
        if label.enabled and label.map != "material"
    }
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "source": {"source_width": 80, "source_height": 64},
                "parts": parts,
                "files": {},
            }
        ),
        encoding="utf-8",
    )
    return package


def _result(package: Path, qc_id: str):
    return next(result for result in run_qc001_010(package) if result.qc_id == qc_id)


def test_qc007_detects_hand_edit_without_overwriting_it(tmp_path: Path) -> None:
    package = _package(tmp_path)
    path = package / "masks" / "left_forearm.png"
    tampered = read_mask(path)
    tampered[0, 0] = 255
    write_binary_mask(path, tampered)
    assert not _result(package, "QC-007").passed
    assert read_mask(path)[0, 0] == 255


def test_qc008_requires_every_enabled_nonmaterial_visibility_state(tmp_path: Path) -> None:
    package = _package(tmp_path)
    assert _result(package, "QC-008").passed
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["parts"]["left_forearm"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = _result(package, "QC-008")
    assert not result.passed and "left_forearm" in result.detail


def test_qc009_recomputes_formula_not_just_hash_record(tmp_path: Path) -> None:
    package = _package(tmp_path)
    assert _result(package, "QC-009").passed
    path = package / "masks_derived" / "left_hand.png"
    tampered = read_mask(path)
    tampered[0, 0] = 255
    write_binary_mask(path, tampered)
    result = _result(package, "QC-009")
    assert not result.passed and "left_hand" in result.detail


def test_qc010_validates_schema_ontology_and_full_image_bounds(tmp_path: Path) -> None:
    package = _package(tmp_path)
    crops = package / "crops"
    crops.mkdir()
    transform = {
        "part": "left_forearm",
        "x0": 5,
        "y0": 4,
        "scale": 2.0,
        "crop_size": 64,
        "source_sha256": "a" * 64,
    }
    path = crops / "crop_to_full_transform.json"
    path.write_text(json.dumps(transform), encoding="utf-8")
    assert _result(package, "QC-010").passed
    transform["x0"] = 60
    path.write_text(json.dumps(transform), encoding="utf-8")
    assert not _result(package, "QC-010").passed
