"""Fail-closed dataset-level coverage accounting for the adult corpus."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


class NudeDatasetCoverageError(ValueError):
    """Coverage inputs or reconciliation were invalid."""


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _load_registry_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            sample_id = row.get("sample_id")
            if not isinstance(sample_id, str) or not sample_id:
                raise NudeDatasetCoverageError(f"registry_sample_id_invalid:{line_number}")
            if sample_id in records:
                raise NudeDatasetCoverageError(f"registry_sample_id_duplicate:{sample_id}")
            records[sample_id] = row
    if not records:
        raise NudeDatasetCoverageError("registry_records_empty")
    return records


def _load_queue_outcomes(path: Path, platform: str) -> list[dict[str, Any]]:
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            rows = connection.execute(
                "SELECT sample_id,source_sha256,outcome,payload_json FROM record_outcomes "
                "WHERE platform=? ORDER BY sample_id",
                (platform,),
            ).fetchall()
    except sqlite3.Error as exc:
        raise NudeDatasetCoverageError("queue_read_failed") from exc
    return [
        {
            "sample_id": row[0],
            "source_sha256": row[1],
            "outcome": row[2],
            "payload": json.loads(row[3]),
        }
        for row in rows
    ]


def _label_kind(label: str, crosswalk: Mapping[str, Any]) -> str:
    if label in crosswalk.get("scene_and_action_labels", {}):
        return "action_or_scene"
    if label in crosswalk.get("anatomy_aliases", {}):
        return "anatomy"
    return "unmapped"


def _coverage_rows(population: Counter[str], processed: Counter[str]) -> list[dict[str, Any]]:
    rows = []
    for stratum in sorted(set(population) | set(processed)):
        population_count = int(population.get(stratum, 0))
        processed_count = int(processed.get(stratum, 0))
        rows.append(
            {
                "stratum": stratum,
                "population_count": population_count,
                "processed_count": processed_count,
                "remaining_count": population_count - processed_count,
                "coverage_fraction": (
                    processed_count / population_count if population_count else None
                ),
                "complete": population_count > 0 and processed_count == population_count,
            }
        )
    return rows


def build_nude_dataset_coverage(
    *,
    registry_records: Path,
    ontology_crosswalk: Path,
    queue_path: Path,
    platform: str,
) -> dict[str, Any]:
    """Reconcile every processed outcome against all input coverage strata."""

    records = _load_registry_records(registry_records)
    crosswalk = json.loads(ontology_crosswalk.read_text(encoding="utf-8"))
    outcomes = _load_queue_outcomes(queue_path, platform)
    axes = ("dataset_id", "source_role", "media_domain", "source_split", "lineage_group")
    population = {axis: Counter() for axis in axes}
    processed = {axis: Counter() for axis in axes}
    population_labels: Counter[str] = Counter()
    processed_labels: Counter[str] = Counter()
    population_label_kinds: Counter[str] = Counter()
    processed_label_kinds: Counter[str] = Counter()
    for row in records.values():
        for axis in axes:
            population[axis][str(row.get(axis) or "unknown")] += 1
        labels = row.get("source_labels") or []
        if not labels:
            population_labels["__unlabeled__"] += 1
            population_label_kinds["unlabeled"] += 1
        for label in labels:
            population_labels[str(label)] += 1
            population_label_kinds[_label_kind(str(label), crosswalk)] += 1

    outcome_counts: Counter[str] = Counter()
    provider_counts: Counter[str] = Counter()
    hard_qc_counts: Counter[str] = Counter()
    repair_counts: Counter[str] = Counter()
    certification_counts: Counter[str] = Counter()
    seen: set[str] = set()
    errors: list[str] = []
    for outcome in outcomes:
        sample_id = str(outcome["sample_id"])
        if sample_id in seen:
            errors.append(f"duplicate_processed_sample:{sample_id}")
            continue
        seen.add(sample_id)
        source = records.get(sample_id)
        if source is None:
            errors.append(f"processed_sample_missing_from_registry:{sample_id}")
            continue
        if outcome["source_sha256"] != source.get("source_sha256"):
            errors.append(f"processed_source_hash_mismatch:{sample_id}")
        for axis in axes:
            processed[axis][str(source.get(axis) or "unknown")] += 1
        labels = source.get("source_labels") or []
        if not labels:
            processed_labels["__unlabeled__"] += 1
            processed_label_kinds["unlabeled"] += 1
        for label in labels:
            processed_labels[str(label)] += 1
            processed_label_kinds[_label_kind(str(label), crosswalk)] += 1
        terminal = str(outcome["outcome"])
        outcome_counts[terminal] += 1
        evidence = outcome["payload"].get("qualification_evidence") or {}
        provider_counts[
            str((evidence.get("provider_comparison") or {}).get("status") or "not_applicable")
        ] += 1
        hard_qc_counts[str((evidence.get("hard_qc") or {}).get("status") or "not_applicable")] += 1
        repair_counts[
            (
                "success"
                if terminal == "repaired"
                else "not_needed" if terminal == "accepted" else "not_applicable"
            )
        ] += 1
        certificate = evidence.get("operational_certificate") or {}
        certification_counts[
            "issued" if certificate.get("certificate_sha256") else "not_issued"
        ] += 1

    processed_count = len(outcomes)
    for axis in axes:
        if sum(processed[axis].values()) != processed_count:
            errors.append(f"processed_axis_total_mismatch:{axis}")
    if sum(outcome_counts.values()) != processed_count:
        errors.append("outcome_total_mismatch")
    if sum(provider_counts.values()) != processed_count:
        errors.append("provider_total_mismatch")
    if sum(hard_qc_counts.values()) != processed_count:
        errors.append("hard_qc_total_mismatch")
    if sum(repair_counts.values()) != processed_count:
        errors.append("repair_total_mismatch")
    if sum(certification_counts.values()) != processed_count:
        errors.append("certification_total_mismatch")

    stratum_coverage = {axis: _coverage_rows(population[axis], processed[axis]) for axis in axes}
    stratum_coverage["raw_label"] = _coverage_rows(population_labels, processed_labels)
    stratum_coverage["label_kind"] = _coverage_rows(population_label_kinds, processed_label_kinds)
    incomplete_strata = {
        axis: [row for row in rows if not row["complete"]]
        for axis, rows in stratum_coverage.items()
    }

    report: dict[str, Any] = {
        "schema_version": "maskfactory.nude_dataset_coverage.v2",
        "artifact_type": "adult_corpus_dataset_coverage",
        "status": "PASS" if not errors else "FAIL",
        "platform": platform,
        "registry_record_count": len(records),
        "processed_record_count": processed_count,
        "remaining_record_count": len(records) - processed_count,
        "population_axes": {
            axis: dict(sorted(counts.items())) for axis, counts in population.items()
        },
        "processed_axes": {
            axis: dict(sorted(counts.items())) for axis, counts in processed.items()
        },
        "population_raw_label_counts": dict(sorted(population_labels.items())),
        "processed_raw_label_counts": dict(sorted(processed_labels.items())),
        "population_label_kind_counts": dict(sorted(population_label_kinds.items())),
        "processed_label_kind_counts": dict(sorted(processed_label_kinds.items())),
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "provider_agreement_status_counts": dict(sorted(provider_counts.items())),
        "hard_qc_status_counts": dict(sorted(hard_qc_counts.items())),
        "repair_status_counts": dict(sorted(repair_counts.items())),
        "abstention_count": outcome_counts.get("abstained", 0),
        "quarantine_count": outcome_counts.get("quarantined", 0),
        "certification_status_counts": dict(sorted(certification_counts.items())),
        "certification_yield": (
            certification_counts.get("issued", 0) / processed_count if processed_count else 0.0
        ),
        "stratum_coverage": stratum_coverage,
        "incomplete_strata": incomplete_strata,
        "all_processed_records_reconciled": not errors,
        "full_population_complete": not errors and processed_count == len(records),
        "integrity_errors": errors,
        "registry_records_sha256": hashlib.sha256(registry_records.read_bytes()).hexdigest(),
        "ontology_crosswalk_sha256": hashlib.sha256(ontology_crosswalk.read_bytes()).hexdigest(),
    }
    report["self_sha256"] = _canonical_sha256(report)
    return report


__all__ = ["NudeDatasetCoverageError", "build_nude_dataset_coverage"]
