from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

from maskfactory.nude_corpus_intake import canonical_sha256


def _module():
    path = Path(__file__).resolve().parents[1] / "tools/compare_person_proposal_batches.py"
    spec = importlib.util.spec_from_file_location("compare_person_proposal_batches_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path):
    image = tmp_path / "source.png"
    Image.new("RGB", (100, 80), "white").save(image)
    sample = {
        "sample_id": "sample-1",
        "source_sha256": _sha(image),
        "source_path_readonly": str(image),
        "source_role": "reference_and_tournament_input",
        "source_split": "unsplit_reference",
        "source_labels": [],
        "annotation_ref": None,
    }
    shard_body = {
        "schema_version": "maskfactory.nude_batch_shard.v1",
        "artifact_type": "tournament_sample_set",
        "batch_lane": "reference_and_tournament_input",
        "batch_number": 1,
        "platform": "runpod",
        "sample_count": 1,
        "ordered_sample_ids": ["sample-1"],
        "samples": [sample],
    }
    shard = tmp_path / "shard.json"
    shard.write_text(json.dumps({**shard_body, "self_sha256": canonical_sha256(shard_body)}))
    yolo_proposal = {
        "bbox_xyxy": [5, 5, 95, 78],
        "confidence": 0.9,
        "label": "person",
        "authority": "proposal_only",
    }
    gdino_proposal = {
        "bbox_xyxy": [5, 5, 95, 78],
        "box_score": 0.9,
        "text_score": 0.9,
        "phrase": "person",
        "prompt": "person",
        "authority": "proposal_only",
    }
    gdino_body = {
        "schema_version": "maskfactory.groundingdino_batch.v1",
        "authority": "proposal_boxes_only",
        "may_write_final_masks": False,
        "source_revision": "rev-g",
        "checkpoint_sha256": "a" * 64,
        "box_threshold": 0.3,
        "record_count": 1,
        "records": [{**sample, "image_size": [100, 80], "proposals": [gdino_proposal]}],
    }
    yolo_body = {
        "schema_version": "maskfactory.yolo11_person_batch.v1",
        "authority": "proposal_boxes_only",
        "may_write_final_masks": False,
        "provider": "yolo11m_person",
        "provider_family": "yolo",
        "checkpoint_sha256": "b" * 64,
        "confidence_min": 0.5,
        "record_count": 1,
        "records": [{**sample, "proposals": [yolo_proposal]}],
    }
    paths = []
    for name, body in (("gdino.json", gdino_body), ("yolo.json", yolo_body)):
        path = tmp_path / name
        path.write_text(json.dumps({**body, "output_sha256": canonical_sha256(body)}))
        paths.append(path)
    return shard, paths


def test_complete_outputs_compare_as_non_authoritative_catalog(tmp_path: Path) -> None:
    runner = _module()
    shard, (gdino, yolo) = _fixture(tmp_path)
    report = runner.compare_batches(
        shard_path=shard,
        groundingdino_path=gdino,
        yolo_path=yolo,
        platform="runpod",
    )
    assert report["status_counts"] == {"pass": 1}
    assert report["record_count"] == 1
    assert report["production_mask_authority"] is False
    assert len(report["self_sha256"]) == 64


def test_comparison_may_raise_but_never_lower_provider_execution_threshold(
    tmp_path: Path,
) -> None:
    runner = _module()
    shard, (gdino, yolo) = _fixture(tmp_path)
    report = runner.compare_batches(
        shard_path=shard,
        groundingdino_path=gdino,
        yolo_path=yolo,
        platform="runpod",
        groundingdino_confidence_min=0.95,
    )
    assert report["status_counts"] == {"abstain": 1}
    assert report["reason_counts"] == {"no_person_consensus": 1}
    with pytest.raises(ValueError, match="cannot be below"):
        runner.compare_batches(
            shard_path=shard,
            groundingdino_path=gdino,
            yolo_path=yolo,
            platform="runpod",
            groundingdino_confidence_min=0.2,
        )


def test_provider_output_seal_or_order_drift_fails_closed(tmp_path: Path) -> None:
    runner = _module()
    shard, (gdino, yolo) = _fixture(tmp_path)
    document = json.loads(gdino.read_text())
    document["records"][0]["sample_id"] = "wrong"
    gdino.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="seal mismatch"):
        runner.compare_batches(
            shard_path=shard,
            groundingdino_path=gdino,
            yolo_path=yolo,
            platform="runpod",
        )
