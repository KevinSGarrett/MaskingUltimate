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

from ..validation import validate_document


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
    issues = validate_document(document, "failure_queue")
    if issues:
        raise FailureMiningError(
            "invalid failure record: " + "; ".join(str(issue) for issue in issues)
        )
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
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
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
    output_path.write_text(summary.rstrip() + "\n", encoding="utf-8")
    return output_path


def _action(record: FailureRecord) -> str:
    if record.failure_reason in {"finger_merge", "hair_edge", "occlusion_confusion"}:
        return f"collect cell {record.pose_angle}; re-annotate {record.correction_needed}; promote persistent failures to hard_case_holdout"
    if record.failure_reason in {"lr_swap", "topology"}:
        return f"re-annotate {record.correction_needed}; audit neighboring skeleton evidence"
    return f"re-annotate {record.correction_needed}; review for ontology label proposal"
