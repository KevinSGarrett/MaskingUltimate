import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
import yaml
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.datasets.active_learning import run_active_learning
from maskfactory.datasets.coverage import (
    build_coverage_matrix,
    coverage_deficit_report,
    write_coverage_matrix,
)
from maskfactory.io.png_strict import write_label_map
from maskfactory.qa.failure_mining import (
    FailureMiningError,
    append_failure,
    append_failure_once,
    append_source_failure,
    harvest_human_edit_deltas,
    make_failure_record,
    priority_score,
    write_acquisition_plan,
    write_manifest_lint_report,
    write_weekly_qa_summary,
)


def test_failure_queue_append_and_exact_priority_formula(tmp_path: Path) -> None:
    config = yaml.safe_load(Path("configs/training/use_weights.yaml").read_text())
    assert config["weights"] == {
        "hands": 1.0,
        "chest": 1.0,
        "feet": 0.8,
        "bands": 0.5,
        "default": 0.3,
    }
    now = datetime(2026, 7, 11, tzinfo=UTC)
    score = priority_score(
        class_error_rate=0.8,
        coverage_deficit=0.6,
        downstream_use_weight=1.0,
        age_days=14,
    )
    assert score == pytest.approx(0.4 * 0.8 + 0.3 * 0.6 + 0.2 * 1.0 + 0.1 * 0.5)
    record = make_failure_record(
        image_id="img_a3f9c2e17b04",
        body_part="left_index_finger",
        reason="finger_merge",
        pose="left_3_4",
        model="sam2_hand_lane",
        correction="manual_crop_repaint",
        class_error_rate=0.8,
        coverage_deficit=0.6,
        use_weight=1.0,
        event_time=now - timedelta(days=14),
        now=now,
    )
    queue = tmp_path / "failure_queue.jsonl"
    append_failure(queue, record)
    append_failure(queue, record)
    lines = queue.read_text().splitlines()
    assert len(lines) == 2
    assert all(json.loads(line)["priority"] == pytest.approx(score) for line in lines)
    assert not (tmp_path / "failure_queue.jsonl.lock").exists()
    once = tmp_path / "failure_once.jsonl"
    assert append_failure_once(once, record) is True
    assert append_failure_once(once, record) is False
    assert len(once.read_text().splitlines()) == 1


def test_failure_reason_sources_and_weekly_top20_acquisition_plan(tmp_path: Path) -> None:
    now = datetime(2026, 7, 11, tzinfo=UTC)
    reasons = (
        "finger_merge",
        "qc_fail",
        "second_review_fail",
        "vlm_autoqa_disagreement",
        "human_edit_delta",
    )
    records = [
        make_failure_record(
            image_id=f"img_{index:012x}",
            body_part="hair",
            reason=reason,
            pose="front",
            model="pipeline",
            correction="manual_repaint",
            class_error_rate=0.9 - index * 0.05,
            coverage_deficit=0.8,
            use_weight=1.0,
            event_time=now,
            now=now,
        )
        for index, reason in enumerate(reasons, 1)
    ]
    path = write_acquisition_plan(
        records,
        output_dir=tmp_path,
        clusterer=lambda values: {value: "edge_or_review" for value in values},
        report_date="2026-07-11",
    )
    text = path.read_text()
    assert text.count("edge_or_review") == 5
    assert "collect cell" in text or "re-annotate" in text
    assert "hard_case_holdout" in text
    queue = tmp_path / "failure_queue.jsonl"
    source_records = [
        append_source_failure(
            queue,
            source=source,
            image_id=f"img_{index + 20:012x}",
            body_part="hair",
            pose="front",
            model="pipeline",
            correction="manual_repaint",
            class_error_rate=0.5,
            coverage_deficit=0.5,
            use_weight=1.0,
            lane_reason="hair_edge",
        )
        for index, source in enumerate(
            ("lane", "qc", "second_review", "vlm_autoqa", "human_edit_delta")
        )
    ]
    assert {record.failure_reason for record in source_records} == {
        "hair_edge",
        "qc_fail",
        "second_review_fail",
        "vlm_autoqa_disagreement",
        "human_edit_delta",
    }


def test_human_edit_delta_harvest_is_hash_verified_measured_and_idempotent(
    tmp_path: Path,
) -> None:
    image_id = "img_a3f9c2e17b04"
    package = tmp_path / "packages" / image_id / "instances" / "p1"
    baseline_root = package / "annotations" / "draft_baseline"
    baseline_root.mkdir(parents=True)
    draft = np.zeros((4, 6), dtype=np.uint16)
    draft[:, :3] = 18
    draft[:, 3:] = 19
    gold = np.zeros_like(draft)
    gold[:, :2] = 18
    gold[:, 2:] = 19
    material = np.ones((4, 6), dtype=np.uint8)
    draft_path = write_label_map(baseline_root / "label_map_part.png", draft, bits=16)
    material_path = write_label_map(baseline_root / "label_map_material.png", material, bits=8)
    gold_path = write_label_map(package / "label_map_part.png", gold, bits=16)

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    (baseline_root / "baseline_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "image_id": image_id,
                "instance_id": "p1",
                "source_stage": "S09_weighted_consensus",
                "sealed_at": "2026-07-11T20:00:00Z",
                "part_map_sha256": digest(draft_path),
                "material_map_sha256": digest(material_path),
            }
        ),
        encoding="utf-8",
    )
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": image_id,
                "person": {
                    "view": "front",
                    "pose_tags": ["arms_down"],
                    "person_count": 2,
                },
                "parts": {
                    "left_forearm": {"status": "human_approved_gold"},
                    "right_forearm": {"status": "human_approved_gold"},
                },
                "review": {"approved_at": "2026-07-11T20:00:00Z"},
                "files": {"label_map_part.png": digest(gold_path)},
            }
        ),
        encoding="utf-8",
    )
    (package / ".maskfactory_frozen.json").write_text("{}", encoding="utf-8")
    coverage = build_coverage_matrix([], generated_at=datetime(2026, 7, 11, tzinfo=UTC))
    queue = tmp_path / "failure_queue.jsonl"
    kwargs = {
        "packages_root": tmp_path / "packages",
        "failure_queue_path": queue,
        "coverage_matrix": coverage,
        "use_weights_path": Path("configs/training/use_weights.yaml"),
        "now": datetime(2026, 7, 11, 20, tzinfo=UTC),
    }

    first = harvest_human_edit_deltas(**kwargs)
    active = run_active_learning(
        failure_queue_path=queue,
        coverage_matrix_path=tmp_path / "coverage.json",
        output_dir=tmp_path / "reports",
        certified_training_package_count=1,
        report_date="2026-07-11",
        packages_root=tmp_path / "packages",
        use_weights_path=Path("configs/training/use_weights.yaml"),
        clusterer=lambda reasons: {reason: "fixture_cluster" for reason in reasons},
    )

    assert first["new_record_count"] == 2
    assert active["human_edit_harvest"]["new_record_count"] == 0
    assert active["human_edit_harvest"]["already_harvested_count"] == 2
    assert active["unresolved_failure_count"] == 2
    rows = [json.loads(line) for line in queue.read_text().splitlines()]
    assert {row["failed_body_part"] for row in rows} == {
        "left_forearm",
        "right_forearm",
    }
    assert all(row["failure_reason"] == "human_edit_delta" for row in rows)
    assert rows[0]["priority"] == pytest.approx(0.4 * (1 / 3) + 0.3 + 0.2 * 0.3 + 0.1)
    assert rows[1]["priority"] == pytest.approx(0.4 * 0.25 + 0.3 + 0.2 * 0.3 + 0.1)
    draft_path.write_bytes(b"tampered")
    with pytest.raises(FailureMiningError, match="missing or corrupt"):
        harvest_human_edit_deltas(**kwargs)


def test_nightly_manifest_lint_report_records_findings_and_parse_failures(tmp_path: Path) -> None:
    good, bad = tmp_path / "good", tmp_path / "bad"
    good.mkdir()
    bad.mkdir()
    (good / "manifest.json").write_text(json.dumps({"image_id": "img_a3f9c2e17b04"}))
    (bad / "manifest.json").write_text("bad json")
    path = write_manifest_lint_report(
        [good, bad],
        output_path=tmp_path / "reports/manifest_lint.json",
        linter=lambda manifest: [{"severity": "WARN", "problem": "notes sparse"}],
    )
    document = json.loads(path.read_text())
    assert len(document["packages"]) == 2
    assert any(item["findings"][0]["severity"] == "BLOCK" for item in document["packages"])
    weekly = write_weekly_qa_summary(
        {"failures": 3},
        output_path=tmp_path / "reports/weekly.md",
        summarizer=lambda stats: f"# Weekly QA\n\nFailures: {stats['failures']}",
    )
    assert weekly.read_text().startswith("# Weekly QA")


def test_coverage_matrix_closed_tagger_writer_and_ranked_deficits(tmp_path: Path) -> None:
    packages = [
        {
            "status": "human_approved_gold",
            "view": "front",
            "pose_tags": ["arms_down", "walking"],
            "instance_context": "solo",
            "attributes": ["hands_visible", "feet_visible"],
        },
        {
            "status": "drafted",
            "view": "front",
            "pose_tags": ["arms_down"],
            "instance_context": "solo",
            "attributes": ["hands_visible"],
        },
        {
            "status": "human_approved_gold",
            "view": "front",
            "pose_tags": ["arms_down"],
            "instance_context": "duo",
            "attributes": [],
        },
        {
            "status": "human_approved_gold",
            "view": "back",
            "pose_tags": ["walking"],
            "instance_context": "small_group",
            "attributes": [],
        },
    ]
    document = build_coverage_matrix(packages, generated_at=datetime(2026, 7, 11, tzinfo=UTC))
    assert len(document["cells"]) == 6 * 7 * 3
    front_down = next(
        cell
        for cell in document["cells"]
        if (cell["view"], cell["pose"], cell["instance_context"]) == ("front", "arms_down", "solo")
    )
    assert front_down["approved_gold_count"] == 1
    assert (
        next(
            cell["approved_gold_count"]
            for cell in document["cells"]
            if (cell["view"], cell["pose"], cell["instance_context"])
            == ("front", "arms_down", "duo")
        )
        == 1
    )
    assert document["attribute_totals"]["hands_visible"] == 1
    path = write_coverage_matrix(tmp_path / "coverage_matrix.json", document)
    assert path.exists()
    report = coverage_deficit_report(document, target_per_cell=5)
    assert report["cells"][0]["normalized_deficit"] == 1.0
    assert report["cells"][-1]["normalized_deficit"] == 0.8
    invocation = CliRunner().invoke(
        main, ["coverage", "report", "--matrix", str(path), "--target-per-cell", "5"]
    )
    assert invocation.exit_code == 0, invocation.output
    assert len(json.loads(invocation.output)["cells"]) == 6 * 7 * 3
    with pytest.raises(ValueError, match="closed"):
        build_coverage_matrix([{**packages[0], "pose_tags": ["invented"]}])
