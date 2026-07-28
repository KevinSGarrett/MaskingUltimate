from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from maskfactory.steward.canonical_source_inventory import (
    CanonicalSourceInventoryError,
    build_inventory,
    seal_inventory,
    seal_resolution_evidence,
    validate_inventory,
    validate_resolution_evidence,
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
    assert rows["src/full_only.py"]["worktree"]["state"] == "untracked_full_product_exact_preserve"
    assert inventory["safety"]["wholesale_merge_authorized"] is False
    assert inventory["safety"]["reset_authorized"] is False
    assert rows["tools/user_owned.py"]["owner"] == "working_tree_user_preserved"
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


def test_inventory_excludes_generated_python_bytecode_from_source_scope(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _write(repo / "src/__pycache__/shared.cpython-311.pyc", "generated\n")
    _write(repo / "tests/__pycache__/test_full.cpython-311.pyo", "generated\n")
    _write(repo / "tools/user_owned.py", "preserve\n")

    inventory = build_inventory(
        repo_root=repo,
        full_product_ref="full-product",
        autonomy_ref="HEAD",
        authority_hashes={"Plan/28.md": "c" * 64},
    )

    assert all("__pycache__" not in row["path"] for row in inventory["paths"])
    assert all(not row["path"].endswith((".pyc", ".pyo")) for row in inventory["paths"])
    user_row = next(row for row in inventory["paths"] if row["path"] == "tools/user_owned.py")
    assert user_row["integration_status"] == "ownership_resolution_required"


def test_exact_resolution_evidence_closes_only_bound_conflict(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    full_commit = _git(repo, "rev-parse", "full-product")
    autonomy_commit = _git(repo, "rev-parse", "HEAD")
    full_object = _git(repo, "rev-parse", "full-product:src/shared.py")
    autonomy_object = _git(repo, "rev-parse", "HEAD:src/shared.py")
    test_object = _git(repo, "rev-parse", "HEAD:tests/test_full.py")
    worktree_sha = hashlib.sha256((repo / "src/shared.py").read_bytes()).hexdigest()
    resolution = seal_resolution_evidence(
        {
            "schema_version": "maskfactory.canonical_source_resolution.v1",
            "full_product_commit_sha": full_commit,
            "autonomy_commit_sha": autonomy_commit,
            "resolutions": [
                {
                    "path": "src/shared.py",
                    "resolution_kind": "behavior_preserving_autonomy_superset",
                    "full_product_git_object_id": full_object,
                    "autonomy_git_object_id": autonomy_object,
                    "worktree_sha256": worktree_sha,
                    "verification": {
                        "commands": ["python -m pytest tests/test_full.py -q"],
                        "passed_test_count": 1,
                        "candidate_test_git_object_ids": {"tests/test_full.py": test_object},
                        "result": "pass",
                    },
                    "limitations": ["This resolves only src/shared.py."],
                }
            ],
            "self_sha256": "0" * 64,
        }
    )
    raw = (json.dumps(resolution, sort_keys=True) + "\n").encode()
    inventory = build_inventory(
        repo_root=repo,
        full_product_ref=full_commit,
        autonomy_ref=autonomy_commit,
        authority_hashes={"Plan/28.md": "d" * 64},
        resolution_evidence=resolution,
        resolution_evidence_path="qa/resolution.json",
        resolution_evidence_raw_sha256=hashlib.sha256(raw).hexdigest(),
    )
    row = next(row for row in inventory["paths"] if row["path"] == "src/shared.py")
    assert row["integration_status"] == "resolved_behavioral_autonomy_superset"
    assert row["unresolved_conflict"] is False
    assert inventory["summary"]["unresolved_conflict_count"] == 1
    validate_resolution_evidence(resolution)
    validate_inventory(inventory)

    changed = copy.deepcopy(resolution)
    changed["resolutions"][0]["worktree_sha256"] = "f" * 64
    with pytest.raises(CanonicalSourceInventoryError, match="source binding drift"):
        build_inventory(
            repo_root=repo,
            full_product_ref=full_commit,
            autonomy_ref=autonomy_commit,
            authority_hashes={"Plan/28.md": "d" * 64},
            resolution_evidence=seal_resolution_evidence(changed),
            resolution_evidence_path="qa/resolution.json",
            resolution_evidence_raw_sha256=hashlib.sha256(raw).hexdigest(),
        )


def test_authority_supersession_requires_exact_authority_and_test_lineage(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    authority_path = repo / "Plan/28.md"
    _write(authority_path, "canonical authority\n")
    full_commit = _git(repo, "rev-parse", "full-product")
    autonomy_commit = _git(repo, "rev-parse", "HEAD")
    test_path = repo / "tests/test_full.py"
    test_object = _git(repo, "rev-parse", "HEAD:tests/test_full.py")
    superseded = seal_resolution_evidence(
        {
            "schema_version": "maskfactory.canonical_source_resolution.v1",
            "full_product_commit_sha": full_commit,
            "autonomy_commit_sha": autonomy_commit,
            "resolutions": [
                {
                    "path": "src/shared.py",
                    "resolution_kind": "behavior_preserving_autonomy_superset",
                    "full_product_git_object_id": _git(
                        repo, "rev-parse", "full-product:src/shared.py"
                    ),
                    "autonomy_git_object_id": _git(repo, "rev-parse", "HEAD:src/shared.py"),
                    "worktree_sha256": hashlib.sha256(
                        (repo / "src/shared.py").read_bytes()
                    ).hexdigest(),
                    "verification": {
                        "commands": ["python -m pytest tests/test_full.py -q"],
                        "passed_test_count": 1,
                        "candidate_test_git_object_ids": {"tests/test_full.py": test_object},
                        "result": "pass",
                    },
                    "limitations": ["This resolves only src/shared.py."],
                }
            ],
            "self_sha256": "0" * 64,
        }
    )
    superseded_raw = (json.dumps(superseded, indent=2, sort_keys=True) + "\n").encode("utf-8")
    superseded_path = repo / "qa/old-resolution.json"
    superseded_path.parent.mkdir(parents=True, exist_ok=True)
    superseded_path.write_bytes(superseded_raw)
    resolution = seal_resolution_evidence(
        {
            "schema_version": "maskfactory.canonical_source_resolution.v2",
            "full_product_commit_sha": full_commit,
            "autonomy_commit_sha": autonomy_commit,
            "authority_file_sha256": {
                "Plan/28.md": hashlib.sha256(authority_path.read_bytes()).hexdigest()
            },
            "supersedes": [
                {
                    "path": "qa/old-resolution.json",
                    "raw_sha256": hashlib.sha256(superseded_raw).hexdigest(),
                    "self_sha256": superseded["self_sha256"],
                }
            ],
            "resolutions": [
                {
                    "path": "src/shared.py",
                    "resolution_kind": "authority_aligned_supersession",
                    "full_product_git_object_id": _git(
                        repo, "rev-parse", "full-product:src/shared.py"
                    ),
                    "autonomy_git_object_id": _git(repo, "rev-parse", "HEAD:src/shared.py"),
                    "worktree_sha256": hashlib.sha256(
                        (repo / "src/shared.py").read_bytes()
                    ).hexdigest(),
                    "verification": {
                        "commands": ["python -m pytest tests/test_full.py -q"],
                        "passed_test_count": 1,
                        "test_lineage": {
                            "tests/test_full.py": {
                                "full_product_git_object_id": test_object,
                                "autonomy_git_object_id": test_object,
                                "worktree_sha256": hashlib.sha256(
                                    test_path.read_bytes()
                                ).hexdigest(),
                            }
                        },
                        "result": "pass",
                    },
                    "limitations": ["This resolves only src/shared.py."],
                }
            ],
            "self_sha256": "0" * 64,
        }
    )
    inventory = build_inventory(
        repo_root=repo,
        full_product_ref=full_commit,
        autonomy_ref=autonomy_commit,
        authority_hashes={"Plan/28.md": "e" * 64},
        resolution_evidence=resolution,
        resolution_evidence_path="qa/resolution-v2.json",
        resolution_evidence_raw_sha256="f" * 64,
    )
    row = next(row for row in inventory["paths"] if row["path"] == "src/shared.py")
    assert row["integration_status"] == "resolved_authority_aligned_supersession"
    assert row["unresolved_conflict"] is False
    validate_resolution_evidence(resolution)
    validate_inventory(inventory)

    _write(authority_path, "drifted authority\n")
    with pytest.raises(CanonicalSourceInventoryError, match="authority drift"):
        build_inventory(
            repo_root=repo,
            full_product_ref=full_commit,
            autonomy_ref=autonomy_commit,
            authority_hashes={"Plan/28.md": "e" * 64},
            resolution_evidence=resolution,
            resolution_evidence_path="qa/resolution-v2.json",
            resolution_evidence_raw_sha256="f" * 64,
        )

    _write(superseded_path, "{}\n")
    with pytest.raises(
        CanonicalSourceInventoryError,
        match="superseded receipt raw binding drift",
    ):
        build_inventory(
            repo_root=repo,
            full_product_ref=full_commit,
            autonomy_ref=autonomy_commit,
            authority_hashes={"Plan/28.md": "e" * 64},
            resolution_evidence=resolution,
            resolution_evidence_path="qa/resolution-v2.json",
            resolution_evidence_raw_sha256="f" * 64,
        )


def test_authority_aligned_resolution_can_bootstrap_without_prior_same_commit(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    full_commit = _git(repo, "rev-parse", "full-product")
    autonomy_commit = _git(repo, "rev-parse", "HEAD")
    path = "src/shared.py"
    test_path = "tests/test_full.py"
    authority_path = repo / "Plan/28.md"
    _write(authority_path, "canonical authority\n")
    authority_sha256 = hashlib.sha256(authority_path.read_bytes()).hexdigest()
    resolution = seal_resolution_evidence(
        {
            "schema_version": "maskfactory.canonical_source_resolution.v2",
            "full_product_commit_sha": full_commit,
            "autonomy_commit_sha": autonomy_commit,
            "authority_file_sha256": {"Plan/28.md": authority_sha256},
            "supersedes": [],
            "resolutions": [
                {
                    "path": path,
                    "resolution_kind": "authority_aligned_supersession",
                    "full_product_git_object_id": _git(repo, "rev-parse", f"full-product:{path}"),
                    "autonomy_git_object_id": _git(repo, "rev-parse", f"HEAD:{path}"),
                    "worktree_sha256": hashlib.sha256((repo / path).read_bytes()).hexdigest(),
                    "verification": {
                        "commands": ["python -m pytest tests/test_full.py -q"],
                        "passed_test_count": 1,
                        "test_lineage": {
                            test_path: {
                                "full_product_git_object_id": _git(
                                    repo,
                                    "rev-parse",
                                    f"full-product:{test_path}",
                                ),
                                "autonomy_git_object_id": _git(
                                    repo, "rev-parse", f"HEAD:{test_path}"
                                ),
                                "worktree_sha256": hashlib.sha256(
                                    (repo / test_path).read_bytes()
                                ).hexdigest(),
                            }
                        },
                        "result": "pass",
                    },
                    "limitations": ["This bootstrap resolves only src/shared.py."],
                }
            ],
            "self_sha256": "0" * 64,
        }
    )

    inventory = build_inventory(
        repo_root=repo,
        full_product_ref=full_commit,
        autonomy_ref=autonomy_commit,
        authority_hashes={"Plan/28.md": authority_sha256},
        resolution_evidence=resolution,
        resolution_evidence_path="qa/resolution-bootstrap.json",
        resolution_evidence_raw_sha256="f" * 64,
    )

    row = next(row for row in inventory["paths"] if row["path"] == path)
    assert row["integration_status"] == "resolved_authority_aligned_supersession"
    validate_resolution_evidence(resolution)
    validate_inventory(inventory)


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
