import json
from pathlib import Path

import numpy as np
from PIL import Image

from maskfactory.stages.s09_5_instance_recon import (
    ReconciliationInstance,
    reconcile_instances,
)


def test_reconciliation_is_reciprocal_and_flags_excessive_overlap(tmp_path: Path) -> None:
    a = np.zeros((40, 60), dtype=bool)
    b = np.zeros_like(a)
    a[5:35, 5:35] = True
    b[5:35, 20:50] = True
    result = reconcile_instances(
        image_id="img_a3f9c2e17b04",
        source_file="source.png",
        instances=(
            ReconciliationInstance("p0", a, (0, 0, 40, 40), tmp_path / "instances/p0"),
            ReconciliationInstance("p1", b, (15, 0, 55, 40), tmp_path / "instances/p1"),
        ),
        output_dir=tmp_path,
        background_person_count=1,
        crowd_scene=False,
        instance_overlap_max=0.3,
    )
    assert result.maximum_pair_iou == 1 / 3
    assert result.qc035_passed is False
    assert len(result.relationships) == 1
    for instance_id in ("p0", "p1"):
        path = tmp_path / f"instances/{instance_id}/masks_regions/interperson_contact_boundary.png"
        with Image.open(path) as image:
            assert image.mode == "L" and image.size == (40, 40)
            assert np.asarray(image).any()
    manifest = json.loads(result.image_manifest_path.read_text(encoding="utf-8"))
    assert manifest["promoted_instances"] == ["p0", "p1"]
    relationship = manifest["interperson_relationships"][0]
    assert relationship["contact_band_file_a"].startswith("instances/p0/")
    assert relationship["contact_band_file_b"].startswith("instances/p1/")


def test_single_instance_reconciliation_writes_trivial_passing_index(tmp_path: Path) -> None:
    silhouette = np.ones((20, 20), dtype=bool)
    result = reconcile_instances(
        image_id="img_a3f9c2e17b04",
        source_file="source.png",
        instances=(ReconciliationInstance("p0", silhouette, (0, 0, 20, 20), tmp_path / "p0"),),
        output_dir=tmp_path,
        background_person_count=0,
        crowd_scene=False,
    )
    assert result.qc035_passed and result.maximum_pair_iou == 0
    assert result.relationships == ()


def test_genuine_edge_contact_passes_overlap_gate_and_injects_reciprocal_bands(
    tmp_path: Path,
) -> None:
    a = np.zeros((50, 80), dtype=bool)
    b = np.zeros_like(a)
    a[10:40, 5:35] = True
    b[10:40, 35:65] = True  # bodies touch at one vertical edge, with zero overlap
    result = reconcile_instances(
        image_id="img_a3f9c2e17b04",
        source_file="source.png",
        instances=(
            ReconciliationInstance("p0", a, (0, 0, 45, 50), tmp_path / "p0"),
            ReconciliationInstance("p1", b, (25, 0, 75, 50), tmp_path / "p1"),
        ),
        output_dir=tmp_path,
        background_person_count=0,
        crowd_scene=False,
    )
    assert result.qc035_passed and result.maximum_pair_iou == 0
    assert len(result.relationships) == 1
    first = np.asarray(Image.open(tmp_path / "p0/masks_regions/interperson_contact_boundary.png"))
    second = np.asarray(Image.open(tmp_path / "p1/masks_regions/interperson_contact_boundary.png"))
    assert first.any() and second.any()
    assert result.relationships[0]["contact_band_file_a"].startswith("instances/p0/")
    assert result.relationships[0]["contact_band_file_b"].startswith("instances/p1/")


def test_three_person_middle_instance_contact_band_accumulates_both_neighbors(
    tmp_path: Path,
) -> None:
    shape = (40, 90)
    masks = []
    for left, right in ((5, 30), (30, 60), (60, 85)):
        mask = np.zeros(shape, dtype=bool)
        mask[8:32, left:right] = True
        masks.append(mask)
    boxes = ((0, 0, 45, 40), (20, 0, 70, 40), (45, 0, 90, 40))
    instances = tuple(
        ReconciliationInstance(f"p{index}", masks[index], boxes[index], tmp_path / f"p{index}")
        for index in range(3)
    )

    result = reconcile_instances(
        image_id="img_a3f9c2e17b04",
        source_file="source.png",
        instances=instances,
        output_dir=tmp_path / "recon",
        background_person_count=0,
        crowd_scene=False,
    )

    assert {(item["a"], item["b"]) for item in result.relationships} == {
        ("p0", "p1"),
        ("p1", "p2"),
    }
    middle = np.asarray(Image.open(tmp_path / "p1/masks_regions/interperson_contact_boundary.png"))
    assert middle[:, :15].any()
    assert middle[:, -15:].any()
