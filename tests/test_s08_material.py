import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from maskfactory.stages.s05_geometry import build_prompt_plan
from maskfactory.stages.s07_sam2 import SamCandidate
from maskfactory.stages.s08_material import (
    MaterialError,
    build_material_map,
    detect_sheer,
    fuse_material_evidence,
    refine_material_regions,
    run_s08_production,
    thin_structure_pass,
)


def test_s08_production_writes_indexed_crop_space_draft_and_evidence(tmp_path: Path) -> None:
    source = np.full((20, 20, 3), 128, dtype=np.uint8)
    Image.fromarray(source, mode="RGB").save(tmp_path / "source.png")
    sapiens = np.full((20, 20), 22, dtype=np.uint8)
    sapiens[2:7, 2:18] = 3
    sapiens[7:14, 3:17] = 1
    schp = np.zeros((20, 20), dtype=np.uint8)
    schp[7:14, 3:17] = 4
    Image.fromarray(sapiens, mode="L").save(tmp_path / "sapiens.png")
    Image.fromarray(schp, mode="L").save(tmp_path / "schp.png")
    full = np.zeros((30, 30), dtype=np.uint8)
    full[5:25, 5:25] = 255
    Image.fromarray(full, mode="L").save(tmp_path / "silhouette.png")
    (tmp_path / "pose.json").write_text(
        json.dumps(
            {
                "keypoints": [
                    {"index": index, "x": 0, "y": 0, "confidence": 0} for index in range(133)
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "gdino.json").write_text(json.dumps({"proposals": []}), encoding="utf-8")
    config = yaml.safe_load(Path("configs/pipeline.yaml").read_text(encoding="utf-8"))

    class Provider:
        def __init__(self):
            self.embed_calls = 0
            self.closed = False

        def embed(self, image, *, model, precision):
            self.embed_calls += 1
            return "material-embedding"

        def predict(self, embedding, plan, *, multimask_output):
            logits = np.full((20, 20), -1.0, dtype=np.float32)
            left, top, right, bottom = plan.box_xyxy
            logits[top:bottom, left:right] = 1
            return [SamCandidate(logits, 0.4)]

        def close(self, embedding):
            self.closed = True

    provider = Provider()
    result = run_s08_production(
        source_path=tmp_path / "source.png",
        sapiens_path=tmp_path / "sapiens.png",
        schp_path=tmp_path / "schp.png",
        silhouette_path=tmp_path / "silhouette.png",
        pose_path=tmp_path / "pose.json",
        gdino_path=tmp_path / "gdino.json",
        context_bbox_xyxy=(5, 5, 25, 25),
        sapiens_map=config["parsing_map"]["sapiens_28"],
        schp_map=config["parsing_map"]["schp_atr"],
        output_dir=tmp_path / "output",
        provider=provider,
    )
    assert result.material_map.shape == (20, 20)
    assert {1, 2, 6} <= set(np.unique(result.material_map).tolist())
    image = Image.open(tmp_path / "output/material_draft.png")
    assert image.mode == "L" and image.size == (20, 20)
    evidence = json.loads((tmp_path / "output/material_evidence.json").read_text())
    assert evidence["primary"] == "schp_plus_s08_heuristics"
    assert evidence["pixel_counts"]["hair_material"] > 0
    assert evidence["sam2_refinement"]["hair_material"]["sam2_low_conf"] is True
    assert provider.embed_calls == 1 and provider.closed

    (tmp_path / "gdino.json").write_text(
        json.dumps(
            {
                "authority": "proposal_boxes_only",
                "may_write_final_masks": False,
                "allowed_consumers": ["sam2_prompting", "fusion_evidence"],
                "proposals": [
                    {
                        "prompt": "shoe",
                        "bbox_xyxy": [1, 1, 5, 5],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(MaterialError, match="require SAM2 refinement"):
        run_s08_production(
            source_path=tmp_path / "source.png",
            sapiens_path=tmp_path / "sapiens.png",
            schp_path=tmp_path / "schp.png",
            silhouette_path=tmp_path / "silhouette.png",
            pose_path=tmp_path / "pose.json",
            gdino_path=tmp_path / "gdino.json",
            context_bbox_xyxy=(5, 5, 25, 25),
            sapiens_map=config["parsing_map"]["sapiens_28"],
            schp_map=config["parsing_map"]["schp_atr"],
            output_dir=tmp_path / "unrefined",
        )


def test_promoted_clothing_model_becomes_primary_with_schp_named_fallback(
    tmp_path: Path,
) -> None:
    source = np.full((12, 12, 3), 128, dtype=np.uint8)
    Image.fromarray(source, mode="RGB").save(tmp_path / "source.png")
    Image.fromarray(np.zeros((12, 12), dtype=np.uint8), mode="L").save(tmp_path / "schp.png")
    full = np.full((12, 12), 255, dtype=np.uint8)
    Image.fromarray(full, mode="L").save(tmp_path / "silhouette.png")
    (tmp_path / "pose.json").write_text(
        json.dumps(
            {
                "keypoints": [
                    {"index": index, "x": 0, "y": 0, "confidence": 0} for index in range(133)
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "gdino.json").write_text('{"proposals":[]}\n', encoding="utf-8")
    models_root = tmp_path / "models"
    models_root.mkdir()
    checkpoint = models_root / "clothing.bin"
    checkpoint.write_bytes(b"verified clothing champion")
    checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    registry_document = json.loads(Path("models/model_registry.json").read_text())
    entry = dict(registry_document["models"][0])
    entry.update(
        {
            "key": "fixture_clothing_champion",
            "role": "champion_clothing",
            "file": "clothing.bin",
            "sha256": checkpoint_sha,
            "verified": True,
        }
    )
    registry_document["models"] = [entry]
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(registry_document), encoding="utf-8")
    config = yaml.safe_load(Path("configs/pipeline.yaml").read_text(encoding="utf-8"))
    champion_map = np.full((12, 12), 3, dtype=np.uint8)
    champion_map[:3] = 1
    events = []

    class Champion:
        def __call__(self, image):
            events.append(("predict", image.shape))
            return champion_map

        def close(self):
            events.append(("close",))

    result = run_s08_production(
        source_path=tmp_path / "source.png",
        sapiens_path=None,
        schp_path=tmp_path / "schp.png",
        silhouette_path=tmp_path / "silhouette.png",
        pose_path=tmp_path / "pose.json",
        gdino_path=tmp_path / "gdino.json",
        context_bbox_xyxy=(0, 0, 12, 12),
        sapiens_map=config["parsing_map"]["sapiens_28"],
        schp_map=config["parsing_map"]["schp_atr"],
        output_dir=tmp_path / "output",
        champion_loader=lambda path: Champion() if path == checkpoint else None,
        model_registry_path=registry,
        models_root=models_root,
    )
    np.testing.assert_array_equal(result.material_map, champion_map)
    evidence = json.loads((tmp_path / "output/material_evidence.json").read_text())
    assert evidence["primary"] == "champion_clothing"
    assert evidence["fallback"] == "schp_plus_s08_heuristics"
    assert evidence["checkpoint_sha256"] == checkpoint_sha
    assert events == [("predict", (12, 12, 3)), ("close",)]

    checkpoint.write_bytes(b"tampered")
    with pytest.raises(MaterialError, match="hash mismatch"):
        run_s08_production(
            source_path=tmp_path / "source.png",
            sapiens_path=None,
            schp_path=tmp_path / "schp.png",
            silhouette_path=tmp_path / "silhouette.png",
            pose_path=tmp_path / "pose.json",
            gdino_path=tmp_path / "gdino.json",
            context_bbox_xyxy=(0, 0, 12, 12),
            sapiens_map=config["parsing_map"]["sapiens_28"],
            schp_map=config["parsing_map"]["schp_atr"],
            output_dir=tmp_path / "tampered",
            champion_loader=lambda _path: Champion(),
            model_registry_path=registry,
            models_root=models_root,
        )


def test_s08_fusion_skin_excludes_clothing_and_specifics_require_evidence() -> None:
    shape = (60, 80)
    visible = np.ones(shape, dtype=bool)
    skin = np.ones(shape, dtype=bool)
    sapiens_clothing = np.zeros(shape, dtype=bool)
    sapiens_clothing[10:30, 10:70] = True
    top = np.zeros(shape, dtype=bool)
    top[10:25, 10:70] = True
    draft = fuse_material_evidence(
        sapiens_skin=skin,
        sapiens_clothing=sapiens_clothing,
        schp_regions={"upper_clothes": top},
        gdino_boxes={"bra": ((25, 15, 55, 25),)},
        silhouette=visible,
    )
    assert not (draft.regions["skin"] & sapiens_clothing).any()
    assert draft.regions["bra"].any()
    assert not draft.regions["underwear_bottom"].any()
    assert np.all(draft.material_map[draft.regions["bra"]] == 4)
    assert np.all(draft.material_map[draft.regions["skin"]] == 1)
    no_specific = fuse_material_evidence(
        sapiens_skin=skin,
        sapiens_clothing=sapiens_clothing,
        schp_regions={},
        gdino_boxes={},
        silhouette=visible,
    )
    assert not no_specific.regions["bra"].any()
    assert np.all(no_specific.material_map[sapiens_clothing] == 3)


def test_thin_structure_pass_classifies_vertical_shoulder_and_horizontal_iliac() -> None:
    clothing = np.zeros((120, 120), dtype=bool)
    clothing[10:55, 20:22] = True
    clothing[80:82, 45:105] = True
    shoulder = np.zeros_like(clothing)
    shoulder[5:25, 10:35] = True
    strap, waistband = thin_structure_pass(
        clothing, torso_width=100, shoulder_region=shoulder, iliac_y=80
    )
    assert strap[20, 20]
    assert waistband[80, 70]
    assert not (strap & waistband).any()


def test_thin_structure_pass_preserves_coordinates_on_large_sparse_canvas() -> None:
    clothing = np.zeros((2048, 3072), dtype=bool)
    clothing[900:1000, 1400:1403] = True
    clothing[1100:1103, 1500:1700] = True
    shoulder = np.zeros_like(clothing)
    shoulder[880:930, 1380:1420] = True

    strap, waistband = thin_structure_pass(
        clothing, torso_width=200, shoulder_region=shoulder, iliac_y=1100
    )

    assert strap[910, 1401]
    assert waistband[1101, 1600]
    assert not (strap & waistband).any()
    assert not strap[:800].any()
    assert not waistband[:, :1300].any()


def test_sheer_detection_uses_adjacent_skin_chroma_similarity() -> None:
    image = np.zeros((40, 60, 3), dtype=np.uint8)
    skin = np.zeros((40, 60), dtype=bool)
    clothing = np.zeros_like(skin)
    skin[:, :10] = True
    clothing[:, 10:50] = True
    image[skin] = (200, 150, 120)
    image[:, 10:30] = (180, 135, 108)  # same chroma direction => sheer
    image[:, 30:50] = (30, 60, 220)  # dissimilar opaque fabric
    sheer = detect_sheer(image, clothing, skin)
    assert sheer[:, 10:30].all()
    assert not sheer[:, 30:50].any()


def test_every_material_region_refines_and_glove_sock_protects_hand_foot() -> None:
    shape = (100, 100)
    top = np.zeros(shape, dtype=bool)
    top[20:80, 20:80] = True
    plan = build_prompt_plan(
        "top_garment",
        top,
        skeleton_points_xy=[(30, 50), (50, 50), (70, 50)],
        skeleton_samples=3,
    )

    class Provider:
        def __init__(self):
            self.calls = 0

        def predict(self, embedding, plan, *, multimask_output):
            self.calls += 1
            return [SamCandidate(np.where(top, 1.0, -1.0), 0.9)]

    hand_foot = np.zeros(shape, dtype=bool)
    texture = np.zeros(shape, dtype=bool)
    hand_foot[30:50, 30:50] = True
    texture[40:60, 40:60] = True
    provider = Provider()
    refined = refine_material_regions(
        provider,
        "embedding",
        {"top_garment": top},
        {"top_garment": plan},
        model="sam2",
        hand_foot_region=hand_foot,
        clothing_texture=texture,
    )
    assert provider.calls == 1
    assert refined["top_garment"].mask.any()
    assert refined["glove_or_sock"].sum() == 100
    material = build_material_map(
        {"top_garment": refined["top_garment"].mask, "glove_or_sock": refined["glove_or_sock"]},
        np.ones(shape, bool),
    )
    assert np.all(material[40:50, 40:50] == 15)
