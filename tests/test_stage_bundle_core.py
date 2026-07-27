import json
from pathlib import Path

import numpy as np

from maskfactory.stages.s06_openvocab import BoxProposal, write_gdino_proposals
from maskfactory.stages.s08_5_densepose import read_densepose_iuv, write_densepose_iuv
from maskfactory.stages.s09_5_instance_recon import ReconciliationInstance, reconcile_instances


def test_s06_serializes_only_proposal_authority(tmp_path: Path) -> None:
    path = write_gdino_proposals(
        [BoxProposal("hand", (1.0, 2.0, 5.0, 6.0), 0.9, 0.8, "proposal_only")],
        tmp_path,
        allowed_prompts={"hand"},
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["authority"] == "proposal_boxes_only"
    assert document["proposals"][0]["prompt"] == "hand"


def test_s08_5_round_trips_validated_densepose_iuv(tmp_path: Path) -> None:
    part = np.array([[0, 1], [2, 24]], dtype=np.uint8)
    u = np.array([[0, 64], [128, 255]], dtype=np.uint8)
    v = np.array([[0, 32], [96, 255]], dtype=np.uint8)
    path = write_densepose_iuv(part, u, v, tmp_path / "iuv.png")
    restored = read_densepose_iuv(path)
    assert np.array_equal(restored.part_index, part)
    assert np.array_equal(restored.u, u)
    assert np.array_equal(restored.v, v)


def test_s09_5_records_contact_and_bounded_overlap(tmp_path: Path) -> None:
    shape = (12, 12)
    first = np.zeros(shape, dtype=bool)
    second = np.zeros(shape, dtype=bool)
    first[2:7, 2:7] = True
    second[5:10, 5:10] = True
    left_dir, right_dir = tmp_path / "p0", tmp_path / "p1"
    (left_dir / "masks_regions").mkdir(parents=True)
    (right_dir / "masks_regions").mkdir(parents=True)
    result = reconcile_instances(
        image_id="img_recon_core",
        source_file="source.png",
        instances=(
            ReconciliationInstance("p0", first, (0, 0, 12, 12), left_dir),
            ReconciliationInstance("p1", second, (0, 0, 12, 12), right_dir),
        ),
        output_dir=tmp_path / "output",
        background_person_count=0,
        crowd_scene=False,
        instance_overlap_max=0.3,
    )
    assert result.qc035_passed is True
    assert len(result.relationships) == 1
    assert (left_dir / "masks_regions/interperson_contact_boundary.png").is_file()
    assert (right_dir / "masks_regions/interperson_contact_boundary.png").is_file()
