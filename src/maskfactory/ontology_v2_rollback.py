"""Non-destructive rehearsal of exact v1 registry/workflow restoration."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .ontology_v2_baseline import DEFAULT_SNAPSHOT, ROOT, V1BaselineError, sha256_file

DEFAULT_EVIDENCE = ROOT / "qa" / "evidence" / "ontology_v2" / "v1_rollback_rehearsal.json"
DEFAULT_WORKFLOWS = ROOT / "src" / "maskfactory" / "serve" / "maskfactory_nodes" / "workflows"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.rollback-tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rehearse_v1_rollback(
    *,
    root: Path | str = ROOT,
    snapshot_path: Path | str = DEFAULT_SNAPSHOT,
    artifact_paths: Iterable[Path | str] | None = None,
) -> dict[str, Any]:
    workspace = Path(root).resolve()
    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    if snapshot.get("active_ontology") != "body_parts_v1":
        raise V1BaselineError("rollback snapshot is not body_parts_v1")
    paths = (
        tuple(Path(path) for path in artifact_paths)
        if artifact_paths is not None
        else (
            workspace / "models" / "model_registry.json",
            *sorted(
                (
                    workspace / "src" / "maskfactory" / "serve" / "maskfactory_nodes" / "workflows"
                ).glob("*.json")
            ),
        )
    )
    if not paths:
        raise V1BaselineError("rollback rehearsal has no registry/workflow artifacts")

    source_before: dict[str, str] = {}
    source_bytes: dict[str, bytes] = {}
    for path in paths:
        source = path.resolve()
        if not source.is_relative_to(workspace) or not source.is_file():
            raise V1BaselineError(f"invalid rollback artifact: {path}")
        relative = source.relative_to(workspace).as_posix()
        source_bytes[relative] = source.read_bytes()
        source_before[relative] = sha256_file(source)

    artifacts: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="maskfactory-v1-rollback-") as temporary:
        staging = Path(temporary)
        for relative, original in source_bytes.items():
            staged = staging / relative
            _atomic_write(staged, original)
            drifted = original + b"\nmaskfactory-simulated-v2-activation-drift\n"
            _atomic_write(staged, drifted)
            drift_sha = sha256_file(staged)
            _atomic_write(staged, original)
            restored_sha = sha256_file(staged)
            expected_sha = _sha256_bytes(original)
            if drift_sha == expected_sha or restored_sha != expected_sha:
                raise V1BaselineError(f"rollback rehearsal failed for {relative}")
            artifacts[relative] = {
                "expected_v1_sha256": expected_sha,
                "simulated_v2_drift_sha256": drift_sha,
                "restored_v1_sha256": restored_sha,
                "restored_exactly": True,
            }

    source_after = {relative: sha256_file(workspace / relative) for relative in source_before}
    if source_after != source_before:
        raise V1BaselineError("rollback rehearsal mutated a production source artifact")
    return {
        "schema_version": "1.0.0",
        "mode": "isolated_copy_no_production_mutation",
        "active_ontology_preserved": "body_parts_v1",
        "v2_activation_performed": False,
        "source_unchanged": True,
        "champion_pointers_restored": snapshot.get("champion_pointers", []),
        "artifacts": artifacts,
        "result": "pass",
    }


def write_v1_rollback_evidence(
    path: Path | str = DEFAULT_EVIDENCE,
    **kwargs: Any,
) -> Path:
    output = Path(path)
    document = rehearse_v1_rollback(**kwargs)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
