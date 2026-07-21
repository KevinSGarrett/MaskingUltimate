"""Streaming SHA-256 primitives for artifacts and manifest file maps."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_file_map(root: Path, paths: Iterable[Path]) -> dict[str, str]:
    """Hash explicit files under root and return canonical POSIX-relative keys."""
    base = Path(root).resolve()
    output = {}
    for path in sorted((Path(item).resolve() for item in paths), key=lambda item: item.as_posix()):
        try:
            relative = path.relative_to(base).as_posix()
        except ValueError as exc:
            raise ValueError(f"file-map path escapes root: {path}") from exc
        if relative in output:
            raise ValueError(f"duplicate file-map path: {relative}")
        if not path.is_file():
            raise FileNotFoundError(path)
        output[relative] = sha256_file(path)
    return output


def verify_file_map(root: Path, expected: Mapping[str, str]) -> tuple[str, ...]:
    """Return stable mismatch messages without mutating the package."""
    base = Path(root).resolve()
    issues = []
    for relative, digest in sorted(expected.items()):
        path = (base / relative).resolve()
        try:
            path.relative_to(base)
        except ValueError:
            issues.append(f"path_escape:{relative}")
            continue
        if not path.is_file():
            issues.append(f"missing:{relative}")
        elif sha256_file(path) != digest:
            issues.append(f"hash_mismatch:{relative}")
    return tuple(issues)


__all__ = ["sha256_bytes", "sha256_file", "sha256_file_map", "verify_file_map"]
