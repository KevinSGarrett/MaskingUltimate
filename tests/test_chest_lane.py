from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.io.png_strict import read_mask
from maskfactory.lanes.chest import (
    ChestLaneError,
    build_breast_seeds,
    clothing_boundary_chest,
    create_chest_crop,
    projected_breast_region,
    refine_chest_boundaries,
    render_mandatory_chest_panels,
    visible_breast_truth,
    write_projected_breast,
)
from maskfactory.qa.semantic import SemanticInputs, run_semantic_qc
from maskfactory.stages.s05_geometry import build_prompt_plan
from maskfactory.stages.s07_sam2 import SamCandidate
from maskfactory.stages.s09_fusion import fuse_consensus

WEIGHTS = {
    "sam2": 0.40,
    "sapiens": 0.25,
    "geometry": 0.15,
    "schp": 0.10,
    "densepose": 0.10,
}


def _torso() -> np.ndarray:
    torso = np.zeros((200, 200), dtype=bool)
    torso[30:170, 35:165] = True
    return torso


def test_chest_crop_uses_clavicle_underbust_and_exact_1_4_scale(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (300, 240), "white").save(source)
    mask = np.zeros((240, 300), dtype=bool)
    mask[50:150, 80:220] = True
    crop = create_chest_crop(
        source,
        mask,
        clavicle_y=50,
        under_bust_y=150,
        torso_left_x=80,
        torso_right_x=220,
        output_dir=tmp_path / "crops",
    )
    assert crop.transform.full_side == 196  # 140px torso width * 1.4
    assert Image.open(crop.image_path).size == (1024, 1024)
    assert set(np.unique(read_mask(crop.mask_path))) == {0, 255}


def test_breast_seeds_are_view_gated_and_character_perspective() -> None:
    torso = _torso()
    front = build_breast_seeds(
        torso,
        left_shoulder_xy=(140, 45),
        right_shoulder_xy=(60, 45),
        under_bust_y=115,
        view="front",
    )
    assert front.left.any() and front.right.any()
    assert np.nonzero(front.left)[1].mean() > np.nonzero(front.right)[1].mean()
    profile = build_breast_seeds(
        torso,
        left_shoulder_xy=(140, 45),
        right_shoulder_xy=(60, 45),
        under_bust_y=115,
        view="left_profile",
    )
    assert profile.left.any() and not profile.right.any()
    assert profile.visibility_states["right_breast"] == "not_visible"
    back = build_breast_seeds(
        torso,
        left_shoulder_xy=(140, 45),
        right_shoulder_xy=(60, 45),
        under_bust_y=115,
        view="back",
    )
    assert back.lane_skipped and not back.left.any() and not back.right.any()
    assert set(back.visibility_states.values()) == {"not_visible"}


def test_visible_truth_skin_identity_and_fully_clothed_empty_skin() -> None:
    seeds = build_breast_seeds(
        _torso(),
        left_shoulder_xy=(140, 45),
        right_shoulder_xy=(60, 45),
        under_bust_y=115,
        view="front",
    )
    skin = np.zeros_like(seeds.left)
    fabric = seeds.left | seeds.right
    clothed = visible_breast_truth(seeds, skin_contour=skin, fabric_contour=fabric)
    assert clothed.left_part.any() and clothed.right_part.any()
    assert not clothed.left_breast_skin.any() and not clothed.right_breast_skin.any()
    half_skin = np.zeros_like(skin)
    half_skin[:, :100] = True
    mixed = visible_breast_truth(seeds, skin_contour=half_skin, fabric_contour=fabric & ~half_skin)
    assert np.array_equal(mixed.left_breast_skin, mixed.left_part & half_skin)
    assert np.array_equal(mixed.right_breast_skin, mixed.right_part & half_skin)


def test_projected_region_is_torso_clipped_and_writer_rejects_masks(tmp_path: Path) -> None:
    torso = _torso()
    seeds = build_breast_seeds(
        torso,
        left_shoulder_xy=(140, 45),
        right_shoulder_xy=(60, 45),
        under_bust_y=115,
        view="front",
    )
    clothing = torso.copy()
    image = np.zeros((200, 200, 3), dtype=np.uint8)
    image[:, ::4] = 255  # luminance curvature evidence inside clothing
    projected = projected_breast_region(
        seeds.left, source_rgb=image, clothing=clothing, torso=torso
    )
    assert projected.sum() >= seeds.left.sum()
    assert np.all(projected <= torso)
    path = write_projected_breast(
        tmp_path / "projected", side="left", region=projected, source_size=(200, 200)
    )
    assert path.parent.name == "projected"
    with pytest.raises(ChestLaneError, match="only"):
        write_projected_breast(
            tmp_path / "masks", side="left", region=projected, source_size=(200, 200)
        )


def test_four_pixel_chest_transition_band_and_mandatory_panels(tmp_path: Path) -> None:
    region = np.zeros((100, 100), dtype=bool)
    region[20:80, 20:80] = True
    skin = np.zeros_like(region)
    clothing = np.zeros_like(region)
    skin[20:80, 20:50] = True
    clothing[20:80, 50:80] = True
    band = clothing_boundary_chest(region, skin, clothing)
    assert band[:, 46:54].any()
    assert not band[:, :40].any()
    strap = np.zeros_like(region)
    strap[20:80, 30:35] = True
    plans = {
        "strap": build_prompt_plan(
            "strap",
            strap,
            skeleton_points_xy=[(32, 25), (32, 50), (32, 75)],
            skeleton_samples=3,
        ),
        "inframammary_boundary": build_prompt_plan(
            "inframammary_boundary",
            band,
            skeleton_points_xy=[(46, 50), (50, 50), (53, 50)],
            skeleton_samples=3,
        ),
    }

    class Provider:
        def predict(self, embedding, plan, *, multimask_output):
            target = strap if plan.label == "strap" else band
            return [SamCandidate(np.where(target, 1.0, -1.0), 0.9)]

    refined = refine_chest_boundaries(
        Provider(),
        "embedding",
        {"strap": strap, "inframammary_boundary": band},
        plans,
        model="sam2",
    )
    assert refined["strap"].mask.any() and refined["inframammary_boundary"].mask.any()
    panels = render_mandatory_chest_panels(
        Image.new("RGB", (100, 100), "gray"),
        {"clothing_boundary_chest": band},
        np.zeros_like(region),
        tmp_path / "qa_panels",
    )
    assert len(panels) == 1
    assert Image.open(panels[0]).size == (2560, 512)


def test_s09_consumes_s08_map_and_clothed_breast_qc019_020_pass(tmp_path: Path) -> None:
    shape = (100, 100)
    silhouette = np.zeros(shape, dtype=bool)
    silhouette[20:80, 20:80] = True
    left = np.zeros(shape, dtype=bool)
    right = np.zeros(shape, dtype=bool)
    left[35:60, 30:48] = True
    right[35:60, 52:70] = True
    chest = silhouette & ~(left | right)
    s08 = np.zeros(shape, dtype=np.uint8)
    s08[silhouette] = 6  # fully top-garment covered
    fused = fuse_consensus(
        part_evidence={
            "left_breast": {"geometry": left},
            "right_breast": {"geometry": right},
            "chest_upper_torso": {"geometry": chest},
        },
        s08_material_map=s08,
        silhouette=silhouette,
        output_dir=tmp_path / "package",
        weights=WEIGHTS,
    )
    assert np.all(read_mask(fused.material_map_path)[silhouette] == 6)
    empty = np.zeros(shape, dtype=bool)
    projected = left | right
    inputs = SemanticInputs(
        atomic_parts={"left_breast": left, "right_breast": right, "chest_upper_torso": chest},
        silhouette=silhouette,
        protected=empty,
        skin_derived=empty,
        clothing=silhouette,
        person_bbox_area=10_000,
        side_votes={
            "left_breast": ("left", "left"),
            "right_breast": ("right", "right"),
        },
        breast_skin=empty,
        material_skin=empty,
        projected={"breast_projected_region": projected},
        projected_allowed_region=silhouette,
        source_gray=np.zeros(shape, np.float32),
    )
    results = {result.qc_id: result for result in run_semantic_qc(inputs)}
    assert results["QC-019"].passed
    assert results["QC-020"].passed
