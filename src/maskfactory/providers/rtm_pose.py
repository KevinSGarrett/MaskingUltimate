"""Governed RTMW-X and RTMO crowded-pose shadow providers."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .contracts import BoxProposal, PoseProvider, ProviderIdentity

ROOT = Path(__file__).resolve().parents[3]
RTM_SOURCE_COMMIT = "5408bc76f5b848cf925a0d1857899011d8c5b497"
RTM_RUNTIME_FINGERPRINT = "0e5374ea0427e07891e87219e9f207e72a2c668fbf47aa9427bdbe728a8deee9"
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
RTM_VARIANTS = {
    "rtmw_x": {
        "checkpoint_sha256": "f840f2044fe46cb3821b7cea86be83e1f6cba406ccd28f5475ac010412dcda95",
        "config_sha256": "3317ddf7b9ad9d8046422254b8549276e25c07170e02e5d1ccad09c0cf8a3623",
        "joint_vocabulary": COCO_WHOLEBODY_NAMES,
        "confidence_transform": "native_score/(1+native_score)",
    },
    "rtmo_crowd": {
        "checkpoint_sha256": "5bafdc11e43fba1a834e1323013108831b3e1e0761681dbe7a37896a179f2183",
        "config_sha256": "0360c8a3e085f1a8958833df44310b7e132946cf400f51834f48387e5b7eb957",
        "joint_vocabulary": CROWDPOSE_NAMES,
        "confidence_transform": "native_probability_clipped_0_1",
    },
}

CommandExecutor = Callable[[Sequence[str], int], subprocess.CompletedProcess[str]]


class RtmPoseProviderError(RuntimeError):
    """The isolated RTM process or its pose provenance violated the contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_command(argv: Sequence[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - exact governed argv, never shell=True
        list(argv),
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )


def _last_json_object(stdout: str) -> Mapping[str, Any]:
    for line in reversed(stdout.splitlines()):
        if not line.lstrip().startswith("{"):
            continue
        try:
            document = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(document, Mapping):
            return document
    raise RtmPoseProviderError("RTM pose process emitted no JSON report")


def _box_iou(first: Sequence[float], second: Sequence[float]) -> float:
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


class RtmPoseProvider:
    """Execute one frozen RTM pose challenger behind ``PoseProvider``.

    Anatomical left/right labels are always character-side semantics. RTMO
    returns a globally detected candidate set and binds the requested person by
    maximum box IoU; its stable candidate key prevents silent identity collapse
    when the same crowded image is queried for multiple people.
    """

    def __init__(
        self,
        variant: str,
        *,
        runtime_python: Path | str = Path("C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe"),
        timeout_seconds: int = 180,
        crowd_assignment_iou: float = 0.05,
        fallback: PoseProvider | None = None,
        executor: CommandExecutor = _run_command,
    ) -> None:
        if variant not in RTM_VARIANTS:
            raise ValueError(f"unknown governed RTM variant: {variant}")
        if timeout_seconds < 1:
            raise ValueError("RTM timeout must be positive")
        if not 0 <= crowd_assignment_iou <= 1:
            raise ValueError("RTMO assignment IoU must be in 0..1")
        self.variant = variant
        self.identity = ProviderIdentity(
            provider_key=variant,
            role="pose_provider",
            model_family="rtmpose",
            source_commit=RTM_SOURCE_COMMIT,
            runtime_fingerprint=RTM_RUNTIME_FINGERPRINT,
        )
        self.runtime_python = str(runtime_python)
        self.timeout_seconds = timeout_seconds
        self.crowd_assignment_iou = crowd_assignment_iou
        self.fallback = fallback
        self._executor = executor

    def infer_pose(self, image_path: Path, *, person_box: BoxProposal) -> Mapping[str, Any]:
        try:
            return self._infer(Path(image_path), person_box=person_box)
        except (RtmPoseProviderError, subprocess.TimeoutExpired):
            if self.fallback is None:
                raise
            return self.fallback.infer_pose(Path(image_path), person_box=person_box)

    def _infer(self, image_path: Path, *, person_box: BoxProposal) -> Mapping[str, Any]:
        if not image_path.is_file():
            raise RtmPoseProviderError(f"RTM pose input image is missing: {image_path}")
        with tempfile.TemporaryDirectory(prefix="maskfactory-rtm-pose-") as directory:
            output_path = Path(directory) / "pose.npz"
            argv = (
                self.runtime_python,
                str(ROOT / "tools" / "run_rtm_pose.py"),
                "--variant",
                self.variant,
                "--image",
                str(image_path.resolve()),
                "--person-box",
                *(str(value) for value in person_box.bbox_xyxy),
                "--output",
                str(output_path),
                "--repeats",
                "2",
            )
            try:
                completed = self._executor(argv, self.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                raise RtmPoseProviderError(
                    f"RTM pose exceeded {self.timeout_seconds}s timeout"
                ) from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "no process output").strip()
                raise RtmPoseProviderError(
                    f"RTM pose process failed with exit {completed.returncode}: {detail[-1000:]}"
                )
            report = _last_json_object(completed.stdout)
            return self._validate_report(
                report,
                output_path=output_path,
                image_path=image_path,
                person_box=person_box,
            )

    def _validate_report(
        self,
        report: Mapping[str, Any],
        *,
        output_path: Path,
        image_path: Path,
        person_box: BoxProposal,
    ) -> Mapping[str, Any]:
        spec = RTM_VARIANTS[self.variant]
        checkpoint, config, image = (
            report.get("checkpoint"),
            report.get("config"),
            report.get("image"),
        )
        if (
            report.get("variant") != self.variant
            or report.get("source_commit") != RTM_SOURCE_COMMIT
            or report.get("runtime_fingerprint") != RTM_RUNTIME_FINGERPRINT
        ):
            raise RtmPoseProviderError("RTM pose source/runtime provenance mismatch")
        if (
            not isinstance(checkpoint, Mapping)
            or checkpoint.get("sha256") != spec["checkpoint_sha256"]
        ):
            raise RtmPoseProviderError("RTM pose checkpoint SHA-256 mismatch")
        if not isinstance(config, Mapping) or config.get("sha256") != spec["config_sha256"]:
            raise RtmPoseProviderError("RTM pose config SHA-256 mismatch")
        if not isinstance(image, Mapping) or image.get("sha256") != _sha256(image_path):
            raise RtmPoseProviderError("RTM pose input image SHA-256 mismatch")
        if report.get("deterministic") is not True or report.get("repeats") != 2:
            raise RtmPoseProviderError("RTM pose output lacks two-run determinism proof")
        reported_box = report.get("person_box_xyxy")
        if (
            not isinstance(reported_box, list)
            or len(reported_box) != 4
            or not all(
                math.isclose(float(actual), expected, abs_tol=1e-9)
                for actual, expected in zip(reported_box, person_box.bbox_xyxy, strict=True)
            )
        ):
            raise RtmPoseProviderError("RTM pose person-box provenance mismatch")
        vocabulary = spec["joint_vocabulary"]
        if report.get("joint_vocabulary") != list(vocabulary):
            raise RtmPoseProviderError("RTM pose joint vocabulary mismatch")
        if report.get("confidence_transform") != spec["confidence_transform"]:
            raise RtmPoseProviderError("RTM pose confidence transform mismatch")
        if not output_path.is_file() or report.get("output_npz_sha256") != _sha256(output_path):
            raise RtmPoseProviderError("RTM pose artifact SHA-256 mismatch")
        try:
            with np.load(output_path, allow_pickle=False) as archive:
                keypoints = np.asarray(archive["keypoints"], dtype=np.float32)
                confidence = np.asarray(archive["confidence"], dtype=np.float32)
                native_scores = np.asarray(archive["native_scores"], dtype=np.float32)
                boxes = np.asarray(archive["bboxes"], dtype=np.float32)
        except (KeyError, OSError, ValueError) as exc:
            raise RtmPoseProviderError("RTM pose artifact is unreadable") from exc
        joint_count = len(vocabulary)
        if (
            keypoints.ndim != 3
            or keypoints.shape[1:] != (joint_count, 2)
            or confidence.shape != keypoints.shape[:2]
            or native_scores.shape != confidence.shape
            or boxes.shape != (len(keypoints), 4)
        ):
            raise RtmPoseProviderError("RTM pose artifact shape mismatch")
        if report.get("person_count") != len(keypoints) or report.get("keypoints_shape") != list(
            keypoints.shape
        ):
            raise RtmPoseProviderError("RTM pose report shape/count mismatch")
        arrays = (keypoints, native_scores, boxes)
        if hashlib.sha256(b"".join(array.tobytes() for array in arrays)).hexdigest() != report.get(
            "payload_sha256"
        ):
            raise RtmPoseProviderError("RTM pose payload hash mismatch")
        if not all(np.isfinite(array).all() for array in (*arrays, confidence)):
            raise RtmPoseProviderError("RTM pose artifact contains non-finite values")
        if confidence.min(initial=0) < 0 or confidence.max(initial=0) > 1:
            raise RtmPoseProviderError("RTM pose confidence must be in 0..1")
        if not len(keypoints):
            raise RtmPoseProviderError("RTM pose returned no candidates")

        if self.variant == "rtmw_x":
            if len(keypoints) != 1:
                raise RtmPoseProviderError("RTMW-X must return one requested person")
            selected_index, assignment_iou = 0, 1.0
        else:
            ious = np.asarray(
                [_box_iou(box, person_box.bbox_xyxy) for box in boxes], dtype=np.float64
            )
            selected_index = int(np.argmax(ious))
            assignment_iou = float(ious[selected_index])
            if assignment_iou < self.crowd_assignment_iou:
                raise RtmPoseProviderError(
                    "RTMO crowd candidates do not overlap the requested person"
                )
        selected_box = tuple(float(value) for value in boxes[selected_index])
        instance_key = hashlib.sha256(
            json.dumps(
                {"provider": self.variant, "bbox_xyxy": selected_box},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()[:24]
        points = np.column_stack((keypoints[selected_index], confidence[selected_index])).astype(
            np.float32
        )
        side_indices = {
            name: index
            for index, name in enumerate(vocabulary)
            if name.startswith(("left_", "right_"))
        }
        return {
            "provider_key": self.identity.provider_key,
            "model_family": self.identity.model_family,
            "source_commit": self.identity.source_commit,
            "runtime_fingerprint": self.identity.runtime_fingerprint,
            "variant": self.variant,
            "joint_vocabulary": tuple(vocabulary),
            "keypoints": points,
            "native_scores": native_scores[selected_index].copy(),
            "candidate_bbox_xyxy": selected_box,
            "requested_bbox_xyxy": person_box.bbox_xyxy,
            "selected_candidate_index": selected_index,
            "candidate_count": len(keypoints),
            "candidate_boxes_xyxy": boxes.copy(),
            "assignment_iou": assignment_iou,
            "instance_key": f"{self.variant}:{instance_key}",
            "side_semantics": "character_anatomical_left_right",
            "character_side_indices": side_indices,
            "confidence_transform": spec["confidence_transform"],
            "authority": "shadow_challenger_only",
        }


__all__ = [
    "COCO_WHOLEBODY_NAMES",
    "CROWDPOSE_NAMES",
    "RTM_RUNTIME_FINGERPRINT",
    "RTM_SOURCE_COMMIT",
    "RTM_VARIANTS",
    "RtmPoseProvider",
    "RtmPoseProviderError",
]
