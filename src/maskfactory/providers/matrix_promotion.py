"""Signed, matrix-bound prerequisites for provider-role promotion.

This contract deliberately stops before registry mutation.  It proves that
every governed role has current role-specific evidence, observed rollback to
a distinct incumbent, and an explicit binding to the recomputed provider
matrix.  Possession of a certificate grants no serving, mask, or gold
authority.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
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

from ..training.promotion_policy import (
    CustomSegmenterPromotionError,
    validate_custom_segmenter_promotion_certificate,
)
from ..validation import ArtifactValidationError, require_valid_document
from .benchmark_policy import SPECIALIST_ROLES
from .promotion import SpecialistPromotionError, validate_specialist_promotion_packet
from .provider_matrix_metrics import ProviderMatrixMetricsError, verify_report

CUSTOM_SEGMENTER_ROLE = "custom_segmenter"
GOVERNED_ROLES = frozenset({*SPECIALIST_ROLES, CUSTOM_SEGMENTER_ROLE})
CERTIFICATE_AUTHORITY = (
    "validated_signed_matrix_bound_prerequisites_only_"
    "no_role_promotion_serving_mask_or_gold_authority"
)


class MatrixPromotionCertificateError(ValueError):
    """The aggregate role-promotion prerequisite certificate is invalid."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise MatrixPromotionCertificateError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise MatrixPromotionCertificateError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC)


def _public_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def generate_matrix_promotion_signing_key(private_key_path: Path, public_key_path: Path) -> str:
    """Generate a dedicated Ed25519 keypair and refuse to overwrite either side."""
    private_key_path = Path(private_key_path)
    public_key_path = Path(public_key_path)
    if private_key_path.exists() or public_key_path.exists():
        raise MatrixPromotionCertificateError("signing key path already exists")
    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    public_key_path.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    private_key_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    try:
        os.chmod(private_key_path, 0o600)
    except OSError:
        pass
    public = _public_bytes(private_key)
    public_key_path.write_bytes(public)
    return hashlib.sha256(public).hexdigest()


def _validate_role_sets(
    specialist_packets: Mapping[str, Mapping[str, Any]],
    role_matrix_bindings: Mapping[str, Mapping[str, Any]],
) -> None:
    if set(specialist_packets) != SPECIALIST_ROLES:
        raise MatrixPromotionCertificateError("specialist role packet set is incomplete")
    if set(role_matrix_bindings) != GOVERNED_ROLES:
        raise MatrixPromotionCertificateError("matrix role binding set is incomplete")


def _derive_role_bindings(
    *,
    matrix_report: Mapping[str, Any],
    matrix_manifest: Mapping[str, Any],
    specialist_packets: Mapping[str, Mapping[str, Any]],
    custom_segmenter_certificate: Mapping[str, Any],
    custom_segmenter_expected_identity_hashes: Mapping[str, Any],
    role_matrix_bindings: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    _validate_role_sets(specialist_packets, role_matrix_bindings)
    report_cells = {cell["cell_id"]: cell for cell in matrix_report["cells"]}
    manifest_cells = {
        cell["cell_id"]: cell
        for cell in [
            *matrix_manifest["screening_cells"],
            *matrix_manifest["enrichment_cells"],
        ]
    }
    artifact_hashes = matrix_manifest["shared_identity"]["provider_artifact_sha256"]
    used_cells: set[str] = set()
    rows: list[dict[str, Any]] = []

    for role in sorted(GOVERNED_ROLES):
        binding = role_matrix_bindings[role]
        if set(binding) != {"binding_mode", "cell_id", "provider_artifact_key"}:
            raise MatrixPromotionCertificateError(f"{role} matrix binding structure is invalid")
        cell_id = binding["cell_id"]
        if (
            not isinstance(cell_id, str)
            or cell_id not in report_cells
            or cell_id not in manifest_cells
        ):
            raise MatrixPromotionCertificateError(f"{role} matrix cell is unknown")
        if cell_id in used_cells:
            raise MatrixPromotionCertificateError("matrix cells may not satisfy multiple roles")
        used_cells.add(cell_id)
        report_cell = report_cells[cell_id]
        manifest_cell = manifest_cells[cell_id]

        if role == CUSTOM_SEGMENTER_ROLE:
            if (
                binding["binding_mode"] != "pipeline_context"
                or binding["provider_artifact_key"] is not None
            ):
                raise MatrixPromotionCertificateError(
                    "custom segmenter must use an explicit pipeline-context matrix binding"
                )
            try:
                summary = validate_custom_segmenter_promotion_certificate(
                    custom_segmenter_certificate,
                    expected_identity_hashes=custom_segmenter_expected_identity_hashes,
                )
            except CustomSegmenterPromotionError as exc:
                raise MatrixPromotionCertificateError(str(exc)) from exc
            shared = matrix_manifest["shared_identity"]
            identity = custom_segmenter_expected_identity_hashes
            for identity_key, shared_key in (
                ("evaluation_set_sha256", "evaluation_set_sha256"),
                ("hardware_profile_sha256", "hardware_profile_sha256"),
                ("qa_config_sha256", "qa_sha256"),
            ):
                if identity.get(identity_key) != shared[shared_key]:
                    raise MatrixPromotionCertificateError(
                        f"custom segmenter matrix identity is stale: {identity_key}"
                    )
            prerequisite = custom_segmenter_certificate
            prerequisite_kind = "custom_segmenter_certificate"
        else:
            if binding["binding_mode"] != "candidate_artifact":
                raise MatrixPromotionCertificateError(f"{role} must bind a candidate artifact")
            artifact_key = binding["provider_artifact_key"]
            if (
                not isinstance(artifact_key, str)
                or artifact_key not in artifact_hashes
                or artifact_key not in manifest_cell["provider_artifact_keys"]
            ):
                raise MatrixPromotionCertificateError(
                    f"{role} candidate artifact is absent from cell"
                )
            prerequisite = specialist_packets[role]
            try:
                summary = validate_specialist_promotion_packet(prerequisite)
            except SpecialistPromotionError as exc:
                raise MatrixPromotionCertificateError(str(exc)) from exc
            if summary["target_role"] != role:
                raise MatrixPromotionCertificateError(f"{role} packet role is rebound")
            if (
                prerequisite["identity_hashes"]["checkpoint_sha256"]
                != artifact_hashes[artifact_key]
            ):
                raise MatrixPromotionCertificateError(
                    f"{role} candidate artifact identity is stale"
                )
            prerequisite_kind = "specialist_promotion_packet"

        rollback = prerequisite["rollback_evidence"]
        rows.append(
            {
                "role": role,
                "candidate_key": summary["candidate_key"],
                "incumbent_provider": summary["rollback_provider"],
                "prerequisite_kind": prerequisite_kind,
                "prerequisite_sha256": prerequisite["sha256"],
                "prerequisite_summary_sha256": _canonical_sha256(summary),
                "rollback_evidence_sha256": _canonical_sha256(rollback),
                "rollback_tested_at": rollback["tested_at"],
                "matrix_binding_mode": binding["binding_mode"],
                "matrix_provider_artifact_key": binding["provider_artifact_key"],
                "matrix_cell_id": cell_id,
                "matrix_cell_identity_sha256": report_cell["cell_identity_sha256"],
                "matrix_cell_observations_sha256": report_cell["observations_sha256"],
                "matrix_cell_result_sha256": _canonical_sha256(report_cell),
            }
        )
    return rows


def _derive_base(
    *,
    reviewer: str,
    issued_at: datetime,
    signer_public_key_sha256: str,
    matrix_report: Mapping[str, Any],
    matrix_observations: Mapping[str, Any],
    matrix_manifest: Mapping[str, Any],
    specialist_packets: Mapping[str, Mapping[str, Any]],
    custom_segmenter_certificate: Mapping[str, Any],
    custom_segmenter_expected_identity_hashes: Mapping[str, Any],
    role_matrix_bindings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise MatrixPromotionCertificateError("reviewer is missing")
    if issued_at.tzinfo is None:
        raise MatrixPromotionCertificateError("issued_at lacks a timezone")
    try:
        verify_report(matrix_report, matrix_observations, matrix_manifest)
    except ProviderMatrixMetricsError as exc:
        raise MatrixPromotionCertificateError(str(exc)) from exc
    current = issued_at.astimezone(UTC)
    if current < _timestamp(matrix_report["evaluated_at"], "matrix_report.evaluated_at"):
        raise MatrixPromotionCertificateError("certificate predates matrix evaluation")
    roles = _derive_role_bindings(
        matrix_report=matrix_report,
        matrix_manifest=matrix_manifest,
        specialist_packets=specialist_packets,
        custom_segmenter_certificate=custom_segmenter_certificate,
        custom_segmenter_expected_identity_hashes=custom_segmenter_expected_identity_hashes,
        role_matrix_bindings=role_matrix_bindings,
    )
    for row in roles:
        if current < _timestamp(row["rollback_tested_at"], f"{row['role']}.rollback_tested_at"):
            raise MatrixPromotionCertificateError(
                f"certificate predates observed rollback for {row['role']}"
            )
    issued = current.isoformat().replace("+00:00", "Z")
    identity = {
        "issued_at": issued,
        "reviewer": reviewer.strip(),
        "matrix_report_sha256": matrix_report["sha256"],
        "role_bindings_sha256": _canonical_sha256(roles),
    }
    return {
        "schema_version": "1.0.0",
        "certificate_id": _canonical_sha256(identity)[:24],
        "issued_at": issued,
        "reviewer": reviewer.strip(),
        "signer_public_key_sha256": signer_public_key_sha256,
        "matrix_identity": {
            "policy_sha256": matrix_report["policy_sha256"],
            "manifest_sha256": matrix_manifest["sha256"],
            "observations_sha256": matrix_observations["sha256"],
            "report_sha256": matrix_report["sha256"],
            "shared_identity_sha256": matrix_report["shared_identity_sha256"],
        },
        "role_bindings": roles,
        "authority": CERTIFICATE_AUTHORITY,
        "signature_algorithm": "ed25519",
    }


def build_matrix_promotion_certificate(
    *,
    reviewer: str,
    private_key_path: Path,
    matrix_report: Mapping[str, Any],
    matrix_observations: Mapping[str, Any],
    matrix_manifest: Mapping[str, Any],
    specialist_packets: Mapping[str, Mapping[str, Any]],
    custom_segmenter_certificate: Mapping[str, Any],
    custom_segmenter_expected_identity_hashes: Mapping[str, Any],
    role_matrix_bindings: Mapping[str, Mapping[str, Any]],
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    """Validate all inputs, derive the aggregate prerequisite record, and sign it."""
    private_key = serialization.load_pem_private_key(Path(private_key_path).read_bytes(), None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise MatrixPromotionCertificateError("signing key type is invalid")
    public = _public_bytes(private_key)
    base = _derive_base(
        reviewer=reviewer,
        issued_at=issued_at or datetime.now(UTC),
        signer_public_key_sha256=hashlib.sha256(public).hexdigest(),
        matrix_report=matrix_report,
        matrix_observations=matrix_observations,
        matrix_manifest=matrix_manifest,
        specialist_packets=specialist_packets,
        custom_segmenter_certificate=custom_segmenter_certificate,
        custom_segmenter_expected_identity_hashes=custom_segmenter_expected_identity_hashes,
        role_matrix_bindings=role_matrix_bindings,
    )
    payload = _canonical_bytes(base)
    base["payload_sha256"] = hashlib.sha256(payload).hexdigest()
    base["signature"] = base64.b64encode(private_key.sign(payload)).decode("ascii")
    base["certificate_sha256"] = _canonical_sha256(base)
    require_valid_document(base, "matrix_promotion_certificate")
    return base


def verify_matrix_promotion_certificate(
    certificate: Mapping[str, Any],
    *,
    public_key_path: Path,
    matrix_report: Mapping[str, Any],
    matrix_observations: Mapping[str, Any],
    matrix_manifest: Mapping[str, Any],
    specialist_packets: Mapping[str, Mapping[str, Any]],
    custom_segmenter_certificate: Mapping[str, Any],
    custom_segmenter_expected_identity_hashes: Mapping[str, Any],
    role_matrix_bindings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Recompute every binding and verify the dedicated Ed25519 signature."""
    try:
        require_valid_document(certificate, "matrix_promotion_certificate")
    except ArtifactValidationError as exc:
        raise MatrixPromotionCertificateError(str(exc)) from exc
    public_bytes = Path(public_key_path).read_bytes()
    expected = _derive_base(
        reviewer=str(certificate["reviewer"]),
        issued_at=_timestamp(certificate["issued_at"], "issued_at"),
        signer_public_key_sha256=hashlib.sha256(public_bytes).hexdigest(),
        matrix_report=matrix_report,
        matrix_observations=matrix_observations,
        matrix_manifest=matrix_manifest,
        specialist_packets=specialist_packets,
        custom_segmenter_certificate=custom_segmenter_certificate,
        custom_segmenter_expected_identity_hashes=custom_segmenter_expected_identity_hashes,
        role_matrix_bindings=role_matrix_bindings,
    )
    signed_payload = {
        key: value
        for key, value in certificate.items()
        if key not in {"payload_sha256", "signature", "certificate_sha256"}
    }
    if signed_payload != expected:
        raise MatrixPromotionCertificateError("signed certificate inputs are stale or rebound")
    payload = _canonical_bytes(signed_payload)
    if certificate["payload_sha256"] != hashlib.sha256(payload).hexdigest():
        raise MatrixPromotionCertificateError("certificate payload hash mismatch")
    if certificate["certificate_sha256"] != _canonical_sha256(
        {key: value for key, value in certificate.items() if key != "certificate_sha256"}
    ):
        raise MatrixPromotionCertificateError("certificate hash mismatch")
    try:
        public_key = serialization.load_pem_public_key(public_bytes)
        if not isinstance(public_key, Ed25519PublicKey):
            raise TypeError
        public_key.verify(base64.b64decode(str(certificate["signature"]), validate=True), payload)
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise MatrixPromotionCertificateError("certificate signature is invalid") from exc
    return {
        "certificate_id": certificate["certificate_id"],
        "certificate_sha256": certificate["certificate_sha256"],
        "role_count": len(certificate["role_bindings"]),
        "authority": CERTIFICATE_AUTHORITY,
    }


__all__ = [
    "CERTIFICATE_AUTHORITY",
    "CUSTOM_SEGMENTER_ROLE",
    "GOVERNED_ROLES",
    "MatrixPromotionCertificateError",
    "build_matrix_promotion_certificate",
    "generate_matrix_promotion_signing_key",
    "verify_matrix_promotion_certificate",
]
