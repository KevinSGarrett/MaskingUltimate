"""Fail-closed validation helpers for the governed P2 S01/S02 truth fixtures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


class P2FixtureError(ValueError):
    """A P2 fixture or captured result violates its acceptance contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bbox_iou(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> float:
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def binary_mask_iou(prediction_path: Path, truth_path: Path) -> float:
    with Image.open(prediction_path) as opened:
        prediction = np.asarray(opened) != 0
    with Image.open(truth_path) as opened:
        truth = np.asarray(opened) != 0
    if prediction.shape != truth.shape:
        raise P2FixtureError(
            f"prediction/truth shape mismatch: {prediction.shape} != {truth.shape}"
        )
    union = np.logical_or(prediction, truth).sum()
    return float(np.logical_and(prediction, truth).sum() / union) if union else 0.0


def load_and_validate_fixture_manifest(path: Path, dataset_root: Path) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema_version") != "1.0.0":
        raise P2FixtureError("fixture manifest schema_version must be 1.0.0")
    if document.get("dataset_key") != "lv_mhp_v1":
        raise P2FixtureError("fixture manifest must identify the governed lv_mhp_v1 source")
    if document.get("use_scope") != "local_non_distributable_research_qc_fixture":
        raise P2FixtureError("fixture manifest use scope is not authorized")
    if document.get("external_masks_are_gold") is not False:
        raise P2FixtureError("external truth masks must be explicitly declared non-gold")
    records = document.get("records")
    if not isinstance(records, list) or len(records) != 10:
        raise P2FixtureError("the P2 acceptance set must contain exactly 10 records")
    identifiers: set[str] = set()
    root = Path(dataset_root).resolve()
    for record in records:
        identifier = record.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise P2FixtureError("fixture ids must be non-empty and unique")
        identifiers.add(identifier)
        if record.get("visual_alignment_review") != "pass":
            raise P2FixtureError(f"{identifier}: visual alignment review is not passed")
        for rel_key, hash_key in (
            ("source_relpath", "source_sha256"),
            ("truth_mask_relpath", "truth_mask_sha256"),
        ):
            candidate = (root / record[rel_key]).resolve()
            if root not in candidate.parents:
                raise P2FixtureError(f"{identifier}: {rel_key} escapes the dataset root")
            if not candidate.is_file():
                raise P2FixtureError(f"{identifier}: missing {candidate}")
            if sha256_file(candidate) != record.get(hash_key):
                raise P2FixtureError(f"{identifier}: {hash_key} mismatch")
        bbox = record.get("truth_bbox_xyxy")
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or not all(isinstance(v, int) for v in bbox)
        ):
            raise P2FixtureError(f"{identifier}: invalid truth_bbox_xyxy")
    return document


def assert_acceptance(results: list[dict[str, Any]], threshold: float = 0.95) -> None:
    if len(results) != 10:
        raise P2FixtureError("acceptance requires exactly 10 evaluated fixtures")
    failures = [
        result["id"]
        for result in results
        if result.get("bbox_iou", 0.0) < threshold or result.get("silhouette_iou", 0.0) < threshold
    ]
    if failures:
        raise P2FixtureError(f"P2 IoU threshold failure: {', '.join(failures)}")
