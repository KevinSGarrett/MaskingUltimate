"""Machine-mask lifecycle sidecars, certificate lookup, and revocation overlays."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

from ..io.hashing import sha256_file
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
        "schema_version": "2.0.0",
        "image_id": image_id,
        "instance_id": instance_id,
        "label": decision.label,
        "context": decision.context,
        "pipeline_fingerprint": pipeline_fingerprint,
        "status": decision.status,
        "truth_tier": decision.truth_tier,
        "training_loss_weight": decision.training_loss_weight,
        "holdout_eligible": False,
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
        "serve_eligible": decision.truth_tier == "autonomous_certified_gold",
        "pseudo_train_eligible": decision.truth_tier == "autonomous_certified_gold",
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


def verified_lifecycle_winner_mask(document: dict, lifecycle_root: Path) -> Path:
    """Validate a lifecycle sidecar and return its hash-verified contained winner mask."""
    issues = validate_document(document, "autonomy_lifecycle")
    if issues:
        raise ArtifactValidationError(issues)
    recorded = document.get("winner_mask_path")
    digest = document.get("winner_mask_sha256")
    if (
        not isinstance(recorded, str)
        or not recorded
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("lifecycle winner mask identity is invalid")
    relative = Path(recorded)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("lifecycle winner mask path must be relative and contained")
    stage_root = Path(lifecycle_root).resolve().parent
    mask_path = (stage_root / relative).resolve()
    try:
        mask_path.relative_to(stage_root)
    except ValueError as exc:
        raise ValueError("lifecycle winner mask escapes its stage root") from exc
    if not mask_path.is_file() or sha256_file(mask_path) != digest:
        raise ValueError(f"lifecycle winner mask hash failed: {mask_path}")
    winner_id = document.get("winner_id")
    winner_rows = [
        row for row in document.get("ranking", ()) if row.get("candidate_id") == winner_id
    ]
    if len(winner_rows) != 1 or winner_rows[0].get("mask_sha256") != digest:
        raise ValueError("lifecycle ranking does not prove its winner mask")
    return mask_path


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


def stratum_revocation_marker_path(
    root: Path,
    *,
    risk_bucket: str,
    instance_context: str,
    pipeline_fingerprint: str,
) -> Path:
    """Return the exact multi-person risk-stratum revocation marker path."""
    if instance_context not in {"duo", "small_group"} or not risk_bucket:
        raise ValueError("multi-person revocation stratum is invalid")
    fingerprint_id = hashlib.sha256(pipeline_fingerprint.encode()).hexdigest()
    return (
        Path(root) / "multi_person" / (f"{risk_bucket}__{instance_context}__{fingerprint_id}.json")
    )


def certificate_stratum_is_revoked(
    revocations_root: Path,
    *,
    risk_bucket: str,
    instance_context: str,
    pipeline_fingerprint: str,
) -> bool:
    """Check an exact multi-person bucket/context/fingerprint overlay."""
    path = stratum_revocation_marker_path(
        revocations_root,
        risk_bucket=risk_bucket,
        instance_context=instance_context,
        pipeline_fingerprint=pipeline_fingerprint,
    )
    if not path.is_file():
        return False
    document = json.loads(path.read_text(encoding="utf-8"))
    return (
        document.get("risk_bucket") == risk_bucket
        and document.get("instance_context") == instance_context
        and document.get("pipeline_fingerprint") == pipeline_fingerprint
        and document.get("status") == "revoked_residual_only"
    )


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
    "certificate_stratum_is_revoked",
    "load_scoped_certificate",
    "revocation_marker_path",
    "stratum_revocation_marker_path",
    "write_lifecycle_sidecar",
    "verified_lifecycle_winner_mask",
]
