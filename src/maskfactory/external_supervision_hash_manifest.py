"""Deterministic full-file hash manifests for external-supervision sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from .external_supervision_evidence import seal_payload


class SourceHashManifestError(ValueError):
    """The source tree cannot be represented as a safe deterministic manifest."""


def build_source_hash_manifest(
    *,
    source: str,
    source_root: Path,
    paths: Iterable[Path] | None = None,
) -> dict[str, Any]:
    """Hash every selected regular file under a source root in stable path order."""

    root = Path(source_root).resolve(strict=True)
    if not root.is_dir():
        raise SourceHashManifestError("source root must be a directory")
    full_tree = paths is None
    candidates = list(paths) if paths is not None else list(root.rglob("*"))
    resolved: list[tuple[str, Path]] = []
    casefolded: set[str] = set()
    for candidate in candidates:
        path = Path(candidate)
        if not path.is_absolute():
            path = root / path
        if path.is_symlink():
            raise SourceHashManifestError(f"symbolic links are forbidden: {path}")
        try:
            actual = path.resolve(strict=True)
            relative = actual.relative_to(root).as_posix()
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise SourceHashManifestError(f"path escaped or is unreadable: {path}") from exc
        if actual.is_dir():
            continue
        if not actual.is_file():
            raise SourceHashManifestError(f"non-regular source entry is forbidden: {path}")
        folded = relative.casefold()
        if folded in casefolded:
            raise SourceHashManifestError(f"case-insensitive path collision: {relative}")
        casefolded.add(folded)
        resolved.append((relative, actual))
    resolved.sort(key=lambda item: item[0].encode("utf-8"))
    if not resolved:
        raise SourceHashManifestError("source manifest cannot be empty")

    records: list[dict[str, Any]] = []
    total_bytes = 0
    for relative, path in resolved:
        before = path.stat()
        size = before.st_size
        sha256 = _hash_file(path)
        after = path.stat()
        if _stat_identity(before) != _stat_identity(after):
            raise SourceHashManifestError(f"source file changed while hashing: {relative}")
        total_bytes += size
        records.append(
            {
                "path": relative,
                "size": size,
                "sha256": sha256,
            }
        )
    if full_tree and tuple(relative for relative, _ in resolved) != _current_file_paths(root):
        raise SourceHashManifestError("source tree changed while building the manifest")
    manifest: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "external_supervision_source_hash_manifest",
        "source": source,
        "gate": "source_hash_manifested",
        "status": "PASS",
        "path_encoding": "utf-8-posix-relative",
        "hash_algorithm": "sha256",
        "file_count": len(records),
        "total_bytes": total_bytes,
        "files": records,
    }
    manifest["seal_sha256"] = seal_payload(manifest)
    return manifest


def publish_source_hash_manifest(manifest: dict[str, Any], output_path: Path) -> str:
    """Atomically publish a manifest and return its file SHA-256."""

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")
    if output.exists():
        existing = output.read_bytes()
        if existing != payload:
            raise SourceHashManifestError("immutable manifest path already has different bytes")
        return hashlib.sha256(existing).hexdigest()
    temporary = output.with_name(f".{output.name}.{os.getpid()}.partial")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return hashlib.sha256(payload).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _current_file_paths(root: Path) -> tuple[str, ...]:
    paths: list[str] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise SourceHashManifestError(f"symbolic links are forbidden: {path}")
        try:
            actual = path.resolve(strict=True)
            relative = actual.relative_to(root).as_posix()
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise SourceHashManifestError(f"source tree changed while scanning: {path}") from exc
        if actual.is_file():
            paths.append(relative)
        elif not actual.is_dir():
            raise SourceHashManifestError(f"non-regular source entry is forbidden: {path}")
    return tuple(sorted(paths, key=lambda value: value.encode("utf-8")))


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = build_source_hash_manifest(source=args.source, source_root=args.source_root)
    manifest_file_sha256 = publish_source_hash_manifest(manifest, args.output)
    print(
        json.dumps(
            {
                "status": "PASS",
                "source": args.source,
                "file_count": manifest["file_count"],
                "total_bytes": manifest["total_bytes"],
                "manifest_path": str(args.output.resolve()),
                "manifest_file_sha256": manifest_file_sha256,
                "manifest_seal_sha256": manifest["seal_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SourceHashManifestError",
    "build_source_hash_manifest",
    "publish_source_hash_manifest",
]
