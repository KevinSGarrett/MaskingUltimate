import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.ontology import get_ontology
from maskfactory.training.augmentations import (
    IGNORE_INDEX,
    AugmentationError,
    RareSamplingMeter,
    burn_ambiguous_to_ignore,
    horizontal_flip_label_map,
    maybe_horizontal_flip,
    photometric_jitter,
    random_resized_crop,
    rotate_sample,
    swap_id_lut,
    validate_augmentation_config,
    write_rare_sampling_metrics,
)
from maskfactory.training.dataset import MaskFactorySegmentationDataset, mmseg_dataset_config


@pytest.mark.parametrize("map_name", ["part", "material"])
def test_swap_lut_covers_every_ontology_id_and_is_reciprocal(map_name: str) -> None:
    ontology = get_ontology()
    labels = ontology.labels_for_map(map_name)
    lut = swap_id_lut(map_name, ontology=ontology)
    for label in labels:
        assert label.id is not None
        expected = (
            ontology.label(label.swap_partner).id if label.side in {"left", "right"} else label.id
        )
        assert int(lut[label.id]) == expected
        assert int(lut[int(lut[label.id])]) == label.id
    assert int(lut[IGNORE_INDEX]) == IGNORE_INDEX


def test_horizontal_flip_fixture_swaps_all_sided_part_ids() -> None:
    ontology = get_ontology()
    sided = [label for label in ontology.labels_for_map("part") if label.side in {"left", "right"}]
    original = np.array([[label.id for label in sided] + [255]], dtype=np.uint8)
    flipped = horizontal_flip_label_map(original, "part", ontology=ontology)
    expected = np.array(
        [[255] + [ontology.label(label.swap_partner).id for label in reversed(sided)]],
        dtype=np.uint8,
    )
    np.testing.assert_array_equal(flipped, expected)
    np.testing.assert_array_equal(
        horizontal_flip_label_map(flipped, "part", ontology=ontology), original
    )


def test_paired_flip_changes_pixels_and_both_maps_without_mutating_inputs() -> None:
    ontology = get_ontology()
    left_hand = ontology.label("left_hand_base").id
    right_hand = ontology.label("right_hand_base").id
    image = np.array([[[1], [2], [3]]], dtype=np.uint8)
    part = np.array([[left_hand, 0, right_hand]], dtype=np.uint8)
    material = np.array([[1, 10, 15]], dtype=np.uint8)
    original_image, original_part = image.copy(), part.copy()
    flipped_image, maps, applied = maybe_horizontal_flip(
        image,
        {"part": part, "material": material},
        random=lambda: 0.49,
        ontology=ontology,
    )
    assert applied
    np.testing.assert_array_equal(flipped_image, image[:, ::-1])
    np.testing.assert_array_equal(maps["part"], [[left_hand, 0, right_hand]])
    np.testing.assert_array_equal(maps["material"], material[:, ::-1])
    np.testing.assert_array_equal(image, original_image)
    np.testing.assert_array_equal(part, original_part)


def test_default_probability_boundary_and_unknown_id_hard_fail() -> None:
    image = np.zeros((1, 2, 3), dtype=np.uint8)
    part = np.zeros((1, 2), dtype=np.uint8)
    _, _, applied = maybe_horizontal_flip(image, {"part": part}, random=lambda: 0.5)
    assert not applied
    with pytest.raises(AugmentationError, match="unknown part label IDs"):
        horizontal_flip_label_map(np.array([[200]], dtype=np.uint8), "part")


def test_rare_crop_measures_forced_rate_and_never_loses_forced_pixel(tmp_path: Path) -> None:
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    labels = np.zeros((64, 64), dtype=np.uint8)
    labels[7, 51] = 24
    rng = np.random.default_rng(1337)
    meter = RareSamplingMeter()
    forced_outputs = []
    for _ in range(200):
        cropped_image, maps, forced = random_resized_crop(
            image,
            {"part": labels},
            rng=rng,
            output_size=16,
            rare_ids={"part": frozenset({24})},
            meter=meter,
        )
        assert cropped_image.shape == (16, 16, 3) and maps["part"].shape == (16, 16)
        if forced:
            forced_outputs.append(np.any(maps["part"] == 24))
    assert 0.32 <= meter.forced_rate <= 0.48
    assert forced_outputs and all(forced_outputs)
    assert meter.rare_contained >= meter.forced_attempts
    logged = json.loads(write_rare_sampling_metrics(tmp_path / "rare.json", meter).read_text())
    assert logged["attempts"] == 200
    assert logged["forced_rate"] == meter.forced_rate


def test_jitter_rotation_ignore_border_and_banned_guard() -> None:
    image = np.full((24, 24, 3), [100, 80, 60], dtype=np.uint8)
    labels = np.zeros((24, 24), dtype=np.uint8)
    labels[5:19, 7:17] = 18
    original = labels.copy()
    jittered = photometric_jitter(image, brightness=0.25, contrast=-0.25, saturation=0.2, hue=0.05)
    assert jittered.shape == image.shape and not np.array_equal(jittered, image)
    np.testing.assert_array_equal(labels, original)
    _rotated_image, maps = rotate_sample(image, {"part": labels}, degrees=15)
    assert set(np.unique(maps["part"])).issubset({0, 18, IGNORE_INDEX})
    assert IGNORE_INDEX in maps["part"]
    validate_augmentation_config({"pipeline": [{"type": "horizontal_flip"}]})
    for banned in ("vflip", "elastic", "perspective", "MixUp", "CutMix"):
        with pytest.raises(AugmentationError, match="banned augmentation"):
            validate_augmentation_config({"pipeline": [{"type": banned}]})


def test_dataset_adapter_burns_ambiguity_to_ignore_255(tmp_path: Path) -> None:
    sample_id = "img_a3f9c2e17b04_p0"
    (tmp_path / "part_seg/images").mkdir(parents=True)
    (tmp_path / "part_seg/annotations").mkdir(parents=True)
    (tmp_path / "material_seg/annotations").mkdir(parents=True)
    (tmp_path / "ambiguous").mkdir()
    Image.new("RGB", (8, 6), "gray").save(tmp_path / f"part_seg/images/{sample_id}.png")
    part = np.full((6, 8), 18, dtype=np.uint8)
    material = np.full((6, 8), 1, dtype=np.uint8)
    ambiguity = np.zeros((6, 8), dtype=np.uint8)
    ambiguity[2:4, 3:5] = 255
    Image.fromarray(part).save(tmp_path / f"part_seg/annotations/{sample_id}.png")
    Image.fromarray(material).save(tmp_path / f"material_seg/annotations/{sample_id}.png")
    Image.fromarray(ambiguity).save(tmp_path / f"ambiguous/{sample_id}.png")
    (tmp_path / "train.txt").write_text(sample_id + "\n", encoding="utf-8")
    dataset = MaskFactorySegmentationDataset(tmp_path, "train")
    sample = dataset.load_sample(0)
    assert len(dataset) == 1 and sample["sample_id"] == sample_id
    assert np.all(sample["part"][2:4, 3:5] == IGNORE_INDEX)
    assert np.all(sample["material"][2:4, 3:5] == IGNORE_INDEX)
    np.testing.assert_array_equal(burn_ambiguous_to_ignore(part, ambiguity), sample["part"])


def test_mmseg_configs_target_exact_export_layout_and_ignore_contract(tmp_path: Path) -> None:
    (tmp_path / "train.txt").write_text("img_a3f9c2e17b04_p0\n", encoding="utf-8")
    part = mmseg_dataset_config(tmp_path, "train", "part")
    material = mmseg_dataset_config(tmp_path, "train", "material")
    assert part == {
        "type": "MaskFactoryBodyPartDataset",
        "data_root": str(tmp_path),
        "ann_file": "train.txt",
        "data_prefix": {
            "img_path": "part_seg/images",
            "seg_map_path": "part_seg/annotations",
        },
        "img_suffix": ".png",
        "seg_map_suffix": ".png",
        "reduce_zero_label": False,
        "ignore_index": 255,
    }
    assert material["type"] == "MaskFactoryMaterialDataset"
    assert material["data_prefix"] == {
        "img_path": "material_seg/images",
        "seg_map_path": "material_seg/annotations",
    }
    with pytest.raises(ValueError, match="unknown MaskFactory MMSeg target"):
        mmseg_dataset_config(tmp_path, "train", "depth")
