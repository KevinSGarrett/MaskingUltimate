from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from maskfactory.steward.repository_packet import (
    MANIFEST_NAME,
    STAGING_CONTRACT_NAME,
    RepositoryPacketError,
    build_repository_packet,
    create_patch_staging_area,
    verify_repository_packet,
)


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.autocrlf=false", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "MaskFactory Test")
    _git(root, "config", "user.email", "maskfactory@example.invalid")
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "worker.py").write_text(
        "def answer() -> int:\n    return 42\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "tests" / "test_worker.py").write_text(
        "def test_answer() -> None:\n    assert 42 == 42\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(root, "add", "src/worker.py", "tests/test_worker.py")
    _git(root, "commit", "-m", "initial")
    return root


def _build(root: Path, destination: Path, **kwargs: object) -> dict:
    options = dict(kwargs)
    options.setdefault("minimum_free_bytes", 0)
    return build_repository_packet(
        repo_root=root,
        packet_root=destination,
        source_paths=["src/worker.py", "tests/test_worker.py"],
        scope_roots=["src", "tests"],
        tracker_item_ids=["MF-P6-16.01"],
        **options,
    )


def test_builds_exact_self_hashed_packet_and_non_git_staging(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    packet_root = tmp_path / "packet"

    manifest = _build(root, packet_root)
    verified = verify_repository_packet(
        packet_root,
        repo_root=root,
        require_current_source=True,
    )
    staging = create_patch_staging_area(
        packet_root=packet_root,
        staging_root=tmp_path / "staging",
        repo_root=root,
        minimum_free_bytes=0,
    )

    assert verified == manifest
    assert manifest["source_commit"] == _git(root, "rev-parse", "HEAD")
    assert manifest["authority"] == {
        "apply_patch": False,
        "git": False,
        "github": False,
        "credentials": False,
        "runpod": False,
        "final_acceptance": False,
    }
    zeroed = dict(manifest)
    zeroed["packet_sha256"] = "0" * 64
    assert (
        manifest["packet_sha256"]
        == hashlib.sha256(
            json.dumps(
                zeroed,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
    )
    assert (tmp_path / "staging" / "sources" / "src" / "worker.py").read_bytes() == (
        root / "src" / "worker.py"
    ).read_bytes()
    assert not (tmp_path / "staging" / ".git").exists()
    assert staging["packet_sha256"] == manifest["packet_sha256"]
    assert (tmp_path / "staging" / STAGING_CONTRACT_NAME).is_file()


@pytest.mark.parametrize(
    "source_paths,scope_roots,error",
    [
        (["../outside.py"], ["src"], "escape"),
        (["src/worker.py"], ["tests"], "outside"),
        (["C:/outside.py"], ["src"], "escape"),
    ],
)
def test_rejects_path_escape_and_scope_violations(
    tmp_path: Path,
    source_paths: list[str],
    scope_roots: list[str],
    error: str,
) -> None:
    root = _repository(tmp_path)
    with pytest.raises(RepositoryPacketError, match=error):
        build_repository_packet(
            repo_root=root,
            packet_root=tmp_path / "packet",
            source_paths=source_paths,
            scope_roots=scope_roots,
            tracker_item_ids=["MF-P6-16.01"],
        )


def test_rejects_untracked_and_modified_user_work(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "src" / "untracked.py").write_text("value = 1\n", encoding="utf-8")
    with pytest.raises(RepositoryPacketError, match="not tracked"):
        build_repository_packet(
            repo_root=root,
            packet_root=tmp_path / "untracked-packet",
            source_paths=["src/untracked.py"],
            scope_roots=["src"],
            tracker_item_ids=["MF-P6-16.01"],
        )

    (root / "src" / "worker.py").write_text("value = 2\n", encoding="utf-8")
    with pytest.raises(RepositoryPacketError, match="uncommitted"):
        build_repository_packet(
            repo_root=root,
            packet_root=tmp_path / "modified-packet",
            source_paths=["src/worker.py"],
            scope_roots=["src"],
            tracker_item_ids=["MF-P6-16.01"],
        )


def test_rejects_secret_paths_and_secret_content(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    secret_path = root / "src" / "api_key.txt"
    secret_path.write_text("placeholder\n", encoding="utf-8")
    _git(root, "add", "src/api_key.txt")
    _git(root, "commit", "-m", "secret path fixture")
    with pytest.raises(RepositoryPacketError, match="secret-like"):
        build_repository_packet(
            repo_root=root,
            packet_root=tmp_path / "secret-path-packet",
            source_paths=["src/api_key.txt"],
            scope_roots=["src"],
            tracker_item_ids=["MF-P6-16.01"],
        )

    secret_path.rename(root / "src" / "settings.py")
    (root / "src" / "settings.py").write_text(
        'password = "abcdefghijklmnop"\n',
        encoding="utf-8",
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "secret content fixture")
    with pytest.raises(RepositoryPacketError, match="secret material"):
        build_repository_packet(
            repo_root=root,
            packet_root=tmp_path / "secret-content-packet",
            source_paths=["src/settings.py"],
            scope_roots=["src"],
            tracker_item_ids=["MF-P6-16.01"],
        )


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows symlink creation requires privileges not guaranteed in CI",
)
def test_rejects_symlink_sources(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    link = root / "src" / "link.py"
    link.symlink_to(root / "src" / "worker.py")
    _git(root, "add", "src/link.py")
    _git(root, "commit", "-m", "symlink fixture")
    with pytest.raises(RepositoryPacketError, match="non-symlink"):
        build_repository_packet(
            repo_root=root,
            packet_root=tmp_path / "packet",
            source_paths=["src/link.py"],
            scope_roots=["src"],
            tracker_item_ids=["MF-P6-16.01"],
        )


def test_stale_commit_and_tampered_packet_fail_closed(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    packet_root = tmp_path / "packet"
    _build(root, packet_root)
    (root / "README.md").write_text("advance\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "advance head")

    with pytest.raises(RepositoryPacketError, match="commit is stale"):
        verify_repository_packet(
            packet_root,
            repo_root=root,
            require_current_source=True,
        )

    source = packet_root / "files" / "src" / "worker.py"
    source.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(RepositoryPacketError, match="hash mismatch"):
        verify_repository_packet(packet_root)


def test_rejects_unexpected_files_reuse_and_insufficient_storage(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    packet_root = tmp_path / "packet"
    _build(root, packet_root)
    with pytest.raises(RepositoryPacketError, match="already exists"):
        _build(root, packet_root)

    (packet_root / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    with pytest.raises(RepositoryPacketError, match="unexpected path set"):
        verify_repository_packet(packet_root)

    with pytest.raises(RepositoryPacketError, match="free-space floor"):
        _build(
            root,
            tmp_path / "storage-blocked",
            minimum_free_bytes=100,
            disk_usage=lambda _: SimpleNamespace(free=100),
        )


def test_staging_revalidates_source_and_never_overwrites(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    packet_root = tmp_path / "packet"
    _build(root, packet_root)
    destination = tmp_path / "staging"
    create_patch_staging_area(
        packet_root=packet_root,
        staging_root=destination,
        repo_root=root,
        minimum_free_bytes=0,
    )
    with pytest.raises(RepositoryPacketError, match="already exists"):
        create_patch_staging_area(
            packet_root=packet_root,
            staging_root=destination,
            repo_root=root,
            minimum_free_bytes=0,
        )

    shutil.rmtree(destination)
    (root / "src" / "worker.py").write_text("dirty = True\n", encoding="utf-8")
    with pytest.raises(RepositoryPacketError, match="uncommitted"):
        create_patch_staging_area(
            packet_root=packet_root,
            staging_root=destination,
            repo_root=root,
            minimum_free_bytes=0,
        )


def test_manifest_tampering_and_extra_manifest_fields_fail_closed(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    packet_root = tmp_path / "packet"
    _build(root, packet_root)
    manifest_path = packet_root / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tracker_item_ids"] = ["MF-P6-99.99"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RepositoryPacketError, match="self-hash mismatch"):
        verify_repository_packet(packet_root)


def test_semantically_resealed_authority_and_secret_path_tampering_fails(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    packet_root = tmp_path / "packet"
    _build(root, packet_root)
    manifest_path = packet_root / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["authority"]["git"] = True
    manifest["packet_sha256"] = "0" * 64
    manifest["packet_sha256"] = hashlib.sha256(
        json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RepositoryPacketError, match="authority"):
        verify_repository_packet(packet_root)


def test_rejects_packet_or_staging_roots_inside_repository(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    with pytest.raises(RepositoryPacketError, match="outside"):
        _build(root, root / "packet")

    packet_root = tmp_path / "packet"
    _build(root, packet_root)
    with pytest.raises(RepositoryPacketError, match="outside"):
        create_patch_staging_area(
            packet_root=packet_root,
            staging_root=root / "staging",
            repo_root=root,
            minimum_free_bytes=0,
        )
