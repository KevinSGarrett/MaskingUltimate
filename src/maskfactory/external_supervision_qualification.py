"""Deterministic qualification-evidence checks for external supervision sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .external_supervision import PRIVATE_NONCOMMERCIAL_PROFILE, TRAIN_PARTITION
from .external_supervision_evidence import (
    CANONICAL_REQUIRED_GATES_BY_SOURCE,
    verify_qualification_evidence_bundle,
)
from .truth_tiers import WEIGHTED_PSEUDO_LABEL


@dataclass(frozen=True)
class QualificationEvidence:
    """Fail-closed qualification decision plus deterministic evidence tokens."""

    source: str
    legally_eligible: bool
    technically_qualified: bool
    admitted: bool
    unmet_gates: tuple[str, ...]
    evidence_tokens: tuple[str, ...]
    evidence_bundle_sha256: str | None
    reason: str


def verify_external_qualification_evidence(
    provenance: Mapping[str, Any],
    inventory: Mapping[str, Any],
    *,
    source: str,
    completed_gates: set[str] | frozenset[str] | None = None,
    evidence_bundle: Mapping[str, Any] | None = None,
    project_root: Path | None = None,
    use_profile_id: str = PRIVATE_NONCOMMERCIAL_PROFILE,
) -> QualificationEvidence:
    """Verify one source using only registry metadata.

    Unknown, malformed, or drifted inputs fail closed by returning a non-admitted
    `QualificationEvidence` with explicit evidence tokens.
    """

    tokens: list[str] = []
    if use_profile_id != PRIVATE_NONCOMMERCIAL_PROFILE:
        tokens.append("locked_use_profile")

    provenance_sources = _provenance_sources(provenance, tokens)
    inventory_sources = _inventory_sources(inventory, tokens)

    if provenance_sources is None or inventory_sources is None:
        return _blocked(source, tokens, "registry metadata is malformed")
    if set(provenance_sources) != set(inventory_sources):
        tokens.append("source_set_drift_detected")
    if source not in provenance_sources or source not in inventory_sources:
        tokens.append("unknown_external_source")
        return _blocked(
            source,
            tokens,
            "source is unknown or not listed in both registries",
        )

    entry = provenance_sources[source]
    if not isinstance(entry, Mapping):
        tokens.append("malformed_source_entry")
        return _blocked(source, tokens, "source entry must be a mapping")

    admission = entry.get("training_admission")
    if not isinstance(admission, Mapping):
        tokens.append("malformed_training_admission")
        return _blocked(source, tokens, "training admission is missing or malformed")

    status = admission.get("status")
    if status == "blocked":
        tokens.append("blocked_by_registry_status")
    elif status != "permitted_after_qualification":
        tokens.append("unknown_training_admission_status")

    _validate_authority_boundaries(entry, admission, tokens)

    required_gates = _required_gates(admission, tokens)
    if required_gates is None:
        return _blocked(source, tokens, "required qualification gates are malformed")
    canonical_gates = CANONICAL_REQUIRED_GATES_BY_SOURCE.get(source)
    if canonical_gates is None or required_gates != canonical_gates:
        tokens.append("canonical_gate_contract_drift")

    evidence_bundle_sha256: str | None = None
    bound_completed_gates: frozenset[str] = frozenset()
    if evidence_bundle is None or project_root is None:
        tokens.append("qualification_evidence_bundle_missing")
        if completed_gates:
            tokens.append("unbound_completed_gates_ignored")
    else:
        verification = verify_qualification_evidence_bundle(
            evidence_bundle,
            source=source,
            project_root=project_root,
        )
        tokens.extend(verification.evidence_tokens)
        evidence_bundle_sha256 = verification.bundle_sha256
        bound_completed_gates = frozenset(verification.completed_gates)
    unmet = tuple(gate for gate in required_gates if gate not in bound_completed_gates)
    technically_qualified = not unmet and "required_gates_malformed" not in tokens

    legally_eligible = (
        status == "permitted_after_qualification"
        and "locked_use_profile" not in tokens
        and all(
            token not in tokens
            for token in (
                "source_set_drift_detected",
                "unknown_training_admission_status",
                "source_role_drift",
                "training_use_profile_drift",
                "truth_tier_drift",
                "truth_partition_drift",
                "holdout_authority_drift",
                "dataset_volume_authority_drift",
                "training_weight_drift",
                "allowed_label_scope_malformed",
                "canonical_gate_contract_drift",
                "qualification_evidence_bundle_missing",
            )
        )
    )

    admitted = legally_eligible and technically_qualified
    if admitted:
        reason = "qualified train-only weighted pseudo-label supervision"
    elif legally_eligible:
        reason = "qualification gates are incomplete"
    else:
        reason = "source is not legally eligible under locked external supervision policy"
    return QualificationEvidence(
        source=source,
        legally_eligible=legally_eligible,
        technically_qualified=technically_qualified,
        admitted=admitted,
        unmet_gates=unmet,
        evidence_tokens=tuple(tokens),
        evidence_bundle_sha256=evidence_bundle_sha256,
        reason=reason,
    )


def _blocked(source: str, tokens: list[str], reason: str) -> QualificationEvidence:
    return QualificationEvidence(
        source=source,
        legally_eligible=False,
        technically_qualified=False,
        admitted=False,
        unmet_gates=(),
        evidence_tokens=tuple(tokens),
        evidence_bundle_sha256=None,
        reason=reason,
    )


def _provenance_sources(
    provenance: Mapping[str, Any], tokens: list[str]
) -> Mapping[str, Any] | None:
    sources = provenance.get("sources")
    if not isinstance(sources, Mapping):
        tokens.append("provenance_sources_malformed")
        return None
    return sources


def _inventory_sources(
    inventory: Mapping[str, Any], tokens: list[str]
) -> dict[str, Mapping[str, Any]] | None:
    raw_sources = inventory.get("sources")
    if not isinstance(raw_sources, list):
        tokens.append("inventory_sources_malformed")
        return None
    sources: dict[str, Mapping[str, Any]] = {}
    for item in raw_sources:
        if not isinstance(item, Mapping):
            tokens.append("inventory_sources_malformed")
            return None
        raw_name = item.get("source")
        if not isinstance(raw_name, str) or not raw_name:
            tokens.append("inventory_sources_malformed")
            return None
        if raw_name in sources:
            tokens.append("inventory_sources_malformed")
            return None
        sources[raw_name] = item
    return sources


def _validate_authority_boundaries(
    entry: Mapping[str, Any], admission: Mapping[str, Any], tokens: list[str]
) -> None:
    if entry.get("source_role") != "external_labeled_reference":
        tokens.append("source_role_drift")
    if admission.get("use_profile_id") != PRIVATE_NONCOMMERCIAL_PROFILE:
        tokens.append("training_use_profile_drift")
    if admission.get("truth_tier") != WEIGHTED_PSEUDO_LABEL:
        tokens.append("truth_tier_drift")
    if admission.get("truth_partition") != TRAIN_PARTITION:
        tokens.append("truth_partition_drift")
    if admission.get("holdout_eligible") is not False:
        tokens.append("holdout_authority_drift")
    if admission.get("dataset_volume_eligible") is not False:
        tokens.append("dataset_volume_authority_drift")

    weight = admission.get("training_loss_weight")
    if not isinstance(weight, (int, float)) or not 0.10 <= float(weight) <= 0.25:
        tokens.append("training_weight_drift")

    label_scope = admission.get("allowed_label_scope")
    if (
        not isinstance(label_scope, list)
        or not label_scope
        or any(not isinstance(label, str) or not label for label in label_scope)
    ):
        tokens.append("allowed_label_scope_malformed")


def _required_gates(admission: Mapping[str, Any], tokens: list[str]) -> tuple[str, ...] | None:
    raw_gates = admission.get("required_gates")
    if not isinstance(raw_gates, list) or not raw_gates:
        tokens.append("required_gates_malformed")
        return None
    if any(not isinstance(gate, str) or not gate for gate in raw_gates):
        tokens.append("required_gates_malformed")
        return None
    if len(raw_gates) != len(set(raw_gates)):
        tokens.append("required_gates_malformed")
        return None
    return tuple(raw_gates)


__all__ = ["QualificationEvidence", "verify_external_qualification_evidence"]
