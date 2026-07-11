import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.io.png_strict import write_label_map
from maskfactory.validation import validate_document
from maskfactory.vlm.production import run_s11_production


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "source.png"
    Image.new("RGB", (40, 30), "gray").save(source)
    part = np.full((30, 40), 18, dtype=np.uint16)
    part_path = write_label_map(tmp_path / "part.png", part, bits=16)
    report = {
        "image_id": "img_a3f9c2e17b04",
        "run_id": "qa_20260711_2200_fixture",
        "pipeline_version": "maskfactory 0.0.1",
        "created_at": "2026-07-11T22:00:00Z",
        "checks": [],
        "metrics_per_part": {},
        "consensus": {"method": "weighted_vote_v1", "sources": ["sam2"]},
        "vlm_review": {"model": "pending_s11", "verdicts": []},
        "overall": "pass",
        "score": 1.0,
    }
    report_path = tmp_path / "qa_report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return source, part_path, report_path


def test_s11_missing_gate_generates_panels_and_routes_careful_without_model_call(
    tmp_path: Path,
) -> None:
    source, part, report = _inputs(tmp_path)
    status = run_s11_production(
        source_crop_path=source,
        part_map_path=part,
        s10_report_path=report,
        output_dir=tmp_path / "output",
        gate_path=tmp_path / "missing_gate.json",
    )
    assert status["enabled"] is False
    assert status["routes"]["left_forearm"]["queue"] == "careful"
    with Image.open(tmp_path / "output/qa_panels/left_forearm.png") as panel:
        assert panel.size == (2560, 512) and panel.mode == "RGB"
    final = json.loads((tmp_path / "output/qa_report.json").read_text())
    assert final["overall"] == "needs_human" and final["vlm_review"]["verdicts"] == []
    assert validate_document(final, "qa_report") == ()


def test_s11_current_gate_runs_local_verdict_and_quick_pass_route(tmp_path: Path) -> None:
    source, part, report = _inputs(tmp_path)

    class Client:
        def generate(self, **kwargs):
            if "VISIBLE LABEL DIGEST" in kwargs["prompt"]:
                return json.dumps(
                    {
                        "missing": [],
                        "mislabeled": [],
                        "lr_suspect": [],
                        "impossible_claims": [],
                        "notes": "No whole-image issue.",
                    }
                )
            return json.dumps(
                {
                    "verdict": "pass",
                    "confidence": 0.95,
                    "problems": [],
                    "evidence": "Boundary follows the visible forearm.",
                    "correction_instruction": "",
                }
            )

    status = run_s11_production(
        source_crop_path=source,
        part_map_path=part,
        s10_report_path=report,
        output_dir=tmp_path / "output",
        gate_path=tmp_path / "gate.json",
        client=Client(),
        gate_checker=lambda *args, **kwargs: {"fingerprint": "verified-fixture"},
    )
    assert status["enabled"] is True
    assert status["routes"]["left_forearm"]["queue"] == "quick_pass"
    assert status["whole_image_review"]["status"] == "complete"
    final = json.loads((tmp_path / "output/qa_report.json").read_text())
    assert final["overall"] == "pass"
    assert final["vlm_review"]["verdicts"][0]["verdict"] == "pass"


def test_s11_autoqa_vlm_disagreement_appends_measured_failure_once(tmp_path: Path) -> None:
    source, part, report = _inputs(tmp_path)

    class Client:
        def generate(self, **kwargs):
            if "VISIBLE LABEL DIGEST" in kwargs["prompt"]:
                return json.dumps(
                    {
                        "missing": [],
                        "mislabeled": [],
                        "lr_suspect": [],
                        "impossible_claims": [],
                        "notes": "Review complete.",
                    }
                )
            return json.dumps(
                {
                    "verdict": "fail",
                    "confidence": 0.9,
                    "problems": ["boundary_too_loose"],
                    "evidence": "Mask extends beyond the visible forearm.",
                    "correction_instruction": "Tighten the outside edge.",
                }
            )

    queue = tmp_path / "failure_queue.jsonl"
    kwargs = {
        "source_crop_path": source,
        "part_map_path": part,
        "s10_report_path": report,
        "output_dir": tmp_path / "output",
        "gate_path": tmp_path / "gate.json",
        "client": Client(),
        "gate_checker": lambda *args, **kwargs: {"fingerprint": "verified-fixture"},
        "failure_queue_path": queue,
        "pose_angle": "front",
    }
    status = run_s11_production(**kwargs)
    run_s11_production(**{**kwargs, "output_dir": tmp_path / "output_rerun"})

    assert status["routes"]["left_forearm"]["queue"] == "careful"
    rows = [json.loads(line) for line in queue.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["failed_body_part"] == "left_forearm"
    assert rows[0]["failure_reason"] == "vlm_autoqa_disagreement"
    assert rows[0]["priority"] == pytest.approx(0.4 * 0.9 + 0.3 + 0.2 * 0.3 + 0.1)
