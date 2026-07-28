"""Cryptographically attested, fail-closed provider technology-currency reviews."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ..governance import (
    GovernancePolicyError,
    provider_activation_issues,
    validate_external_source_registry,
    validate_model_registry,
)
from ..validation import ArtifactValidationError, require_valid_document

REVIEW_EVENTS = frozenset(
    {"scheduled_90_day", "dataset_freeze", "training", "promotion", "major_release"}
)
MAXIMUM_REVIEW_AGE_DAYS = 90
_HEX = frozenset("0123456789abcdef")


class CurrencyReviewError(ValueError):
    """A currency review is invalid, stale, incomplete, or nonpassing."""

    def __init__(self, codes: list[str] | tuple[str, ...]):
        self.codes = tuple(sorted(set(codes)))
        super().__init__("currency review failed: " + ", ".join(self.codes))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _timestamp(value: Any, code: str, findings: list[str]) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        findings.append(code)
        return None
    if parsed.tzinfo is None:
        findings.append(code)
        return None
    return parsed.astimezone(UTC)


def _load_yaml(path: Path) -> Mapping[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise CurrencyReviewError(["registry_document_invalid"])
    return document


def _load_json(path: Path) -> Mapping[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise CurrencyReviewError(["registry_document_invalid"])
    return document


def _input_hashes(
    *,
    pipeline_path: Path,
    external_registry_path: Path,
    model_registry_path: Path,
    rollback_evidence_path: Path,
    dependency_paths: Mapping[str, Path],
) -> dict[str, Any]:
    if not dependency_paths or any(
        not isinstance(name, str) or not name or "/" in name or "\\" in name
        for name in dependency_paths
    ):
        raise CurrencyReviewError(["dependency_input_set_invalid"])
    paths = {
        "pipeline": Path(pipeline_path),
        "external_registry": Path(external_registry_path),
        "model_registry": Path(model_registry_path),
        "rollback_evidence": Path(rollback_evidence_path),
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    missing.extend(
        f"dependency:{name}" for name, path in dependency_paths.items() if not Path(path).is_file()
    )
    if missing:
        raise CurrencyReviewError([f"input_missing:{name}" for name in missing])
    return {
        **{name: _file_sha256(path) for name, path in paths.items()},
        "dependencies": {
            name: _file_sha256(Path(path)) for name, path in sorted(dependency_paths.items())
        },
    }


def _artifact_sha256(entry: Mapping[str, Any]) -> str | None:
    for field in ("sha256", "checkpoint_sha256", "artifact_sha256"):
        value = entry.get(field)
        if _is_sha256(value):
            return str(value)
    return None


def _runtime_identity(entry: Mapping[str, Any]) -> str | None:
    for field in ("runtime", "runtime_identity", "version"):
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _license_status(entry: Mapping[str, Any], *, registry: str, findings: list[str]) -> str:
    if registry == "external_sources":
        issues = set(provider_activation_issues(entry))
        if issues:
            findings.append("license_decision_unresolved")
            return "unresolved"
        return "verified"
    review = entry.get("license_review")
    resolved = isinstance(review, Mapping) and (
        review.get("status") == "verified"
        or review.get("status") == "not_required"
        and entry.get("license") == "MaskFactory-internal"
    )
    if not resolved:
        findings.append("license_decision_unresolved")
        return str(review.get("status", "missing")) if isinstance(review, Mapping) else "missing"
    return str(review["status"])


def _benchmark_status(
    certificate: Any, *, role: str, reviewed_at: datetime, findings: list[str]
) -> tuple[str | None, str | None]:
    if not isinstance(certificate, Mapping):
        findings.append("benchmark_certificate_missing")
        return None, None
    claimed = certificate.get("sha256")
    payload = {key: value for key, value in certificate.items() if key != "sha256"}
    if not _is_sha256(claimed) or claimed != _canonical_sha256(payload):
        findings.append("benchmark_certificate_invalid")
    if certificate.get("target_role") != role:
        findings.append("benchmark_certificate_scope_mismatch")
    if certificate.get("primary_win_or_labor_reduction") is not True:
        findings.append("benchmark_certificate_primary_gate_failed")
    results = certificate.get("hard_bucket_results")
    if (
        not isinstance(results, list)
        or not results
        or any(
            not isinstance(row, Mapping)
            or row.get("passed") is not True
            or not isinstance(row.get("observed_delta"), (int, float))
            or not isinstance(row.get("noninferiority_margin"), (int, float))
            or float(row["observed_delta"]) < -float(row["noninferiority_margin"])
            for row in results
        )
    ):
        findings.append("benchmark_certificate_hard_bucket_failed")
    issued = _timestamp(certificate.get("issued_at"), "benchmark_certificate_invalid", findings)
    if issued is not None and (
        issued > reviewed_at or reviewed_at - issued > timedelta(days=MAXIMUM_REVIEW_AGE_DAYS)
    ):
        findings.append("benchmark_certificate_stale")
    return str(claimed) if _is_sha256(claimed) else None, (
        issued.isoformat().replace("+00:00", "Z") if issued is not None else None
    )


def _rollback_records(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if set(document) != {"schema_version", "records"} or document.get("schema_version") != "1.0.0":
        raise CurrencyReviewError(["rollback_evidence_document_invalid"])
    rows = document.get("records")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise CurrencyReviewError(["rollback_evidence_document_invalid"])
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        role = row.get("role")
        if not isinstance(role, str) or not role or role in indexed:
            raise CurrencyReviewError(["rollback_evidence_document_invalid"])
        indexed[role] = row
    return indexed


def _rollback_status(
    record: Mapping[str, Any] | None,
    *,
    role: str,
    active_provider: str,
    rollback_provider: str | None,
    pipeline_sha256: str,
    active_artifact_sha256: str | None,
    rollback_artifact_sha256: str | None,
    reviewed_at: datetime,
    findings: list[str],
) -> tuple[str | None, str | None]:
    if record is None:
        findings.append("rollback_evidence_missing")
        return None, None
    claimed = record.get("sha256")
    payload = {key: value for key, value in record.items() if key != "sha256"}
    if not _is_sha256(claimed) or claimed != _canonical_sha256(payload):
        findings.append("rollback_evidence_invalid")
    expected = {
        "schema_version": "1.0.0",
        "role": role,
        "active_provider": active_provider,
        "rollback_provider": rollback_provider,
        "pipeline_sha256": pipeline_sha256,
        "active_artifact_sha256": active_artifact_sha256,
        "rollback_artifact_sha256": rollback_artifact_sha256,
        "result": "pass",
        "rollback_observed": True,
        "restore_observed": True,
    }
    if any(record.get(key) != value for key, value in expected.items()):
        findings.append("rollback_evidence_invalid")
    tested = _timestamp(record.get("tested_at"), "rollback_evidence_invalid", findings)
    if tested is not None and (
        tested > reviewed_at or reviewed_at - tested > timedelta(days=MAXIMUM_REVIEW_AGE_DAYS)
    ):
        findings.append("rollback_evidence_stale")
    return str(claimed) if _is_sha256(claimed) else None, (
        tested.isoformat().replace("+00:00", "Z") if tested is not None else None
    )


def _inspect_active_roles(
    *,
    pipeline: Mapping[str, Any],
    external: Mapping[str, Any],
    models: Mapping[str, Any],
    rollback_document: Mapping[str, Any],
    pipeline_sha256: str,
    reviewed_at: datetime,
) -> tuple[list[dict[str, Any]], list[str], str]:
    global_findings: list[str] = []
    try:
        validate_external_source_registry(external)
    except GovernancePolicyError:
        global_findings.append("external_registry_governance_invalid")
    try:
        validate_model_registry(models)
    except GovernancePolicyError:
        global_findings.append("model_registry_governance_invalid")
    roles = pipeline.get("provider_roles")
    catalog = pipeline.get("provider_catalog")
    if not isinstance(roles, Mapping) or not isinstance(catalog, Mapping):
        raise CurrencyReviewError(["pipeline_provider_contract_invalid"])
    external_entries = external.get("providers", {})
    model_entries = {
        str(entry.get("key")): entry
        for entry in models.get("models", ())
        if isinstance(entry, Mapping)
    }
    authorities = {"external_sources": external_entries, "model_registry": model_entries}
    rollback_records = _rollback_records(rollback_document)
    active_config = {
        str(role): config.get("active")
        for role, config in roles.items()
        if isinstance(config, Mapping) and config.get("active") is not None
    }
    active_role_digest = _canonical_sha256(active_config)
    reviews: list[dict[str, Any]] = []
    for role, active_alias in sorted(active_config.items()):
        findings: list[str] = []
        binding = catalog.get(active_alias)
        registry = binding.get("registry") if isinstance(binding, Mapping) else None
        authority_key = binding.get("key") if isinstance(binding, Mapping) else None
        if registry not in authorities or not isinstance(authority_key, str):
            findings.append("active_binding_missing")
            authority: Mapping[str, Any] = {}
            registry = "model_registry"
            authority_key = str(authority_key or active_alias)
        else:
            candidate = authorities[str(registry)].get(authority_key)
            if not isinstance(candidate, Mapping):
                findings.append("active_authority_missing")
                authority = {}
            else:
                authority = candidate
        lifecycle = authority.get("lifecycle_state")
        if lifecycle != "promoted":
            findings.append("active_lifecycle_not_promoted")
        artifact_sha256 = _artifact_sha256(authority)
        if artifact_sha256 is None:
            findings.append("active_artifact_hash_missing")
        runtime = _runtime_identity(authority)
        if runtime is None:
            findings.append("active_runtime_identity_missing")
        license_status = _license_status(authority, registry=str(registry), findings=findings)
        benchmark_sha, benchmark_issued = _benchmark_status(
            authority.get("benchmark_certificate"),
            role=role,
            reviewed_at=reviewed_at,
            findings=findings,
        )
        role_config = roles[role]
        rollback_alias = role_config.get("rollback")
        rollback_artifact_sha256 = None
        if not isinstance(rollback_alias, str) or not rollback_alias:
            findings.append("rollback_provider_missing")
            rollback_alias = None
        elif rollback_alias == active_alias:
            findings.append("rollback_provider_not_distinct")
        else:
            rollback_binding = catalog.get(rollback_alias)
            if (
                not isinstance(rollback_binding, Mapping)
                or rollback_binding.get("registry") not in authorities
            ):
                findings.append("rollback_provider_authority_missing")
            else:
                rollback_authority = authorities[str(rollback_binding["registry"])].get(
                    rollback_binding.get("key")
                )
                if not isinstance(rollback_authority, Mapping):
                    findings.append("rollback_provider_authority_missing")
                else:
                    rollback_artifact_sha256 = _artifact_sha256(rollback_authority)
                    if rollback_artifact_sha256 is None:
                        findings.append("rollback_provider_artifact_hash_missing")
        rollback_sha, rollback_tested = _rollback_status(
            rollback_records.get(role),
            role=role,
            active_provider=str(active_alias),
            rollback_provider=rollback_alias,
            pipeline_sha256=pipeline_sha256,
            active_artifact_sha256=artifact_sha256,
            rollback_artifact_sha256=rollback_artifact_sha256,
            reviewed_at=reviewed_at,
            findings=findings,
        )
        findings = sorted(set(findings))
        reviews.append(
            {
                "role": role,
                "provider_alias": str(active_alias),
                "registry": str(registry),
                "authority_key": authority_key,
                "lifecycle_state": str(lifecycle) if lifecycle is not None else None,
                "artifact_sha256": artifact_sha256,
                "runtime_identity": runtime,
                "license_status": license_status,
                "benchmark_certificate_sha256": benchmark_sha,
                "benchmark_issued_at": benchmark_issued,
                "rollback_provider": rollback_alias,
                "rollback_evidence_sha256": rollback_sha,
                "rollback_tested_at": rollback_tested,
                "findings": findings,
                "status": "pass" if not findings else "fail",
            }
        )
    if not reviews:
        global_findings.append("active_role_set_empty")
    return reviews, sorted(global_findings), active_role_digest


def generate_currency_signing_key(private_key_path: Path, public_key_path: Path) -> str:
    """Create one Ed25519 keypair, refusing to overwrite either side."""
    private_key_path = Path(private_key_path)
    public_key_path = Path(public_key_path)
    if private_key_path.exists() or public_key_path.exists():
        raise CurrencyReviewError(["signing_key_path_already_exists"])
    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    public_key_path.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_key_path.write_bytes(private_bytes)
    try:
        os.chmod(private_key_path, 0o600)
    except OSError:
        pass
    public_key_path.write_bytes(public_bytes)
    return hashlib.sha256(public_bytes).hexdigest()


def build_currency_review(
    *,
    event: str,
    reviewer: str,
    private_key_path: Path,
    pipeline_path: Path,
    external_registry_path: Path,
    model_registry_path: Path,
    rollback_evidence_path: Path,
    dependency_paths: Mapping[str, Path],
    reviewed_at: datetime | None = None,
    previous_review_sha256: str | None = None,
) -> dict[str, Any]:
    """Inspect current authority, sign the derived result, and never self-assert pass."""
    if event not in REVIEW_EVENTS:
        raise CurrencyReviewError(["review_event_invalid"])
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise CurrencyReviewError(["reviewer_missing"])
    if previous_review_sha256 is not None and not _is_sha256(previous_review_sha256):
        raise CurrencyReviewError(["previous_review_hash_invalid"])
    current = (reviewed_at or datetime.now(UTC)).astimezone(UTC)
    input_hashes = _input_hashes(
        pipeline_path=pipeline_path,
        external_registry_path=external_registry_path,
        model_registry_path=model_registry_path,
        rollback_evidence_path=rollback_evidence_path,
        dependency_paths=dependency_paths,
    )
    pipeline = _load_yaml(pipeline_path)
    external = _load_yaml(external_registry_path)
    models = _load_json(model_registry_path)
    rollback_document = _load_json(rollback_evidence_path)
    active_roles, global_findings, active_role_digest = _inspect_active_roles(
        pipeline=pipeline,
        external=external,
        models=models,
        rollback_document=rollback_document,
        pipeline_sha256=input_hashes["pipeline"],
        reviewed_at=current,
    )
    private_key = serialization.load_pem_private_key(
        Path(private_key_path).read_bytes(), password=None
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise CurrencyReviewError(["signing_key_type_invalid"])
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    base = {
        "schema_version": "1.0.0",
        "review_id": _canonical_sha256(
            {"event": event, "reviewed_at": current.isoformat(), "inputs": input_hashes}
        )[:24],
        "event": event,
        "reviewed_at": current.isoformat().replace("+00:00", "Z"),
        "expires_at": (current + timedelta(days=MAXIMUM_REVIEW_AGE_DAYS))
        .isoformat()
        .replace("+00:00", "Z"),
        "reviewer": reviewer.strip(),
        "signer_public_key_sha256": hashlib.sha256(public_bytes).hexdigest(),
        "input_hashes": input_hashes,
        "active_role_digest": active_role_digest,
        "active_roles": active_roles,
        "global_findings": global_findings,
        "status": (
            "pass"
            if not global_findings and all(row["status"] == "pass" for row in active_roles)
            else "fail"
        ),
        "previous_review_sha256": previous_review_sha256,
        "signature_algorithm": "ed25519",
    }
    payload = _canonical_bytes(base)
    base["payload_sha256"] = hashlib.sha256(payload).hexdigest()
    base["signature"] = base64.b64encode(private_key.sign(payload)).decode()
    base["review_sha256"] = _canonical_sha256(base)
    require_valid_document(base, "currency_review")
    return base


def verify_currency_review_signature(
    review: Mapping[str, Any], *, public_key_path: Path
) -> dict[str, str]:
    """Verify an immutable review signature without applying the current schema.

    Historical packets remain cryptographically verifiable after the active schema evolves;
    current packets are schema-validated when they are built and during live verification.
    """
    findings: list[str] = []
    if review.get("review_sha256") != _canonical_sha256(
        {key: value for key, value in review.items() if key != "review_sha256"}
    ):
        findings.append("currency_review_hash_mismatch")
    signed_payload = {
        key: value
        for key, value in review.items()
        if key not in {"payload_sha256", "signature", "review_sha256"}
    }
    payload = _canonical_bytes(signed_payload)
    if review.get("payload_sha256") != hashlib.sha256(payload).hexdigest():
        findings.append("currency_review_payload_hash_mismatch")
    public_bytes = Path(public_key_path).read_bytes()
    if review.get("signer_public_key_sha256") != hashlib.sha256(public_bytes).hexdigest():
        findings.append("currency_review_signer_mismatch")
    try:
        public_key = serialization.load_pem_public_key(public_bytes)
        if not isinstance(public_key, Ed25519PublicKey):
            raise TypeError
        public_key.verify(base64.b64decode(str(review["signature"]), validate=True), payload)
    except (ValueError, TypeError, InvalidSignature):
        findings.append("currency_review_signature_invalid")
    if findings:
        raise CurrencyReviewError(findings)
    return {
        "review_id": str(review["review_id"]),
        "review_sha256": str(review["review_sha256"]),
        "signer_public_key_sha256": str(review["signer_public_key_sha256"]),
    }


def verify_currency_review(
    review: Mapping[str, Any],
    *,
    public_key_path: Path,
    pipeline_path: Path,
    external_registry_path: Path,
    model_registry_path: Path,
    rollback_evidence_path: Path,
    dependency_paths: Mapping[str, Path],
    now: datetime | None = None,
    required_event: str | None = None,
    require_pass: bool = True,
) -> dict[str, Any]:
    """Verify signature, age, current hashes, and a fresh recomputation of every gate."""
    findings: list[str] = []
    try:
        require_valid_document(dict(review), "currency_review")
    except ArtifactValidationError:
        raise CurrencyReviewError(["currency_review_schema_invalid"]) from None
    if review.get("review_sha256") != _canonical_sha256(
        {key: value for key, value in review.items() if key != "review_sha256"}
    ):
        findings.append("currency_review_hash_mismatch")
    signed_payload = {
        key: value
        for key, value in review.items()
        if key not in {"payload_sha256", "signature", "review_sha256"}
    }
    payload = _canonical_bytes(signed_payload)
    if review.get("payload_sha256") != hashlib.sha256(payload).hexdigest():
        findings.append("currency_review_payload_hash_mismatch")
    public_bytes = Path(public_key_path).read_bytes()
    if review.get("signer_public_key_sha256") != hashlib.sha256(public_bytes).hexdigest():
        findings.append("currency_review_signer_mismatch")
    try:
        public_key = serialization.load_pem_public_key(public_bytes)
        if not isinstance(public_key, Ed25519PublicKey):
            raise TypeError
        public_key.verify(base64.b64decode(str(review["signature"]), validate=True), payload)
    except (ValueError, TypeError, InvalidSignature):
        findings.append("currency_review_signature_invalid")
    reviewed = _timestamp(review.get("reviewed_at"), "currency_review_timestamp_invalid", findings)
    expires = _timestamp(review.get("expires_at"), "currency_review_timestamp_invalid", findings)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if expires is not None and current > expires:
        findings.append("currency_review_expired")
    if reviewed is not None and (
        reviewed > current or current - reviewed > timedelta(days=MAXIMUM_REVIEW_AGE_DAYS)
    ):
        findings.append("currency_review_stale")
    if required_event is not None and review.get("event") != required_event:
        findings.append("currency_review_event_mismatch")
    current_inputs = _input_hashes(
        pipeline_path=pipeline_path,
        external_registry_path=external_registry_path,
        model_registry_path=model_registry_path,
        rollback_evidence_path=rollback_evidence_path,
        dependency_paths=dependency_paths,
    )
    if review.get("input_hashes") != current_inputs:
        findings.append("active_input_hash_mismatch")
    if reviewed is not None:
        active_roles, global_findings, active_role_digest = _inspect_active_roles(
            pipeline=_load_yaml(pipeline_path),
            external=_load_yaml(external_registry_path),
            models=_load_json(model_registry_path),
            rollback_document=_load_json(rollback_evidence_path),
            pipeline_sha256=current_inputs["pipeline"],
            reviewed_at=reviewed,
        )
        if review.get("active_roles") != active_roles:
            findings.append("active_role_review_mismatch")
        if review.get("active_role_digest") != active_role_digest:
            findings.append("active_role_digest_mismatch")
        if review.get("global_findings") != global_findings:
            findings.append("global_findings_mismatch")
        expected_status = (
            "pass"
            if not global_findings and all(row["status"] == "pass" for row in active_roles)
            else "fail"
        )
        if review.get("status") != expected_status:
            findings.append("currency_review_status_mismatch")
    if require_pass and review.get("status") != "pass":
        findings.extend(
            finding
            for row in review.get("active_roles", ())
            if isinstance(row, Mapping)
            for finding in row.get("findings", ())
        )
        findings.extend(review.get("global_findings", ()))
        findings.append("currency_review_not_passing")
    if findings:
        raise CurrencyReviewError(findings)
    return {
        "review_id": review["review_id"],
        "review_sha256": review["review_sha256"],
        "event": review["event"],
        "status": review["status"],
        "active_role_count": len(review["active_roles"]),
        "expires_at": review["expires_at"],
    }


__all__ = [
    "CurrencyReviewError",
    "MAXIMUM_REVIEW_AGE_DAYS",
    "REVIEW_EVENTS",
    "build_currency_review",
    "generate_currency_signing_key",
    "verify_currency_review",
    "verify_currency_review_signature",
]
