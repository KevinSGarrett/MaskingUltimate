from __future__ import annotations

from pathlib import Path

import pytest
from tools.audit_runpod_visual_runtime import (
    RunPodVisualAuditError,
    build_result,
    load_env_value,
)


def _remote() -> dict:
    return {
        "gpu": {
            "name": "NVIDIA RTX 6000 Ada Generation",
            "driver_version": "550.127.05",
            "memory_total_mib": 49140,
            "memory_used_mib": 100,
            "memory_free_mib": 49040,
            "utilization_percent": 0,
            "compute_apps": [
                {
                    "pid": 123,
                    "process_name": "[Not Found]",
                    "used_memory_mib": 640,
                    "pid_alive": False,
                }
            ],
        },
        "workspace": {
            "total_bytes": 700_000_000_000,
            "free_bytes": 650_000_000_000,
            "paths_env_exists": True,
            "bound_variable_names": ["HF_HOME"],
        },
        "persistent_directories": {},
        "huggingface_model_cache_names": [],
        "packages": {},
        "visual_setup_job": {
            "exists": True,
            "pid": 456,
            "pid_alive": True,
            "process_tree": [
                {
                    "pid": 456,
                    "ppid": 1,
                    "comm": "bash",
                    "etime": "00:10",
                    "cpu_percent": 0.0,
                    "memory_percent": 0.0,
                    "state": "S",
                }
            ],
            "state": {"stage": "qwen_download", "status": "running"},
            "inventory": None,
            "stdout": {"exists": True, "bytes": 1, "sha256": "a" * 64},
            "stderr": {"exists": True, "bytes": 0, "sha256": "b" * 64},
            "script": {"exists": True, "bytes": 1, "sha256": "c" * 64},
        },
    }


def test_env_loader_accepts_colon_without_exposing_value(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("RUNPOD_API_KEY: secret-value\n", encoding="utf-8")
    assert load_env_value(path, "RUNPOD_API_KEY") == "secret-value"
    with pytest.raises(RunPodVisualAuditError, match="MISSING"):
        load_env_value(path, "MISSING")


def test_result_hashes_identifiers_and_never_serializes_endpoint_or_key() -> None:
    pod = {
        "id": "pod-secret-id",
        "desiredStatus": "RUNNING",
        "networkVolumeId": "volume-secret-id",
        "volumeMountPath": "/workspace",
        "publicIp": "192.0.2.44",
        "portMappings": {"22": 22022},
    }
    result = build_result(pod, _remote())
    serialized = str(result)

    assert all(result["checks"].values())
    assert "pod-secret-id" not in serialized
    assert "volume-secret-id" not in serialized
    assert "192.0.2.44" not in serialized
    assert "22022" not in serialized
