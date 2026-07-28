#!/usr/bin/env python3
"""Create immutable CPU-safe COCO preflight and polygon-raster QA evidence."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path

from maskfactory.qa.coco_preflight import (
    CocoPreflightError,
    build_cpu_safe_coco_preflight,
    canonical_sha256,
    rasterize_authoritative_polygons,
    read_coco_document,
    sha256_file,
    write_json_atomically,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coco", required=True, type=Path, help="authoritative COCO annotations JSON")
    parser.add_argument("--image-root", required=True, type=Path, help="root for COCO file_name values")
    parser.add_argument("--output-dir", required=True, type=Path, help="new, immutable artifact directory")
    parser.add_argument("--max-images", default=32, type=int, help="lexically selected images to validate")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise CocoPreflightError(f"refusing to overwrite existing output directory: {output_dir}")
    if args.max_images < 1:
        raise CocoPreflightError("--max-images must be at least one")

    coco_path = args.coco.resolve()
    image_root = args.image_root.resolve()
    document = read_coco_document(coco_path)
    staging = output_dir.parent / f".{output_dir.name}.staging-{uuid.uuid4().hex}"
    try:
        staging.mkdir(parents=True, exist_ok=False)
        preflight = build_cpu_safe_coco_preflight(
            document, image_root, max_images=args.max_images
        )
        preflight["annotation_file_sha256"] = sha256_file(coco_path)
        write_json_atomically(staging / "input_manifest.json", preflight)
        raster_qa = rasterize_authoritative_polygons(
            document, preflight, image_root, staging / "rasterized_masks"
        )
        write_json_atomically(staging / "rasterized_masks_qa.json", raster_qa)
        receipt = {
            "artifact_type": "maskfactory.cpu_safe_coco_preflight_run_receipt.v1",
            "authority_claimed": False,
            "annotation_document_canonical_sha256": canonical_sha256(document),
            "inputs": {
                "annotation_file_sha256": sha256_file(coco_path),
                "coco_path": str(coco_path),
                "image_root": str(image_root),
                "max_images": args.max_images,
            },
            "outputs": {
                "input_manifest_sha256": sha256_file(staging / "input_manifest.json"),
                "rasterized_masks_qa_sha256": sha256_file(
                    staging / "rasterized_masks_qa.json"
                ),
            },
            "validation_contract": {
                "authoritative_polygons_required": True,
                "empty_or_full_masks_fail_closed": True,
                "promotion_or_acceptance_authority": False,
            },
        }
        write_json_atomically(staging / "run_receipt.json", receipt)
        staging.rename(output_dir)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    print(json.dumps({"output_dir": str(output_dir), "receipt_sha256": sha256_file(output_dir / "run_receipt.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CocoPreflightError as error:
        print(f"CPU-safe COCO preflight refused: {error}", file=sys.stderr)
        raise SystemExit(2) from error
