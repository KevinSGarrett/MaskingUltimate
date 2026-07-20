"""Weekly autonomy audit queues, revocations, and retraining-task generation."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..io.hashing import sha256_file
from .audit import (
    evaluate_immediate_revocation,
    select_mixed_human_audits,
    select_mixed_multi_person_audits,
)
from .lifecycle import (
    certificate_is_revoked,
    certificate_stratum_is_revoked,
    revocation_marker_path,
    stratum_revocation_marker_path,
    verified_lifecycle_winner_mask,
)


def build_weekly_audit_queue(
    lifecycle_root: Path,
    output_path: Path,
    *,
    period_id: str,
    operations_policy: dict[str, Any],
) -> dict[str, Any]:
    lifecycle_root = Path(lifecycle_root)
    records = []
    for path in sorted(lifecycle_root.rglob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid autonomy lifecycle sidecar {path}: {exc}") from exc
        if document.get("status") != operations_policy["calibrated_status"]:
            continue
        winner_mask = verified_lifecycle_winner_mask(document, lifecycle_root)
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
                "risk_bucket": document.get("risk_bucket", document["context"]),
                "risk_priority": float(document.get("risk_priority", 0.0)),
                "pipeline_fingerprint": document["pipeline_fingerprint"],
                "winner_mask_path": document["winner_mask_path"],
                "winner_mask_sha256": document["winner_mask_sha256"],
                "lifecycle_path": str(path),
                "lifecycle_sha256": sha256_file(path),
                "verified_winner_mask_path": str(winner_mask),
            }
        )
    selection = select_mixed_human_audits(
        tuple(records),
        random_fraction=float(operations_policy["random_human_audit_fraction"]),
        minimum_random=int(operations_policy["minimum_random_audits_per_week"]),
        risk_oversample_fraction=float(operations_policy["risk_oversample_fraction"]),
        minimum_per_high_risk_bucket=int(operations_policy["minimum_audits_per_high_risk_bucket"]),
        period_id=period_id,
    )
    selected = set(selection.selected_record_ids)
    document = {
        "schema_version": "1.0.0",
        "period_id": period_id,
        "population_count": selection.population_count,
        "selected_count": len(selection.selected_record_ids),
        "random_selected_count": len(selection.random_record_ids),
        "risk_selected_count": len(selection.risk_record_ids),
        "selection_fraction": (
            len(selection.selected_record_ids) / selection.population_count
            if selection.population_count
            else 0.0
        ),
        "selection_method": "preoutcome_random_plus_risk_bucket_oversample",
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
    queue_rows = queue.get("records")
    if not isinstance(queue_rows, list) or any(not isinstance(row, dict) for row in queue_rows):
        raise ValueError("autonomy audit queue records are invalid")
    expected = {record.get("record_id") for record in queue_rows}
    if None in expected or len(expected) != len(queue_rows):
        raise ValueError("autonomy audit queue record IDs must be present and unique")
    rows = outcomes.get("records")
    if (
        outcomes.get("schema_version") != "1.0.0"
        or not isinstance(rows, list)
        or any(not isinstance(row, dict) for row in rows)
    ):
        raise ValueError("autonomy audit outcomes have the wrong contract")
    if {row.get("record_id") for row in rows} != expected:
        raise ValueError("autonomy audit outcomes must cover the exact selected queue")
    by_id = {record["record_id"]: record for record in queue_rows}
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
        if (
            not isinstance(row["human_defect"], bool)
            or not isinstance(row["serious_defect"], bool)
            or not isinstance(row["distribution_drift"], bool)
            or row["serious_defect"] is True
            and row["human_defect"] is not True
        ):
            raise ValueError("autonomy audit outcome booleans are invalid")
        corrected = row["corrected_gold_sha256"]
        if corrected is not None and (
            not isinstance(corrected, str)
            or len(corrected) != 64
            or any(character not in "0123456789abcdef" for character in corrected)
        ):
            raise ValueError("autonomy audit corrected-gold hash is invalid")
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


def build_multi_person_audit_queue(
    records: tuple[dict[str, Any], ...],
    output_path: Path,
    *,
    period_id: str,
    operations_policy: dict[str, Any],
) -> dict[str, Any]:
    """Write a mixed random+risk queue whose selection unit is a complete image."""
    selection = select_mixed_multi_person_audits(
        records,
        random_fraction=float(operations_policy["random_human_audit_fraction"]),
        minimum_random=int(operations_policy["minimum_random_audits_per_week"]),
        risk_oversample_fraction=float(operations_policy["risk_oversample_fraction"]),
        minimum_per_high_risk_bucket=int(operations_policy["minimum_audits_per_high_risk_bucket"]),
        period_id=period_id,
    )
    selected_ids = set(selection.selected_record_ids)
    selected_records = [row for row in records if str(row["record_id"]) in selected_ids]
    document = {
        "schema_version": "1.0.0",
        "period_id": period_id,
        "population_image_count": selection.population_image_count,
        "selected_image_count": len(selection.selected_image_ids),
        "selected_instance_record_count": len(selected_records),
        "random_image_ids": list(selection.random_image_ids),
        "risk_image_ids": list(selection.risk_image_ids),
        "selected_image_ids": list(selection.selected_image_ids),
        "selection_method": "preoutcome_image_group_random_plus_risk_bucket_oversample",
        "records": selected_records,
        "outcomes_status": "pending" if selected_records else "empty",
    }
    _atomic_json(Path(output_path), document)
    return document


def process_multi_person_audit_outcomes(
    queue_path: Path,
    outcomes_path: Path,
    *,
    revocations_root: Path,
    retraining_policy: dict[str, Any],
    operations_policy: dict[str, Any],
    retraining_output_path: Path,
) -> dict[str, Any]:
    """Immediately revoke the exact stratum for serious identity/relationship defects."""
    queue = json.loads(Path(queue_path).read_text(encoding="utf-8"))
    queue_rows = queue.get("records")
    if not isinstance(queue_rows, list) or any(not isinstance(row, dict) for row in queue_rows):
        raise ValueError("multi-person audit queue records are invalid")
    grouped_images: dict[str, list[dict[str, Any]]] = {}
    for row in queue_rows:
        required = {
            "record_id",
            "image_id",
            "instance_id",
            "context",
            "risk_bucket",
            "pipeline_fingerprint",
        }
        if not required <= set(row) or row["context"] not in {"duo", "small_group"}:
            raise ValueError("multi-person audit queue scope is invalid")
        grouped_images.setdefault(str(row["image_id"]), []).append(row)
    outcomes = json.loads(Path(outcomes_path).read_text(encoding="utf-8"))
    rows = outcomes.get("records")
    if (
        outcomes.get("schema_version") != "1.0.0"
        or not isinstance(rows, list)
        or any(not isinstance(row, dict) for row in rows)
    ):
        raise ValueError("multi-person audit outcomes have the wrong contract")
    if {str(row.get("image_id")) for row in rows} != set(grouped_images):
        raise ValueError("multi-person audit outcomes must cover every selected image exactly")
    if len(rows) != len(grouped_images):
        raise ValueError("multi-person audit image outcomes must be unique")

    allowed_failures = {
        "none",
        "cross_person_bleed",
        "identity",
        "contact",
        "occlusion",
        "other",
    }
    normalized = []
    for row in rows:
        required = {
            "image_id",
            "human_defect",
            "serious_defect",
            "distribution_drift",
            "failure_kind",
            "corrected_gold_sha256",
        }
        if set(row) != required:
            raise ValueError("multi-person audit outcome row has the wrong shape")
        if (
            not isinstance(row["human_defect"], bool)
            or not isinstance(row["serious_defect"], bool)
            or not isinstance(row["distribution_drift"], bool)
            or row["serious_defect"]
            and not row["human_defect"]
            or row["failure_kind"] not in allowed_failures
            or (not row["human_defect"] and row["failure_kind"] != "none")
            or (
                row["serious_defect"]
                and row["failure_kind"]
                not in {"cross_person_bleed", "identity", "contact", "occlusion"}
            )
        ):
            raise ValueError("multi-person audit outcome semantics are invalid")
        corrected = row["corrected_gold_sha256"]
        if corrected is not None and (
            not isinstance(corrected, str)
            or len(corrected) != 64
            or any(character not in "0123456789abcdef" for character in corrected)
        ):
            raise ValueError("multi-person audit corrected-gold hash is invalid")
        normalized.append(row)

    strata: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for outcome in normalized:
        source_rows = grouped_images[str(outcome["image_id"])]
        scopes = {
            (
                str(source["risk_bucket"]),
                str(source["context"]),
                str(source["pipeline_fingerprint"]),
            )
            for source in source_rows
        }
        if len(scopes) != 1:
            raise ValueError("one audited image cannot span multi-person revocation strata")
        strata.setdefault(next(iter(scopes)), []).append(outcome)

    revoked = []
    for (risk_bucket, instance_context, fingerprint), group in sorted(strata.items()):
        serious_kinds = sorted({str(row["failure_kind"]) for row in group if row["serious_defect"]})
        drifted = any(row["distribution_drift"] for row in group)
        if not serious_kinds and not drifted:
            continue
        reasons = [*(f"serious_{kind}" for kind in serious_kinds)]
        if drifted:
            reasons.append("distribution_drift")
        marker = {
            "schema_version": "1.0.0",
            "risk_bucket": risk_bucket,
            "instance_context": instance_context,
            "pipeline_fingerprint": fingerprint,
            "reasons": reasons,
            "source_queue": str(queue_path),
            "source_outcomes": str(outcomes_path),
            "status": "revoked_residual_only",
        }
        marker_path = stratum_revocation_marker_path(
            revocations_root,
            risk_bucket=risk_bucket,
            instance_context=instance_context,
            pipeline_fingerprint=fingerprint,
        )
        _atomic_json(marker_path, marker)
        revoked.append(
            {
                "risk_bucket": risk_bucket,
                "instance_context": instance_context,
                "pipeline_fingerprint": fingerprint,
                "marker_path": str(marker_path),
                "reasons": reasons,
            }
        )

    failures = sum(row["human_defect"] for row in normalized)
    corrections = sum(bool(row["corrected_gold_sha256"]) for row in normalized)
    retrain = failures >= int(retraining_policy["minimum_audit_failures"]) or corrections >= int(
        retraining_policy["minimum_new_human_corrections"]
    )
    retraining = {
        "schema_version": "1.0.0",
        "task_type": "multi_person_autonomy_retraining",
        "source_queue": str(queue_path),
        "source_outcomes": str(outcomes_path),
        "requested": retrain,
        "status": "open" if retrain else "below_trigger",
        "audit_failure_count": failures,
        "new_human_correction_count": corrections,
        "revoked_strata": revoked,
        "require_frozen_human_holdout_evaluation": True,
        "pseudo_label_loss_weight": operations_policy["pseudo_label_loss_weight"],
        "human_gold_loss_weight": operations_policy["human_gold_loss_weight"],
    }
    _atomic_json(Path(retraining_output_path), retraining)
    eligibility_removed = all(
        certificate_stratum_is_revoked(
            revocations_root,
            risk_bucket=row["risk_bucket"],
            instance_context=row["instance_context"],
            pipeline_fingerprint=row["pipeline_fingerprint"],
        )
        for row in revoked
    )
    return {
        "revoked_strata": revoked,
        "serving_and_certified_training_eligibility_removed": eligibility_removed,
        "retraining_requested": retrain,
        "retraining_plan": str(retraining_output_path),
    }


def run_serious_failure_drill(
    output_root: Path,
    *,
    operations_policy: dict[str, Any],
    retraining_policy: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Exercise exact outcomes, immediate revocation, and retraining in isolation."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    timestamp = current.isoformat().replace("+00:00", "Z")
    policy_digest = hashlib.sha256(
        json.dumps(
            {"operations": operations_policy, "retraining": retraining_policy},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    drill_id = hashlib.sha256(f"{timestamp}\0{policy_digest}".encode()).hexdigest()[:24]
    root = Path(output_root) / drill_id
    if root.exists():
        raise ValueError(f"serious-failure drill is immutable and already exists: {drill_id}")
    root.mkdir(parents=True)
    queue_path = root / "queue.json"
    outcomes_path = root / "outcomes.json"
    revocations_root = root / "revocations"
    retraining_path = root / "retraining_task.json"
    fingerprint = f"serious-failure-drill:{drill_id}"
    records = [
        {
            "record_id": hashlib.sha256(f"{drill_id}:{index}".encode()).hexdigest(),
            "image_id": f"drill_image_{index}",
            "instance_id": "p0",
            "label": "left_hand_base",
            "context": "solo",
            "risk_bucket": "hands_feet",
            "pipeline_fingerprint": fingerprint,
        }
        for index in range(int(retraining_policy["minimum_audit_failures"]))
    ]
    if not records:
        raise ValueError("serious-failure drill requires a positive audit-failure threshold")
    queue = {
        "schema_version": "1.0.0",
        "period_id": f"drill-{drill_id}",
        "population_count": len(records),
        "selected_count": len(records),
        "random_selected_count": 1,
        "risk_selected_count": len(records),
        "selection_fraction": 1.0,
        "selection_method": "serious_failure_drill_exact_fixture",
        "records": records,
        "outcomes_status": "pending",
    }
    outcomes = {
        "schema_version": "1.0.0",
        "records": [
            {
                "record_id": record["record_id"],
                "human_defect": True,
                "serious_defect": True,
                "distribution_drift": False,
                "corrected_gold_sha256": hashlib.sha256(
                    f"corrected:{record['record_id']}".encode()
                ).hexdigest(),
            }
            for record in records
        ],
    }
    _atomic_json(queue_path, queue)
    _atomic_json(outcomes_path, outcomes)
    result = process_audit_outcomes(
        queue_path,
        outcomes_path,
        revocations_root=revocations_root,
        retraining_policy=retraining_policy,
        operations_policy=operations_policy,
        retraining_output_path=retraining_path,
    )
    marker_path = revocation_marker_path(
        revocations_root,
        label="left_hand_base",
        context="solo",
        pipeline_fingerprint=fingerprint,
    )
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    retraining = json.loads(retraining_path.read_text(encoding="utf-8"))
    passed = (
        result["retraining_requested"] is True
        and result["audit_failure_count"] == len(records)
        and len(result["revocations"]) == 1
        and marker.get("reasons") == ["serious_false_accept"]
        and marker.get("status") == "revoked_residual_only"
        and certificate_is_revoked(
            revocations_root,
            label="left_hand_base",
            context="solo",
            pipeline_fingerprint=fingerprint,
        )
        and retraining.get("requested") is True
        and retraining.get("status") == "open"
        and retraining.get("require_frozen_human_holdout_evaluation") is True
    )
    report = {
        "schema_version": "1.0.0",
        "drill_id": drill_id,
        "executed_at": timestamp,
        "pipeline_fingerprint": fingerprint,
        "policy_sha256": policy_digest,
        "audit_count": len(records),
        "serious_failure_count": len(records),
        "queue_sha256": sha256_file(queue_path),
        "outcomes_sha256": sha256_file(outcomes_path),
        "revocation_sha256": sha256_file(marker_path),
        "retraining_task_sha256": sha256_file(retraining_path),
        "serving_and_certified_training_eligibility_removed": certificate_is_revoked(
            revocations_root,
            label="left_hand_base",
            context="solo",
            pipeline_fingerprint=fingerprint,
        ),
        "retraining_requested": result["retraining_requested"],
        "passed": passed,
    }
    report["sha256"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    _atomic_json(root / "report.json", report)
    if not passed:
        raise RuntimeError(f"serious-failure drill failed: {drill_id}")
    return report


def _atomic_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the temporary basename short: scoped revocation filenames already
    # contain a full fingerprint and can otherwise exceed legacy MAX_PATH.
    temporary = path.parent / f".tmp-{uuid.uuid4().hex}.json"
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "build_multi_person_audit_queue",
    "build_weekly_audit_queue",
    "process_audit_outcomes",
    "process_multi_person_audit_outcomes",
    "run_serious_failure_drill",
]
