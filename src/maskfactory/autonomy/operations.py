"""Weekly autonomy audit queues, revocations, and retraining-task generation."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from .audit import evaluate_immediate_revocation, select_sparse_human_audits
from .lifecycle import revocation_marker_path


def build_weekly_audit_queue(
    lifecycle_root: Path,
    output_path: Path,
    *,
    period_id: str,
    operations_policy: dict[str, Any],
) -> dict[str, Any]:
    records = []
    for path in sorted(Path(lifecycle_root).rglob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid autonomy lifecycle sidecar {path}: {exc}") from exc
        if document.get("status") != operations_policy["calibrated_status"]:
            continue
        identity = (
            f"{document['image_id']}:{document['instance_id']}:{document['label']}:"
            f"{document['winner_mask_sha256']}:{document['pipeline_fingerprint']}"
        )
        records.append(
            {
                "record_id": hashlib.sha256(identity.encode()).hexdigest(),
                "image_id": document["image_id"],
                "instance_id": document["instance_id"],
                "label": document["label"],
                "context": document["context"],
                "pipeline_fingerprint": document["pipeline_fingerprint"],
                "winner_mask_path": document["winner_mask_path"],
                "winner_mask_sha256": document["winner_mask_sha256"],
                "lifecycle_path": str(path),
            }
        )
    selection = select_sparse_human_audits(
        tuple(records),
        fraction=float(operations_policy["random_human_audit_fraction"]),
        minimum=int(operations_policy["minimum_random_audits_per_week"]),
        period_id=period_id,
    )
    selected = set(selection.selected_record_ids)
    document = {
        "schema_version": "1.0.0",
        "period_id": period_id,
        "population_count": selection.population_count,
        "selected_count": selection.selected_count,
        "selection_fraction": selection.fraction,
        "selection_method": "preoutcome_sha256_rank",
        "records": [record for record in records if record["record_id"] in selected],
        "outcomes_status": "pending" if selected else "empty",
    }
    _atomic_json(Path(output_path), document)
    return document


def process_audit_outcomes(
    queue_path: Path,
    outcomes_path: Path,
    *,
    revocations_root: Path,
    retraining_policy: dict[str, Any],
    operations_policy: dict[str, Any],
    retraining_output_path: Path,
) -> dict[str, Any]:
    queue = json.loads(Path(queue_path).read_text(encoding="utf-8"))
    outcomes = json.loads(Path(outcomes_path).read_text(encoding="utf-8"))
    expected = {record["record_id"] for record in queue["records"]}
    rows = outcomes.get("records")
    if outcomes.get("schema_version") != "1.0.0" or not isinstance(rows, list):
        raise ValueError("autonomy audit outcomes have the wrong contract")
    if {row.get("record_id") for row in rows} != expected:
        raise ValueError("autonomy audit outcomes must cover the exact selected queue")
    by_id = {record["record_id"]: record for record in queue["records"]}
    revocations = []
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        required = {
            "record_id",
            "human_defect",
            "serious_defect",
            "distribution_drift",
            "corrected_gold_sha256",
        }
        if set(row) != required:
            raise ValueError("autonomy audit outcome row has the wrong shape")
        source = by_id[row["record_id"]]
        key = (source["label"], source["context"], source["pipeline_fingerprint"])
        groups.setdefault(key, []).append(row)
    for (label, context, fingerprint), group in groups.items():
        revoked, reasons = evaluate_immediate_revocation(
            tuple(
                {
                    key: row[key]
                    for key in (
                        "record_id",
                        "human_defect",
                        "serious_defect",
                        "distribution_drift",
                    )
                }
                for row in group
            ),
            revoke_on_first_serious_false_accept=bool(
                operations_policy["revoke_on_first_serious_false_accept"]
            ),
        )
        if revoked:
            marker = {
                "schema_version": "1.0.0",
                "label": label,
                "context": context,
                "pipeline_fingerprint": fingerprint,
                "reasons": list(reasons),
                "source_queue": str(queue_path),
                "status": "revoked_residual_only",
            }
            path = revocation_marker_path(
                revocations_root,
                label=label,
                context=context,
                pipeline_fingerprint=fingerprint,
            )
            _atomic_json(path, marker)
            revocations.append(str(path))
    failures = sum(row["human_defect"] is True for row in rows)
    corrections = sum(bool(row["corrected_gold_sha256"]) for row in rows)
    retrain = failures >= int(retraining_policy["minimum_audit_failures"]) or corrections >= int(
        retraining_policy["minimum_new_human_corrections"]
    )
    plan = {
        "schema_version": "1.0.0",
        "task_type": "autonomy_retraining",
        "source_queue": str(queue_path),
        "source_outcomes": str(outcomes_path),
        "audit_failure_count": failures,
        "new_human_correction_count": corrections,
        "requested": retrain,
        "status": "open" if retrain else "below_trigger",
        "include_calibrated_pseudo_labels": bool(
            retraining_policy["include_calibrated_pseudo_labels"]
        ),
        "pseudo_label_loss_weight": operations_policy["pseudo_label_loss_weight"],
        "human_gold_loss_weight": operations_policy["human_gold_loss_weight"],
        "require_frozen_human_holdout_evaluation": True,
        "steps": [
            "build_human_gold_plus_weighted_pseudo_dataset",
            "train_challenger",
            "score_frozen_human_holdouts",
            "rebuild_label_context_certificates",
            "promote_or_reject",
        ],
    }
    _atomic_json(Path(retraining_output_path), plan)
    return {
        "revocations": revocations,
        "retraining_plan": str(retraining_output_path),
        "retraining_requested": retrain,
        "audit_failure_count": failures,
        "new_human_correction_count": corrections,
    }


def _atomic_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = ["build_weekly_audit_queue", "process_audit_outcomes"]
