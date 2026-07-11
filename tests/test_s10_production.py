import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.io.png_strict import write_grayscale, write_label_map
from maskfactory.qa.multi_instance import MultiInstanceQcInputs
from maskfactory.qa.production import run_s10_production
from maskfactory.validation import validate_document


def test_s10_production_writes_schema_valid_report_and_preserves_blocks(tmp_path: Path) -> None:
    shape = (30, 40)
    part = np.zeros(shape, dtype=np.uint16)
    part[:, :20] = 18
    part[:, 20:] = 19
    material = np.ones(shape, dtype=np.uint8)
    write_label_map(tmp_path / "part.png", part, bits=16)
    write_label_map(tmp_path / "material.png", material, bits=8)
    write_grayscale(tmp_path / "disagreement.png", np.zeros(shape, np.uint8), source_size=(40, 30))
    full = np.zeros((50, 60), dtype=np.uint8)
    full[10:40, 10:50] = 255
    Image.fromarray(full, mode="L").save(tmp_path / "silhouette.png")
    Image.new("RGB", (40, 30), "gray").save(tmp_path / "source.png")
    iuv = np.zeros((*shape, 3), dtype=np.uint8)
    iuv[:, :20, 0] = 4
    iuv[:, 20:, 0] = 3
    Image.fromarray(iuv, mode="RGB").save(tmp_path / "densepose.png")
    pose = {
        "view": "front",
        "pose_degraded": False,
        "keypoints": [
            {
                "index": index,
                "x": 20 if index in (5, 11) else 40,
                "y": 20 if index in (5, 6) else 35,
                "confidence": 0.9,
            }
            for index in range(133)
        ],
    }
    (tmp_path / "pose.json").write_text(json.dumps(pose), encoding="utf-8")
    (tmp_path / "parsing.json").write_text(
        json.dumps({"parsing_degraded": False}), encoding="utf-8"
    )
    (tmp_path / "sam2.json").write_text(
        json.dumps(
            {
                "parts": {
                    "left_forearm": {"predicted_iou": 0.9},
                    "right_forearm": {"predicted_iou": 0.9},
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "image_manifest.json").write_text(
        json.dumps({"promoted_instances": ["p0"]}), encoding="utf-8"
    )
    report = run_s10_production(
        image_id="img_a3f9c2e17b04",
        part_map_path=tmp_path / "part.png",
        material_map_path=tmp_path / "material.png",
        disagreement_path=tmp_path / "disagreement.png",
        silhouette_path=tmp_path / "silhouette.png",
        pose_path=tmp_path / "pose.json",
        parsing_metrics_path=tmp_path / "parsing.json",
        sam2_metrics_path=tmp_path / "sam2.json",
        densepose_path=tmp_path / "densepose.png",
        image_manifest_path=tmp_path / "image_manifest.json",
        context_bbox_xyxy=(10, 10, 50, 40),
        person_bbox_xyxy=(10, 10, 50, 40),
        source_crop_path=tmp_path / "source.png",
        output_dir=tmp_path / "output",
        failure_queue_path=tmp_path / "failure_queue.jsonl",
    )
    assert validate_document(report, "qa_report") == ()
    assert report["overall"] == "fail"  # QC-014 has only one independent side vote.
    checks = {item["id"]: item for item in report["checks"]}
    assert checks["QC-014"]["result"] == "fail" and checks["QC-014"]["severity"] == "BLOCK"
    assert checks["QC-035"]["result"] == "pass"
    assert checks["QC-005"]["result"] == "skipped"
    assert (tmp_path / "output/qa_report.json").is_file()
    failures = [
        json.loads(line) for line in (tmp_path / "failure_queue.jsonl").read_text().splitlines()
    ]
    assert {row["failed_body_part"] for row in failures} == {
        check_id.lower().replace("-", "_")
        for check_id, check in checks.items()
        if check["result"] == "fail"
    }
    assert all(row["failure_reason"] == "qc_fail" for row in failures)

    p0 = np.zeros((30, 80), dtype=bool)
    p1 = np.zeros_like(p0)
    p0[:, :30] = True
    p1[:, 50:] = True
    (tmp_path / "image_manifest.json").write_text(
        json.dumps({"promoted_instances": ["p0", "p1"]}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="require full-canvas evidence"):
        run_s10_production(
            image_id="img_a3f9c2e17b04",
            part_map_path=tmp_path / "part.png",
            material_map_path=tmp_path / "material.png",
            disagreement_path=tmp_path / "disagreement.png",
            silhouette_path=tmp_path / "silhouette.png",
            pose_path=tmp_path / "pose.json",
            parsing_metrics_path=tmp_path / "parsing.json",
            sam2_metrics_path=tmp_path / "sam2.json",
            densepose_path=tmp_path / "densepose.png",
            image_manifest_path=tmp_path / "image_manifest.json",
            context_bbox_xyxy=(10, 10, 50, 40),
            person_bbox_xyxy=(10, 10, 50, 40),
            source_crop_path=tmp_path / "source.png",
            output_dir=tmp_path / "refused_output",
        )
    multi_report = run_s10_production(
        image_id="img_a3f9c2e17b04",
        part_map_path=tmp_path / "part.png",
        material_map_path=tmp_path / "material.png",
        disagreement_path=tmp_path / "disagreement.png",
        silhouette_path=tmp_path / "silhouette.png",
        pose_path=tmp_path / "pose.json",
        parsing_metrics_path=tmp_path / "parsing.json",
        sam2_metrics_path=tmp_path / "sam2.json",
        densepose_path=tmp_path / "densepose.png",
        image_manifest_path=tmp_path / "image_manifest.json",
        context_bbox_xyxy=(10, 10, 50, 40),
        person_bbox_xyxy=(10, 10, 50, 40),
        source_crop_path=tmp_path / "source.png",
        output_dir=tmp_path / "multi_output",
        multi_instance_inputs=MultiInstanceQcInputs(
            silhouettes={"p0": p0, "p1": p1},
            atomic_unions={"p0": p0 | p1, "p1": p1},
            expected_promoted_count=2,
        ),
    )
    multi_checks = {item["id"]: item for item in multi_report["checks"]}
    assert multi_checks["QC-036"]["result"] == "fail"
    assert "p0->p1" in multi_checks["QC-036"]["message"]
