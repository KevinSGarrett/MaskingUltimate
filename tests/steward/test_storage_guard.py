from __future__ import annotations

from pathlib import Path

import pytest

from maskfactory.steward.storage_guard import (
    LocalStorageGuard,
    StorageGuardError,
    StoragePolicy,
    worktree_retirement_allowed,
)


def policy() -> StoragePolicy:
    return StoragePolicy.from_mapping(
        {
            "schema_version": "maskfactory_local_workspace_hygiene.v1",
            "warning_free_gib": 75,
            "new_allocation_floor_gib": 50,
            "maximum_single_local_backup_bytes": 1024,
            "full_repository_bundle_allowed": False,
            "verified_checkpoint_retention_count": 2,
            "verified_checkpoint_retention_hours": 24,
        }
    )


def test_policy_loads_repository_config() -> None:
    root = Path(__file__).resolve().parents[2]
    loaded = StoragePolicy.load(root / "configs" / "local_workspace_hygiene_v1.json")

    assert loaded.allocation_floor_bytes == 50 * 1024**3
    assert loaded.full_repository_bundle_allowed is False


def test_allocation_preserves_floor_and_backup_cap() -> None:
    guard = LocalStorageGuard(policy())
    free = 60 * 1024**3

    guard.require_allocation(kind="worktree", expected_bytes=1024, free_bytes=free)
    with pytest.raises(StorageGuardError, match="free-space floor"):
        guard.require_allocation(
            kind="worktree",
            expected_bytes=11 * 1024**3,
            free_bytes=free,
        )
    with pytest.raises(StorageGuardError, match="size cap"):
        guard.require_allocation(
            kind="incremental_backup",
            expected_bytes=1025,
            free_bytes=free,
        )


def test_full_repository_bundle_is_always_blocked() -> None:
    guard = LocalStorageGuard(policy())

    with pytest.raises(StorageGuardError, match="prohibited"):
        guard.require_allocation(
            kind="full_repository_bundle",
            expected_bytes=1,
            free_bytes=100 * 1024**3,
        )


@pytest.mark.parametrize(
    (
        "dirty_entries",
        "remote_contains_head",
        "process_references",
        "is_main_checkout",
        "has_reparse_points",
    ),
    [
        (1, True, 0, False, False),
        (0, False, 0, False, False),
        (0, True, 1, False, False),
        (0, True, 0, True, False),
        (0, True, 0, False, True),
    ],
)
def test_worktree_retirement_refuses_any_unsafe_condition(
    dirty_entries: int,
    remote_contains_head: bool,
    process_references: int,
    is_main_checkout: bool,
    has_reparse_points: bool,
) -> None:
    assert not worktree_retirement_allowed(
        dirty_entries=dirty_entries,
        remote_contains_head=remote_contains_head,
        process_references=process_references,
        is_main_checkout=is_main_checkout,
        has_reparse_points=has_reparse_points,
    )


def test_worktree_retirement_requires_all_positive_evidence() -> None:
    assert worktree_retirement_allowed(
        dirty_entries=0,
        remote_contains_head=True,
        process_references=0,
        is_main_checkout=False,
        has_reparse_points=False,
    )
