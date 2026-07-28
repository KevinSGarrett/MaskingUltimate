"""Fail-closed repository packets for bounded autonomous engineering work.

The packet is deliberately text-only and authority-free.  It copies exact
bytes from a clean, tracked Git commit into an immutable evidence root.  A
separate staging operation may then materialize those bytes into a directory
that is not a Git worktree.  Neither operation runs a worker or applies a
patch.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = "maskfactory_repository_packet.v1"
STAGING_SCHEMA_VERSION = "maskfactory_patch_staging.v1"
MANIFEST_NAME = "packet_manifest.json"
STAGING_CONTRACT_NAME = "staging_contract.json"
DEFAULT_MAX_PACKET_BYTES = 512 * 1024
DEFAULT_ALLOCATION_FLOOR_BYTES = 50 * 1024**3
ZERO_SHA256 = "0" * 64
_AUTHORITY_CEILING = {
    "apply_patch": False,
    "git": False,
    "github": False,
    "credentials": False,
    "runpod": False,
    "final_acceptance": False,
}
_MANIFEST_FIELDS = {
    "schema_version",
    "source_commit",
    "scope_roots",
    "tracker_item_ids",
    "files",
    "payload_tree_sha256",
    "limits",
    "authority",
    "packet_sha256",
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT_ID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SECRET_PATH_RE = re.compile(
    r"(^|[._-])(secret|secrets|credential|credentials|password|passwd|"
    r"private[._-]?key|api[._-]?key|access[._-]?key)([._-]|$)",
    re.IGNORECASE,
)
_SECRET_CONTENT_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[opsu]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password)"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{16,}"
    ),
)


class RepositoryPacketError(RuntimeError):
    """Packet input or durable state is unsafe or contradictory."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_git(repo_root: Path, *arguments: str, text: bool = True) -> str | bytes:
    command = ["git", "-c", "core.autocrlf=false", *arguments]
    try:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=text,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            raw = exc.stderr
            if isinstance(raw, bytes):
                detail = raw.decode("utf-8", errors="replace").strip()
            elif isinstance(raw, str):
                detail = raw.strip()
        suffix = f": {detail}" if detail else ""
        raise RepositoryPacketError(f"Git inspection failed{suffix}") from exc
    return completed.stdout


def _validate_repository(repo_root: Path) -> Path:
    root = repo_root.resolve(strict=True)
    discovered = str(_run_git(root, "rev-parse", "--show-toplevel")).strip()
    if Path(discovered).resolve(strict=True) != root:
        raise RepositoryPacketError("repo_root must be the exact Git worktree root")
    return root


def _normalize_relative_path(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RepositoryPacketError(f"{field} must be a non-empty relative path")
    if any(character in value for character in "\r\n\x00"):
        raise RepositoryPacketError(f"{field} contains a prohibited character")
    candidate = value.replace("\\", "/")
    path = PurePosixPath(candidate)
    if (
        path.is_absolute()
        or ":" in path.parts[0]
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise RepositoryPacketError(f"{field} must not escape the repository")
    return path.as_posix()


def _validate_scope_roots(scope_roots: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(
        sorted(
            {_normalize_relative_path(root, field="scope root").rstrip("/") for root in scope_roots}
        )
    )
    if not normalized:
        raise RepositoryPacketError("at least one scope root is required")
    return normalized


def _path_in_scope(path: str, scope_roots: tuple[str, ...]) -> bool:
    return any(path == root or path.startswith(f"{root}/") for root in scope_roots)


def _secret_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return any(part.lower() == ".env" or _SECRET_PATH_RE.search(part) for part in parts)


def _decode_safe_text(data: bytes, *, path: str) -> str:
    if b"\x00" in data:
        raise RepositoryPacketError(f"{path}: binary files are not permitted")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RepositoryPacketError(f"{path}: source must be UTF-8 text") from exc
    for pattern in _SECRET_CONTENT_PATTERNS:
        if pattern.search(text):
            raise RepositoryPacketError(f"{path}: possible secret material detected")
    return text


def _tracked_file_bytes(repo_root: Path, relative_path: str) -> bytes:
    worktree_path = repo_root.joinpath(*PurePosixPath(relative_path).parts)
    resolved = worktree_path.resolve(strict=True)
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise RepositoryPacketError(
            f"{relative_path}: resolved path escapes the repository"
        ) from exc
    if worktree_path.is_symlink() or not worktree_path.is_file():
        raise RepositoryPacketError(f"{relative_path}: source must be a regular non-symlink file")

    try:
        tracked = str(
            _run_git(repo_root, "ls-files", "--error-unmatch", "--", relative_path)
        ).strip()
    except RepositoryPacketError as exc:
        raise RepositoryPacketError(f"{relative_path}: source is not tracked") from exc
    if tracked != relative_path:
        raise RepositoryPacketError(f"{relative_path}: source is not tracked")
    status = str(
        _run_git(
            repo_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            relative_path,
        )
    ).strip()
    if status:
        raise RepositoryPacketError(
            f"{relative_path}: selected source has uncommitted or untracked work"
        )

    committed = bytes(_run_git(repo_root, "show", f"HEAD:{relative_path}", text=False))
    current = worktree_path.read_bytes()
    if current != committed:
        raise RepositoryPacketError(
            f"{relative_path}: worktree bytes differ from the committed Git blob"
        )
    _decode_safe_text(committed, path=relative_path)
    return committed


def _validate_identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RepositoryPacketError(f"{field} must be non-empty")
    normalized = value.strip()
    if len(normalized) > 160 or any(character in "\r\n\x00" for character in normalized):
        raise RepositoryPacketError(f"{field} is invalid")
    return normalized


def _payload_tree_sha256(rows: Iterable[Mapping[str, Any]]) -> str:
    lines = [
        f"{row['sha256']}  {row['bytes']}  {row['path']}\n"
        for row in sorted(rows, key=lambda item: str(item["path"]))
    ]
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def _seal_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    sealed = dict(manifest)
    sealed["packet_sha256"] = ZERO_SHA256
    sealed["packet_sha256"] = _canonical_sha256(sealed)
    return sealed


def _verify_manifest_self_hash(manifest: Mapping[str, Any]) -> None:
    declared = manifest.get("packet_sha256")
    if not isinstance(declared, str) or not _SHA256_RE.fullmatch(declared):
        raise RepositoryPacketError("packet manifest SHA-256 is invalid")
    zeroed = dict(manifest)
    zeroed["packet_sha256"] = ZERO_SHA256
    if _canonical_sha256(zeroed) != declared:
        raise RepositoryPacketError("packet manifest canonical self-hash mismatch")


def _require_allocation(
    *,
    parent: Path,
    expected_bytes: int,
    minimum_free_bytes: int,
    disk_usage: Callable[[Path], Any],
) -> None:
    if (
        not isinstance(minimum_free_bytes, int)
        or isinstance(minimum_free_bytes, bool)
        or minimum_free_bytes < 0
    ):
        raise RepositoryPacketError("minimum_free_bytes must be non-negative")
    free = disk_usage(parent).free
    if free - expected_bytes < minimum_free_bytes:
        raise RepositoryPacketError("packet allocation would violate the local free-space floor")


def _require_external_destination(destination: Path, repo_root: Path) -> None:
    try:
        destination.relative_to(repo_root)
    except ValueError:
        return
    raise RepositoryPacketError("packet and staging roots must be outside the repository")


def build_repository_packet(
    *,
    repo_root: Path,
    packet_root: Path,
    source_paths: Iterable[str],
    scope_roots: Iterable[str],
    tracker_item_ids: Iterable[str],
    max_packet_bytes: int = DEFAULT_MAX_PACKET_BYTES,
    minimum_free_bytes: int = DEFAULT_ALLOCATION_FLOOR_BYTES,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
) -> dict[str, Any]:
    """Create one atomic, commit-bound, authority-free repository packet."""

    if (
        not isinstance(max_packet_bytes, int)
        or isinstance(max_packet_bytes, bool)
        or max_packet_bytes <= 0
    ):
        raise RepositoryPacketError("max_packet_bytes must be positive")
    root = _validate_repository(repo_root)
    destination = packet_root.resolve(strict=False)
    _require_external_destination(destination, root)
    if destination.exists():
        raise RepositoryPacketError("packet destination already exists")
    if not destination.parent.is_dir():
        raise RepositoryPacketError("packet destination parent must already exist")

    scopes = _validate_scope_roots(scope_roots)
    supplied_paths = tuple(
        _normalize_relative_path(path, field="source path") for path in source_paths
    )
    paths = tuple(sorted(set(supplied_paths)))
    if not paths:
        raise RepositoryPacketError("at least one source path is required")
    if len(paths) != len(supplied_paths):
        raise RepositoryPacketError("source paths must be unique")
    supplied_tracker_ids = tuple(
        _validate_identifier(item, field="tracker item ID") for item in tracker_item_ids
    )
    tracker_ids = tuple(sorted(set(supplied_tracker_ids)))
    if not tracker_ids:
        raise RepositoryPacketError("at least one tracker item ID is required")
    if len(tracker_ids) != len(supplied_tracker_ids):
        raise RepositoryPacketError("tracker item IDs must be unique")

    source_rows: list[dict[str, Any]] = []
    source_bytes: dict[str, bytes] = {}
    total_bytes = 0
    for relative_path in paths:
        if not _path_in_scope(relative_path, scopes):
            raise RepositoryPacketError(f"{relative_path}: source is outside the declared scope")
        if _secret_path(relative_path):
            raise RepositoryPacketError(f"{relative_path}: secret-like paths are not permitted")
        data = _tracked_file_bytes(root, relative_path)
        total_bytes += len(data)
        if total_bytes > max_packet_bytes:
            raise RepositoryPacketError("repository packet exceeds its byte cap")
        digest = hashlib.sha256(data).hexdigest()
        source_rows.append({"path": relative_path, "bytes": len(data), "sha256": digest})
        source_bytes[relative_path] = data

    head = str(_run_git(root, "rev-parse", "HEAD")).strip()
    if not _GIT_OBJECT_ID_RE.fullmatch(head):
        raise RepositoryPacketError("source commit is not a full Git object ID")
    manifest = _seal_manifest(
        {
            "schema_version": SCHEMA_VERSION,
            "source_commit": head,
            "scope_roots": list(scopes),
            "tracker_item_ids": list(tracker_ids),
            "files": source_rows,
            "payload_tree_sha256": _payload_tree_sha256(source_rows),
            "limits": {
                "max_packet_bytes": max_packet_bytes,
                "actual_source_bytes": total_bytes,
            },
            "authority": dict(_AUTHORITY_CEILING),
            "packet_sha256": ZERO_SHA256,
        }
    )
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    )
    expected_allocation = total_bytes + len(manifest_bytes)
    if expected_allocation > max_packet_bytes:
        raise RepositoryPacketError("repository packet exceeds its byte cap")
    _require_allocation(
        parent=destination.parent,
        expected_bytes=expected_allocation,
        minimum_free_bytes=minimum_free_bytes,
        disk_usage=disk_usage,
    )

    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
    try:
        files_root = temporary / "files"
        for relative_path, data in source_bytes.items():
            output = files_root.joinpath(*PurePosixPath(relative_path).parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
        (temporary / MANIFEST_NAME).write_bytes(manifest_bytes)
        verify_repository_packet(temporary, repo_root=root, require_current_source=True)
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return manifest


def verify_repository_packet(
    packet_root: Path,
    *,
    repo_root: Path | None = None,
    require_current_source: bool = False,
) -> dict[str, Any]:
    """Verify packet bytes and optionally reject stale repository state."""

    root = packet_root.resolve(strict=True)
    manifest_path = root / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RepositoryPacketError("packet manifest is unreadable") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise RepositoryPacketError("packet manifest schema mismatch")
    if set(manifest) != _MANIFEST_FIELDS:
        raise RepositoryPacketError("packet manifest field set mismatch")
    _verify_manifest_self_hash(manifest)
    if manifest.get("authority") != _AUTHORITY_CEILING:
        raise RepositoryPacketError("packet authority exceeds the fixed ceiling")
    source_commit = manifest.get("source_commit")
    if not isinstance(source_commit, str) or not _GIT_OBJECT_ID_RE.fullmatch(source_commit):
        raise RepositoryPacketError("packet source commit is invalid")
    if not isinstance(manifest.get("scope_roots"), list):
        raise RepositoryPacketError("packet scope roots are invalid")
    scopes = _validate_scope_roots(manifest["scope_roots"])
    if list(scopes) != manifest["scope_roots"]:
        raise RepositoryPacketError("packet scope roots must be sorted and unique")
    tracker_ids = manifest.get("tracker_item_ids")
    if (
        not isinstance(tracker_ids, list)
        or not tracker_ids
        or tracker_ids
        != sorted({_validate_identifier(item, field="tracker item ID") for item in tracker_ids})
    ):
        raise RepositoryPacketError("packet tracker item IDs are invalid")
    limits = manifest.get("limits")
    if not isinstance(limits, dict) or set(limits) != {
        "max_packet_bytes",
        "actual_source_bytes",
    }:
        raise RepositoryPacketError("packet limits are invalid")
    if (
        not isinstance(limits["max_packet_bytes"], int)
        or isinstance(limits["max_packet_bytes"], bool)
        or limits["max_packet_bytes"] <= 0
        or not isinstance(limits["actual_source_bytes"], int)
        or isinstance(limits["actual_source_bytes"], bool)
        or limits["actual_source_bytes"] < 0
        or limits["actual_source_bytes"] > limits["max_packet_bytes"]
    ):
        raise RepositoryPacketError("packet byte limits are contradictory")

    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise RepositoryPacketError("packet manifest files must be a non-empty list")
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for row in files:
        if not isinstance(row, dict):
            raise RepositoryPacketError("packet file row must be an object")
        if set(row) != {"path", "bytes", "sha256"}:
            raise RepositoryPacketError("packet file row field set mismatch")
        relative_path = _normalize_relative_path(row.get("path"), field="packet path")
        if relative_path in seen:
            raise RepositoryPacketError("packet paths must be unique")
        seen.add(relative_path)
        if not _path_in_scope(relative_path, scopes):
            raise RepositoryPacketError(
                f"{relative_path}: packet path is outside the declared scope"
            )
        if _secret_path(relative_path):
            raise RepositoryPacketError(
                f"{relative_path}: secret-like packet paths are not permitted"
            )
        if not isinstance(row.get("bytes"), int) or row["bytes"] < 0:
            raise RepositoryPacketError(f"{relative_path}: invalid byte count")
        if not isinstance(row.get("sha256"), str) or not _SHA256_RE.fullmatch(row["sha256"]):
            raise RepositoryPacketError(f"{relative_path}: invalid SHA-256")
        source = root / "files" / Path(*PurePosixPath(relative_path).parts)
        resolved = source.resolve(strict=True)
        try:
            resolved.relative_to(root / "files")
        except ValueError as exc:
            raise RepositoryPacketError("packet source escaped its files root") from exc
        if source.is_symlink() or not source.is_file():
            raise RepositoryPacketError(f"{relative_path}: packet source is not a regular file")
        if source.stat().st_size != row["bytes"] or _file_sha256(source) != row["sha256"]:
            raise RepositoryPacketError(f"{relative_path}: packet source hash mismatch")
        _decode_safe_text(source.read_bytes(), path=relative_path)
        rows.append(
            {
                "path": relative_path,
                "bytes": row["bytes"],
                "sha256": row["sha256"],
            }
        )
    if _payload_tree_sha256(rows) != manifest.get("payload_tree_sha256"):
        raise RepositoryPacketError("packet payload tree hash mismatch")
    if sum(row["bytes"] for row in rows) != limits["actual_source_bytes"]:
        raise RepositoryPacketError("packet actual source byte count mismatch")
    if (
        sum(row["bytes"] for row in rows) + manifest_path.stat().st_size
        > limits["max_packet_bytes"]
    ):
        raise RepositoryPacketError("packet exceeds its declared byte cap")

    expected_paths = {
        MANIFEST_NAME,
        *(f"files/{row['path']}" for row in rows),
    }
    actual_paths = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual_paths != expected_paths:
        raise RepositoryPacketError("packet contains an unexpected path set")

    if require_current_source:
        if repo_root is None:
            raise RepositoryPacketError("repo_root is required for stale-source checks")
        repository = _validate_repository(repo_root)
        current_head = str(_run_git(repository, "rev-parse", "HEAD")).strip()
        if current_head != manifest.get("source_commit"):
            raise RepositoryPacketError("repository packet source commit is stale")
        for row in rows:
            current = _tracked_file_bytes(repository, row["path"])
            if len(current) != row["bytes"] or hashlib.sha256(current).hexdigest() != row["sha256"]:
                raise RepositoryPacketError(
                    f"{row['path']}: repository packet source bytes are stale"
                )
    return manifest


def create_patch_staging_area(
    *,
    packet_root: Path,
    staging_root: Path,
    repo_root: Path,
    minimum_free_bytes: int = DEFAULT_ALLOCATION_FLOOR_BYTES,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
) -> dict[str, Any]:
    """Materialize verified packet sources into a non-Git patch staging area."""

    manifest = verify_repository_packet(
        packet_root,
        repo_root=repo_root,
        require_current_source=True,
    )
    destination = staging_root.resolve(strict=False)
    repository = _validate_repository(repo_root)
    _require_external_destination(destination, repository)
    if destination.exists():
        raise RepositoryPacketError("staging destination already exists")
    if not destination.parent.is_dir():
        raise RepositoryPacketError("staging destination parent must already exist")
    staging_contract = {
        "schema_version": STAGING_SCHEMA_VERSION,
        "packet_sha256": manifest["packet_sha256"],
        "source_commit": manifest["source_commit"],
        "tracker_item_ids": manifest["tracker_item_ids"],
        "editable_files": manifest["files"],
        "authority": manifest["authority"],
        "staging_sha256": ZERO_SHA256,
    }
    staging_contract["staging_sha256"] = _canonical_sha256(staging_contract)
    contract_bytes = (
        json.dumps(staging_contract, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
        + b"\n"
    )
    expected_bytes = sum(row["bytes"] for row in manifest["files"]) + len(contract_bytes)
    _require_allocation(
        parent=destination.parent,
        expected_bytes=expected_bytes,
        minimum_free_bytes=minimum_free_bytes,
        disk_usage=disk_usage,
    )

    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
    try:
        for row in manifest["files"]:
            relative = PurePosixPath(row["path"])
            source = packet_root / "files" / Path(*relative.parts)
            output = temporary / "sources" / Path(*relative.parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(source.read_bytes())
            if output.stat().st_size != row["bytes"] or _file_sha256(output) != row["sha256"]:
                raise RepositoryPacketError(f"{row['path']}: staging source hash mismatch")
        (temporary / STAGING_CONTRACT_NAME).write_bytes(contract_bytes)
        if (temporary / ".git").exists():
            raise RepositoryPacketError("staging area must not contain Git metadata")
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return staging_contract


__all__ = [
    "DEFAULT_ALLOCATION_FLOOR_BYTES",
    "DEFAULT_MAX_PACKET_BYTES",
    "MANIFEST_NAME",
    "RepositoryPacketError",
    "SCHEMA_VERSION",
    "STAGING_CONTRACT_NAME",
    "STAGING_SCHEMA_VERSION",
    "build_repository_packet",
    "create_patch_staging_area",
    "verify_repository_packet",
]
