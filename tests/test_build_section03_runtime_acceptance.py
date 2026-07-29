from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.build_section03_runtime_acceptance import (
    RuntimeAcceptanceError,
    validate_lifecycle,
)
from tools.build_test_baseline_evidence import canonical_sha256, sha256_file


def _write_lifecycle(tmp_path: Path) -> Path:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    artifacts = {}
    for index in range(5):
        target = artifact_root / f"artifact-{index}"
        target.write_bytes(f"payload-{index}".encode())
        artifacts[target.name] = {
            "bytes": target.stat().st_size,
            "sha256": sha256_file(target),
        }
    document = {
        "schema_version": "maskfactory.service_lifecycle_evidence.v1",
        "result": "PASS",
        "item_id": "MF-P6-20.04",
        "source": {"commit": "a" * 40, "origin_main": "a" * 40, "status_rows": 0},
        "clean_export": {"build_exit_code": 0, "install_exit_code": 0},
        "artifact_root": str(artifact_root),
        "artifacts": artifacts,
        "routes": {
            "health": {"http_status": 200, "body": {"status": "ok"}},
            "models": {"http_status": 200, "verified_model_count": 17, "champion_count": 0},
            "predict_without_champions": {
                "http_status": 503,
                "body": {"detail": "champion prediction provider is not configured"},
            },
        },
        "process": {"returncode": 0, "post_shutdown_leaked_pids": []},
        "network": {"host": "127.0.0.1", "post_shutdown_open": False},
        "resources": {
            "ports_leaked": 0,
            "processes_leaked": 0,
            "reservations_created": 0,
            "leases_created": 0,
            "gpu_work_performed": False,
            "gpu_compute_before": {"rows": []},
            "gpu_compute_after": {"rows": []},
        },
        "shutdown": {"runtime_final_health": {"status": "not_started"}},
        "persistent_restore": {
            "status": "PASS",
            "prior_receipt": {"pod_id": "pod-a", "network_volume_id": "volume-a"},
            "replacement_receipt": {
                "pod_id": "pod-b",
                "network_volume_id": "volume-a",
                "result_checks": 14,
            },
        },
    }
    document["self_sha256"] = canonical_sha256(document)
    path = tmp_path / "service_lifecycle_evidence.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_validate_lifecycle_accepts_exact_bounded_proof(tmp_path: Path) -> None:
    assert validate_lifecycle(_write_lifecycle(tmp_path))["result"] == "PASS"


def test_validate_lifecycle_rejects_artifact_drift(tmp_path: Path) -> None:
    path = _write_lifecycle(tmp_path)
    (tmp_path / "artifacts/artifact-2").write_bytes(b"drift")
    with pytest.raises(RuntimeAcceptanceError, match="artifact size mismatch"):
        validate_lifecycle(path)


def test_validate_lifecycle_rejects_gpu_work(tmp_path: Path) -> None:
    path = _write_lifecycle(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["resources"]["gpu_work_performed"] = True
    document["self_sha256"] = canonical_sha256(document)
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RuntimeAcceptanceError, match="unleased GPU work"):
        validate_lifecycle(path)


def test_validate_lifecycle_rejects_same_pod_restore(tmp_path: Path) -> None:
    path = _write_lifecycle(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["persistent_restore"]["replacement_receipt"]["pod_id"] = "pod-a"
    document["self_sha256"] = canonical_sha256(document)
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RuntimeAcceptanceError, match="distinct Pod"):
        validate_lifecycle(path)
