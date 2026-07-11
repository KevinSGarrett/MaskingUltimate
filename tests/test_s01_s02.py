import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.io.png_strict import read_mask
from maskfactory.stages.s01_person_detection import (
    Detection,
    PersonDetectionError,
    infer_yolo11_people,
    process_detections,
    run_s01,
)
from maskfactory.stages.s02_silhouette import (
    SilhouetteError,
    build_silhouette,
    infer_birefnet_confidence,
)


def _image() -> Image.Image:
    return Image.new("RGB", (100, 100), "white")


def test_s01_promotes_four_and_protects_remaining_person(tmp_path: Path) -> None:
    detections = [
        Detection((10, 10, 50, 50), 0.9),
        Detection((50, 10, 90, 50), 0.9),
        Detection((10, 50, 50, 90), 0.9),
        Detection((50, 50, 90, 90), 0.9),
        Detection((38, 38, 62, 62), 0.9),
        Detection((0, 0, 10, 10), 0.4),
    ]

    result = process_detections(_image(), detections, tmp_path)

    assert result.outcome == "promoted"
    assert sum(person.promoted for person in result.persons) == 4
    assert sum(person.protected_as_part_50 for person in result.persons) == 1
    assert result.persons[0].detection_index == 0  # equal scores break by left x/index
    assert [p.person_index for p in result.persons[:4]] == [0, 1, 2, 3]
    assert result.persons[4].detection_index == 4  # centered but smaller area ranks fifth
    assert result.persons[4].person_index is None
    assert all((tmp_path / f"p{i}" / "person_ctx.png").exists() for i in range(4))
    document = json.loads((tmp_path / "person_bbox.json").read_text(encoding="utf-8"))
    assert document["raw_detection_count"] == 6
    assert len(document["persons"]) == 5


def test_s01_context_crop_clamps_to_frame_and_ties_break_left(tmp_path: Path) -> None:
    detections = [
        Detection((60, 20, 100, 80), 0.9),
        Detection((0, 20, 40, 80), 0.9),
    ]

    result = process_detections(_image(), detections, tmp_path)

    assert [person.detection_index for person in result.persons] == [1, 0]
    assert result.persons[0].context_bbox_xyxy[0] == 0
    assert result.persons[1].context_bbox_xyxy[2] == 100
    assert Image.open(tmp_path / "p0" / "person_ctx.png").size == (45, 76)


def test_s01_rejects_no_eligible_person_and_quarantines_crowd(tmp_path: Path) -> None:
    rejected = process_detections(_image(), [Detection((0, 0, 10, 10), 0.9)], tmp_path / "rejected")
    crowd = process_detections(_image(), [Detection((0, 0, 30, 30), 0.9)] * 9, tmp_path / "crowd")

    assert (rejected.outcome, rejected.reason) == ("rejected", "no_person")
    assert (crowd.outcome, crowd.reason) == (
        "quarantined",
        "crowd_scene_out_of_scope",
    )


def test_s01_rejects_invalid_confidence(tmp_path: Path) -> None:
    with pytest.raises(PersonDetectionError, match="outside"):
        process_detections(_image(), [Detection((0, 0, 50, 50), 1.1)], tmp_path)


def test_s01_production_adapter_filters_person_and_runs_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image_path = tmp_path / "source.png"
    _image().save(image_path)
    checkpoint = tmp_path / "yolo.pt"
    checkpoint.write_bytes(b"fixture")

    class Values:
        def __init__(self, values):
            self.values = values

        def tolist(self):
            return self.values

    class Boxes:
        cls = Values([0.0])
        conf = Values([0.9])
        xyxy = Values([[10.0, 10.0, 90.0, 90.0]])

    class Result:
        boxes = Boxes()
        names = {0: "person"}

    calls = {}

    class FakeYolo:
        def __init__(self, path: str, task: str):
            calls["init"] = (path, task)

        def predict(self, **kwargs):
            calls["predict"] = kwargs
            return [Result()]

    import ultralytics

    monkeypatch.setattr(ultralytics, "YOLO", FakeYolo)
    detections = infer_yolo11_people(image_path, checkpoint=checkpoint, device="cpu")
    assert detections == [Detection((10.0, 10.0, 90.0, 90.0), 0.9)]
    assert calls["predict"]["classes"] == [0]
    result = run_s01(image_path, tmp_path / "s01", checkpoint=checkpoint, device="cpu")
    assert result.outcome == "promoted"
    assert (tmp_path / "s01/p0/person_ctx.png").is_file()


def test_s02_keeps_largest_and_qualifying_touching_component(tmp_path: Path) -> None:
    confidence = np.zeros((20, 20), dtype=np.float32)
    confidence[3:13, 3:13] = 0.9  # largest: 100 px
    confidence[13:15, 7:12] = 0.8  # 10 px, touches and exceeds 1% of 20x20
    confidence[0:2, 18:20] = 0.9  # isolated: discarded

    result = build_silhouette(
        confidence,
        context_bbox_xyxy=(10, 20, 30, 40),
        person_bbox_xyxy=(10, 20, 30, 40),
        full_size=(50, 60),
        output_dir=tmp_path,
        ratio_range=(0.2, 0.4),
    )

    mask = read_mask(result.silhouette_path)
    conf = read_mask(result.confidence_path)
    assert result.area_px == 110
    assert result.qc_passed
    assert mask.shape == (60, 50)
    assert set(np.unique(mask)) == {0, 255}
    assert np.count_nonzero(mask[:20]) == 0
    assert int(conf[20 + 3, 10 + 3]) == 230
    assert int(conf[20, 28]) == 230  # confidence retained even if component rejected


def test_s02_reports_ratio_failure_and_writes_metrics(tmp_path: Path) -> None:
    confidence = np.ones((10, 10), dtype=np.float32)
    result = build_silhouette(
        confidence,
        context_bbox_xyxy=(0, 0, 10, 10),
        person_bbox_xyxy=(0, 0, 10, 10),
        full_size=(10, 10),
        output_dir=tmp_path,
    )

    assert result.silhouette_bbox_ratio == 1.0
    assert not result.qc_passed
    metrics = json.loads((tmp_path / "silhouette_metrics.json").read_text())
    assert metrics["qc_passed"] is False


def test_s02_rejects_bad_confidence_or_shape(tmp_path: Path) -> None:
    with pytest.raises(SilhouetteError, match="0..1"):
        build_silhouette(
            np.full((2, 2), 1.1),
            context_bbox_xyxy=(0, 0, 2, 2),
            person_bbox_xyxy=(0, 0, 2, 2),
            full_size=(2, 2),
            output_dir=tmp_path,
        )
    with pytest.raises(SilhouetteError, match="shape"):
        build_silhouette(
            np.zeros((3, 2)),
            context_bbox_xyxy=(0, 0, 2, 2),
            person_bbox_xyxy=(0, 0, 2, 2),
            full_size=(2, 2),
            output_dir=tmp_path,
        )


def test_s02_production_adapter_validates_wsl_float_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "crop.png"
    _image().save(image)
    checkpoint = tmp_path / "model.safetensors"
    checkpoint.write_bytes(b"fixture")
    output = tmp_path / "confidence.npy"

    def fake_run(command, **kwargs):
        assert "run_birefnet_wsl.py" in " ".join(command)
        np.save(output, np.full((100, 100), 0.75, dtype=np.float32), allow_pickle=False)

        class Process:
            returncode = 0
            stderr = ""
            stdout = '{"shape":[100,100],"tile_count":1}\n'

        return Process()

    monkeypatch.setattr("maskfactory.stages.s02_silhouette.subprocess.run", fake_run)
    confidence = infer_birefnet_confidence(image, checkpoint=checkpoint, output_path=output)
    assert confidence.shape == (100, 100)
    assert confidence.dtype == np.float32
    assert np.all(confidence == 0.75)
