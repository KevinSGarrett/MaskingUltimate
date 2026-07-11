import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from maskfactory.datasets.active_learning import run_active_learning
from maskfactory.datasets.builder import build_dataset
from maskfactory.datasets.cocorle import decode_binary_mask
from maskfactory.datasets.splits import (
    SplitRecord,
    assign_splits,
    hash_split,
    validate_instance_split_integrity,
)
from maskfactory.io.png_strict import write_label_map


def test_hash_split_duplicate_groups_synthetic_and_hard_override() -> None:
    records = (
        SplitRecord("img_000000000001", "0000000000000000", "owned_photo"),
        SplitRecord("img_000000000002", "0000000000000001", "owned_photo"),
        SplitRecord("img_000000000003", "ffffffffffffffff", "generated"),
        SplitRecord("img_000000000004", "fffffffffffffffe", "owned_photo"),
    )
    splits = assign_splits(records, hard_case_ids=frozenset({"img_000000000001"}))
    assert splits["img_000000000001"] == splits["img_000000000002"] == "hard_case_holdout"
    assert splits["img_000000000003"] == splits["img_000000000004"] == "train"
    expected_bucket = int(hashlib.sha256(b"stable-image").hexdigest()[:8], 16) % 100
    expected = (
        "train" if expected_bucket <= 69 else "val" if expected_bucket <= 84 else "test_holdout"
    )
    assert hash_split("stable-image") == expected


def test_deliberately_instance_keyed_split_fixture_is_rejected() -> None:
    validate_instance_split_integrity(
        {"img_000000000001_p0": "train", "img_000000000001_p1": "train"}
    )
    with pytest.raises(ValueError, match="split leakage"):
        validate_instance_split_integrity(
            {"img_000000000001_p0": "train", "img_000000000001_p1": "test_holdout"}
        )


def test_builder_keeps_instances_together_isolates_holdout_and_rebuilds_identically(
    tmp_path: Path, monkeypatch
) -> None:
    packages = tmp_path / "packages"

    def package(image_id: str, instance: str, origin: str, phash: str) -> None:
        root = packages / image_id / "instances" / instance
        root.mkdir(parents=True)
        Image.new("RGB", (12, 10), "gray").save(root / "source.png")
        part = np.zeros((10, 12), dtype=np.uint16)
        part[2:8, 3:9] = 18
        material = np.zeros((10, 12), dtype=np.uint8)
        material[2:8, 3:9] = 1
        write_label_map(root / "label_map_part.png", part, bits=16)
        write_label_map(root / "label_map_material.png", material, bits=8)
        (root / ".maskfactory_frozen.json").write_text("{}", encoding="utf-8")
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "image_id": image_id,
                    "source": {"source_origin": origin, "phash64": phash},
                    "parts": {"left_forearm": {"status": "human_approved_gold"}},
                }
            ),
            encoding="utf-8",
        )

    package("img_000000000001", "p0", "owned_photo", "1111111111111111")
    package("img_000000000001", "p1", "owned_photo", "1111111111111111")
    package("img_000000000002", "p0", "generated", "eeeeeeeeeeeeeeee")
    hard = tmp_path / "hard.txt"
    hard.write_text("img_000000000001\n", encoding="utf-8")
    monkeypatch.setattr(
        "maskfactory.datasets.builder.verify_packages",
        lambda package: (SimpleNamespace(passed=True),),
    )
    first = build_dataset(
        packages_root=packages,
        output_root=tmp_path / "first",
        version=1,
        hard_case_file=hard,
    )
    second = build_dataset(
        packages_root=packages,
        output_root=tmp_path / "second",
        version=1,
        hard_case_file=hard,
    )
    manifest = json.loads((first / "build_manifest.json").read_text())
    assert manifest["splits"]["img_000000000001"] == "hard_case_holdout"
    assert manifest["instances"]["hard_case_holdout"] == [
        "img_000000000001_p0",
        "img_000000000001_p1",
    ]
    assert manifest["splits"]["img_000000000002"] == "train"
    assert manifest["holdout_trainer_read_path"] is None
    assert (first / "train.txt").read_text().splitlines() == ["img_000000000002_p0"]
    assert not (first / "part_seg/images/img_000000000001_p0.png").exists()
    assert (first / "holdout/hard_case/img_000000000001_p0/source.png").is_file()
    coco = json.loads((first / "coco/annotations.json").read_text())
    assert len(coco["images"]) == 1 and coco["annotations"][0]["category_id"] == 18
    decoded = decode_binary_mask(coco["annotations"][0]["segmentation"])
    assert int(decoded.sum()) == coco["annotations"][0]["area"]
    first_hashes = {
        path.relative_to(first).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in first.rglob("*")
        if path.is_file()
    }
    second_hashes = {
        path.relative_to(second).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in second.rglob("*")
        if path.is_file()
    }
    assert first_hashes == second_hashes
    card = (first / "dataset_card.md").read_text(encoding="utf-8")
    assert "## Coverage cells" in card
    assert "small_group" in card and "Synthetic ratio" in card


def test_builder_preflight_rejects_one_invalid_gold_package(
    tmp_path: Path,
    monkeypatch,
) -> None:
    packages = tmp_path / "packages"
    package = packages / "img_000000000001/instances/p0"
    package.mkdir(parents=True)
    Image.new("RGB", (4, 4), "gray").save(package / "source.png")
    write_label_map(package / "label_map_part.png", np.zeros((4, 4), dtype=np.uint16), bits=16)
    write_label_map(package / "label_map_material.png", np.zeros((4, 4), dtype=np.uint8), bits=8)
    (package / ".maskfactory_frozen.json").write_text("{}", encoding="utf-8")
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": "img_000000000001",
                "source": {"source_origin": "owned_photo", "phash64": "0" * 16},
                "parts": {"left_forearm": {"status": "human_approved_gold"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "maskfactory.datasets.builder.verify_packages",
        lambda _package: (SimpleNamespace(passed=False),),
    )
    with pytest.raises(ValueError, match="verification failed"):
        build_dataset(packages_root=packages, output_root=tmp_path / "output", version=1)
    assert not (tmp_path / "output/bodyparts@v1").exists()


def test_builder_burns_ambiguous_part_regions_to_ignore_in_both_training_maps(
    tmp_path: Path,
    monkeypatch,
) -> None:
    packages = tmp_path / "packages"
    package = packages / "img_000000000005/instances/p0"
    package.mkdir(parents=True)
    Image.new("RGB", (8, 6), "gray").save(package / "source.png")
    part = np.zeros((6, 8), dtype=np.uint16)
    part[1:5, 1:4] = 18  # left_forearm
    part[1:5, 4:7] = 19  # right_forearm, honestly ambiguous
    material = np.ones((6, 8), dtype=np.uint8)
    write_label_map(package / "label_map_part.png", part, bits=16)
    write_label_map(package / "label_map_material.png", material, bits=8)
    (package / ".maskfactory_frozen.json").write_text("{}", encoding="utf-8")
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": "img_000000000005",
                "source": {"source_origin": "owned_photo", "phash64": "5" * 16},
                "parts": {
                    "left_forearm": {"status": "human_approved_gold", "visibility": "visible"},
                    "right_forearm": {"status": "n/a", "visibility": "ambiguous_do_not_use"},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "maskfactory.datasets.builder.verify_packages",
        lambda _package: (SimpleNamespace(passed=True),),
    )
    output = build_dataset(packages_root=packages, output_root=tmp_path / "out", version=1)
    sample_id = "img_000000000005_p0"
    exported_part = np.asarray(Image.open(output / f"part_seg/annotations/{sample_id}.png"))
    exported_material = np.asarray(Image.open(output / f"material_seg/annotations/{sample_id}.png"))
    ambiguous = part == 19
    assert np.all(exported_part[ambiguous] == 255)
    assert np.all(exported_material[ambiguous] == 255)
    assert np.all(exported_part[part == 18] == 18)
    assert np.all(exported_material[~ambiguous] == 1)


def test_active_learning_combines_failure_priority_coverage_and_retrain_trigger(
    tmp_path: Path,
) -> None:
    queue = tmp_path / "failure_queue.jsonl"
    queue.write_text(
        json.dumps(
            {
                "ts": "2026-07-10T00:00:00Z",
                "image_id": "img_000000000001",
                "failed_body_part": "left_index_finger",
                "failure_reason": "finger_merge",
                "pose_angle": "arms_down",
                "model_that_failed": "draft_pipeline_full",
                "correction_needed": "separate visible finger gap",
                "priority": 0.9,
                "resolved": False,
                "resolution_pkg_version": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_active_learning(
        failure_queue_path=queue,
        coverage_matrix_path=tmp_path / "missing_coverage.json",
        output_dir=tmp_path / "reports",
        approved_gold_count=60,
        champion_gold_count=5,
        report_date="2026-07-12",
        clusterer=lambda reasons: {
            reason: "hands_fingers" if reason == "finger_merge" else "fixture_cluster"
            for reason in reasons
        },
    )
    assert result["unresolved_failure_count"] == 1
    assert result["retrain_requested"] is True
    assert result["retrain_triggers"]["new_gold_plus_50"] is True
    task = json.loads(Path(result["retrain_task"]).read_text())
    assert task["status"] == "waiting_for_p5_entry_gate"
    assert task["steps"][-1] == "record_champion_history"
    plan = Path(result["acquisition_plan"]).read_text(encoding="utf-8")
    assert "hands_fingers" in plan and "Top coverage deficits" in plan


def test_two_week_class_error_trigger_opens_idempotent_p5_task(tmp_path: Path) -> None:
    history = tmp_path / "class_error.jsonl"
    history.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {"iso_week": "2026-W26", "label": "left_index_finger", "error_rate": 0.10},
                {"iso_week": "2026-W27", "label": "left_index_finger", "error_rate": 0.16},
                {"iso_week": "2026-W28", "label": "left_index_finger", "error_rate": 0.22},
                {"iso_week": "2026-W26", "label": "hair", "error_rate": 0.10},
                {"iso_week": "2026-W27", "label": "hair", "error_rate": 0.18},
                {"iso_week": "2026-W28", "label": "hair", "error_rate": 0.19},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    kwargs = {
        "failure_queue_path": tmp_path / "missing.jsonl",
        "coverage_matrix_path": tmp_path / "missing_coverage.json",
        "output_dir": tmp_path / "reports",
        "approved_gold_count": 225,
        "champion_gold_count": 225,
        "class_error_history_path": history,
        "report_date": "2026-07-12",
        "clusterer": lambda reasons: {reason: "fixture_cluster" for reason in reasons},
    }
    first = run_active_learning(**kwargs)
    second = run_active_learning(**kwargs)
    assert first["class_error_trigger_classes"] == ["left_index_finger"]
    assert first["retrain_triggers"] == {
        "new_gold_plus_50": False,
        "ontology_changed": False,
        "class_error_increase_two_weeks": True,
    }
    assert first["retrain_task"] == second["retrain_task"]
    task = json.loads(Path(first["retrain_task"]).read_text())
    assert task["status"] == "open" and task["approved_gold_count"] == 225


def test_active_learning_writes_weekly_summary_from_local_model_evidence(tmp_path: Path) -> None:
    class TextClient:
        def generate(self, **kwargs) -> str:
            return json.dumps(
                {
                    "clusters": {"finger_merge": "hands_fingers"},
                    "coverage_targets": ["fingers_spread"],
                    "weekly_summary": "Acquire more separated-finger examples.",
                }
            )

    queue = tmp_path / "failure_queue.jsonl"
    queue.write_text(
        json.dumps(
            {
                "ts": "2026-07-10T00:00:00Z",
                "image_id": "img_000000000001",
                "failed_body_part": "left_index_finger",
                "failure_reason": "finger_merge",
                "pose_angle": "arms_down",
                "model_that_failed": "draft_pipeline_full",
                "correction_needed": "separate visible finger gap",
                "priority": 0.9,
                "resolved": False,
                "resolution_pkg_version": None,
            }
        )
        + "\n"
    )
    config = tmp_path / "vlm.yaml"
    config.write_text(
        "runtime:\n  base_url: http://127.0.0.1:11434\nmodels:\n  text_llm: qwen2.5:7b-instruct\n"
    )
    result = run_active_learning(
        failure_queue_path=queue,
        coverage_matrix_path=tmp_path / "missing.json",
        output_dir=tmp_path / "reports",
        approved_gold_count=0,
        report_date="2026-07-12",
        text_client=TextClient(),
        vlm_config_path=config,
    )
    summary = Path(result["weekly_qa_summary"]).read_text()
    assert "Acquire more separated-finger examples." in summary
    assert "`fingers_spread`" in summary
