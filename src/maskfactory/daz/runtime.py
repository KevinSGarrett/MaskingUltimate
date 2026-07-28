"""Closed named-instance profile and immutable DAZ Script deployment."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..validation import ArtifactValidationError, require_valid_document
from .policy import DazPolicyError, load_yaml


@dataclass(frozen=True)
class DazRuntimePaths:
    app_profile: Path
    bundle_versions: Path
    active_bundle: Path
    job_partial_root: Path
    job_result_root: Path
    worker_log_root: Path
    control_state: Path


@dataclass(frozen=True)
class DazRuntimeProfile:
    schema_version: str
    profile_id: str
    instance_name: str
    execution_mode: str
    process_lifetime: str
    bundle_version: str
    startup: Mapping[str, Any]
    content_directories: tuple[Path, ...]
    runtime_paths: DazRuntimePaths
    timeouts_seconds: Mapping[str, int]
    watchdog: Mapping[str, Any]
    safety: Mapping[str, Any]
    document: Mapping[str, Any]


def load_daz_runtime_profile(path: Path) -> DazRuntimeProfile:
    """Load the closed, default-disabled MaskFactoryDAZ runtime contract."""
    document = load_yaml(Path(path))
    try:
        require_valid_document(document, "daz_runtime")
    except ArtifactValidationError as exc:
        raise DazPolicyError(f"DAZ runtime schema validation failed: {exc}") from exc

    content_directories = tuple(Path(value) for value in document["content_directories"])
    runtime_raw = document["runtime_paths"]
    runtime_paths = DazRuntimePaths(
        app_profile=Path(runtime_raw["app_profile"]),
        bundle_versions=Path(runtime_raw["bundle_versions"]),
        active_bundle=Path(runtime_raw["active_bundle"]),
        job_partial_root=Path(runtime_raw["job_partial_root"]),
        job_result_root=Path(runtime_raw["job_result_root"]),
        worker_log_root=Path(runtime_raw["worker_log_root"]),
        control_state=Path(runtime_raw["control_state"]),
    )
    all_daz_paths = (*content_directories, *runtime_paths.__dict__.values())
    if any(not _is_within_daz_root(path) for path in all_daz_paths):
        raise DazPolicyError("DAZ runtime path escapes F:\\DAZ")
    return DazRuntimeProfile(
        schema_version=document["schema_version"],
        profile_id=document["profile_id"],
        instance_name=document["instance_name"],
        execution_mode=document["execution_mode"],
        process_lifetime=document["process_lifetime"],
        bundle_version=document["bundle_version"],
        startup=document["startup"],
        content_directories=content_directories,
        runtime_paths=runtime_paths,
        timeouts_seconds=document["timeouts_seconds"],
        watchdog=document["watchdog"],
        safety=document["safety"],
        document=document,
    )


def _is_within_daz_root(path: Path) -> bool:
    normalized = os.path.normcase(os.path.abspath(path))
    root = os.path.normcase(os.path.abspath(Path(r"F:\DAZ")))
    try:
        return os.path.commonpath((root, normalized)) == root
    except ValueError:
        return False


def script_bundle_manifest(source: Path, *, version: str) -> dict[str, Any]:
    source = Path(source)
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        relative = path.relative_to(source).as_posix()
        if relative == "bundle_manifest.json":
            continue
        files[relative] = {"sha256": _sha256(path), "bytes": path.stat().st_size}
    if not files or "worker_main.dsa" not in files:
        raise DazPolicyError("DAZ Script bundle must contain worker_main.dsa")
    return {"schema_version": "1.0.0", "bundle_version": version, "files": files}


def deploy_script_bundle(
    profile: DazRuntimeProfile,
    *,
    repository_root: Path,
    bundle_versions: Path | None = None,
    active_bundle: Path | None = None,
    app_profile: Path | None = None,
) -> dict[str, Any]:
    """Deploy one immutable version and update only an atomic active pointer.

    Existing version directories are accepted only when every byte still matches the
    repository manifest. Drift is never overwritten in place.
    """
    repository_root = Path(repository_root)
    source = repository_root / "integrations" / "daz" / "scripts" / profile.bundle_version
    if not source.is_dir():
        raise DazPolicyError(f"DAZ Script source bundle is missing: {source}")
    manifest = script_bundle_manifest(source, version=profile.bundle_version)
    versions_root = Path(bundle_versions or profile.runtime_paths.bundle_versions)
    active_root = Path(active_bundle or profile.runtime_paths.active_bundle)
    app_profile_root = Path(app_profile or profile.runtime_paths.app_profile)
    target = versions_root / profile.bundle_version
    deployed = False

    if target.exists():
        actual = script_bundle_manifest(target, version=profile.bundle_version)
        try:
            recorded = json.loads((target / "bundle_manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DazPolicyError(f"immutable DAZ Script manifest is unreadable: {target}") from exc
        if actual != manifest or recorded != manifest:
            raise DazPolicyError(f"immutable DAZ Script bundle drift detected: {target}")
    else:
        versions_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{profile.bundle_version}.", dir=versions_root))
        try:
            for relative in manifest["files"]:
                source_path = source / Path(relative)
                destination = staging / Path(relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_path, destination)
            _atomic_json(staging / "bundle_manifest.json", manifest)
            os.replace(staging, target)
            deployed = True
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    active_root.mkdir(parents=True, exist_ok=True)
    app_profile_root.mkdir(parents=True, exist_ok=True)
    pointer = {
        "schema_version": "1.0.0",
        "bundle_version": profile.bundle_version,
        "bundle_path": str(target),
        "manifest_sha256": _sha256(target / "bundle_manifest.json"),
    }
    profile_snapshot = {
        "schema_version": profile.schema_version,
        "profile_id": profile.profile_id,
        "instance_name": profile.instance_name,
        "execution_mode": profile.execution_mode,
        "process_lifetime": profile.process_lifetime,
        "startup": dict(profile.startup),
        "content_directories": [str(path) for path in profile.content_directories],
        "control_state": str(profile.runtime_paths.control_state),
        "minimum_render_free_gib": profile.safety["minimum_render_free_gib"],
        "safety": dict(profile.safety),
        "command_contract": [
            "-instanceName",
            profile.instance_name,
            "-noDefaultScene",
            "-noPrompt",
            "-logSize",
            str(profile.startup["log_size"]),
        ],
    }
    _atomic_json(active_root / "active_bundle.json", pointer)
    _atomic_json(app_profile_root / "profile.json", profile_snapshot)
    return {
        "schema_version": "1.0.0",
        "deployed": deployed,
        "target": str(target),
        "manifest": manifest,
        "active_pointer": str(active_root / "active_bundle.json"),
        "profile_snapshot": str(app_profile_root / "profile.json"),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
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
    "DazRuntimePaths",
    "DazRuntimeProfile",
    "deploy_script_bundle",
    "load_daz_runtime_profile",
    "script_bundle_manifest",
]
