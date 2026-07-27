import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.fusion.mapbuild import (
    MapBuildError,
    export_binaries,
    fuse_package,
    priority_argmax,
    rebuild_map_from_binaries,
)
from maskfactory.io.png_strict import read_mask, write_binary_mask
from maskfactory.qa.checks import run_format_integrity
from test_manifest_schema import valid_manifest


def test_priority_argmax_uses_score_then_explicit_priority_then_id() -> None:
    left = np.zeros((4, 5), dtype=np.uint8)
    right = np.zeros_like(left)
    left[1:3, 1:4] = 255
    right[2, 2:5] = 255
    result = priority_argmax(
        {"left_forearm": left, "right_forearm": right},
        map_name="part",
        priorities={"left_forearm": 99, "right_forearm": 1},
    )
    assert result[2, 2] == 18
    assert result[2, 4] == 19
    assert result[0, 0] == 0


def test_priority_argmax_rejects_unknown_wrong_map_and_shape() -> None:
    mask = np.ones((2, 2), dtype=bool)
    with pytest.raises(MapBuildError, match="unknown ontology label"):
        priority_argmax({"invented": mask}, map_name="part")
    with pytest.raises(MapBuildError, match="does not belong"):
        priority_argmax({"skin": mask}, map_name="part")
    with pytest.raises(MapBuildError, match="shape"):
        priority_argmax(
            {"left_forearm": mask, "right_forearm": np.ones((3, 2), dtype=bool)},
            map_name="part",
        )


def test_fuse_export_and_map_roundtrip_are_exact(tmp_path: Path) -> None:
    package = tmp_path / "package"
    part_inputs = package / "annotations" / "part_masks"
    material_inputs = package / "annotations" / "material_masks"
    part_inputs.mkdir(parents=True)
    material_inputs.mkdir(parents=True)
    shape = (12, 16)
    left = np.zeros(shape, dtype=np.uint8)
    right = np.zeros(shape, dtype=np.uint8)
    skin = np.zeros(shape, dtype=np.uint8)
    clothing = np.zeros(shape, dtype=np.uint8)
    left[2:10, 1:7] = 255
    right[2:10, 9:15] = 255
    skin[2:10, 1:7] = 255
    clothing[2:10, 9:15] = 255
    for path, mask in (
        (part_inputs / "left_forearm.png", left),
        (part_inputs / "right_forearm.png", right),
        (material_inputs / "skin.png", skin),
        (material_inputs / "clothing_generic.png", clothing),
    ):
        write_binary_mask(path, mask)

    part_path, material_path = fuse_package(package)
    part_before = read_mask(part_path).astype(np.uint16)
    material_before = read_mask(material_path).astype(np.uint8)
    outputs = export_binaries(package)
    assert len(outputs) == 70  # 54 enabled PART labels + all 16 MATERIAL labels.
    assert np.array_equal(rebuild_map_from_binaries(package, "part"), part_before)
    assert np.array_equal(rebuild_map_from_binaries(package, "material"), material_before)
    assert Image.open(part_path).mode in {"I;16", "I"}
    assert Image.open(material_path).mode == "L"


def test_rebuild_rejects_manually_overlapping_binary_views(tmp_path: Path) -> None:
    package = tmp_path / "package"
    mask = np.ones((3, 3), dtype=np.uint8) * 255
    export_shape = np.zeros((3, 3), dtype=np.uint16)
    from maskfactory.io.png_strict import write_label_map

    write_label_map(package / "label_map_part.png", export_shape, bits=16)
    write_label_map(package / "label_map_material.png", export_shape, bits=8)
    export_binaries(package)
    write_binary_mask(package / "masks" / "left_forearm.png", mask)
    write_binary_mask(package / "masks" / "right_forearm.png", mask)
    with pytest.raises(MapBuildError, match="overlap"):
        rebuild_map_from_binaries(package, "part")


def test_exporter_outputs_pass_qc001_through_qc007(tmp_path: Path) -> None:
    package = tmp_path / "package"
    part = np.zeros((12, 16), dtype=np.uint16)
    material = np.zeros((12, 16), dtype=np.uint8)
    part[2:10, 2:7] = 18
    material[2:10, 2:7] = 1
    from maskfactory.io.png_strict import write_label_map

    write_label_map(package / "label_map_part.png", part, bits=16)
    write_label_map(package / "label_map_material.png", material, bits=8)
    export_binaries(package)
    source = np.zeros((12, 16, 3), dtype=np.uint8)
    Image.fromarray(source).save(package / "source.png")
    manifest = valid_manifest()
    manifest["source"].update(
        {
            "source_file": "source.png",
            "source_sha256": hashlib.sha256((package / "source.png").read_bytes()).hexdigest(),
            "source_width": 16,
            "source_height": 12,
        }
    )
    manifest["files"] = {
        path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in package.rglob("*")
        if path.is_file()
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    results = run_format_integrity(package)
    assert [result.qc_id for result in results] == [f"QC-{number:03d}" for number in range(1, 8)]
    assert all(result.passed for result in results), results
