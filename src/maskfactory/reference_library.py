"""Reference-library status and authority/isolation validation."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

REFERENCE_TIERS = ("benchmark_reference", "retrieval_reference")


class ReferenceLibraryError(ValueError):
    """Reference-library policy, state, or isolation is invalid."""


def load_reference_library_policy(path: Path) -> dict[str, Any]:
    policy = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_reference_library_policy(policy)
    return policy


def validate_reference_library_policy(policy: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != "1.0.0":
        raise ReferenceLibraryError("reference-library policy must be schema 1.0.0")
    if policy.get("source_role") != "unlabeled_reference_corpus":
        raise ReferenceLibraryError("reference library must remain an unlabeled corpus")
    if policy.get("truth_authority") != "none" or policy.get("originals_are_immutable") is not True:
        raise ReferenceLibraryError("reference source has truth authority or mutable originals")
    content = policy.get("content_policy")
    if not isinstance(content, Mapping):
        raise ReferenceLibraryError("reference content policy is missing")
    required_content = {
        "adult_content_is_eligible": True,
        "nsfw_tag_is_organizational_not_an_exclusion": True,
        "known_or_suspected_minor_is_prohibited": True,
        "require_governed_source_rights": True,
    }
    for field, expected in required_content.items():
        if content.get(field) is not expected:
            raise ReferenceLibraryError(f"reference content policy violates {field}")
    tiers = policy.get("tiers")
    if not isinstance(tiers, Mapping) or set(tiers) != set(REFERENCE_TIERS):
        raise ReferenceLibraryError("reference tiers must be benchmark and retrieval")
    for tier, entry in tiers.items():
        if not isinstance(entry.get("target_count"), int) or entry["target_count"] <= 0:
            raise ReferenceLibraryError(f"reference tier has invalid target: {tier}")
        if entry.get("training_eligible") is not False or entry.get("truth_authority") != "none":
            raise ReferenceLibraryError(f"reference tier gained training/truth authority: {tier}")
    if tiers["benchmark_reference"].get("retrieval_eligible") is not False:
        raise ReferenceLibraryError("benchmark tier cannot be a retrieval pool")
    isolation = policy.get("isolation")
    if (
        not isinstance(isolation, Mapping)
        or not isolation
        or any(value != 0 for value in isolation.values())
    ):
        raise ReferenceLibraryError("every reference isolation overlap target must be zero")


def inspect_reference_database(path: Path) -> dict[str, Any]:
    """Read pipeline progress without writing or walking the image library."""
    path = Path(path)
    report: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        return report
    report["bytes"] = path.stat().st_size
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=120)
    try:
        tables = _table_names(connection)
        report["tables"] = sorted(tables)
        report["table_counts"] = {table: _count(connection, table) for table in sorted(tables)}
        if "visual_index" in tables:
            report["visual_status"] = dict(
                connection.execute("SELECT status, COUNT(*) FROM visual_index GROUP BY status")
            )
        if "exact_members" in tables:
            report["exact_representatives"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM exact_members WHERE is_representative=1"
                ).fetchone()[0]
            )
        if "selections" in tables:
            report["selection_tiers"] = dict(
                connection.execute("SELECT tier, COUNT(*) FROM selections GROUP BY tier")
            )
        if "pipeline_runs" in tables:
            columns = ("id", "stage", "started_at", "completed_at", "processed", "failed")
            report["recent_pipeline_runs"] = [
                dict(zip(columns, row, strict=True))
                for row in connection.execute(
                    "SELECT id, stage, started_at, completed_at, processed, failed "
                    "FROM pipeline_runs ORDER BY id DESC LIMIT 10"
                )
            ]
        representatives = report.get("exact_representatives")
        visual_status = report.get("visual_status", {})
        if representatives is not None:
            classified = int(visual_status.get("valid", 0)) + int(visual_status.get("invalid", 0))
            report["index_progress"] = {
                "classified": classified,
                "remaining": max(0, int(representatives) - classified),
                "percent": round(100.0 * classified / max(1, int(representatives)), 3),
                "complete": classified == int(representatives),
            }
    finally:
        connection.close()
    return report


def validate_reference_selection(database: Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    """Validate selection counts, tier disjointness, and materialized hashes."""
    validate_reference_library_policy(policy)
    database = Path(database)
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=120)
    issues: list[str] = []
    try:
        if "selections" not in _table_names(connection):
            raise ReferenceLibraryError("reference database has no selections table")
        rows = connection.execute(
            "SELECT s.relative_path, s.tier, s.materialized_path, s.materialized_sha256, "
            "i.sha256 FROM selections s JOIN images i ON i.relative_path=s.relative_path"
        ).fetchall()
        by_tier = {tier: [] for tier in REFERENCE_TIERS}
        for row in rows:
            if row[1] not in by_tier:
                issues.append(f"unknown_tier:{row[1]}")
                continue
            by_tier[row[1]].append(row)
        for tier, selected in by_tier.items():
            target = int(policy["tiers"][tier]["target_count"])
            if len(selected) != target:
                issues.append(f"selection_count:{tier}:{len(selected)}!={target}")
        path_sets = {tier: {row[0] for row in rows} for tier, rows in by_tier.items()}
        sha_sets = {tier: {row[4] for row in rows} for tier, rows in by_tier.items()}
        if path_sets[REFERENCE_TIERS[0]] & path_sets[REFERENCE_TIERS[1]]:
            issues.append("relative_path_overlap_between_tiers")
        if sha_sets[REFERENCE_TIERS[0]] & sha_sets[REFERENCE_TIERS[1]]:
            issues.append("exact_sha256_overlap_between_tiers")
        for tier_rows in by_tier.values():
            for relative_path, tier, materialized_path, claimed_sha, _source_sha in tier_rows:
                path = Path(materialized_path) if materialized_path else None
                if path is None or not path.is_file():
                    issues.append(f"missing_materialized:{tier}:{relative_path}")
                elif claimed_sha != _sha256_file(path):
                    issues.append(f"materialized_hash_mismatch:{tier}:{relative_path}")
    finally:
        connection.close()
    return {
        "schema_version": "1.0.0",
        "database": str(database),
        "selection_counts": {tier: len(rows) for tier, rows in by_tier.items()},
        "issues": sorted(set(issues)),
        "passed": not issues,
    }


def validate_benchmark_training_isolation(
    database: Path, training_records: Iterable[Mapping[str, Any]]
) -> tuple[str, ...]:
    """Reject exact or perceptual overlap between benchmark references and model data."""
    connection = sqlite3.connect(f"file:{Path(database)}?mode=ro", uri=True, timeout=120)
    try:
        benchmark = connection.execute(
            "SELECT i.sha256, i.dhash64 FROM selections s "
            "JOIN images i ON i.relative_path=s.relative_path "
            "WHERE s.tier='benchmark_reference'"
        ).fetchall()
    finally:
        connection.close()
    benchmark_sha = {str(row[0]) for row in benchmark if row[0]}
    benchmark_dhash = {str(row[1]) for row in benchmark if row[1]}
    issues: list[str] = []
    for index, record in enumerate(training_records):
        source_sha = record.get("source_sha256")
        dhash = record.get("dhash64") or record.get("phash64")
        if source_sha and str(source_sha) in benchmark_sha:
            issues.append(f"exact_overlap:{index}:{source_sha}")
        if dhash and str(dhash) in benchmark_dhash:
            issues.append(f"perceptual_overlap:{index}:{dhash}")
    return tuple(sorted(set(issues)))


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "REFERENCE_TIERS",
    "ReferenceLibraryError",
    "inspect_reference_database",
    "load_reference_library_policy",
    "validate_benchmark_training_isolation",
    "validate_reference_library_policy",
    "validate_reference_selection",
]
