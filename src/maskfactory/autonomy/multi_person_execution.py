"""Execute verified multi-person candidates through the existing per-target tournament."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..validation import ArtifactValidationError, require_valid_document
from .calibration import load_autonomy_config
from .multi_person_availability import (
    DEFAULT_MODEL_REGISTRY,
    DEFAULT_POLICY,
    DEFAULT_RUNTIME_MATRIX,
)
from .multi_person_evidence import (
    DEFAULT_AUTONOMY_CONFIG,
    load_multi_person_tournament_candidates,
)
from .multi_person_gate import MultiPersonCandidateGateResult
from .multi_person_scope import MultiPersonCertificationScopeResult
from .tournament import TournamentDecision, run_candidate_tournament

EXECUTION_AUTHORITY = (
    "multi_person_tournament_decision_evidence_only_"
    "no_finalization_serving_training_or_gold_authority"
)
MANDATORY_GATE_CHECKS = ("QC-035", "QC-036", "AUT-MP-001", "AUT-MP-002", "AUT-MP-003")


class MultiPersonExecutionError(ValueError):
    """Target identity, gate/scope input, or decision evidence is incomplete or rebound."""


@dataclass(frozen=True)
class TargetTournamentControl:
    promoted_instance_id: str
    semantic_context: str
    scope: MultiPersonCertificationScopeResult
    certificate: Mapping[str, Any] | None = None


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _atomic_json(path: Path, document: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _decision_document(decision: TournamentDecision) -> dict[str, Any]:
    return {
        "status": decision.status,
        "truth_tier": decision.truth_tier,
        "training_loss_weight": decision.training_loss_weight,
        "winner_id": decision.winner_id,
        "winner_score": decision.winner_score,
        "runner_up_score": decision.runner_up_score,
        "certificate_valid": decision.certificate_valid,
        "certificate_reason": decision.certificate_reason,
        "human_audit_required": decision.human_audit_required,
        "authoritative_gold": decision.authoritative_gold,
        "reason": decision.reason,
        "ranking": [
            {
                "candidate_id": row.candidate_id,
                "mask_sha256": row.evidence.mask_sha256,
                "score": row.score,
                "eligible": row.eligible,
                "vetoes": list(row.vetoes),
                "independent_sources": row.evidence.independent_sources,
                "source_provider_keys": list(row.evidence.source_provider_keys),
                "source_model_families": list(row.evidence.source_model_families),
            }
            for row in decision.ranking
        ],
    }


def _build_report(
    *,
    evidence_manifest_path: Path,
    artifact_root: Path,
    expected_pipeline_fingerprint: str,
    controls: Mapping[tuple[str, str, str], TargetTournamentControl],
    gate: MultiPersonCandidateGateResult,
    source_image_path: Path | None,
    config_path: Path,
    availability_policy_path: Path,
    model_registry_path: Path,
    runtime_matrix_path: Path,
) -> dict[str, Any]:
    candidates = load_multi_person_tournament_candidates(
        evidence_manifest_path,
        artifact_root=artifact_root,
        expected_pipeline_fingerprint=expected_pipeline_fingerprint,
        source_image_path=source_image_path,
        config_path=config_path,
        availability_policy_path=availability_policy_path,
        model_registry_path=model_registry_path,
        runtime_matrix_path=runtime_matrix_path,
    )
    evidence_document = json.loads(Path(evidence_manifest_path).read_text(encoding="utf-8"))
    if set(controls) != set(candidates):
        raise MultiPersonExecutionError("tournament controls do not exactly cover evidence targets")
    instance_context = evidence_document["instance_context"]
    if gate.instance_context != instance_context:
        raise MultiPersonExecutionError("image gate context differs from evidence context")
    if len(gate.promoted_instances) != len(set(gate.promoted_instances)):
        raise MultiPersonExecutionError("image gate promoted-instance identity is duplicated")
    expected_instances = tuple(f"p{index}" for index in range(len(gate.promoted_instances)))
    if gate.promoted_instances != expected_instances:
        raise MultiPersonExecutionError("image gate promoted instances are not contiguous p0..pN")
    if tuple(check.check_id for check in gate.checks) != MANDATORY_GATE_CHECKS:
        raise MultiPersonExecutionError("image gate does not contain the exact mandatory checks")
    person_mapping: dict[str, str] = {}
    for target, control in controls.items():
        person_id = target[0]
        prior = person_mapping.setdefault(person_id, control.promoted_instance_id)
        if prior != control.promoted_instance_id:
            raise MultiPersonExecutionError("one person is rebound to multiple promoted instances")
    if set(person_mapping.values()) != set(gate.promoted_instances) or len(
        set(person_mapping.values())
    ) != len(person_mapping):
        raise MultiPersonExecutionError("target people do not bijectively cover promoted instances")
    config = load_autonomy_config(config_path)
    rows = []
    for target in sorted(candidates):
        control = controls[target]
        if not control.semantic_context:
            raise MultiPersonExecutionError("target semantic context is empty")
        if (
            control.scope.instance_context != instance_context
            or control.scope.pipeline_fingerprint != expected_pipeline_fingerprint
        ):
            raise MultiPersonExecutionError("target certification scope identity is rebound")
        decision = run_candidate_tournament(
            candidates[target],
            label=target[2],
            context=control.semantic_context,
            pipeline_fingerprint=expected_pipeline_fingerprint,
            config=config,
            certificate=dict(control.certificate) if control.certificate is not None else None,
            instance_context=instance_context,
            multi_person_gate=gate,
            multi_person_scope=control.scope,
        )
        rows.append(
            {
                "person_id": target[0],
                "instance_id": target[1],
                "label": target[2],
                "promoted_instance_id": control.promoted_instance_id,
                "semantic_context": control.semantic_context,
                "risk_bucket": control.scope.risk_bucket,
                "scope": {
                    **asdict(control.scope),
                    "blockers": list(control.scope.blockers),
                    "passed": control.scope.passed,
                },
                "certificate_document_sha256": (
                    _canonical_sha256(dict(control.certificate))
                    if control.certificate is not None
                    else None
                ),
                "certificate_claimed_sha256": (
                    control.certificate.get("sha256") if control.certificate is not None else None
                ),
                "decision": _decision_document(decision),
            }
        )
    status_counts = dict(sorted(Counter(row["decision"]["status"] for row in rows).items()))
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "image_id": evidence_document["image_id"],
        "source_image_sha256": evidence_document["source_image_sha256"],
        "instance_context": instance_context,
        "pipeline_fingerprint": expected_pipeline_fingerprint,
        "evidence_manifest_sha256": evidence_document["sha256"],
        "availability_snapshot_sha256": evidence_document["availability_snapshot"]["sha256"],
        "gate": {
            "instance_context": gate.instance_context,
            "promoted_instances": list(gate.promoted_instances),
            "passed": gate.passed,
            "checks": [asdict(check) for check in gate.checks],
        },
        "target_count": len(rows),
        "status_counts": status_counts,
        "targets": rows,
        "authority": EXECUTION_AUTHORITY,
    }
    report["sha256"] = _canonical_sha256(report)
    try:
        require_valid_document(report, "multi_person_tournament_execution")
    except ArtifactValidationError as exc:
        raise MultiPersonExecutionError(str(exc)) from exc
    return report


def write_multi_person_tournament_execution(
    *,
    evidence_manifest_path: Path,
    artifact_root: Path,
    expected_pipeline_fingerprint: str,
    controls: Mapping[tuple[str, str, str], TargetTournamentControl],
    gate: MultiPersonCandidateGateResult,
    output_path: Path,
    source_image_path: Path | None = None,
    config_path: Path = DEFAULT_AUTONOMY_CONFIG,
    availability_policy_path: Path = DEFAULT_POLICY,
    model_registry_path: Path = DEFAULT_MODEL_REGISTRY,
    runtime_matrix_path: Path = DEFAULT_RUNTIME_MATRIX,
) -> Path:
    """Execute and seal every target decision without changing downstream authority."""
    report = _build_report(
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
    _atomic_json(output_path, report)
    verify_multi_person_tournament_execution(
        output_path,
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
    return Path(output_path)


def verify_multi_person_tournament_execution(
    report_path: Path,
    *,
    evidence_manifest_path: Path,
    artifact_root: Path,
    expected_pipeline_fingerprint: str,
    controls: Mapping[tuple[str, str, str], TargetTournamentControl],
    gate: MultiPersonCandidateGateResult,
    source_image_path: Path | None = None,
    config_path: Path = DEFAULT_AUTONOMY_CONFIG,
    availability_policy_path: Path = DEFAULT_POLICY,
    model_registry_path: Path = DEFAULT_MODEL_REGISTRY,
    runtime_matrix_path: Path = DEFAULT_RUNTIME_MATRIX,
) -> dict[str, Any]:
    """Recompute every decision and require byte-equivalent structured evidence."""
    actual = load_verified_multi_person_tournament_execution(
        report_path,
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
    return {
        "image_id": actual["image_id"],
        "target_count": actual["target_count"],
        "status_counts": actual["status_counts"],
        "sha256": actual["sha256"],
        "authority": EXECUTION_AUTHORITY,
    }


def load_verified_multi_person_tournament_execution(
    report_path: Path,
    *,
    evidence_manifest_path: Path,
    artifact_root: Path,
    expected_pipeline_fingerprint: str,
    controls: Mapping[tuple[str, str, str], TargetTournamentControl],
    gate: MultiPersonCandidateGateResult,
    source_image_path: Path | None = None,
    config_path: Path = DEFAULT_AUTONOMY_CONFIG,
    availability_policy_path: Path = DEFAULT_POLICY,
    model_registry_path: Path = DEFAULT_MODEL_REGISTRY,
    runtime_matrix_path: Path = DEFAULT_RUNTIME_MATRIX,
) -> dict[str, Any]:
    """Return a report only after exact source-input recomputation succeeds."""
    actual = json.loads(Path(report_path).read_text(encoding="utf-8"))
    try:
        require_valid_document(actual, "multi_person_tournament_execution")
    except ArtifactValidationError as exc:
        raise MultiPersonExecutionError(str(exc)) from exc
    payload = {key: value for key, value in actual.items() if key != "sha256"}
    if actual["sha256"] != _canonical_sha256(payload):
        raise MultiPersonExecutionError("multi-person execution report hash mismatch")
    expected = _build_report(
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
    if actual != expected:
        raise MultiPersonExecutionError("multi-person execution report recomputation mismatch")
    return actual


__all__ = [
    "EXECUTION_AUTHORITY",
    "MANDATORY_GATE_CHECKS",
    "MultiPersonExecutionError",
    "TargetTournamentControl",
    "load_verified_multi_person_tournament_execution",
    "verify_multi_person_tournament_execution",
    "write_multi_person_tournament_execution",
]
