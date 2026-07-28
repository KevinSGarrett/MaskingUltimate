import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.io.png_strict import read_mask
from maskfactory.lanes.common import (
    LaneCropError,
    create_lane_crop,
    crop_roundtrip_iou,
    read_crop_transform,
    reproject_crop_mask,
)


def test_lane_crop_exact_resampling_transform_and_roundtrip(tmp_path: Path) -> None:
    source_array = np.zeros((300, 400, 3), dtype=np.uint8)
    source_array[:, :, 0] = np.arange(400, dtype=np.uint16) % 256
    source = tmp_path / "source.png"
    Image.fromarray(source_array).save(source)
    mask = np.zeros((300, 400), dtype=bool)
    mask[100:180, 150:210] = True

    lane = create_lane_crop(
        source,
        mask,
        part="left_hand",
        part_bbox_xyxy=(150, 100, 210, 180),
        output_dir=tmp_path / "crops",
    )

    assert Image.open(lane.image_path).size == (1024, 1024)
    assert Image.open(lane.image_path).mode == "RGB"
    assert read_mask(lane.mask_path).shape == (1024, 1024)
    assert set(np.unique(read_mask(lane.mask_path))) == {0, 255}
    assert lane.transform.full_side == 128  # ceil(max(60,80)*1.6)
    assert lane.transform.scale == 8.0
    assert read_crop_transform(lane.transform_path) == lane.transform
    document = json.loads(lane.transform_path.read_text())
    assert set(document) == {"part", "x0", "y0", "scale", "crop_size", "source_sha256"}
    assert crop_roundtrip_iou(mask, lane) >= 0.995
    reprojected = reproject_crop_mask(lane.mask_path, lane.transform, full_size=(400, 300))
    assert reprojected.dtype == bool and reprojected.shape == mask.shape


def test_lane_crop_shifts_square_at_frame_edge_without_clipping(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (200, 200), "white").save(source)
    mask = np.zeros((200, 200), dtype=bool)
    mask[5:55, 0:40] = True
    lane = create_lane_crop(
        source,
        mask,
        part="right_foot",
        part_bbox_xyxy=(0, 5, 40, 55),
        output_dir=tmp_path / "crops",
    )
    assert lane.transform.x0 == 0
    assert lane.transform.full_side == 80
    assert crop_roundtrip_iou(mask, lane) >= 0.995


def test_lane_crop_rejects_contract_drift_and_unfit_square(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (100, 200), "white").save(source)
    mask = np.zeros((200, 100), dtype=bool)
    with pytest.raises(LaneCropError, match="requires"):
        create_lane_crop(
            source,
            mask,
            part="hair",
            part_bbox_xyxy=(10, 10, 30, 30),
            output_dir=tmp_path,
            crop_size=512,
        )
    with pytest.raises(LaneCropError, match="cannot fit"):
        create_lane_crop(
            source,
            mask,
            part="hair",
            part_bbox_xyxy=(0, 10, 90, 50),
            output_dir=tmp_path,
        )
