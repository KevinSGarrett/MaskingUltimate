"""Atomic, resumable, hash-verified installation for governed checkpoints."""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any, Protocol

import requests


class CheckpointInstallError(RuntimeError):
    """A checkpoint install violated identity, capacity, or transfer invariants."""


class StreamResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]

    def iter_content(self, chunk_size: int) -> Iterator[bytes]: ...

    def close(self) -> None: ...


Requester = Callable[[str, Mapping[str, str]], StreamResponse]
Progress = Callable[[int, int], None]


def install_checkpoint(
    *,
    url: str,
    destination: Path,
    expected_size: int,
    expected_sha256: str,
    token: str,
    requester: Requester | None = None,
    progress: Progress | None = None,
    reserve_bytes: int = 2 * 1024**3,
) -> dict[str, Any]:
    """Install one immutable checkpoint without exposing credentials or partial files."""

    target = Path(destination)
    if (
        not url.startswith("https://huggingface.co/")
        or not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or expected_size <= 0
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
        or not isinstance(token, str)
        or not token.strip()
        or not isinstance(reserve_bytes, int)
        or reserve_bytes < 0
    ):
        raise CheckpointInstallError("checkpoint install request is invalid")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        size, digest = _file_identity(target)
        if size != expected_size or digest != expected_sha256:
            raise CheckpointInstallError("existing checkpoint identity does not match the lock")
        return _result(target, size, digest, downloaded_bytes=0, resumed_from=0, reused=True)
    partial = target.with_name(f".{target.name}.part")
    partial_size = partial.stat().st_size if partial.exists() else 0
    if partial_size > expected_size:
        raise CheckpointInstallError("partial checkpoint exceeds the locked size")
    required = expected_size - partial_size + reserve_bytes
    free = shutil.disk_usage(target.parent).free
    if free < required:
        raise CheckpointInstallError(
            f"insufficient checkpoint capacity: free={free} required={required}"
        )
    headers = {"Authorization": f"Bearer {token}"}
    if partial_size:
        headers["Range"] = f"bytes={partial_size}-"
    response = (requester or _request)(url, headers)
    try:
        status = int(response.status_code)
        if partial_size and status == 206:
            mode = "ab"
            resumed_from = partial_size
        elif status == 200:
            mode = "wb"
            resumed_from = 0
            partial_size = 0
        else:
            raise CheckpointInstallError(f"checkpoint transfer returned HTTP {status}")
        written = partial_size
        with partial.open(mode) as handle:
            for chunk in response.iter_content(chunk_size=8 * 1024**2):
                if not chunk:
                    continue
                handle.write(chunk)
                written += len(chunk)
                if written > expected_size:
                    raise CheckpointInstallError("checkpoint transfer exceeded the locked size")
                if progress is not None:
                    progress(written, expected_size)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        response.close()
    size, digest = _file_identity(partial)
    if size != expected_size:
        raise CheckpointInstallError(
            f"checkpoint size mismatch: observed={size} expected={expected_size}"
        )
    if digest != expected_sha256:
        raise CheckpointInstallError(
            f"checkpoint hash mismatch: observed={digest} expected={expected_sha256}"
        )
    os.replace(partial, target)
    return _result(
        target,
        size,
        digest,
        downloaded_bytes=size - resumed_from,
        resumed_from=resumed_from,
        reused=False,
    )


def _request(url: str, headers: Mapping[str, str]) -> StreamResponse:
    try:
        return requests.get(
            url,
            headers=dict(headers),
            allow_redirects=True,
            stream=True,
            timeout=(30, 120),
        )
    except requests.RequestException as exc:
        raise CheckpointInstallError(f"checkpoint transport failed: {type(exc).__name__}") from exc


def _file_identity(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024**2), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _result(
    path: Path,
    size: int,
    digest: str,
    *,
    downloaded_bytes: int,
    resumed_from: int,
    reused: bool,
) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "size_bytes": size,
        "sha256": digest,
        "downloaded_bytes": downloaded_bytes,
        "resumed_from_bytes": resumed_from,
        "reused_existing": reused,
        "atomic_promotion": True,
        "credential_redacted": True,
    }


__all__ = ["CheckpointInstallError", "install_checkpoint"]
