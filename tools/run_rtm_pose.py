from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT / "models" / "runtime_cache" / "rtm_pose_deps"
SOURCE = ROOT / "models" / "runtime_cache" / "mmpose_v1.3.2"
sys.path[:0] = [str(DEPS), str(SOURCE)]

# These two models do not use the compiled MMCV deformable-attention op.  The
# signed MMPose release imports the unrelated EDPose head eagerly, so isolate
# only that unavailable optional head without changing the source checkout.
stub = types.ModuleType("mmpose.models.heads.transformer_heads")
stub.EDPoseHead = type("UnavailableEDPoseHead", (), {})
sys.modules[stub.__name__] = stub

import numpy as np  # noqa: E402
import torch  # noqa: E402
from mmpose.apis import inference_bottomup, inference_topdown, init_model  # noqa: E402

SOURCE_COMMIT = "5408bc76f5b848cf925a0d1857899011d8c5b497"
RUNTIME_FINGERPRINT = "0e5374ea0427e07891e87219e9f207e72a2c668fbf47aa9427bdbe728a8deee9"
COCO_WHOLEBODY_NAMES = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_big_toe",
    "left_small_toe",
    "left_heel",
    "right_big_toe",
    "right_small_toe",
    "right_heel",
    *(f"face_{index}" for index in range(68)),
    *(f"left_hand_{index}" for index in range(21)),
    *(f"right_hand_{index}" for index in range(21)),
)
CROWDPOSE_NAMES = (
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "top_head",
    "neck",
)
VARIANTS = {
    "rtmw_x": {
        "config": SOURCE / "projects/rtmpose/rtmpose/wholebody_2d_keypoint/"
        "rtmw-x_8xb320-270e_cocktail14-384x288.py",
        "checkpoint": ROOT / "models/pose/rtm/"
        "rtmw-x_simcc-cocktail14_pt-ucoco_270e-384x288-f840f204_20231122.pth",
        "checkpoint_sha256": "f840f2044fe46cb3821b7cea86be83e1f6cba406ccd28f5475ac010412dcda95",
        "names": COCO_WHOLEBODY_NAMES,
        "mode": "topdown",
        "confidence_transform": "native_score/(1+native_score)",
    },
    "rtmo_crowd": {
        "config": SOURCE / "configs/body_2d_keypoint/rtmo/crowdpose/"
        "rtmo-l_16xb16-700e_body7-crowdpose-640x640.py",
        "checkpoint": ROOT / "models/pose/rtm/"
        "rtmo-l_16xb16-700e_body7-crowdpose-640x640-5bafdc11_20231219.pth",
        "checkpoint_sha256": "5bafdc11e43fba1a834e1323013108831b3e1e0761681dbe7a37896a179f2183",
        "names": CROWDPOSE_NAMES,
        "mode": "bottomup",
        "confidence_transform": "native_probability_clipped_0_1",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _arrays(result, expected_joints: int, *, fallback_box) -> tuple[np.ndarray, ...]:
    if len(result) != 1:
        raise RuntimeError("pose inference must return one image result")
    instances = result[0].pred_instances
    keypoints = np.asarray(instances.keypoints, dtype=np.float32)
    native_scores = np.asarray(instances.keypoint_scores, dtype=np.float32)
    if keypoints.ndim != 3 or keypoints.shape[1:] != (expected_joints, 2):
        raise RuntimeError(f"unexpected keypoint shape: {keypoints.shape}")
    if native_scores.shape != keypoints.shape[:2]:
        raise RuntimeError(f"unexpected score shape: {native_scores.shape}")
    if hasattr(instances, "bboxes"):
        boxes = np.asarray(instances.bboxes, dtype=np.float32)
    elif fallback_box is not None:
        boxes = np.repeat(np.asarray(fallback_box, dtype=np.float32)[None, :], len(keypoints), 0)
    else:
        raise RuntimeError("crowd pose output is missing candidate boxes")
    if boxes.shape != (len(keypoints), 4):
        raise RuntimeError(f"unexpected candidate box shape: {boxes.shape}")
    if not all(np.isfinite(array).all() for array in (keypoints, native_scores, boxes)):
        raise RuntimeError("pose output contains non-finite values")
    if native_scores.min(initial=0) < 0:
        raise RuntimeError("pose output contains negative native scores")
    if np.any(boxes[:, 2] <= boxes[:, 0]) or np.any(boxes[:, 3] <= boxes[:, 1]):
        raise RuntimeError("pose output contains a non-positive candidate box")
    return keypoints, native_scores, boxes


def _payload_hash(arrays: tuple[np.ndarray, ...]) -> str:
    digest = hashlib.sha256()
    for array in arrays:
        digest.update(array.tobytes())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=sorted(VARIANTS), required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--person-box", type=float, nargs=4)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    if not args.image.is_file():
        raise FileNotFoundError(args.image)
    if args.repeats != 2:
        raise ValueError("governed RTM runner requires exactly two repeats")
    spec = VARIANTS[args.variant]
    if spec["mode"] == "topdown" and args.person_box is None:
        raise ValueError("RTMW-X requires --person-box")
    checkpoint = Path(spec["checkpoint"])
    if _sha256(checkpoint) != spec["checkpoint_sha256"]:
        raise RuntimeError("refusing RTM checkpoint with an unexpected SHA-256")
    if not torch.cuda.is_available():
        raise RuntimeError("RTM pose runtime requires CUDA")

    # PyTorch 2.6 defaults weights_only=True, while these exact official
    # checkpoints include NumPy metadata. Restore the legacy setting only
    # after the allowlisted checkpoint hash above passes.
    original_torch_load = torch.load

    def trusted_torch_load(*load_args, **load_kwargs):
        load_kwargs.setdefault("weights_only", False)
        return original_torch_load(*load_args, **load_kwargs)

    torch.load = trusted_torch_load
    np.random.seed(0)
    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    load_started = time.perf_counter()
    model = init_model(str(spec["config"]), str(checkpoint), device="cuda:0")
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - load_started

    calls: list[tuple[np.ndarray, ...]] = []
    latencies = []
    for _ in range(args.repeats):
        started = time.perf_counter()
        if spec["mode"] == "topdown":
            bboxes = np.asarray([args.person_box], dtype=np.float32)
            result = inference_topdown(model, str(args.image), bboxes=bboxes, bbox_format="xyxy")
        else:
            result = inference_bottomup(model, str(args.image))
        torch.cuda.synchronize()
        calls.append(
            _arrays(
                result,
                len(spec["names"]),
                fallback_box=args.person_box,
            )
        )
        latencies.append(time.perf_counter() - started)
    hashes = [_payload_hash(call) for call in calls]
    if len(set(hashes)) != 1:
        raise RuntimeError("RTM pose output is nondeterministic across two repeats")
    keypoints, native_scores, boxes = calls[-1]
    if spec["mode"] == "topdown":
        confidence = native_scores / (1.0 + native_scores)
    else:
        confidence = np.clip(native_scores, 0.0, 1.0)
    confidence = np.asarray(confidence, dtype=np.float32)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        keypoints=keypoints,
        confidence=confidence,
        native_scores=native_scores,
        bboxes=boxes,
    )
    report = {
        "schema_version": "1.0.0",
        "variant": args.variant,
        "source_commit": SOURCE_COMMIT,
        "runtime_fingerprint": RUNTIME_FINGERPRINT,
        "checkpoint": {
            "path": checkpoint.relative_to(ROOT).as_posix(),
            "sha256": spec["checkpoint_sha256"],
        },
        "config": {
            "path": Path(spec["config"]).relative_to(ROOT).as_posix(),
            "sha256": _sha256(Path(spec["config"])),
        },
        "image": {"path": str(args.image.resolve()), "sha256": _sha256(args.image)},
        "person_box_xyxy": args.person_box,
        "joint_vocabulary": list(spec["names"]),
        "joint_count": len(spec["names"]),
        "person_count": len(keypoints),
        "keypoints_shape": list(keypoints.shape),
        "confidence_shape": list(confidence.shape),
        "bboxes_shape": list(boxes.shape),
        "native_score_range": [float(native_scores.min()), float(native_scores.max())],
        "confidence_range": [float(confidence.min()), float(confidence.max())],
        "confidence_transform": spec["confidence_transform"],
        "payload_sha256": hashes[-1],
        "output_npz_sha256": _sha256(args.output),
        "deterministic": True,
        "repeats": args.repeats,
        "load_seconds": round(load_seconds, 6),
        "inference_seconds": [round(value, 6) for value in latencies],
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        "device": torch.cuda.get_device_name(0),
        "authority": "shadow_challenger_only",
    }
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
