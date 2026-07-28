import json
from pathlib import Path

import numpy as np
from PIL import Image

from maskfactory.io.png_strict import read_mask, write_label_map
from maskfactory.qa.autofix import run_autofix_once


def test_autofix_attempts_only_allowlist_once_and_logs_recheck(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    Image.fromarray(np.zeros((128, 128, 3), dtype=np.uint8)).save(package / "source.png")
    part = np.zeros((128, 128), dtype=np.uint16)
    part[20:100, 20:100] = 18
    part[50:52, 50:52] = 0  # 4 px interior hole, under 0.5% of the large component.
    part[5:8, 5:8] = 18  # 9 px disconnected component, under 64 px.
    material = np.zeros((128, 128), dtype=np.uint8)
    material[part == 18] = 1
    write_label_map(package / "label_map_part.png", part, bits=16)
    write_label_map(package / "label_map_material.png", material, bits=8)
    (package / "manifest.json").write_text(
        json.dumps(
            {"source": {"source_width": 128, "source_height": 128}, "parts": {}, "files": {}}
        ),
        encoding="utf-8",
    )

    first = run_autofix_once(package)
    fixed = read_mask(package / "label_map_part.png")
    assert first["changes"]["component_pixels_dropped"] == 9
    assert first["changes"]["hole_pixels_filled"] == 4
    assert np.all(fixed[5:8, 5:8] == 0)
    assert np.all(fixed[50:52, 50:52] == 18)
    first_bytes = (package / "label_map_part.png").read_bytes()
    second = run_autofix_once(package)
    assert second == first
    assert (package / "label_map_part.png").read_bytes() == first_bytes
    assert (package / "qa" / "autofix.json").is_file()
    assert first["policy"] == [
        "regenerate_binaries_from_maps",
        "drop_components_lt_max_64px_or_2pct_part",
        "fill_holes_lt_0_5pct_part",
        "rederive_unions",
    ]
