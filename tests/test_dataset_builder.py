import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.datasets.active_learning import run_active_learning
from maskfactory.datasets.builder import (
    PackageTruth,
    _truth_aware_splits,
    build_dataset,
    mark_dataset_exported,
)
from maskfactory.datasets.cocorle import decode_binary_mask
from maskfactory.datasets.splits import (
    SplitRecord,
    assign_splits,
    hash_split,
    validate_instance_split_integrity,
)
from maskfactory.io.png_strict import write_label_map
from maskfactory.state import initialize_database, reader_connection, writer_connection


def _reference_gate(tmp_path: Path, monkeypatch) -> Path:
    database = tmp_path / "reference.sqlite"
    database.touch()

    def evaluate(_database, records, *, expected_benchmark_count=None):
        materialized = tuple(records)
        return {
            "schema_version": "1.0.0",
            "database": str(database),
            "benchmark_count": expected_benchmark_count,
            "benchmark_fingerprint": "f" * 64,
            "record_count": len(materialized),
            "partition_counts": {},
            "dhash_hamming_threshold": 3,
            "conservative_near_duplicate_rule": "fixture",
            "issues": [],
            "passed": True,
        }

    monkeypatch.setattr(
        "maskfactory.datasets.builder.evaluate_benchmark_training_isolation", evaluate
    )
    return database


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
    reference = _reference_gate(tmp_path, monkeypatch)
    first = build_dataset(
        packages_root=packages,
        output_root=tmp_path / "first",
        version=1,
        reference_database=reference,
        hard_case_file=hard,
    )
    second = build_dataset(
        packages_root=packages,
        output_root=tmp_path / "second",
        version=1,
        reference_database=reference,
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
    assert manifest["source_packages"] == [
        "img_000000000001/instances/p0",
        "img_000000000001/instances/p1",
        "img_000000000002/instances/p0",
    ]
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

    monkeypatch.setattr(
        "maskfactory.datasets.builder.evaluate_benchmark_training_isolation",
        lambda *_args, **_kwargs: {
            "passed": False,
            "issues": ["perceptual_overlap:0:0000000000000000"],
        },
    )
    with pytest.raises(ValueError, match="overlaps.*frozen reference benchmark"):
        build_dataset(
            packages_root=packages,
            output_root=tmp_path / "blocked",
            version=1,
            reference_database=reference,
            hard_case_file=hard,
        )
    assert not (tmp_path / "blocked/bodyparts@v1").exists()


def test_mark_dataset_exported_synchronizes_packages_and_sqlite(
    tmp_path: Path, monkeypatch
) -> None:
    packages = tmp_path / "packages"
    package = packages / "img_export" / "instances" / "p0"
    package.mkdir(parents=True)
    manifest_path = package / "manifest.json"
    manifest_path.write_text(
        json.dumps({"image_id": "img_export", "workflow_status": "approved_gold"}),
        encoding="utf-8",
    )
    (package / ".maskfactory_frozen.json").write_text("{}\n", encoding="utf-8")
    dataset = tmp_path / "bodyparts@v1"
    dataset.mkdir()
    (dataset / "build_manifest.json").write_text(
        json.dumps({"source_packages": ["img_export/instances/p0"]}), encoding="utf-8"
    )
    database = tmp_path / "state.sqlite"
    initialize_database(database)
    with writer_connection(database) as connection:
        connection.execute(
            "INSERT INTO images "
            "(image_id, source_sha256, status, current_stage, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("img_export", "a" * 64, "approved_gold", "S13", "t0", "t0"),
        )

    def update(package_root: Path, target: str, *, updated_at: str) -> bool:
        document = json.loads((package_root / "manifest.json").read_text(encoding="utf-8"))
        document.update({"workflow_status": target, "workflow_updated_at": updated_at})
        (package_root / "manifest.json").write_text(json.dumps(document), encoding="utf-8")
        return True

    monkeypatch.setattr("maskfactory.datasets.builder.update_package_workflow_status", update)
    assert mark_dataset_exported(
        dataset,
        packages_root=packages,
        database=database,
        updated_at="2026-07-12T20:00:00Z",
    ) == ("img_export",)
    assert json.loads(manifest_path.read_text())["workflow_status"] == "exported"
    with reader_connection(database) as connection:
        row = connection.execute(
            "SELECT status, current_stage, updated_at FROM images WHERE image_id = 'img_export'"
        ).fetchone()
    assert tuple(row) == ("exported", "S14", "2026-07-12T20:00:00Z")


def test_mark_dataset_exported_rolls_back_package_when_later_update_fails(
    tmp_path: Path, monkeypatch
) -> None:
    packages = tmp_path / "packages"
    relatives = ["img_export/instances/p0", "img_export/instances/p1"]
    originals = {}
    for relative in relatives:
        package = packages / relative
        package.mkdir(parents=True)
        path = package / "manifest.json"
        path.write_text(
            json.dumps({"image_id": "img_export", "workflow_status": "approved_gold"}),
            encoding="utf-8",
        )
        originals[path] = path.read_bytes()
        (package / ".maskfactory_frozen.json").write_text("{}\n", encoding="utf-8")
    dataset = tmp_path / "bodyparts@v1"
    dataset.mkdir()
    (dataset / "build_manifest.json").write_text(
        json.dumps({"source_packages": relatives}), encoding="utf-8"
    )
    database = tmp_path / "state.sqlite"
    initialize_database(database)
    with writer_connection(database) as connection:
        connection.execute(
            "INSERT INTO images "
            "(image_id, source_sha256, status, current_stage, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("img_export", "a" * 64, "approved_gold", "S13", "t0", "t0"),
        )

    calls = 0

    def update(package_root: Path, target: str, *, updated_at: str) -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("seeded package update failure")
        (package_root / "manifest.json").write_text(
            json.dumps(
                {
                    "image_id": "img_export",
                    "workflow_status": target,
                    "workflow_updated_at": updated_at,
                }
            ),
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr("maskfactory.datasets.builder.update_package_workflow_status", update)
    with pytest.raises(RuntimeError, match="seeded package update failure"):
        mark_dataset_exported(dataset, packages_root=packages, database=database)
    assert all(path.read_bytes() == content for path, content in originals.items())
    with reader_connection(database) as connection:
        status = connection.execute(
            "SELECT status FROM images WHERE image_id = 'img_export'"
        ).fetchone()[0]
    assert status == "approved_gold"


def test_dataset_cli_marks_exported_only_after_successful_dvc_push(
    tmp_path: Path, monkeypatch
) -> None:
    def fake_build_dataset(**kwargs):
        dataset = kwargs["output_root"] / f"bodyparts@v{kwargs['version']}"
        dataset.mkdir(parents=True)
        return dataset

    monkeypatch.setattr(
        "maskfactory.datasets.builder.approved_package_count",
        lambda _root, *, ontology_version=None: 200,
    )
    monkeypatch.setattr("maskfactory.datasets.builder.build_dataset", fake_build_dataset)
    events = []

    def fake_subprocess(args, **_kwargs):
        events.append("git-preflight" if "--list" in args else "git-tag")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("subprocess.run", fake_subprocess)
    marked = []
    monkeypatch.setattr(
        "maskfactory.datasets.builder.mark_dataset_exported",
        lambda path, **kwargs: marked.append((path, kwargs)),
    )
    dvc_results = iter(
        (
            SimpleNamespace(returncode=0, stderr=""),
            SimpleNamespace(returncode=1, stderr="seeded push failure"),
        )
    )

    def failed_dvc(args, **_kwargs):
        events.append("dvc-" + args[0])
        return next(dvc_results)

    monkeypatch.setattr("maskfactory.dvc_runtime.run_dvc", failed_dvc)
    reference = tmp_path / "reference.sqlite"
    reference.touch()
    args = [
        "dataset",
        "build",
        "--packages-root",
        str(tmp_path / "packages"),
        "--output-root",
        str(tmp_path / "datasets"),
        "--database",
        str(tmp_path / "state.sqlite"),
        "--reference-database",
        str(reference),
    ]
    failed = CliRunner().invoke(main, args)
    assert failed.exit_code != 0 and "seeded push failure" in failed.output
    assert marked == []
    assert events == ["git-preflight", "dvc-add", "dvc-push"]

    events.clear()
    monkeypatch.setattr(
        "maskfactory.dvc_runtime.run_dvc",
        lambda args, **_kwargs: (
            events.append("dvc-" + args[0]) or SimpleNamespace(returncode=0, stderr="")
        ),
    )
    passed = CliRunner().invoke(main, args)
    assert passed.exit_code == 0, passed.output
    assert events == ["git-preflight", "dvc-add", "dvc-push", "git-tag"]
    assert marked == [
        (
            tmp_path / "datasets" / "bodyparts@v2",
            {
                "packages_root": tmp_path / "packages",
                "database": tmp_path / "state.sqlite",
            },
        )
    ]


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
    reference = _reference_gate(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="verification failed"):
        build_dataset(
            packages_root=packages,
            output_root=tmp_path / "output",
            version=1,
            reference_database=reference,
        )
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
    output = build_dataset(
        packages_root=packages,
        output_root=tmp_path / "out",
        version=1,
        reference_database=_reference_gate(tmp_path, monkeypatch),
    )
    sample_id = "img_000000000005_p0"
    exported_part = np.asarray(Image.open(output / f"part_seg/annotations/{sample_id}.png"))
    exported_material = np.asarray(Image.open(output / f"material_seg/annotations/{sample_id}.png"))
    ambiguous = part == 19
    assert np.all(exported_part[ambiguous] == 255)
    assert np.all(exported_material[ambiguous] == 255)
    assert np.all(exported_part[part == 18] == 18)
    assert np.all(exported_material[~ambiguous] == 1)


def test_builder_enforces_truth_tier_weights_volume_and_holdout_isolation(
    tmp_path: Path, monkeypatch
) -> None:
    packages = tmp_path / "packages"

    def package(
        image_id: str,
        *,
        tier: str,
        partition: str,
        weight: float,
        part_status: str,
        certification: dict | None = None,
    ) -> None:
        root = packages / image_id / "instances" / "p0"
        root.mkdir(parents=True)
        Image.new("RGB", (6, 6), "gray").save(root / "source.png")
        part = np.zeros((6, 6), dtype=np.uint16)
        part[1:5, 1:5] = 18
        material = np.zeros((6, 6), dtype=np.uint8)
        write_label_map(root / "label_map_part.png", part, bits=16)
        write_label_map(root / "label_map_material.png", material, bits=8)
        (root / ".maskfactory_frozen.json").write_text("{}", encoding="utf-8")
        manifest = {
            "image_id": image_id,
            "truth_tier": tier,
            "truth_partition": partition,
            "training_loss_weight": weight,
            "source": {
                "source_origin": "owned_photo",
                "phash64": hashlib.sha256(image_id.encode()).hexdigest()[:16],
            },
            "parts": {"left_forearm": {"status": part_status}},
        }
        if certification is not None:
            manifest["certification"] = certification
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    package(
        "img_000000000011",
        tier="human_anchor_gold",
        partition="train",
        weight=1.0,
        part_status="human_anchor_gold",
    )
    package(
        "img_000000000012",
        tier="human_anchor_gold",
        partition="calibration",
        weight=0.0,
        part_status="human_anchor_gold",
    )
    package(
        "img_000000000013",
        tier="human_anchor_gold",
        partition="holdout",
        weight=0.0,
        part_status="human_anchor_gold",
    )
    certificate = {
        "certificates": [
            {
                "certificate_id": "cert_fixture",
                "risk_bucket": "ordinary_visible_part",
                "certificate_sha256": "a" * 64,
                "covered_labels": ["left_forearm"],
            }
        ],
        "pipeline_fingerprint": "fixture-pipeline",
        "evidence_sha256": "b" * 64,
        "final_mask_set_sha256": "c" * 64,
    }
    package(
        "img_000000000014",
        tier="autonomous_certified_gold",
        partition="train",
        weight=0.65,
        part_status="autonomous_certified_gold",
        certification=certificate,
    )
    package(
        "img_000000000015",
        tier="weighted_pseudo_label",
        partition="train",
        weight=0.20,
        part_status="weighted_pseudo_label",
    )
    package(
        "img_000000000016",
        tier="machine_candidate",
        partition="residual",
        weight=0.0,
        part_status="machine_candidate",
    )
    hard = tmp_path / "hard.txt"
    hard.write_text("img_000000000014\n", encoding="utf-8")
    monkeypatch.setattr(
        "maskfactory.datasets.builder.verify_packages",
        lambda _package: (SimpleNamespace(passed=True),),
    )
    reference = _reference_gate(tmp_path, monkeypatch)

    output = build_dataset(
        packages_root=packages,
        output_root=tmp_path / "out",
        version=1,
        reference_database=reference,
        hard_case_file=hard,
    )
    build = json.loads((output / "build_manifest.json").read_text(encoding="utf-8"))
    assert build["schema_version"] == "2.0.0"
    assert build["splits"]["img_000000000014"] == "train"
    assert build["splits"]["img_000000000012"] == "calibration"
    assert build["splits"]["img_000000000013"] == "test_holdout"
    assert "img_000000000016" not in build["splits"]
    assert build["truth_metrics"] == {
        "human_anchor_train_count": 1,
        "human_anchor_calibration_count": 1,
        "human_anchor_holdout_count": 1,
        "autonomous_certified_gold_count": 1,
        "weighted_pseudo_label_count": 1,
        "machine_candidate_count": 1,
        "certified_training_package_count": 2,
        "effective_training_weight_units": 1.85,
    }
    weights = json.loads((output / "sample_weights.json").read_text(encoding="utf-8"))["samples"]
    assert weights["img_000000000011_p0"]["training_loss_weight"] == 1.0
    assert weights["img_000000000014_p0"]["training_loss_weight"] == 0.65
    assert weights["img_000000000015_p0"]["training_loss_weight"] == 0.20
    assert weights["img_000000000012_p0"]["training_loss_weight"] == 0.0
    assert weights["img_000000000013_p0"]["training_loss_weight"] == 0.0
    assert weights["img_000000000015_p0"]["dataset_volume_eligible"] is False
    calibration_id = "img_000000000012_p0"
    assert calibration_id not in (output / "train.txt").read_text(encoding="utf-8")
    assert calibration_id not in (output / "val.txt").read_text(encoding="utf-8")
    assert (output / f"calibration/{calibration_id}/source.png").is_file()
    assert not (output / f"part_seg/images/{calibration_id}.png").exists()
    assert build["calibration_trainer_read_path"] is None
    assert "calibration" not in build["trainer_inputs"]
    assert set((output / "protected_anchor_ids.txt").read_text().splitlines()) == {
        "img_000000000012",
        "img_000000000013",
    }


def test_explicit_anchor_partitions_cannot_split_a_phash_duplicate_group(tmp_path: Path) -> None:
    train = tmp_path / "train"
    holdout = tmp_path / "holdout"
    by_image = {
        "img_000000000021": [(train, {"source": {"phash64": "0000000000000000"}})],
        "img_000000000022": [(holdout, {"source": {"phash64": "0000000000000001"}})],
    }
    truth = {
        train: PackageTruth("human_anchor_gold", "train", 1.0),
        holdout: PackageTruth("human_anchor_gold", "holdout", 0.0),
    }
    with pytest.raises(ValueError, match="pHash duplicate group"):
        _truth_aware_splits(
            {
                "img_000000000021": "train",
                "img_000000000022": "test_holdout",
            },
            by_image,
            truth,
            hard_case_ids=frozenset(),
        )


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
        certified_training_package_count=60,
        champion_certified_package_count=5,
        report_date="2026-07-12",
        clusterer=lambda reasons: {
            reason: "hands_fingers" if reason == "finger_merge" else "fixture_cluster"
            for reason in reasons
        },
    )
    assert result["unresolved_failure_count"] == 1
    assert result["retrain_requested"] is True
    assert result["retrain_triggers"]["new_certified_plus_50"] is True
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
        "certified_training_package_count": 225,
        "champion_certified_package_count": 225,
        "class_error_history_path": history,
        "report_date": "2026-07-12",
        "clusterer": lambda reasons: {reason: "fixture_cluster" for reason in reasons},
    }
    first = run_active_learning(**kwargs)
    second = run_active_learning(**kwargs)
    assert first["class_error_trigger_classes"] == ["left_index_finger"]
    assert first["retrain_triggers"] == {
        "new_certified_plus_50": False,
        "ontology_changed": False,
        "class_error_increase_two_weeks": True,
    }
    assert first["retrain_task"] == second["retrain_task"]
    task = json.loads(Path(first["retrain_task"]).read_text())
    assert task["status"] == "open"
    assert task["certified_training_package_count"] == 225


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
        certified_training_package_count=0,
        report_date="2026-07-12",
        text_client=TextClient(),
        vlm_config_path=config,
    )
    summary = Path(result["weekly_qa_summary"]).read_text()
    assert "Acquire more separated-finger examples." in summary
    assert "`fingers_spread`" in summary
