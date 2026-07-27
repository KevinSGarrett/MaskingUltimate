"""Focused closure tests for the canonical durable run ledger."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from maskfactory.runlog import PipelineRunLog


def test_runlog_matches_full_product_and_records_complete_atomic_telemetry(tmp_path: Path) -> None:
    full_ref = "7d66ca27781d899a43eb644c0378bcf1478045a7"
    source = Path("src/maskfactory/runlog.py")
    assert (
        subprocess.check_output(
            ["git", "rev-parse", f"{full_ref}:src/maskfactory/runlog.py"], text=True
        ).strip()
        == subprocess.check_output(["git", "hash-object", str(source)], text=True).strip()
    )
    logs_root = tmp_path / "logs"
    runs_root = tmp_path / "runs"
    with PipelineRunLog(
        image_ids=["image-b", "image-a"],
        config={"mode": "governed", "workers": 1},
        logs_root=logs_root,
        runs_root=runs_root,
        run_id="run_closure",
    ) as ledger:
        ledger.record_stage(
            image_id="image-a",
            stage="S10",
            status="passed",
            config_hash="a" * 64,
            model_keys=["critic-b", "critic-a", "critic-a"],
            duration_sec=1.25,
            vram_peak_mb=42.1259,
        )
        ledger.record_stage(
            image_id="image-b",
            stage="S11",
            status="abstained",
            config_hash="b" * 64,
            model_keys=["critic-c"],
            duration_sec=0.5,
            vram_peak_mb=16.0,
        )

    document = json.loads((runs_root / "run_closure" / "run.json").read_text(encoding="utf-8"))
    assert document["status"] == "complete"
    assert document["error"] is None
    assert document["model_keys"] == ["critic-a", "critic-b", "critic-c"]
    assert document["duration_sec"] == 1.75
    assert document["vram_peak_mb"] == 42.126
    assert [entry["stage"] for entry in document["stages"]] == ["S10", "S11"]
    log_files = list(logs_root.glob("maskfactory_*.log"))
    assert len(log_files) == 1
    assert "run finished status=complete" in log_files[0].read_text(encoding="utf-8")


def test_runlog_persists_failure_before_terminalization(tmp_path: Path) -> None:
    logs_root = tmp_path / "logs"
    runs_root = tmp_path / "runs"
    ledger = PipelineRunLog(
        image_ids=["image-a"],
        config={"mode": "governed"},
        logs_root=logs_root,
        runs_root=runs_root,
        run_id="run_failure",
    )
    ledger.record_failure(
        image_id="image-a",
        stage="S11",
        category="provider_disagreement",
        attempts=1,
        error="independent critic disagreement",
    )
    persisted = json.loads((runs_root / "run_failure" / "run.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "running"
    assert persisted["stages"] == [
        {
            "attempts": 1,
            "category": "provider_disagreement",
            "error": "independent critic disagreement",
            "image_id": "image-a",
            "stage": "S11",
            "status": "failed",
        }
    ]
    ledger.finish(status="failed", error="terminal abstention")
    terminal = json.loads((runs_root / "run_failure" / "run.json").read_text(encoding="utf-8"))
    assert terminal["status"] == "failed"
    assert terminal["error"] == "terminal abstention"
    assert terminal["ended_at"] is not None
