import json
from pathlib import Path

import numpy as np
import yaml

from maskfactory.derive import derive_package
from maskfactory.io.png_strict import read_mask, write_label_map
from maskfactory.ontology_source import DERIVED_FORMULAS


def test_derived_config_contains_every_exact_doc02_formula() -> None:
    document = yaml.safe_load(Path("configs/derived.yaml").read_text(encoding="utf-8"))
    assert document["formulas"] == DERIVED_FORMULAS


def test_derive_emits_all_formulas_and_expected_boolean_identities(tmp_path: Path) -> None:
    package = tmp_path / "package"
    part = np.zeros((32, 40), dtype=np.uint16)
    material = np.zeros(part.shape, dtype=np.uint8)
    part[2:10, 2:8] = 5  # left breast
    part[2:10, 10:16] = 6  # right breast
    part[12:18, 2:6] = 22  # left hand base
    part[12:18, 6:8] = 24  # left thumb
    part[20:28, 2:10] = 7  # abdomen
    part[23:25, 5:7] = 8  # belly button
    material[2:10, 2:8] = 1  # left breast skin
    material[2:10, 10:16] = 4  # right breast bra
    material[12:18, 2:8] = 1
    write_label_map(package / "label_map_part.png", part, bits=16)
    write_label_map(package / "label_map_material.png", material, bits=8)

    outputs = derive_package(package)
    assert len(outputs) == 40
    left_skin = read_mask(package / "masks_derived" / "left_breast_skin.png") > 0
    right_skin = read_mask(package / "masks_derived" / "right_breast_skin.png") > 0
    left_hand = read_mask(package / "masks_derived" / "left_hand.png") > 0
    abdomen = read_mask(package / "masks_derived" / "abdomen_full.png") > 0
    assert np.array_equal(left_skin, (part == 5) & (material == 1))
    assert not right_skin.any()
    assert np.array_equal(left_hand, (part == 22) | (part == 24))
    assert np.array_equal(abdomen, (part == 7) | (part == 8))
    manifest = json.loads((package / "masks_derived" / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["derivations"]) == set(DERIVED_FORMULAS)
    record = manifest["derivations"]["left_breast_skin"]
    assert record["formula"] == DERIVED_FORMULAS["left_breast_skin"]
    assert set(record["inputs"]) == {"label_map_part.png", "label_map_material.png"}
    assert len(record["output_sha256"]) == 64
