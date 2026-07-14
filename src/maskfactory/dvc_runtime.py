"""Resolve and execute the pinned DVC runtime without depending on shell activation."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[2]


class DvcRuntimeError(RuntimeError):
    """The governed DVC executable or repository runtime is unavailable."""


def resolve_dvc_executable(*, root: Path = ROOT) -> Path:
    """Prefer an explicit executable, then PATH, then the workspace-local pinned runtime."""
    explicit = os.environ.get("MASKFACTORY_DVC_EXE")
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise DvcRuntimeError(f"MASKFACTORY_DVC_EXE does not exist: {path}")
        return path
    discovered = shutil.which("dvc")
    if discovered:
        return Path(discovered).resolve()
    root = Path(root).resolve()
    candidates = (
        root / ".tools/dvc-venv/Scripts/dvc.exe",
        root / ".tools/dvc-venv/bin/dvc",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise DvcRuntimeError(
        "DVC runtime unavailable; install env/requirements.lock.txt or bootstrap .tools/dvc-venv"
    )


def run_dvc(
    arguments: Sequence[str],
    *,
    root: Path = ROOT,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    """Run DVC from the repository root with repository-local config/cache isolation."""
    root = Path(root).resolve()
    executable = resolve_dvc_executable(root=root)
    dvc_dir = root / ".dvc"
    if not (dvc_dir / "config").is_file():
        raise DvcRuntimeError(f"DVC repository is not initialized: {root}")
    runtime_config = dvc_dir / "runtime_config"
    site_cache = dvc_dir / "site-cache"
    for directory in (
        runtime_config / "system",
        runtime_config / "global",
        site_cache / "repo",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "DVC_NO_ANALYTICS": "true",
            "DVC_SYSTEM_CONFIG_DIR": str(runtime_config / "system"),
            "DVC_GLOBAL_CONFIG_DIR": str(runtime_config / "global"),
            "DVC_SITE_CACHE_DIR": str(site_cache),
        }
    )
    try:
        return subprocess.run(
            [str(executable), *arguments],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DvcRuntimeError(f"DVC command failed to execute: {exc}") from exc
