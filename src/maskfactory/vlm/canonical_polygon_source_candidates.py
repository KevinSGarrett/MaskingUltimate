"""Select exact external polygons for canonical visual-control qualification.

Selection is deliberately below qualification authority.  It proves that a
source record has an exact raw label, deterministic polygon hard-QC evidence,
an eligible declared source license, a frozen split, and immutable hashes.  A
selected row still requires visual-alignment review and complete case
materialization before it may serve as a critic positive control.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from .critic_catalog import canonical_sha256

SCHEMA_VERSION = "maskfactory.canonical_polygon_source_candidates.v2"
EXACT_RAW_TO_CANONICAL = {"anus": "anus"}
BOUNDED_ALIAS_RAW_TO_CANONICAL = {"vagina": "vulva"}
REQUIRED_PARTITIONS = ("train", "test")
ELIGIBLE_LICENSE = "CC BY 4.0"


class CanonicalPolygonSourceCandidateError(ValueError):
    """Candidate selection input is incomplete, drifted, or overclaims authority."""


def _record_sha256(record: Mapping[str, Any]) -> str:
    return canonical_sha256(record)


def _dataset_rows(registry: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = registry.get("datasets")
    if not isinstance(raw, list):
        raise CanonicalPolygonSourceCandidateError("dataset registry rows are missing")
    rows: dict[str, Mapping[str, Any]] = {}
    for row in raw:
        if not isinstance(row, Mapping):
            raise CanonicalPolygonSourceCandidateError("dataset registry row is invalid")
        dataset_id = row.get("dataset_id")
        if not isinstance(dataset_id, str) or not dataset_id or dataset_id in rows:
            raise CanonicalPolygonSourceCandidateError(
                "dataset registry IDs are invalid or duplicated"
            )
        rows[dataset_id] = row
    return rows


def build_canonical_polygon_source_candidates(
    *,
    records: Iterable[Mapping[str, Any]],
    registry: Mapping[str, Any],
    hard_qc_summary: Mapping[str, Any],
    records_file_sha256: str,
    registry_file_sha256: str,
    hard_qc_summary_file_sha256: str,
    per_partition: int = 16,
) -> dict[str, Any]:
    """Select a split-disjoint, label-exact adult-anatomy source population."""

    if not 1 <= per_partition <= 256:
        raise CanonicalPolygonSourceCandidateError("per-partition count is out of bounds")
    if any(
        not isinstance(value, str) or len(value) != 64
        for value in (
            records_file_sha256,
            registry_file_sha256,
            hard_qc_summary_file_sha256,
        )
    ):
        raise CanonicalPolygonSourceCandidateError("input file hashes are invalid")
    hard_qc = hard_qc_summary.get("hard_qc")
    if (
        not isinstance(hard_qc, Mapping)
        or hard_qc.get("mask_hash_contract") != "MASKFACTORY_BOOL_MASK_V1_shape_packbits_big"
        or not isinstance(hard_qc.get("mask_hash_implementation_sha256"), str)
        or len(str(hard_qc["mask_hash_implementation_sha256"])) != 64
        or hard_qc_summary.get("records_file_sha256") != records_file_sha256
        or not isinstance(hard_qc_summary.get("self_sha256"), str)
    ):
        raise CanonicalPolygonSourceCandidateError(
            "hard-QC mask-hash contract or records binding is stale"
        )
    datasets = _dataset_rows(registry)
    exact_by_partition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    bounded_alias_counts: Counter[tuple[str, str]] = Counter()
    refusal_counts: Counter[str] = Counter()
    for record in records:
        if not isinstance(record, Mapping):
            refusal_counts["malformed_record"] += 1
            continue
        if (
            record.get("outcome") != "hard_qc_pass_candidate"
            or record.get("source_role") != "polygon_external_supervision"
            or record.get("external_mask_authority") != "machine_hard_qc_candidate_only"
        ):
            continue
        partition = str(record.get("assigned_partition"))
        if partition not in REQUIRED_PARTITIONS:
            continue
        dataset_id = str(record.get("dataset_id"))
        dataset = datasets.get(dataset_id)
        if dataset is None:
            refusal_counts["dataset_missing_from_registry"] += 1
            continue
        if (
            dataset.get("primary_role") != "polygon_external_supervision"
            or dataset.get("annotation_format") != "coco_segmentation"
        ):
            refusal_counts["dataset_role_or_format_ineligible"] += 1
            continue
        if dataset.get("license_claim") != ELIGIBLE_LICENSE:
            refusal_counts["declared_license_not_exactly_eligible"] += 1
            continue
        masks = record.get("masks")
        if not isinstance(masks, list):
            refusal_counts["mask_rows_missing"] += 1
            continue
        for mask in masks:
            if not isinstance(mask, Mapping):
                refusal_counts["malformed_mask_row"] += 1
                continue
            raw = str(mask.get("raw_label", "")).casefold()
            if raw in BOUNDED_ALIAS_RAW_TO_CANONICAL:
                bounded_alias_counts[(partition, raw)] += 1
                continue
            canonical = EXACT_RAW_TO_CANONICAL.get(raw)
            if canonical is None:
                continue
            if (
                mask.get("candidate_label") != canonical
                or mask.get("candidate_kind") != "anatomy"
                or mask.get("binary_mask_materialized") is not True
                or mask.get("production_authority") is not False
                or mask.get("gold_authority") is not False
            ):
                refusal_counts["exact_label_mask_contract_drift"] += 1
                continue
            row = {
                "sample_id": record["sample_id"],
                "dataset_id": dataset_id,
                "lineage_group": dataset["lineage_group"],
                "assigned_partition": partition,
                "split_group_id": record["split_group_id"],
                "source_sha256": record["source_sha256"],
                "annotation_ref": record["annotation_ref"],
                "annotation_file_sha256": record["annotation_file_sha256"],
                "raw_label": raw,
                "canonical_label": canonical,
                "mask_sha256": mask["mask_sha256"],
                "mask_pixels": mask["mask_pixels"],
                "mask_bbox_xyxy": mask["mask_bbox_xyxy"],
                "segmentation_encoding": mask["segmentation_encoding"],
                "declared_license": dataset["license_claim"],
                "hard_qc_record_sha256": _record_sha256(record),
                "source_authority": "external_polygon_hard_qc_candidate",
                "external_reference_qualification_complete": False,
                "critic_positive_control_eligible": False,
                "gold_or_production_authority": False,
            }
            exact_by_partition[partition].append(row)

    selected: list[dict[str, Any]] = []
    used_groups: set[str] = set()
    for partition in REQUIRED_PARTITIONS:
        candidates = sorted(
            exact_by_partition[partition],
            key=lambda row: (
                str(row["dataset_id"]),
                str(row["source_sha256"]),
                str(row["mask_sha256"]),
            ),
        )
        dataset_counts: Counter[str] = Counter()
        partition_selected: list[dict[str, Any]] = []
        while len(partition_selected) < per_partition:
            remaining = [row for row in candidates if str(row["split_group_id"]) not in used_groups]
            if not remaining:
                break
            remaining.sort(
                key=lambda row: (
                    dataset_counts[str(row["dataset_id"])],
                    str(row["dataset_id"]),
                    str(row["source_sha256"]),
                    str(row["mask_sha256"]),
                )
            )
            chosen = remaining[0]
            partition_selected.append(chosen)
            used_groups.add(str(chosen["split_group_id"]))
            dataset_counts[str(chosen["dataset_id"])] += 1
        if len(partition_selected) != per_partition:
            raise CanonicalPolygonSourceCandidateError(
                f"insufficient exact split-disjoint sources:{partition}:"
                f"{len(partition_selected)}/{per_partition}"
            )
        selected.extend(partition_selected)

    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "canonical_external_polygon_source_candidate_set",
        "authority_claimed": False,
        "critic_positive_control_authority_granted": False,
        "gold_or_production_authority_granted": False,
        "input_bindings": {
            "registry_self_sha256": registry["self_sha256"],
            "registry_file_sha256": registry_file_sha256,
            "hard_qc_records_file_sha256": records_file_sha256,
            "hard_qc_summary_file_sha256": hard_qc_summary_file_sha256,
            "hard_qc_summary_self_sha256": hard_qc_summary["self_sha256"],
            "mask_hash_contract": hard_qc["mask_hash_contract"],
            "mask_hash_implementation_sha256": hard_qc["mask_hash_implementation_sha256"],
        },
        "selection_policy": {
            "exact_raw_to_canonical": EXACT_RAW_TO_CANONICAL,
            "bounded_alias_raw_to_canonical": BOUNDED_ALIAS_RAW_TO_CANONICAL,
            "eligible_declared_license": ELIGIBLE_LICENSE,
            "required_partitions": list(REQUIRED_PARTITIONS),
            "per_partition": per_partition,
            "split_group_disjoint": True,
        },
        "selected_count": len(selected),
        "selected_by_partition": dict(
            sorted(Counter(row["assigned_partition"] for row in selected).items())
        ),
        "selected_by_dataset": dict(sorted(Counter(row["dataset_id"] for row in selected).items())),
        "bounded_alias_diagnostic_counts": {
            f"{partition}:{raw}": count
            for (partition, raw), count in sorted(bounded_alias_counts.items())
        },
        "refusal_counts": dict(sorted(refusal_counts.items())),
        "selected": selected,
        "next_required_stage": (
            "runpod_exact_mask_rasterization_full_panel_materialization_and_"
            "visual_alignment_qualification"
        ),
        "claim_limits": [
            "Selection is deterministic candidate evidence, not source qualification.",
            "Only raw anus polygons map exactly to the current canonical anus label.",
            "Raw vagina polygons remain bounded external aliases for canonical vulva and do not count as exact positive controls.",
            "Every selected source still requires exact re-rasterization, panel evidence, visual-alignment qualification, and frozen case construction.",
            "No selected row is gold, production authority, an operational certificate, or autonomous training truth.",
        ],
    }
    document["self_sha256"] = canonical_sha256(document)
    verify_canonical_polygon_source_candidates(document)
    return document


def verify_canonical_polygon_source_candidates(document: Mapping[str, Any]) -> None:
    if (
        document.get("schema_version") != SCHEMA_VERSION
        or document.get("authority_claimed") is not False
        or document.get("critic_positive_control_authority_granted") is not False
        or document.get("gold_or_production_authority_granted") is not False
    ):
        raise CanonicalPolygonSourceCandidateError("candidate-set authority drift")
    payload = {key: value for key, value in document.items() if key != "self_sha256"}
    if document.get("self_sha256") != canonical_sha256(payload):
        raise CanonicalPolygonSourceCandidateError("candidate-set self hash mismatch")
    selected = document.get("selected")
    policy = document.get("selection_policy")
    if not isinstance(selected, list) or not isinstance(policy, Mapping):
        raise CanonicalPolygonSourceCandidateError("candidate-set rows or policy missing")
    expected = int(policy["per_partition"]) * len(REQUIRED_PARTITIONS)
    if document.get("selected_count") != expected or len(selected) != expected:
        raise CanonicalPolygonSourceCandidateError("candidate-set count drift")
    groups = [row.get("split_group_id") for row in selected]
    if len(groups) != len(set(groups)):
        raise CanonicalPolygonSourceCandidateError("candidate-set split groups overlap")
    for row in selected:
        if (
            row.get("raw_label") != "anus"
            or row.get("canonical_label") != "anus"
            or row.get("declared_license") != ELIGIBLE_LICENSE
            or row.get("external_reference_qualification_complete") is not False
            or row.get("critic_positive_control_eligible") is not False
            or row.get("gold_or_production_authority") is not False
        ):
            raise CanonicalPolygonSourceCandidateError("candidate-set row authority drift")


def load_jsonl(path: Any) -> Iterable[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise CanonicalPolygonSourceCandidateError("JSONL row is not an object")
                yield value


def sha256_file(path: Any) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "CanonicalPolygonSourceCandidateError",
    "build_canonical_polygon_source_candidates",
    "load_jsonl",
    "sha256_file",
    "verify_canonical_polygon_source_candidates",
]
