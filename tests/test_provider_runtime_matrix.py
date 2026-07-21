import copy
import hashlib
import json
from pathlib import Path

import pytest

from maskfactory.providers.runtime_matrix import RuntimeMatrixError, verify_runtime_matrix

MATRIX = Path("env/provider_runtime_matrix.json")


def _write_matrix(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "provider_runtime_matrix.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def _rehash(document: dict) -> None:
    payload = {key: value for key, value in document.items() if key != "manifest_sha256"}
    document["manifest_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_live_runtime_matrix_is_hash_exact_and_explicit_about_pending_runtimes():
    result = verify_runtime_matrix()
    assert result["provider_count"] == 8
    assert result["qualified_runtime_count"] == 6
    assert result["human_gated_runtime_count"] == 0
    assert result["pending_runtime_count"] == 2
    assert result["artifact_count"] == 18
    assert result["core_torch"] == "2.11.0+cu128"
    assert result["status"] == "pass_with_explicit_pending_runtimes"


def test_matrix_rejects_manifest_edit_even_when_artifacts_are_unchanged(tmp_path: Path):
    document = json.loads(MATRIX.read_text(encoding="utf-8"))
    document["runtimes"][0]["isolation_boundary"] = "mutated"
    with pytest.raises(RuntimeMatrixError, match="runtime_matrix_manifest_hash_mismatch"):
        verify_runtime_matrix(_write_matrix(tmp_path, document))


def test_matrix_rejects_pending_checkpoint_claim_as_qualified(tmp_path: Path):
    document = json.loads(MATRIX.read_text(encoding="utf-8"))
    row = next(row for row in document["runtimes"] if row["provider"] == "sam3_1")
    row["status"] = "live_smoke_passed"
    row["checkpoint_status"] = "installed"
    row["smoke_status"] = "pass"
    _rehash(document)
    with pytest.raises(RuntimeMatrixError, match="runtime_expected_pending:sam3_1"):
        verify_runtime_matrix(_write_matrix(tmp_path, document), enforce_locked_hash=False)


def test_matrix_rejects_artifact_hash_drift(tmp_path: Path):
    document = copy.deepcopy(json.loads(MATRIX.read_text(encoding="utf-8")))
    document["runtimes"][0]["artifacts"][0]["sha256"] = "f" * 64
    _rehash(document)
    with pytest.raises(RuntimeMatrixError, match="runtime_artifact_hash_mismatch"):
        verify_runtime_matrix(_write_matrix(tmp_path, document), enforce_locked_hash=False)
