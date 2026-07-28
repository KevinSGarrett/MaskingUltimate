"""Governed RF-DETR Medium person-detector shadow adapter."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .contracts import BoxProposal, ProviderIdentity

ROOT = Path(__file__).resolve().parents[3]
RFDETR_SOURCE_REVISION = "6e1620e751f3c814ead8648cada51ceff9029e5c"
RFDETR_CHECKPOINT_SHA256 = "749ff6071828aaffac63e204c4f4135ed3d6cdae4d702e086c360edc3b5768c8"
RFDETR_RUNTIME_FINGERPRINT = "5ab1da8e03134bb26fbbaabbabe11c52470c91be785b1628505bf47cfd0c6887"
RFDETR_VERSION = "1.7.1"

CommandExecutor = Callable[[Sequence[str], int], subprocess.CompletedProcess[str]]


class RfdetrProviderError(RuntimeError):
    """The isolated RF-DETR process or its provenance violated the contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def windows_to_wsl_path(path: Path) -> str:
    """Map a local drive path to its stable WSL mount path."""
    resolved = Path(path).resolve(strict=False)
    drive = resolved.drive.rstrip(":")
    if len(drive) != 1 or not drive.isalpha():
        raise RfdetrProviderError(f"RF-DETR requires a drive-backed local path: {resolved}")
    suffix = resolved.as_posix()[2:].lstrip("/")
    return f"/mnt/{drive.lower()}/{suffix}"


def _run_command(argv: Sequence[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - exact governed argv, never shell=True
        list(argv),
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )


class RfdetrPersonDetector:
    """Execute the exact RF-DETR Medium runtime behind ``PersonDetector``.

    This adapter has proposal authority only. Provider selection separately
    prevents its installed/shadow lifecycle from becoming the active S01 route.
    """

    identity = ProviderIdentity(
        provider_key="rf_detr_medium",
        role="person_detector",
        model_family="rfdetr",
        source_commit=RFDETR_SOURCE_REVISION,
        runtime_fingerprint=RFDETR_RUNTIME_FINGERPRINT,
    )

    def __init__(
        self,
        *,
        checkpoint: Path = ROOT
        / "models"
        / "runtime_cache"
        / "rfdetr_weights_1.7.1"
        / "rf-detr-medium.pth",
        runtime_python: str = "/home/kevin/mfenvs/rfdetr-1.7.1/bin/python",
        distro: str = "Ubuntu-22.04",
        threshold: float = 0.5,
        timeout_seconds: int = 180,
        executor: CommandExecutor = _run_command,
    ) -> None:
        if not 0 < threshold < 1:
            raise ValueError("RF-DETR threshold must be within 0..1")
        if timeout_seconds < 1:
            raise ValueError("RF-DETR timeout must be positive")
        self.checkpoint = Path(checkpoint)
        self.runtime_python = runtime_python
        self.distro = distro
        self.threshold = threshold
        self.timeout_seconds = timeout_seconds
        self._executor = executor

    def detect_people(self, image_path: Path) -> tuple[BoxProposal, ...]:
        image_path = Path(image_path)
        if not image_path.is_file():
            raise RfdetrProviderError(f"RF-DETR input image is missing: {image_path}")
        if not self.checkpoint.is_file():
            raise RfdetrProviderError(f"RF-DETR checkpoint is missing: {self.checkpoint}")

        argv = (
            "wsl.exe",
            "-d",
            self.distro,
            "--",
            self.runtime_python,
            windows_to_wsl_path(ROOT / "tools" / "smoke_rfdetr_wsl.py"),
            "--checkpoint",
            windows_to_wsl_path(self.checkpoint),
            "--image",
            windows_to_wsl_path(image_path),
            "--threshold",
            str(self.threshold),
            "--repeats",
            "2",
            "--optimize-dtype",
            "float16",
        )
        try:
            completed = self._executor(argv, self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise RfdetrProviderError(f"RF-DETR exceeded {self.timeout_seconds}s timeout") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "no process output").strip()
            raise RfdetrProviderError(
                f"RF-DETR process failed with exit {completed.returncode}: {detail[-1000:]}"
            )
        report = _last_json_object(completed.stdout)
        return _validate_report(report, image_path=image_path, threshold=self.threshold)


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
    raise RfdetrProviderError("RF-DETR process emitted no JSON report")


def _validate_report(
    report: Mapping[str, Any], *, image_path: Path, threshold: float
) -> tuple[BoxProposal, ...]:
    checkpoint = report.get("checkpoint")
    image = report.get("image")
    if not isinstance(checkpoint, Mapping) or (
        checkpoint.get("sha256") != RFDETR_CHECKPOINT_SHA256
    ):
        raise RfdetrProviderError("RF-DETR checkpoint SHA-256 mismatch")
    if report.get("rfdetr") != RFDETR_VERSION:
        raise RfdetrProviderError("RF-DETR runtime version mismatch")
    if report.get("deterministic") is not True or report.get("repeats") != 2:
        raise RfdetrProviderError("RF-DETR output lacks two-run determinism proof")
    if not isinstance(image, Mapping) or image.get("sha256") != _sha256(image_path):
        raise RfdetrProviderError("RF-DETR input image SHA-256 mismatch")
    if not math.isclose(float(report.get("threshold", -1)), threshold, abs_tol=1e-12):
        raise RfdetrProviderError("RF-DETR threshold provenance mismatch")
    detections = report.get("detections")
    if not isinstance(detections, list):
        raise RfdetrProviderError("RF-DETR detections must be an array")

    proposals: list[BoxProposal] = []
    for record in detections:
        if not isinstance(record, Mapping) or record.get("class_name") != "person":
            continue
        bbox = record.get("xyxy")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise RfdetrProviderError("RF-DETR person box must be xyxy[4]")
        try:
            proposal = BoxProposal(
                tuple(float(value) for value in bbox),
                float(record["confidence"]),
                "person",
                f"rf_detr_medium:{len(proposals)}",
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RfdetrProviderError(f"invalid RF-DETR person proposal: {record}") from exc
        if proposal.confidence < threshold:
            raise RfdetrProviderError("RF-DETR returned a person below the requested threshold")
        proposals.append(proposal)
    if report.get("person_count") != len(proposals):
        raise RfdetrProviderError("RF-DETR person count does not match detections")
    if not proposals:
        raise RfdetrProviderError("RF-DETR reported no person proposals")
    return tuple(proposals)


def compare_person_boxes(
    incumbent: Sequence[BoxProposal],
    challenger: Sequence[BoxProposal],
    *,
    match_iou: float = 0.5,
) -> dict[str, Any]:
    """Greedily compare two frozen detection sets without granting authority."""
    if not 0 < match_iou <= 1:
        raise ValueError("match_iou must be within (0, 1]")
    candidates = sorted(
        (
            (_box_iou(left.bbox_xyxy, right.bbox_xyxy), left_index, right_index)
            for left_index, left in enumerate(incumbent)
            for right_index, right in enumerate(challenger)
        ),
        reverse=True,
    )
    used_incumbent: set[int] = set()
    used_challenger: set[int] = set()
    matches: list[dict[str, Any]] = []
    for iou, left_index, right_index in candidates:
        if iou < match_iou:
            break
        if left_index in used_incumbent or right_index in used_challenger:
            continue
        used_incumbent.add(left_index)
        used_challenger.add(right_index)
        matches.append(
            {
                "incumbent_index": left_index,
                "challenger_index": right_index,
                "iou": round(iou, 8),
            }
        )
    mean_iou = sum(match["iou"] for match in matches) / len(matches) if matches else 0.0
    return {
        "authority": "shadow_comparison_only",
        "match_iou_threshold": match_iou,
        "incumbent_count": len(incumbent),
        "challenger_count": len(challenger),
        "matched_count": len(matches),
        "incumbent_recall": len(matches) / len(incumbent) if incumbent else 1.0,
        "challenger_recall": len(matches) / len(challenger) if challenger else 1.0,
        "mean_matched_iou": round(mean_iou, 8),
        "matches": matches,
        "unmatched_incumbent": sorted(set(range(len(incumbent))) - used_incumbent),
        "unmatched_challenger": sorted(set(range(len(challenger))) - used_challenger),
    }


def _box_iou(first: Sequence[float], second: Sequence[float]) -> float:
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


__all__ = [
    "RFDETR_CHECKPOINT_SHA256",
    "RFDETR_RUNTIME_FINGERPRINT",
    "RFDETR_SOURCE_REVISION",
    "RfdetrPersonDetector",
    "RfdetrProviderError",
    "compare_person_boxes",
    "windows_to_wsl_path",
]
