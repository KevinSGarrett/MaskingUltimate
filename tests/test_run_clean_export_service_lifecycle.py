from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from tools.run_clean_export_service_lifecycle import (
    LifecycleEvidenceError,
    canonical_sha256,
    validate_persistent_restore,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    prior_path = repo / "qa/live_verification/runpod_package_persistence_and_restore_20260722.json"
    replacement_root = (
        repo / "runtime_artifacts/runpod_package_pod_replacement_restore_20260725T205000Z"
    )
    descriptor = repo / "data/packages.dvc"
    prior_path.parent.mkdir(parents=True)
    replacement_root.mkdir(parents=True)
    descriptor.parent.mkdir(parents=True)
    descriptor.write_text("outs: []\n", encoding="utf-8")
    verifier = replacement_root / "verify_exact_package_restore.py"
    verifier.write_text("print('verified')\n", encoding="utf-8")
    prior = {
        "status": "RUNTIME_PASS_BOUNDED_PROCESS_RESTORE_POD_REPLACEMENT_OPEN",
        "platform": {"pod_id": "pod-a", "network_volume_id": "volume-a"},
    }
    prior_path.write_text(json.dumps(prior), encoding="utf-8")
    replacement = {
        "status": "RUNTIME_PASS_POD_REPLACEMENT_RESTORE",
        "prior_proof": {"sha256": _sha(prior_path)},
        "current_pod": {"id": "pod-b", "network_volume_id": "volume-a"},
        "exact_package": {
            "descriptor_sha256": _sha(descriptor),
            "restored_file_count": 15,
            "manifest_sha256": "a" * 64,
            "archive_sha256": "b" * 64,
            "chunk_count": 5,
        },
        "replay_verifier": {
            "sha256": _sha(verifier),
            "result": {"archive": True, "chunks": True},
        },
    }
    (replacement_root / "POD_REPLACEMENT_RESTORE_RECEIPT.json").write_text(
        json.dumps(replacement), encoding="utf-8"
    )
    return repo


def test_validate_persistent_restore_requires_distinct_pod_and_exact_bytes(tmp_path: Path) -> None:
    result = validate_persistent_restore(_fixture_repo(tmp_path))
    assert result["status"] == "PASS"
    assert result["replacement_receipt"]["result_checks"] == 2
    assert result["descriptor"]["restored_file_count"] == 15


def test_validate_persistent_restore_rejects_descriptor_drift(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    (repo / "data/packages.dvc").write_text("changed\n", encoding="utf-8")
    with pytest.raises(LifecycleEvidenceError, match="descriptor bytes differ"):
        validate_persistent_restore(repo)


def test_validate_persistent_restore_rejects_nonpassing_check(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    path = (
        repo
        / "runtime_artifacts/runpod_package_pod_replacement_restore_20260725T205000Z"
        / "POD_REPLACEMENT_RESTORE_RECEIPT.json"
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    document["replay_verifier"]["result"]["chunks"] = False
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(LifecycleEvidenceError, match="non-passing result"):
        validate_persistent_restore(repo)


def test_canonical_sha_excludes_only_self_hash() -> None:
    first = {"schema_version": "v1", "value": 3}
    sealed = {**first, "self_sha256": canonical_sha256(first)}
    assert canonical_sha256(sealed) == sealed["self_sha256"]
    sealed["value"] = 4
    assert canonical_sha256(sealed) != sealed["self_sha256"]
