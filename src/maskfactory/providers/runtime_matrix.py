"""Fail-closed verification for the frozen cross-provider runtime matrix."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

DEFAULT_MATRIX = Path("env/provider_runtime_matrix.json")
LOCKED_MATRIX_SHA256 = "9dbd1b41b7452d8180dd0dc5803bab5a5bf46bb1cb0b19bd77f3baa93ab7356a"
EXPECTED_PROVIDERS = {
    "maskfactory_core",
    "sam3_1",
    "sam3_litetext_s0",
    "qwen3_vl",
    "rfdetr",
    "eomt_dinov3",
    "rtm_pose",
    "sam3d_body",
}
CURRENT_HUMAN_GATES: set[str] = set()
CURRENT_PENDING = {
    "sam3_1": (
        "checkpoint_installed_smoke_pending",
        "installed",
        "not_run_wsl_filesystem_io_error",
    ),
    "sam3d_body": (
        "checkpoint_installed_runtime_pending",
        "installed",
        "not_run_wsl_filesystem_io_error",
    ),
}
QUALIFIED = "live_smoke_passed"
GATED = "source_only_human_gate"


class RuntimeMatrixError(ValueError):
    """The runtime matrix is incomplete, drifted, or overclaims qualification."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_runtime_matrix(
    matrix_path: Path = DEFAULT_MATRIX,
    *,
    workspace: Path = Path("."),
    enforce_locked_hash: bool = True,
) -> dict[str, Any]:
    """Verify exact provider coverage, artifact hashes, isolation, and honest gates."""
    matrix_path = Path(matrix_path)
    workspace = Path(workspace).resolve()
    document = json.loads(matrix_path.read_text(encoding="utf-8"))
    if document.get("schema_version") != "1.0.0":
        raise RuntimeMatrixError("runtime_matrix_schema_version_invalid")
    expected_hash = _canonical_sha256(
        {key: value for key, value in document.items() if key != "manifest_sha256"}
    )
    if document.get("manifest_sha256") != expected_hash:
        raise RuntimeMatrixError("runtime_matrix_manifest_hash_mismatch")
    if enforce_locked_hash and document.get("manifest_sha256") != LOCKED_MATRIX_SHA256:
        raise RuntimeMatrixError("runtime_matrix_locked_hash_mismatch")
    policy = document.get("policy")
    if not isinstance(policy, dict) or policy.get("core_torch") != "2.11.0+cu128":
        raise RuntimeMatrixError("runtime_matrix_core_policy_invalid")
    rows = document.get("runtimes")
    if not isinstance(rows, list):
        raise RuntimeMatrixError("runtime_matrix_rows_invalid")
    providers = [row.get("provider") for row in rows if isinstance(row, dict)]
    if len(providers) != len(set(providers)) or set(providers) != EXPECTED_PROVIDERS:
        raise RuntimeMatrixError("runtime_matrix_provider_coverage_invalid")
    qualified = 0
    gated = 0
    pending = 0
    artifact_count = 0
    for row in rows:
        provider = str(row["provider"])
        status = row.get("status")
        isolation = row.get("isolation_boundary")
        if not isinstance(isolation, str) or not isolation.strip():
            raise RuntimeMatrixError(f"runtime_isolation_missing:{provider}")
        if row.get("may_author_gold") is not False:
            raise RuntimeMatrixError(f"runtime_authority_overclaim:{provider}")
        if provider in CURRENT_HUMAN_GATES and status != GATED:
            raise RuntimeMatrixError(f"runtime_expected_human_gate:{provider}")
        if provider not in CURRENT_HUMAN_GATES and status == GATED:
            raise RuntimeMatrixError(f"runtime_unexpected_human_gate:{provider}")
        if provider in CURRENT_PENDING and status != CURRENT_PENDING[provider][0]:
            raise RuntimeMatrixError(f"runtime_expected_pending:{provider}")
        artifacts = row.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise RuntimeMatrixError(f"runtime_artifacts_missing:{provider}")
        kinds: set[str] = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict) or artifact.get("kind") not in {"lock", "evidence"}:
                raise RuntimeMatrixError(f"runtime_artifact_invalid:{provider}")
            relative = Path(str(artifact.get("path", "")))
            path = (workspace / relative).resolve()
            try:
                path.relative_to(workspace)
            except ValueError as exc:
                raise RuntimeMatrixError(f"runtime_artifact_path_escape:{provider}") from exc
            if not path.is_file():
                raise RuntimeMatrixError(
                    f"runtime_artifact_missing:{provider}:{relative.as_posix()}"
                )
            if _file_sha256(path) != artifact.get("sha256"):
                raise RuntimeMatrixError(
                    f"runtime_artifact_hash_mismatch:{provider}:{relative.as_posix()}"
                )
            kinds.add(str(artifact["kind"]))
            artifact_count += 1
        if "evidence" not in kinds:
            raise RuntimeMatrixError(f"runtime_evidence_missing:{provider}")
        if status == QUALIFIED:
            if "lock" not in kinds:
                raise RuntimeMatrixError(f"runtime_lock_missing:{provider}")
            if row.get("checkpoint_status") != "installed" or row.get("smoke_status") != "pass":
                raise RuntimeMatrixError(f"runtime_qualification_overclaim:{provider}")
            if "needs_kevin" in row:
                raise RuntimeMatrixError(f"runtime_qualified_has_human_gate:{provider}")
            qualified += 1
        elif provider in CURRENT_PENDING:
            expected_status, expected_checkpoint, expected_smoke = CURRENT_PENDING[provider]
            if (
                status != expected_status
                or row.get("checkpoint_status") != expected_checkpoint
                or row.get("smoke_status") != expected_smoke
                or "needs_kevin" in row
            ):
                raise RuntimeMatrixError(f"runtime_pending_invalid:{provider}")
            pending += 1
        elif status == GATED:
            reason = row.get("needs_kevin")
            if (
                row.get("checkpoint_status") != "manual_huggingface_gate"
                or row.get("smoke_status") != "not_run_checkpoint_gated"
                or not isinstance(reason, str)
                or not reason.startswith("NEEDS KEVIN:")
            ):
                raise RuntimeMatrixError(f"runtime_human_gate_invalid:{provider}")
            gated += 1
        else:
            raise RuntimeMatrixError(f"runtime_status_invalid:{provider}")
    return {
        "manifest_sha256": document["manifest_sha256"],
        "provider_count": len(rows),
        "qualified_runtime_count": qualified,
        "human_gated_runtime_count": gated,
        "pending_runtime_count": pending,
        "artifact_count": artifact_count,
        "core_torch": policy["core_torch"],
        "status": (
            "pass_with_explicit_human_gates"
            if gated
            else "pass_with_explicit_pending_runtimes" if pending else "pass"
        ),
    }


__all__ = ["DEFAULT_MATRIX", "RuntimeMatrixError", "verify_runtime_matrix"]
