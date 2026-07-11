import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.derive import derive_package
from maskfactory.fusion.mapbuild import export_binaries
from maskfactory.io.png_strict import read_mask, write_binary_mask, write_label_map
from maskfactory.versioning import VersioningError, begin_correction, promote_correction


def _frozen_package(tmp_path: Path) -> Path:
    package = tmp_path / "package"
    package.mkdir()
    Image.fromarray(np.zeros((48, 64, 3), dtype=np.uint8)).save(package / "source.png")
    part = np.zeros((48, 64), dtype=np.uint16)
    material = np.zeros((48, 64), dtype=np.uint8)
    part[10:35, 15:28] = 18
    material[10:35, 15:28] = 1
    write_label_map(package / "label_map_part.png", part, bits=16)
    write_label_map(package / "label_map_material.png", material, bits=8)
    export_binaries(package)
    derive_package(package)
    (package / "manifest.json").write_text(
        json.dumps({"source": {"source_width": 64, "source_height": 48}, "parts": {}, "files": {}}),
        encoding="utf-8",
    )
    (package / ".maskfactory_frozen.json").write_text("{}", encoding="utf-8")
    return package


def test_correction_branch_rolls_back_block_then_promotes_with_30_day_retention(
    tmp_path: Path,
) -> None:
    package = _frozen_package(tmp_path)
    original = read_mask(package / "masks" / "left_forearm.png")
    candidate = begin_correction(package, now=datetime(2026, 7, 11, tzinfo=UTC))
    tampered = read_mask(candidate / "left_forearm.png")
    tampered[0, 0] = 255
    write_binary_mask(candidate / "left_forearm.png", tampered)
    with pytest.raises(VersioningError, match="QC-007"):
        promote_correction(package, 2, human_approved=True)
    assert np.array_equal(read_mask(package / "masks" / "left_forearm.png"), original)
    assert read_mask(candidate / "left_forearm.png")[0, 0] == 255

    write_binary_mask(candidate / "left_forearm.png", original)
    promoted_at = datetime(2026, 7, 12, tzinfo=UTC)
    promote_correction(package, 2, human_approved=True, now=promoted_at)
    registry = json.loads((package / "mask_versions.json").read_text(encoding="utf-8"))
    assert registry["active_version"] == 2
    assert registry["versions"]["1"]["status"] == "deprecated"
    assert registry["versions"]["1"]["retain_until"] == "2026-08-11T00:00:00+00:00"
    assert registry["versions"]["2"]["status"] == "human_approved_gold"
    assert (package / "masks@v1" / "left_forearm.png").is_file()
    assert not (package / "masks@v2").exists()
