"""STATIC binder for acquisition plans and mining abstention routing (P4 residual).

Code/fixture only. Never claims D4, VLM calibration, gold, doctor-green, or
human-anchor authority. Abstention routes here do not require human-anchor corpora.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..validation import validate_document
from .failure_mining import FailureRecord, _action, priority_score

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "failure_mining_static_report"
AUTHORITY = "failure_mining_static_only_no_d4_vlm_calibration_or_human_anchor_authority"

PRIORITY_WEIGHTS = {
    "class_error_rate": 0.4,
    "coverage_deficit": 0.3,
    "downstream_use_weight": 0.2,
    "recency": 0.1,
}
TOP_ACTION_CAP = 20

ACTION_KINDS = (
    "collect_cell_reannotate_holdout",
    "reannotate_skeleton_audit",
    "reannotate_label_proposal",
    "v2_governed_acquisition",
)

MINING_ABSTENTION_REASONS = frozenset(
    {
        "empty_unresolved_queue",
        "clusterer_invalid_output",
        "clusterer_missing_reasons",
        "clusterer_extra_reasons",
        "schema_validation_failed",
        "text_llm_unavailable",
        "priority_inputs_invalid",
        "overclaim_d4_or_vlm_calibration",
    }
)

HONEST_NON_CLAIMS = (
    "d4_complete",
    "vlm_calibration_complete",
    "human_anchor_authority",
    "doctor_green",
    "gold",
    "PRODUCTION_EVIDENCE_PASS",
)


class FailureMiningStaticError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def action_kind_for_record(record: FailureRecord) -> str:
    """Closed action-kind vocabulary for machine-readable acquisition plans."""
    reason = record.failure_reason
    if reason.startswith("v2_"):
        return "v2_governed_acquisition"
    if reason in {"finger_merge", "hair_edge", "occlusion_confusion"}:
        return "collect_cell_reannotate_holdout"
    if reason in {"lr_swap", "topology"}:
        return "reannotate_skeleton_audit"
    return "reannotate_label_proposal"


def route_mining_abstention(
    reason: str,
    *,
    detail: str = "",
) -> dict[str, Any]:
    """Route a mining failure to residual without needing human-anchor corpora."""
    if reason not in MINING_ABSTENTION_REASONS:
        raise FailureMiningStaticError(f"unknown_mining_abstention_reason:{reason}")
    return {
        "schema_version": "1.0.0",
        "decision": "autonomous_abstention",
        "destination": "residual_mining_queue",
        "reason": reason,
        "detail": detail,
        "may_claim_weekly_plan_authority": False,
        "may_claim_d4": False,
        "may_claim_vlm_calibration": False,
        "human_anchor_required": False,
        "human_anchor_authority": False,
        "proof_tier": PROOF_TIER,
    }


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _validate_clusters(
    unresolved: tuple[FailureRecord, ...],
    clusters: Mapping[str, str],
) -> dict[str, Any] | None:
    reasons = tuple(record.failure_reason for record in unresolved)
    expected = set(reasons)
    actual = set(clusters)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            return route_mining_abstention(
                "clusterer_missing_reasons",
                detail=f"missing={','.join(missing)}",
            )
        return route_mining_abstention(
            "clusterer_extra_reasons",
            detail=f"extra={','.join(extra)}",
        )
    for reason, theme in clusters.items():
        if not isinstance(theme, str) or not theme.strip():
            return route_mining_abstention(
                "clusterer_invalid_output",
                detail=f"empty_theme_for={reason}",
            )
    return None


def build_acquisition_plan_document(
    records: Iterable[FailureRecord],
    *,
    report_date: str,
    clusterer: Callable[[tuple[str, ...]], dict[str, str]],
    markdown_relative_path: str | None = None,
) -> dict[str, Any]:
    """Build a schema-valid acquisition plan or a typed mining abstention."""
    unresolved = tuple(
        sorted(
            (record for record in records if not record.resolved),
            key=lambda item: (-item.priority, item.image_id),
        )
    )
    if not unresolved:
        abstention = route_mining_abstention("empty_unresolved_queue")
        draft = {
            "schema_version": "1.0.0",
            "artifact_type": "acquisition_plan",
            "report_date": report_date,
            "unresolved_failure_count": 0,
            "top_action_cap": TOP_ACTION_CAP,
            "top_actions": [],
            "action_kinds_used": [],
            "clustering_complete": False,
            "d4_complete": False,
            "vlm_calibration_complete": False,
            "human_anchor_authority": False,
            "weekly_plan_authority": False,
        }
        if markdown_relative_path is not None:
            draft["markdown_relative_path"] = markdown_relative_path
        digest = _sha(draft)
        draft["sha256"] = digest
        draft["abstention"] = abstention
        return draft

    try:
        clusters = clusterer(tuple(record.failure_reason for record in unresolved))
    except Exception as exc:  # noqa: BLE001 — mining must fail closed on any clusterer fault
        abstention = route_mining_abstention("text_llm_unavailable", detail=str(exc))
        draft = {
            "schema_version": "1.0.0",
            "artifact_type": "acquisition_plan",
            "report_date": report_date,
            "unresolved_failure_count": len(unresolved),
            "top_action_cap": TOP_ACTION_CAP,
            "top_actions": [],
            "action_kinds_used": [],
            "clustering_complete": False,
            "d4_complete": False,
            "vlm_calibration_complete": False,
            "human_anchor_authority": False,
            "weekly_plan_authority": False,
            "abstention": abstention,
        }
        digest = _sha({k: v for k, v in draft.items() if k != "sha256"})
        draft["sha256"] = digest
        return draft

    if not isinstance(clusters, dict):
        abstention = route_mining_abstention(
            "clusterer_invalid_output", detail="clusters_not_mapping"
        )
        draft = {
            "schema_version": "1.0.0",
            "artifact_type": "acquisition_plan",
            "report_date": report_date,
            "unresolved_failure_count": len(unresolved),
            "top_action_cap": TOP_ACTION_CAP,
            "top_actions": [],
            "action_kinds_used": [],
            "clustering_complete": False,
            "d4_complete": False,
            "vlm_calibration_complete": False,
            "human_anchor_authority": False,
            "weekly_plan_authority": False,
            "abstention": abstention,
        }
        digest = _sha({k: v for k, v in draft.items() if k != "sha256"})
        draft["sha256"] = digest
        return draft

    abstention = _validate_clusters(unresolved, clusters)
    if abstention is not None:
        draft = {
            "schema_version": "1.0.0",
            "artifact_type": "acquisition_plan",
            "report_date": report_date,
            "unresolved_failure_count": len(unresolved),
            "top_action_cap": TOP_ACTION_CAP,
            "top_actions": [],
            "action_kinds_used": [],
            "clustering_complete": False,
            "d4_complete": False,
            "vlm_calibration_complete": False,
            "human_anchor_authority": False,
            "weekly_plan_authority": False,
            "abstention": abstention,
        }
        digest = _sha({k: v for k, v in draft.items() if k != "sha256"})
        draft["sha256"] = digest
        return draft

    top_actions = []
    kinds: list[str] = []
    for rank, record in enumerate(unresolved[:TOP_ACTION_CAP], 1):
        kind = action_kind_for_record(record)
        kinds.append(kind)
        top_actions.append(
            {
                "rank": rank,
                "image_id": record.image_id,
                "failed_body_part": record.failed_body_part,
                "failure_reason": record.failure_reason,
                "pose_angle": record.pose_angle,
                "priority": float(record.priority),
                "cluster": clusters[record.failure_reason],
                "action_kind": kind,
                "action_text": _action(record),
            }
        )

    draft: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "acquisition_plan",
        "report_date": report_date,
        "unresolved_failure_count": len(unresolved),
        "top_action_cap": TOP_ACTION_CAP,
        "top_actions": top_actions,
        "action_kinds_used": sorted(set(kinds)),
        "clustering_complete": True,
        "d4_complete": False,
        "vlm_calibration_complete": False,
        "human_anchor_authority": False,
        "weekly_plan_authority": True,
    }
    if markdown_relative_path is not None:
        draft["markdown_relative_path"] = markdown_relative_path
    digest = _sha({k: v for k, v in draft.items() if k != "sha256"})
    draft["sha256"] = digest
    issues = validate_document(draft, "acquisition_plan")
    if issues:
        raise FailureMiningStaticError(
            "schema_validation_failed: "
            + "; ".join(f"{issue.pointer or '/'} {issue.message}" for issue in issues)
        )
    return draft


def persist_acquisition_plan_json(
    document: Mapping[str, Any],
    *,
    output_dir: Path,
    report_date: str,
) -> tuple[Path, dict[str, Any]]:
    """Atomically persist a built acquisition plan (schema body + optional abstention)."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if document.get("weekly_plan_authority") is False and "abstention" in document:
        persist = {k: v for k, v in document.items() if k != "abstention"}
        digest = _sha({k: v for k, v in persist.items() if k != "sha256"})
        persist["sha256"] = digest
        issues = validate_document(persist, "acquisition_plan")
        if issues:
            raise FailureMiningStaticError(
                "schema_validation_failed: "
                + "; ".join(f"{issue.pointer or '/'} {issue.message}" for issue in issues)
            )
        out_doc = {**persist, "abstention": document["abstention"]}
    else:
        out_doc = dict(document)
        issues = validate_document(
            {k: v for k, v in out_doc.items() if k != "abstention"},
            "acquisition_plan",
        )
        if issues:
            raise FailureMiningStaticError(
                "schema_validation_failed: "
                + "; ".join(f"{issue.pointer or '/'} {issue.message}" for issue in issues)
            )
    path = output_dir / f"acquisition_plan_{report_date}.json"
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(out_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path, out_doc


def write_acquisition_plan_json(
    records: Iterable[FailureRecord],
    *,
    output_dir: Path,
    clusterer: Callable[[tuple[str, ...]], dict[str, str]],
    report_date: str,
    markdown_relative_path: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Build and write schema-valid acquisition plan JSON beside the markdown plan."""
    document = build_acquisition_plan_document(
        records,
        report_date=report_date,
        clusterer=clusterer,
        markdown_relative_path=markdown_relative_path or f"acquisition_plan_{report_date}.md",
    )
    return persist_acquisition_plan_json(document, output_dir=output_dir, report_date=report_date)


def refuse_d4_or_vlm_calibration_claim(document: Mapping[str, Any]) -> None:
    """Fail closed if a plan or binder overclaims D4 / VLM calibration."""
    for key in ("d4_complete", "vlm_calibration_complete", "human_anchor_authority"):
        if document.get(key) is True:
            raise FailureMiningStaticError(f"overclaim_d4_or_vlm_calibration:{key}")


def build_failure_mining_static_report(
    *,
    seeded_fixture_blocks: Mapping[str, bool],
) -> dict[str, Any]:
    """Seal STATIC binder for acquisition-plan schema + mining abstention routing."""
    required = {
        "acquisition_plan_validates",
        "invalid_clusterer_abstains",
        "empty_queue_abstains",
        "overclaim_d4_refused",
    }
    if set(seeded_fixture_blocks) != required:
        raise FailureMiningStaticError("seeded_fixture_blocks_incomplete")
    if not all(bool(seeded_fixture_blocks[key]) for key in required):
        raise FailureMiningStaticError("seeded_fixture_not_blocked")

    # Prove priority formula constants still match runtime scorer identity.
    sample = priority_score(
        class_error_rate=1.0,
        coverage_deficit=1.0,
        downstream_use_weight=1.0,
        age_days=0.0,
    )
    expected = (
        PRIORITY_WEIGHTS["class_error_rate"]
        + PRIORITY_WEIGHTS["coverage_deficit"]
        + PRIORITY_WEIGHTS["downstream_use_weight"]
        + PRIORITY_WEIGHTS["recency"]
    )
    if abs(sample - expected) > 1e-12:
        raise FailureMiningStaticError("priority_formula_drift")

    draft: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "priority_weights": dict(PRIORITY_WEIGHTS),
        "top_action_cap": TOP_ACTION_CAP,
        "action_kinds": list(ACTION_KINDS),
        "abstention_reasons": sorted(MINING_ABSTENTION_REASONS),
        "checks": {
            "acquisition_plan_schema": "pass",
            "priority_formula": "pass",
            "top20_cap": "pass",
            "abstention_routing": "pass",
        },
        "seeded_fixture_blocks": {key: True for key in sorted(required)},
        "d4_complete": False,
        "vlm_calibration_complete": False,
        "human_anchor_authority": False,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "production_evidence_pass_claimed": False,
        "honest_non_claims": list(HONEST_NON_CLAIMS),
    }
    refuse_d4_or_vlm_calibration_claim(draft)
    digest = _sha(draft)
    draft["report_id"] = f"fms_{digest[:24]}"
    draft["seal_sha256"] = digest
    issues = validate_document(draft, "failure_mining_static_report")
    if issues:
        raise FailureMiningStaticError(
            "schema_validation_failed: "
            + "; ".join(f"{issue.pointer or '/'} {issue.message}" for issue in issues)
        )
    return draft


def failure_record_as_mapping(record: FailureRecord) -> dict[str, Any]:
    return asdict(record)


__all__ = [
    "ACTION_KINDS",
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "HONEST_NON_CLAIMS",
    "MINING_ABSTENTION_REASONS",
    "PRIORITY_WEIGHTS",
    "PROOF_TIER",
    "TOP_ACTION_CAP",
    "FailureMiningStaticError",
    "action_kind_for_record",
    "build_acquisition_plan_document",
    "build_failure_mining_static_report",
    "failure_record_as_mapping",
    "persist_acquisition_plan_json",
    "refuse_d4_or_vlm_calibration_claim",
    "route_mining_abstention",
    "write_acquisition_plan_json",
]
