"""Governed admission of externally labelled datasets as train-only supervision.

External labels are useful supervision, but they are not MaskFactory observations of
real-image truth.  This module keeps legal/use-profile eligibility separate from the
technical qualification needed before a converted sample may enter a training build.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .truth_tiers import WEIGHTED_PSEUDO_LABEL

PRIVATE_NONCOMMERCIAL_PROFILE = "private_personal_noncommercial_non_distributed"
EXTERNAL_LABEL_ROLE = "external_labeled_reference"
TRAIN_PARTITION = "train"


class ExternalSupervisionError(ValueError):
    """External-source authority or qualification metadata is invalid."""


@dataclass(frozen=True)
class TrainingAdmission:
    source: str
    legally_eligible: bool
    technically_qualified: bool
    admitted: bool
    source_role: str
    truth_tier: str | None
    truth_partition: str | None
    training_loss_weight: float
    allowed_label_scope: tuple[str, ...]
    unmet_gates: tuple[str, ...]
    reason: str


def load_external_supervision_registry(
    provenance_path: Path,
    inventory_path: Path,
) -> dict[str, Any]:
    """Load and validate the MaskedWarehouse registry against its inventory."""
    provenance = yaml.safe_load(Path(provenance_path).read_text(encoding="utf-8"))
    inventory = json.loads(Path(inventory_path).read_text(encoding="utf-8"))
    validate_external_supervision_registry(provenance, inventory)
    return provenance


def validate_external_supervision_registry(
    provenance: Mapping[str, Any], inventory: Mapping[str, Any]
) -> None:
    if provenance.get("schema_version") != "2.0.0":
        raise ExternalSupervisionError("external supervision registry must be schema 2.0.0")
    profile = provenance.get("project_use_profile")
    if not isinstance(profile, Mapping) or profile.get("id") != PRIVATE_NONCOMMERCIAL_PROFILE:
        raise ExternalSupervisionError("locked private/noncommercial use profile is missing")
    required_profile = {
        "commercial_use": False,
        "external_distribution": False,
        "source_or_derived_data_redistribution": False,
        "local_private_execution": True,
    }
    for field, expected in required_profile.items():
        if profile.get(field) is not expected:
            raise ExternalSupervisionError(f"use profile violates {field}={expected}")

    policy = provenance.get("policy")
    if not isinstance(policy, Mapping):
        raise ExternalSupervisionError("external supervision policy is missing")
    required_policy = {
        "source_masks_are_gold": False,
        "external_labels_truth_tier": WEIGHTED_PSEUDO_LABEL,
        "external_labels_truth_partition": TRAIN_PARTITION,
        "external_labels_may_enter_holdout": False,
        "external_labels_may_satisfy_certified_volume": False,
    }
    for field, expected in required_policy.items():
        if policy.get(field) != expected:
            raise ExternalSupervisionError(f"external supervision policy violates {field}")
    maximum_share = policy.get("maximum_combined_external_batch_fraction")
    if not isinstance(maximum_share, (int, float)) or not 0 < float(maximum_share) < 0.5:
        raise ExternalSupervisionError("external batch cap must be greater than zero and below 0.5")

    inventory_sources = {str(record["source"]): record for record in inventory.get("sources", ())}
    sources = provenance.get("sources")
    if not isinstance(sources, Mapping) or set(sources) != set(inventory_sources):
        raise ExternalSupervisionError("provenance and inventory source sets differ")
    for source, entry in sources.items():
        if not isinstance(entry, Mapping):
            raise ExternalSupervisionError(f"source entry is not a mapping: {source}")
        if entry.get("gold_gate") != "blocked_external_source_masks_are_not_gold":
            raise ExternalSupervisionError(f"external source is not gold-blocked: {source}")
        admission = entry.get("training_admission")
        if not isinstance(admission, Mapping):
            raise ExternalSupervisionError(f"training admission is missing: {source}")
        status = admission.get("status")
        if status not in {"permitted_after_qualification", "blocked"}:
            raise ExternalSupervisionError(f"training admission status is invalid: {source}")
        if status == "permitted_after_qualification":
            _validate_eligible_admission(source, entry, admission)
        else:
            if (
                admission.get("truth_tier") is not None
                or admission.get("truth_partition") is not None
            ):
                raise ExternalSupervisionError(f"blocked source carries truth authority: {source}")


def evaluate_training_admission(
    registry: Mapping[str, Any],
    source: str,
    *,
    completed_gates: set[str] | frozenset[str],
    use_profile_id: str = PRIVATE_NONCOMMERCIAL_PROFILE,
) -> TrainingAdmission:
    """Return fail-closed training admission for one external source."""
    if use_profile_id != PRIVATE_NONCOMMERCIAL_PROFILE:
        return TrainingAdmission(
            source,
            False,
            False,
            False,
            EXTERNAL_LABEL_ROLE,
            None,
            None,
            0.0,
            (),
            ("locked_use_profile",),
            "requested use profile is not the approved private/noncommercial profile",
        )
    try:
        entry = registry["sources"][source]
    except (KeyError, TypeError) as exc:
        raise ExternalSupervisionError(f"unknown external source: {source}") from exc
    admission = entry["training_admission"]
    legally_eligible = admission["status"] == "permitted_after_qualification"
    required = tuple(admission.get("required_gates", ()))
    unmet = tuple(gate for gate in required if gate not in completed_gates)
    admitted = legally_eligible and not unmet
    return TrainingAdmission(
        source=source,
        legally_eligible=legally_eligible,
        technically_qualified=not unmet,
        admitted=admitted,
        source_role=str(entry.get("source_role", EXTERNAL_LABEL_ROLE)),
        truth_tier=admission.get("truth_tier") if legally_eligible else None,
        truth_partition=admission.get("truth_partition") if legally_eligible else None,
        training_loss_weight=float(admission.get("training_loss_weight", 0.0)),
        allowed_label_scope=tuple(admission.get("allowed_label_scope", ())),
        unmet_gates=unmet,
        reason=(
            "qualified train-only weighted pseudo-label supervision"
            if admitted
            else str(admission.get("reason", "technical qualification is incomplete"))
        ),
    )


def _validate_eligible_admission(
    source: str, entry: Mapping[str, Any], admission: Mapping[str, Any]
) -> None:
    if entry.get("source_role") != EXTERNAL_LABEL_ROLE:
        raise ExternalSupervisionError(f"eligible source has wrong source role: {source}")
    required = {
        "use_profile_id": PRIVATE_NONCOMMERCIAL_PROFILE,
        "truth_tier": WEIGHTED_PSEUDO_LABEL,
        "truth_partition": TRAIN_PARTITION,
        "holdout_eligible": False,
        "dataset_volume_eligible": False,
    }
    for field, expected in required.items():
        if admission.get(field) != expected:
            raise ExternalSupervisionError(f"eligible source violates {field}: {source}")
    weight = admission.get("training_loss_weight")
    if not isinstance(weight, (int, float)) or not 0.1 <= float(weight) <= 0.25:
        raise ExternalSupervisionError(f"eligible source weight must be 0.1..0.25: {source}")
    gates = admission.get("required_gates")
    labels = admission.get("allowed_label_scope")
    if not isinstance(gates, list) or not gates or len(gates) != len(set(gates)):
        raise ExternalSupervisionError(
            f"eligible source needs unique qualification gates: {source}"
        )
    if not isinstance(labels, list) or not labels:
        raise ExternalSupervisionError(f"eligible source needs a bounded label scope: {source}")


__all__ = [
    "EXTERNAL_LABEL_ROLE",
    "ExternalSupervisionError",
    "PRIVATE_NONCOMMERCIAL_PROFILE",
    "TRAIN_PARTITION",
    "TrainingAdmission",
    "evaluate_training_admission",
    "load_external_supervision_registry",
    "validate_external_supervision_registry",
]
