"""Locate the sibling MaskFactory producer repo and make its contracts importable.

This isolated consumer lives OUTSIDE the producer repo. It consumes the producer
purely through the published ``maskfactory`` package (contract surface plus the
producer-side conformance/journal/circuit/qualification builders). It never
imports from, writes to, or otherwise touches the dirty ``C:\\Comfy_UI_Main``
Wave64 tree.

Resolution order for the producer root:
  1. ``$MASKFACTORY_PRODUCER_ROOT`` if set and valid,
  2. the default sibling path ``C:\\Comfy_UI_Main_Masking``,
  3. whatever an already-installed ``maskfactory`` package resolves to.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DEFAULT_PRODUCER_ROOT = Path(r"C:\Comfy_UI_Main_Masking")


def producer_root() -> Path:
    env = os.environ.get("MASKFACTORY_PRODUCER_ROOT")
    if env:
        candidate = Path(env)
        if (candidate / "src" / "maskfactory").is_dir():
            return candidate
    if (DEFAULT_PRODUCER_ROOT / "src" / "maskfactory").is_dir():
        return DEFAULT_PRODUCER_ROOT
    return DEFAULT_PRODUCER_ROOT


def ensure_producer_importable() -> Path:
    """Guarantee ``import maskfactory`` works; return the resolved producer root."""
    root = producer_root()
    src = root / "src"
    try:
        import maskfactory  # noqa: F401  (probe an existing install first)

        return root
    except ImportError:
        if src.is_dir() and str(src) not in sys.path:
            sys.path.insert(0, str(src))
        import maskfactory  # noqa: F401  (re-raise if still unavailable)

        return root


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    value = out.stdout.strip()
    return value or None


def producer_git_head(root: Path | None = None) -> str | None:
    root = root or producer_root()
    value = (_git(root, "rev-parse", "HEAD") or "").lower()
    return value if len(value) == 40 and all(c in "0123456789abcdef" for c in value) else None


def producer_worktree_dirty(root: Path | None = None) -> bool | None:
    """True if the live producer working tree has uncommitted changes.

    Recorded for transparency only. The bridge adopts a *pinned published
    release snapshot*, so live worktree churn does not gate adoption; this field
    simply keeps the isolated-consumer evidence honest about the producer state.
    """
    root = root or producer_root()
    status = _git(root, "status", "--porcelain")
    if status is None:
        return None
    return bool(status.strip())
