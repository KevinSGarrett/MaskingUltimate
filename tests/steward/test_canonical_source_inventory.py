from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import pytest

from maskfactory.steward.canonical_source_inventory import (
    CanonicalSourceInventoryError,
    build_inventory,
    seal_inventory,
    validate_inventory,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
        encoding="utf-8",
    ).strip()


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Codex Test")
    _git(repo, "config", "user.email", "codex@example.invalid")
    _write(repo / "src/shared.py", "full\n")
    _write(repo / "src/full_only.py", "full-only\n")
    _write(repo / "tests/test_full.py", "def test_full(): pass\n")
    _write(repo / "pyproject.toml", "[project]\nname='full'\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "full")
    _git(repo, "branch", "full-product")
    _write(repo / "src/shared.py", "autonomy\n")
    (repo / "src/full_only.py").unlink()
    _write(repo / "src/autonomy_only.py", "autonomy-only\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "autonomy")
    return repo


def test_inventory_classifies_exact_union_and_preserves_dirty_worktree(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _write(repo / "src/shared.py", "user-dirty\n")
    _write(repo / "src/full_only.py", "full-only\n")
    _write(repo / "tools/user_owned.py", "preserve\n")
    inventory = build_inventory(
        repo_root=repo,
        full_product_ref="full-product",
        autonomy_ref="HEAD",
        authority_hashes={"Plan/28.md": "a" * 64},
    )

    rows = {row["path"]: row for row in inventory["paths"]}
    assert inventory["summary"] == {
        "full_product_path_count": 4,
        "autonomy_path_count": 4,
        "union_path_count": 6,
        "classification_counts": {
            "autonomy_only": 1,
            "divergent_conflict": 1,
            "full_product_only": 1,
            "identical": 2,
            "worktree_only_untracked": 1,
        },
        "integration_status_counts": {
            "behavioral_resolution_required": 1,
            "exact_untracked_candidate_preserved": 1,
            "ownership_resolution_required": 1,
            "present_exact": 3,
        },
        "unresolved_conflict_count": 2,
    }
    assert rows["src/shared.py"]["worktree"]["state"] == "tracked_modified_preserve"
    assert rows["src/shared.py"]["unresolved_conflict"] is True
    assert (
        rows["src/full_only.py"]["worktree"]["state"]
        == "untracked_full_product_exact_preserve"
    )
    assert inventory["safety"]["wholesale_merge_authorized"] is False
    assert inventory["safety"]["reset_authorized"] is False
    assert (
        rows["tools/user_owned.py"]["owner"]
        == "working_tree_user_preserved"
    )
    validate_inventory(inventory)


def test_inventory_replay_is_deterministic_and_tamper_fails(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    kwargs = {
        "repo_root": repo,
        "full_product_ref": "full-product",
        "autonomy_ref": "HEAD",
        "authority_hashes": {"Plan/28.md": "b" * 64},
    }
    first = build_inventory(**kwargs)
    second = build_inventory(**kwargs)
    assert first == second

    changed = copy.deepcopy(first)
    changed["summary"]["union_path_count"] += 1
    with pytest.raises(CanonicalSourceInventoryError, match="self hash"):
        validate_inventory(changed)

    changed = copy.deepcopy(first)
    changed["safety"]["completion_credit_claimed"] = True
    with pytest.raises(CanonicalSourceInventoryError, match="completion credit"):
        validate_inventory(seal_inventory(changed))

    changed = copy.deepcopy(first)
    changed["paths"][0]["integration_status"] = "invented"
    with pytest.raises(CanonicalSourceInventoryError, match="integration summary"):
        validate_inventory(seal_inventory(changed))


def test_inventory_rejects_non_root_and_bad_authority_hash(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(CanonicalSourceInventoryError, match="worktree root"):
        build_inventory(
            repo_root=repo / "src",
            full_product_ref="full-product",
            autonomy_ref="HEAD",
            authority_hashes={"Plan/28.md": "c" * 64},
        )
    with pytest.raises(CanonicalSourceInventoryError, match="authority hash"):
        build_inventory(
            repo_root=repo,
            full_product_ref="full-product",
            autonomy_ref="HEAD",
            authority_hashes={"Plan/28.md": "bad"},
        )
