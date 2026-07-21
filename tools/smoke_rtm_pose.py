from __future__ import annotations

import hashlib
import json
import sys
import time
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT / "models" / "runtime_cache" / "rtm_pose_deps"
SOURCE = ROOT / "models" / "runtime_cache" / "mmpose_v1.3.2"
sys.path[:0] = [str(DEPS), str(SOURCE)]

# RTMW/RTMO use no compiled MMCV ops. MMPose 1.3.2 imports the unrelated
# EDPose head eagerly, so isolate that unavailable optional head without
# changing the signed source tree.
stub = types.ModuleType("mmpose.models.heads.transformer_heads")
stub.EDPoseHead = type("UnavailableEDPoseHead", (), {})
sys.modules[stub.__name__] = stub

import mmcv  # noqa: E402
import mmdet  # noqa: E402
import mmengine  # noqa: E402
import mmpose  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
from mmpose.apis import inference_bottomup, inference_topdown, init_model  # noqa: E402

# PyTorch 2.6 changed torch.load's default to weights_only=True, while these
# immutable official OpenMMLab checkpoints include NumPy metadata.  MMEngine
# 0.10 does not pass an explicit value.  After the exact SHA-256 checks in
# main(), this process-local wrapper restores the legacy behavior solely for
# the two trusted checkpoint loads.
_torch_load = torch.load


def _trusted_torch_load(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _torch_load(*args, **kwargs)


FIXTURE = ROOT / "qa" / "fixtures" / "smoke" / "ultralytics_bus_adults.jpg"
OUTPUT = ROOT / "qa" / "live_verification" / "rtm_pose_runtime_20260714.json"
RTMW_CONFIG = (
    SOURCE
    / "projects"
    / "rtmpose"
    / "rtmpose"
    / "wholebody_2d_keypoint"
    / "rtmw-x_8xb320-270e_cocktail14-384x288.py"
)
RTMW_CHECKPOINT = (
    ROOT
    / "models"
    / "pose"
    / "rtm"
    / "rtmw-x_simcc-cocktail14_pt-ucoco_270e-384x288-f840f204_20231122.pth"
)
RTMO_CONFIG = (
    SOURCE
    / "configs"
    / "body_2d_keypoint"
    / "rtmo"
    / "crowdpose"
    / "rtmo-l_16xb16-700e_body7-crowdpose-640x640.py"
)
RTMO_CHECKPOINT = (
    ROOT
    / "models"
    / "pose"
    / "rtm"
    / "rtmo-l_16xb16-700e_body7-crowdpose-640x640-5bafdc11_20231219.pth"
)
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prediction_arrays(results, expected_keypoints: int) -> tuple[np.ndarray, np.ndarray]:
    if len(results) != 1:
        raise RuntimeError("pose inference must return exactly one image result")
    instances = results[0].pred_instances
    keypoints = np.asarray(instances.keypoints, dtype=np.float32)
    scores = np.asarray(instances.keypoint_scores, dtype=np.float32)
    if keypoints.ndim != 3 or keypoints.shape[1:] != (expected_keypoints, 2):
        raise RuntimeError(f"unexpected pose keypoint shape: {keypoints.shape}")
    if scores.shape != keypoints.shape[:2]:
        raise RuntimeError(f"unexpected pose score shape: {scores.shape}")
    if not np.isfinite(keypoints).all() or not np.isfinite(scores).all():
        raise RuntimeError("pose output must be finite")
    # RTMW-X's signed official config deliberately sets SimCCLabel
    # normalize=False, so keypoint_scores are non-negative SimCC response
    # magnitudes rather than probabilities.  Preserve that native evidence;
    # provider-facing confidence normalization is a separate contract step.
    if scores.min(initial=0) < 0:
        raise RuntimeError(
            "pose scores must be non-negative: "
            f"min={scores.min(initial=0)!r} max={scores.max(initial=0)!r}"
        )
    return keypoints, scores


def _record(
    *,
    model,
    load_seconds: float,
    calls: list[tuple[np.ndarray, np.ndarray, float]],
    keypoint_names: tuple[str, ...],
    checkpoint: Path,
    config: Path,
) -> dict[str, Any]:
    keypoints, scores, _ = calls[-1]
    payload_hashes = [
        hashlib.sha256(points.tobytes() + confidence.tobytes()).hexdigest()
        for points, confidence, _ in calls
    ]
    if len(set(payload_hashes)) != 1:
        raise RuntimeError("pose output is nondeterministic across two repeats")
    if len(keypoint_names) != keypoints.shape[1]:
        raise RuntimeError("pose keypoint vocabulary length mismatch")
    return {
        "checkpoint": {
            "path": checkpoint.relative_to(ROOT).as_posix(),
            "bytes": checkpoint.stat().st_size,
            "sha256": _sha256(checkpoint),
        },
        "config": {
            "path": config.relative_to(ROOT).as_posix(),
            "sha256": _sha256(config),
        },
        "joint_vocabulary": list(keypoint_names),
        "joint_count": len(keypoint_names),
        "person_count": int(keypoints.shape[0]),
        "keypoints_shape": list(keypoints.shape),
        "scores_shape": list(scores.shape),
        "payload_sha256": payload_hashes[-1],
        "deterministic": True,
        "repeats": 2,
        "load_seconds": round(load_seconds, 6),
        "inference_seconds": [round(call[2], 6) for call in calls],
        "confident_joint_fraction_0_3": float((scores >= 0.3).mean()),
        "native_score_range": [float(scores.min()), float(scores.max())],
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        "dataset_meta_keypoints": list(model.dataset_meta["keypoint_id2name"].values()),
    }


def main() -> int:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    expected_hashes = {
        RTMW_CHECKPOINT: "f840f2044fe46cb3821b7cea86be83e1f6cba406ccd28f5475ac010412dcda95",
        RTMO_CHECKPOINT: "5bafdc11e43fba1a834e1323013108831b3e1e0761681dbe7a37896a179f2183",
    }
    for checkpoint, expected_hash in expected_hashes.items():
        actual_hash = _sha256(checkpoint)
        if actual_hash != expected_hash:
            raise RuntimeError(f"refusing untrusted checkpoint {checkpoint}: {actual_hash}")
    torch.load = _trusted_torch_load
    np.random.seed(0)
    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    records: dict[str, Any] = {}

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    rtmw = init_model(str(RTMW_CONFIG), str(RTMW_CHECKPOINT), device="cuda:0")
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - started
    rtmw_calls = []
    bbox = np.asarray([[49.75, 398.25, 247.625, 905.5]], dtype=np.float32)
    for _ in range(2):
        started = time.perf_counter()
        output = inference_topdown(rtmw, str(FIXTURE), bboxes=bbox, bbox_format="xyxy")
        torch.cuda.synchronize()
        points, scores = _prediction_arrays(output, 133)
        rtmw_calls.append((points, scores, time.perf_counter() - started))
    records["rtmw_x"] = _record(
        model=rtmw,
        load_seconds=load_seconds,
        calls=rtmw_calls,
        keypoint_names=COCO_WHOLEBODY_NAMES,
        checkpoint=RTMW_CHECKPOINT,
        config=RTMW_CONFIG,
    )
    del rtmw
    torch.cuda.empty_cache()

    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    rtmo = init_model(str(RTMO_CONFIG), str(RTMO_CHECKPOINT), device="cuda:0")
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - started
    rtmo_calls = []
    for _ in range(2):
        started = time.perf_counter()
        output = inference_bottomup(rtmo, str(FIXTURE))
        torch.cuda.synchronize()
        points, scores = _prediction_arrays(output, 14)
        rtmo_calls.append((points, scores, time.perf_counter() - started))
    records["rtmo_crowd"] = _record(
        model=rtmo,
        load_seconds=load_seconds,
        calls=rtmo_calls,
        keypoint_names=CROWDPOSE_NAMES,
        checkpoint=RTMO_CHECKPOINT,
        config=RTMO_CONFIG,
    )

    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "captured_at": datetime.now(UTC).isoformat(),
        "result": "pass",
        "fixture": {
            "path": FIXTURE.relative_to(ROOT).as_posix(),
            "sha256": _sha256(FIXTURE),
            "rtmw_person_box_xyxy": bbox[0].tolist(),
        },
        "source": {
            "mmpose_commit": "5408bc76f5b848cf925a0d1857899011d8c5b497",
            "mmpose_tree": "592d7336c9dd65a3f19f96c8bbcf0956bcf97426",
            "mmpose_version": mmpose.__version__,
            "mmpose_license_sha256": _sha256(SOURCE / "LICENSE"),
        },
        "runtime": {
            "python": sys.executable,
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "device": torch.cuda.get_device_name(0),
            "capability": list(torch.cuda.get_device_capability(0)),
            "numpy": np.__version__,
            "mmcv_lite": mmcv.__version__,
            "mmengine": mmengine.__version__,
            "mmdet": mmdet.__version__,
            "optional_compiled_heads_disabled": ["EDPoseHead"],
        },
        "variants": records,
        "authority": {
            "lifecycle_state": "installed",
            "shadow_only": True,
            "active": "dwpose_133",
            "independent_vote": "mediapipe_hands",
            "promotion_claimed": False,
        },
    }
    document["sha256"] = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
