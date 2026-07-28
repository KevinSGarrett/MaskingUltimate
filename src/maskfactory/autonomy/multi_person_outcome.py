"""Seal multi-person tournament decisions into lifecycle and routing evidence.

The bridge deliberately performs no serving, publication, training, audit selection,
or gold finalization.  It proves that downstream lifecycle and route documents are
exact projections of a source-recomputed tournament execution report.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..io.hashing import sha256_file
from ..serve.routing import build_certificate_aware_serving_route
from ..validation import ArtifactValidationError, require_valid_document
from .lifecycle import verified_lifecycle_winner_mask
from .multi_person_availability import (
    DEFAULT_MODEL_REGISTRY,
    DEFAULT_POLICY,
    DEFAULT_RUNTIME_MATRIX,
)
from .multi_person_evidence import DEFAULT_AUTONOMY_CONFIG
from .multi_person_execution import (
    TargetTournamentControl,
    load_verified_multi_person_tournament_execution,
)
from .multi_person_gate import MultiPersonCandidateGateResult

OUTCOME_AUTHORITY = (
    "multi_person_lifecycle_routing_evidence_only_"
    "no_serving_publication_training_audit_gold_or_completion_authority"
)
MEASUREMENT_AUTHORITY = "receipt_identity_only_no_headline_metric_or_performance_authority"


class MultiPersonOutcomeError(ValueError):
    """Execution, lifecycle, certificate, route, or snapshot evidence was rebound."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _atomic_json(path: Path, document: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _evaluated_at(value: datetime) -> tuple[str, datetime]:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise MultiPersonOutcomeError("evaluated_at must be a timezone-aware datetime")
    normalized = value.astimezone(UTC)
    return normalized.isoformat().replace("+00:00", "Z"), normalized


def _revocation_snapshot(root: Path) -> dict[str, Any]:
    resolved = Path(root).resolve()
    files = []
    if resolved.is_dir():
        for path in sorted(item for item in resolved.rglob("*") if item.is_file()):
            relative = path.resolve().relative_to(resolved).as_posix()
            files.append({"path": relative, "sha256": sha256_file(path)})
    snapshot = {"root_exists": resolved.is_dir(), "files": files}
    snapshot["sha256"] = _canonical_sha256(snapshot)
    return snapshot


def _target_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(row["person_id"]), str(row["instance_id"]), str(row["label"])


def _require_exact_lifecycle(
    lifecycle: Mapping[str, Any],
    *,
    lifecycle_path: Path,
    execution: Mapping[str, Any],
    target: Mapping[str, Any],
) -> None:
    try:
        require_valid_document(lifecycle, "autonomy_lifecycle")
    except ArtifactValidationError as exc:
        raise MultiPersonOutcomeError(f"invalid lifecycle: {exc}") from exc
    decision = target["decision"]
    identity = {
        "image_id": execution["image_id"],
        "instance_id": target["promoted_instance_id"],
        "label": target["label"],
        "context": target["semantic_context"],
        "pipeline_fingerprint": execution["pipeline_fingerprint"],
    }
    if any(lifecycle.get(key) != value for key, value in identity.items()):
        raise MultiPersonOutcomeError("lifecycle target identity differs from execution")
    projection = {
        "status": decision["status"],
        "truth_tier": decision["truth_tier"],
        "training_loss_weight": decision["training_loss_weight"],
        "winner_id": decision["winner_id"],
        "winner_score": decision["winner_score"],
        "certificate_valid": decision["certificate_valid"],
        "certificate_reason": decision["certificate_reason"],
        "human_audit_required": decision["human_audit_required"],
        "reason": decision["reason"],
    }
    if any(lifecycle.get(key) != value for key, value in projection.items()):
        raise MultiPersonOutcomeError("lifecycle decision differs from execution")
    expected_eligible = decision["truth_tier"] == "autonomous_certified_gold"
    if (
        lifecycle["authoritative_human_gold"] is not False
        or lifecycle["serve_eligible"] is not expected_eligible
        or lifecycle["pseudo_train_eligible"] is not expected_eligible
        or lifecycle["holdout_eligible"] is not False
    ):
        raise MultiPersonOutcomeError("lifecycle authority differs from tournament truth tier")
    expected_ranking = [
        {
            "candidate_id": row["candidate_id"],
            "score": row["score"],
            "eligible": row["eligible"],
            "vetoes": row["vetoes"],
            "mask_sha256": row["mask_sha256"],
        }
        for row in decision["ranking"]
    ]
    if lifecycle["ranking"] != expected_ranking:
        raise MultiPersonOutcomeError("lifecycle ranking differs from execution")
    if decision["winner_id"] is None:
        if lifecycle["winner_mask_path"] is not None or lifecycle["winner_mask_sha256"] is not None:
            raise MultiPersonOutcomeError("winnerless lifecycle carries a mask")
        return
    winner_rows = [
        row for row in decision["ranking"] if row["candidate_id"] == decision["winner_id"]
    ]
    if len(winner_rows) != 1 or lifecycle["winner_mask_sha256"] != winner_rows[0]["mask_sha256"]:
        raise MultiPersonOutcomeError("lifecycle winner mask differs from execution")
    try:
        verified_lifecycle_winner_mask(dict(lifecycle), Path(lifecycle_path).parent)
    except (ArtifactValidationError, ValueError) as exc:
        raise MultiPersonOutcomeError(
            f"lifecycle winner artifact failed verification: {exc}"
        ) from exc


def _build_report(
    execution_report_path: Path,
    *,
    evidence_manifest_path: Path,
    artifact_root: Path,
    expected_pipeline_fingerprint: str,
    controls: Mapping[tuple[str, str, str], TargetTournamentControl],
    gate: MultiPersonCandidateGateResult,
    lifecycle_paths: Mapping[tuple[str, str, str], Path],
    revocations_root: Path,
    selected_for_audit: bool,
    evaluated_at: datetime,
    source_image_path: Path | None,
    config_path: Path,
    availability_policy_path: Path,
    model_registry_path: Path,
    runtime_matrix_path: Path,
) -> dict[str, Any]:
    if not isinstance(selected_for_audit, bool):
        raise MultiPersonOutcomeError("selected_for_audit must be boolean")
    evaluated_at_text, evaluated_at_value = _evaluated_at(evaluated_at)
    execution = load_verified_multi_person_tournament_execution(
        execution_report_path,
        evidence_manifest_path=evidence_manifest_path,
        artifact_root=artifact_root,
        expected_pipeline_fingerprint=expected_pipeline_fingerprint,
        controls=controls,
        gate=gate,
        source_image_path=source_image_path,
        config_path=config_path,
        availability_policy_path=availability_policy_path,
        model_registry_path=model_registry_path,
        runtime_matrix_path=runtime_matrix_path,
    )
    targets = {_target_key(row): row for row in execution["targets"]}
    if len(targets) != len(execution["targets"]):
        raise MultiPersonOutcomeError("execution target identity is duplicated")
    if set(lifecycle_paths) != set(targets) or set(controls) != set(targets):
        raise MultiPersonOutcomeError(
            "lifecycle and control keys must exactly cover execution targets"
        )

    snapshot = _revocation_snapshot(revocations_root)
    rows = []
    for key in sorted(targets):
        target = targets[key]
        lifecycle_path = Path(lifecycle_paths[key])
        if not lifecycle_path.is_file():
            raise MultiPersonOutcomeError(f"lifecycle file is absent: {lifecycle_path}")
        lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
        if not isinstance(lifecycle, Mapping):
            raise MultiPersonOutcomeError("lifecycle document must be an object")
        _require_exact_lifecycle(
            lifecycle,
            lifecycle_path=lifecycle_path,
            execution=execution,
            target=target,
        )
        certificate = controls[key].certificate
        certificate_document_sha256 = (
            _canonical_sha256(dict(certificate)) if certificate is not None else None
        )
        certificate_claimed_sha256 = certificate.get("sha256") if certificate is not None else None
        if (
            certificate_document_sha256 != target["certificate_document_sha256"]
            or certificate_claimed_sha256 != target["certificate_claimed_sha256"]
        ):
            raise MultiPersonOutcomeError("route certificate differs from execution")
        route = build_certificate_aware_serving_route(
            lifecycle,
            certificate,
            expected_pipeline_fingerprint=expected_pipeline_fingerprint,
            selected_for_audit=selected_for_audit,
            revocations_root=revocations_root,
            now=evaluated_at_value,
        )
        rows.append(
            {
                "person_id": key[0],
                "instance_id": key[1],
                "label": key[2],
                "promoted_instance_id": target["promoted_instance_id"],
                "lifecycle_file_sha256": sha256_file(lifecycle_path),
                "lifecycle_document_sha256": _canonical_sha256(lifecycle),
                "certificate_document_sha256": certificate_document_sha256,
                "certificate_claimed_sha256": certificate_claimed_sha256,
                "tournament_status": target["decision"]["status"],
                "route": route,
                "route_sha256": _canonical_sha256(route),
            }
        )

    destinations = Counter(row["route"]["routing"]["destination"] for row in rows)
    residual_count = destinations["cvat_residual_review"]
    image_truth_partition = "residual" if residual_count else "train"
    instance_partitions = {
        instance_id: image_truth_partition
        for instance_id in execution["gate"]["promoted_instances"]
    }
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "evaluated_at": evaluated_at_text,
        "image_id": execution["image_id"],
        "source_image_sha256": execution["source_image_sha256"],
        "instance_context": execution["instance_context"],
        "pipeline_fingerprint": execution["pipeline_fingerprint"],
        "execution_report_sha256": execution["sha256"],
        "revocation_snapshot": snapshot,
        "selected_for_audit": selected_for_audit,
        "image_truth_partition": image_truth_partition,
        "instance_truth_partitions": instance_partitions,
        "target_count": len(rows),
        "served_target_count": destinations["served_without_routine_review"],
        "residual_target_count": residual_count,
        "audit_target_count": destinations["cvat_preselected_audit"],
        "targets": rows,
        "measurement_binding": {
            "source_image_sha256": execution["source_image_sha256"],
            "execution_report_sha256": execution["sha256"],
            "target_route_sha256s": [row["route_sha256"] for row in rows],
            "preselected_audit": selected_for_audit,
            "authority": MEASUREMENT_AUTHORITY,
        },
        "authority": OUTCOME_AUTHORITY,
    }
    report["sha256"] = _canonical_sha256(report)
    try:
        require_valid_document(report, "multi_person_lifecycle_route")
    except ArtifactValidationError as exc:
        raise MultiPersonOutcomeError(str(exc)) from exc
    return report


def write_multi_person_lifecycle_route(
    execution_report_path: Path,
    *,
    evidence_manifest_path: Path,
    artifact_root: Path,
    expected_pipeline_fingerprint: str,
    controls: Mapping[tuple[str, str, str], TargetTournamentControl],
    gate: MultiPersonCandidateGateResult,
    lifecycle_paths: Mapping[tuple[str, str, str], Path],
    revocations_root: Path,
    selected_for_audit: bool,
    evaluated_at: datetime,
    output_path: Path,
    source_image_path: Path | None = None,
    config_path: Path = DEFAULT_AUTONOMY_CONFIG,
    availability_policy_path: Path = DEFAULT_POLICY,
    model_registry_path: Path = DEFAULT_MODEL_REGISTRY,
    runtime_matrix_path: Path = DEFAULT_RUNTIME_MATRIX,
) -> Path:
    """Build and atomically write one exact execution-to-route evidence bridge."""
    report = _build_report(
        execution_report_path,
        evidence_manifest_path=evidence_manifest_path,
        artifact_root=artifact_root,
        expected_pipeline_fingerprint=expected_pipeline_fingerprint,
        controls=controls,
        gate=gate,
        lifecycle_paths=lifecycle_paths,
        revocations_root=revocations_root,
        selected_for_audit=selected_for_audit,
        evaluated_at=evaluated_at,
        source_image_path=source_image_path,
        config_path=config_path,
        availability_policy_path=availability_policy_path,
        model_registry_path=model_registry_path,
        runtime_matrix_path=runtime_matrix_path,
    )
    _atomic_json(output_path, report)
    verify_multi_person_lifecycle_route(
        output_path,
        execution_report_path=execution_report_path,
        evidence_manifest_path=evidence_manifest_path,
        artifact_root=artifact_root,
        expected_pipeline_fingerprint=expected_pipeline_fingerprint,
        controls=controls,
        gate=gate,
        lifecycle_paths=lifecycle_paths,
        revocations_root=revocations_root,
        selected_for_audit=selected_for_audit,
        evaluated_at=evaluated_at,
        source_image_path=source_image_path,
        config_path=config_path,
        availability_policy_path=availability_policy_path,
        model_registry_path=model_registry_path,
        runtime_matrix_path=runtime_matrix_path,
    )
    return Path(output_path)


def verify_multi_person_lifecycle_route(
    report_path: Path,
    *,
    execution_report_path: Path,
    evidence_manifest_path: Path,
    artifact_root: Path,
    expected_pipeline_fingerprint: str,
    controls: Mapping[tuple[str, str, str], TargetTournamentControl],
    gate: MultiPersonCandidateGateResult,
    lifecycle_paths: Mapping[tuple[str, str, str], Path],
    revocations_root: Path,
    selected_for_audit: bool,
    evaluated_at: datetime,
    source_image_path: Path | None = None,
    config_path: Path = DEFAULT_AUTONOMY_CONFIG,
    availability_policy_path: Path = DEFAULT_POLICY,
    model_registry_path: Path = DEFAULT_MODEL_REGISTRY,
    runtime_matrix_path: Path = DEFAULT_RUNTIME_MATRIX,
) -> dict[str, Any]:
    """Recompute the source execution, lifecycle routes, and revocation snapshot exactly."""
    actual = json.loads(Path(report_path).read_text(encoding="utf-8"))
    try:
        require_valid_document(actual, "multi_person_lifecycle_route")
    except ArtifactValidationError as exc:
        raise MultiPersonOutcomeError(str(exc)) from exc
    payload = {key: value for key, value in actual.items() if key != "sha256"}
    if actual["sha256"] != _canonical_sha256(payload):
        raise MultiPersonOutcomeError("multi-person lifecycle route hash mismatch")
    expected = _build_report(
        execution_report_path,
        evidence_manifest_path=evidence_manifest_path,
        artifact_root=artifact_root,
        expected_pipeline_fingerprint=expected_pipeline_fingerprint,
        controls=controls,
        gate=gate,
        lifecycle_paths=lifecycle_paths,
        revocations_root=revocations_root,
        selected_for_audit=selected_for_audit,
        evaluated_at=evaluated_at,
        source_image_path=source_image_path,
        config_path=config_path,
        availability_policy_path=availability_policy_path,
        model_registry_path=model_registry_path,
        runtime_matrix_path=runtime_matrix_path,
    )
    if actual != expected:
        raise MultiPersonOutcomeError("multi-person lifecycle route recomputation mismatch")
    return {
        "image_id": actual["image_id"],
        "target_count": actual["target_count"],
        "served_target_count": actual["served_target_count"],
        "residual_target_count": actual["residual_target_count"],
        "audit_target_count": actual["audit_target_count"],
        "sha256": actual["sha256"],
        "authority": OUTCOME_AUTHORITY,
    }


__all__ = [
    "MEASUREMENT_AUTHORITY",
    "OUTCOME_AUTHORITY",
    "MultiPersonOutcomeError",
    "verify_multi_person_lifecycle_route",
    "write_multi_person_lifecycle_route",
]
