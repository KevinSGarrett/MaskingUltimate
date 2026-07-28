from pathlib import Path

import yaml


def _config(name: str) -> dict:
    return yaml.safe_load(Path("configs/training", name).read_text(encoding="utf-8"))


def test_bodypart_segformer_b3_contract() -> None:
    config = _config("bodypart_segformer_b3.yaml")
    assert config["model"] == {
        "architecture": "segformer_b3",
        "pretrained": "imagenet",
        "num_classes": 56,
    }
    assert config["data"]["crop_size"] == [512, 512]
    assert config["data"]["ignore_index"] == 255
    assert config["optimizer"]["learning_rate"] == 0.00006
    assert config["optimizer"]["schedule"] == {
        "type": "poly",
        "power": 1.0,
        "warmup_iters": 1500,
    }
    assert config["training"] | {} == config["training"]
    assert config["training"]["iterations"] == 40000
    assert config["training"]["iterations_at_500_gold"] == 80000
    assert config["training"]["batch_per_gpu"] * config["training"]["gradient_accumulation"] == 16
    assert config["training"]["amp"] == "bf16"
    assert config["training"]["loss"] == ["cross_entropy", "dice"]
    assert config["training"]["class_weights"]["cap_multiplier"] == 8.0
    assert config["evaluation"]["interval_iters"] == 4000


def test_bodypart_mask2former_swinb_challenger_contract() -> None:
    config = _config("bodypart_mask2former_swinb.yaml")
    assert config["model"]["architecture"] == "mask2former_swin_b"
    assert config["model"]["num_classes"] == 56
    assert config["model"]["backbone"]["activation_checkpointing"] is True
    assert config["training"]["activation_checkpointing"] is True
    assert config["training"]["loss"] == {
        "type": "native_mask2former_matcher",
        "components": ["classification_cross_entropy", "mask_binary_cross_entropy", "dice"],
    }
    assert config["training"]["batch_per_gpu"] * config["training"]["gradient_accumulation"] == 16
    assert config["execution"] == {
        "swin_b": "local",
        "swin_l": "aws_burst_only",
        "aws_item": "MF-P5-08.03",
    }


def test_clothing_segformer_b2_contract() -> None:
    config = _config("clothing_segformer_b2.yaml")
    assert config["model"]["architecture"] == "segformer_b2"
    assert config["model"]["num_classes"] == 16
    assert config["training"]["iterations"] == 30000
    assert set(config["data"]["crop_class_weights"].values()) == {4.0}
    assert config["promotion_gate"]["strap_iou_min"] == 0.55
    assert config["promotion_gate"]["waistband_iou_min"] == 0.55


def test_hand_segformer_b2_contract() -> None:
    config = _config("hand_segformer_b2.yaml")
    assert config["model"]["architecture"] == "segformer_b2"
    assert config["model"]["num_classes"] == len(config["model"]["classes"]) == 14
    assert config["data"]["source_crop_size"] == 1024
    assert config["data"]["crop_size"] == [768, 768]
    assert config["data"]["multi_scale"] == [0.75, 1.25]
    assert config["data"]["horizontal_flip_swap_partner"] is True
    assert config["training"]["iterations"] == 25000
    assert config["promotion_gate"] == {
        "finger_mean_iou_min": 0.70,
        "merged_finger_false_split_rate_max": 0.02,
        "paste_back_iou_min": 0.995,
    }
