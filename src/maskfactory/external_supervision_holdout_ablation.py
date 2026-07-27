"""STATIC real-holdout ablation gate for external source/label activation.

MF-P9-13.08 host-side contract. A source/label remains ablation-active only when a
frozen human-anchor holdout binding exists and the matched ablation is improve or
non-inferior without hard-bucket, identity, boundary, or calibration regressions.

Live holdout execution and gold claims remain out of scope for STATIC_PASS.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .external_supervision import EXTERNAL_LABEL_ROLE
from .truth_tiers import HUMAN_ANCHOR_GOLD, WEIGHTED_PSEUDO_LABEL
from .validation import ArtifactValidationError, require_valid_document

PROOF_TIER = "STATIC_PASS"
AUTHORITY = "external_supervision_holdout_ablation_static_only_no_live_holdout"
SCHEMA_VERSION = "1.0.0"
ARTIFACT_TYPE = "external_supervision_holdout_ablation_report"
REGRESSION_BUCKETS = ("hard_bucket", "identity", "boundary", "calibration")
HOLDOUT_PARTITIONS = frozenset({"holdout", "test_holdout", "hard_case_holdout"})


class ExternalHoldoutAblationError(ValueError):
    """External holdout ablation contract violated."""


@dataclass(frozen=True)
class AblationDecision:
    source: str
    label_scope: tuple[str, ...]
    active: bool
    reason: str
    primary_metric: str
    observed_delta: float
    noninferiority_margin: float


def _canonical_sha256(document: Mapping[str, Any]) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def require_frozen_human_anchor_holdout(binding: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed unless a frozen human-anchor holdout fingerprint is bound."""

    if not isinstance(binding, Mapping):
        raise ExternalHoldoutAblationError("frozen human-anchor holdout binding missing")
    holdout_id = binding.get("frozen_holdout_id")
    fingerprint = binding.get("fingerprint_sha256")
    truth_tier = binding.get("truth_tier")
    partition = binding.get("truth_partition")
    source_role = binding.get("source_role")
    if not isinstance(holdout_id, str) or not holdout_id.strip():
        raise ExternalHoldoutAblationError("frozen_holdout_id missing")
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(ch not in "0123456789abcdef" for ch in fingerprint)
    ):
        raise ExternalHoldoutAblationError("frozen holdout fingerprint_sha256 invalid")
    if truth_tier != HUMAN_ANCHOR_GOLD:
        raise ExternalHoldoutAblationError("holdout ablation requires truth_tier=human_anchor_gold")
    if partition not in HOLDOUT_PARTITIONS:
        raise ExternalHoldoutAblationError(
            "holdout ablation requires a frozen holdout/test partition"
        )
    if source_role in {EXTERNAL_LABEL_ROLE, "synthetic_geometry_exact", "synthetic"}:
        raise ExternalHoldoutAblationError(
            "holdout ablation cannot bind external or synthetic holdout authority"
        )
    if binding.get("external_labels_may_enter_holdout") is True:
        raise ExternalHoldoutAblationError(
            "holdout ablation refuses external_labels_may_enter_holdout=true"
        )
    return {
        "frozen_holdout_id": holdout_id,
        "fingerprint_sha256": fingerprint,
        "truth_tier": truth_tier,
        "truth_partition": partition,
        "source_role": source_role,
    }


def _normalize_label_scope(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ExternalHoldoutAblationError("mapped label_scope missing")
    labels: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ExternalHoldoutAblationError("mapped label_scope contains invalid label")
        labels.append(item)
    if len(set(labels)) != len(labels):
        raise ExternalHoldoutAblationError("mapped label_scope has duplicate labels")
    return tuple(sorted(labels))


def _validate_regression_buckets(row: Mapping[str, Any]) -> None:
    buckets = row.get("regression_buckets")
    if not isinstance(buckets, Mapping):
        raise ExternalHoldoutAblationError("regression_buckets missing")
    if set(buckets) != set(REGRESSION_BUCKETS):
        raise ExternalHoldoutAblationError(
            f"regression_buckets must be exactly {list(REGRESSION_BUCKETS)}"
        )
    for name in REGRESSION_BUCKETS:
        entry = buckets[name]
        if not isinstance(entry, Mapping):
            raise ExternalHoldoutAblationError(f"regression bucket invalid: {name}")
        if entry.get("passed") is not True:
            raise ExternalHoldoutAblationError(f"regression bucket failed: {name}")
        delta = entry.get("observed_delta")
        margin = entry.get("noninferiority_margin")
        if not isinstance(delta, (int, float)) or isinstance(delta, bool):
            raise ExternalHoldoutAblationError(f"regression bucket delta invalid: {name}")
        if not isinstance(margin, (int, float)) or isinstance(margin, bool) or float(margin) < 0:
            raise ExternalHoldoutAblationError(f"regression bucket margin invalid: {name}")
        if float(delta) < -float(margin):
            raise ExternalHoldoutAblationError(f"regression bucket non-inferiority failed: {name}")


def evaluate_source_label_ablation(
    row: Mapping[str, Any],
    *,
    holdout: Mapping[str, Any],
) -> AblationDecision:
    """Decide whether one source/label-scope ablation may remain active."""

    bound = require_frozen_human_anchor_holdout(holdout)
    if not isinstance(row, Mapping):
        raise ExternalHoldoutAblationError("ablation row missing")
    source = row.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ExternalHoldoutAblationError("ablation source missing")
    label_scope = _normalize_label_scope(row.get("label_scope"))
    metric = row.get("primary_metric")
    if not isinstance(metric, str) or not metric.strip():
        raise ExternalHoldoutAblationError("primary_metric missing")
    delta = row.get("observed_delta")
    margin = row.get("noninferiority_margin")
    if not isinstance(delta, (int, float)) or isinstance(delta, bool):
        raise ExternalHoldoutAblationError("observed_delta invalid")
    if not isinstance(margin, (int, float)) or isinstance(margin, bool) or float(margin) < 0:
        raise ExternalHoldoutAblationError("noninferiority_margin invalid")
    row_holdout = row.get("frozen_holdout_fingerprint_sha256")
    if row_holdout != bound["fingerprint_sha256"]:
        raise ExternalHoldoutAblationError(
            "ablation row is not bound to the frozen holdout fingerprint"
        )
    if row.get("truth_tier") not in {None, WEIGHTED_PSEUDO_LABEL}:
        raise ExternalHoldoutAblationError(
            "ablation row cannot claim non-pseudo training authority"
        )
    if row.get("counts_as_human_anchor_gold") not in {None, False}:
        raise ExternalHoldoutAblationError("ablation row cannot claim human-anchor gold")

    try:
        _validate_regression_buckets(row)
        primary_ok = float(delta) >= -float(margin)
        if not primary_ok:
            raise ExternalHoldoutAblationError("primary metric non-inferiority failed")
    except ExternalHoldoutAblationError as exc:
        return AblationDecision(
            source=source,
            label_scope=label_scope,
            active=False,
            reason=str(exc),
            primary_metric=metric,
            observed_delta=float(delta),
            noninferiority_margin=float(margin),
        )

    return AblationDecision(
        source=source,
        label_scope=label_scope,
        active=True,
        reason="non_regressing_or_non_inferior_on_frozen_human_anchor_holdout",
        primary_metric=metric,
        observed_delta=float(delta),
        noninferiority_margin=float(margin),
    )


def decide_active_external_supervision(
    *,
    holdout: Mapping[str, Any],
    ablations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Seal an ablation report that keeps only non-regressing source/label scopes active."""

    bound = require_frozen_human_anchor_holdout(holdout)
    if not isinstance(ablations, Sequence) or not ablations:
        raise ExternalHoldoutAblationError("ablation rows missing")

    decisions: list[AblationDecision] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for row in ablations:
        decision = evaluate_source_label_ablation(row, holdout=bound)
        key = (decision.source, decision.label_scope)
        if key in seen:
            raise ExternalHoldoutAblationError(
                f"duplicate ablation scope: {decision.source}/{list(decision.label_scope)}"
            )
        seen.add(key)
        decisions.append(decision)

    active = [
        {
            "source": item.source,
            "label_scope": list(item.label_scope),
            "primary_metric": item.primary_metric,
            "observed_delta": item.observed_delta,
            "noninferiority_margin": item.noninferiority_margin,
            "reason": item.reason,
        }
        for item in decisions
        if item.active
    ]
    inactive = [
        {
            "source": item.source,
            "label_scope": list(item.label_scope),
            "primary_metric": item.primary_metric,
            "observed_delta": item.observed_delta,
            "noninferiority_margin": item.noninferiority_margin,
            "reason": item.reason,
        }
        for item in decisions
        if not item.active
    ]
    core = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "live_holdout_executed": False,
        "admission_ready": False,
        "any_source_admitted_live": False,
        "gold_claimed": False,
        "frozen_holdout": bound,
        "active_source_label_scopes": active,
        "inactive_source_label_scopes": inactive,
        "active_count": len(active),
        "inactive_count": len(inactive),
    }
    report = {**core, "seal_sha256": _canonical_sha256(core)}
    return report


def active_scope_keys(report: Mapping[str, Any]) -> set[tuple[str, tuple[str, ...]]]:
    require_ablation_report(report)
    keys: set[tuple[str, tuple[str, ...]]] = set()
    for row in report.get("active_source_label_scopes", ()):
        if not isinstance(row, Mapping):
            raise ExternalHoldoutAblationError("active scope row invalid")
        source = row.get("source")
        if not isinstance(source, str):
            raise ExternalHoldoutAblationError("active scope source invalid")
        keys.add((source, _normalize_label_scope(row.get("label_scope"))))
    return keys


def require_ablation_report(report: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(report, Mapping):
        raise ExternalHoldoutAblationError("ablation report missing")
    try:
        require_valid_document(dict(report), "external_supervision_holdout_ablation_report")
    except ArtifactValidationError as exc:
        raise ExternalHoldoutAblationError(f"ablation report schema invalid: {exc}") from exc
    if report.get("schema_version") != SCHEMA_VERSION:
        raise ExternalHoldoutAblationError("ablation report schema_version invalid")
    if report.get("artifact_type") != ARTIFACT_TYPE:
        raise ExternalHoldoutAblationError("ablation report artifact_type invalid")
    if report.get("proof_tier") != PROOF_TIER:
        raise ExternalHoldoutAblationError("ablation report proof_tier invalid")
    if report.get("live_holdout_executed") is True:
        raise ExternalHoldoutAblationError(
            "STATIC ablation report cannot claim live_holdout_executed"
        )
    if report.get("gold_claimed") is True:
        raise ExternalHoldoutAblationError("ablation report cannot claim gold")
    if report.get("admission_ready") is True:
        raise ExternalHoldoutAblationError("STATIC ablation report cannot set admission_ready=true")
    require_frozen_human_anchor_holdout(report.get("frozen_holdout", {}))
    payload = {key: value for key, value in report.items() if key != "seal_sha256"}
    if report.get("seal_sha256") != _canonical_sha256(payload):
        raise ExternalHoldoutAblationError("ablation report seal_sha256 mismatch")
    return report


def discover_holdout_ablation_report(packages_root: Path | str) -> dict[str, Any] | None:
    """Load a sealed ablation report beside a package batch, if present."""

    root = Path(packages_root)
    for candidate in (
        root / "holdout_ablation_report.json",
        root.parent / "holdout_ablation_report.json",
    ):
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExternalHoldoutAblationError(
                f"holdout ablation report unreadable: {candidate}"
            ) from exc
        return dict(require_ablation_report(payload))
    return None


def assert_only_ablation_active_external_rows(
    rows: Iterable[Mapping[str, Any]],
    report: Mapping[str, Any] | None,
) -> None:
    """Refuse external rows that claim ablation_active without a matching active scope."""

    active_keys: set[tuple[str, tuple[str, ...]]] | None = None
    if report is not None:
        active_keys = active_scope_keys(report)

    for row in rows:
        if row.get("source_role") != EXTERNAL_LABEL_ROLE:
            if row.get("ablation_active") is True:
                raise ExternalHoldoutAblationError("non-external row cannot claim ablation_active")
            continue
        claimed = row.get("ablation_active")
        if claimed is True:
            if active_keys is None:
                raise ExternalHoldoutAblationError(
                    "ablation_active claimed without sealed holdout ablation report"
                )
            source = row.get("external_source") or row.get("source")
            if isinstance(source, Mapping):
                source = source.get("external_source") or source.get("source")
            labels = row.get("label_names") or row.get("label_scope")
            if not isinstance(source, str):
                raise ExternalHoldoutAblationError("ablation_active external row missing source")
            key = (source, _normalize_label_scope(labels))
            if key not in active_keys:
                raise ExternalHoldoutAblationError(
                    f"ablation-inactive external scope cannot train: {source}/{list(key[1])}"
                )
        elif claimed not in {None, False}:
            raise ExternalHoldoutAblationError("ablation_active must be bool or omitted")


def filter_active_selections(
    selections: Sequence[Mapping[str, Any]],
    report: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    """Return only selections whose source/label scope remained active."""

    keys = active_scope_keys(report)
    kept: list[Mapping[str, Any]] = []
    for selection in selections:
        source = selection.get("source")
        labels = selection.get("label_names") or selection.get("label_scope")
        if not isinstance(source, str):
            raise ExternalHoldoutAblationError("selection source missing")
        key = (source, _normalize_label_scope(labels))
        if key in keys:
            kept.append(selection)
    return kept


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "AblationDecision",
    "ExternalHoldoutAblationError",
    "PROOF_TIER",
    "REGRESSION_BUCKETS",
    "SCHEMA_VERSION",
    "active_scope_keys",
    "assert_only_ablation_active_external_rows",
    "decide_active_external_supervision",
    "discover_holdout_ablation_report",
    "evaluate_source_label_ablation",
    "filter_active_selections",
    "require_ablation_report",
    "require_frozen_human_anchor_holdout",
]
