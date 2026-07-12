from pathlib import Path

import pytest
import yaml

from maskfactory.ontology import get_ontology

CONFIG = yaml.safe_load(Path("configs/pipeline.yaml").read_text(encoding="utf-8"))


def test_s02_governed_contract_is_explicit() -> None:
    assert CONFIG["stages"]["S02"] == {
        "enabled": True,
        "model": "birefnet_general",
        "precision": "fp16",
        "long_side": 2048,
        "tile_overlap": 128,
        "threshold": 0.5,
        "connected_min_person_pct": 0.01,
        "silhouette_bbox_ratio": [0.35, 0.95],
        "local_cuda_python": "C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe",
        "hf_home": "models/runtime_cache/huggingface",
    }


def test_s03_governed_cuda_runtime_is_explicit() -> None:
    assert CONFIG["stages"]["S03"]["local_cuda_python"] == (
        "C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe"
    )
    assert CONFIG["stages"]["S03"]["schp_cache"] == "models/runtime_cache/schp"


def test_s04_governed_cuda_runtime_is_explicit() -> None:
    assert CONFIG["stages"]["S04"]["local_cuda_python"] == (
        "C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe"
    )
    assert CONFIG["stages"]["S04"]["ort_gpu_site"] == ("models/runtime_cache/onnxruntime_gpu")


def test_s06_governed_local_runtime_is_explicit() -> None:
    stage = CONFIG["stages"]["S06"]
    assert stage["local_python"] == "C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe"
    assert stage["source_path"].endswith("856dde20aee659246248e20734ef9ba5214f5e44")
    assert stage["dependency_site"] == "models/runtime_cache/groundingdino_deps"
    assert stage["hf_home"] == "models/runtime_cache/huggingface"


def test_s07_governed_local_cuda_runtime_is_explicit() -> None:
    stage = CONFIG["stages"]["S07"]
    assert stage["local_cuda_python"] == "C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe"
    assert stage["source_path"].endswith("2b90b9f5ceec907a1c18123530e92e794ad901a4")
    assert stage["dependency_site"] == "models/runtime_cache/sam2_deps"


def test_s08_5_governed_local_cuda_runtime_is_explicit() -> None:
    stage = CONFIG["stages"]["S08.5"]
    assert stage["local_cuda_python"] == "C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe"
    assert stage["source_path"].endswith("02b5c4e295e990042a714712c21dc79b731e8833")
    assert stage["dependency_site"] == "models/runtime_cache/detectron2_deps"


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
