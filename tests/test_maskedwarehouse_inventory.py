import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "inventory_maskedwarehouse", ROOT / "tools" / "inventory_maskedwarehouse.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
build_inventory = MODULE.build_inventory


def _save(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(array).save(path)


def test_inventory_roles_counts_hashes_and_encodings(tmp_path: Path) -> None:
    rgb = np.zeros((8, 10, 3), dtype=np.uint8)
    binary = np.zeros((8, 10), dtype=np.uint8)
    binary[2:6, 3:7] = 255
    indexed = np.arange(80, dtype=np.uint8).reshape(8, 10) % 4
    color = np.zeros((8, 10, 3), dtype=np.uint8)
    color[:, 5:] = (255, 0, 0)

    _save(tmp_path / "CelebAMask-HQ" / "CelebA-HQ-img" / "0.jpg", rgb)
    _save(tmp_path / "CelebAMask-HQ" / "CelebAMask-HQ-mask-anno" / "0_skin.png", binary)
    _save(tmp_path / "LaPa" / "train" / "images" / "a.jpg", rgb)
    _save(tmp_path / "LaPa" / "train" / "labels" / "a.png", indexed)
    _save(tmp_path / "Body" / "LV-MHP-v1" / "images" / "a.jpg", rgb)
    _save(tmp_path / "Body" / "LV-MHP-v1" / "annotations" / "a.png", indexed)
    _save(
        tmp_path / "Body" / "UniDataPro_swimsuit-human-segmentation-dataset" / "1" / "image.jpg",
        rgb,
    )
    _save(
        tmp_path / "Body" / "UniDataPro_swimsuit-human-segmentation-dataset" / "1" / "mask.png",
        color,
    )
    _save(tmp_path / "Body" / "archive" / "Men I" / "img" / "a.jpg", rgb)
    _save(tmp_path / "Body" / "archive" / "Men I" / "masks" / "a.png", binary)

    inventory = build_inventory(tmp_path, sample_count=2)
    sources = {source["source"]: source for source in inventory["sources"]}

    assert inventory["source_count"] == 5
    assert all(source["counts"]["images"] == 1 for source in sources.values())
    assert all(source["counts"]["masks"] == 1 for source in sources.values())
    assert sources["celebamask_hq"]["observed_mask_encoding"] == "binary_grayscale"
    assert sources["lapa"]["observed_mask_encoding"] == "indexed_grayscale"
    assert sources["swimsuit_preview"]["observed_mask_encoding"] == "rgb_or_rgba_color_map"
    assert all(source["image_samples"][0]["sha256"] for source in sources.values())
    json.dumps(inventory)
