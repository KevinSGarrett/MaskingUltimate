from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from maskfactory.providers.checkpoint_install import (
    CheckpointInstallError,
    install_checkpoint,
)


class _Response:
    def __init__(self, payload: bytes, status: int) -> None:
        self.payload = payload
        self.status_code = status
        self.headers = {}
        self.closed = False

    def iter_content(self, chunk_size: int):
        for offset in range(0, len(self.payload), max(1, chunk_size // 2)):
            yield self.payload[offset : offset + max(1, chunk_size // 2)]

    def close(self) -> None:
        self.closed = True


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_atomic_install_and_idempotent_reuse_redact_credentials(tmp_path: Path) -> None:
    payload = b"official-checkpoint-fixture"
    seen = {}

    def requester(url, headers):
        seen.update({"url": url, "headers": dict(headers)})
        return _Response(payload, 200)

    target = tmp_path / "models/checkpoint.pt"
    result = install_checkpoint(
        url="https://huggingface.co/owner/repo/resolve/revision/checkpoint.pt",
        destination=target,
        expected_size=len(payload),
        expected_sha256=_sha(payload),
        token="secret-never-output",
        requester=requester,
        reserve_bytes=0,
    )
    assert target.read_bytes() == payload
    assert not target.with_name(".checkpoint.pt.part").exists()
    assert result["credential_redacted"] is True
    assert "secret" not in str(result)
    assert seen["headers"]["Authorization"] == "Bearer secret-never-output"
    reused = install_checkpoint(
        url=seen["url"],
        destination=target,
        expected_size=len(payload),
        expected_sha256=_sha(payload),
        token="different-secret",
        requester=lambda *_: pytest.fail("reused install must not request network"),
        reserve_bytes=0,
    )
    assert reused["reused_existing"] is True and reused["downloaded_bytes"] == 0


def test_range_resume_requires_206_and_hashes_complete_file(tmp_path: Path) -> None:
    payload = b"0123456789abcdef"
    target = tmp_path / "checkpoint.pt"
    partial = target.with_name(".checkpoint.pt.part")
    partial.write_bytes(payload[:7])
    observed_headers = {}

    def requester(_url, headers):
        observed_headers.update(headers)
        return _Response(payload[7:], 206)

    result = install_checkpoint(
        url="https://huggingface.co/owner/repo/resolve/revision/checkpoint.pt",
        destination=target,
        expected_size=len(payload),
        expected_sha256=_sha(payload),
        token="secret",
        requester=requester,
        reserve_bytes=0,
    )
    assert observed_headers["Range"] == "bytes=7-"
    assert result["resumed_from_bytes"] == 7
    assert result["downloaded_bytes"] == len(payload) - 7
    assert target.read_bytes() == payload


def test_server_ignoring_range_restarts_partial_safely(tmp_path: Path) -> None:
    payload = b"complete-response"
    target = tmp_path / "checkpoint.pt"
    target.with_name(".checkpoint.pt.part").write_bytes(b"stale-prefix")
    result = install_checkpoint(
        url="https://huggingface.co/owner/repo/resolve/revision/checkpoint.pt",
        destination=target,
        expected_size=len(payload),
        expected_sha256=_sha(payload),
        token="secret",
        requester=lambda *_: _Response(payload, 200),
        reserve_bytes=0,
    )
    assert result["resumed_from_bytes"] == 0
    assert target.read_bytes() == payload


@pytest.mark.parametrize(
    ("payload", "expected_size", "expected_sha", "message"),
    [
        (b"short", 6, _sha(b"short!"), "size mismatch"),
        (b"wrong", 5, _sha(b"right"), "hash mismatch"),
    ],
)
def test_identity_mismatch_never_promotes(
    tmp_path: Path,
    payload: bytes,
    expected_size: int,
    expected_sha: str,
    message: str,
) -> None:
    target = tmp_path / "checkpoint.pt"
    with pytest.raises(CheckpointInstallError, match=message):
        install_checkpoint(
            url="https://huggingface.co/owner/repo/resolve/revision/checkpoint.pt",
            destination=target,
            expected_size=expected_size,
            expected_sha256=expected_sha,
            token="secret",
            requester=lambda *_: _Response(payload, 200),
            reserve_bytes=0,
        )
    assert not target.exists()


def test_existing_wrong_identity_and_invalid_request_fail_before_network(tmp_path: Path) -> None:
    target = tmp_path / "checkpoint.pt"
    target.write_bytes(b"wrong")
    with pytest.raises(CheckpointInstallError, match="existing checkpoint identity"):
        install_checkpoint(
            url="https://huggingface.co/owner/repo/resolve/revision/checkpoint.pt",
            destination=target,
            expected_size=5,
            expected_sha256=_sha(b"right"),
            token="secret",
            requester=lambda *_: pytest.fail("must fail before network"),
            reserve_bytes=0,
        )
    with pytest.raises(CheckpointInstallError, match="request is invalid"):
        install_checkpoint(
            url="http://example.invalid/checkpoint.pt",
            destination=tmp_path / "other.pt",
            expected_size=1,
            expected_sha256="0" * 64,
            token="secret",
            reserve_bytes=0,
        )
