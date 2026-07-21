from __future__ import annotations

import copy
from pathlib import Path

import pytest

from maskfactory.providers.meta_checkpoint_access import (
    PROBE_AUTHORITY,
    MetaCheckpointAccessError,
    load_meta_checkpoint_targets,
    probe_meta_checkpoint_access,
    verify_meta_checkpoint_access_probe,
)


def test_governed_targets_cover_exact_official_checkpoint_files() -> None:
    targets = load_meta_checkpoint_targets()
    assert [(target.provider, target.repository) for target in targets] == [
        ("sam3_1", "facebook/sam3.1"),
        ("sam3d_body", "facebook/sam-3d-body-dinov3"),
    ]
    assert targets[0].files == ("sam3.1_multiplex.pt",)
    assert targets[1].files == ("model.ckpt", "model_config.yaml", "assets/mhr_model.pt")
    assert all(len(target.revision) == 40 for target in targets)


def test_pending_probe_redacts_credential_and_never_downloads() -> None:
    calls = []

    def requester(url, headers):
        calls.append((url, dict(headers)))
        return 401, {}, None

    document = probe_meta_checkpoint_access(
        token="secret-token",
        requester=requester,
        observed_at="2026-07-16T00:20:00Z",
    )
    summary = verify_meta_checkpoint_access_probe(document)

    assert summary["result"] == "human_gate_pending"
    assert summary["provider_count"] == 2 and summary["file_count"] == 4
    assert document["credential_present"] is True
    assert document["credential_redacted"] is True
    assert document["downloaded_bytes"] == 0
    assert document["authority"] == PROBE_AUTHORITY
    assert "secret-token" not in str(document)
    assert len(calls) == 4
    assert all(headers == {"Authorization": "Bearer secret-token"} for _, headers in calls)
    assert all("/resolve/" in url for url, _ in calls)


def test_accessible_and_transport_failure_results_are_distinct() -> None:
    accessible = probe_meta_checkpoint_access(
        token=None,
        requester=lambda *_args: (302, {"Content-Length": "123"}, None),
        observed_at="2026-07-16T00:20:00Z",
    )
    failed = probe_meta_checkpoint_access(
        token=None,
        requester=lambda *_args: (0, {}, "Timeout"),
        observed_at="2026-07-16T00:20:00Z",
    )

    assert verify_meta_checkpoint_access_probe(accessible)["result"] == "access_ready"
    assert verify_meta_checkpoint_access_probe(failed)["result"] == "probe_error"
    assert all(
        item["content_length"] == 123
        for provider in accessible["providers"]
        for item in provider["files"]
    )


def test_probe_tamper_and_registry_drift_fail_closed(tmp_path: Path) -> None:
    document = probe_meta_checkpoint_access(
        token=None,
        requester=lambda *_args: (401, {}, None),
        observed_at="2026-07-16T00:20:00Z",
    )
    tampered = copy.deepcopy(document)
    tampered["downloaded_bytes"] = 1
    with pytest.raises(MetaCheckpointAccessError, match="hash mismatch"):
        verify_meta_checkpoint_access_probe(tampered)

    (tmp_path / "env").mkdir()
    (tmp_path / "configs").mkdir()
    (tmp_path / "env/sam31_runtime.lock.json").write_text(
        '{"provider":"foreign","checkpoint":{}}', encoding="utf-8"
    )
    (tmp_path / "configs/external_sources.yaml").write_text("providers: {}\n", encoding="utf-8")
    with pytest.raises(MetaCheckpointAccessError, match="SAM 3.1 gate identity drifted"):
        load_meta_checkpoint_targets(tmp_path)
