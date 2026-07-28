"""Fail-closed local storage and worktree hygiene policy.

This module does not delete files.  It makes allocation and retirement
decisions explicit so supervisors and operator tools can refuse unsafe local
growth before creating another clone, worktree, or repository-scale backup.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "maskfactory_local_workspace_hygiene.v1"
ALLOCATION_KINDS = frozenset(
    {"incremental_backup", "worktree", "runtime_evidence", "full_repository_bundle"}
)


class StorageGuardError(RuntimeError):
    """The requested allocation or retirement is unsafe."""


def _positive_int(value: object, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise StorageGuardError(f"{field} must be a positive integer")
    return value


@dataclass(frozen=True)
class StoragePolicy:
    warning_free_bytes: int
    allocation_floor_bytes: int
    maximum_single_backup_bytes: int
    full_repository_bundle_allowed: bool
    verified_checkpoint_retention_count: int
    verified_checkpoint_retention_hours: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StoragePolicy":
        if value.get("schema_version") != SCHEMA_VERSION:
            raise StorageGuardError("storage policy schema mismatch")
        warning_gib = _positive_int(value.get("warning_free_gib"), field="warning_free_gib")
        floor_gib = _positive_int(
            value.get("new_allocation_floor_gib"),
            field="new_allocation_floor_gib",
        )
        if floor_gib > warning_gib:
            raise StorageGuardError("allocation floor cannot exceed warning threshold")
        allowed = value.get("full_repository_bundle_allowed")
        if not isinstance(allowed, bool):
            raise StorageGuardError("full_repository_bundle_allowed must be boolean")
        return cls(
            warning_free_bytes=warning_gib * 1024**3,
            allocation_floor_bytes=floor_gib * 1024**3,
            maximum_single_backup_bytes=_positive_int(
                value.get("maximum_single_local_backup_bytes"),
                field="maximum_single_local_backup_bytes",
            ),
            full_repository_bundle_allowed=allowed,
            verified_checkpoint_retention_count=_positive_int(
                value.get("verified_checkpoint_retention_count"),
                field="verified_checkpoint_retention_count",
            ),
            verified_checkpoint_retention_hours=_positive_int(
                value.get("verified_checkpoint_retention_hours"),
                field="verified_checkpoint_retention_hours",
            ),
        )

    @classmethod
    def load(cls, path: Path) -> "StoragePolicy":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StorageGuardError(f"storage policy is unreadable: {path}") from exc
        if not isinstance(value, dict):
            raise StorageGuardError("storage policy must be an object")
        return cls.from_mapping(value)


@dataclass(frozen=True)
class StorageSnapshot:
    root: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    warning: bool
    allocation_blocked: bool


class LocalStorageGuard:
    """Evaluate local allocations without mutating the filesystem."""

    def __init__(self, policy: StoragePolicy):
        self.policy = policy

    def snapshot(self, root: Path) -> StorageSnapshot:
        usage = shutil.disk_usage(root)
        return StorageSnapshot(
            root=str(root),
            total_bytes=usage.total,
            used_bytes=usage.used,
            free_bytes=usage.free,
            warning=usage.free < self.policy.warning_free_bytes,
            allocation_blocked=usage.free < self.policy.allocation_floor_bytes,
        )

    def require_allocation(
        self,
        *,
        kind: str,
        expected_bytes: int,
        free_bytes: int,
    ) -> None:
        if kind not in ALLOCATION_KINDS:
            raise StorageGuardError(f"unknown allocation kind: {kind}")
        if not isinstance(expected_bytes, int) or expected_bytes < 0:
            raise StorageGuardError("expected_bytes must be a non-negative integer")
        if not isinstance(free_bytes, int) or free_bytes < 0:
            raise StorageGuardError("free_bytes must be a non-negative integer")
        if kind == "full_repository_bundle" and not self.policy.full_repository_bundle_allowed:
            raise StorageGuardError("full repository bundles are prohibited")
        if (
            kind == "incremental_backup"
            and expected_bytes > self.policy.maximum_single_backup_bytes
        ):
            raise StorageGuardError("incremental backup exceeds the local size cap")
        remaining = free_bytes - expected_bytes
        if remaining < self.policy.allocation_floor_bytes:
            raise StorageGuardError("allocation would violate the local free-space floor")


def worktree_retirement_allowed(
    *,
    dirty_entries: int,
    remote_contains_head: bool,
    process_references: int,
    is_main_checkout: bool,
    has_reparse_points: bool,
) -> bool:
    """Return whether a worktree may enter an explicit retirement operation."""

    if dirty_entries < 0 or process_references < 0:
        raise StorageGuardError("worktree counters cannot be negative")
    return (
        dirty_entries == 0
        and remote_contains_head
        and process_references == 0
        and not is_main_checkout
        and not has_reparse_points
    )


__all__ = [
    "ALLOCATION_KINDS",
    "LocalStorageGuard",
    "SCHEMA_VERSION",
    "StorageGuardError",
    "StoragePolicy",
    "StorageSnapshot",
    "worktree_retirement_allowed",
]
