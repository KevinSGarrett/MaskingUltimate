import json
from pathlib import Path

import numpy as np
import pytest

from maskfactory.cvat_bridge.mask_delta import MaskDeltaError, apply_part_mask_delta
from maskfactory.io.png_strict import read_mask, write_binary_mask, write_label_map
from maskfactory.ontology import get_ontology


def test_mask_delta_stages_explicit_add_and_relabel_subtract(tmp_path: Path) -> None:
    ontology = get_ontology()
    target = ontology.label("left_hand_base")
    replacement = ontology.label("left_forearm")
    part = np.zeros((12, 12), dtype=np.uint16)
    part[2:10, 2:10] = replacement.id
    part[6:9, 6:9] = target.id
    label_map = write_label_map(tmp_path / "part.png", part, bits=16)
    silhouette = write_binary_mask(tmp_path / "silhouette.png", part > 0)
    add = np.zeros((12, 12), dtype=bool)
    add[4:6, 6:8] = True
    subtract = np.zeros((12, 12), dtype=bool)
    subtract[8, 8] = True
    add_path = write_binary_mask(tmp_path / "add.png", add)
    subtract_path = write_binary_mask(tmp_path / "subtract.png", subtract)
    output = apply_part_mask_delta(
        label_map_path=label_map,
        target_label="left_hand_base",
        output_path=tmp_path / "work" / "corrections" / "part.png",
        add_mask_path=add_path,
        subtract_mask_path=subtract_path,
        subtract_replacement_label="left_forearm",
        silhouette_path=silhouette,
    )
    result = read_mask(output)
    assert np.all(result[4:6, 6:8] == target.id)
    assert result[8, 8] == replacement.id
    evidence = json.loads(output.with_suffix(".mask_delta.json").read_text())
    assert evidence["authority"] == "human_review_staging_only"
    assert evidence["requires_normal_derivation_qa_and_human_approval"] is True


def test_mask_delta_rejects_direct_nonwork_output_and_ambiguous_subtract(tmp_path: Path) -> None:
    ontology = get_ontology()
    part = np.full((4, 4), ontology.label("left_hand_base").id, dtype=np.uint16)
    label_map = write_label_map(tmp_path / "part.png", part, bits=16)
    mask = write_binary_mask(tmp_path / "mask.png", np.ones((4, 4), dtype=bool))
    with pytest.raises(MaskDeltaError, match="work directory"):
        apply_part_mask_delta(
            label_map_path=label_map,
            target_label="left_hand_base",
            output_path=tmp_path / "gold.png",
            add_mask_path=mask,
        )
    with pytest.raises(MaskDeltaError, match="replacement"):
        apply_part_mask_delta(
            label_map_path=label_map,
            target_label="left_hand_base",
            output_path=tmp_path / "work" / "part.png",
            subtract_mask_path=mask,
        )
