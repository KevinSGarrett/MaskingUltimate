"""Append-only failure queue, exact priority scoring, and scheduled report builders."""

from __future__ import annotations

import json
import math
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable

import yaml

from ..io.png_strict import read_mask
from ..ontology import get_ontology
from ..validation import validate_document
from .metrics import iou


class FailureMiningError(ValueError):
    """Failure evidence or report inputs violate the mining contract."""


@dataclass(frozen=True)
class FailureRecord:
    ts: str
    image_id: str
    failed_body_part: str
    failure_reason: str
    pose_angle: str
    model_that_failed: str
    correction_needed: str
    priority: float
    resolved: bool = False
    resolution_pkg_version: str | None = None


def append_failure(path: Path, record: FailureRecord, *, lock_timeout_sec: float = 5) -> None:
    """Validate then append one durable JSONL record under a short exclusive lock."""
    document = asdict(record)
    _validate_failure_document(document)
    _append_document(path, document, lock_timeout_sec=lock_timeout_sec)


def append_failure_once(path: Path, record: FailureRecord, *, lock_timeout_sec: float = 5) -> bool:
    """Atomically append unless the exact producer identity already exists."""
    document = asdict(record)
    _validate_failure_document(document)
    identity = _failure_identity(document)
    return _append_document(
        path,
        document,
        lock_timeout_sec=lock_timeout_sec,
        unique_identity=identity,
    )


def _validate_failure_document(document: dict) -> None:
    issues = validate_document(document, "failure_queue")
    if issues:
        raise FailureMiningError(
            "invalid failure record: " + "; ".join(str(issue) for issue in issues)
        )


def _append_document(
    path: Path,
    document: dict,
    *,
    lock_timeout_sec: float,
    unique_identity: tuple[str, ...] | None = None,
) -> bool:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + lock_timeout_sec
    descriptor = None
    while descriptor is None:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise FailureMiningError(f"failure queue lock remained busy: {lock}")
            time.sleep(0.05)
    try:
        os.close(descriptor)
        if unique_identity is not None and path.is_file():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    existing = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise FailureMiningError(f"invalid failure queue row {number}: {exc}") from exc
                if _failure_identity(existing) == unique_identity:
                    return False
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return True
    finally:
        lock.unlink(missing_ok=True)


def priority_score(
    *,
    class_error_rate: float,
    coverage_deficit: float,
    downstream_use_weight: float,
    age_days: float,
    half_life_days: float = 14,
) -> float:
    """0.4 error + 0.3 deficit + 0.2 use + 0.1 recency (14-day half-life)."""
    values = (class_error_rate, coverage_deficit, downstream_use_weight)
    if any(not 0 <= value <= 1 for value in values) or age_days < 0 or half_life_days <= 0:
        raise FailureMiningError("priority inputs outside normalized ranges")
    recency = math.exp(-math.log(2) * age_days / half_life_days)
    return (
        0.4 * class_error_rate
        + 0.3 * coverage_deficit
        + 0.2 * downstream_use_weight
        + 0.1 * recency
    )


def make_failure_record(
    *,
    image_id: str,
    body_part: str,
    reason: str,
    pose: str,
    model: str,
    correction: str,
    class_error_rate: float,
    coverage_deficit: float,
    use_weight: float,
    event_time: datetime | None = None,
    now: datetime | None = None,
) -> FailureRecord:
    event = event_time or datetime.now(UTC)
    reference = now or datetime.now(UTC)
    if event.tzinfo is None or reference.tzinfo is None:
        raise FailureMiningError("failure timestamps must be timezone-aware")
    age = max(0.0, (reference - event).total_seconds() / 86400)
    return FailureRecord(
        event.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        image_id,
        body_part,
        reason,
        pose,
        model,
        correction,
        priority_score(
            class_error_rate=class_error_rate,
            coverage_deficit=coverage_deficit,
            downstream_use_weight=use_weight,
            age_days=age,
        ),
    )


def append_source_failure(
    path: Path,
    *,
    source: str,
    image_id: str,
    body_part: str,
    pose: str,
    model: str,
    correction: str,
    class_error_rate: float,
    coverage_deficit: float,
    use_weight: float,
    lane_reason: str | None = None,
) -> FailureRecord:
    """Single wiring point for lane/QC/second-review/VLM/human-delta producers."""
    reason_by_source = {
        "lane": lane_reason or "other",
        "qc": "qc_fail",
        "second_review": "second_review_fail",
        "vlm_autoqa": "vlm_autoqa_disagreement",
        "human_edit_delta": "human_edit_delta",
    }
    if source not in reason_by_source:
        raise FailureMiningError(f"unknown failure source: {source}")
    record = make_failure_record(
        image_id=image_id,
        body_part=body_part,
        reason=reason_by_source[source],
        pose=pose,
        model=model,
        correction=correction,
        class_error_rate=class_error_rate,
        coverage_deficit=coverage_deficit,
        use_weight=use_weight,
    )
    append_failure(path, record)
    return record


def _failure_identity(document: dict) -> tuple[str, ...]:
    return tuple(
        str(document.get(key, ""))
        for key in (
            "image_id",
            "failed_body_part",
            "failure_reason",
            "model_that_failed",
            "correction_needed",
        )
    )


def harvest_human_edit_deltas(
    *,
    packages_root: Path,
    failure_queue_path: Path,
    coverage_matrix: dict,
    use_weights_path: Path,
    now: datetime | None = None,
) -> dict:
    """Compare sealed S09 maps with approved gold and append each new per-part delta once."""
    reference = (now or datetime.now(UTC)).astimezone(UTC)
    weights = yaml.safe_load(Path(use_weights_path).read_text(encoding="utf-8"))["weights"]
    if set(weights) != {"hands", "chest", "feet", "bands", "default"} or any(
        not isinstance(value, (int, float)) or not 0 <= float(value) <= 1
        for value in weights.values()
    ):
        raise FailureMiningError("human-edit use weights violate the governed contract")
    existing = _read_failure_records(failure_queue_path)
    known = {
        (row.image_id, row.failed_body_part, row.failure_reason, row.model_that_failed)
        for row in existing
    }
    authority = get_ontology()
    appended = []
    compared = 0
    unchanged = 0
    duplicate_count = 0
    missing_baseline = []
    for manifest_path in sorted(Path(packages_root).rglob("manifest.json")):
        package = manifest_path.parent
        if not (package / ".maskfactory_frozen.json").is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not all(key in manifest for key in ("image_id", "person", "parts", "review")):
            continue
        baseline_root = package / "annotations" / "draft_baseline"
        baseline_manifest_path = baseline_root / "baseline_manifest.json"
        if not baseline_manifest_path.is_file():
            missing_baseline.append(str(package))
            continue
        baseline = json.loads(baseline_manifest_path.read_text(encoding="utf-8"))
        image_id = str(manifest["image_id"])
        instance_id = package.name if package.name.startswith("p") else "p0"
        if (
            baseline.get("schema_version") != "1.0.0"
            or baseline.get("source_stage") != "S09_weighted_consensus"
            or baseline.get("image_id") != image_id
            or baseline.get("instance_id") != instance_id
        ):
            raise FailureMiningError(f"draft baseline identity mismatch: {package}")
        draft_path = baseline_root / "label_map_part.png"
        draft_material_path = baseline_root / "label_map_material.png"
        gold_path = package / "label_map_part.png"
        if (
            not draft_path.is_file()
            or _sha256(draft_path) != baseline.get("part_map_sha256")
            or not draft_material_path.is_file()
            or _sha256(draft_material_path) != baseline.get("material_map_sha256")
            or not gold_path.is_file()
        ):
            raise FailureMiningError(f"draft/gold PART authority is missing or corrupt: {package}")
        files = manifest.get("files", {})
        if files.get("label_map_part.png") != _sha256(gold_path):
            raise FailureMiningError(f"gold PART map differs from frozen manifest: {package}")
        visible_statuses = [
            entry.get("status")
            for entry in manifest["parts"].values()
            if isinstance(entry, dict) and entry.get("status") != "n/a"
        ]
        if not visible_statuses or set(visible_statuses) != {"human_approved_gold"}:
            raise FailureMiningError(f"frozen package is not uniformly approved gold: {package}")
        draft = read_mask(draft_path)
        gold = read_mask(gold_path)
        if draft.shape != gold.shape or draft.ndim != 2:
            raise FailureMiningError(f"draft/gold PART geometry differs: {package}")
        compared += 1
        package_changed = False
        pose = str(manifest["person"].get("view", ""))
        context = _instance_context(int(manifest["person"].get("person_count", 1)))
        coverage_deficit = _coverage_deficit(
            coverage_matrix,
            view=pose,
            pose_tags=tuple(manifest["person"].get("pose_tags", ())),
            context=context,
        )
        approved_at = str(manifest["review"].get("approved_at") or "")
        try:
            event_time = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FailureMiningError(
                f"approved package has invalid review timestamp: {package}"
            ) from exc
        model = f"s09_weighted_consensus:{instance_id}:{baseline['part_map_sha256'][:12]}"
        for label in authority.labels_for_map("part", enabled_only=True):
            if label.id == 0:
                continue
            score = iou(draft == int(label.id), gold == int(label.id))
            error_rate = 1.0 - score
            if error_rate <= 0:
                continue
            package_changed = True
            key = (image_id, label.name, "human_edit_delta", model)
            if key in known:
                duplicate_count += 1
                continue
            record = make_failure_record(
                image_id=image_id,
                body_part=label.name,
                reason="human_edit_delta",
                pose=pose,
                model=model,
                correction=f"correct_{label.name}",
                class_error_rate=error_rate,
                coverage_deficit=coverage_deficit,
                use_weight=_use_weight(label.name, label.mask_type, weights),
                event_time=event_time,
                now=reference,
            )
            append_failure(failure_queue_path, record)
            appended.append(record)
            known.add(key)
        if not package_changed:
            unchanged += 1
    return {
        "compared_package_count": compared,
        "unchanged_package_count": unchanged,
        "missing_baseline_packages": missing_baseline,
        "new_record_count": len(appended),
        "already_harvested_count": duplicate_count,
        "new_records": tuple(appended),
    }


def write_acquisition_plan(
    records: Iterable[FailureRecord],
    *,
    output_dir: Path,
    clusterer: Callable[[tuple[str, ...]], dict[str, str]],
    report_date: str,
) -> Path:
    """Use a text-LLM cluster callback and write the top-20 concrete priority actions."""
    unresolved = sorted(
        (record for record in records if not record.resolved),
        key=lambda item: (-item.priority, item.image_id),
    )
    clusters = clusterer(tuple(record.failure_reason for record in unresolved))
    lines = [f"# MaskFactory Acquisition Plan — {report_date}", "", "Top priority actions:", ""]
    for rank, record in enumerate(unresolved[:20], 1):
        cluster = clusters.get(record.failure_reason, "unclustered")
        action = _action(record)
        lines.append(
            f"{rank}. **{record.failed_body_part}** ({record.priority:.4f}, {cluster}) — {action} "
            f"[`{record.image_id}`]"
        )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"acquisition_plan_{report_date}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_manifest_lint_report(
    packages: Iterable[Path],
    *,
    output_path: Path,
    linter: Callable[[dict], list[dict]],
) -> Path:
    findings = []
    for package in sorted(map(Path, packages)):
        manifest_path = package / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            package_findings = linter(manifest)
        except (OSError, json.JSONDecodeError) as exc:
            package_findings = [{"severity": "BLOCK", "problem": str(exc)}]
        findings.append({"package": str(package), "findings": package_findings})
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(json.dumps({"packages": findings}, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return output_path


def write_weekly_qa_summary(
    statistics: dict,
    *,
    output_path: Path,
    summarizer: Callable[[dict], str],
) -> Path:
    """Draft weekly Markdown via the configured local text-LLM callback."""
    summary = summarizer(statistics)
    if not isinstance(summary, str) or not summary.strip():
        raise FailureMiningError("weekly summarizer returned no Markdown")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(summary.rstrip() + "\n", encoding="utf-8")
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return output_path


def _action(record: FailureRecord) -> str:
    if record.failure_reason in {"finger_merge", "hair_edge", "occlusion_confusion"}:
        return f"collect cell {record.pose_angle}; re-annotate {record.correction_needed}; promote persistent failures to hard_case_holdout"
    if record.failure_reason in {"lr_swap", "topology"}:
        return f"re-annotate {record.correction_needed}; audit neighboring skeleton evidence"
    return f"re-annotate {record.correction_needed}; review for ontology label proposal"


def _read_failure_records(path: Path) -> tuple[FailureRecord, ...]:
    if not Path(path).is_file():
        return ()
    output = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            output.append(FailureRecord(**json.loads(line)))
        except (json.JSONDecodeError, TypeError) as exc:
            raise FailureMiningError(f"invalid failure queue row {number}: {exc}") from exc
    return tuple(output)


def _coverage_deficit(
    document: dict, *, view: str, pose_tags: tuple[str, ...], context: str
) -> float:
    matching = [
        cell
        for cell in document.get("cells", ())
        if cell.get("view") == view
        and cell.get("pose") in pose_tags
        and cell.get("instance_context") == context
    ]
    if not matching:
        return 1.0
    return max(max(0.0, 8.0 - float(cell["approved_gold_count"])) / 8.0 for cell in matching)


def _instance_context(person_count: int) -> str:
    if person_count < 1:
        raise FailureMiningError("approved package person_count must be positive")
    return "solo" if person_count == 1 else "duo" if person_count == 2 else "small_group"


def _use_weight(label: str, mask_type: str, weights: dict) -> float:
    if any(token in label for token in ("finger", "thumb", "hand", "wrist")):
        group = "hands"
    elif any(token in label for token in ("chest", "breast")):
        group = "chest"
    elif any(token in label for token in ("foot", "toe", "ankle")):
        group = "feet"
    elif mask_type == "region_band":
        group = "bands"
    else:
        group = "default"
    return float(weights[group])


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
