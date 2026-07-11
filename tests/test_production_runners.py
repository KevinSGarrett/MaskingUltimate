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
from maskfactory.stages import production
from maskfactory.stages.s01_person_detection import RankedPerson, S01Result
from maskfactory.stages.s05_geometry import run_s05_production


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
    assert s01 == {"background_people": 0, "outcome": "promoted", "promoted_instances": 1}


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
    captured = {}

    def fake_s07(*args, **kwargs):
        captured.update(kwargs)
        return {}, kwargs["primary_model"]

    monkeypatch.setattr(production, "run_s07_production", fake_s07)
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


@pytest.mark.parametrize("person_count", (1, 2, 3))
def test_multi_person_outer_loop_runs_every_promoted_instance_then_reconciles(
    tmp_path: Path,
    person_count: int,
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
                    "source_width": 100,
                    "source_height": 100,
                },
            }
        ),
        encoding="utf-8",
    )
    work = tmp_path / "work"
    calls = []

    def factory(config, *, images_root, person_index=0, shared_work_root=None):
        calls.append((person_index, shared_work_root))
        return {"fixture": person_index}

    def pipeline(image_id_arg, *, selected, work_root, runners, **kwargs):
        assert image_id_arg == image_id
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
                Image.fromarray(silhouette, mode="L").save(s02 / "silhouette.png")
        return ()

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
    )
    assert set(result.per_instance) == {f"p{index}" for index in range(person_count)}
    assert calls[0] == (0, None)
    assert calls[1:] == [(index, work) for index in range(person_count)]
    manifest = json.loads(result.image_manifest_path.read_text())
    assert manifest["promoted_instances"] == [f"p{index}" for index in range(person_count)]
    assert result.qc035_passed
    assert len(result.draft_contract_paths) == person_count
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
