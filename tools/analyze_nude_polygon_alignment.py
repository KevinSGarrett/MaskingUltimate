"""Summarize COCO polygon/bbox alignment failures without emitting source records."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from maskfactory.nude_corpus_intake import (
    load_adopted_intake,
    load_records,
    rasterize_coco_segmentation,
)


def _quantiles(values: list[float], probabilities: tuple[float, ...]) -> dict[str, float]:
    array = np.asarray(values, dtype=float)
    return {str(value): float(np.quantile(array, value)) for value in probabilities}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    args = parser.parse_args()

    intake = load_adopted_intake(args.intake, platform="local")
    source_records = load_records(intake)
    source_root = Path(intake["registry"]["root"])
    failed: set[str] = set()
    with args.records.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if "polygon_bbox_alignment_failed" in row["reasons"]:
                failed.add(str(row["sample_id"]))

    cache: dict[str, dict[int, list[dict[str, object]]]] = {}
    ious: list[float] = []
    deltas: list[float] = []
    segmentation_types: Counter[str] = Counter()
    rle_count_types: Counter[str] = Counter()
    rle_size_matches: Counter[str] = Counter()
    decode_failures: Counter[str] = Counter()
    for sample_id in failed:
        record = source_records[sample_id]
        annotation_ref = str(record["annotation_ref"])
        if annotation_ref not in cache:
            document = json.loads((source_root / annotation_ref).read_text(encoding="utf-8"))
            by_image: dict[int, list[dict[str, object]]] = {}
            for annotation in document.get("annotations", []):
                by_image.setdefault(int(annotation["image_id"]), []).append(annotation)
            cache[annotation_ref] = by_image
        for annotation in cache[annotation_ref].get(int(record["annotation_image_id"]), []):
            segmentation = annotation.get("segmentation")
            segmentation_types[type(segmentation).__name__] += 1
            if isinstance(segmentation, dict):
                rle_count_types[type(segmentation.get("counts")).__name__] += 1
                rle_size_matches[
                    str(segmentation.get("size") == [int(record["height"]), int(record["width"])])
                ] += 1
            try:
                mask = rasterize_coco_segmentation(
                    segmentation, width=int(record["width"]), height=int(record["height"])
                )
            except Exception as exc:  # diagnostic preserves only typed aggregate counts
                decode_failures[f"{type(exc).__name__}:{exc}"] += 1
                continue
            ys, xs = np.nonzero(mask)
            observed = (float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1))
            x, y, width, height = (float(value) for value in annotation["bbox"])
            expected = (x, y, x + width, y + height)
            left = max(expected[0], observed[0])
            top = max(expected[1], observed[1])
            right = min(expected[2], observed[2])
            bottom = min(expected[3], observed[3])
            intersection = max(0.0, right - left) * max(0.0, bottom - top)
            expected_area = (expected[2] - expected[0]) * (expected[3] - expected[1])
            observed_area = (observed[2] - observed[0]) * (observed[3] - observed[1])
            union = expected_area + observed_area - intersection
            ious.append(intersection / union if union else 0.0)
            deltas.append(max(abs(first - second) for first, second in zip(expected, observed)))

    result = {
        "failed_records": len(failed),
        "decoded_annotations": len(ious),
        "iou_quantiles": _quantiles(ious, (0.0, 0.1, 0.5, 0.9, 0.99, 1.0)),
        "edge_delta_quantiles": _quantiles(deltas, (0.0, 0.5, 0.9, 0.99, 1.0)),
        "edge_delta_le_1_5": sum(value <= 1.5 for value in deltas),
        "edge_delta_le_2": sum(value <= 2.0 for value in deltas),
        "segmentation_types": dict(sorted(segmentation_types.items())),
        "rle_count_types": dict(sorted(rle_count_types.items())),
        "rle_size_matches": dict(sorted(rle_size_matches.items())),
        "decode_failures": dict(sorted(decode_failures.items())),
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
