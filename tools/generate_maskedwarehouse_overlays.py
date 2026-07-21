"""Generate bounded face/body source-mask alignment panels for MF-P0-13.03.

Also supports a disk-light CelebAMask-HQ face-panel lane (composited part masks)
for sealed visual-alignment QA. External source masks are never gold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

DEFAULT_WAREHOUSE = Path(r"C:\Comfy_UI_Main\MaskedWarehouse")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "work" / "maskedwarehouse_alignment"
DEFAULT_MANIFEST = ROOT / "qa" / "reports" / "maskedwarehouse_alignment_manifest.json"
DEFAULT_CELEBA_OUTPUT = ROOT / "work" / "celebamask_hq_alignment"
DEFAULT_CELEBA_MANIFEST = ROOT / "qa" / "reports" / "celebamask_hq_alignment_manifest.json"
SAMPLE_COUNT = 5
# Stable part IDs for composited CelebAMask-HQ alignment panels (visualization only).
CELEBA_PART_IDS: dict[str, int] = {
    "skin": 1,
    "nose": 2,
    "l_eye": 3,
    "r_eye": 4,
    "l_brow": 5,
    "r_brow": 6,
    "l_ear": 7,
    "r_ear": 8,
    "mouth": 9,
    "u_lip": 10,
    "l_lip": 11,
    "hair": 12,
    "hat": 13,
    "ear_r": 14,
    "neck_l": 15,
    "neck": 16,
    "cloth": 17,
    "eye_g": 18,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def lapa_pairs(root: Path) -> list[tuple[Path, Path]]:
    pairs = []
    for split in ("test", "train", "val"):
        image_root = root / split / "images"
        label_root = root / split / "labels"
        if not image_root.exists():
            continue
        for image_path in image_root.iterdir():
            if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            mask_path = label_root / f"{image_path.stem}.png"
            if mask_path.exists():
                pairs.append((image_path, mask_path))
    return sorted(pairs, key=lambda pair: str(pair[0]).casefold())


def lv_mhp_pairs(root: Path) -> list[tuple[Path, Path]]:
    nested = root / "LV-MHP-v1"
    base = nested if nested.exists() else root
    image_root = base / "images"
    annotation_root = base / "annotations"
    first_mask_by_image: dict[str, Path] = {}
    for mask_path in sorted(annotation_root.glob("*.png")):
        image_stem = mask_path.stem.split("_", 1)[0]
        first_mask_by_image.setdefault(image_stem, mask_path)
    pairs = []
    for image_path in image_root.iterdir():
        if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        mask_path = first_mask_by_image.get(image_path.stem)
        if mask_path:
            pairs.append((image_path, mask_path))
    return sorted(pairs, key=lambda pair: str(pair[0]).casefold())


def compose_celeba_label_map(mask_dir: Path) -> np.ndarray:
    """Composite per-part CelebAMask-HQ binary PNGs into one uint8 label map."""

    part_files = sorted(mask_dir.glob("*.png"))
    if not part_files:
        raise ValueError(f"no CelebA part masks in {mask_dir}")
    with Image.open(part_files[0]) as probe:
        width, height = probe.size
    labels = np.zeros((height, width), dtype=np.uint8)
    for part_path in part_files:
        token = part_path.stem.split("_", 1)[-1]
        part_id = CELEBA_PART_IDS.get(token)
        if part_id is None:
            continue
        with Image.open(part_path) as part_image:
            if part_image.size != (width, height):
                raise ValueError(f"CelebA part dimension mismatch: {part_path}")
            array = np.asarray(part_image.convert("L"))
        labels[array > 0] = np.uint8(part_id)
    if not np.any(labels):
        raise ValueError(f"CelebA composite mask is empty: {mask_dir}")
    return labels


def celeba_pairs(root: Path, *, limit: int | None = None) -> list[tuple[Path, Path]]:
    """Return (image, mask_dir) pairs for CelebAMask-HQ alignment sampling."""

    image_root = root / "CelebA-HQ-img"
    anno_root = root / "CelebAMask-HQ-mask-anno"
    if not image_root.is_dir() or not anno_root.is_dir():
        return []
    pairs: list[tuple[Path, Path]] = []
    # Numeric stems are contiguous from 0; probe in order to avoid listing 30k files.
    for index in range(0, 30_000):
        image_path = image_root / f"{index}.jpg"
        if not image_path.is_file():
            continue
        mask_dir = anno_root / str(index)
        if mask_dir.is_dir() and any(mask_dir.glob("*.png")):
            pairs.append((image_path, mask_dir))
            if limit is not None and len(pairs) >= limit:
                return pairs
    return pairs


def make_panel_from_labels(
    image_path: Path,
    labels: np.ndarray,
    destination: Path,
    *,
    mask_path: Path,
) -> dict:
    """Build a panel; CelebAMask-HQ images are resized to mask size (512) for QA."""

    with Image.open(image_path) as image_file:
        native = image_file.convert("RGB")
    native_size = [native.width, native.height]
    mask_size = [int(labels.shape[1]), int(labels.shape[0])]
    if native.size != (labels.shape[1], labels.shape[0]):
        # Official CelebAMask-HQ annotations are 512 while HQ images are 1024.
        image = native.resize((labels.shape[1], labels.shape[0]), Image.Resampling.BILINEAR)
        resize_policy = "image_to_mask_bilinear"
    else:
        image = native
        resize_policy = "native_match"
    source = np.asarray(image)
    panels = [
        tile(image, "source"),
        tile(colorize_labels(labels), "source mask labels"),
        tile(overlay_labels(source, labels), "overlay + 1px contour"),
    ]
    combined = Image.new("RGB", (1536, 512), "black")
    for index, panel in enumerate(panels):
        combined.paste(panel, (index * 512, 0))
    destination.parent.mkdir(parents=True, exist_ok=True)
    combined.save(destination, format="JPEG", quality=85, optimize=True)
    return {
        "source_path": str(image_path),
        "source_sha256": sha256_file(image_path),
        "mask_path": str(mask_path),
        "mask_sha256": hashlib.sha256(labels.tobytes()).hexdigest(),
        "mask_encoding": "celebamask_hq_composited_uint8_label_map",
        "native_image_dimensions": native_size,
        "mask_dimensions": mask_size,
        "alignment_resize_policy": resize_policy,
        "dimensions": mask_size,
        "dimension_match": True,
        "observed_label_ids": [int(value) for value in np.unique(labels)],
        "panel_path": str(destination),
        "panel_sha256": sha256_file(destination),
    }


def colorize_labels(labels: np.ndarray) -> Image.Image:
    palette = np.array(
        [
            [0, 0, 0],
            [230, 25, 75],
            [60, 180, 75],
            [255, 225, 25],
            [0, 130, 200],
            [245, 130, 48],
            [145, 30, 180],
            [70, 240, 240],
            [240, 50, 230],
            [210, 245, 60],
            [250, 190, 190],
            [0, 128, 128],
            [230, 190, 255],
            [170, 110, 40],
            [255, 250, 200],
            [128, 0, 0],
            [170, 255, 195],
            [128, 128, 0],
            [255, 215, 180],
        ],
        dtype=np.uint8,
    )
    return Image.fromarray(palette[labels.astype(np.int64) % len(palette)], mode="RGB")


def overlay_labels(source: np.ndarray, labels: np.ndarray) -> Image.Image:
    output = source.astype(np.float32).copy()
    foreground = labels > 0
    output[foreground] = output[foreground] * 0.57 + np.array([255, 64, 64]) * 0.43
    padded = np.pad(foreground, 1, mode="edge")
    interior = foreground.copy()
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        interior &= padded[
            1 + dy : 1 + dy + foreground.shape[0], 1 + dx : 1 + dx + foreground.shape[1]
        ]
    boundary = foreground & ~interior
    output[boundary] = (255, 255, 0)
    return Image.fromarray(np.clip(output, 0, 255).astype(np.uint8), mode="RGB")


def tile(image: Image.Image, label: str) -> Image.Image:
    fitted = ImageOps.contain(image.convert("RGB"), (512, 480))
    canvas = Image.new("RGB", (512, 512), "black")
    canvas.paste(fitted, ((512 - fitted.width) // 2, 32 + (480 - fitted.height) // 2))
    ImageDraw.Draw(canvas).text((8, 8), label, fill="white")
    return canvas


def make_panel(image_path: Path, mask_path: Path, destination: Path) -> dict:
    with Image.open(image_path) as image_file:
        image = image_file.convert("RGB")
    with Image.open(mask_path) as mask_file:
        labels = np.asarray(mask_file.convert("L"))
    if image.size != (labels.shape[1], labels.shape[0]):
        raise ValueError(
            f"dimension mismatch: {image_path} {image.size} vs {mask_path} {labels.shape}"
        )
    source = np.asarray(image)
    panels = [
        tile(image, "source"),
        tile(colorize_labels(labels), "source mask labels"),
        tile(overlay_labels(source, labels), "overlay + 1px contour"),
    ]
    combined = Image.new("RGB", (1536, 512), "black")
    for index, panel in enumerate(panels):
        combined.paste(panel, (index * 512, 0))
    destination.parent.mkdir(parents=True, exist_ok=True)
    combined.save(destination, format="JPEG", quality=85, optimize=True)
    return {
        "source_path": str(image_path),
        "source_sha256": sha256_file(image_path),
        "mask_path": str(mask_path),
        "mask_sha256": sha256_file(mask_path),
        "dimensions": [image.width, image.height],
        "dimension_match": True,
        "observed_label_ids": [int(value) for value in np.unique(labels)],
        "panel_path": str(destination),
        "panel_sha256": sha256_file(destination),
    }


def make_contact_sheet(panel_paths: list[Path], destination: Path) -> dict:
    rows = []
    for panel_path in panel_paths:
        with Image.open(panel_path) as panel:
            rows.append(panel.convert("RGB").resize((768, 256), Image.Resampling.LANCZOS))
    sheet = Image.new("RGB", (768, 256 * len(rows)), "black")
    for index, row in enumerate(rows):
        sheet.paste(row, (0, index * 256))
    sheet.save(destination, format="JPEG", quality=88, optimize=True)
    return {"path": str(destination), "sha256": sha256_file(destination), "rows": len(rows)}


def generate_overlays(
    warehouse_root: Path,
    output_root: Path,
    manifest_path: Path,
    sample_count: int = SAMPLE_COUNT,
) -> dict:
    sources = {
        "face_lapa": lapa_pairs(warehouse_root / "LaPa")[:sample_count],
        "body_lv_mhp_v1": lv_mhp_pairs(warehouse_root / "Body" / "LV-MHP-v1")[:sample_count],
    }
    if any(len(pairs) < sample_count for pairs in sources.values()):
        raise ValueError(
            f"insufficient alignment pairs: { {key: len(value) for key, value in sources.items()} }"
        )
    records = []
    for source_name, pairs in sources.items():
        category = "face" if source_name.startswith("face") else "body"
        for index, (image_path, mask_path) in enumerate(pairs, start=1):
            destination = output_root / category / f"{index:02d}_{image_path.stem}.jpg"
            record = make_panel(image_path, mask_path, destination)
            record.update({"source": source_name, "category": category})
            records.append(record)
    contact_sheets = {}
    for category in ("face", "body"):
        paths = [Path(record["panel_path"]) for record in records if record["category"] == category]
        contact_sheets[category] = make_contact_sheet(
            paths, output_root / f"{category}_contact_sheet.jpg"
        )
    manifest = {
        "schema_version": "1.0.0",
        "purpose": "source-mask alignment QA only; external masks are never gold",
        "face_panel_count": sum(record["category"] == "face" for record in records),
        "body_panel_count": sum(record["category"] == "body" for record in records),
        "all_dimensions_match": all(record["dimension_match"] for record in records),
        "visual_review_required": True,
        "contact_sheets": contact_sheets,
        "records": records,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def generate_celeba_overlays(
    warehouse_root: Path,
    output_root: Path,
    manifest_path: Path,
    sample_count: int = SAMPLE_COUNT,
) -> dict:
    """Generate bounded CelebAMask-HQ face alignment panels (never gold)."""

    pairs = celeba_pairs(warehouse_root / "CelebAMask-HQ", limit=sample_count)
    if len(pairs) < sample_count:
        raise ValueError(f"insufficient CelebAMask-HQ pairs: {len(pairs)} < {sample_count}")
    records = []
    for index, (image_path, mask_dir) in enumerate(pairs, start=1):
        labels = compose_celeba_label_map(mask_dir)
        destination = output_root / "face" / f"{index:02d}_{image_path.stem}.jpg"
        record = make_panel_from_labels(image_path, labels, destination, mask_path=mask_dir)
        record.update({"source": "face_celebamask_hq", "category": "face"})
        records.append(record)
    contact_sheet = make_contact_sheet(
        [Path(record["panel_path"]) for record in records],
        output_root / "face_celebamask_hq_contact_sheet.jpg",
    )
    manifest = {
        "schema_version": "1.0.0",
        "purpose": "source-mask alignment QA only; external masks are never gold",
        "source": "celebamask_hq",
        "face_panel_count": len(records),
        "body_panel_count": 0,
        "all_dimensions_match": all(record["dimension_match"] for record in records),
        "visual_review_required": True,
        "source_masks_are_gold": False,
        "training_or_gold_admission": False,
        "contact_sheets": {"face_celebamask_hq": contact_sheet},
        "records": records,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warehouse-root", type=Path, default=DEFAULT_WAREHOUSE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--sample-count", type=int, default=SAMPLE_COUNT)
    parser.add_argument(
        "--celeba-only",
        action="store_true",
        help="Generate only bounded CelebAMask-HQ face panels (disk-light STATIC lane).",
    )
    parser.add_argument("--celeba-output-root", type=Path, default=DEFAULT_CELEBA_OUTPUT)
    parser.add_argument("--celeba-manifest", type=Path, default=DEFAULT_CELEBA_MANIFEST)
    args = parser.parse_args()
    if args.celeba_only:
        manifest = generate_celeba_overlays(
            args.warehouse_root,
            args.celeba_output_root,
            args.celeba_manifest,
            args.sample_count,
        )
        print(
            f"celeba_face={manifest['face_panel_count']} "
            f"dimensions_match={manifest['all_dimensions_match']}"
        )
        return 0
    manifest = generate_overlays(
        args.warehouse_root, args.output_root, args.manifest, args.sample_count
    )
    print(
        f"face={manifest['face_panel_count']} body={manifest['body_panel_count']} "
        f"dimensions_match={manifest['all_dimensions_match']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
