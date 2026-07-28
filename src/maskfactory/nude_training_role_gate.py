"""Fail-closed source-role gate before adult-corpus pixel-training admission."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .nude_corpus_intake import FINE_LABELS_NOT_INFERRED_FROM_COARSE
from .nude_person_ownership import validate_person_ownership_stage_receipt

PIXEL_TRAINING_SOURCE_ROLE = "polygon_external_supervision"
PIXEL_TRAINING_PARTITION = "train"
ALLOWED_PIXEL_MAPPING_KINDS = frozenset(
    {
        "anatomy",
        "anatomy_state",
        "appearance_region",
        "coarse_anatomy",
        "coarse_anatomy_state",
        "ambiguous_coarse_anatomy",
        "source_alias_for_visible_external_anatomy",
    }
)


class NudeTrainingRoleError(ValueError):
    """A non-pixel, non-training, or semantically unsafe source reached export."""


def _sha256(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise NudeTrainingRoleError(f"{field}_invalid")
    return value


def require_nude_pixel_training_role(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Prove role eligibility only; never grant final training authority."""

    sample_id = candidate.get("sample_id")
    if not isinstance(sample_id, str) or not sample_id:
        raise NudeTrainingRoleError("sample_id_invalid")
    source_role = candidate.get("source_role")
    if source_role != PIXEL_TRAINING_SOURCE_ROLE:
        raise NudeTrainingRoleError(f"non_pixel_source_role:{source_role}")
    partition = candidate.get("assigned_partition")
    if partition != PIXEL_TRAINING_PARTITION:
        raise NudeTrainingRoleError(f"non_training_partition:{partition}")
    raw_label = candidate.get("raw_label")
    candidate_label = candidate.get("candidate_label")
    mapping_kind = candidate.get("candidate_kind")
    if not isinstance(raw_label, str) or not raw_label:
        raise NudeTrainingRoleError("raw_label_invalid")
    if not isinstance(candidate_label, str) or not candidate_label:
        raise NudeTrainingRoleError("candidate_label_invalid")
    if mapping_kind not in ALLOWED_PIXEL_MAPPING_KINDS:
        raise NudeTrainingRoleError(f"non_pixel_mapping_kind:{mapping_kind}")
    if "coarse" in str(mapping_kind) and candidate_label in FINE_LABELS_NOT_INFERRED_FROM_COARSE:
        raise NudeTrainingRoleError("coarse_source_invented_fine_label")
    source_sha256 = _sha256(candidate.get("source_sha256"), "source_sha256")
    mask_sha256 = _sha256(candidate.get("mask_sha256"), "mask_sha256")
    return {
        "sample_id": sample_id,
        "source_role": source_role,
        "assigned_partition": partition,
        "source_sha256": source_sha256,
        "mask_sha256": mask_sha256,
        "raw_label": raw_label,
        "candidate_label": candidate_label,
        "candidate_kind": mapping_kind,
        "pixel_training_role_eligible": True,
        "person_instance_ownership_verified": False,
        "ownership_status": "unresolved",
        "person_index": None,
        "scene_instance_id": None,
        "ownership_report_sha256": None,
        "ownership_stage_evidence_sha256": None,
        "training_authority_granted": False,
        "remaining_required_gates": [
            "external_supervision_qualification",
            "independent_provider_comparison",
            "hard_qc",
            "person_instance_ownership",
            "strict_per_record_visual_review",
            "terminal_machine_verified_outcome",
            "immutable_weighted_training_export",
        ],
    }


def _ownership_index(
    path: Path | None,
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], str | None, int]:
    if path is None:
        return {}, None, 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NudeTrainingRoleError("ownership_stage_receipts_invalid") from exc
    if not isinstance(payload, list):
        raise NudeTrainingRoleError("ownership_stage_receipts_not_list")
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    queue_envelope_compatibility_count = 0
    for receipt in payload:
        candidate_receipt = receipt
        if isinstance(receipt, Mapping) and "sample_index" in receipt:
            sample_index = receipt["sample_index"]
            if (
                isinstance(sample_index, bool)
                or not isinstance(sample_index, int)
                or sample_index < 0
            ):
                raise NudeTrainingRoleError("ownership_stage_receipt_sample_index_invalid")
            candidate_receipt = {
                key: value for key, value in receipt.items() if key != "sample_index"
            }
            queue_envelope_compatibility_count += 1
        try:
            validated = validate_person_ownership_stage_receipt(candidate_receipt)
        except ValueError as exc:
            raise NudeTrainingRoleError(f"ownership_stage_receipt_invalid:{exc}") from exc
        for report in validated["ownership_reports"]:
            key = (
                validated["sample_id"],
                report["mask_sha256"],
                report["candidate_label"],
            )
            if key in index:
                raise NudeTrainingRoleError("ownership_stage_receipt_duplicate_binding")
            index[key] = {
                **report,
                "ownership_stage_evidence_sha256": validated["evidence_sha256"],
            }
    return (
        index,
        hashlib.sha256(path.read_bytes()).hexdigest(),
        queue_envelope_compatibility_count,
    )


def build_nude_training_role_population(
    polygon_records: Path,
    output_dir: Path,
    *,
    ownership_stage_receipts: Path | None = None,
) -> dict[str, Any]:
    """Write every train-role-eligible mask while retaining all exclusions as counts."""

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "role_eligible_masks.jsonl"
    outcomes: Counter[str] = Counter()
    partitions: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    ownership_statuses: Counter[str] = Counter()
    (
        ownership_index,
        ownership_receipts_sha256,
        ownership_queue_envelope_compatibility_count,
    ) = _ownership_index(ownership_stage_receipts)
    matched_ownership_bindings = 0
    input_records = 0
    input_masks = 0
    with (
        polygon_records.open(encoding="utf-8") as source,
        output_path.open("w", encoding="utf-8", newline="\n") as target,
    ):
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise NudeTrainingRoleError(f"polygon_record_json_invalid:{line_number}") from exc
            input_records += 1
            masks = record.get("masks")
            if not isinstance(masks, list):
                raise NudeTrainingRoleError(f"polygon_record_masks_invalid:{line_number}")
            input_masks += len(masks)
            outcome = str(record.get("outcome"))
            partition = str(record.get("assigned_partition"))
            outcomes[outcome] += 1
            partitions[partition] += 1
            if outcome != "hard_qc_pass_candidate" or partition != PIXEL_TRAINING_PARTITION:
                continue
            for mask_index, mask in enumerate(masks):
                candidate = require_nude_pixel_training_role(
                    {
                        "sample_id": record.get("sample_id"),
                        "source_role": record.get("source_role"),
                        "assigned_partition": partition,
                        "source_sha256": record.get("source_sha256"),
                        "mask_sha256": mask.get("mask_sha256"),
                        "raw_label": mask.get("raw_label"),
                        "candidate_label": mask.get("candidate_label"),
                        "candidate_kind": mask.get("candidate_kind"),
                    }
                )
                candidate["mask_index"] = mask_index
                candidate["split_group_id"] = record.get("split_group_id")
                candidate["dataset_id"] = record.get("dataset_id")
                ownership = ownership_index.get(
                    (
                        candidate["sample_id"],
                        candidate["mask_sha256"],
                        candidate["candidate_label"],
                    )
                )
                if ownership is not None:
                    matched_ownership_bindings += 1
                    candidate["ownership_status"] = ownership["status"]
                    candidate["person_instance_ownership_verified"] = (
                        ownership["status"] == "verified"
                    )
                    candidate["person_index"] = ownership.get("person_index")
                    candidate["scene_instance_id"] = ownership.get("scene_instance_id")
                    candidate["ownership_report_sha256"] = ownership["report_sha256"]
                    candidate["ownership_stage_evidence_sha256"] = ownership[
                        "ownership_stage_evidence_sha256"
                    ]
                    if candidate["person_instance_ownership_verified"]:
                        candidate["remaining_required_gates"].remove("person_instance_ownership")
                labels[str(candidate["candidate_label"])] += 1
                ownership_statuses[str(candidate["ownership_status"])] += 1
                target.write(json.dumps(candidate, sort_keys=True, separators=(",", ":")) + "\n")
    output_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
    summary: dict[str, Any] = {
        "schema_version": "maskfactory.nude_training_role_population.v3",
        "artifact_type": "nude_pixel_training_role_population",
        "status": "ROLE_GATE_PASS_PENDING_QUALIFICATION",
        "source_polygon_records_sha256": hashlib.sha256(polygon_records.read_bytes()).hexdigest(),
        "input_record_count": input_records,
        "input_mask_count": input_masks,
        "input_outcome_counts": dict(sorted(outcomes.items())),
        "input_partition_counts": dict(sorted(partitions.items())),
        "role_eligible_mask_count": sum(labels.values()),
        "role_eligible_label_counts": dict(sorted(labels.items())),
        "role_eligible_masks_sha256": output_sha256,
        "ownership_stage_receipts_sha256": ownership_receipts_sha256,
        "ownership_queue_envelope_compatibility_count": (
            ownership_queue_envelope_compatibility_count
        ),
        "matched_ownership_binding_count": matched_ownership_bindings,
        "person_instance_ownership_verified_count": ownership_statuses["verified"],
        "ownership_status_counts": dict(sorted(ownership_statuses.items())),
        "training_authority_granted": False,
        "claim_boundary": (
            "Role eligibility does not replace external qualification, provider comparison, hard "
            "QC, person-instance ownership, strict visual review, terminal outcome, or immutable "
            "weighted export gates."
        ),
    }
    encoded = json.dumps(summary, sort_keys=True, separators=(",", ":"))
    summary["self_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


__all__ = [
    "ALLOWED_PIXEL_MAPPING_KINDS",
    "NudeTrainingRoleError",
    "PIXEL_TRAINING_PARTITION",
    "PIXEL_TRAINING_SOURCE_ROLE",
    "require_nude_pixel_training_role",
    "build_nude_training_role_population",
]
