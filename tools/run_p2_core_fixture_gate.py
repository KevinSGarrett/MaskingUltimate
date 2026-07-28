"""Run the exact ten governed P2 fixtures through p0 S09 and close core/QC gates."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maskfactory.orchestrator import load_pipeline_config, run_pipeline  # noqa: E402
from maskfactory.qa.core_drafts import verify_core_draft_contract  # noqa: E402
from maskfactory.qa.p2_truth_fixtures import (  # noqa: E402
    load_and_validate_fixture_manifest,
    sha256_file,
)
from maskfactory.qa.semantic import qc011_atomic_exclusivity  # noqa: E402

MIN_MATERIALLY_DRAFTED_CORE_PARTS = 12


def _runtime_hashes() -> dict[str, str]:
    return {
        "s05": sha256_file(ROOT / "src/maskfactory/stages/s05_geometry.py"),
        "production": sha256_file(ROOT / "src/maskfactory/stages/production.py"),
        "core_contract": sha256_file(ROOT / "src/maskfactory/qa/core_drafts.py"),
        "s09": sha256_file(ROOT / "src/maskfactory/stages/s09_fusion.py"),
        "qc011": sha256_file(ROOT / "src/maskfactory/qa/semantic.py"),
    }


from maskfactory.stages.production import build_production_runners  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture-manifest", type=Path, default=ROOT / "qa/fixtures/p2_s01_s02_truth.json"
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path(r"C:\Comfy_UI_Main\MaskedWarehouse\Body\LV-MHP-v1\LV-MHP-v1"),
    )
    parser.add_argument("--images-root", type=Path, default=ROOT / "work/p2_core_fixture_images")
    parser.add_argument("--work-root", type=Path, default=ROOT / "work/p2_core_fixture_pipeline")
    parser.add_argument(
        "--evidence",
        type=Path,
        default=ROOT / "qa/live_verification/p2_core_fixture_gate_20260712.json",
    )
    parser.add_argument(
        "--fixture",
        action="append",
        default=[],
        help="Run only a named native fixture id (repeatable); subset runs do not write gate evidence.",
    )
    return parser.parse_args()


def _stage_fixture(record: dict, dataset_root: Path, images_root: Path) -> str:
    source = dataset_root / record["source_relpath"]
    image_id = "img_" + record["source_sha256"][:12]
    target = images_root / image_id
    target.mkdir(parents=True, exist_ok=True)
    canonical = target / "source.jpg"
    if not canonical.is_file() or sha256_file(canonical) != record["source_sha256"]:
        shutil.copy2(source, canonical)
    with Image.open(canonical) as opened:
        width, height = opened.size
    manifest = {
        "schema_version": "1.0.0",
        "image_id": image_id,
        "status": "ingested",
        "reason": "governed_local_non_distributable_p2_fixture",
        "source": {
            "source_file": "source.jpg",
            "source_sha256": record["source_sha256"],
            "source_width": width,
            "source_height": height,
            "source_format": "JPEG",
            "source_origin": "lv_mhp_v1_local_qa_fixture",
            "exif_stripped": False,
        },
        "fixture_governance": {
            "external_masks_are_gold": False,
            "training_authority": False,
            "distribution_authority": False,
        },
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return image_id


def _neighbor_truth_in_context(
    record: dict, dataset_root: Path, context_box: list[int]
) -> np.ndarray:
    target = (dataset_root / record["truth_mask_relpath"]).resolve()
    left, top, right, bottom = context_box
    neighbor_union: np.ndarray | None = None
    native_id = record["id"]
    for path in sorted((dataset_root / "annotations").glob(f"{native_id}_*.png")):
        if path.resolve() == target:
            continue
        with Image.open(path) as opened:
            neighbor = np.asarray(opened) != 0
        cropped = neighbor[top:bottom, left:right]
        neighbor_union = cropped.copy() if neighbor_union is None else neighbor_union | cropped
    if neighbor_union is None:
        neighbor_union = np.zeros((bottom - top, right - left), dtype=bool)
    return neighbor_union


def _require_stage(instance_root: Path, image_id: str, stage: str) -> dict:
    path = instance_root / stage.lower().replace(".", "_") / image_id / "stage_run.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("status") != "complete" or document.get("stage") != stage:
        raise RuntimeError(f"{image_id}: {stage} is not complete")
    return document


def _run_one(
    record: dict,
    *,
    config: dict,
    dataset_root: Path,
    images_root: Path,
    work_root: Path,
) -> dict:
    image_id = _stage_fixture(record, dataset_root, images_root)
    shared_runners = build_production_runners(config, images_root=images_root)
    run_pipeline(
        image_id,
        selected=("S00", "S01"),
        config=config,
        work_root=work_root,
        runners=shared_runners,
        gpu_lock_path=ROOT / "runs/gpu.lock",
    )
    people = json.loads((work_root / "s01" / image_id / "person_bbox.json").read_text())
    person = next(item for item in people["persons"] if item.get("person_index") == 0)
    neighbor_truth = _neighbor_truth_in_context(record, dataset_root, person["context_bbox_xyxy"])
    neighbor_pixels = int(neighbor_truth.sum())
    instance_root = work_root / "instances/p0"
    runners = build_production_runners(
        config,
        images_root=images_root,
        person_index=0,
        shared_work_root=work_root,
    )
    s02 = run_pipeline(
        image_id,
        selected=("S02",),
        config=config,
        work_root=instance_root,
        runners=runners,
        gpu_lock_path=ROOT / "runs/gpu.lock",
    )
    if any(execution.status == "terminal" for execution in s02):
        raise RuntimeError(f"{image_id}: S02 routed to human review")
    runtime_hashes = _runtime_hashes()
    runtime_contract_path = instance_root / "s09" / image_id / "core_gate_runtime.json"
    try:
        runtime_current = (
            json.loads(runtime_contract_path.read_text(encoding="utf-8"))["implementation_hashes"]
            == runtime_hashes
        )
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        runtime_current = False
    run_pipeline(
        image_id,
        selected=("S03", "S04", "S05", "S06", "S07", "S08", "S08.5", "S09"),
        config=config,
        work_root=instance_root,
        runners=runners,
        gpu_lock_path=ROOT / "runs/gpu.lock",
        force=() if runtime_current else ("S05", "S07", "S08", "S09"),
    )
    s06 = _require_stage(instance_root, image_id, "S06")
    s07 = _require_stage(instance_root, image_id, "S07")
    _require_stage(instance_root, image_id, "S09")
    s09_dir = instance_root / "s09" / image_id
    core = verify_core_draft_contract(s09_dir / "core_drafts/manifest.json", s09_dir)
    with Image.open(s09_dir / "label_map_part.png") as opened:
        part_map = np.asarray(opened).copy()
    if part_map.shape != neighbor_truth.shape:
        raise RuntimeError(f"{image_id}: p0 PART map and co-subject truth crop dimensions differ")
    # External fixture annotations are QA-only here: they never enter a prompt or
    # production mask. They verify that p0 did not claim body pixels owned by a neighbor.
    body_authority = (part_map > 0) & (part_map < 50)
    output_neighbor_overlap_px = int(np.count_nonzero(body_authority & neighbor_truth))
    if output_neighbor_overlap_px:
        raise RuntimeError(
            f"{image_id}: p0 output claims {output_neighbor_overlap_px} co-subject pixels"
        )
    from maskfactory.ontology import get_ontology

    atomic = {label.name: part_map == label.id for label in get_ontology().labels_for_map("part")}
    qc011 = qc011_atomic_exclusivity(atomic)
    if not qc011.passed:
        raise RuntimeError(f"{image_id}: QC-011 failed: {qc011.detail}")
    refined_mask_count = len(list((instance_root / "s07" / image_id).glob("sam2_*.png")))
    drafted_count = sum(row["state"] == "drafted" for row in core["records"])
    if refined_mask_count < 1 or drafted_count < MIN_MATERIALLY_DRAFTED_CORE_PARTS:
        raise RuntimeError(
            f"{image_id}: anatomically shallow draft: {drafted_count} core parts and "
            f"{refined_mask_count} refined masks; require at least "
            f"{MIN_MATERIALLY_DRAFTED_CORE_PARTS} and 1"
        )
    runtime_contract_path.write_text(
        json.dumps(
            {"image_id": image_id, "implementation_hashes": runtime_hashes},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "fixture_id": record["id"],
        "image_id": image_id,
        "source_sha256": record["source_sha256"],
        "neighbor_pixels_in_p0_context": neighbor_pixels,
        "output_neighbor_overlap_px": output_neighbor_overlap_px,
        "s06_model_keys": s06["model_keys"],
        "s07_model_keys": s07["model_keys"],
        "s07_refined_mask_count": refined_mask_count,
        "core_part_count": core["core_part_count"],
        "core_drafted_count": drafted_count,
        "core_not_visible_count": sum(row["state"] == "not_visible" for row in core["records"]),
        "core_disabled_count": sum(row["state"] == "disabled" for row in core["records"]),
        "core_manifest_sha256": sha256_file(s09_dir / "core_drafts/manifest.json"),
        "part_map_sha256": sha256_file(s09_dir / "label_map_part.png"),
        "qc011_passed": qc011.passed,
        "qc011_detail": qc011.detail,
    }


def main() -> int:
    args = parse_args()
    manifest = load_and_validate_fixture_manifest(args.fixture_manifest, args.dataset_root)
    requested = set(args.fixture)
    records = [
        record for record in manifest["records"] if not requested or record["id"] in requested
    ]
    if requested - {record["id"] for record in records}:
        raise RuntimeError(f"unknown fixture ids: {sorted(requested - {r['id'] for r in records})}")
    config = load_pipeline_config(ROOT / "configs/pipeline.yaml")
    results = []
    for index, record in enumerate(records, 1):
        print(f"[{index}/{len(records)}] {record['id']} starting", flush=True)
        result = _run_one(
            record,
            config=config,
            dataset_root=args.dataset_root,
            images_root=args.images_root,
            work_root=args.work_root,
        )
        results.append(result)
        print(json.dumps(result, sort_keys=True), flush=True)
    if requested:
        print(f"PROBE PASS: {len(results)} selected fixture(s)")
        return 0
    if len(results) != 10 or any(
        row["core_part_count"] != 46
        or row["core_drafted_count"] < MIN_MATERIALLY_DRAFTED_CORE_PARTS
        or row["s07_refined_mask_count"] < 1
        or not row["qc011_passed"]
        for row in results
    ):
        raise RuntimeError("full P2 core fixture gate did not pass exactly 10 fixtures")
    evidence = {
        "schema_version": "1.0.0",
        "item_ids": ["MF-P2-05.08", "MF-P2-06.08"],
        "captured_at": datetime.now(UTC).isoformat(),
        "outcome": "pass",
        "fixture_count": len(results),
        "core_registry_rule": "PART ids 0..55 minus P3 hand-lane finger ids 24..33",
        "core_part_count_per_fixture": 46,
        "minimum_materially_drafted_core_parts": MIN_MATERIALLY_DRAFTED_CORE_PARTS,
        "qc011_pass_count": sum(row["qc011_passed"] for row in results),
        "fixture_manifest_sha256": sha256_file(args.fixture_manifest),
        "pipeline_config_sha256": sha256_file(ROOT / "configs/pipeline.yaml"),
        "implementation_hashes": _runtime_hashes(),
        "gate_harness_sha256": sha256_file(ROOT / "tools/run_p2_core_fixture_gate.py"),
        "results": results,
    }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"PASS: 10/10 core contracts and QC-011; wrote {args.evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
