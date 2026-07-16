"""Reference-library status and authority/isolation validation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import yaml
from PIL import Image, ImageOps

REFERENCE_TIERS = ("benchmark_reference", "retrieval_reference")
_COVERAGE_VIEW_MAP = {
    "front": ("front",),
    "back": ("back",),
    "left_profile": ("profile",),
    "right_profile": ("profile",),
    "left_3_4": ("three_quarter",),
    "right_3_4": ("three_quarter",),
}
_COVERAGE_POSE_MAP = {
    "seated_or_crouched": ("sitting", "kneeling"),
    "lying": ("lying",),
    "walking": ("walking_running",),
    "leg_overlap": ("interacting", "bent_twisted"),
}
_COVERAGE_CONTEXT_MAP = {
    "solo": ("one",),
    "duo": ("two",),
    "small_group": ("small_group",),
}
_PART_REFERENCE_TAGS = {
    "hand": "part_hand_fingers",
    "finger": "part_hand_fingers",
    "foot": "part_foot_toes",
    "toe": "part_foot_toes",
    "ankle": "part_ankle",
    "knee": "part_knee",
    "thigh": "part_thigh",
    "calf": "part_lower_leg_calf",
    "forearm": "part_forearm_wrist",
    "wrist": "part_forearm_wrist",
    "elbow": "part_elbow",
    "shoulder": "part_shoulder",
    "hair": "part_hair",
    "ear": "part_ear",
    "face": "part_head_face",
    "breast": "part_chest_breasts",
    "torso": "part_torso_abdomen",
    "glute": "part_hips_pelvis_buttocks",
}


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
    for root_name in ("source_root", "output_root"):
        root_value = policy.get(root_name)
        if not isinstance(root_value, str) or not Path(root_value).is_absolute():
            raise ReferenceLibraryError(f"reference {root_name} must be an absolute path")
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


def inspect_reference_selection(database: Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    """Prove deterministic near-dedup and tier selection before materialization."""
    validate_reference_library_policy(policy)
    database = Path(database)
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=120)
    connection.row_factory = sqlite3.Row
    issues: list[str] = []
    required_tables = {
        "exact_members",
        "images",
        "near_duplicate_members",
        "pipeline_meta",
        "selections",
        "visual_index",
    }
    try:
        tables = _table_names(connection)
        missing_tables = sorted(required_tables - tables)
        if missing_tables:
            raise ReferenceLibraryError(
                "reference selection database is missing: " + ", ".join(missing_tables)
            )
        metadata = {
            str(row["key"]): json.loads(str(row["value_json"]))
            for row in connection.execute("SELECT key,value_json FROM pipeline_meta")
        }
        exact_representatives = _scalar(
            connection,
            "SELECT COUNT(*) FROM exact_members WHERE is_representative=1",
        )
        visual_valid = _scalar(connection, "SELECT COUNT(*) FROM visual_index WHERE status='valid'")
        visual_invalid = _scalar(
            connection, "SELECT COUNT(*) FROM visual_index WHERE status='invalid'"
        )
        near_members = _scalar(connection, "SELECT COUNT(*) FROM near_duplicate_members")
        near_clusters = _scalar(
            connection, "SELECT COUNT(DISTINCT cluster_id) FROM near_duplicate_members"
        )
        near_meta = metadata.get("near_dedup", {})
        if visual_valid + visual_invalid != exact_representatives:
            issues.append("visual_index_incomplete")
        if visual_invalid:
            issues.append(f"visual_index_invalid:{visual_invalid}")
        if near_members != exact_representatives:
            issues.append(f"near_member_count:{near_members}!={exact_representatives}")
        if near_meta.get("near_unique") != near_clusters:
            issues.append(f"near_cluster_count:{near_clusters}!={near_meta.get('near_unique')}")

        selection_counts = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT tier,COUNT(*) FROM selections GROUP BY tier ORDER BY tier"
            )
        }
        for tier in REFERENCE_TIERS:
            target = int(policy["tiers"][tier]["target_count"])
            if selection_counts.get(tier, 0) != target:
                issues.append(f"selection_count:{tier}:{selection_counts.get(tier, 0)}!={target}")
        issues.extend(
            f"unknown_tier:{tier}" for tier in sorted(set(selection_counts) - set(REFERENCE_TIERS))
        )
        missing_near_members = _scalar(
            connection,
            "SELECT COUNT(*) FROM selections s LEFT JOIN near_duplicate_members n "
            "ON n.relative_path=s.relative_path WHERE n.relative_path IS NULL",
        )
        if missing_near_members:
            issues.append(f"selection_missing_near_group:{missing_near_members}")
        exact_sha_overlap = _scalar(
            connection,
            "SELECT COUNT(*) FROM (SELECT i.sha256 FROM selections s JOIN images i "
            "ON i.relative_path=s.relative_path GROUP BY i.sha256 "
            "HAVING COUNT(DISTINCT s.tier)>1)",
        )
        if exact_sha_overlap:
            issues.append(f"exact_sha256_overlap_between_tiers:{exact_sha_overlap}")
        near_cluster_overlap = _scalar(
            connection,
            "SELECT COUNT(*) FROM (SELECT n.cluster_id FROM selections s "
            "JOIN near_duplicate_members n ON n.relative_path=s.relative_path "
            "GROUP BY n.cluster_id HAVING COUNT(DISTINCT s.tier)>1)",
        )
        if near_cluster_overlap:
            issues.append(f"near_duplicate_cluster_overlap_between_tiers:{near_cluster_overlap}")

        body_part_tags = tuple(
            sorted(metadata.get("library_purpose", {}).get("body_part_focus_tags", []))
        )
        selected_tags: Counter[str] = Counter()
        for row in connection.execute(
            "SELECT v.tags_json FROM selections s JOIN visual_index v "
            "ON v.relative_path=s.relative_path"
        ):
            selected_tags.update(json.loads(str(row[0])))
        body_part_coverage = {tag: int(selected_tags.get(tag, 0)) for tag in body_part_tags}
        issues.extend(
            f"missing_body_part_tag:{tag}"
            for tag, count in body_part_coverage.items()
            if count == 0
        )

        near_fingerprint = _rows_fingerprint(
            connection.execute(
                "SELECT relative_path,cluster_id,representative_path,group_size,similarity "
                "FROM near_duplicate_members ORDER BY relative_path"
            )
        )
        selection_fingerprint = _rows_fingerprint(
            connection.execute(
                "SELECT tier,rank,relative_path,selection_score,selection_reasons_json "
                "FROM selections ORDER BY tier,rank,relative_path"
            )
        )
        selected_bytes = {
            str(row[0]): int(row[1] or 0)
            for row in connection.execute(
                "SELECT s.tier,SUM(i.size_bytes) FROM selections s JOIN images i "
                "ON i.relative_path=s.relative_path GROUP BY s.tier ORDER BY s.tier"
            )
        }
    finally:
        connection.close()
    return {
        "schema_version": "1.0.0",
        "database": str(database),
        "exact_representatives": exact_representatives,
        "visual_valid": visual_valid,
        "visual_invalid": visual_invalid,
        "near_duplicate_members": near_members,
        "near_duplicate_clusters": near_clusters,
        "near_duplicates_removed": exact_representatives - near_clusters,
        "near_group_fingerprint": near_fingerprint,
        "selection_counts": selection_counts,
        "selection_bytes": selected_bytes,
        "selection_fingerprint": selection_fingerprint,
        "cross_tier_exact_sha_overlap": exact_sha_overlap,
        "cross_tier_near_cluster_overlap": near_cluster_overlap,
        "body_part_coverage": body_part_coverage,
        "issues": sorted(set(issues)),
        "passed": not issues,
    }


def publish_reference_database_snapshot(database: Path, output_path: Path) -> dict[str, Any]:
    """Atomically publish one transactionally consistent copy of the live reference DB."""
    database = Path(database).resolve(strict=True)
    output_path = Path(output_path).resolve()
    if database == output_path:
        raise ReferenceLibraryError("reference database snapshot source and output must differ")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.partial-{os.getpid()}")
    temporary.unlink(missing_ok=True)
    source = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=120)
    destination: sqlite3.Connection | None = None
    try:
        if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ReferenceLibraryError("source reference database failed quick_check")
        destination = sqlite3.connect(temporary)
        source.backup(destination)
        destination.commit()
        if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ReferenceLibraryError("copied reference database failed quick_check")
        destination.close()
        destination = None
        with temporary.open("rb+") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
    except sqlite3.Error as exc:
        raise ReferenceLibraryError(f"reference database snapshot failed: {exc}") from exc
    finally:
        if destination is not None:
            destination.close()
        source.close()
        temporary.unlink(missing_ok=True)
    return {
        "schema_version": "1.0.0",
        "source": str(database),
        "output": str(output_path),
        "bytes": output_path.stat().st_size,
        "sha256": _sha256_file(output_path),
        "quick_check": "ok",
    }


def materialize_reference_tier(
    database: Path,
    policy: Mapping[str, Any],
    tier: str,
    *,
    max_items: int = 100,
    soft_floor_gib: float = 150.0,
    hard_floor_gib: float = 100.0,
    free_bytes_provider: Callable[[Path], int] | None = None,
) -> dict[str, Any]:
    """Materialize one bounded, resumable reference tier under shared-F capacity gates."""
    validate_reference_library_policy(policy)
    if tier not in REFERENCE_TIERS:
        raise ReferenceLibraryError(f"unknown reference tier: {tier}")
    if max_items <= 0:
        raise ReferenceLibraryError("reference materialization max_items must be positive")
    if not 0 < hard_floor_gib < soft_floor_gib:
        raise ReferenceLibraryError("reference materialization capacity floors are invalid")
    database = Path(database)
    source_root = Path(str(policy["source_root"])).resolve(strict=True)
    output_root = Path(str(policy["output_root"])).resolve(strict=True)
    get_free_bytes = free_bytes_provider or (lambda root: int(shutil.disk_usage(root).free))
    gib = 1024**3
    connection = sqlite3.connect(database, timeout=120)
    connection.row_factory = sqlite3.Row
    processed = reused = 0
    issues: list[str] = []
    capacity_hold: dict[str, Any] | None = None
    try:
        target = int(policy["tiers"][tier]["target_count"])
        selected_count = _scalar(
            connection, "SELECT COUNT(*) FROM selections WHERE tier=?", (tier,)
        )
        if selected_count != target:
            raise ReferenceLibraryError(
                f"reference tier selection is incomplete: {tier}:{selected_count}!={target}"
            )
        rows = connection.execute(
            "SELECT s.relative_path,s.rank,s.materialized_path,s.materialized_sha256,"
            "i.sha256,i.size_bytes,v.content_state,v.person_count "
            "FROM selections s JOIN images i ON i.relative_path=s.relative_path "
            "JOIN visual_index v ON v.relative_path=s.relative_path "
            "WHERE s.tier=? AND (s.materialized_path IS NULL OR s.materialized_sha256 IS NULL) "
            "ORDER BY s.rank,s.relative_path LIMIT ?",
            (tier, max_items),
        ).fetchall()
        for row in rows:
            source = _path_under_root(source_root, str(row["relative_path"]))
            relative_destination = _reference_materialized_relative_path(row, tier)
            destination = _path_under_root(output_root, relative_destination.as_posix())
            expected_sha = str(row["sha256"])
            expected_size = int(row["size_bytes"])
            if not source.is_file():
                issues.append(f"source_missing:{row['relative_path']}")
                break
            source_before = (source.stat().st_size, source.stat().st_mtime_ns)
            if destination.exists():
                if _sha256_file(source) != expected_sha:
                    issues.append(f"source_hash_conflict:{row['relative_path']}")
                    break
                if destination.stat().st_size != expected_size:
                    issues.append(f"destination_size_conflict:{relative_destination.as_posix()}")
                    break
                observed_sha = _sha256_file(destination)
                if observed_sha != expected_sha:
                    issues.append(f"destination_hash_conflict:{relative_destination.as_posix()}")
                    break
                reused += 1
            else:
                free_bytes = int(get_free_bytes(output_root))
                if free_bytes < int(soft_floor_gib * gib):
                    capacity_hold = {
                        "reason": "storage_below_soft_floor",
                        "free_bytes": free_bytes,
                        "free_gib": round(free_bytes / gib, 3),
                        "soft_floor_gib": soft_floor_gib,
                        "hard_floor_gib": hard_floor_gib,
                    }
                    break
                if free_bytes - expected_size < int(hard_floor_gib * gib):
                    capacity_hold = {
                        "reason": "copy_would_cross_hard_floor",
                        "free_bytes": free_bytes,
                        "free_gib": round(free_bytes / gib, 3),
                        "copy_bytes": expected_size,
                        "soft_floor_gib": soft_floor_gib,
                        "hard_floor_gib": hard_floor_gib,
                    }
                    break
                destination.parent.mkdir(parents=True, exist_ok=True)
                partial = destination.with_suffix(destination.suffix + ".partial")
                if partial.exists():
                    partial.unlink()
                try:
                    shutil.copy2(source, partial)
                    with partial.open("rb+") as handle:
                        os.fsync(handle.fileno())
                    if partial.stat().st_size != expected_size:
                        raise ReferenceLibraryError(
                            "copied reference size does not match inventory"
                        )
                    observed_sha = _sha256_file(partial)
                    if observed_sha != expected_sha:
                        raise ReferenceLibraryError(
                            "copied reference hash does not match inventory"
                        )
                    os.replace(partial, destination)
                finally:
                    if partial.exists():
                        partial.unlink()
                processed += 1
            source_after = (source.stat().st_size, source.stat().st_mtime_ns)
            if source_after != source_before:
                issues.append(f"source_mutated_during_copy:{row['relative_path']}")
                break
            connection.execute(
                "UPDATE selections SET materialized_path=?,materialized_sha256=?,"
                "materialized_at=datetime('now') WHERE relative_path=? AND tier=?",
                (
                    relative_destination.as_posix(),
                    expected_sha,
                    row["relative_path"],
                    tier,
                ),
            )
            connection.commit()
        remaining = _scalar(
            connection,
            "SELECT COUNT(*) FROM selections WHERE tier=? AND "
            "(materialized_path IS NULL OR materialized_sha256 IS NULL)",
            (tier,),
        )
        materialized = selected_count - remaining
    except sqlite3.Error as exc:
        connection.rollback()
        raise ReferenceLibraryError(f"reference materialization database failure: {exc}") from exc
    finally:
        connection.close()
    return {
        "schema_version": "1.0.0",
        "database": str(database),
        "tier": tier,
        "target_count": selected_count,
        "processed_this_chunk": processed,
        "reused_this_chunk": reused,
        "materialized_count": materialized,
        "remaining_count": remaining,
        "complete": remaining == 0 and not issues,
        "capacity_hold": capacity_hold,
        "issues": issues,
        "source_files_modified": 0,
    }


def validate_reference_materialized_tier(
    database: Path, policy: Mapping[str, Any], tier: str
) -> dict[str, Any]:
    """Independently hash every output in one reference tier."""
    validate_reference_library_policy(policy)
    if tier not in REFERENCE_TIERS:
        raise ReferenceLibraryError(f"unknown reference tier: {tier}")
    output_root = Path(str(policy["output_root"])).resolve(strict=True)
    connection = sqlite3.connect(f"file:{Path(database)}?mode=ro", uri=True, timeout=120)
    try:
        rows = connection.execute(
            "SELECT s.relative_path,s.materialized_path,s.materialized_sha256,i.sha256,i.size_bytes "
            "FROM selections s JOIN images i ON i.relative_path=s.relative_path "
            "WHERE s.tier=? ORDER BY s.rank,s.relative_path",
            (tier,),
        ).fetchall()
    finally:
        connection.close()
    target = int(policy["tiers"][tier]["target_count"])
    issues: list[str] = []
    total_bytes = 0
    identities = []
    if len(rows) != target:
        issues.append(f"selection_count:{len(rows)}!={target}")
    for relative_path, materialized_path, claimed_sha, source_sha, source_size in rows:
        if not materialized_path:
            issues.append(f"missing_materialized:{relative_path}")
            continue
        try:
            path = _path_under_root(output_root, str(materialized_path))
        except ReferenceLibraryError:
            issues.append(f"materialized_path_escape:{relative_path}")
            continue
        if not path.is_file():
            issues.append(f"missing_materialized:{relative_path}")
            continue
        observed_size = path.stat().st_size
        if observed_size != int(source_size):
            issues.append(f"materialized_size_mismatch:{relative_path}")
            continue
        if claimed_sha != source_sha:
            issues.append(f"materialized_source_hash_mismatch:{relative_path}")
            continue
        observed_sha = _sha256_file(path)
        if observed_sha != claimed_sha:
            issues.append(f"materialized_hash_mismatch:{relative_path}")
            continue
        total_bytes += observed_size
        identities.append((str(materialized_path), str(observed_sha), int(observed_size)))
    tier_root = output_root / tier
    partials = sorted(
        path.relative_to(output_root).as_posix()
        for path in tier_root.rglob("*.partial*")
        if path.is_file()
    )
    if partials:
        issues.append(f"orphan_partial_files:{len(partials)}")
    return {
        "schema_version": "1.0.0",
        "database": str(database),
        "tier": tier,
        "target_count": target,
        "verified_count": len(identities),
        "verified_bytes": total_bytes,
        "materialized_fingerprint": _rows_fingerprint(identities),
        "orphan_partial_files": partials,
        "issues": issues,
        "passed": not issues,
    }


def retrieve_reference_candidates(
    database: Path,
    query: Mapping[str, Any],
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """Rank retrieval-only references for one deficit without granting authority."""
    if limit <= 0 or limit > 100:
        raise ReferenceLibraryError("reference retrieval limit must be within 1..100")
    expected_views = set(_COVERAGE_VIEW_MAP.get(str(query.get("view")), ()))
    expected_poses = set(_COVERAGE_POSE_MAP.get(str(query.get("pose")), ()))
    expected_counts = set(_COVERAGE_CONTEXT_MAP.get(str(query.get("instance_context")), ()))
    required_tags = {
        str(value) for value in query.get("required_tags", ()) if isinstance(value, str) and value
    }
    failed_part = str(query.get("failed_body_part", "")).casefold()
    required_tags.update(tag for token, tag in _PART_REFERENCE_TAGS.items() if token in failed_part)
    connection = sqlite3.connect(f"file:{Path(database)}?mode=ro", uri=True, timeout=120)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT s.relative_path,s.rank,s.selection_score,s.materialized_path,"
            "i.sha256,i.quality_score,v.person_count,v.framing,v.view,v.pose,"
            "v.content_state,v.presentation,v.body_type,v.background,v.lighting,"
            "v.difficulty_score,v.tags_json FROM selections s "
            "JOIN images i ON i.relative_path=s.relative_path "
            "JOIN visual_index v ON v.relative_path=s.relative_path "
            "WHERE s.tier='retrieval_reference'"
        ).fetchall()
    finally:
        connection.close()
    ranked = []
    for row in rows:
        tags = set(json.loads(str(row["tags_json"])))
        matched_tags = sorted(required_tags & tags)
        matched = {
            "view": bool(expected_views and row["view"] in expected_views),
            "pose": bool(expected_poses and row["pose"] in expected_poses),
            "instance_context": bool(expected_counts and row["person_count"] in expected_counts),
        }
        score = (
            8.0 * sum(matched.values())
            + 20.0 * len(matched_tags)
            + 2.0 * float(row["difficulty_score"] or 0.0)
            + float(row["quality_score"] or 0.0)
            + 0.1 * float(row["selection_score"] or 0.0)
        )
        ranked.append((score, str(row["relative_path"]), row, matched, matched_tags, tags))
    eligible = [item for item in ranked if item[4]] if required_tags else ranked
    if not eligible:
        eligible = ranked
    selected = sorted(eligible, key=lambda item: (-item[0], item[1]))[:limit]
    candidates = []
    for score, relative_path, row, matched, matched_tags, tags in selected:
        candidates.append(
            {
                "reference_id": f"ref_{str(row['sha256'])[:24]}",
                "relative_path": relative_path,
                "materialized_path": row["materialized_path"],
                "sha256": row["sha256"],
                "rank": int(row["rank"]),
                "retrieval_score": round(score, 9),
                "matched_attributes": [name for name, value in matched.items() if value],
                "matched_tags": matched_tags,
                "attributes": {
                    name: row[name]
                    for name in (
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
                },
                "tags": sorted(tags),
                "source_role": "unlabeled_reference_corpus",
                "truth_authority": "none",
                "training_eligible": False,
                "use": "acquisition_context_only_requires_independent_certification",
            }
        )
    return {
        "schema_version": "1.0.0",
        "query": dict(query),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "authority": {
            "source_role": "unlabeled_reference_corpus",
            "truth_authority": "none",
            "training_eligible": False,
            "selection_or_retrieval_creates_truth": False,
        },
    }


def write_reference_acquisition_context(
    database: Path,
    *,
    coverage_deficits: Iterable[Mapping[str, Any]],
    failures: Iterable[Mapping[str, Any]],
    output_path: Path,
    limit_per_target: int = 5,
) -> Path:
    """Atomically attach retrieval-only examples to coverage and failure targets."""
    targets = []
    for index, deficit in enumerate(coverage_deficits):
        query = {
            "view": deficit.get("view"),
            "pose": deficit.get("pose"),
            "instance_context": deficit.get("instance_context"),
            "deficit": deficit.get("deficit"),
        }
        targets.append(
            {
                "target_id": f"coverage_{index:03d}",
                "target_type": "coverage_deficit",
                "retrieval": retrieve_reference_candidates(database, query, limit=limit_per_target),
            }
        )
    for index, failure in enumerate(failures):
        query = {
            "failed_body_part": failure.get("failed_body_part"),
            "failure_reason": failure.get("failure_reason"),
            "pose": failure.get("pose_angle"),
        }
        targets.append(
            {
                "target_id": f"failure_{index:03d}",
                "target_type": "hard_case_failure",
                "retrieval": retrieve_reference_candidates(database, query, limit=limit_per_target),
            }
        )
    document = {
        "schema_version": "1.0.0",
        "database": str(database),
        "target_count": len(targets),
        "targets": targets,
        "authority": {
            "source_role": "unlabeled_reference_corpus",
            "truth_authority": "none",
            "training_eligible": False,
            "independent_certification_required_for_any_truth": True,
        },
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return output_path


def validate_reference_selection(database: Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    """Validate selection counts, tier disjointness, and materialized hashes."""
    validate_reference_library_policy(policy)
    database = Path(database)
    output_root = Path(str(policy["output_root"])).resolve()
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
        if "near_duplicate_members" in _table_names(connection):
            cross_tier_clusters = connection.execute(
                "SELECT n.cluster_id FROM selections s "
                "JOIN near_duplicate_members n ON n.relative_path=s.relative_path "
                "GROUP BY n.cluster_id HAVING COUNT(DISTINCT s.tier)>1"
            ).fetchall()
            if cross_tier_clusters:
                issues.append("near_duplicate_cluster_overlap_between_tiers")
        for tier_rows in by_tier.values():
            for relative_path, tier, materialized_path, claimed_sha, source_sha in tier_rows:
                if not materialized_path:
                    issues.append(f"missing_materialized:{tier}:{relative_path}")
                    continue
                path = Path(str(materialized_path))
                path = path if path.is_absolute() else output_root / path
                resolved = path.resolve()
                try:
                    resolved.relative_to(output_root)
                except ValueError:
                    issues.append(f"materialized_outside_output_root:{tier}:{relative_path}")
                    continue
                if not resolved.is_file():
                    issues.append(f"missing_materialized:{tier}:{relative_path}")
                elif claimed_sha != source_sha:
                    issues.append(f"materialized_source_hash_mismatch:{tier}:{relative_path}")
                elif claimed_sha != _sha256_file(resolved):
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
    database: Path,
    training_records: Iterable[Mapping[str, Any]],
    *,
    expected_benchmark_count: int | None = None,
) -> tuple[str, ...]:
    """Return fail-closed benchmark leakage findings for every model-data partition."""
    return tuple(
        evaluate_benchmark_training_isolation(
            database,
            training_records,
            expected_benchmark_count=expected_benchmark_count,
        )["issues"]
    )


def evaluate_benchmark_training_isolation(
    database: Path,
    training_records: Iterable[Mapping[str, Any]],
    *,
    expected_benchmark_count: int | None = None,
) -> dict[str, Any]:
    """Reject path, SHA, or conservative dHash-near overlap with the benchmark."""
    connection = sqlite3.connect(f"file:{Path(database)}?mode=ro", uri=True, timeout=120)
    try:
        benchmark = connection.execute(
            "SELECT i.relative_path,i.sha256,i.dhash64 FROM selections s "
            "JOIN images i ON i.relative_path=s.relative_path "
            "WHERE s.tier='benchmark_reference' ORDER BY i.relative_path"
        ).fetchall()
    finally:
        connection.close()
    benchmark_paths = {_normalized_reference_path(str(row[0])) for row in benchmark if row[0]}
    benchmark_sha = {str(row[1]).casefold() for row in benchmark if row[1]}
    benchmark_dhash = tuple(_parse_dhash(str(row[2])) for row in benchmark if row[2])
    benchmark_fingerprint = _rows_fingerprint(benchmark)
    issues: list[str] = []
    if expected_benchmark_count is not None and len(benchmark) != expected_benchmark_count:
        issues.append(f"benchmark_count:{len(benchmark)}!={expected_benchmark_count}")
    partition_counts: Counter[str] = Counter()
    records = tuple(training_records)
    allowed_partitions = {
        "train",
        "val",
        "calibration",
        "holdout",
        "test_holdout",
        "hard_case_holdout",
    }
    for index, record in enumerate(records):
        partition = record.get("partition") or record.get("split")
        if partition not in allowed_partitions:
            issues.append(f"invalid_partition:{index}:{partition}")
        else:
            partition_counts[str(partition)] += 1
        relative_path = record.get("relative_path") or record.get("source_file")
        source_sha = record.get("source_sha256")
        dhash = record.get("dhash64")
        if not isinstance(relative_path, str) or not relative_path:
            issues.append(f"missing_relative_path:{index}")
        elif _normalized_reference_path(relative_path) in benchmark_paths:
            issues.append(f"path_overlap:{index}:{relative_path}")
        if not isinstance(source_sha, str) or len(source_sha) != 64:
            issues.append(f"missing_source_sha256:{index}")
        elif str(source_sha).casefold() in benchmark_sha:
            issues.append(f"exact_overlap:{index}:{source_sha}")
        if not isinstance(dhash, str):
            issues.append(f"missing_dhash64:{index}")
            continue
        try:
            parsed_dhash = _parse_dhash(dhash)
        except ReferenceLibraryError:
            issues.append(f"invalid_dhash64:{index}:{dhash}")
            continue
        if any((parsed_dhash ^ candidate).bit_count() <= 3 for candidate in benchmark_dhash):
            issues.append(f"perceptual_overlap:{index}:{dhash}")
    unique_issues = sorted(set(issues))
    return {
        "schema_version": "1.0.0",
        "database": str(database),
        "benchmark_count": len(benchmark),
        "benchmark_fingerprint": benchmark_fingerprint,
        "record_count": len(records),
        "partition_counts": dict(sorted(partition_counts.items())),
        "dhash_hamming_threshold": 3,
        "conservative_near_duplicate_rule": "dhash_hamming_lte_3_blocks_without_requiring_embedding_confirmation",
        "issues": unique_issues,
        "passed": not unique_issues,
    }


def reference_dhash64(path: Path) -> str:
    """Compute the exact 9x8 bilinear dHash used by the reference inventory."""
    with Image.open(Path(path)) as opened:
        image = ImageOps.exif_transpose(opened.convert("RGB"))
    grayscale = image.convert("L").resize((9, 8), Image.Resampling.BILINEAR)
    pixels = grayscale.tobytes()
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value = (value << 1) | int(pixels[offset + column + 1] > pixels[offset + column])
    return f"{value:016x}"


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _scalar(connection: sqlite3.Connection, query: str, parameters: tuple[Any, ...] = ()) -> int:
    return int(connection.execute(query, parameters).fetchone()[0])


def _rows_fingerprint(rows: Iterable[sqlite3.Row]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        normalized = []
        for value in row:
            if isinstance(value, float):
                normalized.append(format(value, ".17g"))
            elif isinstance(value, str) and value.startswith(("{", "[")):
                try:
                    normalized.append(
                        json.dumps(json.loads(value), sort_keys=True, separators=(",", ":"))
                    )
                except json.JSONDecodeError:
                    normalized.append(value)
            else:
                normalized.append(value)
        digest.update(
            json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _path_under_root(root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ReferenceLibraryError("reference materialization path escapes its governed root")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReferenceLibraryError(
            "reference materialization path escapes its governed root"
        ) from exc
    return resolved


def _safe_reference_stem(path: str) -> str:
    cleaned = "".join(character if character.isalnum() else "_" for character in Path(path).stem)
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return (cleaned[:60] or "image").strip("_")


def _reference_materialized_relative_path(row: Mapping[str, Any], tier: str) -> Path:
    extension = Path(str(row["relative_path"])).suffix.lower() or ".jpg"
    category = f"{row['content_state']}__{row['person_count']}"
    safe_category = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in category
    )
    name = (
        f"{str(row['sha256'])[:16]}__"
        f"{_safe_reference_stem(str(row['relative_path']))}{extension}"
    )
    return Path(tier) / safe_category / name


def _normalized_reference_path(value: str) -> str:
    return value.replace("\\", "/").strip("/").casefold()


def _parse_dhash(value: str) -> int:
    if len(value) != 16:
        raise ReferenceLibraryError("reference dHash must contain exactly 16 hexadecimal digits")
    try:
        parsed = int(value, 16)
    except ValueError as exc:
        raise ReferenceLibraryError("reference dHash is not hexadecimal") from exc
    if not 0 <= parsed < 2**64:
        raise ReferenceLibraryError("reference dHash is outside unsigned 64-bit range")
    return parsed


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "REFERENCE_TIERS",
    "ReferenceLibraryError",
    "evaluate_benchmark_training_isolation",
    "inspect_reference_database",
    "inspect_reference_selection",
    "load_reference_library_policy",
    "materialize_reference_tier",
    "publish_reference_database_snapshot",
    "reference_dhash64",
    "retrieve_reference_candidates",
    "validate_benchmark_training_isolation",
    "validate_reference_materialized_tier",
    "validate_reference_library_policy",
    "validate_reference_selection",
    "write_reference_acquisition_context",
]
