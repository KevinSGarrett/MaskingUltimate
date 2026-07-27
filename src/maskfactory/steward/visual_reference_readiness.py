"""Build source-bound visual-reference readiness evidence without qualification claims."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .continuous_contract import canonical_sha256

SCHEMA_VERSION = "maskfactory.visual_reference_readiness.v1"
ZERO_SHA256 = "0" * 64
REQUIRED_VISUAL_INDEX_COLUMNS = {
    "background",
    "body_type",
    "content_state",
    "difficulty_score",
    "framing",
    "lighting",
    "model_id",
    "person_count",
    "pose",
    "presentation",
    "relative_path",
    "status",
    "tags_json",
    "view",
}
STRATUM_COLUMNS = (
    "person_count",
    "framing",
    "view",
    "pose",
    "content_state",
    "presentation",
    "body_type",
    "background",
    "lighting",
)


class VisualReferenceReadinessError(RuntimeError):
    """Reference inventory cannot support a source-bound readiness receipt."""


def _file_evidence(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VisualReferenceReadinessError(
            f"JSON source is unreadable: {path.name}"
        ) from exc
    if not isinstance(value, dict):
        raise VisualReferenceReadinessError(
            f"JSON source must be an object: {path.name}"
        )
    return value


def _read_library(database: Path) -> dict[str, Any]:
    uri = f"{database.resolve(strict=True).as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        required_tables = {"images", "pipeline_meta", "selections", "visual_index"}
        if not required_tables.issubset(tables):
            raise VisualReferenceReadinessError(
                "reference library required tables are unavailable"
            )
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(visual_index)")
        }
        if not REQUIRED_VISUAL_INDEX_COLUMNS.issubset(columns):
            raise VisualReferenceReadinessError(
                "reference library visual-index schema is unavailable"
            )
        meta: dict[str, Any] = {}
        for key, raw in connection.execute(
            "SELECT key, value_json FROM pipeline_meta ORDER BY key"
        ):
            try:
                meta[str(key)] = json.loads(raw)
            except (TypeError, json.JSONDecodeError) as exc:
                raise VisualReferenceReadinessError(
                    f"pipeline metadata is invalid: {key}"
                ) from exc
        purpose = meta.get("library_purpose")
        selection = meta.get("selection")
        content_policy = meta.get("content_policy")
        if not isinstance(purpose, dict) or not isinstance(selection, dict):
            raise VisualReferenceReadinessError(
                "reference library purpose or selection metadata is unavailable"
            )
        if not isinstance(content_policy, dict) or content_policy.get(
            "content_state_is_organizational_only"
        ) is not True:
            raise VisualReferenceReadinessError(
                "reference library content-state authority boundary is unavailable"
            )
        declared_tags = purpose.get("body_part_focus_tags")
        if (
            not isinstance(declared_tags, list)
            or not declared_tags
            or any(not isinstance(tag, str) or not tag for tag in declared_tags)
        ):
            raise VisualReferenceReadinessError(
                "reference library body-part focus tags are unavailable"
            )

        counts = {
            "images": int(
                connection.execute("SELECT COUNT(*) FROM images").fetchone()[0]
            ),
            "visual_index": int(
                connection.execute("SELECT COUNT(*) FROM visual_index").fetchone()[0]
            ),
            "benchmark_reference": int(
                connection.execute(
                    "SELECT COUNT(*) FROM selections "
                    "WHERE tier = 'benchmark_reference'"
                ).fetchone()[0]
            ),
            "retrieval_reference": int(
                connection.execute(
                    "SELECT COUNT(*) FROM selections "
                    "WHERE tier = 'retrieval_reference'"
                ).fetchone()[0]
            ),
        }
        tag_counts = {
            str(tag): int(count)
            for tag, count in connection.execute(
                """
                SELECT tag.value, COUNT(*)
                FROM selections AS selected
                JOIN visual_index AS visual USING(relative_path),
                     json_each(visual.tags_json) AS tag
                WHERE selected.tier = 'benchmark_reference'
                GROUP BY tag.value
                ORDER BY tag.value
                """
            )
            if str(tag) in declared_tags
        }
        missing_tags = sorted(set(declared_tags) - set(tag_counts))
        strata: dict[str, dict[str, int]] = {}
        for column in STRATUM_COLUMNS:
            rows = connection.execute(
                f"""
                SELECT visual.{column}, COUNT(*)
                FROM selections AS selected
                JOIN visual_index AS visual USING(relative_path)
                WHERE selected.tier = 'benchmark_reference'
                GROUP BY visual.{column}
                ORDER BY visual.{column}
                """
            )
            strata[column] = {str(value): int(count) for value, count in rows}
    except sqlite3.Error as exc:
        raise VisualReferenceReadinessError(
            "reference library query failed closed"
        ) from exc
    finally:
        connection.close()

    return {
        "classifier": purpose.get("classifier_version"),
        "content_state_is_organizational_only": True,
        "counts": counts,
        "declared_body_part_focus_tags": sorted(declared_tags),
        "benchmark_body_part_tag_counts": tag_counts,
        "benchmark_missing_body_part_focus_tags": missing_tags,
        "benchmark_strata": strata,
        "selection_sets_are_disjoint": selection.get("sets_are_disjoint") is True,
    }


def _read_inventory(database: Path) -> dict[str, int]:
    uri = f"{database.resolve(strict=True).as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not {"images", "runs"}.issubset(tables):
            raise VisualReferenceReadinessError(
                "reference inventory required tables are unavailable"
            )
        rows = connection.execute(
            "SELECT status, COUNT(*) FROM images GROUP BY status ORDER BY status"
        )
        statuses = {str(status): int(count) for status, count in rows}
    except sqlite3.Error as exc:
        raise VisualReferenceReadinessError(
            "reference inventory query failed closed"
        ) from exc
    finally:
        connection.close()
    return {
        "total_images": sum(statuses.values()),
        "valid_images": statuses.get("valid", 0),
        "invalid_images": statuses.get("invalid", 0),
    }


def _verify_annotation_registry(path: Path) -> dict[str, int]:
    registry = _read_object(path)
    datasets = registry.get("datasets")
    registry_root_value = registry.get("root")
    if not isinstance(datasets, list) or not datasets:
        raise VisualReferenceReadinessError("dataset registry is empty")
    if not isinstance(registry_root_value, str) or not registry_root_value:
        raise VisualReferenceReadinessError("dataset registry root is invalid")
    registry_root = Path(registry_root_value).resolve(strict=True)
    declared = 0
    verified = 0
    bbox_annotations = 0
    segmentation_annotations = 0
    for dataset in datasets:
        if not isinstance(dataset, dict):
            raise VisualReferenceReadinessError("dataset registry entry is invalid")
        root_value = dataset.get("path")
        annotations = dataset.get("annotation_files")
        if not isinstance(root_value, str) or not isinstance(annotations, list):
            raise VisualReferenceReadinessError(
                "dataset annotation registry is invalid"
            )
        bbox_annotations += int(dataset.get("bbox_annotations", 0))
        segmentation_annotations += int(dataset.get("segmentation_annotations", 0))
        root = Path(root_value).resolve(strict=True)
        try:
            root.relative_to(registry_root)
        except ValueError as exc:
            raise VisualReferenceReadinessError(
                "dataset source escapes the registry root"
            ) from exc
        for annotation in annotations:
            declared += 1
            if not isinstance(annotation, dict):
                raise VisualReferenceReadinessError(
                    "dataset annotation entry is invalid"
                )
            relative = annotation.get("path")
            expected = annotation.get("sha256")
            if (
                not isinstance(relative, str)
                or not relative
                or Path(relative).is_absolute()
                or not isinstance(expected, str)
                or len(expected) != 64
            ):
                raise VisualReferenceReadinessError(
                    "dataset annotation binding is invalid"
                )
            candidate = (registry_root / relative).resolve(strict=True)
            try:
                candidate.relative_to(root)
            except ValueError as exc:
                raise VisualReferenceReadinessError(
                    "dataset annotation escapes its source root"
                ) from exc
            if _file_evidence(candidate)["sha256"] != expected:
                raise VisualReferenceReadinessError(
                    f"dataset annotation hash mismatch: {relative}"
                )
            verified += 1
    return {
        "datasets": len(datasets),
        "annotation_files_declared": declared,
        "annotation_files_verified": verified,
        "annotation_file_hash_mismatches": declared - verified,
        "bbox_annotations_declared": bbox_annotations,
        "segmentation_annotations_declared": segmentation_annotations,
    }


def build_visual_reference_readiness(
    *,
    inventory_summary: Path,
    inventory_database: Path,
    library_database: Path,
    dataset_registry: Path,
    ontology_crosswalk: Path,
    observed_at_utc: str,
) -> dict[str, Any]:
    """Return one immutable reference-only readiness observation."""

    summary = _read_object(inventory_summary)
    inventory = _read_inventory(inventory_database)
    library = _read_library(library_database)
    annotation_registry = _verify_annotation_registry(dataset_registry)
    if summary.get("content_hint_is_organizational_only") is not True:
        raise VisualReferenceReadinessError(
            "inventory content-hint authority boundary is unavailable"
        )
    if int(summary.get("total_images", -1)) != library["counts"]["images"]:
        raise VisualReferenceReadinessError(
            "inventory summary and reference library image counts disagree"
        )
    if (
        inventory["total_images"] != int(summary["total_images"])
        or inventory["valid_images"] != int(summary["status_counts"]["valid"])
        or inventory["invalid_images"] != int(summary["status_counts"]["invalid"])
    ):
        raise VisualReferenceReadinessError(
            "inventory database and inventory summary counts disagree"
        )
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "observed_at_utc": observed_at_utc,
        "sources": {
            "inventory_summary": _file_evidence(inventory_summary),
            "inventory_database": _file_evidence(inventory_database),
            "library_database": _file_evidence(library_database),
            "dataset_registry": _file_evidence(dataset_registry),
            "ontology_crosswalk": _file_evidence(ontology_crosswalk),
        },
        "reference_library": library,
        "source_inventory": {
            **inventory,
            "source_files_modified": int(summary["source_files_modified"]),
            "content_hint_is_organizational_only": True,
        },
        "annotation_registry": annotation_registry,
        "authority_boundary": {
            "classification": "REFERENCE_COVERAGE_ONLY",
            "promotion_allowed": False,
            "qualified_mask_truth_present": False,
            "qualified_high_end_primary_present": False,
            "qualified_independent_family_juror_present": False,
            "reference_metadata_can_approve_masks": False,
            "limitations": [
                "Body-part focus tags are retrieval metadata, not segmentation labels.",
                "Benchmark selection proves reference coverage, not mask correctness.",
                "No current source-bound qualified primary critic certificate is bound.",
                "No current independent-family juror certificate is bound.",
                "Historical visual receipts are not restored or counted as current authority.",
            ],
        },
        "readiness": {
            "all_declared_body_part_focus_tags_represented": not library[
                "benchmark_missing_body_part_focus_tags"
            ],
            "reference_sources_hash_bound": True,
            "ready_for_source_bound_candidate_screening": True,
            "ready_for_source_bound_candidate_selection": False,
            "metadata_candidate_selection_requires_direct_visual_confirmation": True,
            "ready_for_visual_qualification": False,
        },
        "self_sha256": ZERO_SHA256,
    }
    receipt["self_sha256"] = canonical_sha256(receipt)
    return receipt


def validate_visual_reference_readiness(receipt: dict[str, Any]) -> None:
    """Fail closed unless the receipt preserves the reference-only boundary."""

    declared = receipt.get("self_sha256")
    if not isinstance(declared, str) or len(declared) != 64:
        raise VisualReferenceReadinessError("readiness self hash is invalid")
    canonical = dict(receipt)
    canonical["self_sha256"] = ZERO_SHA256
    if canonical_sha256(canonical) != declared:
        raise VisualReferenceReadinessError("readiness self hash mismatch")
    boundary = receipt.get("authority_boundary")
    readiness = receipt.get("readiness")
    if not isinstance(boundary, dict) or not isinstance(readiness, dict):
        raise VisualReferenceReadinessError("readiness authority fields are invalid")
    if (
        boundary.get("classification") != "REFERENCE_COVERAGE_ONLY"
        or boundary.get("promotion_allowed") is not False
        or boundary.get("qualified_mask_truth_present") is not False
        or boundary.get("qualified_high_end_primary_present") is not False
        or boundary.get("qualified_independent_family_juror_present") is not False
        or readiness.get("ready_for_source_bound_candidate_screening") is not True
        or readiness.get("ready_for_source_bound_candidate_selection") is not False
        or readiness.get(
            "metadata_candidate_selection_requires_direct_visual_confirmation"
        )
        is not True
        or readiness.get("ready_for_visual_qualification") is not False
    ):
        raise VisualReferenceReadinessError(
            "readiness receipt exceeds reference-only authority"
        )
