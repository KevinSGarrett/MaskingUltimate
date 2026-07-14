"""Closed-vocabulary approved-gold coverage matrix and deficit reporting."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from ..validation import validate_document

VIEWS = ("front", "back", "left_profile", "right_profile", "left_3_4", "right_3_4")
POSES = (
    "arms_raised",
    "arms_down",
    "arms_crossed",
    "seated_or_crouched",
    "lying",
    "walking",
    "leg_overlap",
)
CONTEXTS = ("solo", "duo", "small_group")
ATTRIBUTES = (
    "hands_visible",
    "feet_visible",
    "hand_body_contact",
    "hair_occlusion",
    "clothing_boundary",
    "bare_skin_dominant",
    "tight_clothing",
    "loose_clothing",
    "back_visible",
    "fingers_spread",
    "fingers_merged",
    "props_present",
)


def build_coverage_matrix(
    packages: Iterable[dict], *, generated_at: datetime | None = None
) -> dict:
    counts = {(view, pose, context): 0 for view in VIEWS for pose in POSES for context in CONTEXTS}
    attributes = {name: 0 for name in ATTRIBUTES}
    for package in packages:
        if package.get("status") != "human_approved_gold":
            continue
        view = package.get("view")
        poses = tuple(package.get("pose_tags", ()))
        context = package.get("instance_context")
        unknown = set(poses) - set(POSES)
        if view not in VIEWS or context not in CONTEXTS or unknown:
            raise ValueError("package contains non-closed coverage vocabulary")
        for pose in poses:
            counts[(view, pose, context)] += 1
        for attribute in package.get("attributes", ()):
            if attribute not in attributes:
                raise ValueError(f"unknown coverage attribute: {attribute}")
            attributes[attribute] += 1
    document = {
        "schema_version": "1.0.0",
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
        "cells": [
            {"view": view, "pose": pose, "instance_context": context, "approved_gold_count": count}
            for (view, pose, context), count in sorted(counts.items())
        ],
        "attribute_totals": attributes,
    }
    issues = validate_document(document, "coverage_matrix")
    if issues:
        raise ValueError("invalid coverage matrix: " + "; ".join(str(issue) for issue in issues))
    return document


def write_coverage_matrix(path: Path, document: dict) -> Path:
    issues = validate_document(document, "coverage_matrix")
    if issues:
        raise ValueError("invalid coverage matrix")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def coverage_deficit_report(document: dict, *, target_per_cell: int) -> dict:
    if target_per_cell <= 0:
        raise ValueError("target_per_cell must be positive")
    rows = []
    for cell in document["cells"]:
        deficit = max(0, target_per_cell - cell["approved_gold_count"])
        rows.append(
            {
                **cell,
                "target": target_per_cell,
                "deficit": deficit,
                "normalized_deficit": deficit / target_per_cell,
            }
        )
    rows.sort(
        key=lambda row: (
            -row["normalized_deficit"],
            row["view"],
            row["pose"],
            row["instance_context"],
        )
    )
    return {"target_per_cell": target_per_cell, "cells": rows}
