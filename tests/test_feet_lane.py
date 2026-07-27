from pathlib import Path

import numpy as np
from PIL import Image

from maskfactory.lanes.feet import (
    apply_footwear_logic,
    create_foot_crop,
    split_foot_base_toes,
)


def test_foot_crop_uses_ankle_and_side_foot_keypoints(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (300, 220), "white").save(source)
    pose = np.zeros((133, 3), dtype=np.float64)
    pose[15] = (80, 120, 0.9)
    pose[17] = (105, 150, 0.8)
    pose[18] = (95, 152, 0.8)
    pose[19] = (75, 145, 0.8)
    prior = np.zeros((220, 300), dtype=bool)
    prior[115:160, 70:110] = True
    crop = create_foot_crop(source, prior, pose, side="left", output_dir=tmp_path / "crops")
    assert crop.image_path.name == "left_foot_crop.png"
    assert crop.transform.part == "left_foot"
    assert crop.transform.full_side == 53  # ceil(1.6 * 33px ankle/foot extent)


def test_mtp_width_profile_splits_foot_base_and_toes_exclusively() -> None:
    foot = np.zeros((100, 140), dtype=bool)
    foot[35:66, 15:100] = True
    foot[40:61, 100:125] = True  # narrower distal toe zone
    split = split_foot_base_toes(
        foot, heel_xy=(20, 50), big_toe_xy=(120, 43), small_toe_xy=(120, 58)
    )
    assert split.foot_base.any() and split.toes.any()
    assert not (split.foot_base & split.toes).any()
    assert np.array_equal(split.foot_base | split.toes, foot)
    assert 0.55 <= split.mtp_fraction_from_heel <= 0.85
    assert np.nonzero(split.toes)[1].mean() > np.nonzero(split.foot_base)[1].mean()


def test_shod_sock_and_barefoot_material_visibility_constitution() -> None:
    foot = np.zeros((60, 100), dtype=bool)
    foot[20:40, 10:90] = True
    split = split_foot_base_toes(foot, heel_xy=(15, 30), big_toe_xy=(85, 24), small_toe_xy=(85, 36))
    skin = foot.copy()
    shod = apply_footwear_logic(split, side="left", coverage="closed_shoe", visible_skin=skin)
    assert np.array_equal(shod.foot_base, foot)
    assert not shod.toes.any()
    assert shod.visibility_states["left_toes"] == "not_visible"
    assert np.all(shod.material_map[foot] == 8)
    assert not shod.visible_body_skin.any()
    sock = apply_footwear_logic(split, side="left", coverage="sock", visible_skin=skin)
    assert np.all(sock.material_map[foot] == 15)
    assert not sock.visible_body_skin.any()
    barefoot = apply_footwear_logic(split, side="left", coverage="barefoot", visible_skin=skin)
    assert barefoot.foot_base.any() and barefoot.toes.any()
    assert np.all(barefoot.material_map[foot] == 1)
    assert np.array_equal(barefoot.visible_body_skin, foot)
