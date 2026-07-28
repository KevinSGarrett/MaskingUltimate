"""Signed matrix-bound prerequisite for interactive-provider promotion.

The aggregate ten-role certificate remains unchanged.  This companion
certificate binds the interactive role's exact candidate/incumbent artifacts,
benchmark decision, and an observed isolated rollback to that same signed
matrix execution.  It grants no activation authority by itself.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ..validation import ArtifactValidationError, require_valid_document
from .matrix_promotion import (
    MatrixPromotionCertificateError,
    load_and_verify_matrix_promotion_bundle,
)

INTERACTIVE_ROLE = "interactive_segmenter"
CERTIFICATE_AUTHORITY = (
    "signed_matrix_bound_interactive_promotion_prerequisite_only_"
    "no_activation_serving_mask_or_gold_authority"
)


class InteractivePromotionCertificateError(ValueError):
    """The interactive role certificate or one of its bound inputs is invalid."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise InteractivePromotionCertificateError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise InteractivePromotionCertificateError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC)


def _load_object(path: Path, name: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InteractivePromotionCertificateError(f"{name} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise InteractivePromotionCertificateError(f"{name} must be an object")
    return value


def _validate_benchmark_certificate(certificate: Mapping[str, Any], *, report_sha256: str) -> None:
    required = {
        "schema_version",
        "target_role",
        "primary_win_or_labor_reduction",
        "hard_bucket_results",
        "frozen_eval_sha256",
        "issued_at",
        "sha256",
    }
    if set(certificate) != required or certificate.get("schema_version") != "1.0.0":
        raise InteractivePromotionCertificateError(
            "interactive benchmark certificate is incomplete"
        )
    if (
        certificate.get("target_role") != INTERACTIVE_ROLE
        or certificate.get("primary_win_or_labor_reduction") is not True
        or certificate.get("frozen_eval_sha256") != report_sha256
    ):
        raise InteractivePromotionCertificateError(
            "interactive benchmark certificate is not bound to the exact matrix report"
        )
    rows = certificate.get("hard_bucket_results")
    if not isinstance(rows, list) or not rows:
        raise InteractivePromotionCertificateError("interactive hard-bucket results are missing")
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"bucket", "observed_delta", "noninferiority_margin", "passed"}
            or not isinstance(row.get("bucket"), str)
            or not row["bucket"]
            or not isinstance(row.get("observed_delta"), (int, float))
            or not isinstance(row.get("noninferiority_margin"), (int, float))
            or float(row["noninferiority_margin"]) < 0
            or row.get("passed") is not True
            or float(row["observed_delta"]) < -float(row["noninferiority_margin"])
        ):
            raise InteractivePromotionCertificateError(
                "interactive benchmark hard-bucket non-inferiority failed"
            )
    _timestamp(certificate.get("issued_at"), "benchmark_certificate.issued_at")
    payload = {key: value for key, value in certificate.items() if key != "sha256"}
    if certificate.get("sha256") != _canonical_sha256(payload):
        raise InteractivePromotionCertificateError(
            "interactive benchmark certificate hash mismatch"
        )


def _validate_rollback_evidence(
    evidence: Mapping[str, Any], *, candidate_key: str, incumbent_key: str
) -> None:
    required = {
        "schema_version",
        "target_role",
        "candidate_provider",
        "incumbent_provider",
        "pipeline_before_sha256",
        "pipeline_promoted_sha256",
        "pipeline_restored_sha256",
        "candidate_smoke_sha256",
        "incumbent_smoke_sha256",
        "rollback_observed",
        "restore_observed",
        "tested_at",
        "sha256",
    }
    if set(evidence) != required or evidence.get("schema_version") != "1.0.0":
        raise InteractivePromotionCertificateError("interactive rollback evidence is incomplete")
    if (
        evidence.get("target_role") != INTERACTIVE_ROLE
        or evidence.get("candidate_provider") != candidate_key
        or evidence.get("incumbent_provider") != incumbent_key
        or evidence.get("rollback_observed") is not True
        or evidence.get("restore_observed") is not True
        or evidence.get("pipeline_before_sha256") != evidence.get("pipeline_restored_sha256")
        or evidence.get("pipeline_before_sha256") == evidence.get("pipeline_promoted_sha256")
    ):
        raise InteractivePromotionCertificateError("interactive rollback rehearsal is invalid")
    for field in (
        "pipeline_before_sha256",
        "pipeline_promoted_sha256",
        "pipeline_restored_sha256",
        "candidate_smoke_sha256",
        "incumbent_smoke_sha256",
    ):
        value = evidence.get(field)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise InteractivePromotionCertificateError(f"rollback evidence {field} is invalid")
    _timestamp(evidence.get("tested_at"), "rollback_evidence.tested_at")
    payload = {key: value for key, value in evidence.items() if key != "sha256"}
    if evidence.get("sha256") != _canonical_sha256(payload):
        raise InteractivePromotionCertificateError("interactive rollback evidence hash mismatch")


def _matrix_inputs(bundle_root: Path) -> tuple[dict[str, Any], ...]:
    root = Path(bundle_root).resolve()
    try:
        loaded = load_and_verify_matrix_promotion_bundle(root)
    except MatrixPromotionCertificateError as exc:
        raise InteractivePromotionCertificateError(str(exc)) from exc
    report = _load_object(root / "matrix_report.json", "matrix report")
    observations = _load_object(root / "matrix_observations.json", "matrix observations")
    manifest = _load_object(root / "matrix_manifest.json", "matrix manifest")
    aggregate = loaded["certificate"]
    return aggregate, report, observations, manifest


def _derive_base(
    *,
    reviewer: str,
    issued_at: datetime,
    signer_public_key_sha256: str,
    matrix_bundle_root: Path,
    benchmark_certificate: Mapping[str, Any],
    rollback_evidence: Mapping[str, Any],
    candidate_key: str,
    incumbent_key: str,
    candidate_artifact_key: str,
    incumbent_artifact_key: str,
    candidate_checkpoint_sha256: str,
    incumbent_checkpoint_sha256: str,
    candidate_runtime_lock_sha256: str,
) -> dict[str, Any]:
    if not reviewer.strip() or candidate_key == incumbent_key:
        raise InteractivePromotionCertificateError("interactive certificate scope is invalid")
    aggregate, report, observations, manifest = _matrix_inputs(matrix_bundle_root)
    _validate_benchmark_certificate(benchmark_certificate, report_sha256=report["sha256"])
    _validate_rollback_evidence(
        rollback_evidence, candidate_key=candidate_key, incumbent_key=incumbent_key
    )
    artifacts = manifest["shared_identity"]["provider_artifact_sha256"]
    if artifacts.get(candidate_artifact_key) != candidate_checkpoint_sha256:
        raise InteractivePromotionCertificateError("candidate checkpoint is absent from the matrix")
    if artifacts.get(incumbent_artifact_key) != incumbent_checkpoint_sha256:
        raise InteractivePromotionCertificateError("incumbent checkpoint is absent from the matrix")
    current = issued_at.astimezone(UTC)
    if current < _timestamp(
        report["evaluated_at"], "matrix_report.evaluated_at"
    ) or current < _timestamp(rollback_evidence["tested_at"], "rollback_evidence.tested_at"):
        raise InteractivePromotionCertificateError(
            "interactive certificate predates its matrix or rollback evidence"
        )
    issued = current.isoformat().replace("+00:00", "Z")
    identity = {
        "issued_at": issued,
        "candidate_key": candidate_key,
        "incumbent_key": incumbent_key,
        "matrix_certificate_sha256": aggregate["certificate_sha256"],
        "benchmark_certificate_sha256": benchmark_certificate["sha256"],
    }
    return {
        "schema_version": "1.0.0",
        "certificate_id": _canonical_sha256(identity)[:24],
        "issued_at": issued,
        "reviewer": reviewer.strip(),
        "target_role": INTERACTIVE_ROLE,
        "candidate_key": candidate_key,
        "incumbent_key": incumbent_key,
        "candidate_artifact_key": candidate_artifact_key,
        "incumbent_artifact_key": incumbent_artifact_key,
        "benchmark_certificate_sha256": benchmark_certificate["sha256"],
        "candidate_checkpoint_sha256": candidate_checkpoint_sha256,
        "incumbent_checkpoint_sha256": incumbent_checkpoint_sha256,
        "candidate_runtime_lock_sha256": candidate_runtime_lock_sha256,
        "matrix_certificate_id": aggregate["certificate_id"],
        "matrix_certificate_sha256": aggregate["certificate_sha256"],
        "matrix_identity": {
            "manifest_sha256": manifest["sha256"],
            "observations_sha256": observations["sha256"],
            "report_sha256": report["sha256"],
            "shared_identity_sha256": report["shared_identity_sha256"],
        },
        "rollback_evidence": dict(rollback_evidence),
        "authority": CERTIFICATE_AUTHORITY,
        "signer_public_key_sha256": signer_public_key_sha256,
        "signature_algorithm": "ed25519",
    }


def build_interactive_promotion_certificate(
    *,
    reviewer: str,
    private_key_path: Path,
    matrix_bundle_root: Path,
    benchmark_certificate: Mapping[str, Any],
    rollback_evidence: Mapping[str, Any],
    candidate_key: str,
    incumbent_key: str,
    candidate_artifact_key: str,
    incumbent_artifact_key: str,
    candidate_checkpoint_sha256: str,
    incumbent_checkpoint_sha256: str,
    candidate_runtime_lock_sha256: str,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    """Build and sign the exact interactive role prerequisite."""
    private_key = serialization.load_pem_private_key(Path(private_key_path).read_bytes(), None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise InteractivePromotionCertificateError("interactive signing key type is invalid")
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    bundle_public = Path(matrix_bundle_root) / "public_key.pem"
    if public_bytes != bundle_public.read_bytes():
        raise InteractivePromotionCertificateError(
            "interactive signer differs from the aggregate matrix signer"
        )
    base = _derive_base(
        reviewer=reviewer,
        issued_at=issued_at or datetime.now(UTC),
        signer_public_key_sha256=hashlib.sha256(public_bytes).hexdigest(),
        matrix_bundle_root=matrix_bundle_root,
        benchmark_certificate=benchmark_certificate,
        rollback_evidence=rollback_evidence,
        candidate_key=candidate_key,
        incumbent_key=incumbent_key,
        candidate_artifact_key=candidate_artifact_key,
        incumbent_artifact_key=incumbent_artifact_key,
        candidate_checkpoint_sha256=candidate_checkpoint_sha256,
        incumbent_checkpoint_sha256=incumbent_checkpoint_sha256,
        candidate_runtime_lock_sha256=candidate_runtime_lock_sha256,
    )
    payload = _canonical_bytes(base)
    base["payload_sha256"] = hashlib.sha256(payload).hexdigest()
    base["signature"] = base64.b64encode(private_key.sign(payload)).decode("ascii")
    base["certificate_sha256"] = _canonical_sha256(base)
    require_valid_document(base, "interactive_provider_promotion_certificate")
    return base


def verify_interactive_promotion_certificate(
    certificate: Mapping[str, Any],
    *,
    matrix_bundle_root: Path,
    benchmark_certificate: Mapping[str, Any],
    rollback_evidence: Mapping[str, Any],
    candidate_key: str,
    incumbent_key: str,
    candidate_artifact_key: str,
    incumbent_artifact_key: str,
    candidate_checkpoint_sha256: str,
    incumbent_checkpoint_sha256: str,
    candidate_runtime_lock_sha256: str,
) -> dict[str, Any]:
    """Recompute all inputs and verify the aggregate signer's detached signature."""
    try:
        require_valid_document(certificate, "interactive_provider_promotion_certificate")
    except ArtifactValidationError as exc:
        raise InteractivePromotionCertificateError(str(exc)) from exc
    public_bytes = (Path(matrix_bundle_root) / "public_key.pem").read_bytes()
    expected = _derive_base(
        reviewer=str(certificate["reviewer"]),
        issued_at=_timestamp(certificate["issued_at"], "issued_at"),
        signer_public_key_sha256=hashlib.sha256(public_bytes).hexdigest(),
        matrix_bundle_root=matrix_bundle_root,
        benchmark_certificate=benchmark_certificate,
        rollback_evidence=rollback_evidence,
        candidate_key=candidate_key,
        incumbent_key=incumbent_key,
        candidate_artifact_key=candidate_artifact_key,
        incumbent_artifact_key=incumbent_artifact_key,
        candidate_checkpoint_sha256=candidate_checkpoint_sha256,
        incumbent_checkpoint_sha256=incumbent_checkpoint_sha256,
        candidate_runtime_lock_sha256=candidate_runtime_lock_sha256,
    )
    signed_payload = {
        key: value
        for key, value in certificate.items()
        if key not in {"payload_sha256", "signature", "certificate_sha256"}
    }
    if signed_payload != expected:
        raise InteractivePromotionCertificateError(
            "interactive certificate inputs are stale or rebound"
        )
    payload = _canonical_bytes(signed_payload)
    if certificate["payload_sha256"] != hashlib.sha256(payload).hexdigest():
        raise InteractivePromotionCertificateError("interactive certificate payload hash mismatch")
    if certificate["certificate_sha256"] != _canonical_sha256(
        {key: value for key, value in certificate.items() if key != "certificate_sha256"}
    ):
        raise InteractivePromotionCertificateError("interactive certificate hash mismatch")
    try:
        public_key = serialization.load_pem_public_key(public_bytes)
        if not isinstance(public_key, Ed25519PublicKey):
            raise TypeError
        public_key.verify(base64.b64decode(str(certificate["signature"]), validate=True), payload)
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise InteractivePromotionCertificateError(
            "interactive certificate signature is invalid"
        ) from exc
    return {
        "certificate_id": certificate["certificate_id"],
        "certificate_sha256": certificate["certificate_sha256"],
        "candidate_key": candidate_key,
        "incumbent_key": incumbent_key,
        "authority": CERTIFICATE_AUTHORITY,
    }


__all__ = [
    "CERTIFICATE_AUTHORITY",
    "INTERACTIVE_ROLE",
    "InteractivePromotionCertificateError",
    "build_interactive_promotion_certificate",
    "verify_interactive_promotion_certificate",
]
