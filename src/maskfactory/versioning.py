"""Immutable mask-version branching and QA-gated atomic promotion."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .qa.checks import run_qc001_010


class VersioningError(RuntimeError):
    """A mask version operation would violate immutability or QA."""


def begin_correction(package_root: Path, *, now: datetime | None = None) -> Path:
    """Copy frozen active masks into the next editable masks@vN branch."""
    package_root = Path(package_root)
    if not (package_root / ".maskfactory_frozen.json").is_file():
        raise VersioningError("corrections require a frozen approved package")
    active = package_root / "masks"
    if not active.is_dir():
        raise VersioningError("active masks directory is missing")
    registry = _load_registry(package_root)
    current = int(registry["active_version"])
    candidate_version = current + 1
    candidate = package_root / f"masks@v{candidate_version}"
    if candidate.exists():
        raise VersioningError(f"correction branch already exists: {candidate}")
    shutil.copytree(active, candidate)
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    registry["versions"].setdefault(
        str(current), {"status": "human_approved_gold", "directory": "masks"}
    )
    registry["versions"][str(candidate_version)] = {
        "status": "in_review",
        "directory": candidate.name,
        "created_at": timestamp,
    }
    _write_registry(package_root, registry)
    return candidate


def promote_correction(
    package_root: Path,
    version: int,
    *,
    human_approved: bool,
    now: datetime | None = None,
) -> None:
    """Atomically swap a candidate active, QA it, and roll back on any BLOCK."""
    if not human_approved:
        raise VersioningError("explicit human approval is required for version promotion")
    package_root = Path(package_root)
    registry = _load_registry(package_root)
    current = int(registry["active_version"])
    if version != current + 1:
        raise VersioningError(f"next promotable version is v{current + 1}, got v{version}")
    candidate = package_root / f"masks@v{version}"
    active = package_root / "masks"
    if not candidate.is_dir() or not active.is_dir():
        raise VersioningError("active or candidate masks directory is missing")
    old_temporary = package_root / f".masks.v{current}.tmp-{uuid.uuid4().hex}"
    os.replace(active, old_temporary)
    try:
        os.replace(candidate, active)
        results = run_qc001_010(package_root)
        changed_mask_gates = {"QC-001", "QC-002", "QC-003", "QC-004", "QC-007"}
        failed = [
            result.qc_id
            for result in results
            if result.qc_id in changed_mask_gates and not result.passed
        ]
        if failed:
            raise VersioningError("candidate blocked by " + ", ".join(failed))
    except Exception:
        if active.exists():
            os.replace(active, candidate)
        os.replace(old_temporary, active)
        raise
    archive = package_root / f"masks@v{current}"
    if archive.exists():
        shutil.rmtree(old_temporary)
    else:
        os.replace(old_temporary, archive)
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    registry["active_version"] = version
    registry["versions"][str(current)].update(
        {
            "status": "deprecated",
            "directory": archive.name,
            "deprecated_at": timestamp.isoformat(),
            "retain_until": (timestamp + timedelta(days=30)).isoformat(),
        }
    )
    registry["versions"][str(version)].update(
        {
            "status": "human_approved_gold",
            "directory": "masks",
            "approved_at": timestamp.isoformat(),
        }
    )
    _write_registry(package_root, registry)


def _load_registry(package_root: Path) -> dict[str, Any]:
    path = package_root / "mask_versions.json"
    if not path.is_file():
        return {
            "schema_version": "1.0.0",
            "active_version": 1,
            "versions": {"1": {"status": "human_approved_gold", "directory": "masks"}},
        }
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("versions"), dict):
        raise VersioningError("invalid mask_versions.json")
    return document


def _write_registry(package_root: Path, document: dict[str, Any]) -> None:
    path = package_root / "mask_versions.json"
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
