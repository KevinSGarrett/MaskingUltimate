"""Validated model leaderboard storage, context breakouts, and comparison."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Iterable

from ..truth_tiers import HUMAN_ANCHOR_GOLD
from ..validation import ArtifactValidationError, validate_document

INSTANCE_CONTEXTS = ("solo", "duo", "small_group")
STANDING_BASELINES = ("sam2_only", "sam2_pose", "sam2_parsing", "draft_pipeline_full")
FINAL_EVALUATION_AUTHORITY = "final_holdout"
FINAL_HOLDOUT_SPLITS = frozenset({"test_holdout", "hard_case_holdout"})
EVALUATION_AUTHORITIES = frozenset(
    {"final_holdout", "diagnostic", "standing_baseline", "human_ceiling"}
)


def enforce_final_evaluation_authority(row: dict[str, Any]) -> dict[str, Any]:
    """Reject autonomous/pseudo/machine truth as final holdout evaluation authority.

    Rows without ``evaluation_authority`` are unchanged (standing baselines / legacy).
    When ``evaluation_authority == final_holdout``, require human-anchor gold on a
    frozen holdout split plus an evaluation-manifest identity.
    """
    authority = row.get("evaluation_authority")
    if authority is None:
        return row
    if authority not in EVALUATION_AUTHORITIES:
        raise ValueError(f"unknown evaluation_authority: {authority}")
    if authority != FINAL_EVALUATION_AUTHORITY:
        return row
    tier = row.get("evaluation_truth_tier")
    if tier != HUMAN_ANCHOR_GOLD:
        raise ValueError(
            "final_holdout evaluation authority requires evaluation_truth_tier="
            f"{HUMAN_ANCHOR_GOLD!r}; autonomous/pseudo/machine truth is ineligible"
        )
    if row.get("split") not in FINAL_HOLDOUT_SPLITS:
        raise ValueError(
            "final_holdout evaluation authority requires split in "
            f"{sorted(FINAL_HOLDOUT_SPLITS)}"
        )
    manifest = row.get("evaluation_manifest_sha256")
    if (
        not isinstance(manifest, str)
        or len(manifest) != 64
        or any(ch not in "0123456789abcdef" for ch in manifest)
    ):
        raise ValueError("final_holdout evaluation authority requires evaluation_manifest_sha256")
    return row


def normalize_leaderboard_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a schema-current row; legacy pooled rows become an equivalent solo row."""
    normalized = json.loads(json.dumps(row))
    if "instance_context_scores" not in normalized:
        normalized["instance_context_scores"] = {
            "solo": {
                "mean_iou": normalized["mean_iou"],
                "mean_boundary_f": normalized["mean_boundary_f"],
                "per_class": normalized["per_class"],
                "sample_count": int(normalized.get("sample_count", 0)),
            }
        }
    unknown = set(normalized["instance_context_scores"]) - set(INSTANCE_CONTEXTS)
    if unknown:
        raise ValueError(f"unknown instance context: {sorted(unknown)}")
    issues = validate_document(normalized, "leaderboard")
    if issues:
        raise ArtifactValidationError(issues)
    return enforce_final_evaluation_authority(normalized)


def append_leaderboard_row(path: Path, row: dict[str, Any]) -> dict[str, Any]:
    """Validate and durably append one candidate x holdout leaderboard row."""
    normalized = normalize_leaderboard_row(row)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_rows = load_leaderboard(path) if path.is_file() else ()
    duplicate = next(
        (entry for entry in existing_rows if entry["run_id"] == normalized["run_id"]), None
    )
    if duplicate is not None:
        if duplicate == normalized:
            return duplicate
        raise ValueError(
            f"leaderboard run_id is immutable and already exists: {normalized['run_id']}"
        )
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    existing = path.read_bytes() if path.is_file() else b""
    try:
        temporary.write_bytes(
            existing
            + (json.dumps(normalized, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return normalized


def load_leaderboard(path: Path) -> tuple[dict[str, Any], ...]:
    """Read and normalize current and pre-instance-context JSONL rows."""
    rows = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(normalize_leaderboard_row(json.loads(line)))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid leaderboard row {number}: {exc}") from exc
    return tuple(rows)


def ensure_standing_baselines(
    path: Path,
    *,
    dataset_ref: str,
    split: str,
    score: Callable[[str, str, str], dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Score each missing standing baseline exactly once for a dataset holdout.

    ``score`` is the production pipeline/evaluator boundary. It receives
    ``(baseline, dataset_ref, split)`` and returns the measured leaderboard payload;
    identity fields are stamped here so a scorer cannot accidentally misattribute a run.
    """
    if not dataset_ref or split not in {"val", "test_holdout", "hard_case_holdout"}:
        raise ValueError("standing baseline dataset_ref/split invalid")
    path = Path(path)
    existing = load_leaderboard(path) if path.is_file() else ()
    indexed = {}
    for row in existing:
        baseline = row["model_family"]
        if (
            row["dataset_ref"] != dataset_ref
            or row["split"] != split
            or baseline not in STANDING_BASELINES
        ):
            continue
        if baseline in indexed:
            raise ValueError(
                f"multiple {baseline} rows exist for {dataset_ref}/{split}; baseline is ambiguous"
            )
        indexed[baseline] = row
    for baseline in STANDING_BASELINES:
        if baseline in indexed:
            continue
        payload = dict(score(baseline, dataset_ref, split))
        payload.update(
            {
                "run_id": f"baseline_{baseline}_{dataset_ref}_{split}",
                "model_family": baseline,
                "dataset_ref": dataset_ref,
                "split": split,
            }
        )
        indexed[baseline] = append_leaderboard_row(path, payload)
    missing = set(STANDING_BASELINES) - set(indexed)
    if missing:
        raise RuntimeError(f"standing baselines missing after scoring: {sorted(missing)}")
    return tuple(indexed[name] for name in STANDING_BASELINES)


def compare_runs(rows: Iterable[dict[str, Any]], run_a: str, run_b: str) -> dict[str, Any]:
    """Compare pooled, class, group, and instance-context scores for two rows."""
    indexed = {}
    for row in rows:
        normalized = normalize_leaderboard_row(row)
        run_id = str(normalized["run_id"])
        if run_id in indexed:
            raise ValueError(f"leaderboard contains ambiguous duplicate run_id: {run_id}")
        indexed[run_id] = normalized
    if run_a not in indexed or run_b not in indexed:
        raise KeyError("both comparison run IDs must exist in the leaderboard")
    a, b = indexed[run_a], indexed[run_b]
    if (a["dataset_ref"], a["split"]) != (b["dataset_ref"], b["split"]):
        raise ValueError("leaderboard comparisons require the same dataset_ref and split")
    labels = sorted(set(a["per_class"]) | set(b["per_class"]))
    groups = sorted(set(a["group_scores"]) | set(b["group_scores"]))
    contexts = sorted(set(a["instance_context_scores"]) | set(b["instance_context_scores"]))
    return {
        "run_a": run_a,
        "run_b": run_b,
        "dataset_ref": a["dataset_ref"],
        "split": a["split"],
        "pooled_delta": _metric_delta(a, b),
        "per_class_delta": {
            label: _class_metric_delta(a["per_class"].get(label), b["per_class"].get(label))
            for label in labels
        },
        "group_delta": {
            group: _class_metric_delta(a["group_scores"].get(group), b["group_scores"].get(group))
            for group in groups
        },
        "instance_context_delta": {
            context: _metric_delta(
                a["instance_context_scores"].get(context),
                b["instance_context_scores"].get(context),
            )
            for context in contexts
        },
    }


def format_comparison_table(comparison: dict[str, Any]) -> str:
    """Render pooled, class, group, and context deltas as a stable Markdown table."""
    lines = [
        f"# {comparison['run_a']} -> {comparison['run_b']}",
        "",
        "| Scope | Name | IoU delta | Boundary-F delta |",
        "|---|---|---:|---:|",
    ]
    _table_row(lines, "pooled", "all", comparison["pooled_delta"], mean=True)
    for scope, key in (
        ("class", "per_class_delta"),
        ("group", "group_delta"),
        ("context", "instance_context_delta"),
    ):
        for name, metrics in sorted(comparison[key].items()):
            _table_row(lines, scope, name, metrics, mean=scope == "context")
    return "\n".join(lines) + "\n"


def saturation_report(
    rows: Iterable[dict[str, Any]], human_run_id: str, *, threshold: float = 0.02
) -> dict[str, Any]:
    """Report classes whose best model is within threshold of human IAA on IoU and BF."""
    normalized = tuple(normalize_leaderboard_row(row) for row in rows)
    human = next((row for row in normalized if row["run_id"] == human_run_id), None)
    if human is None or human["model_family"] != "human_ceiling_iaa":
        raise ValueError("human ceiling row not found")
    candidates = [row for row in normalized if row["model_family"] != "human_ceiling_iaa"]
    classes = {}
    for label, ceiling in human["per_class"].items():
        scored = [row for row in candidates if label in row["per_class"]]
        best = max(scored, key=lambda row: row["per_class"][label]["iou"], default=None)
        classes[label] = {
            "human_iou": ceiling["iou"],
            "human_bf": ceiling["bf"],
            "best_run_id": best["run_id"] if best else None,
            "saturated": bool(
                best
                and ceiling["iou"] - best["per_class"][label]["iou"] <= threshold
                and ceiling["bf"] - best["per_class"][label]["bf"] <= threshold
            ),
        }
    return {"human_run_id": human_run_id, "threshold": threshold, "classes": classes}


def _table_row(
    lines: list[str], scope: str, name: str, metrics: dict[str, Any], *, mean: bool
) -> None:
    iou_key, bf_key = ("mean_iou", "mean_boundary_f") if mean else ("iou", "bf")
    values = [metrics.get(iou_key), metrics.get(bf_key)]
    rendered = ["n/a" if value is None else f"{float(value):+.4f}" for value in values]
    lines.append(f"| {scope} | {name} | {rendered[0]} | {rendered[1]} |")


def _metric_delta(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, float | None]:
    return {
        metric: None if a is None or b is None else float(b[metric]) - float(a[metric])
        for metric in ("mean_iou", "mean_boundary_f")
    }


def _class_metric_delta(
    a: dict[str, Any] | None, b: dict[str, Any] | None
) -> dict[str, float | None]:
    return {
        metric: None if a is None or b is None else float(b[metric]) - float(a[metric])
        for metric in ("iou", "bf")
    }
