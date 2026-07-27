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
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = "maskfactory.canonical_source_inventory.v1"
RESOLUTION_SCHEMA_VERSION = "maskfactory.canonical_source_resolution.v1"
RESOLUTION_SCHEMA_V2 = "maskfactory.canonical_source_resolution.v2"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
GIT_OBJECT_RE = re.compile(r"^[a-f0-9]{40,64}$")
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
    "ROLE_BUDGET_GATE_OPEN",
    "POLICY_LINEAGE_GATE_OPEN",
)
RESOLUTION_KINDS = {
    "authority_aligned_supersession",
    "behavior_preserving_autonomy_superset",
}


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


def seal_resolution_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(dict(value))
    sealed["self_sha256"] = "0" * 64
    sealed["self_sha256"] = canonical_sha256(sealed)
    return sealed


def validate_resolution_evidence(value: Mapping[str, Any]) -> None:
    schema_version = value.get("schema_version")
    required = {
        "schema_version",
        "full_product_commit_sha",
        "autonomy_commit_sha",
        "resolutions",
        "self_sha256",
    }
    if schema_version == RESOLUTION_SCHEMA_V2:
        required.update({"authority_file_sha256", "supersedes"})
    if set(value) != required:
        raise CanonicalSourceInventoryError("resolution evidence schema is not closed")
    if schema_version not in {RESOLUTION_SCHEMA_VERSION, RESOLUTION_SCHEMA_V2}:
        raise CanonicalSourceInventoryError("resolution evidence schema is unsupported")
    expected = value.get("self_sha256")
    zeroed = copy.deepcopy(dict(value))
    zeroed["self_sha256"] = "0" * 64
    if not isinstance(expected, str) or canonical_sha256(zeroed) != expected:
        raise CanonicalSourceInventoryError("resolution evidence self hash mismatch")
    for name in ("full_product_commit_sha", "autonomy_commit_sha"):
        if not isinstance(value.get(name), str) or not re.fullmatch(
            r"[a-f0-9]{40}", str(value[name])
        ):
            raise CanonicalSourceInventoryError(f"resolution evidence {name} is invalid")
    if schema_version == RESOLUTION_SCHEMA_V2:
        authority_hashes = value.get("authority_file_sha256")
        if (
            not isinstance(authority_hashes, Mapping)
            or not authority_hashes
            or any(
                not isinstance(authority_path, str)
                or not authority_path
                or not isinstance(digest, str)
                or not SHA256_RE.fullmatch(digest)
                for authority_path, digest in authority_hashes.items()
            )
        ):
            raise CanonicalSourceInventoryError(
                "resolution authority binding is invalid"
            )
        supersedes = value.get("supersedes")
        supersedes_keys = {"path", "raw_sha256", "self_sha256"}
        if (
            not isinstance(supersedes, list)
            or any(
                not isinstance(entry, Mapping)
                or set(entry) != supersedes_keys
                or not isinstance(entry.get("path"), str)
                or not entry["path"]
                or Path(entry["path"]).is_absolute()
                or ".." in Path(entry["path"]).parts
                or not isinstance(entry.get("raw_sha256"), str)
                or not SHA256_RE.fullmatch(entry["raw_sha256"])
                or not isinstance(entry.get("self_sha256"), str)
                or not SHA256_RE.fullmatch(entry["self_sha256"])
                for entry in supersedes
            )
        ):
            raise CanonicalSourceInventoryError(
                "resolution supersession binding is invalid"
            )
        superseded_paths = [str(entry["path"]) for entry in supersedes]
        if (
            superseded_paths != sorted(superseded_paths)
            or len(superseded_paths) != len(set(superseded_paths))
        ):
            raise CanonicalSourceInventoryError(
                "resolution supersession paths must be sorted and unique"
            )
    resolutions = value.get("resolutions")
    if not isinstance(resolutions, list) or not resolutions:
        raise CanonicalSourceInventoryError("resolution evidence entries are absent")
    paths: list[str] = []
    entry_keys = {
        "path",
        "resolution_kind",
        "full_product_git_object_id",
        "autonomy_git_object_id",
        "worktree_sha256",
        "verification",
        "limitations",
    }
    for entry in resolutions:
        if not isinstance(entry, Mapping) or set(entry) != entry_keys:
            raise CanonicalSourceInventoryError("resolution entry schema is not closed")
        path = entry.get("path")
        if (
            not isinstance(path, str)
            or not path
            or "\\" in path
            or Path(path).is_absolute()
            or ".." in Path(path).parts
        ):
            raise CanonicalSourceInventoryError("resolution path is invalid")
        paths.append(path)
        if entry.get("resolution_kind") not in RESOLUTION_KINDS:
            raise CanonicalSourceInventoryError("resolution kind is unsupported")
        for name in ("full_product_git_object_id", "autonomy_git_object_id"):
            if not isinstance(entry.get(name), str) or not GIT_OBJECT_RE.fullmatch(
                str(entry[name])
            ):
                raise CanonicalSourceInventoryError(f"resolution {name} is invalid")
        if not isinstance(entry.get("worktree_sha256"), str) or not SHA256_RE.fullmatch(
            str(entry["worktree_sha256"])
        ):
            raise CanonicalSourceInventoryError("resolution worktree hash is invalid")
        resolution_kind = entry["resolution_kind"]
        verification = entry.get("verification")
        common_verification_keys = {
            "commands",
            "passed_test_count",
            "result",
        }
        expected_verification_keys = (
            common_verification_keys | {"candidate_test_git_object_ids"}
            if resolution_kind == "behavior_preserving_autonomy_superset"
            else common_verification_keys | {"test_lineage"}
        )
        if (
            not isinstance(verification, Mapping)
            or set(verification) != expected_verification_keys
            or verification.get("result") != "pass"
            or not isinstance(verification.get("passed_test_count"), int)
            or verification["passed_test_count"] < 1
            or not isinstance(verification.get("commands"), list)
            or not verification["commands"]
            or any(
                not isinstance(command, str) or not command
                for command in verification["commands"]
            )
        ):
            raise CanonicalSourceInventoryError(
                "resolution verification binding is invalid"
            )
        if resolution_kind == "behavior_preserving_autonomy_superset":
            test_objects = verification.get("candidate_test_git_object_ids")
            if (
                not isinstance(test_objects, Mapping)
                or not test_objects
                or any(
                    not isinstance(test_path, str)
                    or not test_path
                    or not isinstance(object_id, str)
                    or not GIT_OBJECT_RE.fullmatch(object_id)
                    for test_path, object_id in test_objects.items()
                )
            ):
                raise CanonicalSourceInventoryError(
                    "resolution candidate test binding is invalid"
                )
        else:
            test_lineage = verification.get("test_lineage")
            lineage_keys = {
                "full_product_git_object_id",
                "autonomy_git_object_id",
                "worktree_sha256",
            }
            if (
                not isinstance(test_lineage, Mapping)
                or not test_lineage
                or any(
                    not isinstance(test_path, str)
                    or not test_path
                    or not isinstance(lineage, Mapping)
                    or set(lineage) != lineage_keys
                    or not GIT_OBJECT_RE.fullmatch(
                        str(lineage["full_product_git_object_id"])
                    )
                    or not GIT_OBJECT_RE.fullmatch(
                        str(lineage["autonomy_git_object_id"])
                    )
                    or not SHA256_RE.fullmatch(str(lineage["worktree_sha256"]))
                    for test_path, lineage in test_lineage.items()
                )
            ):
                raise CanonicalSourceInventoryError(
                    "resolution test lineage binding is invalid"
                )
        limitations = entry.get("limitations")
        if (
            not isinstance(limitations, list)
            or not limitations
            or any(not isinstance(item, str) or not item for item in limitations)
        ):
            raise CanonicalSourceInventoryError("resolution limitations are absent")
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise CanonicalSourceInventoryError(
            "resolution paths must be sorted and unique"
        )


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
    resolved = [
        row
        for row in paths
        if str(row.get("integration_status", "")).startswith("resolved_")
    ]
    resolution_binding = value.get("resolution_evidence")
    if resolved:
        if (
            not isinstance(resolution_binding, Mapping)
            or set(resolution_binding)
            != {"path", "raw_sha256", "self_sha256", "resolution_count"}
            or not isinstance(resolution_binding.get("path"), str)
            or not resolution_binding["path"]
            or not isinstance(resolution_binding.get("raw_sha256"), str)
            or not SHA256_RE.fullmatch(resolution_binding["raw_sha256"])
            or not isinstance(resolution_binding.get("self_sha256"), str)
            or not SHA256_RE.fullmatch(resolution_binding["self_sha256"])
            or resolution_binding.get("resolution_count") != len(resolved)
            or any(
                row.get("unresolved_conflict") is not False
                or row.get("owner") != "shared_behavior_resolved"
                or row.get("resolution", {}).get("evidence_self_sha256")
                != resolution_binding["self_sha256"]
                or (
                    row.get("integration_status")
                    == "resolved_behavioral_autonomy_superset"
                    and row.get("resolution", {}).get("kind")
                    != "behavior_preserving_autonomy_superset"
                )
                or (
                    row.get("integration_status")
                    == "resolved_authority_aligned_supersession"
                    and row.get("resolution", {}).get("kind")
                    != "authority_aligned_supersession"
                )
                for row in resolved
            )
        ):
            raise CanonicalSourceInventoryError(
                "inventory resolution binding drift"
            )
    elif resolution_binding is not None:
        raise CanonicalSourceInventoryError(
            "inventory binds unused resolution evidence"
        )


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


def _is_generated_worktree_path(path: str) -> bool:
    """Exclude Python bytecode caches from a source-path reconciliation inventory."""
    parts = PurePosixPath(path).parts
    return "__pycache__" in parts or path.endswith((".pyc", ".pyo"))


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


def _read_resolution_chain(
    *,
    root: Path,
    top_level: Mapping[str, Any],
    full_commit: str,
    autonomy_commit: str,
) -> dict[str, Mapping[str, Any]]:
    """Resolve a hash-bound supersession chain into its latest path entries."""
    documents: list[Mapping[str, Any]] = [top_level]
    seen_paths: set[str] = set()
    position = 0
    while position < len(documents):
        document = documents[position]
        position += 1
        if (
            document.get("full_product_commit_sha") != full_commit
            or document.get("autonomy_commit_sha") != autonomy_commit
        ):
            raise CanonicalSourceInventoryError(
                "resolution evidence commit binding mismatch"
            )
        if document.get("schema_version") != RESOLUTION_SCHEMA_V2:
            continue
        for superseded in document["supersedes"]:
            receipt_path = str(superseded["path"])
            if receipt_path in seen_paths:
                raise CanonicalSourceInventoryError(
                    "resolution supersession chain contains a cycle"
                )
            seen_paths.add(receipt_path)
            receipt_file = root / receipt_path
            if (
                not receipt_file.is_file()
                or _file_sha256(receipt_file)[0] != superseded["raw_sha256"]
            ):
                raise CanonicalSourceInventoryError(
                    "resolution superseded receipt raw binding drift: "
                    f"{receipt_path}"
                )
            try:
                value = json.loads(receipt_file.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise CanonicalSourceInventoryError(
                    "resolution superseded receipt is unreadable: "
                    f"{receipt_path}"
                ) from exc
            if not isinstance(value, Mapping):
                raise CanonicalSourceInventoryError(
                    "resolution superseded receipt is not an object: "
                    f"{receipt_path}"
                )
            validate_resolution_evidence(value)
            if value["self_sha256"] != superseded["self_sha256"]:
                raise CanonicalSourceInventoryError(
                    "resolution superseded receipt self binding drift: "
                    f"{receipt_path}"
                )
            documents.append(value)

    entries: dict[str, Mapping[str, Any]] = {}
    source_fields = {
        "full_product_git_object_id",
        "autonomy_git_object_id",
        "worktree_sha256",
    }
    for document in reversed(documents):
        for entry in document["resolutions"]:
            path = str(entry["path"])
            previous = entries.get(path)
            if previous is not None and any(
                previous[field] != entry[field] for field in source_fields
            ):
                raise CanonicalSourceInventoryError(
                    "resolution supersession source binding contradiction: "
                    f"{path}"
                )
            entries[path] = entry
    return entries


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
    paths = (
        raw.decode("utf-8", errors="surrogateescape")
        for raw in output.split(b"\0")
        if raw
    )
    return {
        path
        for path in paths
        if _in_scope(path, prefixes=prefixes, root_files=root_files)
        and not _is_generated_worktree_path(path)
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
    resolution_evidence: Mapping[str, Any] | None = None,
    resolution_evidence_path: str | None = None,
    resolution_evidence_raw_sha256: str | None = None,
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
    resolution_entries: dict[str, Mapping[str, Any]] = {}
    resolution_binding: dict[str, Any] | None = None
    if resolution_evidence is not None:
        validate_resolution_evidence(resolution_evidence)
        if (
            not isinstance(resolution_evidence_path, str)
            or not resolution_evidence_path
            or Path(resolution_evidence_path).is_absolute()
            or ".." in Path(resolution_evidence_path).parts
            or not isinstance(resolution_evidence_raw_sha256, str)
            or not SHA256_RE.fullmatch(resolution_evidence_raw_sha256)
        ):
            raise CanonicalSourceInventoryError(
                "resolution evidence file binding is invalid"
            )
        resolution_entries = _read_resolution_chain(
            root=root,
            top_level=resolution_evidence,
            full_commit=full_commit,
            autonomy_commit=autonomy_commit,
        )
        resolution_binding = {
            "path": resolution_evidence_path,
            "raw_sha256": resolution_evidence_raw_sha256,
            "self_sha256": resolution_evidence["self_sha256"],
            "resolution_count": len(resolution_entries),
        }
    elif (
        resolution_evidence_path is not None
        or resolution_evidence_raw_sha256 is not None
    ):
        raise CanonicalSourceInventoryError(
            "resolution evidence binding is incomplete"
        )
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
        resolution = resolution_entries.get(relative)
        if resolution is not None:
            if classification != "divergent_conflict":
                raise CanonicalSourceInventoryError(
                    f"resolution path is not a divergent conflict: {relative}"
                )
            if (
                full_entry is None
                or autonomy_entry is None
                or resolution["full_product_git_object_id"]
                != full_entry["git_object_id"]
                or resolution["autonomy_git_object_id"]
                != autonomy_entry["git_object_id"]
                or resolution["worktree_sha256"] != worktree["sha256"]
            ):
                raise CanonicalSourceInventoryError(
                    f"resolution source binding drift: {relative}"
                )
            if (
                resolution["resolution_kind"]
                == "behavior_preserving_autonomy_superset"
            ):
                for test_path, object_id in resolution["verification"][
                    "candidate_test_git_object_ids"
                ].items():
                    if (
                        test_path not in full
                        or test_path not in autonomy
                        or full[test_path]["git_object_id"] != object_id
                        or autonomy[test_path]["git_object_id"] != object_id
                    ):
                        raise CanonicalSourceInventoryError(
                            f"resolution candidate test drift: {test_path}"
                        )
                integration_status = "resolved_behavioral_autonomy_superset"
            else:
                for authority_path, digest in resolution_evidence[
                    "authority_file_sha256"
                ].items():
                    authority_file = root / authority_path
                    if (
                        not authority_file.is_file()
                        or _file_sha256(authority_file)[0] != digest
                    ):
                        raise CanonicalSourceInventoryError(
                            f"resolution authority drift: {authority_path}"
                        )
                for test_path, lineage in resolution["verification"][
                    "test_lineage"
                ].items():
                    test_file = root / test_path
                    if (
                        test_path not in full
                        or test_path not in autonomy
                        or full[test_path]["git_object_id"]
                        != lineage["full_product_git_object_id"]
                        or autonomy[test_path]["git_object_id"]
                        != lineage["autonomy_git_object_id"]
                        or not test_file.is_file()
                        or _file_sha256(test_file)[0]
                        != lineage["worktree_sha256"]
                    ):
                        raise CanonicalSourceInventoryError(
                            f"resolution test lineage drift: {test_path}"
                        )
                integration_status = "resolved_authority_aligned_supersession"
            owner = "shared_behavior_resolved"
        elif classification == "worktree_only_untracked":
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
                "resolution": (
                    {
                        "kind": resolution["resolution_kind"],
                        "evidence_self_sha256": resolution_evidence["self_sha256"],
                    }
                    if resolution is not None
                    else None
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
        "resolution_evidence": resolution_binding,
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
    "RESOLUTION_SCHEMA_VERSION",
    "RESOLUTION_SCHEMA_V2",
    "SCHEMA_VERSION",
    "build_inventory",
    "canonical_sha256",
    "seal_inventory",
    "seal_resolution_evidence",
    "validate_inventory",
    "validate_resolution_evidence",
    "write_inventory",
]
