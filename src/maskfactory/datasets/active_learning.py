"""S15 failure/coverage harvesting and concrete acquisition planning."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path

from ..qa.failure_mining import (
    FailureRecord,
    harvest_human_edit_deltas,
    write_acquisition_plan,
)
from .coverage import build_coverage_matrix, coverage_deficit_report


def run_active_learning(
    *,
    failure_queue_path: Path,
    coverage_matrix_path: Path,
    output_dir: Path,
    approved_gold_count: int,
    champion_gold_count: int = 0,
    ontology_changed: bool = False,
    class_error_history_path: Path | None = None,
    report_date: str | None = None,
    packages_root: Path | None = None,
    use_weights_path: Path = Path("configs/training/use_weights.yaml"),
) -> dict:
    coverage = _coverage(coverage_matrix_path)
    harvest = (
        harvest_human_edit_deltas(
            packages_root=packages_root,
            failure_queue_path=failure_queue_path,
            coverage_matrix=coverage,
            use_weights_path=use_weights_path,
        )
        if packages_root is not None
        else {
            "compared_package_count": 0,
            "unchanged_package_count": 0,
            "missing_baseline_packages": [],
            "new_record_count": 0,
            "already_harvested_count": 0,
        }
    )
    records = _records(failure_queue_path)
    date = report_date or datetime.now(UTC).date().isoformat()
    plan = write_acquisition_plan(
        records,
        output_dir=output_dir,
        clusterer=lambda reasons: {reason: _cluster(reason) for reason in reasons},
        report_date=date,
    )
    deficits = coverage_deficit_report(coverage, target_per_cell=8)["cells"]
    top = [row for row in deficits if row["deficit"] > 0][:10]
    with plan.open("a", encoding="utf-8") as handle:
        handle.write("\n## Top coverage deficits\n\n")
        for row in top:
            handle.write(
                f"- Collect {row['deficit']} approved `{row['view']}` / `{row['pose']}` / "
                f"`{row['instance_context']}` examples (current {row['approved_gold_count']}/8).\n"
            )
    error_trigger, error_classes = _class_error_trigger(class_error_history_path)
    triggers = {
        "new_gold_plus_50": approved_gold_count - champion_gold_count >= 50,
        "ontology_changed": ontology_changed,
        "class_error_increase_two_weeks": error_trigger,
    }
    output_dir = Path(output_dir)
    retrain_requested = any(triggers.values())
    retrain_task = (
        _write_retrain_task(
            output_dir / "retrain_tasks" / f"p5_retrain_{date}.json",
            report_date=date,
            triggers=triggers,
            error_classes=error_classes,
            approved_gold_count=approved_gold_count,
        )
        if retrain_requested
        else None
    )
    result = {
        "schema_version": "1.0.0",
        "report_date": date,
        "unresolved_failure_count": sum(not record.resolved for record in records),
        "coverage_deficit_count": sum(row["deficit"] > 0 for row in deficits),
        "top_coverage_deficits": top,
        "retrain_triggers": triggers,
        "retrain_requested": retrain_requested,
        "retrain_task": str(retrain_task) if retrain_task else None,
        "class_error_trigger_classes": list(error_classes),
        "acquisition_plan": str(plan),
        "human_edit_harvest": {
            key: value for key, value in harvest.items() if key != "new_records"
        },
    }
    (output_dir / f"active_learning_{date}.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def _class_error_trigger(path: Path | None) -> tuple[bool, tuple[str, ...]]:
    """Require >5-point error increases in each of the last two weekly transitions."""
    if path is None or not Path(path).is_file():
        return False, ()
    by_class: dict[str, list[tuple[str, float]]] = {}
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            label = str(row["label"])
            week = str(row["iso_week"])
            error_rate = float(row["error_rate"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid class-error history row {number}: {exc}") from exc
        if not 0 <= error_rate <= 1:
            raise ValueError(f"class-error history row {number} outside 0..1")
        by_class.setdefault(label, []).append((week, error_rate))
    triggered = []
    for label, values in by_class.items():
        ordered = sorted(values)
        if len(ordered) >= 3:
            recent = [value for _week, value in ordered[-3:]]
            if recent[1] - recent[0] > 0.05 and recent[2] - recent[1] > 0.05:
                triggered.append(label)
    return bool(triggered), tuple(sorted(triggered))


def _write_retrain_task(
    path: Path,
    *,
    report_date: str,
    triggers: dict[str, bool],
    error_classes: tuple[str, ...],
    approved_gold_count: int,
) -> Path:
    document = {
        "schema_version": "1.0.0",
        "task_type": "p5_triggered_retrain",
        "task_id": f"p5_retrain_{report_date}",
        "created_on": report_date,
        "status": "open" if approved_gold_count >= 200 else "waiting_for_p5_entry_gate",
        "approved_gold_count": approved_gold_count,
        "required_gold_count": 200,
        "triggers": triggers,
        "class_error_trigger_classes": list(error_classes),
        "steps": [
            "build_dataset_vnext",
            "train_candidates",
            "score_frozen_holdouts",
            "leaderboard_compare",
            "promote_or_reject",
            "record_champion_history",
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != document:
            raise ValueError(f"retrain task ID collision with different content: {path}")
        return path
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _records(path: Path) -> tuple[FailureRecord, ...]:
    if not Path(path).is_file():
        return ()
    allowed = {field.name for field in fields(FailureRecord)}
    output = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            document = json.loads(line)
            output.append(FailureRecord(**{key: document[key] for key in allowed}))
    return tuple(output)


def _coverage(path: Path) -> dict:
    if Path(path).is_file():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return build_coverage_matrix([], generated_at=datetime(1970, 1, 1, tzinfo=UTC))


def _cluster(reason: str) -> str:
    lowered = reason.lower()
    if "finger" in lowered or "hand" in lowered:
        return "hands_fingers"
    if "hair" in lowered:
        return "hair_boundary"
    if "occlu" in lowered or "contact" in lowered:
        return "occlusion_contact"
    if "left" in lowered or "right" in lowered or "swap" in lowered:
        return "left_right"
    return "general_boundary"
