"""Atomic consolidation for disjoint reference-corpus provider waves."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .nude_box_mask_generation import validate_box_prompt_provider_batch
from .nude_person_catalog import validate_person_proposal_catalog_report
from .nude_reference_mask_hard_qc import run_reference_person_mask_hard_qc


class NudeBoxMaskConsolidationError(ValueError):
    """Disjoint provider waves cannot be consolidated without authority drift."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_catalog(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    if document.get("schema_version") != "maskfactory.nude_person_catalog_batch.v1":
        raise NudeBoxMaskConsolidationError("catalog_batch_schema_invalid")
    body = {key: value for key, value in document.items() if key != "self_sha256"}
    if document.get("self_sha256") != _canonical_sha256(body):
        raise NudeBoxMaskConsolidationError("catalog_batch_hash_mismatch")
    records = document.get("records")
    if not isinstance(records, list) or len(records) != document.get("record_count"):
        raise NudeBoxMaskConsolidationError("catalog_batch_records_invalid")
    validated = [validate_person_proposal_catalog_report(record) for record in records]
    sample_ids = [record["sample_id"] for record in validated]
    if len(sample_ids) != len(set(sample_ids)):
        raise NudeBoxMaskConsolidationError("catalog_batch_sample_duplicate")
    return validated


def _quarantined_unreferenced(
    *,
    provider_root: Path,
    referenced: set[str],
    input_index: int,
) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(Path(provider_root).rglob("*.png")):
        relative = path.relative_to(provider_root).as_posix()
        if relative in referenced:
            continue
        rows.append(
            {
                "input_index": input_index,
                "relative_path": relative,
                "artifact_sha256": _file_sha256(path),
                "authority": "quarantined_unreferenced_incident_evidence_only",
                "eligible_for_consolidation": False,
            }
        )
    return rows


def consolidate_box_prompt_provider_batches(
    *,
    catalog_batch: Mapping[str, Any],
    provider_batches: Sequence[tuple[Mapping[str, Any], Path]],
    source_paths: Mapping[str, Path],
    output_root: Path,
) -> dict[str, Any]:
    """Consolidate disjoint waves and rerun hard QA in one atomic package."""

    catalog_records = _validated_catalog(catalog_batch)
    if not provider_batches:
        raise NudeBoxMaskConsolidationError("provider_batches_empty")
    expected_source_ids = {record["sample_id"] for record in catalog_records}
    if set(source_paths) != expected_source_ids:
        raise NudeBoxMaskConsolidationError("source_path_population_mismatch")

    identity: dict[str, Any] | None = None
    records_by_id: dict[str, dict[str, Any]] = {}
    candidate_sources: dict[str, Path] = {}
    quarantined = []
    input_bindings = []
    for input_index, (document, provider_root) in enumerate(provider_batches):
        root = Path(provider_root)
        validated = validate_box_prompt_provider_batch(document, output_root=root)
        if validated["catalog_batch_sha256"] != catalog_batch["self_sha256"]:
            raise NudeBoxMaskConsolidationError("provider_catalog_binding_mismatch")
        current_identity = dict(validated["provider"])
        if identity is None:
            identity = current_identity
        elif current_identity != identity:
            raise NudeBoxMaskConsolidationError("provider_identity_mismatch")
        referenced = set()
        for record in validated["records"]:
            sample_id = record["sample_id"]
            if sample_id in records_by_id:
                raise NudeBoxMaskConsolidationError("provider_record_overlap")
            if sample_id not in expected_source_ids:
                raise NudeBoxMaskConsolidationError("provider_record_outside_catalog")
            records_by_id[sample_id] = dict(record)
            for candidate in record["candidates"]:
                relative = candidate["artifact_relative_path"]
                if relative in candidate_sources:
                    raise NudeBoxMaskConsolidationError("provider_candidate_path_overlap")
                referenced.add(relative)
                candidate_sources[relative] = root / relative
        quarantined.extend(
            _quarantined_unreferenced(
                provider_root=root,
                referenced=referenced,
                input_index=input_index,
            )
        )
        input_bindings.append(
            {
                "input_index": input_index,
                "provider_batch_sha256": validated["self_sha256"],
                "record_count": validated["record_count"],
                "candidate_count": validated["candidate_count"],
            }
        )
    assert identity is not None

    output_records = []
    for catalog_record in catalog_records:
        sample_id = catalog_record["sample_id"]
        provider_record = records_by_id.get(sample_id)
        if catalog_record["status"] == "pass":
            if provider_record is None:
                raise NudeBoxMaskConsolidationError("eligible_provider_record_missing")
            if provider_record["status"] == "catalog_abstain":
                raise NudeBoxMaskConsolidationError("eligible_record_catalog_abstain_invalid")
            output_records.append(provider_record)
            continue
        if provider_record is not None:
            raise NudeBoxMaskConsolidationError("catalog_abstain_was_sent_to_provider")
        output_records.append(
            {
                "sample_id": sample_id,
                "source_sha256": catalog_record["source_sha256"],
                "status": "catalog_abstain",
                "reason": list(catalog_record["reasons"]),
                "candidates": [],
            }
        )

    counts = Counter(record["status"] for record in output_records)
    body = {
        "schema_version": "maskfactory.nude_box_prompt_provider_batch.v1",
        "catalog_batch_sha256": catalog_batch["self_sha256"],
        "provider": identity,
        "record_count": len(output_records),
        "candidate_count": sum(len(record["candidates"]) for record in output_records),
        "status_counts": dict(sorted(counts.items())),
        "records": output_records,
        "authority": "draft_provider_masks_only",
        "source_images_are_pixel_truth": False,
        "boxes_are_pixel_truth": False,
        "production_mask_authority": False,
        "operational_certificates_issued": False,
    }
    provider_document = {**body, "self_sha256": _canonical_sha256(body)}
    quarantine_body = {
        "schema_version": "maskfactory.unreferenced_provider_artifact_quarantine.v1",
        "record_count": len(quarantined),
        "records": quarantined,
        "authority": "incident_evidence_only",
        "eligible_for_training": False,
        "eligible_for_certification": False,
    }
    quarantine_document = {
        **quarantine_body,
        "self_sha256": _canonical_sha256(quarantine_body),
    }

    output_root = Path(output_root)
    if output_root.exists():
        raise NudeBoxMaskConsolidationError("consolidated_output_already_exists")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output_root.name}.",
        dir=output_root.parent,
    ) as directory:
        stage = Path(directory) / output_root.name
        candidates_root = stage / "candidates"
        candidates_root.mkdir(parents=True)
        for relative, source in sorted(candidate_sources.items()):
            destination = candidates_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            expected = records_by_id[Path(relative).parts[0]]["candidates"]
            expected_sha256 = next(
                candidate["artifact_sha256"]
                for candidate in expected
                if candidate["artifact_relative_path"] == relative
            )
            if _file_sha256(destination) != expected_sha256:
                raise NudeBoxMaskConsolidationError("candidate_copy_hash_mismatch")

        hard_qc = run_reference_person_mask_hard_qc(
            provider_document,
            output_root=candidates_root,
            source_paths=source_paths,
        )
        (stage / "provider.json").write_text(
            json.dumps(provider_document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (stage / "hard_qc.json").write_text(
            json.dumps(hard_qc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (stage / "quarantine.json").write_text(
            json.dumps(quarantine_document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_body = {
            "schema_version": "maskfactory.nude_provider_consolidation.v1",
            "catalog_batch_sha256": catalog_batch["self_sha256"],
            "inputs": input_bindings,
            "provider_file_sha256": _file_sha256(stage / "provider.json"),
            "provider_self_sha256": provider_document["self_sha256"],
            "hard_qc_file_sha256": _file_sha256(stage / "hard_qc.json"),
            "hard_qc_self_sha256": hard_qc["self_sha256"],
            "quarantine_file_sha256": _file_sha256(stage / "quarantine.json"),
            "quarantine_self_sha256": quarantine_document["self_sha256"],
            "record_count": len(output_records),
            "candidate_count": provider_document["candidate_count"],
            "provider_status_counts": provider_document["status_counts"],
            "hard_qc_status_counts": hard_qc["status_counts"],
            "quarantined_unreferenced_count": len(quarantined),
            "authority": "provider_and_deterministic_hard_qc_stage_only",
            "strict_visual_review_complete": False,
            "terminal_record_count": 0,
            "operational_certificates_issued": False,
        }
        manifest = {**manifest_body, "self_sha256": _canonical_sha256(manifest_body)}
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(stage, output_root)
    return manifest


__all__ = [
    "NudeBoxMaskConsolidationError",
    "consolidate_box_prompt_provider_batches",
]
