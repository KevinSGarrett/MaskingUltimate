from pathlib import Path

import numpy as np
from PIL import Image

from maskfactory.qa.topology import (
    TopologyInputs,
    regression_guard,
    run_topology_qc,
    run_uncertainty_qc,
)


def _result(inputs, qc_id):
    return next(result for result in run_topology_qc(inputs) if result.qc_id == qc_id)


def test_qc025_chain_break_requires_real_occluder_gap_coverage() -> None:
    shape = (80, 100)
    wrist = np.zeros(shape, bool)
    hand = np.zeros(shape, bool)
    forearm = np.zeros(shape, bool)
    wrist[35:45, 20:25] = True
    hand[35:45, 40:50] = True
    forearm[35:45, 15:20] = True
    masks = {"left_wrist": wrist, "left_hand_base": hand, "left_forearm": forearm}
    broken = _result(
        TopologyInputs(masks=masks, side_reference_x={"left": 20, "right": 80}), "QC-025"
    )
    assert not broken.passed and "left_wrist<->left_hand_base" in broken.detail
    occluder = np.zeros(shape, bool)
    occluder[35:45, 25:40] = True
    explained = _result(
        TopologyInputs(
            masks=masks,
            occluders={("left_wrist", "left_hand_base"): occluder},
            side_reference_x={"left": 20, "right": 80},
        ),
        "QC-025",
    )
    assert explained.passed


def test_qc026_finger_containment_and_thumb_adjacency() -> None:
    shape = (100, 100)
    hand_region = np.zeros(shape, bool)
    base = np.zeros(shape, bool)
    thumb = np.zeros(shape, bool)
    hand_region[20:70, 20:70] = True
    base[40:65, 35:60] = True
    thumb[30:45, 30:40] = True
    inputs = TopologyInputs(
        masks={"left_hand_base": base, "left_thumb": thumb},
        hand_crop_regions={"left": hand_region},
        side_reference_x={"left": 40, "right": 70},
    )
    assert _result(inputs, "QC-026").passed
    outside = thumb.copy()
    outside[0:5, 0:5] = True
    bad = TopologyInputs(
        masks={"left_hand_base": base, "left_thumb": outside},
        hand_crop_regions={"left": hand_region},
        side_reference_x={"left": 40, "right": 70},
    )
    assert not _result(bad, "QC-026").passed


def test_qc027_band_geometry_intersects_both_and_matches_30pct() -> None:
    shape = (80, 100)
    upper = np.zeros(shape, bool)
    elbow = np.zeros(shape, bool)
    forearm = np.zeros(shape, bool)
    upper[35:45, 20:40] = True
    elbow[35:45, 40:46] = True
    forearm[35:45, 46:70] = True
    inputs = TopologyInputs(
        masks={"left_upper_arm": upper, "left_elbow": elbow, "left_forearm": forearm},
        joint_axes={"left_elbow": (1, 0)},
        joint_expected_heights={"left_elbow": 6},
        side_reference_x={"left": 30, "right": 70},
    )
    assert _result(inputs, "QC-027").passed
    bad = TopologyInputs(
        masks=inputs.masks,
        joint_axes=inputs.joint_axes,
        joint_expected_heights={"left_elbow": 20},
        side_reference_x=inputs.side_reference_x,
    )
    assert not _result(bad, "QC-027").passed


def test_qc028_side_coherence_and_qc029_breast_position_order() -> None:
    shape = (100, 100)
    left = np.zeros(shape, bool)
    right = np.zeros(shape, bool)
    left[30:50, 65:75] = True
    right[30:50, 25:35] = True
    band = np.zeros(shape, bool)
    band[20:60, 15:85] = True
    inputs = TopologyInputs(
        masks={"left_breast": left, "right_breast": right},
        side_reference_x={"left": 70, "right": 30},
        chest_horizontal_band=band,
        view="front",
    )
    assert _result(inputs, "QC-028").passed
    assert _result(inputs, "QC-029").passed
    swapped = TopologyInputs(
        masks={"left_breast": right, "right_breast": left},
        side_reference_x=inputs.side_reference_x,
        chest_horizontal_band=band,
        view="front",
    )
    assert not _result(swapped, "QC-028").passed
    assert not _result(swapped, "QC-029").passed
    back = TopologyInputs(
        masks=inputs.masks,
        side_reference_x=inputs.side_reference_x,
        chest_horizontal_band=band,
        view="back",
    )
    assert not _result(back, "QC-029").passed


def test_qc031_033_uncertainty_thresholds_and_routes() -> None:
    mask = np.zeros((100, 100), bool)
    mask[20:80, 20:80] = True
    heat = np.zeros((100, 100), np.uint8)
    heat[20:30, 20:40] = 200  # 200/3600 >3% above .5
    results = {
        result.qc_id: result
        for result in run_uncertainty_qc(
            part_masks={"hair": mask},
            disagreement=heat,
            sam2_predicted_iou={"hair": 0.49},
            parsing_degraded=True,
            pose_degraded=False,
        )
    }
    assert not results["QC-031"].passed and results["QC-031"].severity == "ROUTE"
    assert not results["QC-032"].passed and results["QC-032"].severity == "WARN"
    assert not results["QC-033"].passed and "parsing_degraded" in results["QC-033"].detail


def test_qc034_previous_gold_guard_writes_diff_report_and_blocks(tmp_path: Path) -> None:
    previous = np.zeros((60, 80), np.uint16)
    current = np.zeros_like(previous)
    previous[10:40, 10:40] = 18
    current[10:40, 50:75] = 18
    result = regression_guard(current, previous, output_dir=tmp_path)
    assert not result.passed and result.severity == "BLOCK"
    assert (tmp_path / "gold_v1_vs_v2_diff.json").exists()
    assert Image.open(tmp_path / "gold_v1_vs_v2_diff.png").size == (80, 60)
    passing = regression_guard(previous.copy(), previous, output_dir=tmp_path / "pass")
    assert passing.passed
