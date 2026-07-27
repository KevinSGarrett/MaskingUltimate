import json
from pathlib import Path

from PIL import Image

from maskfactory.stages.s01_person_detection import Detection, process_detections


def test_s01_promotes_bounded_people_and_preserves_overflow_as_protected(tmp_path: Path) -> None:
    image = Image.new("RGB", (100, 100), color="white")
    result = process_detections(
        image,
        [
            Detection((10, 10, 90, 90), 0.99),
            Detection((0, 0, 40, 40), 0.90),
            Detection((60, 60, 100, 100), 0.80),
        ],
        tmp_path,
        max_instances_per_image=2,
    )

    assert result.outcome == "promoted"
    assert [person.promoted for person in result.persons] == [True, True, False]
    assert result.persons[-1].protected_as_part_50 is True
    assert (tmp_path / "p0" / "person_ctx.png").is_file()
    assert (tmp_path / "p1" / "person_ctx.png").is_file()
    document = json.loads((tmp_path / "person_bbox.json").read_text(encoding="utf-8"))
    assert document["outcome"] == "promoted"
    assert document["raw_detection_count"] == 3


def test_s01_rejects_empty_and_quarantines_crowd_without_creating_crops(tmp_path: Path) -> None:
    image = Image.new("RGB", (64, 64), color="white")
    rejected = process_detections(image, [], tmp_path / "rejected")
    crowded = process_detections(
        image,
        [Detection((0, 0, 32, 32), 0.9) for _ in range(9)],
        tmp_path / "crowded",
        crowd_scene_threshold=8,
    )

    assert (rejected.outcome, rejected.reason) == ("rejected", "no_person")
    assert (crowded.outcome, crowded.reason) == ("quarantined", "crowd_scene_out_of_scope")
    assert not list((tmp_path / "crowded").glob("p*/person_ctx.png"))
