import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.qa.second_review import (
    PartVerdict,
    SecondReviewError,
    record_second_review,
    sample_approved_packages,
    write_weekly_iaa_report,
)
from maskfactory.training.leaderboard import normalize_leaderboard_row
from test_manifest_schema import valid_manifest


def _package(root: Path, index: int) -> Path:
    package = root / f"pkg{index:02d}"
    package.mkdir(parents=True)
    manifest = valid_manifest()
    manifest["image_id"] = f"img_{index:012x}"
    manifest["qa"]["qa_overall"] = "pass"
    for entry in manifest["parts"].values():
        if entry.get("mask_file"):
            entry["status"] = "human_approved_gold"
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return package


def test_stratified_sampler_is_exact_15_percent_deterministic_and_gold_only(
    tmp_path: Path,
) -> None:
    packages = tmp_path / "packages"
    for index in range(20):
        _package(packages, index)
    rejected = _package(packages, 99)
    document = json.loads((rejected / "manifest.json").read_text(encoding="utf-8"))
    document["qa"]["qa_overall"] = "fail"
    (rejected / "manifest.json").write_text(json.dumps(document), encoding="utf-8")
    first = sample_approved_packages(packages, seed="week-2026-28")
    second = sample_approved_packages(packages, seed="week-2026-28")
    assert first == second
    assert len(first) == 3
    assert all(sample.image_id != "img_000000000063" for sample in first)
    assert all(sample.part and sample.package_root.is_dir() for sample in first)
    result = CliRunner().invoke(
        main,
        ["second-review", "sample", "--packages-root", str(packages), "--seed", "week-2026-28"],
    )
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)) == 3


def test_second_review_requires_fresh_eyes_and_panels_first(tmp_path: Path) -> None:
    package = _package(tmp_path / "packages", 1)
    mask = tmp_path / "mask.png"
    Image.fromarray(np.zeros((4, 4), dtype=np.uint8), mode="L").save(mask)
    common = dict(
        package_root=package,
        verdicts=(PartVerdict("left_forearm", "pass", mask, mask),),
        reviewer="kevin",
        panels_first_at=datetime(2026, 7, 12, 12, tzinfo=UTC),
        full_image_at=datetime(2026, 7, 12, 13, tzinfo=UTC),
        completed_at=datetime(2026, 7, 12, 14, tzinfo=UTC),
        iaa_root=tmp_path / "iaa",
        failure_queue_path=tmp_path / "failure.jsonl",
    )
    with pytest.raises(SecondReviewError, match="different from first"):
        record_second_review(**common)
    common["reviewer"] = "quatavius"
    common["panels_first_at"], common["full_image_at"] = (
        common["full_image_at"],
        common["panels_first_at"],
    )
    with pytest.raises(SecondReviewError, match="panels-first"):
        record_second_review(**common)


def test_fail_demotes_archives_both_masks_and_queues_failure(tmp_path: Path) -> None:
    package = _package(tmp_path / "packages", 2)
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.fromarray(np.zeros((4, 4), dtype=np.uint8), mode="L").save(first)
    Image.fromarray(np.full((4, 4), 255, dtype=np.uint8), mode="L").save(second)
    evidence = record_second_review(
        package,
        (PartVerdict("left_forearm", "fail", first, second, "tighten boundary"),),
        reviewer="quatavius",
        panels_first_at=datetime(2026, 7, 12, 12, tzinfo=UTC),
        full_image_at=datetime(2026, 7, 12, 13, tzinfo=UTC),
        completed_at=datetime(2026, 7, 12, 14, tzinfo=UTC),
        iaa_root=tmp_path / "iaa",
        failure_queue_path=tmp_path / "failure.jsonl",
    )
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["review"]["second_review"]["result"] == "fail"
    assert manifest["qa"] == {
        "qa_report_file": "qa_report.json",
        "qa_overall": "fail",
        "qa_score": 0.0,
    }
    assert {
        entry["status"] for entry in manifest["parts"].values() if entry["status"] != "n/a"
    } == {"rejected_needs_fix"}
    review = json.loads(evidence.read_text(encoding="utf-8"))
    assert review["verdicts"][0]["first_sha256"] != review["verdicts"][0]["second_sha256"]
    queued = json.loads((tmp_path / "failure.jsonl").read_text(encoding="utf-8"))
    assert queued["failure_reason"] == "second_review_fail"
    assert queued["failed_body_part"] == "left_forearm"
    markdown, ceiling = write_weekly_iaa_report(
        tmp_path / "iaa", iso_week="2026-W28", reports_root=tmp_path / "reports"
    )
    report = json.loads((tmp_path / "reports/iaa_2026-W28.json").read_text(encoding="utf-8"))
    assert report["per_class"]["left_forearm"] == {
        "samples": 1,
        "mean_iou": 0.0,
        "mean_boundary_f": 0.0,
        "target_iou": 0.92,
        "passed": False,
    }
    row = json.loads(ceiling.read_text(encoding="utf-8"))
    assert row["model_family"] == "human_ceiling_iaa"
    assert row["per_class"]["left_forearm"]["iou"] == 0.0
    assert normalize_leaderboard_row(row)["run_id"] == "human_ceiling_2026-W28"
    assert "FAIL" in markdown.read_text(encoding="utf-8")
    result = CliRunner().invoke(
        main,
        [
            "second-review",
            "report",
            "--iaa-root",
            str(tmp_path / "iaa"),
            "--iso-week",
            "2026-W28",
            "--reports-root",
            str(tmp_path / "cli-reports"),
        ],
    )
    assert result.exit_code == 0, result.output
