"""Stream a deterministic inventory of the local MaskedWarehouse datasets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

import numpy as np
from PIL import Image

DEFAULT_ROOT = Path(r"C:\Comfy_UI_Main\MaskedWarehouse")
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "configs" / "maskedwarehouse_inventory.json"
SAMPLE_COUNT = 5
RASTER_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}

SOURCE_DEFINITIONS = {
    "celebamask_hq": {
        "relative_root": "CelebAMask-HQ",
        "role": "face_components",
        "image_markers": {"celeba-hq-img"},
        "mask_markers": {"celebamask-hq-mask-anno"},
        "expected_encoding": "per-component binary PNG",
    },
    "lapa": {
        "relative_root": "LaPa",
        "role": "face_parsing",
        "image_markers": {"images"},
        "mask_markers": {"labels"},
        "expected_encoding": "indexed semantic PNG",
    },
    "lv_mhp_v1": {
        "relative_root": "Body/LV-MHP-v1",
        "role": "multi_person_full_body_parsing",
        "image_markers": {"images"},
        "mask_markers": {"annotations"},
        "expected_encoding": "indexed per-person semantic PNG",
    },
    "swimsuit_preview": {
        "relative_root": "Body/UniDataPro_swimsuit-human-segmentation-dataset",
        "role": "clothing_body_color_segmentation_preview",
        "image_names": {"image.jpg"},
        "mask_names": {"mask.png"},
        "ignored_markers": {".cache"},
        "expected_encoding": "RGB color map",
    },
    "body_archive": {
        "relative_root": "Body/archive",
        "role": "seven_group_body_color_segmentation",
        "image_markers": {"img"},
        "mask_markers": {"masks"},
        "expected_encoding": "RGB color map paired by stem; semantics referenced by workbook",
    },
}


def iter_files(root: Path) -> Iterator[Path]:
    stack = [root]
    while stack:
        directory = stack.pop()
        subdirectories = []
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    subdirectories.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    yield Path(entry.path)
        stack.extend(subdirectories)


def classify_file(path: Path, root: Path, definition: dict[str, Any]) -> str:
    relative = path.relative_to(root)
    parts = {part.lower() for part in relative.parts[:-1]}
    name = path.name.lower()
    if parts & set(definition.get("ignored_markers", set())):
        return "ignored"
    if path.suffix.lower() not in RASTER_SUFFIXES:
        return "metadata"
    if name in definition.get("image_names", set()) or parts & set(
        definition.get("image_markers", set())
    ):
        return "image"
    if name in definition.get("mask_names", set()) or parts & set(
        definition.get("mask_markers", set())
    ):
        return "mask"
    return "metadata"


def update_smallest(samples: list[str], value: str, limit: int) -> None:
    if value in samples:
        return
    samples.append(value)
    samples.sort(key=str.casefold)
    del samples[limit:]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_image(path: Path, root: Path, include_values: bool) -> dict[str, Any]:
    with Image.open(path) as image:
        record: dict[str, Any] = {
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "sha256": sha256_file(path),
            "format": image.format,
            "mode": image.mode,
            "size": [image.width, image.height],
        }
        if include_values:
            array = np.asarray(image)
            if array.ndim == 2:
                values = np.unique(array)
                record["unique_value_count"] = int(values.size)
                record["unique_values"] = [int(value) for value in values[:256]]
                record["values_truncated"] = values.size > 256
            else:
                colors = np.unique(array.reshape(-1, array.shape[-1]), axis=0)
                record["unique_color_count"] = int(colors.shape[0])
                record["unique_colors"] = [color.tolist() for color in colors[:256]]
                record["colors_truncated"] = colors.shape[0] > 256
        return record


def infer_encoding(mask_samples: list[dict[str, Any]]) -> str:
    if not mask_samples:
        return "no_masks_sampled"
    modes = {sample["mode"] for sample in mask_samples}
    if modes <= {"1", "L"}:
        values = {value for sample in mask_samples for value in sample.get("unique_values", [])}
        if values <= {0, 255}:
            return "binary_grayscale"
        return "indexed_grayscale"
    if "P" in modes:
        return "indexed_palette"
    if modes & {"RGB", "RGBA"}:
        colors = {
            tuple(color) for sample in mask_samples for color in sample.get("unique_colors", [])
        }
        if colors <= {(0, 0, 0), (255, 255, 255)}:
            return "binary_rgb"
        return "rgb_or_rgba_color_map"
    return "mixed_or_unknown"


def inventory_source(
    warehouse_root: Path, name: str, definition: dict[str, Any], sample_count: int
) -> dict[str, Any]:
    root = warehouse_root / Path(definition["relative_root"])
    counts = Counter()
    extensions: dict[str, Counter] = {
        "image": Counter(),
        "mask": Counter(),
        "metadata": Counter(),
        "ignored": Counter(),
    }
    samples: dict[str, list[str]] = {role: [] for role in extensions}
    for path in iter_files(root):
        role = classify_file(path, root, definition)
        counts[role] += 1
        extensions[role][path.suffix.lower() or "<none>"] += 1
        update_smallest(samples[role], str(path.relative_to(root)).replace("\\", "/"), sample_count)

    image_samples = [inspect_image(root / path, root, False) for path in samples["image"]]
    mask_samples = [inspect_image(root / path, root, True) for path in samples["mask"]]
    return {
        "source": name,
        "root": str(root),
        "role": definition["role"],
        "expected_encoding": definition["expected_encoding"],
        "counts": {
            "images": counts["image"],
            "masks": counts["mask"],
            "metadata": counts["metadata"],
            "ignored": counts["ignored"],
            "total_files": sum(counts.values()),
        },
        "extensions": {role: dict(sorted(counter.items())) for role, counter in extensions.items()},
        "sample_count_per_role": sample_count,
        "image_samples": image_samples,
        "mask_samples": mask_samples,
        "observed_mask_encoding": infer_encoding(mask_samples),
    }


def build_inventory(warehouse_root: Path, sample_count: int = SAMPLE_COUNT) -> dict[str, Any]:
    sources = [
        inventory_source(warehouse_root, name, definition, sample_count)
        for name, definition in SOURCE_DEFINITIONS.items()
    ]
    return {
        "schema_version": "1.0.0",
        "warehouse_root": str(warehouse_root),
        "streaming_inventory": True,
        "sample_hash_policy": f"lexicographically smallest {sample_count} files per role",
        "source_count": len(sources),
        "sources": sources,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-count", type=int, default=SAMPLE_COUNT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = (
        json.dumps(build_inventory(args.root, args.sample_count), indent=2, ensure_ascii=False)
        + "\n"
    )
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"stale inventory: run {Path(__file__).name}")
        print(f"PASS: {args.output} is current")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
