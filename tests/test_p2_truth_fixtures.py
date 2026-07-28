from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.qa.p2_truth_fixtures import (
    P2FixtureError,
    assert_acceptance,
    bbox_iou,
    binary_mask_iou,
    load_and_validate_fixture_manifest,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_iou_helpers_use_half_open_boxes_and_binary_nonzero(tmp_path: Path) -> None:
    assert bbox_iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)
    first = np.zeros((4, 4), dtype=np.uint8)
    second = first.copy()
    first[1:3, 1:3] = 255
    second[1:3, 2:4] = 7
    Image.fromarray(first).save(tmp_path / "first.png")
    Image.fromarray(second).save(tmp_path / "second.png")
    assert binary_mask_iou(tmp_path / "first.png", tmp_path / "second.png") == pytest.approx(1 / 3)


def test_manifest_is_exactly_ten_hash_bound_reviewed_records(tmp_path: Path) -> None:
    source = tmp_path / "images/source.jpg"
    mask = tmp_path / "annotations/mask.png"
    source.parent.mkdir()
    mask.parent.mkdir()
    Image.new("RGB", (4, 4)).save(source)
    Image.new("L", (4, 4), 255).save(mask)
    record = {
        "source_relpath": "images/source.jpg",
        "source_sha256": _sha(source),
        "truth_mask_relpath": "annotations/mask.png",
        "truth_mask_sha256": _sha(mask),
        "truth_bbox_xyxy": [0, 0, 4, 4],
        "visual_alignment_review": "pass",
    }
    records = [{"id": str(index), **record} for index in range(10)]
    document = {
        "schema_version": "1.0.0",
        "dataset_key": "lv_mhp_v1",
        "use_scope": "local_non_distributable_research_qc_fixture",
        "external_masks_are_gold": False,
        "records": records,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert len(load_and_validate_fixture_manifest(path, tmp_path)["records"]) == 10
    document["records"][0]["visual_alignment_review"] = "fail"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(P2FixtureError, match="visual alignment"):
        load_and_validate_fixture_manifest(path, tmp_path)


def test_acceptance_fails_closed_on_either_metric() -> None:
    results = [{"id": str(index), "bbox_iou": 0.95, "silhouette_iou": 0.95} for index in range(10)]
    assert_acceptance(results)
    results[-1]["silhouette_iou"] = 0.9499
    with pytest.raises(P2FixtureError, match="9"):
        assert_acceptance(results)
