import copy
import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from maskfactory.datasets.builder import _training_label_maps
from maskfactory.ontology import load_ontology
from maskfactory.ontology_v2 import DEFAULT_ONTOLOGY_V2
from maskfactory.ontology_v2_manifest import OntologyV2ManifestError
from maskfactory.training.augmentations import (
    IGNORE_INDEX,
    horizontal_flip_label_map,
    photometric_jitter,
    random_resized_crop,
    rotate_sample,
)
from maskfactory.training.bodypart.v2_contract import (
    V2_CLASS_NAMES,
    V2_NEW_CLASS_IDS,
    V2_NEW_CLASS_NAMES,
    V2EvaluationSample,
    V2HoldoutRecord,
    V2TrainingContractError,
    build_v2_holdout_manifest,
    evaluate_v2_holdouts,
    evaluate_v2_promotion_gate,
    plan_v2_finetune_batches,
    prepare_v2_training_map,
    supervision_contract,
    validate_v2_training_config,
)
from maskfactory.training.mmseg_compile import inverse_sqrt_class_weights


def _config(name: str) -> dict:
    return yaml.safe_load(Path("configs/training", name).read_text(encoding="utf-8"))


def _holdout_records() -> tuple[V2HoldoutRecord, ...]:
    return (
        V2HoldoutRecord("img_train_p0", "identity_train", "aaaaaaaaaaaaaaaa", "train"),
        V2HoldoutRecord(
            "img_positive_p0",
            "identity_positive",
            "0000000000000000",
            "positive_holdout",
            positive_labels=V2_NEW_CLASS_NAMES,
        ),
        V2HoldoutRecord(
            "img_clothed_p0",
            "identity_clothed",
            "ffffffffffffffff",
            "clothed_negative_holdout",
            clothed_negative=True,
        ),
    )


def test_v1_is_pretraining_only_and_unreviewed_v2_cannot_enter_finetune() -> None:
    contract = supervision_contract({"mask_ontology_version": "body_parts_v1"})
    assert contract["mode"] == "v1_pretraining_only"
    assert contract["head_num_classes"] == 56
    assert contract["supervised_ids"] == list(range(56))
    assert contract["v2_finetune_eligible"] is False
    assert contract["new_label_negative_ids"] == []
    with pytest.raises(OntologyV2ManifestError, match="v2 supervision refused"):
        supervision_contract({"mask_ontology_version": "body_parts_v2"})


def test_v2_export_preserves_ids_56_through_65_and_burns_separate_ambiguity(
    tmp_path: Path,
) -> None:
    package = tmp_path / "p0"
    package.mkdir()
    part = np.arange(56, 66, dtype=np.uint8).reshape(2, 5)
    material = np.full((2, 5), 1, dtype=np.uint8)
    ambiguity = np.zeros((2, 5), dtype=np.uint8)
    ambiguity[0, 4] = 255
    Image.fromarray(part, mode="L").save(package / "label_map_part.png")
    Image.fromarray(material, mode="L").save(package / "label_map_material.png")
    Image.fromarray(ambiguity, mode="L").save(package / "ambiguity.png")
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "mask_ontology_version": "body_parts_v2",
                "parts": {
                    "left_areola": {
                        "visibility": "ambiguous_do_not_use",
                        "ambiguity_file": "ambiguity.png",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    exported_part, exported_material = _training_label_maps(
        package, ontology=load_ontology(DEFAULT_ONTOLOGY_V2)
    )
    expected = part.copy()
    expected[0, 4] = IGNORE_INDEX
    np.testing.assert_array_equal(exported_part, expected)
    assert set(exported_part.ravel()) == set(V2_NEW_CLASS_IDS) - {60} | {IGNORE_INDEX}
    assert exported_material[0, 4] == IGNORE_INDEX
    np.testing.assert_array_equal(
        prepare_v2_training_map(part, ambiguity > 0),
        expected,
    )
    with pytest.raises(V2TrainingContractError, match="out-of-range"):
        prepare_v2_training_map(np.array([[66]], dtype=np.uint8))


@pytest.mark.parametrize(
    "name",
    ["bodypart_v2_segformer_b3.yaml", "bodypart_v2_mask2former_swinb.yaml"],
)
def test_inactive_configs_are_exact_66_class_contracts_and_never_57(name: str) -> None:
    config = _config(name)
    validate_v2_training_config(config)
    assert config["model"]["num_classes"] == len(config["model"]["classes"]) == 66
    assert tuple(config["model"]["classes"]) == V2_CLASS_NAMES
    assert config["data"]["ignore_index"] == 255
    assert config["promotion_gate"]["aggregate_miou_only_can_pass"] is False
    drifted = copy.deepcopy(config)
    drifted["model"]["num_classes"] = 57
    with pytest.raises(V2TrainingContractError, match="66 classes, never 57"):
        validate_v2_training_config(drifted)


def test_v2_flip_crop_rotation_color_and_class_weight_contracts() -> None:
    ontology = load_ontology(DEFAULT_ONTOLOGY_V2)
    original = np.array([list(V2_NEW_CLASS_IDS) + [IGNORE_INDEX]], dtype=np.uint8)
    flipped = horizontal_flip_label_map(original, "part", ontology=ontology)
    expected_names = [
        ontology.label(V2_CLASS_NAMES[class_id]).swap_partner or V2_CLASS_NAMES[class_id]
        for class_id in reversed(V2_NEW_CLASS_IDS)
    ]
    expected_ids = [ontology.label(name).id for name in expected_names]
    np.testing.assert_array_equal(
        flipped, np.array([[IGNORE_INDEX] + expected_ids], dtype=np.uint8)
    )
    np.testing.assert_array_equal(
        horizontal_flip_label_map(flipped, "part", ontology=ontology), original
    )

    image = np.full((32, 32, 3), [90, 120, 150], dtype=np.uint8)
    labels = np.zeros((32, 32), dtype=np.uint8)
    labels[4:12, 20:28] = 64
    cropped_image, cropped_maps, forced = random_resized_crop(
        image,
        {"part": labels},
        rng=np.random.default_rng(7),
        output_size=16,
        rare_ids={"part": frozenset(V2_NEW_CLASS_IDS)},
        force_rare_probability=1.0,
    )
    assert forced and cropped_image.shape == (16, 16, 3)
    assert np.any(cropped_maps["part"] == 64)
    rotated_image, rotated_maps = rotate_sample(image, {"part": labels}, degrees=15)
    assert rotated_image.shape == image.shape and IGNORE_INDEX in rotated_maps["part"]
    original_labels = labels.copy()
    jittered = photometric_jitter(image, brightness=0.2, contrast=-0.2, saturation=0.2, hue=0.04)
    assert not np.array_equal(jittered, image)
    np.testing.assert_array_equal(labels, original_labels)
    weights = inverse_sqrt_class_weights([100] * 56 + [1] * 10, cap_multiplier=8)
    assert len(weights) == 66 and max(weights) == 8


def test_batch_plan_meets_anatomy_and_whole_body_contract_without_fabrication() -> None:
    samples = [
        {"sample_id": "positive", "fully_reviewed_v2": True, "present_new_ids": [56, 58]},
        {"sample_id": "clothed", "fully_reviewed_v2": True, "present_new_ids": []},
    ]
    plan = plan_v2_finetune_batches(samples, draws=8)
    assert plan["anatomy_focused_fraction"] >= 0.5
    assert plan["whole_body_fraction"] >= 0.25
    assert plan["fabricated_positive_count"] == 0
    anatomy = [row for row in plan["selections"] if row["mode"] == "anatomy_focused_crop"]
    assert anatomy and all(row["present_new_ids"] for row in anatomy)
    with pytest.raises(V2TrainingContractError, match="unreviewed"):
        plan_v2_finetune_batches(
            [{"sample_id": "unsafe", "fully_reviewed_v2": False, "present_new_ids": [56]}],
            draws=4,
        )


def test_holdouts_are_identity_and_phash_separated_and_semantically_typed() -> None:
    manifest = build_v2_holdout_manifest(_holdout_records())
    assert manifest["identity_phash_separation_passed"] is True
    assert manifest["cohorts"]["positive_holdout"] == ["img_positive_p0"]
    assert manifest["cohorts"]["clothed_negative_holdout"] == ["img_clothed_p0"]
    leaked = list(_holdout_records())
    leaked[2] = V2HoldoutRecord(
        "img_clothed_p0",
        "identity_positive",
        "ffffffffffffffff",
        "clothed_negative_holdout",
        clothed_negative=True,
    )
    with pytest.raises(V2TrainingContractError, match="crosses v2 cohorts"):
        build_v2_holdout_manifest(leaked)
    invalid_negative = list(_holdout_records())
    invalid_negative[2] = V2HoldoutRecord(
        "img_clothed_p0",
        "identity_clothed",
        "ffffffffffffffff",
        "clothed_negative_holdout",
        positive_labels=("vulva",),
        clothed_negative=True,
    )
    with pytest.raises(V2TrainingContractError, match="not an explicit reviewed negative"):
        build_v2_holdout_manifest(invalid_negative)


def test_metrics_are_per_class_and_promotion_fails_closed_on_evidence_or_clothing() -> None:
    holdout = build_v2_holdout_manifest(_holdout_records())
    positive = np.array(V2_NEW_CLASS_IDS, dtype=np.uint8).reshape(2, 5)
    negative = np.zeros((2, 5), dtype=np.uint8)
    report = evaluate_v2_holdouts(
        (
            V2EvaluationSample(
                "img_positive_p0", "identity_positive", "positive_holdout", positive, positive
            ),
            V2EvaluationSample(
                "img_clothed_p0",
                "identity_clothed",
                "clothed_negative_holdout",
                negative,
                negative,
            ),
        ),
        positive_inventory={name: 50 for name in V2_NEW_CLASS_NAMES},
        holdout_manifest=holdout,
    )
    assert report["aggregate_only_is_sufficient"] is False
    assert [row["class_id"] for row in report["classes"]] == list(V2_NEW_CLASS_IDS)
    assert all(
        row["iou"] == row["boundary_f_2px"] == row["positive_recall"] == 1
        for row in report["classes"]
    )
    assert all(row["clothed_false_positive_image_rate"] == 0 for row in report["classes"])
    assert evaluate_v2_promotion_gate(report)["passed"] is True

    insufficient = copy.deepcopy(report)
    insufficient["classes"][0]["clear_positive_inventory"] = 49
    result = evaluate_v2_promotion_gate(insufficient)
    assert result["passed"] is False
    assert result["checks"]["left_areola"]["clear_positive_inventory_at_least_50"] is False

    clothing_fire = copy.deepcopy(report)
    clothing_fire["classes"][0].update(
        {
            "clothed_false_positive_images": 1,
            "clothed_false_positive_image_rate": 1.0,
            "clothed_false_positive_pixel_rate": 1 / 10,
            "systematic_clothed_false_positive": True,
        }
    )
    result = evaluate_v2_promotion_gate(clothing_fire)
    assert result["passed"] is False
    assert result["checks"]["left_areola"]["no_systematic_clothed_false_positive"] is False

    missing = copy.deepcopy(report)
    missing["classes"][0]["positive_recall"] = None
    assert evaluate_v2_promotion_gate(missing)["passed"] is False
