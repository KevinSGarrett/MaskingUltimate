from pathlib import Path

import pytest
import yaml

from maskfactory.ontology import get_ontology

CONFIG = yaml.safe_load(Path("configs/pipeline.yaml").read_text(encoding="utf-8"))


def test_pipeline_config_has_all_stages_devices_io_and_determinism() -> None:
    assert CONFIG["seed"] == 1337
    assert CONFIG["gpu_cooldown_sec"] == 3
    assert CONFIG["io"]["workdir"] == "work"
    assert set(CONFIG["stages"]) == {
        "S00",
        "S01",
        "S02",
        "S03",
        "S04",
        "S05",
        "S06",
        "S07",
        "S08",
        "S08.5",
        "S09",
        "S09.5",
        "S10",
        "S11",
        "S12",
        "S13",
        "S14",
        "S15",
    }
    assert all(stage["enabled"] is True for stage in CONFIG["stages"].values())


def test_parsing_maps_are_complete_native_vocabularies_and_only_known_priors() -> None:
    maps = CONFIG["parsing_map"]
    assert list(maps["sapiens_28"]) == list(range(28))
    assert list(maps["schp_atr"]) == list(range(18))
    assert [entry["class"] for entry in maps["sapiens_28"].values()][6] == "left_lower_arm"
    assert [entry["class"] for entry in maps["schp_atr"].values()] == [
        "background",
        "hat",
        "hair",
        "sunglasses",
        "upper_clothes",
        "skirt",
        "pants",
        "dress",
        "belt",
        "left_shoe",
        "right_shoe",
        "face",
        "left_leg",
        "right_leg",
        "left_arm",
        "right_arm",
        "bag",
        "scarf",
    ]
    ontology = get_ontology()
    for provider in maps.values():
        for entry in provider.values():
            for name in (*entry["part_priors"], *entry["material_priors"]):
                assert ontology.label(name)


def test_pose_rules_and_fusion_contract_are_closed_and_exact() -> None:
    assert set(CONFIG["pose_tags_rules"]) == {
        "arms_raised",
        "arms_down",
        "arms_crossed",
        "seated_or_crouched",
        "lying",
        "walking",
        "leg_overlap",
    }
    weights = CONFIG["fusion"]["weights"]
    assert weights == {
        "sam2": 0.40,
        "sapiens": 0.25,
        "geometry": 0.15,
        "schp": 0.10,
        "densepose": 0.10,
        "custom_bodypart": 0.45,
    }
    assert sum(
        value for key, value in weights.items() if key != "custom_bodypart"
    ) == pytest.approx(1.0)
    assert weights["custom_bodypart"] == pytest.approx(0.45)
    rules = CONFIG["fusion"]["zorder_rules"]
    assert [rule["priority"] for rule in rules] == [10, 20, 30, 40, 100]
    assert rules[-1]["winner"] == "higher_consensus_score"
