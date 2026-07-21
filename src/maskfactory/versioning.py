"""Immutable mask-version branching and QA-gated atomic promotion."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from .fusion.mapbuild import export_binaries, rebuild_map_from_binaries
from .io.hashing import sha256_file
from .io.png_strict import read_mask
from .qa.checks import run_qc001_010
from .review_package import refresh_review_package_derivations
from .state import transition_image_status, writer_connection


class VersioningError(RuntimeError):
    """A mask version operation would violate immutability or QA."""


DvcAdd = Callable[[Path], None]
VERSION_ASSETS = (
    "label_map_part.png",
    "label_map_material.png",
    "masks",
    "masks_material",
    "protected",
)


def begin_correction(package_root: Path, *, now: datetime | None = None) -> Path:
    """Copy frozen active map authority and its binary views into editable masks@vN."""
    package_root = Path(package_root)
    if not (package_root / ".maskfactory_frozen.json").is_file():
        raise VersioningError("corrections require a frozen approved package")
    manifest = _load_manifest(package_root)
    if manifest.get("workflow_status") not in {"approved_gold", "exported"}:
        raise VersioningError("corrections require approved_gold or exported package workflow")
    for relative in VERSION_ASSETS:
        if not (package_root / relative).exists():
            raise VersioningError(f"active version asset is missing: {relative}")

    registry = _load_registry(package_root)
    current = int(registry["active_version"])
    candidate_version = current + 1
    candidate = package_root / f"masks@v{candidate_version}"
    if candidate.exists():
        raise VersioningError(f"correction branch already exists: {candidate}")
    candidate.mkdir()
    try:
        for relative in VERSION_ASSETS:
            source = package_root / relative
            target = candidate / relative
            if source.is_dir():
                shutil.copytree(source, target, copy_function=shutil.copy2)
            else:
                shutil.copy2(source, target)
        timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        registry["versions"].setdefault(
            str(current), {"status": "human_approved_gold", "directory": "active"}
        )
        registry["versions"][str(candidate_version)] = {
            "status": "in_review",
            "directory": candidate.name,
            "created_at": timestamp,
            "files": _version_file_hashes(candidate),
        }
        _write_registry(package_root, registry)
        _refresh_file_inventory(package_root)
    except BaseException:
        shutil.rmtree(candidate, ignore_errors=True)
        raise
    return candidate


def refresh_correction_branch(package_root: Path, version: int) -> Path:
    """Regenerate a candidate's binary views from its edited authoritative maps."""
    package_root = Path(package_root)
    registry = _load_registry(package_root)
    current = int(registry["active_version"])
    if version != current + 1:
        raise VersioningError(f"editable correction version is v{current + 1}, got v{version}")
    candidate = package_root / f"masks@v{version}"
    if not candidate.is_dir():
        raise VersioningError(f"correction branch is missing: {candidate}")
    try:
        export_binaries(candidate)
        _validate_candidate(candidate)
    except (OSError, RuntimeError, ValueError) as exc:
        raise VersioningError(f"invalid correction branch: {exc}") from exc
    registry["versions"][str(version)]["files"] = _version_file_hashes(candidate)
    registry["versions"][str(version)]["updated_at"] = datetime.now(UTC).isoformat()
    _write_registry(package_root, registry)
    _refresh_file_inventory(package_root)
    return candidate


def promote_correction(
    package_root: Path,
    version: int,
    *,
    human_approved: bool,
    reviewer: str | None = None,
    review_minutes: float | None = None,
    database: Path | None = None,
    dvc_add: DvcAdd | None = None,
    now: datetime | None = None,
) -> None:
    """Promote a corrected map authority, fully reseal it, and roll back every side effect."""
    if not human_approved:
        raise VersioningError("explicit human approval is required for version promotion")
    if (reviewer is None) != (review_minutes is None):
        raise VersioningError("reviewer and review_minutes must be supplied together")
    if reviewer is not None and (not reviewer.strip() or float(review_minutes) < 0):
        raise VersioningError("reviewer is required and review_minutes must be non-negative")

    package_root = Path(package_root)
    registry = _load_registry(package_root)
    current = int(registry["active_version"])
    if version != current + 1:
        raise VersioningError(f"next promotable version is v{current + 1}, got v{version}")
    candidate = package_root / f"masks@v{version}"
    if not candidate.is_dir():
        raise VersioningError("candidate correction branch is missing")
    try:
        _validate_candidate(candidate)
    except (OSError, RuntimeError, ValueError) as exc:
        raise VersioningError(f"candidate correction branch is invalid: {exc}") from exc

    manifest = _load_manifest(package_root)
    image_id = str(manifest.get("image_id", ""))
    if database is not None and not image_id:
        raise VersioningError("database synchronization requires manifest image_id")
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    backup = _snapshot_directory(package_root)
    try:
        with _optional_writer(database) as connection:
            database_status = None
            if connection is not None:
                row = connection.execute(
                    "SELECT status FROM images WHERE image_id = ?", (image_id,)
                ).fetchone()
                if row is None:
                    raise VersioningError(f"correction image is missing from SQLite: {image_id}")
                database_status = str(row[0])
                if database_status not in {"approved_gold", "exported", "corrected"}:
                    raise VersioningError(
                        f"correction requires approved_gold/exported SQLite state, got {database_status}"
                    )

            archive = package_root / f"masks@v{current}"
            if archive.exists():
                raise VersioningError(f"previous-version archive already exists: {archive}")
            archive.mkdir()
            for relative in VERSION_ASSETS:
                os.replace(package_root / relative, archive / relative)
            for relative in VERSION_ASSETS:
                os.replace(candidate / relative, package_root / relative)
            candidate.rmdir()

            registry["active_version"] = version
            registry["versions"][str(current)].update(
                {
                    "status": "deprecated",
                    "directory": archive.name,
                    "deprecated_at": timestamp.isoformat(),
                    "retain_until": (timestamp + timedelta(days=30)).isoformat(),
                    "files": _version_file_hashes(archive),
                }
            )
            registry["versions"][str(version)].update(
                {
                    "status": "human_approved_gold",
                    "directory": "active",
                    "approved_at": timestamp.isoformat(),
                    "files": _active_version_file_hashes(package_root),
                }
            )
            _write_registry(package_root, registry)
            _stamp_corrected_gold_manifest(
                package_root,
                archive,
                reviewer=reviewer,
                review_minutes=review_minutes,
                timestamp=timestamp,
            )
            frozen = json.loads(
                (package_root / ".maskfactory_frozen.json").read_text(encoding="utf-8")
            )
            frozen.update({"active_mask_version": version, "frozen_at": timestamp.isoformat()})
            _write_json(package_root / ".maskfactory_frozen.json", frozen)
            refresh_review_package_derivations(package_root)
            results = run_qc001_010(package_root)
            failed = [result.qc_id for result in results if not result.passed]
            if failed:
                raise VersioningError("candidate blocked by " + ", ".join(failed))
            if dvc_add is not None:
                dvc_add(package_root)

            if connection is not None:
                if database_status in {"approved_gold", "exported"}:
                    transition_image_status(
                        connection,
                        image_id,
                        "corrected",
                        updated_at=timestamp.isoformat(),
                        current_stage="S12",
                    )
                transition_image_status(
                    connection,
                    image_id,
                    "approved_gold",
                    updated_at=timestamp.isoformat(),
                    current_stage="S13",
                )
    except BaseException:
        _restore_directory_snapshot(package_root, backup)
        raise
    shutil.rmtree(backup)


def _validate_candidate(candidate: Path) -> None:
    part = read_mask(candidate / "label_map_part.png").astype(np.uint16)
    material = read_mask(candidate / "label_map_material.png").astype(np.uint8)
    if part.shape != material.shape:
        raise VersioningError("candidate PART and MATERIAL maps differ in dimensions")
    rebuilt_part = rebuild_map_from_binaries(candidate, "part").astype(np.uint16)
    rebuilt_material = rebuild_map_from_binaries(candidate, "material").astype(np.uint8)
    if not np.array_equal(part, rebuilt_part):
        raise VersioningError("candidate PART binaries do not reproduce its authoritative map")
    if not np.array_equal(material, rebuilt_material):
        raise VersioningError("candidate MATERIAL binaries do not reproduce its authoritative map")


def _stamp_corrected_gold_manifest(
    package_root: Path,
    archive: Path,
    *,
    reviewer: str | None,
    review_minutes: float | None,
    timestamp: datetime,
) -> None:
    path = package_root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for entry in manifest.get("parts", {}).values():
        if not isinstance(entry, dict) or entry.get("status") == "n/a":
            continue
        entry["status"] = "human_approved_gold"
        mask_file = entry.get("mask_file")
        if (
            mask_file
            and (archive / str(mask_file)).is_file()
            and (package_root / str(mask_file)).is_file()
        ):
            changed = sha256_file(archive / str(mask_file)) != sha256_file(
                package_root / str(mask_file)
            )
            if changed:
                entry.setdefault("provenance", {})["human_edit"] = True
    manifest["workflow_status"] = "approved_gold"
    manifest["workflow_updated_at"] = timestamp.isoformat()
    if reviewer is not None:
        manifest.setdefault("review", {}).update(
            {
                "reviewer": reviewer,
                "approved_at": timestamp.isoformat(),
                "review_time_sec": round(float(review_minutes) * 60),
            }
        )
    _write_json(path, manifest)


def _load_manifest(package_root: Path) -> dict[str, Any]:
    path = package_root / "manifest.json"
    if not path.is_file():
        raise VersioningError("package manifest is missing")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise VersioningError("invalid package manifest")
    return document


def _load_registry(package_root: Path) -> dict[str, Any]:
    path = package_root / "mask_versions.json"
    if not path.is_file():
        return {
            "schema_version": "1.0.0",
            "active_version": 1,
            "versions": {"1": {"status": "human_approved_gold", "directory": "active"}},
        }
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("versions"), dict):
        raise VersioningError("invalid mask_versions.json")
    return document


def _refresh_file_inventory(package_root: Path) -> None:
    path = package_root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["files"] = {
        file.relative_to(package_root).as_posix(): sha256_file(file)
        for file in sorted(package_root.rglob("*"))
        if file.is_file()
        and file.name != "manifest.json"
        and not file.relative_to(package_root).parts[0].startswith("masks@v")
    }
    _write_json(path, manifest)


def _version_file_hashes(version_root: Path) -> dict[str, str]:
    return {
        file.relative_to(version_root).as_posix(): sha256_file(file)
        for file in sorted(version_root.rglob("*"))
        if file.is_file()
    }


def _active_version_file_hashes(package_root: Path) -> dict[str, str]:
    results: dict[str, str] = {}
    for relative in VERSION_ASSETS:
        path = package_root / relative
        if path.is_file():
            results[relative] = sha256_file(path)
        else:
            results.update(
                {
                    file.relative_to(package_root).as_posix(): sha256_file(file)
                    for file in sorted(path.rglob("*"))
                    if file.is_file()
                }
            )
    return results


def _snapshot_directory(package_root: Path) -> Path:
    backup = package_root.parent / f".{package_root.name}.correction-{uuid.uuid4().hex}"
    shutil.copytree(package_root, backup, copy_function=shutil.copy2)
    return backup


def _restore_directory_snapshot(package_root: Path, backup: Path) -> None:
    failed = package_root.parent / f".{package_root.name}.failed-{uuid.uuid4().hex}"
    os.replace(package_root, failed)
    try:
        os.replace(backup, package_root)
    except BaseException:
        os.replace(failed, package_root)
        raise
    shutil.rmtree(failed)


@contextmanager
def _optional_writer(database: Path | None) -> Iterator[Any | None]:
    if database is None:
        yield None
        return
    with writer_connection(Path(database)) as connection:
        yield connection


def _write_registry(package_root: Path, document: dict[str, Any]) -> None:
    _write_json(package_root / "mask_versions.json", document)


def _write_json(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
