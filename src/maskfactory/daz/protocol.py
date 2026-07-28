"""Atomic, job-private DAZ recipe/result protocol."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..validation import ArtifactValidationError, require_valid_document
from .policy import DazPolicyError


@dataclass(frozen=True)
class DazJobFiles:
    job_directory: Path
    recipe: Path
    partial_result: Path
    terminal_result: Path
    worker_log: Path
    watchdog_evidence: Path


def prepare_job_files(root: Path, job_id: str) -> DazJobFiles:
    if not _safe_identifier(job_id):
        raise DazPolicyError(f"unsafe DAZ job identifier: {job_id!r}")
    root = Path(root).resolve()
    job_directory = (root / job_id).resolve()
    if job_directory.parent != root:
        raise DazPolicyError("DAZ job directory escaped its private root")
    job_directory.mkdir(parents=True, exist_ok=True)
    return DazJobFiles(
        job_directory=job_directory,
        recipe=job_directory / "recipe.json",
        partial_result=job_directory / "worker_result.json.partial",
        terminal_result=job_directory / "worker_result.json",
        worker_log=job_directory / "worker.log",
        watchdog_evidence=job_directory / "watchdog.json",
    )


def stage_recipe(files: DazJobFiles, recipe: Mapping[str, Any]) -> Path:
    """Validate and atomically publish a recipe exactly once."""
    try:
        require_valid_document(recipe, "daz_scene_recipe")
    except ArtifactValidationError as exc:
        raise DazPolicyError(f"DAZ recipe schema validation failed: {exc}") from exc
    if recipe["job_id"] != files.job_directory.name:
        raise DazPolicyError("DAZ recipe job_id does not match its private directory")
    if files.recipe.exists():
        existing = json.loads(files.recipe.read_text(encoding="utf-8"))
        if existing != dict(recipe):
            raise DazPolicyError("published DAZ recipe is immutable")
        return files.recipe
    _atomic_json(files.recipe, recipe)
    return files.recipe


def read_terminal_result(
    files: DazJobFiles,
    recipe: Mapping[str, Any],
    *,
    allowed_artifact_roots: tuple[Path, ...],
) -> dict[str, Any] | None:
    """Accept only a final, schema-valid, identity-bound and hash-valid result."""
    if not files.terminal_result.is_file():
        return None
    try:
        result = json.loads(files.terminal_result.read_text(encoding="utf-8"))
        require_valid_document(result, "daz_worker_result")
    except (OSError, json.JSONDecodeError, ArtifactValidationError) as exc:
        raise DazPolicyError(f"DAZ terminal result is invalid: {exc}") from exc
    for field in ("job_id", "recipe_id", "bundle_version"):
        if result[field] != recipe[field]:
            raise DazPolicyError(f"DAZ terminal result identity mismatch: {field}")
    if tuple(_normalize_path(value) for value in result["runtime"]["content_directories"]) != tuple(
        _normalize_path(value) for value in recipe["content_directories"]
    ):
        raise DazPolicyError("DAZ terminal result content-directory mismatch")
    if (
        result["status"] == "success"
        and recipe["operation"] != "runtime_probe"
        and not result["artifacts"]
    ):
        raise DazPolicyError("successful DAZ render result contains no artifacts")

    roots = tuple(Path(root).resolve() for root in allowed_artifact_roots)
    for artifact in result["artifacts"]:
        path = Path(artifact["path"]).resolve()
        if not path.is_file() or not any(_is_relative_to(path, root) for root in roots):
            raise DazPolicyError(f"DAZ result artifact is missing or outside authority: {path}")
        if path.stat().st_size != artifact["bytes"] or _sha256(path) != artifact["sha256"]:
            raise DazPolicyError(f"DAZ result artifact hash/size mismatch: {path}")
    return result


def write_watchdog_evidence(path: Path, document: Mapping[str, Any]) -> None:
    _atomic_json(Path(path), document)


def _safe_identifier(value: str) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and value[0].isalnum()
        and all(character.isalnum() or character in "_.-" for character in value)
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _normalize_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "DazJobFiles",
    "prepare_job_files",
    "read_terminal_result",
    "stage_recipe",
    "write_watchdog_evidence",
]
