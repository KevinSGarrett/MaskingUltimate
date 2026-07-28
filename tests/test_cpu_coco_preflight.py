from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image

from maskfactory.qa.coco_preflight import (
    CocoPreflightError,
    build_cpu_safe_coco_preflight,
    canonical_sha256,
    rasterize_authoritative_polygons,
)


def _dataset(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    image_root = tmp_path / "images"
    image_root.mkdir()
    Image.new("RGB", (10, 8), (40, 80, 120)).save(image_root / "z.jpg")
    Image.new("RGB", (10, 8), (120, 80, 40)).save(image_root / "a.jpg")
    coco: dict[str, object] = {
        "images": [
            {"id": 11, "file_name": "z.jpg", "width": 10, "height": 8},
            {"id": 3, "file_name": "a.jpg", "width": 10, "height": 8},
        ],
        "categories": [{"id": 4, "name": "subject"}],
        "annotations": [
            {
                "id": 101,
                "image_id": 11,
                "category_id": 4,
                "bbox": [2, 1, 4, 3],
                "segmentation": [[2, 1, 6, 1, 6, 4, 2, 4]],
            },
            {
                "id": 100,
                "image_id": 3,
                "category_id": 4,
                "bbox": [1, 1, 4, 4],
                "segmentation": [[1, 1, 5, 1, 5, 5, 1, 5]],
            },
        ],
    }
    return image_root, coco


def test_preflight_is_sorted_compact_and_non_authoritative(tmp_path: Path) -> None:
    image_root, coco = _dataset(tmp_path)

    manifest = build_cpu_safe_coco_preflight(coco, image_root, max_images=2)

    assert manifest["authority_claimed"] is False
    assert manifest["annotation_document_canonical_sha256"] == canonical_sha256(coco)
    assert [entry["file_name"] for entry in manifest["selected_images"]] == ["a.jpg", "z.jpg"]
    assert all(
        "segmentation" not in annotation
        for entry in manifest["selected_images"]
        for annotation in entry["annotations"]
    )


def test_preflight_rejects_out_of_bounds_bbox(tmp_path: Path) -> None:
    image_root, coco = _dataset(tmp_path)
    invalid = deepcopy(coco)
    invalid["annotations"][0]["bbox"] = [2, 1, 20, 3]

    with pytest.raises(CocoPreflightError, match="bbox lies outside image bounds"):
        build_cpu_safe_coco_preflight(invalid, image_root, max_images=2)


def test_rasterization_uses_original_hash_bound_polygons_not_compact_manifest(
    tmp_path: Path,
) -> None:
    image_root, coco = _dataset(tmp_path)
    manifest = build_cpu_safe_coco_preflight(coco, image_root, max_images=2)

    result = rasterize_authoritative_polygons(coco, manifest, image_root, tmp_path / "masks")

    assert result["authority_claimed"] is False
    assert result["mask_count"] == 2
    assert result["summary"]["empty_mask_count"] == 0
    assert result["summary"]["full_mask_count"] == 0
    assert all(0 < entry["coverage_fraction"] < 1 for entry in result["masks"])
    for entry in result["masks"]:
        with Image.open(tmp_path / "masks" / entry["mask_path"]) as mask:
            assert mask.mode == "L"
            assert mask.size == (10, 8)
            assert mask.getextrema() == (0, 255)


def test_rasterization_refuses_annotation_document_hash_drift(tmp_path: Path) -> None:
    image_root, coco = _dataset(tmp_path)
    manifest = build_cpu_safe_coco_preflight(coco, image_root, max_images=2)
    drifted = deepcopy(coco)
    drifted["info"] = {"drift": "detected"}

    with pytest.raises(CocoPreflightError, match="document hash drifted"):
        rasterize_authoritative_polygons(drifted, manifest, image_root, tmp_path / "masks")


def test_preflight_refuses_path_escape(tmp_path: Path) -> None:
    image_root, coco = _dataset(tmp_path)
    invalid = deepcopy(coco)
    invalid["images"][0]["file_name"] = "../outside.jpg"

    with pytest.raises(CocoPreflightError, match="unsafe COCO file_name"):
        build_cpu_safe_coco_preflight(invalid, image_root, max_images=2)


def test_preflight_refuses_duplicate_file_names(tmp_path: Path) -> None:
    image_root, coco = _dataset(tmp_path)
    invalid = deepcopy(coco)
    invalid["images"][1]["file_name"] = "z.jpg"

    with pytest.raises(CocoPreflightError, match="duplicate image file_name"):
        build_cpu_safe_coco_preflight(invalid, image_root, max_images=2)
