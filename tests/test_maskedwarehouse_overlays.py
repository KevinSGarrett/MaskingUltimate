import importlib.util
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "generate_maskedwarehouse_overlays",
    ROOT / "tools" / "generate_maskedwarehouse_overlays.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
generate_overlays = MODULE.generate_overlays


def _save_pair(image_path: Path, mask_path: Path, seed: int) -> None:
    image_path.parent.mkdir(parents=True, exist_ok=True)
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    y, x = np.mgrid[:24, :32]
    image = np.stack(
        ((x + seed) * 7 % 256, (y + seed) * 9 % 256, (x + y) * 4 % 256), axis=2
    ).astype(np.uint8)
    mask = ((x // 8 + y // 8 + seed) % 4).astype(np.uint8)
    Image.fromarray(image).save(image_path)
    Image.fromarray(mask).save(mask_path)


def test_generates_celeba_face_alignment_panels(tmp_path: Path) -> None:
    celeba_root = tmp_path / "CelebAMask-HQ"
    for index in range(5):
        image_path = celeba_root / "CelebA-HQ-img" / f"{index}.jpg"
        mask_dir = celeba_root / "CelebAMask-HQ-mask-anno" / str(index)
        image_path.parent.mkdir(parents=True, exist_ok=True)
        mask_dir.mkdir(parents=True, exist_ok=True)
        y, x = np.mgrid[:32, :32]
        image = np.stack(
            ((x + index) * 7 % 256, (y + index) * 9 % 256, (x + y) * 4 % 256), axis=2
        ).astype(np.uint8)
        Image.fromarray(image).resize((64, 64)).save(image_path)
        # Official-style 2x smaller mask canvas.
        mask = ((x // 8 + y // 8 + index) % 2 * 255).astype(np.uint8)
        Image.fromarray(mask).save(mask_dir / f"{index:05d}_skin.png")
        Image.fromarray((mask // 2).astype(np.uint8)).save(mask_dir / f"{index:05d}_hair.png")

    output_root = tmp_path / "panels"
    manifest_path = tmp_path / "celeba_manifest.json"
    manifest = MODULE.generate_celeba_overlays(tmp_path, output_root, manifest_path, sample_count=5)
    assert manifest["face_panel_count"] == 5
    assert manifest["source"] == "celebamask_hq"
    assert manifest["source_masks_are_gold"] is False
    assert manifest["training_or_gold_admission"] is False
    assert all(record["source"] == "face_celebamask_hq" for record in manifest["records"])
    assert all(
        record["alignment_resize_policy"] == "image_to_mask_bilinear"
        for record in manifest["records"]
    )
    assert Path(manifest["contact_sheets"]["face_celebamask_hq"]["path"]).is_file()


def test_generates_five_face_and_five_body_alignment_panels(tmp_path: Path) -> None:
    for index in range(5):
        stem = f"face_{index}"
        _save_pair(
            tmp_path / "LaPa" / "train" / "images" / f"{stem}.jpg",
            tmp_path / "LaPa" / "train" / "labels" / f"{stem}.png",
            index,
        )
        body_stem = f"{index + 1:04d}"
        _save_pair(
            tmp_path / "Body" / "LV-MHP-v1" / "LV-MHP-v1" / "images" / f"{body_stem}.jpg",
            tmp_path
            / "Body"
            / "LV-MHP-v1"
            / "LV-MHP-v1"
            / "annotations"
            / f"{body_stem}_01_01.png",
            index,
        )
    output_root = tmp_path / "panels"
    manifest_path = tmp_path / "manifest.json"
    manifest = generate_overlays(tmp_path, output_root, manifest_path)

    assert manifest["face_panel_count"] == 5
    assert manifest["body_panel_count"] == 5
    assert manifest["all_dimensions_match"] is True
    assert len(manifest["records"]) == 10
    assert all(record["source_sha256"] and record["mask_sha256"] for record in manifest["records"])
    assert all(Path(record["panel_path"]).exists() for record in manifest["records"])
    assert all(
        Image.open(record["panel_path"]).size == (1536, 512) for record in manifest["records"]
    )
    assert set(manifest["contact_sheets"]) == {"face", "body"}
    assert all(
        Image.open(sheet["path"]).size == (768, 1280)
        for sheet in manifest["contact_sheets"].values()
    )
