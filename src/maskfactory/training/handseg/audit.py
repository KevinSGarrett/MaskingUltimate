"""Seeded merged-finger audit corpus and strict false-split metric (doc 12 §6.3)."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from ...io.png_strict import write_binary_mask, write_label_map

HAND_CLASSES = (
    "background",
    "left_hand_base",
    "right_hand_base",
    "left_thumb",
    "right_thumb",
    "left_index_finger",
    "right_index_finger",
    "left_middle_finger",
    "right_middle_finger",
    "left_ring_finger",
    "right_ring_finger",
    "left_pinky",
    "right_pinky",
    "finger_occlusion_boundary",
)
CLASS_ID = {name: index for index, name in enumerate(HAND_CLASSES)}
FINGERS = ("thumb", "index_finger", "middle_finger", "ring_finger", "pinky")


class HandAuditError(ValueError):
    """The ambiguous-hand audit corpus or prediction set is invalid."""


def build_ambiguous_hand_audit(
    output_root: Path, *, case_count: int = 100, seed: int = 1337, size: int = 128
) -> Path:
    """Create deterministic known-truth merged-finger cases and their spatial ambiguity masks."""
    if case_count < 100 or size < 64:
        raise HandAuditError("audit requires at least 100 cases and 64px geometry")
    root = Path(output_root)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"ambiguous-hand audit root is not empty: {root}")
    (root / "images").mkdir(parents=True, exist_ok=True)
    (root / "truth").mkdir()
    (root / "ambiguous").mkdir()
    rng = np.random.default_rng(seed)
    cases = []
    for index in range(case_count):
        side = "left" if index % 2 == 0 else "right"
        first_index = index % (len(FINGERS) - 1)
        affected = (FINGERS[first_index], FINGERS[first_index + 1])
        shift_x, shift_y = (int(value) for value in rng.integers(-6, 7, size=2))
        width = int(rng.integers(9, 15))
        gap = int(rng.integers(-3, 2))  # touching/overlap is the known ambiguous condition
        canvas = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(canvas)
        center = size // 2 + shift_x
        top = size // 4 + shift_y
        bottom = 3 * size // 4 + shift_y
        first_left = center - width - max(gap, 0) // 2
        second_left = first_left + width + gap
        draw.rounded_rectangle(
            (first_left, top, first_left + width, bottom), radius=width // 2, fill=255
        )
        draw.rounded_rectangle(
            (second_left, top + 2, second_left + width, bottom), radius=width // 2, fill=255
        )
        ambiguity = np.asarray(canvas).copy() > 0
        truth = np.zeros((size, size), dtype=np.uint8)
        truth[ambiguity] = CLASS_ID[f"{side}_hand_base"]
        noise = rng.normal(90, 12, size=(size, size)).clip(0, 255).astype(np.uint8)
        rgb = np.stack((noise, noise, noise), axis=2)
        rgb[ambiguity] = (180, 145, 125)
        case_id = f"ambiguous_{index:03d}"
        Image.fromarray(rgb, mode="RGB").save(root / "images" / f"{case_id}.png")
        write_label_map(root / "truth" / f"{case_id}.png", truth, bits=8)
        write_binary_mask(root / "ambiguous" / f"{case_id}.png", ambiguity)
        cases.append(
            {
                "case_id": case_id,
                "side": side,
                "affected_fingers": [f"{side}_{name}" for name in affected],
                "truth_class": f"{side}_hand_base",
                "image": f"images/{case_id}.png",
                "truth": f"truth/{case_id}.png",
                "ambiguity_mask": f"ambiguous/{case_id}.png",
            }
        )
    manifest = {
        "schema_version": "1.0.0",
        "seed": seed,
        "case_count": case_count,
        "classes": list(HAND_CLASSES),
        "false_split_rule": "any affected finger-class pixel inside ambiguity_mask",
        "gate": {"operator": "lt", "threshold": 0.02},
        "cases": cases,
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def evaluate_merged_finger_false_splits(
    audit_root: Path, predictions_root: Path
) -> dict[str, object]:
    """Evaluate the exact case-level false-split rate; missing predictions hard-fail."""
    root = Path(audit_root)
    document = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    false_cases = []
    for case in document["cases"]:
        case_id = case["case_id"]
        prediction_path = Path(predictions_root) / f"{case_id}.png"
        if not prediction_path.is_file():
            raise HandAuditError(f"missing ambiguous-hand prediction: {case_id}")
        prediction = np.asarray(Image.open(prediction_path))
        ambiguity = np.asarray(Image.open(root / case["ambiguity_mask"]).convert("L")) > 0
        if prediction.shape != ambiguity.shape:
            raise HandAuditError(f"prediction dimensions differ: {case_id}")
        unknown = set(np.unique(prediction).tolist()) - set(range(len(HAND_CLASSES))) - {255}
        if unknown:
            raise HandAuditError(f"prediction has unknown hand class IDs: {sorted(unknown)}")
        affected_ids = {CLASS_ID[name] for name in case["affected_fingers"]}
        if np.isin(prediction[ambiguity], tuple(affected_ids)).any():
            false_cases.append(case_id)
    case_count = int(document["case_count"])
    rate = len(false_cases) / case_count
    threshold = float(document["gate"]["threshold"])
    return {
        "case_count": case_count,
        "false_split_count": len(false_cases),
        "false_split_rate": rate,
        "threshold": threshold,
        "passed": rate < threshold,
        "false_split_cases": false_cases,
    }


def evaluate_hand_promotion_gate(
    leaderboard_row: dict[str, object],
    false_split_result: dict[str, object],
    *,
    paste_back_iou: float,
) -> dict[str, object]:
    """Evaluate the indivisible D7 gate from holdout, ambiguity, and round-trip evidence."""
    if leaderboard_row.get("split") != "test_holdout":
        raise HandAuditError("hand promotion requires a frozen test_holdout leaderboard row")
    groups = leaderboard_row.get("group_scores")
    if not isinstance(groups, dict) or "fingers" not in groups:
        raise HandAuditError("hand leaderboard row lacks fingers group metrics")
    finger_metrics = groups["fingers"]
    if not isinstance(finger_metrics, dict) or "iou" not in finger_metrics:
        raise HandAuditError("hand leaderboard fingers group lacks IoU")
    finger_iou = float(finger_metrics["iou"])
    if not 0 <= finger_iou <= 1 or not 0 <= paste_back_iou <= 1:
        raise HandAuditError("hand promotion IoU metrics must be in [0, 1]")
    if int(false_split_result.get("case_count", 0)) < 100:
        raise HandAuditError("false-split evidence must contain at least 100 audit cases")
    false_split_rate = float(false_split_result.get("false_split_rate", -1))
    if not 0 <= false_split_rate <= 1:
        raise HandAuditError("false-split rate must be in [0, 1]")
    checks = {
        "finger_mean_iou": {
            "measured": finger_iou,
            "operator": "gte",
            "threshold": 0.70,
            "passed": finger_iou >= 0.70,
        },
        "merged_finger_false_split_rate": {
            "measured": false_split_rate,
            "operator": "lt",
            "threshold": 0.02,
            "passed": false_split_rate < 0.02,
        },
        "paste_back_iou": {
            "measured": paste_back_iou,
            "operator": "gte",
            "threshold": 0.995,
            "passed": paste_back_iou >= 0.995,
        },
    }
    return {
        "schema_version": "1.0.0",
        "run_id": leaderboard_row.get("run_id"),
        "dataset_ref": leaderboard_row.get("dataset_ref"),
        "split": "test_holdout",
        "checks": checks,
        "passed": all(bool(check["passed"]) for check in checks.values()),
    }


def write_hand_promotion_gate(path: Path, result: dict[str, object]) -> Path:
    """Durably write one evaluated gate result; passing is never inferred by the writer."""
    if set(result.get("checks", {})) != {
        "finger_mean_iou",
        "merged_finger_false_split_rate",
        "paste_back_iou",
    }:
        raise HandAuditError("hand promotion gate result is incomplete")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
