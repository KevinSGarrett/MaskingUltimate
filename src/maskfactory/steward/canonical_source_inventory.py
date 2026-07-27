"""Deterministic Git-object inventory for canonical product/autonomy convergence."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "maskfactory.canonical_source_inventory.v1"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
DEFAULT_PREFIXES = ("src/", "tests/", "tools/", "configs/")
DEFAULT_ROOT_FILES = ("pyproject.toml", "setup.py", "setup.cfg")
CLASSIFICATIONS = {
    "autonomy_only",
    "divergent_conflict",
    "full_product_only",
    "identical",
    "worktree_only_untracked",
}
OPEN_CONTROLLER_GUARDS = (
    "CROSS_CONTROLLER_INTEGRATION_OPEN",
    "MISSION_SIZE_GATE_OPEN",
    "SERVERLESS_SUCCESSOR_GUARD_OPEN",
    "CANONICAL_CALLER_PATH_GATE_OPEN",
)


class CanonicalSourceInventoryError(RuntimeError):
    """The requested inventory cannot be reproduced safely."""


def _run_git(repo_root: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise CanonicalSourceInventoryError("Git executable is unavailable") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise CanonicalSourceInventoryError(
            f"Git command failed: {' '.join(arguments)}: {detail[-1000:]}"
        )
    return completed.stdout


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def seal_inventory(value: Mapping[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(dict(value))
    sealed["self_sha256"] = "0" * 64
    sealed["self_sha256"] = canonical_sha256(sealed)
    return sealed


def validate_inventory(value: Mapping[str, Any]) -> None:
    if value.get("schema_version") != SCHEMA_VERSION:
        raise CanonicalSourceInventoryError("inventory schema is unsupported")
    expected = value.get("self_sha256")
    zeroed = copy.deepcopy(dict(value))
    zeroed["self_sha256"] = "0" * 64
    if not isinstance(expected, str) or canonical_sha256(zeroed) != expected:
        raise CanonicalSourceInventoryError("inventory self hash mismatch")
    paths = value.get("paths")
    if not isinstance(paths, list) or not paths:
        raise CanonicalSourceInventoryError("inventory path set is empty")
    names = [row.get("path") for row in paths if isinstance(row, dict)]
    if (
        len(names) != len(paths)
        or any(not isinstance(name, str) or not name for name in names)
        or names != sorted(names)
        or len(set(names)) != len(names)
    ):
        raise CanonicalSourceInventoryError(
            "inventory paths must be sorted, unique, non-empty strings"
        )
    summary = value.get("summary")
    if not isinstance(summary, dict):
        raise CanonicalSourceInventoryError("inventory summary is absent")
    if any(
        row.get("classification") not in CLASSIFICATIONS
        or not isinstance(row.get("integration_status"), str)
        or not isinstance(row.get("unresolved_conflict"), bool)
        for row in paths
    ):
        raise CanonicalSourceInventoryError("inventory path classification is invalid")
    classifications = Counter(str(row["classification"]) for row in paths)
    if summary.get("classification_counts") != dict(sorted(classifications.items())):
        raise CanonicalSourceInventoryError("inventory classification summary drift")
    integration = Counter(str(row["integration_status"]) for row in paths)
    if summary.get("integration_status_counts") != dict(sorted(integration.items())):
        raise CanonicalSourceInventoryError("inventory integration summary drift")
    unresolved = sum(bool(row["unresolved_conflict"]) for row in paths)
    if summary.get("unresolved_conflict_count") != unresolved:
        raise CanonicalSourceInventoryError("inventory unresolved summary drift")
    if summary.get("union_path_count") != len(paths):
        raise CanonicalSourceInventoryError("inventory union count drift")
    full_count = sum(row.get("full_product") is not None for row in paths)
    autonomy_count = sum(row.get("autonomy") is not None for row in paths)
    if summary.get("full_product_path_count") != full_count:
        raise CanonicalSourceInventoryError("full-product path count drift")
    if summary.get("autonomy_path_count") != autonomy_count:
        raise CanonicalSourceInventoryError("autonomy path count drift")
    authority = value.get("item24_verify_binding", {}).get("authority_sha256")
    if (
        not isinstance(authority, dict)
        or not authority
        or any(
            not isinstance(name, str)
            or not name
            or not isinstance(digest, str)
            or not SHA256_RE.fullmatch(digest)
            for name, digest in authority.items()
        )
    ):
        raise CanonicalSourceInventoryError("inventory authority binding is invalid")
    safety = value.get("safety", {})
    if safety.get("wholesale_merge_authorized") is not False:
        raise CanonicalSourceInventoryError("inventory cannot authorize wholesale merge")
    if safety.get("reset_authorized") is not False:
        raise CanonicalSourceInventoryError("inventory cannot authorize reset")
    if safety.get("replacement_worktree_authorized") is not False:
        raise CanonicalSourceInventoryError(
            "inventory cannot authorize replacement worktree"
        )
    if safety.get("completion_credit_claimed") is not False:
        raise CanonicalSourceInventoryError("inventory cannot claim completion credit")
    if safety.get("open_controller_integration_guards") != list(
        OPEN_CONTROLLER_GUARDS
    ):
        raise CanonicalSourceInventoryError("inventory open guard binding drift")


def _resolve_commit(repo_root: Path, ref: str) -> tuple[str, str]:
    commit = _run_git(repo_root, "rev-parse", "--verify", f"{ref}^{{commit}}")
    commit_sha = commit.decode("ascii").strip()
    tree = _run_git(repo_root, "show", "-s", "--format=%T", commit_sha)
    tree_sha = tree.decode("ascii").strip()
    if not re.fullmatch(r"[a-f0-9]{40}", commit_sha) or not re.fullmatch(
        r"[a-f0-9]{40}", tree_sha
    ):
        raise CanonicalSourceInventoryError("resolved Git identity is invalid")
    return commit_sha, tree_sha


def _in_scope(
    path: str,
    *,
    prefixes: Sequence[str],
    root_files: Sequence[str],
) -> bool:
    return path in root_files or any(path.startswith(prefix) for prefix in prefixes)


def _tree_entries(
    repo_root: Path,
    commit_sha: str,
    *,
    prefixes: Sequence[str],
    root_files: Sequence[str],
) -> dict[str, dict[str, str]]:
    output = _run_git(repo_root, "ls-tree", "-r", "-z", commit_sha)
    entries: dict[str, dict[str, str]] = {}
    for record in output.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if not _in_scope(path, prefixes=prefixes, root_files=root_files):
            continue
        entries[path] = {
            "mode": mode,
            "object_type": object_type,
            "git_object_id": object_id,
        }
    return entries


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _worktree_entry(
    repo_root: Path,
    relative: str,
    *,
    full_entry: Mapping[str, str] | None,
    autonomy_entry: Mapping[str, str] | None,
) -> dict[str, Any]:
    absolute = repo_root / Path(relative)
    tracked = autonomy_entry is not None
    if not absolute.is_file():
        return {
            "state": "absent",
            "tracked_by_autonomy": tracked,
            "sha256": None,
            "bytes": None,
            "git_object_id": None,
            "matches_full_product": False,
            "matches_autonomy": False,
        }
    sha256, size = _file_sha256(absolute)
    object_id = _run_git(repo_root, "hash-object", "--", relative).decode("ascii").strip()
    matches_full = bool(full_entry and object_id == full_entry["git_object_id"])
    matches_autonomy = bool(autonomy_entry and object_id == autonomy_entry["git_object_id"])
    if tracked and matches_autonomy:
        state = "tracked_clean"
    elif tracked:
        state = "tracked_modified_preserve"
    elif matches_full:
        state = "untracked_full_product_exact_preserve"
    else:
        state = "untracked_user_or_generated_preserve"
    return {
        "state": state,
        "tracked_by_autonomy": tracked,
        "sha256": sha256,
        "bytes": size,
        "git_object_id": object_id,
        "matches_full_product": matches_full,
        "matches_autonomy": matches_autonomy,
    }


def _worktree_scope_paths(
    repo_root: Path,
    *,
    prefixes: Sequence[str],
    root_files: Sequence[str],
) -> set[str]:
    output = _run_git(
        repo_root,
        "ls-files",
        "-c",
        "-o",
        "--exclude-standard",
        "-z",
    )
    return {
        raw.decode("utf-8", errors="surrogateescape")
        for raw in output.split(b"\0")
        if raw
        and _in_scope(
            raw.decode("utf-8", errors="surrogateescape"),
            prefixes=prefixes,
            root_files=root_files,
        )
    }


def _classify(
    full_entry: Mapping[str, str] | None,
    autonomy_entry: Mapping[str, str] | None,
) -> str:
    if full_entry is None and autonomy_entry is None:
        return "worktree_only_untracked"
    if full_entry is None:
        return "autonomy_only"
    if autonomy_entry is None:
        return "full_product_only"
    if (
        full_entry["mode"] == autonomy_entry["mode"]
        and full_entry["git_object_id"] == autonomy_entry["git_object_id"]
    ):
        return "identical"
    return "divergent_conflict"


def build_inventory(
    *,
    repo_root: Path,
    full_product_ref: str,
    autonomy_ref: str,
    authority_hashes: Mapping[str, str],
    prefixes: Sequence[str] = DEFAULT_PREFIXES,
    root_files: Sequence[str] = DEFAULT_ROOT_FILES,
) -> dict[str, Any]:
    """Build a complete, sorted path classification without changing Git state."""
    root = Path(repo_root).resolve()
    git_root = Path(
        _run_git(root, "rev-parse", "--show-toplevel")
        .decode("utf-8", errors="strict")
        .strip()
    ).resolve()
    if git_root != root:
        raise CanonicalSourceInventoryError("repo_root is not the Git worktree root")
    for name, digest in authority_hashes.items():
        if not name or not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise CanonicalSourceInventoryError("authority hash binding is invalid")
    full_commit, full_tree = _resolve_commit(root, full_product_ref)
    autonomy_commit, autonomy_tree = _resolve_commit(root, autonomy_ref)
    full = _tree_entries(
        root,
        full_commit,
        prefixes=prefixes,
        root_files=root_files,
    )
    autonomy = _tree_entries(
        root,
        autonomy_commit,
        prefixes=prefixes,
        root_files=root_files,
    )
    worktree_paths = _worktree_scope_paths(
        root,
        prefixes=prefixes,
        root_files=root_files,
    )
    rows: list[dict[str, Any]] = []
    for relative in sorted(set(full) | set(autonomy) | worktree_paths):
        full_entry = full.get(relative)
        autonomy_entry = autonomy.get(relative)
        classification = _classify(full_entry, autonomy_entry)
        worktree = _worktree_entry(
            root,
            relative,
            full_entry=full_entry,
            autonomy_entry=autonomy_entry,
        )
        if classification == "worktree_only_untracked":
            integration_status = "ownership_resolution_required"
            owner = "working_tree_user_preserved"
        elif classification == "divergent_conflict":
            integration_status = "behavioral_resolution_required"
            owner = "shared_conflict_unresolved"
        elif classification == "full_product_only":
            integration_status = (
                "exact_untracked_candidate_preserved"
                if worktree["matches_full_product"]
                else "materialization_or_resolution_required"
            )
            owner = "full_product_candidate"
        elif classification == "autonomy_only":
            integration_status = (
                "present_exact"
                if worktree["matches_autonomy"]
                else "autonomy_worktree_resolution_required"
            )
            owner = "autonomy"
        else:
            integration_status = (
                "present_exact"
                if worktree["matches_autonomy"]
                else "worktree_resolution_required"
            )
            owner = "shared_identical"
        rows.append(
            {
                "path": relative,
                "classification": classification,
                "owner": owner,
                "integration_status": integration_status,
                "unresolved_conflict": integration_status.endswith(
                    "resolution_required"
                ),
                "full_product": copy.deepcopy(full_entry),
                "autonomy": copy.deepcopy(autonomy_entry),
                "worktree": worktree,
            }
        )
    classifications = Counter(row["classification"] for row in rows)
    integration = Counter(row["integration_status"] for row in rows)
    inventory = {
        "schema_version": SCHEMA_VERSION,
        "tracker_item": "MF-P6-20.01",
        "item24_verify_binding": {
            "plan": "Plan/28_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION_AND_COMFYUI_ADOPTION.md",
            "item_file": "Plan/Items/24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md",
            "verify_boundary": (
                "complete path classification; no unexplained deletion, overwrite, "
                "reset, replacement worktree, or unresolved conflict"
            ),
            "authority_sha256": dict(sorted(authority_hashes.items())),
        },
        "scope": {
            "prefixes": list(prefixes),
            "root_files": list(root_files),
            "excludes_runtime_evidence_models_and_dependencies": True,
        },
        "full_product": {
            "requested_ref": full_product_ref,
            "commit_sha": full_commit,
            "tree_sha": full_tree,
        },
        "autonomy": {
            "requested_ref": autonomy_ref,
            "commit_sha": autonomy_commit,
            "tree_sha": autonomy_tree,
        },
        "summary": {
            "full_product_path_count": len(full),
            "autonomy_path_count": len(autonomy),
            "union_path_count": len(rows),
            "classification_counts": dict(sorted(classifications.items())),
            "integration_status_counts": dict(sorted(integration.items())),
            "unresolved_conflict_count": sum(
                bool(row["unresolved_conflict"]) for row in rows
            ),
        },
        "safety": {
            "read_only_git_object_inventory": True,
            "wholesale_merge_authorized": False,
            "reset_authorized": False,
            "replacement_worktree_authorized": False,
            "untracked_or_modified_work_must_be_preserved": True,
            "completion_credit_claimed": False,
            "limitations": [
                "This inventory classifies source ownership and conflicts only.",
                "Each divergent path still requires behavioral resolution and tests.",
                "No tracker, runtime, provider, route, mask, or release credit is claimed.",
            ],
            "open_controller_integration_guards": list(OPEN_CONTROLLER_GUARDS),
        },
        "paths": rows,
        "self_sha256": "0" * 64,
    }
    sealed = seal_inventory(inventory)
    validate_inventory(sealed)
    return sealed


def write_inventory(path: Path, value: Mapping[str, Any]) -> None:
    validate_inventory(value)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "CanonicalSourceInventoryError",
    "SCHEMA_VERSION",
    "build_inventory",
    "canonical_sha256",
    "seal_inventory",
    "validate_inventory",
    "write_inventory",
]
