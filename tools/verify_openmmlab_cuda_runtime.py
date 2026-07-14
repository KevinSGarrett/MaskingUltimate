"""Verify the pinned OpenMMLab stack with a real MMSeg sample and CUDA op."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import mmcv  # noqa: E402
import mmcv._ext  # noqa: E402
import mmdet  # noqa: E402
import mmengine  # noqa: E402
import mmseg  # noqa: E402
from mmcv.ops import nms  # noqa: E402
from mmseg.registry import DATASETS  # noqa: E402

import maskfactory.training.mmseg_metric  # noqa: E402, F401
import maskfactory.training.mmseg_transforms  # noqa: E402, F401
from maskfactory.training.dataset import mmseg_training_dataset_bundle  # noqa: E402
from maskfactory.training.runtime import probe_openmmlab_runtime  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(*, mmcv_source: Path) -> dict[str, object]:
    runtime = probe_openmmlab_runtime(ROOT / "env" / "openmmlab_training_stack.lock.json")
    if not runtime.ready:
        raise RuntimeError(f"OpenMMLab training doctor failed: {runtime.issues}")

    with tempfile.TemporaryDirectory(prefix="maskfactory_mmseg_live_") as temporary:
        dataset_root = Path(temporary)
        (dataset_root / "part_seg" / "images").mkdir(parents=True)
        (dataset_root / "part_seg" / "annotations").mkdir(parents=True)
        image = np.zeros((96, 80, 3), dtype=np.uint8)
        image[..., 0], image[..., 1], image[..., 2] = 31, 127, 223
        labels = np.zeros((96, 80), dtype=np.uint8)
        labels[16:80, 20:60] = 1
        labels[40:56, 32:48] = 24
        Image.fromarray(image).save(dataset_root / "part_seg" / "images" / "live.png")
        Image.fromarray(labels).save(dataset_root / "part_seg" / "annotations" / "live.png")
        (dataset_root / "train.txt").write_text("live\n", encoding="utf-8")

        training_config = yaml.safe_load(
            (ROOT / "configs" / "training" / "bodypart_segformer_b3.yaml").read_text(
                encoding="utf-8"
            )
        )
        bundle = mmseg_training_dataset_bundle(dataset_root, "train", "part", training_config)
        dataset = DATASETS.build(bundle["dataset"])
        sample = dataset[0]
        inputs = sample["inputs"]
        ground_truth = sample["data_samples"].gt_sem_seg.data

    boxes = torch.tensor(
        [[0.0, 0.0, 10.0, 10.0], [1.0, 1.0, 9.0, 9.0], [20.0, 20.0, 30.0, 30.0]],
        device="cuda",
    )
    scores = torch.tensor([0.9, 0.8, 0.7], device="cuda")
    detections, keep = nms(boxes, scores, 0.5)
    torch.cuda.synchronize()

    pipeline = [record["type"] for record in bundle["dataset"]["pipeline"]]
    expected_pipeline = [
        "LoadImageFromFile",
        "mmseg.LoadAnnotations",
        "mmseg.MaskFactoryRandomResizedCrop",
        "mmseg.MaskFactoryHorizontalFlip",
        "mmseg.MaskFactoryPhotometricJitter",
        "mmseg.MaskFactoryRotate",
        "mmseg.PackSegInputs",
    ]
    if list(inputs.shape) != [3, 512, 512] or list(ground_truth.shape) != [1, 512, 512]:
        raise RuntimeError("live BaseSegDataset sample has the wrong transformed geometry")
    if pipeline != expected_pipeline:
        raise RuntimeError("live BaseSegDataset did not use the governed transform pipeline")
    if str(detections.device) != "cuda:0" or keep.cpu().tolist() != [0, 2]:
        raise RuntimeError("MMCV CUDA NMS produced an unexpected result")

    extension = Path(mmcv._ext.__file__).resolve()
    source_commit = subprocess.check_output(
        ["git", "-C", str(mmcv_source), "rev-parse", "HEAD"], text=True
    ).strip()
    return {
        "schema_version": "1.0.0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "outcome": "pass",
        "runtime": runtime.as_dict(),
        "versions": {
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "mmcv": mmcv.__version__,
            "mmengine": mmengine.__version__,
            "mmsegmentation": mmseg.__version__,
            "mmdet": mmdet.__version__,
        },
        "cuda": {
            "device": torch.cuda.get_device_name(0),
            "capability": list(torch.cuda.get_device_capability(0)),
        },
        "mmcv": {
            "source_commit": source_commit,
            "extension_path": str(extension),
            "extension_sha256": _sha256(extension),
            "cuda_nms": {
                "device": str(detections.device),
                "keep": keep.cpu().tolist(),
                "detections": int(detections.shape[0]),
            },
        },
        "dataset": {
            "class": type(dataset).__name__,
            "length": len(dataset),
            "inputs_shape": list(inputs.shape),
            "ground_truth_shape": list(ground_truth.shape),
            "ground_truth_values": sorted(
                int(value) for value in torch.unique(ground_truth).tolist()
            ),
            "ignore_index": int(dataset.ignore_index),
            "reduce_zero_label": bool(dataset.reduce_zero_label),
            "pipeline": pipeline,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mmcv-source", default="/home/kevin/mfwork/source/mmcv-2.1.0", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    document = verify(mmcv_source=args.mmcv_source)
    rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(args.output)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
