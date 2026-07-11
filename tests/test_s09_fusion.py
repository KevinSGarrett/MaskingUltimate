import hashlib
import json
import random
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from maskfactory.io.png_strict import read_mask
from maskfactory.stages.s09_fusion import (
    FusionError,
    ZOrderDecision,
    configure_determinism,
    fuse_consensus,
    make_contact_band,
    make_waist_band,
    run_s09_production,
)

WEIGHTS = {"sam2": 0.40, "sapiens": 0.25, "geometry": 0.15, "schp": 0.10, "densepose": 0.10}
CHAMPION_WEIGHTS = {**WEIGHTS, "custom_bodypart": 0.45}


def test_s09_production_assembles_disk_evidence_and_fills_visible_coverage(tmp_path: Path) -> None:
    shape = (20, 20)
    for name in ("s03", "s05", "s07", "s08", "s085"):
        (tmp_path / name).mkdir()
    left = np.zeros(shape, dtype=np.uint8)
    right = np.zeros(shape, dtype=np.uint8)
    left[4:16, 2:10] = 255
    right[4:16, 10:18] = 255
    Image.fromarray(left, mode="L").save(tmp_path / "s05/prior_left_forearm.png")
    Image.fromarray(right, mode="L").save(tmp_path / "s05/prior_right_forearm.png")
    Image.fromarray(left, mode="L").save(tmp_path / "s07/sam2_left_forearm.png")
    Image.fromarray(right, mode="L").save(tmp_path / "s07/sam2_right_forearm.png")
    sapiens = np.zeros(shape, dtype=np.uint8)
    sapiens[:, :10] = 6
    sapiens[:, 10:] = 16
    schp = np.zeros(shape, dtype=np.uint8)
    schp[:, :10] = 14
    schp[:, 10:] = 15
    Image.fromarray(sapiens, mode="L").save(tmp_path / "s03/sapiens_28.png")
    Image.fromarray(schp, mode="L").save(tmp_path / "s03/schp_atr.png")
    custom = np.zeros(shape, dtype=np.uint16)
    custom[:, :10] = 18
    custom[:, 10:] = 19
    Image.fromarray(custom).save(tmp_path / "s03/custom_bodypart.png")
    models_root = tmp_path / "models"
    models_root.mkdir()
    checkpoint = models_root / "champion.bin"
    checkpoint.write_bytes(b"champion fixture")
    checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    registry_document = json.loads(Path("models/model_registry.json").read_text())
    champion_entry = dict(registry_document["models"][0])
    champion_entry.update(
        {
            "key": "fixture_champion_bodypart",
            "role": "champion_bodypart",
            "file": "champion.bin",
            "sha256": checkpoint_sha,
            "verified": True,
        }
    )
    registry_document["models"] = [champion_entry]
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(registry_document), encoding="utf-8")
    (tmp_path / "s03/custom_bodypart_provenance.json").write_text(
        json.dumps({"role": "champion_bodypart", "checkpoint_sha256": checkpoint_sha}),
        encoding="utf-8",
    )
    Image.fromarray(np.ones(shape, dtype=np.uint8), mode="L").save(
        tmp_path / "s08/material_draft.png"
    )
    iuv = np.zeros((*shape, 3), dtype=np.uint8)
    iuv[:, :10, 0] = 4
    iuv[:, 10:, 0] = 3
    Image.fromarray(iuv, mode="RGB").save(tmp_path / "s085/densepose_iuv.png")
    full = np.zeros((30, 30), dtype=np.uint8)
    full[5:25, 5:25] = 255
    Image.fromarray(full, mode="L").save(tmp_path / "silhouette.png")
    protected = np.zeros((30, 30), dtype=np.uint8)
    protected[10:20, 5:8] = 255
    Image.fromarray(protected, mode="L").save(tmp_path / "other_person.png")
    pose = {
        "keypoints": [
            {
                "index": index,
                "x": 10 if index % 2 else 20,
                "y": 10 + index,
                "confidence": 0.9 if index in (5, 6, 11, 12) else 0.0,
            }
            for index in range(133)
        ]
    }
    (tmp_path / "pose.json").write_text(json.dumps(pose), encoding="utf-8")
    config = yaml.safe_load(Path("configs/pipeline.yaml").read_text(encoding="utf-8"))
    result = run_s09_production(
        s03_dir=tmp_path / "s03",
        s05_dir=tmp_path / "s05",
        s07_dir=tmp_path / "s07",
        s08_material_path=tmp_path / "s08/material_draft.png",
        s08_5_iuv_path=tmp_path / "s085/densepose_iuv.png",
        silhouette_path=tmp_path / "silhouette.png",
        pose_path=tmp_path / "pose.json",
        context_bbox_xyxy=(5, 5, 25, 25),
        parsing_maps=config["parsing_map"],
        weights=CHAMPION_WEIGHTS,
        output_dir=tmp_path / "output",
        other_person_protected_path=tmp_path / "other_person.png",
        model_registry_path=registry,
        models_root=models_root,
    )
    part = read_mask(result.part_map_path)
    assert set(np.unique(part).tolist()) == {18, 19, 50}
    assert np.all(part[5:15, :3] == 50)
    assert result.material_map_path.is_file() and result.disagreement_path.is_file()
    assert (tmp_path / "output/masks_regions/waist.png").is_file()
    metrics = json.loads((tmp_path / "output/work/s09/consensus.json").read_text())
    assert "custom_bodypart" in metrics["sources"]


def test_s09_determinism_setup_fixes_python_numpy_and_torch_contract() -> None:
    state = configure_determinism()
    python_first, numpy_first = random.random(), np.random.random()
    configure_determinism()
    assert random.random() == python_first
    assert np.random.random() == numpy_first
    assert state["seed"] == 1337
    assert state["pythonhashseed"] == "1337"
    assert state["cublas_workspace_config"] == ":4096:8"


def _score(shape=(30, 40), value=0.0):
    return np.full(shape, value, dtype=np.float32)


def test_s09_weighted_consensus_routes_and_normalized_disagreement(tmp_path: Path) -> None:
    silhouette = np.ones((30, 40), dtype=bool)
    left = _score()
    right = _score()
    left[:, :20] = 1
    right[:, 20:] = 1
    left[:, 18:22] = 0.8
    right[:, 18:22] = 0.8
    material = _score(value=1)
    result = fuse_consensus(
        part_evidence={
            "left_forearm": {"sam2": left, "sapiens": left, "geometry": left},
            "right_forearm": {"sam2": right, "sapiens": right, "geometry": right},
        },
        material_evidence={"skin": {"schp": material}},
        silhouette=silhouette,
        output_dir=tmp_path,
        weights=WEIGHTS,
    )
    part = read_mask(result.part_map_path)
    mat = read_mask(result.material_map_path)
    disagreement = read_mask(result.disagreement_path)
    assert set(np.unique(part)) == {18, 19}
    assert set(np.unique(mat)) == {1}
    assert disagreement[:, 19:21].min() == 255  # equal top-two scores => full disagreement
    assert disagreement[:, 0].max() == 0
    assert result.review_routes == {"left_forearm": "quick_pass", "right_forearm": "quick_pass"}
    metrics = json.loads((tmp_path / "work/s09/consensus.json").read_text())
    assert metrics["review_routes"] == result.review_routes


def test_s09_zorder_hair_hand_crossed_limb_and_object_rules(tmp_path: Path) -> None:
    shape = (20, 20)
    visible = np.ones(shape, dtype=bool)
    full = _score(shape, 0.8)
    material = _score(shape, 1)
    decisions = (
        ZOrderDecision("left_hand_base", "abdomen_stomach", "wrist_depth_cue_front"),
        ZOrderDecision("left_forearm", "right_forearm", "uninterrupted_contour"),
        ZOrderDecision("occluding_object", "left_thigh", "gdino_sam2_closed_contour_cover"),
    )
    result = fuse_consensus(
        part_evidence={
            name: {"sam2": full}
            for name in (
                "hair",
                "head_face",
                "left_hand_base",
                "abdomen_stomach",
                "left_forearm",
                "right_forearm",
                "occluding_object",
                "left_thigh",
            )
        },
        material_evidence={"skin": {"schp": material}},
        silhouette=visible,
        output_dir=tmp_path,
        weights=WEIGHTS,
        zorder_decisions=decisions,
    )
    # All overlap everywhere; automatic hair rule applies first and hair owns over face,
    # while explicit relations are still independently recorded for audit.
    assert any(r.reason == "hair_front_overlap" for r in result.occlusions)
    assert {r.reason for r in result.occlusions} >= {
        "wrist_depth_cue_front",
        "uninterrupted_contour",
        "gdino_sam2_closed_contour_cover",
    }
    boundary = read_mask(tmp_path / "masks_regions/overlap_occlusion_boundary.png")
    assert set(np.unique(boundary)) <= {0, 255}
    assert all(record.occluded_visibility == "partially_visible" for record in result.occlusions)


def test_s09_background_material_containment_bands_and_determinism(tmp_path: Path) -> None:
    silhouette = np.zeros((40, 50), dtype=bool)
    silhouette[5:35, 10:40] = True
    evidence = silhouette.astype(np.float32)
    skin = silhouette.astype(np.float32)
    waist = make_waist_band(silhouette, shoulder_mid_y=10, hip_mid_y=30)
    contact_seed = np.zeros_like(silhouette)
    contact_seed[20, 25] = True
    contact = make_contact_band(contact_seed)
    kwargs = dict(
        part_evidence={"abdomen_stomach": {"geometry": evidence}},
        material_evidence={"skin": {"schp": skin}},
        silhouette=silhouette,
        weights=WEIGHTS,
        region_bands={"waist": waist, "body_contact_region": contact},
    )
    first = fuse_consensus(output_dir=tmp_path / "a", **kwargs)
    second = fuse_consensus(output_dir=tmp_path / "b", **kwargs)
    assert first.artifact_sha256 == second.artifact_sha256
    part = read_mask(first.part_map_path)
    material = read_mask(first.material_map_path)
    assert np.all(part[~silhouette] == 0) and np.all(part[silhouette] == 7)
    assert np.all(material[~silhouette] == 0) and np.all(material[silhouette] == 1)
    assert read_mask(tmp_path / "a/masks_regions/waist.png").any()
    assert read_mask(tmp_path / "a/masks_regions/body_contact_region.png").any()


def test_s09_rejects_bad_weights_and_unassigned_silhouette(tmp_path: Path) -> None:
    visible = np.ones((2, 2), dtype=bool)
    zeros = np.zeros((2, 2), dtype=np.float32)
    ones = np.ones((2, 2), dtype=np.float32)
    with pytest.raises(FusionError, match="weights"):
        fuse_consensus(
            part_evidence={"hair": {"sam2": ones}},
            material_evidence={"skin": {"schp": ones}},
            silhouette=visible,
            output_dir=tmp_path,
            weights={"sam2": 1.0},
        )
    with pytest.raises(FusionError, match="unassigned"):
        fuse_consensus(
            part_evidence={"hair": {"sam2": zeros}},
            material_evidence={"skin": {"schp": ones}},
            silhouette=visible,
            output_dir=tmp_path,
            weights=WEIGHTS,
        )


def test_unused_champion_weight_is_byte_identical_before_promotion(tmp_path: Path) -> None:
    visible = np.ones((8, 8), dtype=bool)
    left = np.zeros((8, 8), dtype=np.float32)
    right = np.zeros((8, 8), dtype=np.float32)
    left[:, :4] = 1
    right[:, 4:] = 1
    kwargs = {
        "part_evidence": {
            "left_forearm": {"sam2": left},
            "right_forearm": {"sam2": right},
        },
        "material_evidence": {"skin": {"schp": np.ones((8, 8), dtype=np.float32)}},
        "silhouette": visible,
    }
    base = fuse_consensus(output_dir=tmp_path / "base", weights=WEIGHTS, **kwargs)
    ready = fuse_consensus(
        output_dir=tmp_path / "champion_ready", weights=CHAMPION_WEIGHTS, **kwargs
    )
    assert base.artifact_sha256 == ready.artifact_sha256
