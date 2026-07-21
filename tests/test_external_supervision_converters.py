from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from maskfactory.external_supervision_converters import (
    AUTHORITY,
    IGNORE_PIXEL,
    PROOF_TIER,
    ExternalSupervisionConverterError,
    convert_component_mask,
    convert_indexed_mask,
    load_remap_plan,
)
from maskfactory.ontology import load_ontology

ROOT = Path(__file__).resolve().parents[1]
REMAP = ROOT / "configs" / "remap"


def test_lapa_face_merge_maps_skin_to_head_face_not_atomics() -> None:
    plan = load_remap_plan(REMAP / "lapa.yaml")
    ontology = load_ontology()
    indexed = np.zeros((4, 4), dtype=np.uint8)
    indexed[1:3, 1:3] = 1  # skin -> head_face
    result = convert_indexed_mask(plan, indexed, ontology=ontology)
    head_face = next(label.id for label in ontology.labels if label.name == "head_face")
    skin = next(label.id for label in ontology.labels if label.name == "skin")
    assert result.proof_tier == PROOF_TIER
    assert result.authority == AUTHORITY
    assert result.admission_ready is False
    assert result.part_map[1, 1] == head_face
    assert result.material_map[1, 1] == skin
    assert not bool(result.ignore_mask[1, 1])
    assert "skin" in result.mapped_source_labels


def test_lv_mhp_limbs_and_clothes_are_ignore_255() -> None:
    plan = load_remap_plan(REMAP / "lv_mhp_v1.yaml")
    ontology = load_ontology()
    indexed = np.zeros((3, 3), dtype=np.uint8)
    indexed[0, 0] = 14  # left_arm split_required
    indexed[0, 1] = 4  # upper_clothes split_required
    indexed[1, 1] = 11  # face direct
    result = convert_indexed_mask(plan, indexed, ontology=ontology)
    head_face = next(label.id for label in ontology.labels if label.name == "head_face")
    assert result.part_map[0, 0] == IGNORE_PIXEL
    assert result.part_map[0, 1] == IGNORE_PIXEL
    assert bool(result.ignore_mask[0, 0]) and bool(result.ignore_mask[0, 1])
    assert result.part_map[1, 1] == head_face
    assert "left_arm" in result.ignored_source_labels
    assert "upper_clothes" in result.ignored_source_labels
    assert "face" in result.mapped_source_labels


def test_celeba_cloth_component_is_ignore_not_fabricated_chest() -> None:
    plan = load_remap_plan(REMAP / "celebamask_hq.yaml")
    ontology = load_ontology()
    binary = np.zeros((5, 5), dtype=np.uint8)
    binary[2:4, 2:4] = 255
    result = convert_component_mask(plan, "cloth", binary, ontology=ontology)
    clothing = next(label.id for label in ontology.labels if label.name == "clothing_generic")
    assert result.part_map[2, 2] == IGNORE_PIXEL
    assert result.material_map[2, 2] == clothing
    assert bool(result.ignore_mask[2, 2])
    assert "cloth" in result.ignored_source_labels
    assert result.training_authority["truth_tier"] == "weighted_pseudo_label"


def test_celeba_hair_component_maps_directly() -> None:
    plan = load_remap_plan(REMAP / "celebamask_hq.yaml")
    ontology = load_ontology()
    binary = np.zeros((3, 3), dtype=np.uint8)
    binary[1, 1] = 1
    result = convert_component_mask(plan, "hair", binary, ontology=ontology)
    hair = next(label.id for label in ontology.labels if label.name == "hair")
    hair_mat = next(label.id for label in ontology.labels if label.name == "hair_material")
    assert result.part_map[1, 1] == hair
    assert result.material_map[1, 1] == hair_mat
    assert not bool(result.ignore_mask[1, 1])


def test_blocked_preview_and_gold_partition_fail_closed(tmp_path: Path) -> None:
    preview = yaml.safe_load((REMAP / "swimsuit_preview.yaml").read_text(encoding="utf-8"))
    with pytest.raises(ExternalSupervisionConverterError, match="source_blocked"):
        convert_indexed_mask(preview, np.zeros((2, 2), dtype=np.uint8))

    plan = yaml.safe_load((REMAP / "lapa.yaml").read_text(encoding="utf-8"))
    plan["training_authority"] = {
        "truth_tier": "human_anchor_gold",
        "truth_partition": "holdout",
        "holdout_eligible": True,
        "loss_weight": 1.0,
    }
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(plan), encoding="utf-8")
    bad = load_remap_plan(path)
    with pytest.raises(ExternalSupervisionConverterError, match="training_authority"):
        convert_indexed_mask(bad, np.zeros((2, 2), dtype=np.uint8))
