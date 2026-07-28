"""Replay the exact ten-image P2 S01/S02 acceptance fixture set."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maskfactory.qa.p2_truth_fixtures import (  # noqa: E402
    assert_acceptance,
    bbox_iou,
    binary_mask_iou,
    load_and_validate_fixture_manifest,
    sha256_file,
)
from maskfactory.stages.s01_person_detection import run_s01  # noqa: E402
from maskfactory.stages.s02_silhouette import run_s02  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "qa/fixtures/p2_s01_s02_truth.json")
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path(r"C:\Comfy_UI_Main\MaskedWarehouse\Body\LV-MHP-v1\LV-MHP-v1"),
    )
    parser.add_argument("--work-root", type=Path, default=ROOT / "work/p2_s01_s02_acceptance")
    parser.add_argument(
        "--evidence",
        type=Path,
        default=ROOT / "qa/live_verification/p2_s01_s02_truth_gate_20260712.json",
    )
    parser.add_argument(
        "--local-cuda-python",
        type=Path,
        default=Path(r"C:\Comfy_UI_Main\ComfyUI\.venv\Scripts\python.exe"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_and_validate_fixture_manifest(args.manifest, args.dataset_root)
    results = []
    for record in manifest["records"]:
        identifier = record["id"]
        source = args.dataset_root / record["source_relpath"]
        truth = args.dataset_root / record["truth_mask_relpath"]
        fixture_root = args.work_root / identifier
        if fixture_root.exists():
            shutil.rmtree(fixture_root)
        s01 = run_s01(
            source,
            fixture_root / "s01",
            checkpoint=ROOT / "models/detect/yolo11m.pt",
            device="cpu",
        )
        person = next((item for item in s01.persons if item.person_index == 0), None)
        if person is None:
            raise RuntimeError(f"{identifier}: S01 did not promote p0")
        with Image.open(source) as opened:
            full_size = opened.size
        s02 = run_s02(
            fixture_root / "s01/p0/person_ctx.png",
            context_bbox_xyxy=person.context_bbox_xyxy,
            person_bbox_xyxy=person.bbox_xyxy,
            full_size=full_size,
            output_dir=fixture_root / "s02",
            checkpoint=ROOT / "models/silhouette/BiRefNet-general.safetensors",
            local_cuda_python=args.local_cuda_python,
            hf_home=ROOT / "models/runtime_cache/huggingface",
        )
        result = {
            "id": identifier,
            "detector_source": s01.detector_source,
            "detected_bbox_xyxy": list(person.bbox_xyxy),
            "truth_bbox_xyxy": record["truth_bbox_xyxy"],
            "bbox_iou": bbox_iou(tuple(person.bbox_xyxy), tuple(record["truth_bbox_xyxy"])),
            "silhouette_iou": binary_mask_iou(s02.silhouette_path, truth),
            "s02_qc_passed": s02.qc_passed,
            "prediction_sha256": sha256_file(s02.silhouette_path),
        }
        results.append(result)
        print(json.dumps(result, sort_keys=True), flush=True)
    assert_acceptance(results)
    evidence = {
        "schema_version": "1.0.0",
        "item_id": "MF-P2-01.03",
        "captured_at": datetime.now(UTC).isoformat(),
        "outcome": "pass",
        "threshold": 0.95,
        "fixture_count": len(results),
        "manifest_sha256": sha256_file(args.manifest),
        "model_hashes": {
            "yolo11m": sha256_file(ROOT / "models/detect/yolo11m.pt"),
            "birefnet_general": sha256_file(
                ROOT / "models/silhouette/BiRefNet-general.safetensors"
            ),
        },
        "minimum_bbox_iou": min(row["bbox_iou"] for row in results),
        "minimum_silhouette_iou": min(row["silhouette_iou"] for row in results),
        "results": results,
    }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"PASS: wrote {args.evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
