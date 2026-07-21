"""Replay and score the exact 20-image S04 hand-tagged acceptance set."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maskfactory.lanes.prior3d import surface_vote  # noqa: E402
from maskfactory.qa.s04_eval import (  # noqa: E402
    assert_s04_acceptance,
    load_hand_truth,
    score_predictions,
    sha256_file,
)
from maskfactory.stages.s04_pose import PoseCandidate, process_pose_candidates  # noqa: E402
from maskfactory.stages.s08_5_densepose import DensePoseOutput  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--truth", type=Path, default=ROOT / "qa/fixtures/p2_s04_hand_truth.json")
    parser.add_argument(
        "--lv-mhp-root",
        type=Path,
        default=Path(r"C:\Comfy_UI_Main\MaskedWarehouse\Body\LV-MHP-v1\LV-MHP-v1"),
    )
    parser.add_argument("--work-root", type=Path, default=ROOT / "work")
    parser.add_argument(
        "--evidence",
        type=Path,
        default=ROOT / "qa/live_verification/p2_s04_hand_truth_gate_20260712.json",
    )
    return parser.parse_args()


def _paths(
    record: dict, args: argparse.Namespace
) -> tuple[Path, Path, Path, Path, tuple[Path, Path]]:
    identifier = record["id"]
    if record["source_kind"] == "governed":
        source = ROOT / record["source_relpath"]
        pose_root = args.work_root / "instances/p0/s04" / identifier
        dense_root = args.work_root / "instances/p0/s08_5" / identifier
        bbox_path = args.work_root / "s01" / identifier / "person_bbox.json"
        dense_path = dense_root / "densepose_iuv.png"
        runtime_paths = (
            pose_root / "provider_work/runtime.json",
            dense_root / "provider_work/runtime.json",
        )
    elif record["source_kind"] == "lv_mhp_v1":
        native_id = identifier.removeprefix("lv_")
        source = args.lv_mhp_root / record["source_relpath"]
        pose_root = args.work_root / "p2_s04_external_real" / native_id
        bbox_path = args.work_root / "p2_s01_s02_acceptance" / native_id / "s01/person_bbox.json"
        dense_path = pose_root / "densepose_view/densepose_iuv.png"
        runtime_paths = (
            pose_root / "provider_work/runtime.json",
            pose_root / "densepose_view_provider/runtime.json",
        )
    else:
        raise ValueError(f"{identifier}: unsupported source_kind")
    return source, pose_root / "pose133.json", dense_path, bbox_path, runtime_paths


def main() -> int:
    args = parse_args()
    truth = load_hand_truth(args.truth)
    rules = yaml.safe_load((ROOT / "configs/pipeline.yaml").read_text(encoding="utf-8"))[
        "pose_tags_rules"
    ]
    predictions = []
    for record in truth["records"]:
        source, pose_path, dense_path, bbox_path, runtime_paths = _paths(record, args)
        if sha256_file(source) != record["source_sha256"]:
            raise RuntimeError(f"{record['id']}: source hash mismatch")
        for runtime_path in runtime_paths:
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            if not runtime.get("device") or "+cu128" not in str(runtime.get("torch", "")):
                raise RuntimeError(f"{record['id']}: non-governed GPU runtime evidence")
        pose = json.loads(pose_path.read_text(encoding="utf-8"))
        keypoints = np.asarray(
            [[point["x"], point["y"], point["confidence"]] for point in pose["keypoints"]],
            dtype=np.float64,
        )
        with Image.open(dense_path) as opened:
            iuv = np.asarray(opened).copy()
        densepose = DensePoseOutput(iuv[:, :, 0], iuv[:, :, 1], iuv[:, :, 2])
        vote = surface_vote(densepose.part_index > 0, densepose)
        people = json.loads(bbox_path.read_text(encoding="utf-8"))
        person = next(item for item in people["persons"] if item.get("person_index") == 0)
        result = process_pose_candidates(
            [PoseCandidate(tuple(pose["bbox_xyxy"]), keypoints)],
            instance_bbox_xyxy=tuple(person["bbox_xyxy"]),
            output_dir=args.work_root / "p2_s04_eval_replay" / record["id"],
            pose_tag_rules=rules,
            densepose_back_ratio=vote.back_fraction,
            densepose_side_vote=vote.side_vote,
        )
        prediction = {
            "id": record["id"],
            "view": result.view,
            "pose_tags": list(result.pose_tags),
            "pose_degraded": result.pose_degraded,
            "body_keypoint_fraction": result.body_keypoint_fraction,
            "densepose_back_ratio": vote.back_fraction,
            "densepose_side_vote": vote.side_vote,
            "source_sha256": record["source_sha256"],
            "pose_artifact_sha256": sha256_file(pose_path),
            "densepose_artifact_sha256": sha256_file(dense_path),
        }
        predictions.append(prediction)
        print(json.dumps(prediction, sort_keys=True), flush=True)
    score = score_predictions(truth["records"], predictions)
    assert_s04_acceptance(score)
    evidence = {
        "schema_version": "1.0.0",
        "item_id": "MF-P2-03.05",
        "captured_at": datetime.now(UTC).isoformat(),
        "outcome": "pass",
        "threshold": 0.90,
        "truth_manifest_sha256": sha256_file(args.truth),
        "pipeline_config_sha256": sha256_file(ROOT / "configs/pipeline.yaml"),
        "implementation_hashes": {
            "s04_pose": sha256_file(ROOT / "src/maskfactory/stages/s04_pose.py"),
            "densepose_referee": sha256_file(ROOT / "src/maskfactory/lanes/prior3d.py"),
            "evaluator": sha256_file(ROOT / "src/maskfactory/qa/s04_eval.py"),
        },
        "model_hashes": {
            "dwpose_detector": sha256_file(ROOT / "models/pose/yolox_l.onnx"),
            "dwpose_pose": sha256_file(ROOT / "models/pose/dw-ll_ucoco_384.onnx"),
            "densepose": sha256_file(ROOT / "models/densepose/densepose_rcnn_R_50_FPN_s1x.pkl"),
        },
        "score": score,
        "predictions": predictions,
    }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"PASS: view={score['view_accuracy']:.3f}, "
        f"pose_tags_exact={score['pose_tags_exact_accuracy']:.3f}; wrote {args.evidence}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
