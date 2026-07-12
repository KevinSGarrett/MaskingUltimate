import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.intake import IntakeResult
from maskfactory.orchestrator import STAGE_BY_NAME, StageContext, load_pipeline_config, run_pipeline
from maskfactory.qa.multi_instance import run_multi_instance_qc
from maskfactory.stages import production
from maskfactory.stages.s01_person_detection import RankedPerson, S01Result
from maskfactory.stages.s05_geometry import run_s05_production
from test_qa_report_schema import valid_report


def test_production_runner_factory_executes_real_file_contract_through_s01(
    tmp_path: Path, monkeypatch
) -> None:
    image_id = "img_a3f9c2e17b04"
    images = tmp_path / "images"
    directory = images / image_id
    directory.mkdir(parents=True)
    source = directory / "source.png"
    Image.new("RGB", (100, 120), "white").save(source)
    manifest = {
        "image_id": image_id,
        "status": "ingested",
        "source": {
            "source_file": "source.png",
            "source_sha256": "a" * 64,
            "source_width": 100,
            "source_height": 120,
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def fake_s01(image_path, output_dir, **kwargs):
        (output_dir / "p0").mkdir()
        Image.new("RGB", (80, 100), "white").save(output_dir / "p0/person_ctx.png")
        person = RankedPerson(
            0,
            (10, 10, 90, 110),
            (5, 5, 95, 115),
            0.9,
            8000,
            2 / 3,
            1.0,
            8000.0,
            0,
            True,
            False,
        )
        (output_dir / "person_bbox.json").write_text(
            json.dumps({"persons": [{"person_index": 0}]}), encoding="utf-8"
        )
        return S01Result("promoted", None, (person,))

    monkeypatch.setattr(production, "run_s01", fake_s01)
    config = load_pipeline_config(Path("configs/pipeline.yaml"))
    results = run_pipeline(
        image_id,
        selected=("S00", "S01"),
        config=config,
        work_root=tmp_path / "work",
        runners=production.build_production_runners(config, images_root=images),
    )
    assert [result.stage for result in results] == ["S00", "S01"]
    assert all(result.status == "complete" for result in results)
    s00 = json.loads((tmp_path / f"work/s00/{image_id}/manifest_delta.json").read_text())
    s01 = json.loads((tmp_path / f"work/s01/{image_id}/manifest_delta.json").read_text())
    assert s00["source_width"] == 100
    assert s01 == {
        "background_people": 0,
        "detector_source": "yolo11m",
        "outcome": "promoted",
        "promoted_instances": 1,
    }


def test_s02_production_runner_forwards_entire_governed_stage_contract(
    tmp_path: Path, monkeypatch
) -> None:
    image_id = "img_a3f9c2e17b04"
    images = tmp_path / "images"
    image_dir = images / image_id
    image_dir.mkdir(parents=True)
    Image.new("RGB", (100, 120), "white").save(image_dir / "source.png")
    (image_dir / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": image_id,
                "status": "ingested",
                "source": {
                    "source_file": "source.png",
                    "source_sha256": "a" * 64,
                    "source_width": 100,
                    "source_height": 120,
                },
            }
        ),
        encoding="utf-8",
    )
    work = tmp_path / "work"
    s01_dir = work / "s01" / image_id
    (s01_dir / "p0").mkdir(parents=True)
    Image.new("RGB", (90, 110), "white").save(s01_dir / "p0/person_ctx.png")
    (s01_dir / "person_bbox.json").write_text(
        json.dumps(
            {
                "persons": [
                    {
                        "person_index": 0,
                        "context_bbox_xyxy": [5, 5, 95, 115],
                        "bbox_xyxy": [10, 10, 90, 110],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_s02(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(silhouette_bbox_ratio=0.6, qc_passed=True)

    monkeypatch.setattr(production, "run_s02", fake_s02)
    config = load_pipeline_config(Path("configs/pipeline.yaml"))
    context = StageContext(
        image_id=image_id,
        stage=STAGE_BY_NAME["S02"],
        output_dir=work / "s02" / image_id,
        work_root=work,
        config={"global": config.get("global", {}), "stage": config["stages"]["S02"]},
        config_hash="fixture",
    )

    delta = production.build_production_runners(config, images_root=images)["S02"](context)

    assert delta["qc_passed"] is True
    assert captured["tile_size"] == 2048
    assert captured["tile_overlap"] == 128
    assert captured["threshold"] == 0.5
    assert captured["connected_min_person_pct"] == 0.01
    assert captured["ratio_range"] == (0.35, 0.95)


def test_s02_production_runner_returns_verified_human_resolution(
    tmp_path: Path, monkeypatch
) -> None:
    image_id = "img_a3f9c2e17b04"
    images = tmp_path / "images"
    image_dir = images / image_id
    image_dir.mkdir(parents=True)
    Image.new("RGB", (10, 12), "white").save(image_dir / "source.png")
    (image_dir / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": image_id,
                "source": {
                    "source_file": "source.png",
                    "source_width": 10,
                    "source_height": 12,
                },
            }
        ),
        encoding="utf-8",
    )
    work = tmp_path / "work"
    s01 = work / "s01" / image_id
    (s01 / "p0").mkdir(parents=True)
    Image.new("RGB", (8, 12), "white").save(s01 / "p0/person_ctx.png")
    (s01 / "person_bbox.json").write_text(
        json.dumps(
            {
                "persons": [
                    {
                        "person_index": 0,
                        "context_bbox_xyxy": [1, 0, 9, 12],
                        "bbox_xyxy": [2, 1, 8, 11],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        production,
        "run_s02",
        lambda *args, **kwargs: SimpleNamespace(silhouette_bbox_ratio=0.3, qc_passed=False),
    )
    captured = {}

    def apply(**kwargs):
        captured.update(kwargs)
        return {
            "decision": "confirmed_valid",
            "reviewer": "kevin",
            "silhouette_bbox_ratio": 0.3,
            "resolution_sha256": "d" * 64,
        }

    monkeypatch.setattr(production, "apply_s02_review_resolution", apply)
    config = load_pipeline_config(Path("configs/pipeline.yaml"))
    context = StageContext(
        image_id=image_id,
        stage=STAGE_BY_NAME["S02"],
        output_dir=work / "s02" / image_id,
        work_root=work,
        config={"global": {}, "stage": config["stages"]["S02"]},
        config_hash="a" * 64,
    )
    delta = production.build_production_runners(config, images_root=images)["S02"](context)
    assert delta["qc_passed"] is delta["human_review_passed"] is True
    assert delta["review_decision"] == "confirmed_valid"
    assert captured["config_hash"] == "a" * 64
    assert captured["work_root"] == work

    def refuse(**kwargs):
        raise production.ReviewResolutionError("tampered evidence")

    monkeypatch.setattr(production, "apply_s02_review_resolution", refuse)
    with pytest.raises(production.SemanticStageError, match="tampered evidence"):
        production.build_production_runners(config, images_root=images)["S02"](context)


def test_s02_review_resolution_forces_cached_terminal_refresh(tmp_path: Path, monkeypatch) -> None:
    image_id = "img_a3f9c2e17b04"
    image_dir = tmp_path / "images" / image_id
    image_dir.mkdir(parents=True)
    Image.new("RGB", (10, 12), "white").save(image_dir / "source.png")
    (image_dir / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": image_id,
                "source": {"source_file": "source.png", "source_width": 10, "source_height": 12},
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def pipeline(image_id_arg, *, selected, work_root, force=(), **kwargs):
        assert image_id_arg == image_id
        calls.append((tuple(selected), tuple(force)))
        if tuple(selected) == ("S00", "S01"):
            directory = Path(work_root) / "s01" / image_id
            (directory / "p0").mkdir(parents=True)
            (directory / "person_bbox.json").write_text(
                json.dumps(
                    {
                        "persons": [
                            {
                                "person_index": 0,
                                "promoted": True,
                                "bbox_xyxy": [2, 1, 8, 11],
                                "context_bbox_xyxy": [1, 0, 9, 12],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
        return ()

    monkeypatch.setattr(production, "s02_review_refresh_required", lambda *args: True)
    result = production.run_multi_person_production(
        image_id,
        config=load_pipeline_config(Path("configs/pipeline.yaml")),
        images_root=tmp_path / "images",
        work_root=tmp_path / "work",
        pipeline_runner=pipeline,
        runner_factory=lambda *args, **kwargs: {},
        silhouettes_only=True,
    )
    assert result.terminal_outcome is None
    assert calls == [(("S00", "S01"), ()), (("S02",), ("S02",))]


@pytest.mark.parametrize("key,value", [("model", "other"), ("precision", "fp32")])
def test_s02_production_runner_refuses_ungoverned_runtime(
    tmp_path: Path, monkeypatch, key: str, value: str
) -> None:
    image_id = "img_a3f9c2e17b04"
    images = tmp_path / "images"
    image_dir = images / image_id
    image_dir.mkdir(parents=True)
    Image.new("RGB", (10, 10), "white").save(image_dir / "source.png")
    (image_dir / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": image_id,
                "status": "ingested",
                "source": {"source_file": "source.png", "source_width": 10, "source_height": 10},
            }
        ),
        encoding="utf-8",
    )
    s01_dir = tmp_path / "work" / "s01" / image_id
    (s01_dir / "p0").mkdir(parents=True)
    Image.new("RGB", (10, 10), "white").save(s01_dir / "p0/person_ctx.png")
    (s01_dir / "person_bbox.json").write_text(
        json.dumps(
            {
                "persons": [
                    {
                        "person_index": 0,
                        "context_bbox_xyxy": [0, 0, 10, 10],
                        "bbox_xyxy": [0, 0, 10, 10],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config = load_pipeline_config(Path("configs/pipeline.yaml"))
    settings = dict(config["stages"]["S02"])
    settings[key] = value
    context = StageContext(
        image_id=image_id,
        stage=STAGE_BY_NAME["S02"],
        output_dir=tmp_path / "work" / "s02" / image_id,
        work_root=tmp_path / "work",
        config={"global": {}, "stage": settings},
        config_hash="fixture",
    )

    with pytest.raises(production.SemanticStageError, match="governed"):
        production.build_production_runners(config, images_root=images)["S02"](context)


def test_s03_production_runner_forwards_governed_parser_contract(
    tmp_path: Path, monkeypatch
) -> None:
    image_id = "img_a3f9c2e17b04"
    work = tmp_path / "work"
    s01_dir = work / "s01" / image_id
    (s01_dir / "p0").mkdir(parents=True)
    crop = s01_dir / "p0/person_ctx.png"
    Image.new("RGB", (80, 100), "white").save(crop)
    (s01_dir / "person_bbox.json").write_text(
        json.dumps(
            {
                "persons": [
                    {
                        "person_index": 0,
                        "context_bbox_xyxy": [10, 10, 90, 110],
                        "bbox_xyxy": [15, 15, 85, 105],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_s03(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(parsing_degraded=False, sapiens_scale=1.0)

    monkeypatch.setattr(production, "run_s03_production", fake_s03)
    config = load_pipeline_config(Path("configs/pipeline.yaml"))
    settings = config["stages"]["S03"]
    context = StageContext(
        image_id=image_id,
        stage=STAGE_BY_NAME["S03"],
        output_dir=work / "s03" / image_id,
        work_root=work,
        config={"global": {}, "stage": settings},
        config_hash="fixture",
    )

    delta = production.build_production_runners(config)["S03"](context)

    assert delta["parsing_degraded"] is False
    assert captured["sapiens_long_side"] == 1024
    assert captured["tile_size"] == 1536
    assert captured["tile_overlap"] == 128
    assert captured["local_cuda_python"] == Path(
        "C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe"
    )
    assert captured["schp_cache"] == Path("models/runtime_cache/schp")


@pytest.mark.parametrize(
    "key,value",
    [
        ("model", "other"),
        ("precision", "fp32"),
        ("oom_half_res_retry", False),
        ("fallback", "none"),
    ],
)
def test_s03_production_runner_refuses_governance_drift(
    tmp_path: Path, key: str, value: object
) -> None:
    image_id = "img_a3f9c2e17b04"
    s01_dir = tmp_path / "work" / "s01" / image_id
    (s01_dir / "p0").mkdir(parents=True)
    Image.new("RGB", (10, 10), "white").save(s01_dir / "p0/person_ctx.png")
    config = load_pipeline_config(Path("configs/pipeline.yaml"))
    settings = dict(config["stages"]["S03"])
    settings[key] = value
    context = StageContext(
        image_id=image_id,
        stage=STAGE_BY_NAME["S03"],
        output_dir=tmp_path / "work" / "s03" / image_id,
        work_root=tmp_path / "work",
        config={"global": {}, "stage": settings},
        config_hash="fixture",
    )

    with pytest.raises(production.SemanticStageError, match="governed"):
        production.build_production_runners(config)["S03"](context)


def test_s04_production_runner_forwards_governed_pose_contract(tmp_path: Path, monkeypatch) -> None:
    image_id = "img_a3f9c2e17b04"
    images = tmp_path / "images"
    image_dir = images / image_id
    image_dir.mkdir(parents=True)
    Image.new("RGB", (100, 120), "white").save(image_dir / "source.png")
    (image_dir / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": image_id,
                "status": "ingested",
                "source": {
                    "source_file": "source.png",
                    "source_width": 100,
                    "source_height": 120,
                },
            }
        ),
        encoding="utf-8",
    )
    work = tmp_path / "work"
    s01_dir = work / "s01" / image_id
    s01_dir.mkdir(parents=True)
    (s01_dir / "person_bbox.json").write_text(
        json.dumps(
            {
                "persons": [
                    {
                        "person_index": 0,
                        "promoted": True,
                        "bbox_xyxy": [10, 10, 90, 110],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_s04(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(view="front", pose_tags=("arms_down",), pose_degraded=False)

    monkeypatch.setattr(production, "run_s04_production", fake_s04)
    config = load_pipeline_config(Path("configs/pipeline.yaml"))
    context = StageContext(
        image_id=image_id,
        stage=STAGE_BY_NAME["S04"],
        output_dir=work / "s04" / image_id,
        work_root=work,
        config={"global": {}, "stage": config["stages"]["S04"]},
        config_hash="fixture",
    )

    delta = production.build_production_runners(config, images_root=images)["S04"](context)

    assert delta["view"] == "front"
    assert captured["require_cuda"] is True and captured["use_wsl"] is True
    assert captured["confidence_min"] == 0.3
    assert captured["degraded_body_fraction"] == 0.6
    assert captured["local_cuda_python"] == Path(
        "C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe"
    )
    assert captured["ort_gpu_site"] == Path("models/runtime_cache/onnxruntime_gpu")


def test_s04_production_runner_refuses_model_drift(tmp_path: Path) -> None:
    config = load_pipeline_config(Path("configs/pipeline.yaml"))
    settings = dict(config["stages"]["S04"])
    settings["model"] = "other"
    context = StageContext(
        image_id="img_a3f9c2e17b04",
        stage=STAGE_BY_NAME["S04"],
        output_dir=tmp_path / "work/s04/img_a3f9c2e17b04",
        work_root=tmp_path / "work",
        config={"global": {}, "stage": settings},
        config_hash="fixture",
    )

    with pytest.raises(production.SemanticStageError, match="governed"):
        production.build_production_runners(config)["S04"](context)


def test_s06_production_runner_forwards_exact_prompt_and_threshold_contract(
    tmp_path: Path, monkeypatch
) -> None:
    image_id = "img_a3f9c2e17b04"
    work = tmp_path / "work"
    crop_dir = work / "s01" / image_id / "p0"
    crop_dir.mkdir(parents=True)
    Image.new("RGB", (20, 30), "white").save(crop_dir / "person_ctx.png")
    captured = {}

    def fake_s06(image_path, output_dir, **kwargs):
        captured.update(kwargs)
        path = Path(output_dir) / "gdino_boxes.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "authority": "proposal_boxes_only",
                    "may_write_final_masks": False,
                    "proposals": [],
                }
            ),
            encoding="utf-8",
        )
        return path

    monkeypatch.setattr(production, "run_s06_production", fake_s06)
    config = load_pipeline_config(Path("configs/pipeline.yaml"))
    context = StageContext(
        image_id=image_id,
        stage=STAGE_BY_NAME["S06"],
        output_dir=work / "s06" / image_id,
        work_root=work,
        config={"global": {}, "stage": config["stages"]["S06"]},
        config_hash="fixture",
    )

    delta = production.build_production_runners(config)["S06"](context)

    assert delta["authority"] == "proposal_boxes_only"
    assert captured["prompts"] == (
        "hair",
        "bra",
        "underwear",
        "shoe",
        "sock",
        "glove",
        "necklace",
        "handheld object",
        "chair",
        "bed",
        "surface",
    )
    assert captured["box_threshold"] == 0.3
    assert captured["text_threshold"] == 0.25
    assert captured["local_python"] == Path("C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe")
    assert captured["source_path"] == Path(
        "models/runtime_cache/groundingdino/856dde20aee659246248e20734ef9ba5214f5e44"
    )
    assert captured["dependency_site"] == Path("models/runtime_cache/groundingdino_deps")
    assert captured["hf_home"] == Path("models/runtime_cache/huggingface")


def test_s06_production_runner_refuses_threshold_source_drift(tmp_path: Path) -> None:
    config = load_pipeline_config(Path("configs/pipeline.yaml"))
    settings = dict(config["stages"]["S06"])
    settings["box_threshold"] = 0.31
    context = StageContext(
        image_id="img_a3f9c2e17b04",
        stage=STAGE_BY_NAME["S06"],
        output_dir=tmp_path / "work/s06/img_a3f9c2e17b04",
        work_root=tmp_path / "work",
        config={"global": {}, "stage": settings},
        config_hash="fixture",
    )

    with pytest.raises(production.SemanticStageError, match="threshold configuration drift"):
        production.build_production_runners(config)["S06"](context)


def test_s07_production_runner_forwards_governed_large_and_fallback_models(
    tmp_path: Path, monkeypatch
) -> None:
    image_id = "img_a3f9c2e17b04"
    work = tmp_path / "work"
    crop_dir = work / "s01" / image_id / "p0"
    crop_dir.mkdir(parents=True)
    Image.new("RGB", (20, 30), "white").save(crop_dir / "person_ctx.png")
    (crop_dir.parent / "person_bbox.json").write_text(
        json.dumps(
            {
                "persons": [
                    {
                        "person_index": 0,
                        "promoted": True,
                        "bbox_xyxy": [0, 0, 20, 30],
                        "context_bbox_xyxy": [0, 0, 20, 30],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_s07(*args, **kwargs):
        captured.update(kwargs)
        return {}, kwargs["primary_model"]

    hand_audit = {}

    def fake_hand_audit(results, **kwargs):
        hand_audit.update(kwargs)
        return {"failure_record_count": 0}

    monkeypatch.setattr(production, "run_s07_production", fake_s07)
    monkeypatch.setattr(production, "apply_and_record_s07_hand_merges", fake_hand_audit)
    config = load_pipeline_config(Path("configs/pipeline.yaml"))
    context = StageContext(
        image_id=image_id,
        stage=STAGE_BY_NAME["S07"],
        output_dir=work / "s07" / image_id,
        work_root=work,
        config={"global": {}, "stage": config["stages"]["S07"]},
        config_hash="fixture",
    )

    delta = production.build_production_runners(config)["S07"](context)

    assert delta["embedding_count"] == 1
    assert captured["primary_model"] == "sam2.1_hiera_large"
    assert captured["fallback_model"] == "sam2.1_hiera_base_plus"
    assert captured["provider"].local_cuda_python == Path(
        "C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe"
    )
    assert captured["provider"].source_path == Path(
        "models/runtime_cache/sam2/2b90b9f5ceec907a1c18123530e92e794ad901a4"
    )
    assert captured["provider"].dependency_site == Path("models/runtime_cache/sam2_deps")
    assert hand_audit["instance_id"] == "p0"
    assert hand_audit["pose_path"] == work / "s04" / image_id / "pose133.json"


def test_s07_production_runner_refuses_model_alias_drift(tmp_path: Path) -> None:
    config = load_pipeline_config(Path("configs/pipeline.yaml"))
    settings = dict(config["stages"]["S07"])
    settings["primary_model"] = "unknown"
    context = StageContext(
        image_id="img_a3f9c2e17b04",
        stage=STAGE_BY_NAME["S07"],
        output_dir=tmp_path / "work/s07/img_a3f9c2e17b04",
        work_root=tmp_path / "work",
        config={"global": {}, "stage": settings},
        config_hash="fixture",
    )

    with pytest.raises(production.SemanticStageError, match="not governed"):
        production.build_production_runners(config)["S07"](context)


def test_s05_production_projects_full_canvas_inputs_into_context_contract(tmp_path: Path) -> None:
    parsing = np.zeros((100, 80), dtype=np.uint8)
    parsing[15:75, 25:55] = 22  # Sapiens torso
    parsing[20:55, 10:25] = 10  # left upper arm
    parsing[50:85, 10:25] = 6  # left lower arm
    parsing[3:18, 27:53] = 3  # hair
    Image.fromarray(parsing, mode="L").save(tmp_path / "parsing.png")
    full = np.zeros((120, 100), dtype=np.uint8)
    full[10:110, 10:90] = 255
    Image.fromarray(full, mode="L").save(tmp_path / "silhouette.png")
    coords = {
        5: (50, 30),
        6: (70, 30),
        7: (25, 55),
        9: (25, 90),
        11: (52, 78),
        12: (68, 78),
        15: (52, 105),
        17: (50, 108),
        18: (55, 108),
        19: (52, 105),
    }
    pose = {
        "view": "front",
        "keypoints": [
            {
                "index": index,
                "x": coords.get(index, (60, 60))[0],
                "y": coords.get(index, (60, 60))[1],
                "confidence": 0.9 if index in coords else 0.0,
            }
            for index in range(133)
        ],
    }
    (tmp_path / "pose.json").write_text(json.dumps(pose), encoding="utf-8")
    config = yaml.safe_load(Path("configs/pipeline.yaml").read_text(encoding="utf-8"))
    output = tmp_path / "s05"
    priors, plans, crops = run_s05_production(
        parsing_path=tmp_path / "parsing.png",
        silhouette_path=tmp_path / "silhouette.png",
        pose_path=tmp_path / "pose.json",
        context_bbox_xyxy=(10, 10, 90, 110),
        parsing_map=config["parsing_map"]["sapiens_28"],
        output_dir=output,
    )
    assert {"left_upper_arm", "left_forearm", "hair", "chest_upper_torso"} <= priors.keys()
    assert all(mask.shape == (100, 80) for mask in priors.values())
    assert len(plans) == len(priors)
    assert any(request.label == "left_foot" for request in crops)
    document = json.loads((output / "prompts.json").read_text(encoding="utf-8"))
    assert len(document["plans"]) == len(priors)
    assert (output / "debug/left_forearm.png").is_file()


def test_s05_selects_schp_when_sapiens_is_degraded(tmp_path: Path) -> None:
    Image.new("L", (8, 8), 0).save(tmp_path / "sapiens_28.png")
    Image.new("L", (8, 8), 11).save(tmp_path / "schp_atr.png")
    (tmp_path / "parsing_metrics.json").write_text(
        json.dumps({"parsing_degraded": True}), encoding="utf-8"
    )

    path, provider = production._select_s05_parsing(tmp_path)

    assert path == tmp_path / "schp_atr.png"
    assert provider == "schp_atr"


def test_s05_pose_capsules_recover_anatomical_sides_from_swapped_parser_classes(
    tmp_path: Path,
) -> None:
    parsing = np.zeros((100, 100), dtype=np.uint8)
    parsing[20:80, 65:76] = 6  # parser says left, but this is the right pose chain
    parsing[20:80, 25:36] = 16  # parser says right, but this is the left pose chain
    Image.fromarray(parsing, mode="L").save(tmp_path / "parsing.png")
    Image.fromarray(np.full((100, 100), 255, dtype=np.uint8), mode="L").save(
        tmp_path / "silhouette.png"
    )
    coordinates = {7: (30, 25), 9: (30, 75), 8: (70, 25), 10: (70, 75)}
    pose = {
        "view": "front",
        "keypoints": [
            {
                "index": index,
                "x": coordinates.get(index, (0, 0))[0],
                "y": coordinates.get(index, (0, 0))[1],
                "confidence": 0.9 if index in coordinates else 0.0,
            }
            for index in range(133)
        ],
    }
    (tmp_path / "pose.json").write_text(json.dumps(pose), encoding="utf-8")
    config = yaml.safe_load(Path("configs/pipeline.yaml").read_text(encoding="utf-8"))

    priors, _, _ = run_s05_production(
        parsing_path=tmp_path / "parsing.png",
        silhouette_path=tmp_path / "silhouette.png",
        pose_path=tmp_path / "pose.json",
        context_bbox_xyxy=(0, 0, 100, 100),
        parsing_map=config["parsing_map"]["sapiens_28"],
        output_dir=tmp_path / "s05",
    )

    left_x = np.nonzero(priors["left_forearm"])[1].mean()
    right_x = np.nonzero(priors["right_forearm"])[1].mean()
    assert left_x < 50 < right_x


def test_s12_runner_assembles_pushes_and_reports_manual_review_pending(
    tmp_path: Path, monkeypatch
) -> None:
    image_id = "img_a3f9c2e17b04"
    images = tmp_path / "images"
    image_dir = images / image_id
    image_dir.mkdir(parents=True)
    Image.new("RGB", (80, 100), "white").save(image_dir / "source.png")
    (image_dir / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": image_id,
                "status": "ingested",
                "source": {
                    "source_file": "source.png",
                    "source_origin": "owned_photo",
                    "original_name": "owned.png",
                    "ingested_at": "2026-07-11T22:00:00Z",
                },
            }
        ),
        encoding="utf-8",
    )
    work = tmp_path / "work"
    s01 = work / "s01" / image_id
    s01.mkdir(parents=True)
    (s01 / "person_bbox.json").write_text(
        json.dumps(
            {
                "persons": [
                    {
                        "person_index": 0,
                        "promoted": True,
                        "bbox_xyxy": [10, 10, 70, 90],
                        "context_bbox_xyxy": [0, 0, 80, 100],
                        "protected_as_part_50": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    called = {}

    def fake_assemble(**kwargs):
        called["package"] = kwargs["package_root"]
        return kwargs["package_root"]

    monkeypatch.setattr(production, "assemble_review_package", fake_assemble)
    monkeypatch.setattr(production.CvatClient, "from_config", lambda path: "client")
    monkeypatch.setattr(production, "push_images", lambda *args, **kwargs: (321,))
    config = load_pipeline_config(Path("configs/pipeline.yaml"))
    runner = production.build_production_runners(config, images_root=images)["S12"]
    result = runner(
        StageContext(
            image_id,
            STAGE_BY_NAME["S12"],
            tmp_path / "s12-output",
            work,
            {"stage": config["stages"]["S12"]},
            "fixture-hash",
        )
    )
    assert result["cvat_task_ids"] == [321]
    assert result["manual_review_status"] == "pending_kevin_correction_and_approval"
    assert result["human_approved"] is False
    assert called["package"].as_posix().endswith(f"data/packages/{image_id}/instances/p0")


def test_s13_runner_writes_needs_kevin_handoff_without_approving(
    tmp_path: Path, monkeypatch
) -> None:
    image_id = "img_a3f9c2e17b04"
    package = tmp_path / f"data/packages/{image_id}/instances/p0"
    package.mkdir(parents=True)
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "parts": {
                    "left_forearm": {"status": "human_corrected"},
                    "right_forearm": {"status": "n/a"},
                }
            }
        ),
        encoding="utf-8",
    )
    config = load_pipeline_config(Path("configs/pipeline.yaml"))
    runner = production.build_production_runners(config, images_root=tmp_path / "images")["S13"]
    monkeypatch.setattr(production, "ROOT", tmp_path)
    output = tmp_path / "s13-output"
    result = runner(
        StageContext(
            image_id,
            STAGE_BY_NAME["S13"],
            output,
            tmp_path / "work",
            {"stage": config["stages"]["S13"]},
            "fixture-hash",
        )
    )
    assert result["gold_exported"] is False
    assert result["status"] == "needs_kevin_approval"
    manifest = json.loads((package / "manifest.json").read_text())
    assert manifest["parts"]["left_forearm"]["status"] == "human_corrected"
    handoff = json.loads((output / "approval_handoff.json").read_text())
    assert handoff["status"] == "needs_kevin_approval"
    assert "maskfactory package" in handoff["command"]


def test_s14_runner_enforces_200_gold_entry_gate(tmp_path: Path, monkeypatch) -> None:
    image_id = "img_a3f9c2e17b04"
    config = load_pipeline_config(Path("configs/pipeline.yaml"))
    runner = production.build_production_runners(config, images_root=tmp_path / "images")["S14"]
    monkeypatch.setattr(production, "ROOT", tmp_path)
    output = tmp_path / "s14-output"
    result = runner(
        StageContext(
            image_id,
            STAGE_BY_NAME["S14"],
            output,
            tmp_path / "work",
            {"stage": config["stages"]["S14"]},
            "fixture-hash",
        )
    )
    assert result == {
        "status": "entry_gate_not_met",
        "approved_gold_instances": 0,
        "required_approved_gold_instances": 200,
        "dataset_built": False,
    }
    assert not list((tmp_path / "datasets").glob("bodyparts@v*"))


@pytest.mark.parametrize(
    ("person_count", "review_handoff"),
    ((1, False), (2, False), (3, False), (2, True)),
)
def test_multi_person_outer_loop_runs_every_promoted_instance_then_reconciles(
    tmp_path: Path,
    person_count: int,
    review_handoff: bool,
    monkeypatch,
) -> None:
    image_id = "img_a3f9c2e17b04"
    images = tmp_path / "images" / image_id
    images.mkdir(parents=True)
    Image.new("RGB", (100, 100), "white").save(images / "source.png")
    (images / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": image_id,
                "status": "ingested",
                "source": {
                    "source_file": "source.png",
                    "source_sha256": "a" * 64,
                    "source_width": 100,
                    "source_height": 100,
                },
            }
        ),
        encoding="utf-8",
    )
    work = tmp_path / "work"
    calls = []
    pipeline_calls = []
    handoff_events = []
    progress_events = []
    monkeypatch.setattr(
        production, "persist_recovered_image_outcome", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        production,
        "persist_image_progress",
        lambda database, image_id, status, **kwargs: progress_events.append(status) or True,
    )

    def factory(config, *, images_root, person_index=0, shared_work_root=None):
        calls.append((person_index, shared_work_root))
        return {"fixture": person_index}

    def pipeline(image_id_arg, *, selected, work_root, runners, **kwargs):
        assert image_id_arg == image_id
        pipeline_calls.append((Path(work_root), tuple(selected)))
        if tuple(selected) == ("S00", "S01"):
            s01 = Path(work_root) / "s01" / image_id
            s01.mkdir(parents=True)
            persons = []
            for index in range(person_count):
                left = index * 30
                persons.append(
                    {
                        "person_index": index,
                        "promoted": True,
                        "bbox_xyxy": [left, 10, left + 20, 90],
                        "context_bbox_xyxy": [left, 0, left + 30, 100],
                        "protected_as_part_50": False,
                    }
                )
                (s01 / f"p{index}").mkdir()
                Image.new("RGB", (30, 100), "white").save(s01 / f"p{index}/person_ctx.png")
            persons.append(
                {
                    "person_index": None,
                    "promoted": False,
                    "bbox_xyxy": [90, 0, 100, 10],
                    "context_bbox_xyxy": [90, 0, 100, 10],
                    "protected_as_part_50": True,
                }
            )
            (s01 / "person_bbox.json").write_text(
                json.dumps({"persons": persons}), encoding="utf-8"
            )
        else:
            instance = Path(work_root).name
            index = 0 if instance == "legacy" else int(instance.removeprefix("p"))
            for stage in selected:
                stage_dir = Path(work_root) / stage.lower().replace(".", "_") / image_id
                stage_dir.mkdir(parents=True, exist_ok=True)
                (stage_dir / "regression_marker.json").write_text(
                    json.dumps({"image_id": image_id, "stage": stage}, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            if "S09" in selected:
                s09 = Path(work_root) / "s09" / image_id
                part = np.zeros((100, 30), dtype=np.uint16)
                part[10:90, 5:25] = 1
                material = np.zeros((100, 30), dtype=np.uint8)
                material[10:90, 5:25] = 1
                Image.fromarray(part).save(s09 / "label_map_part.png")
                Image.fromarray(material, mode="L").save(s09 / "label_map_material.png")
            if "S02" in selected:
                s02 = Path(work_root) / "s02" / image_id
                silhouette = np.zeros((100, 100), dtype=np.uint8)
                silhouette[10:90, index * 30 : index * 30 + 20] = 255
                Image.fromarray(silhouette, mode="L").save(s02 / "person_full_visible.png")
            if tuple(selected) == ("S12",):
                handoff_events.append(("s12", runners["S12"](None)))
        return ()

    def package_assembler(**kwargs):
        handoff_events.append(("package", kwargs["instance_index"]))

    def cvat_pusher(*args, **kwargs):
        handoff_events.append(("push", image_id))
        return tuple(range(101, 101 + person_count + (1 if person_count > 1 else 0)))

    legacy_root = work / "legacy"
    if person_count == 1:
        pipeline(
            image_id,
            selected=("S02", "S03", "S04", "S05", "S06", "S07", "S08", "S08.5", "S09"),
            work_root=legacy_root,
            runners={},
        )

    result = production.run_multi_person_production(
        image_id,
        config=load_pipeline_config(Path("configs/pipeline.yaml")),
        images_root=tmp_path / "images",
        work_root=work,
        pipeline_runner=pipeline,
        runner_factory=factory,
        through_autoqa=not review_handoff,
        through_review_handoff=review_handoff,
        package_assembler=package_assembler,
        cvat_pusher=cvat_pusher,
        cvat_client_factory=lambda: object(),
        cvat_task_records=tmp_path / "cvat_tasks",
        database=tmp_path / "state.sqlite",
    )
    assert set(result.per_instance) == {f"p{index}" for index in range(person_count)}
    assert calls[0] == (0, None)
    assert calls[1:] == [(index, work) for index in range(person_count)]
    manifest = json.loads(result.image_manifest_path.read_text())
    assert manifest["promoted_instances"] == [f"p{index}" for index in range(person_count)]
    assert result.qc035_passed
    assert len(result.draft_contract_paths) == person_count
    assert sum(selected == ("S10",) for _, selected in pipeline_calls) == person_count
    if review_handoff:
        assert sum(selected == ("S11",) for _, selected in pipeline_calls) == person_count
        assert sum(selected == ("S12",) for _, selected in pipeline_calls) == person_count
        assert result.cvat_task_ids == (101, 102, 103)
        assert [event[0] for event in handoff_events] == [
            "package",
            "package",
            "push",
            "s12",
            "s12",
        ]
        for _, receipt in handoff_events[-2:]:
            assert receipt["human_approved"] is False
            assert receipt["manual_review_status"] == "pending_kevin_correction_and_approval"
        assert progress_events == ["drafted", "auto_qa", "vlm_qa", "in_review"]
    else:
        assert progress_events == ["drafted", "auto_qa"]
    for contract_path in result.draft_contract_paths:
        contract = json.loads(contract_path.read_text())
        assert contract["atomic_count"] == 56
        assert len(contract["atomics"]) == 56
    p0_protected = (
        np.asarray(Image.open(work / f"instances/p0/s02/{image_id}/other_person_protected.png")) > 0
    )
    assert not p0_protected[20, 5]
    assert p0_protected[5, 95]  # non-promoted background person is protected too
    assert bool(p0_protected[:, :90].any()) == (person_count > 1)
    if person_count == 1:
        regression = production.verify_single_person_regression(
            image_id, legacy_work_root=legacy_root, p8_work_root=work
        )
        assert regression["byte_identical"] is True
        assert set(regression["stages"]) == set(production.SINGLE_PERSON_REGRESSION_STAGES)
        assert regression["file_count"] == 12
        assert set(regression["p8_only_files"]["s02"]) == {"other_person_protected.png"}


def test_multi_person_s02_terminal_is_queued_once_across_cached_reruns(tmp_path: Path) -> None:
    image_id = "img_a3f9c2e17b04"
    image_dir = tmp_path / "images" / image_id
    image_dir.mkdir(parents=True)
    Image.new("RGB", (100, 100), "white").save(image_dir / "source.png")
    (image_dir / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": image_id,
                "status": "ingested",
                "source": {
                    "source_file": "source.png",
                    "source_width": 100,
                    "source_height": 100,
                },
            }
        ),
        encoding="utf-8",
    )
    work = tmp_path / "work"

    def pipeline(image_id_arg, *, selected, work_root, **kwargs):
        assert image_id_arg == image_id
        if tuple(selected) == ("S00", "S01"):
            directory = Path(work_root) / "s01" / image_id
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "person_bbox.json").write_text(
                json.dumps(
                    {
                        "persons": [
                            {
                                "person_index": index,
                                "promoted": True,
                                "bbox_xyxy": [index * 40, 10, index * 40 + 30, 90],
                                "context_bbox_xyxy": [index * 40, 0, index * 40 + 40, 100],
                                "protected_as_part_50": False,
                            }
                            for index in range(2)
                        ]
                    }
                ),
                encoding="utf-8",
            )
            return ()
        instance = Path(work_root).name
        terminal = instance == "p1"
        return (
            production.StageExecution(
                "S02",
                "terminal" if terminal else "complete",
                "b" * 64,
                str(Path(work_root) / "s02" / image_id),
                False,
                terminal_outcome="needs_review" if terminal else None,
                terminal_reason="silhouette ratio outside range" if terminal else None,
            ),
        )

    kwargs = {
        "config": load_pipeline_config(Path("configs/pipeline.yaml")),
        "images_root": tmp_path / "images",
        "work_root": work,
        "pipeline_runner": pipeline,
        "runner_factory": lambda *args, **options: {},
        "silhouettes_only": True,
    }
    first = production.run_multi_person_production(image_id, **kwargs)
    second = production.run_multi_person_production(image_id, **kwargs)

    assert first.terminal_outcome == second.terminal_outcome == "needs_review"
    records = [
        json.loads(line)
        for line in (work / "queues/review_queue.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    assert records[0]["image_id"] == image_id
    assert records[0]["instance_id"] == "p1"
    assert records[0]["stage"] == "S02"


def test_promoted_bodypart_role_forces_stale_cached_s03_refresh(
    tmp_path: Path, monkeypatch
) -> None:
    image_id = "img_a3f9c2e17b04"
    image_dir = tmp_path / "images" / image_id
    image_dir.mkdir(parents=True)
    Image.new("RGB", (60, 80), "white").save(image_dir / "source.png")
    (image_dir / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": image_id,
                "status": "ingested",
                "source": {
                    "source_file": "source.png",
                    "source_width": 60,
                    "source_height": 80,
                },
            }
        ),
        encoding="utf-8",
    )
    work = tmp_path / "work"
    force_calls = []

    def pipeline(image_id_arg, *, selected, work_root, force=(), **kwargs):
        assert image_id_arg == image_id
        if tuple(selected) == ("S00", "S01"):
            directory = Path(work_root) / "s01" / image_id
            (directory / "p0").mkdir(parents=True)
            Image.new("RGB", (60, 80), "white").save(directory / "p0/person_ctx.png")
            (directory / "person_bbox.json").write_text(
                json.dumps(
                    {
                        "persons": [
                            {
                                "person_index": 0,
                                "promoted": True,
                                "bbox_xyxy": [0, 0, 60, 80],
                                "context_bbox_xyxy": [0, 0, 60, 80],
                                "protected_as_part_50": False,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            return ()
        instance_root = Path(work_root)
        if tuple(selected) == ("S02",):
            directory = instance_root / "s02" / image_id
            directory.mkdir(parents=True)
            Image.new("L", (60, 80), 255).save(directory / "person_full_visible.png")
            return (production.StageExecution("S02", "complete", "a" * 64, str(directory), False),)
        force_calls.append(tuple(force))
        return ()

    monkeypatch.setattr(production, "custom_bodypart_refresh_required", lambda path: True)
    result = production.run_multi_person_production(
        image_id,
        config=load_pipeline_config(Path("configs/pipeline.yaml")),
        images_root=tmp_path / "images",
        work_root=work,
        pipeline_runner=pipeline,
        runner_factory=lambda *args, **kwargs: {},
        parsing_only=True,
    )

    assert result.terminal_outcome is None
    assert force_calls == [("S03",)]


@pytest.mark.parametrize(
    ("hand_stale", "clothing_stale", "expected"),
    [
        (True, False, ("S07",)),
        (False, True, ("S08",)),
        (True, True, ("S07", "S08")),
    ],
)
def test_promoted_specialist_roles_force_their_cached_stage_refresh(
    tmp_path: Path,
    monkeypatch,
    hand_stale: bool,
    clothing_stale: bool,
    expected: tuple[str, ...],
) -> None:
    image_id = "img_a3f9c2e17b04"
    image_dir = tmp_path / "images" / image_id
    image_dir.mkdir(parents=True)
    Image.new("RGB", (60, 80), "white").save(image_dir / "source.png")
    (image_dir / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": image_id,
                "status": "ingested",
                "source": {"source_file": "source.png", "source_width": 60, "source_height": 80},
            }
        ),
        encoding="utf-8",
    )
    force_calls = []

    def pipeline(image_id_arg, *, selected, work_root, force=(), **kwargs):
        assert image_id_arg == image_id
        if tuple(selected) == ("S00", "S01"):
            directory = Path(work_root) / "s01" / image_id
            (directory / "p0").mkdir(parents=True)
            Image.new("RGB", (60, 80), "white").save(directory / "p0/person_ctx.png")
            (directory / "person_bbox.json").write_text(
                json.dumps(
                    {
                        "persons": [
                            {
                                "person_index": 0,
                                "promoted": True,
                                "bbox_xyxy": [0, 0, 60, 80],
                                "context_bbox_xyxy": [0, 0, 60, 80],
                                "protected_as_part_50": False,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            return ()
        if tuple(selected) == ("S02",):
            directory = Path(work_root) / "s02" / image_id
            directory.mkdir(parents=True)
            Image.new("L", (60, 80), 255).save(directory / "person_full_visible.png")
            return (production.StageExecution("S02", "complete", "a" * 64, str(directory), False),)
        force_calls.append(tuple(force))
        return ()

    monkeypatch.setattr(production, "custom_bodypart_refresh_required", lambda path: False)
    monkeypatch.setattr(production, "champion_hand_refresh_required", lambda path: hand_stale)
    monkeypatch.setattr(
        production, "champion_clothing_refresh_required", lambda path: clothing_stale
    )
    result = production.run_multi_person_production(
        image_id,
        config=load_pipeline_config(Path("configs/pipeline.yaml")),
        images_root=tmp_path / "images",
        work_root=tmp_path / "work",
        pipeline_runner=pipeline,
        runner_factory=lambda *args, **kwargs: {},
        densepose_only=True,
    )

    assert result.terminal_outcome is None
    assert force_calls == [expected]


def test_single_person_regression_verifier_rejects_one_byte_drift(tmp_path: Path) -> None:
    image_id = "img_a3f9c2e17b04"
    legacy = tmp_path / "legacy"
    activated = tmp_path / "activated"
    for stage in production.SINGLE_PERSON_REGRESSION_STAGES:
        left = legacy / stage / image_id
        right = activated / "instances/p0" / stage / image_id
        left.mkdir(parents=True)
        right.mkdir(parents=True)
        (left / "artifact.bin").write_bytes(stage.encode())
        (right / "artifact.bin").write_bytes(stage.encode())
    (activated / "instances/p0/s07" / image_id / "artifact.bin").write_bytes(b"drift")
    with pytest.raises(production.SemanticStageError, match="bytes differ: s07/artifact.bin"):
        production.verify_single_person_regression(
            image_id, legacy_work_root=legacy, p8_work_root=activated
        )


def test_existing_cvat_handoff_is_reused_only_when_exact(tmp_path: Path) -> None:
    image_id = "img_a3f9c2e17b04"
    records = tmp_path / "tasks"
    records.mkdir()
    for task_id, name in ((21, "p0"), (22, "p1")):
        (records / f"task_{task_id}.json").write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "job_type": "instance_review",
                    "frames": [{"image_id": image_id, "instance_id": f"{image_id}_{name}"}],
                }
            ),
            encoding="utf-8",
        )
    (records / "task_23.json").write_text(
        json.dumps(
            {
                "task_id": 23,
                "job_type": "image_overview",
                "frames": [
                    {
                        "image_id": image_id,
                        "instance_ids": [f"{image_id}_p0", f"{image_id}_p1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert production._existing_cvat_handoff_task_ids(
        image_id, ("p0", "p1"), task_records=records
    ) == (21, 22, 23)


def test_existing_cvat_handoff_fails_closed_on_partial_records(tmp_path: Path) -> None:
    image_id = "img_a3f9c2e17b04"
    records = tmp_path / "tasks"
    records.mkdir()
    (records / "task_21.json").write_text(
        json.dumps(
            {
                "task_id": 21,
                "job_type": "instance_review",
                "frames": [{"image_id": image_id, "instance_id": f"{image_id}_p0"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(production.SemanticStageError, match="partial CVAT handoff"):
        production._existing_cvat_handoff_task_ids(image_id, ("p0", "p1"), task_records=records)


def test_run_through_drafts_exposes_one_command_multi_instance_path(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = tmp_path / "image_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        production,
        "run_multi_person_production",
        lambda *args, **kwargs: production.MultiPersonProductionResult(
            shared=(),
            per_instance={"p0": (), "p1": ()},
            image_manifest_path=manifest,
            qc035_passed=True,
        ),
    )
    result = CliRunner().invoke(
        main,
        [
            "run",
            "img_a3f9c2e17b04",
            "--through-drafts",
            "--work-root",
            str(tmp_path / "work"),
            "--images-root",
            str(tmp_path / "images"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "p0: 0 stage execution(s) S02-S09" in result.output
    assert "p1: 0 stage execution(s) S02-S09" in result.output
    assert "qc035=True" in result.output


def test_run_through_silhouettes_stops_after_every_instance_s02(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = tmp_path / "person_bbox.json"
    manifest.write_text("{}", encoding="utf-8")
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return production.MultiPersonProductionResult(
            shared=(),
            per_instance={"p0": (), "p1": ()},
            image_manifest_path=manifest,
            qc035_passed=False,
        )

    monkeypatch.setattr(production, "run_multi_person_production", fake_run)
    result = CliRunner().invoke(
        main,
        [
            "run",
            "img_a3f9c2e17b04",
            "--through-silhouettes",
            "--work-root",
            str(tmp_path / "work"),
            "--images-root",
            str(tmp_path / "images"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["silhouettes_only"] is True
    assert "p0: 0 stage execution(s) S02" in result.output
    assert "S02 batch complete: 2 instance(s)" in result.output
    assert "S09.5" not in result.output


def test_run_through_parsing_stops_after_every_instance_s03(tmp_path: Path, monkeypatch) -> None:
    manifest = tmp_path / "person_bbox.json"
    manifest.write_text("{}", encoding="utf-8")
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return production.MultiPersonProductionResult(
            shared=(),
            per_instance={"p0": (), "p1": ()},
            image_manifest_path=manifest,
            qc035_passed=False,
        )

    monkeypatch.setattr(production, "run_multi_person_production", fake_run)
    result = CliRunner().invoke(
        main,
        ["run", "img_a3f9c2e17b04", "--through-parsing"],
    )
    assert result.exit_code == 0, result.output
    assert captured["parsing_only"] is True
    assert "p0: 0 stage execution(s) S02-S03" in result.output
    assert "S03 batch complete: 2 instance(s)" in result.output
    assert "S09.5" not in result.output


def test_run_through_pose_stops_after_every_instance_s04(tmp_path: Path, monkeypatch) -> None:
    manifest = tmp_path / "person_bbox.json"
    manifest.write_text("{}", encoding="utf-8")
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return production.MultiPersonProductionResult(
            shared=(),
            per_instance={"p0": (), "p1": ()},
            image_manifest_path=manifest,
            qc035_passed=False,
        )

    monkeypatch.setattr(production, "run_multi_person_production", fake_run)
    result = CliRunner().invoke(main, ["run", "img_a3f9c2e17b04", "--through-pose"])
    assert result.exit_code == 0, result.output
    assert captured["pose_only"] is True
    assert "p0: 0 stage execution(s) S02-S04" in result.output
    assert "S04 batch complete: 2 instance(s)" in result.output
    assert "S09.5" not in result.output


def test_run_through_openvocab_stops_after_every_instance_s06(tmp_path: Path, monkeypatch) -> None:
    manifest = tmp_path / "person_bbox.json"
    manifest.write_text("{}", encoding="utf-8")
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return production.MultiPersonProductionResult(
            shared=(),
            per_instance={"p0": (), "p1": ()},
            image_manifest_path=manifest,
            qc035_passed=False,
        )

    monkeypatch.setattr(production, "run_multi_person_production", fake_run)
    result = CliRunner().invoke(main, ["run", "img_a3f9c2e17b04", "--through-openvocab"])
    assert result.exit_code == 0, result.output
    assert captured["openvocab_only"] is True
    assert "p0: 0 stage execution(s) S02-S06" in result.output
    assert "S06 batch complete: 2 instance(s)" in result.output
    assert "S09.5" not in result.output


def test_run_through_sam2_stops_after_every_instance_s07(tmp_path: Path, monkeypatch) -> None:
    manifest = tmp_path / "person_bbox.json"
    manifest.write_text("{}", encoding="utf-8")
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return production.MultiPersonProductionResult(
            shared=(),
            per_instance={"p0": (), "p1": ()},
            image_manifest_path=manifest,
            qc035_passed=False,
        )

    monkeypatch.setattr(production, "run_multi_person_production", fake_run)
    result = CliRunner().invoke(main, ["run", "img_a3f9c2e17b04", "--through-sam2"])
    assert result.exit_code == 0, result.output
    assert captured["sam2_only"] is True
    assert "p0: 0 stage execution(s) S02-S07" in result.output
    assert "S07 batch complete: 2 instance(s)" in result.output
    assert "S09.5" not in result.output


def test_run_through_densepose_stops_after_every_instance_s08_5(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = tmp_path / "person_bbox.json"
    manifest.write_text("{}", encoding="utf-8")
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return production.MultiPersonProductionResult(
            shared=(),
            per_instance={"p0": (), "p1": ()},
            image_manifest_path=manifest,
            qc035_passed=False,
        )

    monkeypatch.setattr(production, "run_multi_person_production", fake_run)
    result = CliRunner().invoke(main, ["run", "img_a3f9c2e17b04", "--through-densepose"])
    assert result.exit_code == 0, result.output
    assert captured["densepose_only"] is True
    assert "p0: 0 stage execution(s) S02-S08.5" in result.output
    assert "S08.5 batch complete: 2 instance(s)" in result.output
    assert "S09.5" not in result.output


def test_run_through_autoqa_extends_each_instance_through_s10(tmp_path: Path, monkeypatch) -> None:
    manifest = tmp_path / "image_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(kwargs)
        return production.MultiPersonProductionResult(
            shared=(),
            per_instance={"p0": (), "p1": ()},
            image_manifest_path=manifest,
            qc035_passed=True,
        )

    monkeypatch.setattr(production, "run_multi_person_production", fake_run)
    result = CliRunner().invoke(
        main,
        [
            "run",
            "img_a3f9c2e17b04",
            "--through-autoqa",
            "--work-root",
            str(tmp_path / "work"),
            "--images-root",
            str(tmp_path / "images"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls[0]["through_autoqa"] is True
    assert "p0: 0 stage execution(s) S02-S10" in result.output


def test_qa_command_forces_multi_instance_s10_and_emits_valid_summary(
    tmp_path: Path, monkeypatch
) -> None:
    image_id = "img_a3f9c2e17b04"
    work = tmp_path / "work"
    report = valid_report()
    report["checks"] = [report["checks"][0]]
    report["overall"] = "pass"
    for instance in ("p0", "p1"):
        directory = work / "instances" / instance / "s10" / image_id
        directory.mkdir(parents=True)
        instance_report = json.loads(json.dumps(report))
        if instance == "p1":
            instance_report["checks"].append(
                {
                    "id": "QC-015",
                    "name": "area_sanity",
                    "scope": "instance",
                    "result": "route",
                    "severity": "ROUTE",
                }
            )
            instance_report["overall"] = "needs_human"
        (directory / "qa_report.json").write_text(json.dumps(instance_report), encoding="utf-8")
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return production.MultiPersonProductionResult(
            shared=(),
            per_instance={"p0": (), "p1": ()},
            image_manifest_path=tmp_path / "image_manifest.json",
            qc035_passed=True,
        )

    monkeypatch.setattr(production, "run_multi_person_production", fake_run)
    result = CliRunner().invoke(main, ["qa", image_id, "--work-root", str(work)])

    assert result.exit_code == 0, result.output
    assert captured["through_autoqa"] is True
    assert captured["force_autoqa"] is True
    summary = json.loads(result.output)
    assert summary["status"] == "needs_human"
    assert summary["instance_count"] == 2
    assert summary["failed_block_count"] == 0
    assert sorted(summary["instances"]) == ["p0", "p1"]


def test_qa_command_returns_nonzero_and_names_hard_blocks(tmp_path: Path, monkeypatch) -> None:
    image_id = "img_a3f9c2e17b04"
    work = tmp_path / "work"
    directory = work / "instances" / "p0" / "s10" / image_id
    directory.mkdir(parents=True)
    (directory / "qa_report.json").write_text(json.dumps(valid_report()), encoding="utf-8")
    monkeypatch.setattr(
        production,
        "run_multi_person_production",
        lambda *args, **kwargs: production.MultiPersonProductionResult(
            shared=(),
            per_instance={"p0": ()},
            image_manifest_path=tmp_path / "image_manifest.json",
            qc035_passed=True,
        ),
    )

    result = CliRunner().invoke(main, ["qa", image_id, "--work-root", str(work)])

    assert result.exit_code == 1
    summary = json.loads(result.output)
    assert summary["status"] == "blocked"
    assert summary["failed_block_count"] == 1
    assert summary["instances"]["p0"]["failed_blocks"] == ["QC-014"]


def test_vlmqa_run_forces_s10_s11_and_refuses_unavailable_gate(tmp_path: Path, monkeypatch) -> None:
    image_id = "img_a3f9c2e17b04"
    work = tmp_path / "work"
    directory = work / "instances" / "p0" / "s11" / image_id
    directory.mkdir(parents=True)
    report = valid_report()
    report["checks"] = [report["checks"][0]]
    report["overall"] = "needs_human"
    report["vlm_review"] = {"model": "qwen2.5vl:7b", "verdicts": []}
    (directory / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
    (directory / "vlm_routing.json").write_text(
        json.dumps(
            {
                "enabled": False,
                "reason": "calibration gate is missing",
                "routes": {
                    "left_forearm": {
                        "queue": "careful",
                        "priority": "high",
                        "reason": "vlm_calibration_gate_unavailable",
                    }
                },
                "whole_image_review": {"status": "skipped_gate_unavailable"},
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return production.MultiPersonProductionResult(
            shared=(),
            per_instance={"p0": ()},
            image_manifest_path=tmp_path / "image_manifest.json",
            qc035_passed=True,
        )

    monkeypatch.setattr(production, "run_multi_person_production", fake_run)
    result = CliRunner().invoke(main, ["vlmqa", "run", image_id, "--work-root", str(work)])

    assert result.exit_code == 1
    assert captured["through_vlmqa"] is True
    assert captured["force_autoqa"] is True
    assert captured["force_vlmqa"] is True
    summary = json.loads(result.output)
    assert summary["status"] == "disabled_gate_unavailable"
    assert summary["instances"]["p0"]["enabled"] is False
    assert summary["instances"]["p0"]["route_counts"] == {"careful": 1}
    assert summary["instances"]["p0"]["whole_image_status"] == "skipped_gate_unavailable"


def test_run_through_review_handoff_reports_pending_cvat_tasks(tmp_path: Path, monkeypatch) -> None:
    manifest = tmp_path / "image_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return production.MultiPersonProductionResult(
            shared=(),
            per_instance={"p0": (), "p1": ()},
            image_manifest_path=manifest,
            qc035_passed=True,
            cvat_task_ids=(31, 32, 33),
        )

    monkeypatch.setattr(production, "run_multi_person_production", fake_run)
    result = CliRunner().invoke(
        main,
        ["run", "img_a3f9c2e17b04", "--through-review-handoff"],
    )
    assert result.exit_code == 0, result.output
    assert captured["through_review_handoff"] is True
    assert "p0: 0 stage execution(s) S02-S12" in result.output
    assert "S12 CVAT tasks: 31,32,33" in result.output
    assert "status=pending_kevin_correction_and_approval" in result.output


def test_multi_instance_s10_inputs_project_maps_and_exclude_other_person(
    tmp_path: Path,
) -> None:
    image_id = "img_a3f9c2e17b04"
    work = tmp_path / "work"
    shape = (40, 80)
    p0_silhouette = np.zeros(shape, dtype=np.uint8)
    p1_silhouette = np.zeros(shape, dtype=np.uint8)
    p0_silhouette[5:35, 5:30] = 255
    p1_silhouette[5:35, 50:75] = 255
    people = []
    for index, silhouette in enumerate((p0_silhouette, p1_silhouette)):
        name = f"p{index}"
        s02 = work / "instances" / name / "s02" / image_id
        s09 = work / "instances" / name / "s09" / image_id
        (s09 / "masks_regions").mkdir(parents=True)
        s02.mkdir(parents=True)
        Image.fromarray(silhouette, mode="L").save(s02 / "person_full_visible.png")
        part = np.zeros(shape, dtype=np.uint16)
        part[silhouette > 0] = 18 + index
        if index == 0:
            part[p1_silhouette > 0] = 50
        Image.fromarray(part).save(s09 / "label_map_part.png")
        band = np.zeros(shape, dtype=np.uint8)
        band[5:35, 38:42] = 255
        Image.fromarray(band, mode="L").save(s09 / "masks_regions/interperson_contact_boundary.png")
        people.append(
            {
                "person_index": index,
                "promoted": True,
                "context_bbox_xyxy": [0, 0, 80, 40],
            }
        )
    image_manifest = work / "s09_5" / image_id / "image_manifest.json"
    image_manifest.parent.mkdir(parents=True)
    image_manifest.write_text(
        json.dumps(
            {
                "promoted_instances": ["p0", "p1"],
                "interperson_relationships": [{"a": "p0", "b": "p1"}],
            }
        ),
        encoding="utf-8",
    )

    inputs = production.build_multi_instance_qc_inputs(
        image_id,
        people=people,
        work_root=work,
        image_manifest_path=image_manifest,
        configured_cap=4,
    )
    results = {item.qc_id: item for item in run_multi_instance_qc(inputs)}
    assert not inputs.atomic_unions["p0"][p1_silhouette > 0].any()
    assert all(results[qc].passed for qc in ("QC-035", "QC-036", "QC-037", "QC-038"))


def test_d1_materializer_emits_full_resolution_all_56_atomic_contract(
    tmp_path: Path,
) -> None:
    image_id = "img_a3f9c2e17b04"
    work = tmp_path / "work"
    s09 = work / "instances/p0/s09" / image_id
    s09.mkdir(parents=True)
    part = np.zeros((3, 4), dtype=np.uint16)
    part[:, :2] = 1
    part[:, 2:] = 2
    material = np.ones((3, 4), dtype=np.uint8)
    Image.fromarray(part).save(s09 / "label_map_part.png")
    Image.fromarray(material, mode="L").save(s09 / "label_map_material.png")
    promoted = [{"person_index": 0, "context_bbox_xyxy": [1, 1, 5, 4]}]
    manifest = {"source": {"source_width": 6, "source_height": 5}}

    paths = production.materialize_d1_atomic_drafts(
        image_id,
        promoted=promoted,
        manifest=manifest,
        work_root=work,
    )

    assert len(paths) == 1
    contract = json.loads(paths[0].read_text())
    assert contract["contract"] == "D1_all_56_atomic_parts"
    assert contract["atomic_count"] == 56
    assert contract["disabled_atomic_ids"] == [54, 55]
    root = paths[0].parent
    masks = [np.asarray(Image.open(root / record["path"])) for record in contract["atomics"]]
    assert all(mask.shape == (5, 6) and set(np.unique(mask)) <= {0, 255} for mask in masks)
    assert np.count_nonzero(masks[54]) == np.count_nonzero(masks[55]) == 0
    assert sum(np.count_nonzero(mask) for mask in masks) == 30
    assert np.count_nonzero(masks[0]) == 18

    repeated = production.materialize_d1_atomic_drafts(
        image_id,
        promoted=promoted,
        manifest=manifest,
        work_root=work,
    )
    assert repeated == paths


def test_d1_materializer_refuses_disabled_or_unknown_map_ids(tmp_path: Path) -> None:
    image_id = "img_a3f9c2e17b04"
    s09 = tmp_path / "work/instances/p0/s09" / image_id
    s09.mkdir(parents=True)
    Image.fromarray(np.full((2, 2), 55, dtype=np.uint16)).save(s09 / "label_map_part.png")
    Image.fromarray(np.ones((2, 2), dtype=np.uint8), mode="L").save(s09 / "label_map_material.png")
    with pytest.raises(production.SemanticStageError, match="disabled/unknown IDs"):
        production.materialize_d1_atomic_drafts(
            image_id,
            promoted=[{"person_index": 0, "context_bbox_xyxy": [0, 0, 2, 2]}],
            manifest={"source": {"source_width": 2, "source_height": 2}},
            work_root=tmp_path / "work",
        )


def test_draft_command_ingests_runs_and_returns_verified_d1_contract(
    tmp_path: Path, monkeypatch
) -> None:
    incoming = tmp_path / "incoming"
    image = incoming / "owned" / "person.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (512, 512), "white").save(image)
    contract = tmp_path / "work/drafts/img_a3f9c2e17b04/instances/p0/draft_contract.json"
    contract.parent.mkdir(parents=True)
    contract.write_text(
        json.dumps({"contract": "D1_all_56_atomic_parts", "atomic_count": 56}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "maskfactory.intake.ingest_one",
        lambda *args, **kwargs: IntakeResult(
            "img_a3f9c2e17b04", "ingested", "accepted", manifest_path=tmp_path / "manifest.json"
        ),
    )
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return production.MultiPersonProductionResult(
            shared=(),
            per_instance={"p0": ()},
            image_manifest_path=tmp_path / "image_manifest.json",
            qc035_passed=True,
            draft_contract_paths=(contract,),
        )

    monkeypatch.setattr(production, "run_multi_person_production", fake_run)
    result = CliRunner().invoke(
        main,
        [
            "draft",
            str(image),
            "--incoming-root",
            str(incoming),
            "--images-root",
            str(tmp_path / "images"),
            "--work-root",
            str(tmp_path / "work"),
            "--database",
            str(tmp_path / "state.sqlite"),
            "--event-log",
            str(tmp_path / "intake.jsonl"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["image_id"] == "img_a3f9c2e17b04"
    assert payload["atomic_count_per_instance"] == 56
    assert payload["draft_contracts"] == [str(contract)]
    assert captured["gpu_lock_path"].name == "gpu.lock"
