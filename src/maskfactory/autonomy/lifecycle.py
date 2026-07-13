"""Machine-mask lifecycle sidecars, certificate lookup, and revocation overlays."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

from ..validation import ArtifactValidationError, validate_document
from .tournament import TournamentDecision


def load_scoped_certificate(root: Path, *, label: str, context: str) -> dict | None:
    path = Path(root) / f"{label}__{context}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def write_lifecycle_sidecar(
    path: Path,
    *,
    image_id: str,
    instance_id: str,
    pipeline_fingerprint: str,
    decision: TournamentDecision,
) -> dict:
    path = Path(path)
    stage_root = path.parent.parent
    winner = next(
        (item for item in decision.ranking if item.candidate_id == decision.winner_id), None
    )
    document = {
        "schema_version": "1.0.0",
        "image_id": image_id,
        "instance_id": instance_id,
        "label": decision.label,
        "context": decision.context,
        "pipeline_fingerprint": pipeline_fingerprint,
        "status": decision.status,
        "winner_id": decision.winner_id,
        "winner_mask_path": (
            _portable_artifact_path(winner.evidence.mask_path, stage_root) if winner else None
        ),
        "winner_mask_sha256": winner.evidence.mask_sha256 if winner else None,
        "winner_score": decision.winner_score,
        "certificate_valid": decision.certificate_valid,
        "certificate_reason": decision.certificate_reason,
        "human_audit_required": decision.human_audit_required,
        "authoritative_human_gold": False,
        "serve_eligible": decision.status == "calibrated_auto_accepted",
        "pseudo_train_eligible": decision.status == "calibrated_auto_accepted",
        "reason": decision.reason,
        "ranking": [
            {
                "candidate_id": item.candidate_id,
                "score": item.score,
                "eligible": item.eligible,
                "vetoes": list(item.vetoes),
                "mask_sha256": item.evidence.mask_sha256,
            }
            for item in decision.ranking
        ],
    }
    issues = validate_document(document, "autonomy_lifecycle")
    if issues:
        raise ArtifactValidationError(issues)
    _atomic_json(path, document)
    return document


def _portable_artifact_path(value: str, root: Path) -> str:
    candidate = Path(value)
    try:
        return candidate.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(candidate)


def certificate_is_revoked(
    revocations_root: Path, *, label: str, context: str, pipeline_fingerprint: str
) -> bool:
    paths = (
        revocation_marker_path(
            revocations_root,
            label=label,
            context=context,
            pipeline_fingerprint=pipeline_fingerprint,
        ),
        Path(revocations_root) / f"{label}__{context}.json",
    )
    for path in paths:
        if not path.is_file():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("pipeline_fingerprint") == pipeline_fingerprint:
            return True
    return False


def revocation_marker_path(
    root: Path, *, label: str, context: str, pipeline_fingerprint: str
) -> Path:
    """Return a collision-free marker path so one scope cannot overwrite another."""
    fingerprint_id = hashlib.sha256(pipeline_fingerprint.encode()).hexdigest()
    return Path(root) / f"{label}__{context}__{fingerprint_id}.json"


def _atomic_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "certificate_is_revoked",
    "load_scoped_certificate",
    "revocation_marker_path",
    "write_lifecycle_sidecar",
]
