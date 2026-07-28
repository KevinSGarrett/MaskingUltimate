"""Deterministic second-review sampling and disagreement handling (doc 11 §6)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import statistics
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from ..io.png_strict import read_mask
from ..validation import validate_document
from .failure_mining import append_source_failure
from .metrics import boundary_f, iou

HARD_CLASS_TOKENS = (
    "finger",
    "thumb",
    "pinky",
    "toes",
    "chest",
    "breast",
    "pelvic",
    "waistband",
    "hairline",
    "hand_body_contact",
)


class SecondReviewError(ValueError):
    """Second-review selection or evidence violates the fresh-eyes contract."""


@dataclass(frozen=True)
class ReviewSample:
    image_id: str
    package_root: Path
    part: str
    hard_class: bool


@dataclass(frozen=True)
class PartVerdict:
    part: str
    result: str
    original_mask: Path
    reviewed_mask: Path
    correction: str = ""


@dataclass(frozen=True)
class IaaClassScore:
    samples: int
    mean_iou: float
    mean_boundary_f: float
    target_iou: float
    passed: bool


def sample_approved_packages(
    packages_root: Path,
    *,
    sample_rate: float = 0.15,
    seed: str,
) -> tuple[ReviewSample, ...]:
    """Select ceil(15%) approved packages and one weighted part from each."""
    if not 0 < sample_rate <= 1:
        raise SecondReviewError("second-review sample rate must be in (0, 1]")
    candidates: list[tuple[Path, dict[str, Any], tuple[str, ...]]] = []
    for path in sorted(Path(packages_root).rglob("manifest.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SecondReviewError(f"cannot read package manifest {path}: {exc}") from exc
        if manifest.get("qa", {}).get("qa_overall") != "pass":
            continue
        parts = tuple(
            sorted(
                name
                for name, entry in manifest.get("parts", {}).items()
                if isinstance(entry, dict)
                and entry.get("status") == "human_approved_gold"
                and entry.get("mask_file")
            )
        )
        if parts:
            candidates.append((path.parent, manifest, parts))
    count = math.ceil(len(candidates) * sample_rate)
    ranked = sorted(
        candidates,
        key=lambda item: (
            -math.log(max(_unit_hash(seed, item[1]["image_id"], "package"), 1e-15))
            / (2.0 if any(_is_hard(part) for part in item[2]) else 1.0),
            item[1]["image_id"],
        ),
    )[:count]
    samples = []
    for package_root, manifest, parts in ranked:
        part = min(
            parts,
            key=lambda name: (
                -math.log(max(_unit_hash(seed, manifest["image_id"], name), 1e-15))
                / (2.0 if _is_hard(name) else 1.0),
                name,
            ),
        )
        samples.append(ReviewSample(manifest["image_id"], package_root, part, _is_hard(part)))
    return tuple(samples)


def record_second_review(
    package_root: Path,
    verdicts: tuple[PartVerdict, ...],
    *,
    reviewer: str,
    panels_first_at: datetime,
    full_image_at: datetime,
    completed_at: datetime,
    iaa_root: Path,
    failure_queue_path: Path,
) -> Path:
    """Capture the ordered fresh-eyes review and atomically demote on any failure."""
    package_root = Path(package_root)
    manifest_path = package_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    original_reviewer = manifest.get("review", {}).get("reviewer")
    approved_at = _timestamp(manifest.get("review", {}).get("approved_at"), "approved_at")
    times = (panels_first_at, full_image_at, completed_at)
    if any(value.tzinfo is None for value in times):
        raise SecondReviewError("second-review timestamps must be timezone-aware")
    if not reviewer.strip() or reviewer == original_reviewer:
        raise SecondReviewError(
            "second reviewer must be identified and different from first reviewer"
        )
    if completed_at.astimezone(UTC).date() <= approved_at.astimezone(UTC).date():
        raise SecondReviewError("second review must occur on a different later UTC day")
    if not panels_first_at <= full_image_at <= completed_at:
        raise SecondReviewError("review evidence must prove panels-first, then full-image order")
    if not verdicts or len({item.part for item in verdicts}) != len(verdicts):
        raise SecondReviewError("sampled parts require one unique pass/fail verdict each")
    if any(item.result not in {"pass", "fail"} for item in verdicts):
        raise SecondReviewError("second-review verdict must be pass or fail")
    unknown = {item.part for item in verdicts} - set(manifest.get("parts", {}))
    if unknown:
        raise SecondReviewError(f"review verdict references unknown parts: {sorted(unknown)}")

    stamp = completed_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive = Path(iaa_root) / manifest["image_id"] / stamp
    archive.mkdir(parents=True, exist_ok=False)
    failed = tuple(item for item in verdicts if item.result == "fail")
    records = []
    for verdict in verdicts:
        original = _copy_mask(verdict.original_mask, archive / f"{verdict.part}_first.png")
        reviewed = _copy_mask(verdict.reviewed_mask, archive / f"{verdict.part}_second.png")
        records.append(
            {
                "part": verdict.part,
                "result": verdict.result,
                "correction": verdict.correction,
                "first_mask": original.name,
                "second_mask": reviewed.name,
                "first_sha256": _sha256(original),
                "second_sha256": _sha256(reviewed),
            }
        )

    result = "fail" if failed else "pass"
    manifest["review"]["second_review"] = {
        "required": True,
        "reviewer": reviewer,
        "result": result,
        "at": completed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }
    if failed:
        for entry in manifest["parts"].values():
            if isinstance(entry, dict) and entry.get("status") != "n/a":
                entry["status"] = "rejected_needs_fix"
        manifest["qa"].update({"qa_overall": "fail", "qa_score": 0.0})
    issues = validate_document(manifest, "manifest")
    if issues:
        raise SecondReviewError(
            "second-review manifest invalid: " + "; ".join(str(issue) for issue in issues)
        )
    _atomic_json(manifest_path, manifest)
    evidence = {
        "schema_version": "1.0.0",
        "image_id": manifest["image_id"],
        "first_reviewer": original_reviewer,
        "second_reviewer": reviewer,
        "panels_first_at": _iso(panels_first_at),
        "full_image_at": _iso(full_image_at),
        "completed_at": _iso(completed_at),
        "result": result,
        "verdicts": records,
    }
    evidence_path = archive / "review.json"
    _atomic_json(evidence_path, evidence)
    for verdict in failed:
        append_source_failure(
            failure_queue_path,
            source="second_review",
            image_id=manifest["image_id"],
            body_part=verdict.part,
            pose=manifest.get("person", {}).get("view", "front"),
            model="human_first_review",
            correction=_slug(verdict.correction or f"correct_{verdict.part}"),
            class_error_rate=1.0,
            coverage_deficit=0.0,
            use_weight=1.0 if _is_hard(verdict.part) else 0.3,
        )
    return evidence_path


def write_weekly_iaa_report(
    iaa_root: Path,
    *,
    iso_week: str,
    reports_root: Path,
) -> tuple[Path, Path]:
    """Measure archived mask pairs and write the weekly report + leaderboard input."""
    if not _valid_iso_week(iso_week):
        raise SecondReviewError("iso_week must use YYYY-Www")
    measurements: dict[str, list[tuple[float, float]]] = {}
    reviewed_images: set[str] = set()
    for evidence_path in sorted(Path(iaa_root).rglob("review.json")):
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            completed = _timestamp(evidence.get("completed_at"), "completed_at")
        except (OSError, json.JSONDecodeError, SecondReviewError) as exc:
            raise SecondReviewError(f"invalid IAA evidence {evidence_path}: {exc}") from exc
        year, week, _ = completed.isocalendar()
        if f"{year:04d}-W{week:02d}" != iso_week:
            continue
        reviewed_images.add(evidence["image_id"])
        for verdict in evidence.get("verdicts", []):
            part = verdict["part"]
            first = _validated_binary(evidence_path.parent / verdict["first_mask"])
            second = _validated_binary(evidence_path.parent / verdict["second_mask"])
            measurements.setdefault(part, []).append(
                (iou(first, second), boundary_f(first, second, tolerance_px=2))
            )
    if not measurements:
        raise SecondReviewError(f"no second-review mask pairs found for {iso_week}")
    scores = {
        part: IaaClassScore(
            samples=len(values),
            mean_iou=statistics.fmean(value[0] for value in values),
            mean_boundary_f=statistics.fmean(value[1] for value in values),
            target_iou=0.80 if _is_finger(part) else 0.92,
            passed=statistics.fmean(value[0] for value in values)
            >= (0.80 if _is_finger(part) else 0.92),
        )
        for part, values in sorted(measurements.items())
    }
    total_pairs = sum(score.samples for score in scores.values())
    mean_iou = sum(score.mean_iou * score.samples for score in scores.values()) / total_pairs
    mean_bf = sum(score.mean_boundary_f * score.samples for score in scores.values()) / total_pairs
    report = {
        "schema_version": "1.0.0",
        "iso_week": iso_week,
        "reviewed_images": len(reviewed_images),
        "mask_pairs": total_pairs,
        "mean_iou": mean_iou,
        "mean_boundary_f": mean_bf,
        "all_targets_passed": all(score.passed for score in scores.values()),
        "per_class": {part: asdict(score) for part, score in scores.items()},
    }
    reports_root = Path(reports_root)
    report_path = reports_root / f"iaa_{iso_week}.json"
    _atomic_json(report_path, report)
    markdown = [
        f"# MaskFactory Weekly IAA — {iso_week}",
        "",
        f"Reviewed images: {len(reviewed_images)} · mask pairs: {total_pairs}",
        f"Pooled IoU: {mean_iou:.4f} · boundary-F@2px: {mean_bf:.4f}",
        "",
        "| Class | N | IoU | BF@2px | Target | Result |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for part, score in scores.items():
        markdown.append(
            f"| {part} | {score.samples} | {score.mean_iou:.4f} | "
            f"{score.mean_boundary_f:.4f} | {score.target_iou:.2f} | "
            f"{'PASS' if score.passed else 'FAIL'} |"
        )
    markdown_path = reports_root / f"iaa_{iso_week}.md"
    _atomic_text(markdown_path, "\n".join(markdown) + "\n")
    leaderboard = {
        "run_id": f"human_ceiling_{iso_week}",
        "model_family": "human_ceiling_iaa",
        "ckpt_sha": "0" * 64,
        "dataset_ref": f"iaa:{iso_week}",
        "split": "test_holdout",
        "mean_iou": mean_iou,
        "mean_boundary_f": mean_bf,
        "per_class": {
            part: {"iou": score.mean_iou, "bf": score.mean_boundary_f}
            for part, score in scores.items()
        },
        "group_scores": _group_scores(scores),
        "latency_ms_1024": 0,
        "vram_gb": 0,
        "seeds": [],
        "sample_count": total_pairs,
        "notes": "Human second-review agreement ceiling; models within 0.02 are saturated.",
    }
    leaderboard_path = reports_root / f"human_ceiling_{iso_week}.json"
    _atomic_json(leaderboard_path, leaderboard)
    return markdown_path, leaderboard_path


def _is_hard(part: str) -> bool:
    return any(token in part for token in HARD_CLASS_TOKENS)


def _is_finger(part: str) -> bool:
    return any(token in part for token in ("finger", "thumb", "pinky"))


def _group_scores(scores: dict[str, IaaClassScore]) -> dict[str, dict[str, float]]:
    groups = {
        "fingers": ("finger", "thumb", "pinky"),
        "toes": ("toes",),
        "chest_boundary": ("chest", "breast"),
        "hairline": ("hairline", "hair"),
        "bands": ("band", "waistband", "strap"),
    }
    result = {}
    for group, tokens in groups.items():
        selected = [
            score for part, score in scores.items() if any(token in part for token in tokens)
        ]
        if selected:
            result[group] = {
                "iou": statistics.fmean(score.mean_iou for score in selected),
                "bf": statistics.fmean(score.mean_boundary_f for score in selected),
            }
    return result


def _validated_binary(path: Path) -> NDArray[np.bool_]:
    with Image.open(path) as opened:
        if opened.mode != "L":
            raise SecondReviewError(f"IAA mask must be PNG mode L: {path}")
    array = read_mask(path)
    if array.ndim != 2 or set(np.unique(array).tolist()) - {0, 255}:
        raise SecondReviewError(f"IAA mask is not binary mode-compatible data: {path}")
    return array == 255


def _valid_iso_week(value: str) -> bool:
    try:
        year, week = value.split("-W")
        datetime.fromisocalendar(int(year), int(week), 1)
    except (ValueError, TypeError):
        return False
    return len(year) == 4 and len(week) == 2


def _slug(value: str) -> str:
    normalized = "_".join(
        token
        for token in "".join(
            character if character.isalnum() else " " for character in value.lower()
        ).split()
    )
    return normalized or "manual_correction"


def _unit_hash(*values: str) -> float:
    digest = hashlib.sha256("\0".join(values).encode()).digest()
    return (int.from_bytes(digest[:8], "big") + 1) / (2**64 + 1)


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise SecondReviewError(f"manifest {field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SecondReviewError(f"manifest {field} is invalid") from exc
    if parsed.tzinfo is None:
        raise SecondReviewError(f"manifest {field} lacks timezone")
    return parsed


def _copy_mask(source: Path, destination: Path) -> Path:
    source = Path(source)
    if not source.is_file():
        raise SecondReviewError(f"review mask does not exist: {source}")
    shutil.copy2(source, destination)
    return destination


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
