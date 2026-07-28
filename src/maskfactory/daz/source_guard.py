"""Prevent DAZ source assets, geometry, textures, and installers from entering Git."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Iterable

PROHIBITED_EXTENSIONS = frozenset(
    {
        ".daz",
        ".dazip",
        ".dbz",
        ".dsf",
        ".duf",
        ".exr",
        ".fbx",
        ".glb",
        ".gltf",
        ".hdr",
        ".hdri",
        ".ies",
        ".obj",
        ".tif",
        ".tiff",
    }
)
APPROVED_FIXTURE_PREFIX = PurePosixPath("tests/fixtures/daz")
MAXIMUM_FIXTURE_BYTES = 128 * 1024


def find_prohibited_source_assets(
    paths: Iterable[str | Path], *, workspace: Path
) -> tuple[str, ...]:
    """Return deterministic violations without reading non-candidate file contents."""
    root = Path(workspace).resolve()
    violations: list[str] = []
    for raw in paths:
        portable = PurePosixPath(str(raw).replace("\\", "/"))
        if portable.suffix.casefold() not in PROHIBITED_EXTENSIONS:
            continue
        local = root.joinpath(*portable.parts)
        if _is_approved_fixture(portable, local):
            continue
        violations.append(portable.as_posix())
    return tuple(sorted(set(violations)))


def _is_approved_fixture(portable: PurePosixPath, local: Path) -> bool:
    try:
        portable.relative_to(APPROVED_FIXTURE_PREFIX)
    except ValueError:
        return False
    return local.is_file() and local.stat().st_size <= MAXIMUM_FIXTURE_BYTES


__all__ = ["PROHIBITED_EXTENSIONS", "find_prohibited_source_assets"]
