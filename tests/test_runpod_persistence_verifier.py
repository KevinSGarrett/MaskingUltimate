from __future__ import annotations

from pathlib import Path

import pytest
from tools.verify_runpod_persistence import build_evidence, load_env_value


def _pod() -> dict:
    return {
        "id": "pod-private",
        "desiredStatus": "RUNNING",
        "imageName": "private/image:tag",
        "containerDiskInGb": 20,
        "volumeInGb": 0,
        "volumeMountPath": "/workspace",
        "networkVolumeId": "volume-private",
    }


def _volume() -> dict:
    return {
        "id": "volume-private",
        "name": "private-name",
        "dataCenterId": "private-dc",
        "size": 600,
    }


def _remote() -> dict:
    return {
        "workspace": {
            "total_bytes": 600_000_000_000,
            "free_bytes": 400_000_000_000,
            "device": 2,
        },
        "container_root": {
            "total_bytes": 20_000_000_000,
            "free_bytes": 10_000_000_000,
            "device": 1,
        },
        "mount": {
            "target": "/workspace",
            "fstype": "nfs4",
            "source_sha256": "a" * 64,
            "source_present": True,
        },
        "sentinel": {
            "path": "/workspace/maskfactory/runtime_artifacts/.maskfactory_persistence_probe",
            "sha256": "b" * 64,
            "write_pid": 10,
            "read_pid": 11,
            "readback_matches": True,
            "distinct_processes": True,
        },
        "paths_env": {"exists": True, "sha256": "c" * 64},
        "gpu": {"name": "RTX 6000 Ada", "driver_version": "1", "memory_mib": 49140},
    }


def test_build_evidence_passes_and_redacts_api_identity() -> None:
    evidence = build_evidence(
        pod=_pod(),
        network_volume=_volume(),
        remote=_remote(),
        source_evidence=None,
    )

    assert evidence["status"] == "RUNTIME_PASS_BOUNDED"
    assert all(evidence["checks"].values())
    rendered = str(evidence)
    for private in ("pod-private", "volume-private", "private-name", "private-dc"):
        assert private not in rendered


def test_build_evidence_blocks_root_overlay_or_failed_readback() -> None:
    remote = _remote()
    remote["workspace"]["device"] = remote["container_root"]["device"]
    remote["sentinel"]["readback_matches"] = False

    evidence = build_evidence(
        pod=_pod(),
        network_volume=_volume(),
        remote=remote,
        source_evidence=None,
    )

    assert evidence["status"] == "RUNTIME_BLOCKED"
    assert evidence["checks"]["workspace_is_distinct_device_from_container_root"] is False
    assert evidence["checks"]["sentinel_readback_matches"] is False


def test_load_env_value_supports_colon_and_equals(tmp_path: Path) -> None:
    colon = tmp_path / "colon.env"
    equals = tmp_path / "equals.env"
    colon.write_text('RUNPOD_API_KEY: "colon-value"\n', encoding="utf-8")
    equals.write_text("RUNPOD_API_KEY=equals-value\n", encoding="utf-8")

    assert load_env_value(colon, "RUNPOD_API_KEY") == "colon-value"
    assert load_env_value(equals, "RUNPOD_API_KEY") == "equals-value"


def test_load_env_value_refuses_missing_secret(tmp_path: Path) -> None:
    env = tmp_path / "missing.env"
    env.write_text("OTHER=value\n", encoding="utf-8")

    with pytest.raises(ValueError, match="RUNPOD_API_KEY not found"):
        load_env_value(env, "RUNPOD_API_KEY")
