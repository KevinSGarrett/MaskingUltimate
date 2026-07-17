"""Deterministic issuance for exact-output operational autonomy certificates.

The issuer accepts a fully described but unsigned certificate body from the
pipeline.  It independently binds the actual source and mask bytes, compares
all authority-bearing subdocuments with caller-supplied adopted records, and
signs only after the frozen v1 semantic validator reports no issue.
"""

from __future__ import annotations

import base64
import copy
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PIL import Image, ImageOps

from maskfactory.validation import (
    artifact_identity_sha256,
    canonical_document_sha256,
    canonical_json_bytes,
    validate_operational_autonomy_certificate,
)

_AUTHORITATIVE_BINDINGS = (
    "release_binding",
    "ontology_binding",
    "pipeline_policy_binding",
    "execution_binding",
    "subject_binding",
    "coordinate_binding",
    "qualified_route_scope",
    "qa_evidence",
    "revocation",
)


class OperationalCertificateIssuanceError(ValueError):
    """Raised when exact-output operational authority cannot be proven."""

    def __init__(self, *codes: str):
        self.codes = tuple(sorted(set(codes))) or ("issuance_rejected",)
        super().__init__("operational certificate issuance rejected: " + ", ".join(self.codes))


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_decoded_raster_sha256(
    pixels: np.ndarray,
    *,
    channel_layout: str,
    allowed_values: str | None = None,
) -> str:
    """Hash typed raster semantics and contiguous decoded pixels deterministically."""
    contiguous = np.ascontiguousarray(pixels)
    height, width = contiguous.shape[:2]
    header = {
        "algorithm": "maskfactory-decoded-raster-v1",
        "width": int(width),
        "height": int(height),
        "channel_layout": channel_layout,
        "dtype": str(contiguous.dtype),
        "shape": list(contiguous.shape),
        "allowed_values": allowed_values,
    }
    return hashlib.sha256(canonical_json_bytes(header) + b"\n" + contiguous.tobytes()).hexdigest()


def _decode_exact(path: Path, binding: Mapping[str, Any], *, mask: bool) -> np.ndarray:
    if not path.is_file():
        raise OperationalCertificateIssuanceError("artifact_path_missing")
    layout = binding.get("channel_layout")
    expected_mode = {"GRAY": "L", "L": "L", "RGB": "RGB", "RGBA": "RGBA"}.get(layout)
    if expected_mode is None:
        raise OperationalCertificateIssuanceError("unsupported_channel_layout")
    with Image.open(path) as opened:
        observed_orientation = int(opened.getexif().get(274, 1))
        if not mask and binding.get("exif_orientation") != observed_orientation:
            raise OperationalCertificateIssuanceError("source_orientation_mismatch")
        image = (
            ImageOps.exif_transpose(opened) if binding.get("orientation_applied") else opened.copy()
        )
        if image.mode != expected_mode:
            raise OperationalCertificateIssuanceError("decoded_channel_layout_mismatch")
        if mask and opened.format != "PNG":
            raise OperationalCertificateIssuanceError("mask_format_not_png")
        pixels = np.asarray(image)
    if pixels.dtype != np.uint8 or binding.get("dtype") != "uint8":
        raise OperationalCertificateIssuanceError("decoded_dtype_mismatch")
    height, width = pixels.shape[:2]
    if binding.get("width") != width or binding.get("height") != height:
        raise OperationalCertificateIssuanceError("decoded_dimensions_mismatch")
    if mask:
        values = set(int(value) for value in np.unique(pixels))
        if binding.get("allowed_values") != "binary_0_255" or not values.issubset({0, 255}):
            raise OperationalCertificateIssuanceError("mask_values_not_binary")
    return pixels


def _mask_summary(pixels: np.ndarray) -> dict[str, Any]:
    foreground = pixels == 255
    area = int(np.count_nonzero(foreground))
    height, width = pixels.shape[:2]
    bounds = None
    if area:
        ys, xs = np.nonzero(foreground)
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        bounds = {"x": x0, "y": y0, "width": x1 - x0 + 1, "height": y1 - y0 + 1}
    return {
        "bounds": bounds,
        "area_pixels": area,
        "area_ppm": (area * 1_000_000) // (width * height),
        "is_empty": area == 0,
    }


def _require_authoritative_bindings(
    document: Mapping[str, Any], authoritative_bindings: Mapping[str, Mapping[str, Any]]
) -> None:
    codes: list[str] = []
    if set(authoritative_bindings) != set(_AUTHORITATIVE_BINDINGS):
        codes.append("authoritative_binding_set_incomplete")
    for field in _AUTHORITATIVE_BINDINGS:
        if field not in authoritative_bindings:
            continue
        if canonical_json_bytes(document.get(field)) != canonical_json_bytes(
            authoritative_bindings[field]
        ):
            codes.append(f"authoritative_{field}_mismatch")
    if codes:
        raise OperationalCertificateIssuanceError(*codes)


def _require_protected_inputs(document: Mapping[str, Any], *, decision_time: datetime) -> None:
    protected = document.get("lineage", {}).get("input_protected_regions", ())
    codes: list[str] = []
    for row in protected:
        if not isinstance(row, Mapping):
            codes.append("protected_input_malformed")
            continue
        required = row.get("required_minimum_authority_state")
        actual = row.get("authority_state")
        if required == "certified" and not (
            actual == "certified"
            and row.get("issuer_kind") == "maskfactory_autonomous"
            and row.get("certificate_kind") == "exact_serving_route_output"
            and row.get("certificate_status") == "active"
            and row.get("certificate_exact_scope_match") is True
        ):
            codes.append("protected_input_authority_too_weak")
        checked = _parse_timestamp(row.get("revocation_checked_at"))
        if (
            checked is None
            or checked > decision_time
            or (decision_time - checked).total_seconds() > 300
        ):
            codes.append("protected_input_revocation_stale")
    if codes:
        raise OperationalCertificateIssuanceError(*codes)


def _load_signing_key(
    path: Path,
    *,
    key_id: str,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]],
    issued_at: datetime,
) -> tuple[Ed25519PrivateKey, bytes]:
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as exc:
        raise OperationalCertificateIssuanceError("private_key_unreadable") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise OperationalCertificateIssuanceError("private_key_not_ed25519")
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    record = trusted_signing_keys.get(key_id)
    if not isinstance(record, Mapping):
        raise OperationalCertificateIssuanceError("signing_key_untrusted")
    valid_from = _parse_timestamp(record.get("valid_from"))
    valid_until = _parse_timestamp(record.get("valid_until"))
    if record.get("public_key_sha256") != hashlib.sha256(public).hexdigest():
        raise OperationalCertificateIssuanceError("signing_key_substituted")
    if "producer_authority" not in set(record.get("roles") or ()):
        raise OperationalCertificateIssuanceError("signing_key_wrong_role")
    if record.get("status") != "active" or record.get("usage_scope") != "production":
        raise OperationalCertificateIssuanceError("signing_key_not_production_active")
    if valid_from is None or valid_until is None or not (valid_from <= issued_at < valid_until):
        raise OperationalCertificateIssuanceError("signing_key_out_of_validity")
    return key, public


def issue_operational_autonomy_certificate(
    unsigned_certificate: Mapping[str, Any],
    *,
    source_path: str | Path,
    artifact_paths: Mapping[str, str | Path],
    authoritative_bindings: Mapping[str, Mapping[str, Any]],
    candidate_authority_state: str,
    candidate_truth_tier: str,
    journal_state: Mapping[str, Any],
    private_key_path: str | Path,
    signing_key_id: str,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]],
    decision_time: str,
) -> dict[str, Any]:
    """Issue exact-output authority, or reject without returning a partial certificate."""
    document = copy.deepcopy(dict(unsigned_certificate))
    if candidate_authority_state != "qa_passed_noncertified" or candidate_truth_tier != (
        "qa_passed_machine_candidate"
    ):
        raise OperationalCertificateIssuanceError("candidate_not_qa_passed_noncertified")
    if document.get("fixture_only") is not False or document.get("evidence_context") != (
        "runtime_evidence"
    ):
        raise OperationalCertificateIssuanceError("runtime_evidence_required")
    issued_at = _parse_timestamp(document.get("issued_at"))
    expires_at = _parse_timestamp(document.get("expires_at"))
    at_time = _parse_timestamp(decision_time)
    if (
        issued_at is None
        or expires_at is None
        or at_time is None
        or not (issued_at <= at_time < expires_at)
    ):
        raise OperationalCertificateIssuanceError("certificate_validity_rejected")
    _require_authoritative_bindings(document, authoritative_bindings)
    if journal_state.get("fork_detected") is not False:
        raise OperationalCertificateIssuanceError("signed_journal_fork")
    revocation = document.get("revocation")
    if not isinstance(revocation, Mapping) or any(
        revocation.get(field) != journal_state.get(field)
        for field in ("checked_at", "revocation_index_sha256", "is_revoked")
    ):
        raise OperationalCertificateIssuanceError("revocation_state_mismatch")
    if revocation.get("is_revoked") is not False:
        raise OperationalCertificateIssuanceError("certificate_scope_revoked")
    _require_protected_inputs(document, decision_time=at_time)

    source_binding = document.get("source_binding")
    if not isinstance(source_binding, dict):
        raise OperationalCertificateIssuanceError("source_binding_missing")
    source = Path(source_path)
    source_pixels = _decode_exact(source, source_binding, mask=False)
    observed_source_encoded = _sha256_file(source)
    observed_source_decoded = canonical_decoded_raster_sha256(
        source_pixels,
        channel_layout=str(source_binding["channel_layout"]),
    )
    if source_binding.get("encoded_sha256") != observed_source_encoded:
        raise OperationalCertificateIssuanceError("source_encoded_hash_mismatch")
    if source_binding.get("decoded_pixel_sha256") != observed_source_decoded:
        raise OperationalCertificateIssuanceError("source_decoded_hash_mismatch")

    artifacts = document.get("bound_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise OperationalCertificateIssuanceError("bound_artifacts_missing")
    expected_ids = {row.get("artifact_id") for row in artifacts if isinstance(row, Mapping)}
    if None in expected_ids or set(artifact_paths) != expected_ids:
        raise OperationalCertificateIssuanceError("artifact_path_set_mismatch")
    identities: list[str] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise OperationalCertificateIssuanceError("bound_artifact_malformed")
        path = Path(artifact_paths[str(artifact["artifact_id"])])
        pixels = _decode_exact(path, artifact, mask=True)
        if artifact.get("content_summary") != _mask_summary(pixels):
            raise OperationalCertificateIssuanceError("mask_content_summary_mismatch")
        observed_encoded = _sha256_file(path)
        observed_decoded = canonical_decoded_raster_sha256(
            pixels,
            channel_layout=str(artifact["channel_layout"]),
            allowed_values=str(artifact["allowed_values"]),
        )
        if artifact.get("encoded_sha256") != observed_encoded:
            raise OperationalCertificateIssuanceError("mask_encoded_hash_mismatch")
        if artifact.get("decoded_mask_sha256") != observed_decoded:
            raise OperationalCertificateIssuanceError("mask_decoded_hash_mismatch")
        if artifact.get("source_decoded_pixel_sha256") != source_binding["decoded_pixel_sha256"]:
            raise OperationalCertificateIssuanceError("mask_source_hash_mismatch")
        expected_identity = artifact_identity_sha256(artifact)
        if artifact.get("artifact_identity_sha256") != expected_identity:
            raise OperationalCertificateIssuanceError("mask_artifact_identity_mismatch")
        identities.append(artifact["artifact_identity_sha256"])
    if document.get("certified_output_scope", {}).get("artifact_identity_sha256s") != identities:
        raise OperationalCertificateIssuanceError("certified_output_scope_mismatch")
    if document.get("lineage", {}).get("output_artifact_identity_sha256s") != identities:
        raise OperationalCertificateIssuanceError("output_lineage_mismatch")

    key, public = _load_signing_key(
        Path(private_key_path),
        key_id=signing_key_id,
        trusted_signing_keys=trusted_signing_keys,
        issued_at=issued_at,
    )
    document["signature"] = {
        "algorithm": "ed25519",
        "key_id": signing_key_id,
        "public_key_base64": base64.b64encode(public).decode("ascii"),
        "signed_payload_sha256": "0" * 64,
        "signed_payload_format": "sha256_digest_bytes",
        "value_base64": base64.b64encode(b"0" * 64).decode("ascii"),
    }
    document["certificate_payload_sha256"] = canonical_document_sha256(
        document,
        excluded_top_level_fields=("certificate_payload_sha256", "signature"),
    )
    document["signature"]["signed_payload_sha256"] = document["certificate_payload_sha256"]
    document["signature"]["value_base64"] = base64.b64encode(
        key.sign(bytes.fromhex(document["certificate_payload_sha256"]))
    ).decode("ascii")
    issues = validate_operational_autonomy_certificate(
        document,
        trusted_signing_keys=trusted_signing_keys,
        at_time=decision_time,
        production_required=True,
    )
    if issues:
        raise OperationalCertificateIssuanceError(*(issue.validator for issue in issues))
    return document
