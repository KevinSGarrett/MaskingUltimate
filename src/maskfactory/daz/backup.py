from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

from .control import DazControlError, DazErrorCode


@dataclass(frozen=True)
class TierABackupPolicy:
    document: Mapping[str, Any]
    sha256: str
    include_roots: tuple[str, ...]
    required_categories: Mapping[str, tuple[str, ...]]


def load_tier_a_backup_policy(path: Path) -> TierABackupPolicy:
    path = Path(path)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        schema_path = Path(__file__).parents[1] / "schemas" / "daz_backup.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID,
            f"backup policy is unreadable: {exc}",
            evidence_paths=(str(path),),
        ) from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document), key=lambda item: list(item.path)
    )
    if errors:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID,
            f"backup policy violates its closed schema: {errors[0].message}",
            evidence_paths=(str(path),),
        )
    canonical = _canonical_bytes(document)
    return TierABackupPolicy(
        document=document,
        sha256=hashlib.sha256(canonical).hexdigest(),
        include_roots=tuple(document["include_roots"]),
        required_categories={
            key: tuple(value) for key, value in document["required_restore_categories"].items()
        },
    )


def create_tier_a_backup(
    source_root: Path,
    destination_root: Path,
    policy: TierABackupPolicy,
    *,
    backup_id: str,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Create an immutable hash manifest and payload without following links."""
    source = Path(source_root).resolve(strict=True)
    destination = Path(destination_root).resolve()
    _require_outside(destination, source, "backup destination")
    final = destination / backup_id
    partial = destination / f".{backup_id}.partial"
    if final.exists() or partial.exists():
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "backup destination already exists",
            entity_ids=(backup_id,),
        )
    files = _inventory(source, policy.include_roots)
    category_presence = _category_presence((row[0] for row in files), policy.required_categories)
    missing = sorted(key for key, present in category_presence.items() if not present)
    if missing:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            f"Tier A source is missing required categories: {','.join(missing)}",
            entity_ids=(backup_id,),
        )
    payload = partial / "payload"
    payload.mkdir(parents=True)
    manifest_files: list[dict[str, Any]] = []
    try:
        for relative, source_file in files:
            target = payload / Path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            if relative == "10_queue/queue.sqlite":
                _backup_sqlite(source_file, target)
            else:
                shutil.copyfile(source_file, target, follow_symlinks=False)
            manifest_files.append(
                {
                    "path": relative,
                    "bytes": target.stat().st_size,
                    "sha256": _sha256(target),
                }
            )
        body = {
            "schema_version": "1.0.0",
            "backup_id": backup_id,
            "tier": "A",
            "captured_at": _timestamp(captured_at),
            "policy_sha256": policy.sha256,
            "files": manifest_files,
            "category_presence": category_presence,
        }
        manifest = {**body, "manifest_sha256": hashlib.sha256(_canonical_bytes(body)).hexdigest()}
        (partial / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(partial, final)
    except Exception:
        if partial.exists():
            shutil.rmtree(partial)
        raise
    return {**manifest, "backup_path": str(final)}


def plan_tier_a_backup(
    source_root: Path,
    destination_root: Path,
    policy: TierABackupPolicy,
    *,
    backup_id: str,
) -> dict[str, Any]:
    """Validate the exact source/destination boundary without creating any bytes."""
    source = Path(source_root).resolve(strict=True)
    destination = Path(destination_root).resolve()
    _require_outside(destination, source, "backup destination")
    final = destination / backup_id
    partial = destination / f".{backup_id}.partial"
    if final.exists() or partial.exists():
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "backup destination already exists",
            entity_ids=(backup_id,),
        )
    files = _inventory(source, policy.include_roots)
    categories = _category_presence((row[0] for row in files), policy.required_categories)
    missing = sorted(key for key, present in categories.items() if not present)
    if missing:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            f"Tier A source is missing required categories: {','.join(missing)}",
            entity_ids=(backup_id,),
        )
    return {
        "schema_version": "1.0.0",
        "backup_id": backup_id,
        "tier": "A",
        "apply": False,
        "source_root": str(source),
        "destination_root": str(destination),
        "backup_path": str(final),
        "policy_sha256": policy.sha256,
        "file_count": len(files),
        "source_bytes": sum(path.stat().st_size for _, path in files),
        "category_presence": categories,
    }


def verify_tier_a_backup(backup_root: Path, policy: TierABackupPolicy) -> dict[str, Any]:
    root = Path(backup_root).resolve(strict=True)
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DazControlError(
            DazErrorCode.STATE_DATABASE_INVALID,
            f"backup manifest is unreadable: {exc}",
            evidence_paths=(str(manifest_path),),
        ) from exc
    provided_seal = str(manifest.pop("manifest_sha256", ""))
    if hashlib.sha256(_canonical_bytes(manifest)).hexdigest() != provided_seal:
        raise DazControlError(DazErrorCode.STATE_DATABASE_INVALID, "backup manifest seal mismatch")
    if manifest.get("policy_sha256") != policy.sha256 or manifest.get("tier") != "A":
        raise DazControlError(DazErrorCode.STATE_DATABASE_INVALID, "backup policy/tier mismatch")
    expected = {str(row["path"]): row for row in manifest["files"]}
    observed_files = {
        path.relative_to(root / "payload").as_posix(): path
        for path in (root / "payload").rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if set(expected) != set(observed_files):
        raise DazControlError(DazErrorCode.STATE_DATABASE_INVALID, "backup file set mismatch")
    for relative, row in expected.items():
        path = observed_files[relative]
        if path.stat().st_size != int(row["bytes"]) or _sha256(path) != str(row["sha256"]):
            raise DazControlError(
                DazErrorCode.STATE_DATABASE_INVALID,
                "backup payload hash mismatch",
                evidence_paths=(str(path),),
            )
    queue = observed_files.get("10_queue/queue.sqlite")
    integrity = _sqlite_integrity(queue) if queue is not None else None
    if integrity not in {None, "ok"}:
        raise DazControlError(DazErrorCode.STATE_DATABASE_INVALID, "backup queue DB is corrupt")
    return {
        "passed": True,
        "backup_id": manifest["backup_id"],
        "manifest_sha256": provided_seal,
        "file_count": len(expected),
        "total_bytes": sum(int(row["bytes"]) for row in expected.values()),
        "queue_integrity": integrity,
        "category_presence": manifest["category_presence"],
    }


def restore_tier_a_test(
    backup_root: Path,
    target_root: Path,
    policy: TierABackupPolicy,
) -> dict[str, Any]:
    """Restore to an empty root and verify manifest hashes and required categories."""
    backup = Path(backup_root).resolve(strict=True)
    target = Path(target_root).resolve()
    _require_outside(target, backup, "restore target")
    if target.exists() and any(target.iterdir()):
        raise DazControlError(DazErrorCode.SCHEDULER_REFUSED, "restore target is not empty")
    target.mkdir(parents=True, exist_ok=True)
    verification = verify_tier_a_backup(backup, policy)
    try:
        shutil.copytree(backup / "payload", target, dirs_exist_ok=True, symlinks=False)
        restored = {
            path.relative_to(target).as_posix(): path
            for path in target.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
        for row in manifest["files"]:
            path = restored[str(row["path"])]
            if _sha256(path) != str(row["sha256"]):
                raise DazControlError(
                    DazErrorCode.STATE_DATABASE_INVALID, "restored payload hash mismatch"
                )
        categories = _category_presence(restored, policy.required_categories)
        queue_integrity = _sqlite_integrity(restored.get("10_queue/queue.sqlite"))
        passed = all(categories.values()) and queue_integrity == "ok"
        return {
            "passed": passed,
            "backup_id": verification["backup_id"],
            "manifest_sha256": verification["manifest_sha256"],
            "restored_file_count": len(restored),
            "category_presence": categories,
            "queue_integrity": queue_integrity,
            "semantic_replay_executed": False,
            "lineage_query_executed": False,
        }
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise


def plan_tier_a_restore_test(
    backup_root: Path,
    target_root: Path,
    policy: TierABackupPolicy,
) -> dict[str, Any]:
    """Verify a backup and empty target without restoring any payload bytes."""
    backup = Path(backup_root).resolve(strict=True)
    target = Path(target_root).resolve()
    _require_outside(target, backup, "restore target")
    if target.exists() and any(target.iterdir()):
        raise DazControlError(DazErrorCode.SCHEDULER_REFUSED, "restore target is not empty")
    verification = verify_tier_a_backup(backup, policy)
    return {
        **verification,
        "apply": False,
        "backup_path": str(backup),
        "target_root": str(target),
        "target_exists": target.exists(),
    }


def _inventory(source: Path, include_roots: tuple[str, ...]) -> list[tuple[str, Path]]:
    rows: dict[str, Path] = {}
    for logical in include_roots:
        candidate = (source / Path(logical)).resolve()
        if not candidate.is_relative_to(source) or candidate.is_symlink():
            raise DazControlError(DazErrorCode.SCHEDULER_REFUSED, "unsafe backup source path")
        paths = (
            [candidate]
            if candidate.is_file()
            else candidate.rglob("*") if candidate.is_dir() else []
        )
        for path in paths:
            if path.is_symlink():
                raise DazControlError(
                    DazErrorCode.SCHEDULER_REFUSED, "backup source contains a link"
                )
            if path.is_file():
                rows[path.relative_to(source).as_posix()] = path
    return sorted(rows.items())


def _category_presence(
    paths: Any, required_categories: Mapping[str, tuple[str, ...]]
) -> dict[str, bool]:
    path_list = tuple(str(path) for path in paths)
    return {
        category: any(
            path == prefix or path.startswith(f"{prefix.rstrip('/')}/")
            for path in path_list
            for prefix in prefixes
        )
        for category, prefixes in required_categories.items()
    }


def _backup_sqlite(source: Path, target: Path) -> None:
    source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()
    if _sqlite_integrity(target) != "ok":
        raise DazControlError(DazErrorCode.STATE_DATABASE_INVALID, "SQLite backup failed integrity")


def _sqlite_integrity(path: Path | None) -> str | None:
    if path is None:
        return None
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()


def _require_outside(candidate: Path, protected: Path, label: str) -> None:
    if candidate == protected or candidate.is_relative_to(protected):
        raise DazControlError(DazErrorCode.SCHEDULER_REFUSED, f"{label} is inside protected root")


def _timestamp(value: datetime | None) -> str:
    captured = value or datetime.now(UTC)
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    return captured.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(document: Mapping[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = [
    "TierABackupPolicy",
    "create_tier_a_backup",
    "load_tier_a_backup_policy",
    "plan_tier_a_backup",
    "plan_tier_a_restore_test",
    "restore_tier_a_test",
    "verify_tier_a_backup",
]
