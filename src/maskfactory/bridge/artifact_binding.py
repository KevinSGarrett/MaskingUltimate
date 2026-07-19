"""Fail-closed, additive byte binding for bridge artifact consumption.

Frozen v1 request and receipt documents declare artifact identities.  This
module is the separate at-use boundary: it resolves the declared encoded and
canonical decoded bytes, rebinds all execution facts, and produces a
cache-safe decision without widening those wire documents.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from maskfactory.validation import canonical_document_sha256

POLICY_PATH = Path(__file__).parents[3] / "configs" / "bridge_artifact_consumption_policy.yaml"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "bridge_artifact_binding_decision.schema.json"
POLICY_ID = "maskfactory-bridge-artifact-consumption-v1"


class ArtifactConsumptionError(ValueError):
    """An artifact set cannot safely be consumed or reused."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _policy() -> dict[str, Any]:
    try:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactConsumptionError("artifact consumption policy is unavailable") from exc
    if policy.get("policy_id") != POLICY_ID:
        raise ArtifactConsumptionError("unexpected artifact consumption policy")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise ArtifactConsumptionError("artifact consumption policy hash mismatch")
    return policy


def _require_bytes(value: object, code: str, issues: list[str]) -> bytes | None:
    if not isinstance(value, bytes):
        issues.append(code)
        return None
    return value


def _binding(value: object, name: str, issues: list[str]) -> Mapping[str, bytes]:
    if not isinstance(value, Mapping):
        issues.append(f"{name}_evidence_missing")
        return {}
    return value


def _matches(actual: bytes | None, expected: object, code: str, issues: list[str]) -> str | None:
    if actual is None:
        return None
    digest = _sha256(actual)
    if not isinstance(expected, str) or digest != expected:
        issues.append(code)
    return digest


def _signed_revocation_identity(value: bytes | None, issues: list[str]) -> str | None:
    """Require a self-consistent signed revocation record before hashing it."""
    if value is None:
        return None
    try:
        record = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        issues.append("signed_revocation_identity_malformed")
        return _sha256(value)
    if not isinstance(record, Mapping):
        issues.append("signed_revocation_identity_malformed")
        return _sha256(value)
    signature = record.get("signature")
    trust_binding = record.get("trust_binding")
    payload = record.get("event_payload_sha256")
    if (
        not isinstance(signature, Mapping)
        or signature.get("signed_payload_sha256") != payload
        or not isinstance(payload, str)
        or not isinstance(trust_binding, Mapping)
        or trust_binding.get("key_role") != "producer_journal"
    ):
        issues.append("signed_revocation_identity_unverified")
    return _sha256(value)


def _provider_fingerprint(receipt: Mapping[str, Any]) -> tuple[str | None, str | None]:
    provider = receipt.get("provider_binding")
    if provider is None:
        return None, None
    if not isinstance(provider, Mapping):
        return "", ""
    components = {
        "stack_id": provider.get("stack_id"),
        "model_artifacts": provider.get("model_artifacts"),
        "workflow": provider.get("workflow"),
        "runtime": provider.get("runtime"),
    }
    stack = canonical_document_sha256(components)
    execution = canonical_document_sha256(
        {
            "provider_stack_sha256": stack,
            "route_selection": (receipt.get("execution_observation") or {}).get("route_selection"),
            "source_binding": receipt.get("source_binding"),
        }
    )
    return stack, execution


def _context(
    request: Mapping[str, Any],
    receipt: Mapping[str, Any],
    source: Mapping[str, str],
    artifacts: list[Mapping[str, Any]],
    qa_sha256: str | None,
    selection_sha256: str | None,
    revocation_sha256: str | None,
) -> dict[str, Any]:
    """Keep every authority-relevant fact in the cache identity."""
    provider_stack, execution_fingerprint = _provider_fingerprint(receipt)
    return {
        "request_payload_sha256": request.get("request_payload_sha256"),
        "receipt_payload_sha256": receipt.get("receipt_payload_sha256"),
        "release": receipt.get("release_binding"),
        "media_scope": request.get("media_scope"),
        "source": source,
        "decoder_color_orientation": {
            key: request.get("source", {}).get(key)
            for key in (
                "decoder",
                "exif_orientation",
                "orientation_applied",
                "channel_layout",
                "alpha_mode",
                "bit_depth",
                "dtype",
                "color_space",
                "icc_profile_sha256",
                "color_transform",
                "frame_extraction",
            )
        },
        "subject": request.get("subject"),
        "ontology": (request.get("compatibility") or {}).get("ontology_sha256"),
        "ontology_version": (request.get("compatibility") or {}).get("ontology_version"),
        "protected_inputs": request.get("protected_regions"),
        "protected_owner_roster": request.get("protected_owner_roster"),
        "artifacts": artifacts,
        "transform": request.get("transform_chain"),
        "provider_stack_sha256": provider_stack,
        "execution_fingerprint_sha256": execution_fingerprint,
        "qa_report_sha256": qa_sha256,
        "selection_evidence_sha256": selection_sha256,
        "authority": receipt.get("authority"),
        "lineage": receipt.get("lineage"),
        "revocation_identity_sha256": revocation_sha256,
    }


def build_artifact_consumption_decision(
    request: Mapping[str, Any],
    receipt: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    cached_decision: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve actual bytes and decide whether consumption/cache reuse is safe.

    ``evidence`` is deliberately byte-only at this boundary.  It must contain
    ``source`` (``encoded``, ``decoded_pixels``), ``artifacts`` keyed by
    artifact id (``encoded``, ``decoded_pixels``), ``qa_report``,
    ``selection_evidence``, and ``revocation_identity``.  A caller must
    canonicalize decoded pixels/masks with the declared decoder before calling;
    this function refuses an omitted or mismatched canonical byte stream.
    """
    policy = _policy()
    issues: list[str] = []
    source_evidence = _binding(evidence.get("source"), "source", issues)
    source_declared = request.get("source") if isinstance(request.get("source"), Mapping) else {}
    source_encoded = _require_bytes(
        source_evidence.get("encoded"), "source_encoded_missing", issues
    )
    source_pixels = _require_bytes(
        source_evidence.get("decoded_pixels"), "source_decoded_pixels_missing", issues
    )
    source = {
        "encoded_sha256": _matches(
            source_encoded, source_declared.get("encoded_sha256"), "source_encoded_drift", issues
        ),
        "decoded_pixel_sha256": _matches(
            source_pixels,
            source_declared.get("decoded_pixel_sha256"),
            "source_decoded_pixels_drift",
            issues,
        ),
    }

    evidence_artifacts = _binding(evidence.get("artifacts"), "output_artifacts", issues)
    receipt_artifacts = receipt.get("artifacts")
    if not isinstance(receipt_artifacts, list) or not receipt_artifacts:
        issues.append("output_artifacts_missing")
        receipt_artifacts = []
    resolved_artifacts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for artifact in receipt_artifacts:
        if not isinstance(artifact, Mapping):
            issues.append("output_artifact_ambiguous")
            continue
        artifact_id = artifact.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id or artifact_id in seen_ids:
            issues.append("output_artifact_ambiguous")
            continue
        seen_ids.add(artifact_id)
        actual = _binding(evidence_artifacts.get(artifact_id), f"output_{artifact_id}", issues)
        encoded = _require_bytes(actual.get("encoded"), "output_encoded_missing", issues)
        pixels = _require_bytes(
            actual.get("decoded_pixels"), "output_decoded_pixels_missing", issues
        )
        encoded_hash = _matches(
            encoded, artifact.get("encoded_sha256"), "output_encoded_drift", issues
        )
        decoded_hash = _matches(
            pixels, artifact.get("decoded_mask_sha256"), "output_decoded_pixels_drift", issues
        )
        resolved = {
            "artifact_id": artifact_id,
            "artifact_identity_sha256": artifact.get("artifact_identity_sha256"),
            "encoded_sha256": encoded_hash,
            "decoded_mask_sha256": decoded_hash,
            "mask_type": artifact.get("mask_type"),
            "owner": artifact.get("owner"),
            "source_decoded_pixel_sha256": artifact.get("source_decoded_pixel_sha256"),
            "transform_chain_sha256": artifact.get("transform_chain_sha256"),
            "label": artifact.get("label"),
            "artifact_kind": artifact.get("artifact_kind"),
        }
        if artifact.get("source_decoded_pixel_sha256") != source["decoded_pixel_sha256"]:
            issues.append("output_source_pixel_binding_drift")
        expected_identity = canonical_document_sha256(
            {
                "artifact_id": artifact.get("artifact_id"),
                "intent_id": artifact.get("intent_id"),
                "label": artifact.get("label"),
                "artifact_kind": artifact.get("artifact_kind"),
                "mask_type": artifact.get("mask_type"),
                "owner": artifact.get("owner"),
                "encoded_sha256": encoded_hash,
                "decoded_mask_sha256": decoded_hash,
                "source_decoded_pixel_sha256": artifact.get("source_decoded_pixel_sha256"),
                "width": artifact.get("width"),
                "height": artifact.get("height"),
                "coordinate_space": artifact.get("coordinate_space"),
                "transform_chain_sha256": artifact.get("transform_chain_sha256"),
            }
        )
        if artifact.get("artifact_identity_sha256") != expected_identity:
            issues.append("output_artifact_identity_drift")
        resolved_artifacts.append(resolved)
    if set(evidence_artifacts) != seen_ids:
        issues.append("output_artifact_evidence_ambiguous")

    qa = _require_bytes(evidence.get("qa_report"), "qa_report_missing", issues)
    selection = _require_bytes(
        evidence.get("selection_evidence"), "selection_evidence_missing", issues
    )
    certificate = evidence.get("certificate")
    authority = receipt.get("authority") if isinstance(receipt.get("authority"), Mapping) else {}
    certificate_sha256 = authority.get("certificate_sha256")
    if certificate_sha256 is not None:
        certificate = _require_bytes(certificate, "certificate_missing", issues)
        _matches(certificate, certificate_sha256, "certificate_drift", issues)
    elif certificate is not None:
        issues.append("certificate_evidence_ambiguous")
    revocation = _require_bytes(
        evidence.get("revocation_identity"), "revocation_identity_missing", issues
    )
    qa_sha256 = _matches(
        qa, (receipt.get("qa") or {}).get("report_sha256"), "qa_report_drift", issues
    )
    selection_sha256 = _matches(
        selection,
        ((receipt.get("execution_observation") or {}).get("route_selection") or {}).get(
            "selection_evidence_sha256"
        ),
        "selection_evidence_drift",
        issues,
    )
    revocation_sha256 = _signed_revocation_identity(revocation, issues)
    if authority.get("revocation_index_sha256") != revocation_sha256:
        issues.append("signed_revocation_identity_drift")
    if policy["require_active_authority"] and (
        authority.get("certificate_status") not in {"active", "none"}
        or authority.get("authority_state") == "invalid"
    ):
        issues.append("authority_not_current")
    provider_stack, execution_fingerprint = _provider_fingerprint(receipt)
    provider = receipt.get("provider_binding")
    if isinstance(provider, Mapping) and (
        provider.get("stack_sha256") != provider_stack
        or provider.get("execution_fingerprint_sha256") != execution_fingerprint
    ):
        issues.append("provider_runtime_workflow_drift")

    context = _context(
        request, receipt, source, resolved_artifacts, qa_sha256, selection_sha256, revocation_sha256
    )
    cache_key = canonical_document_sha256({"policy_sha256": policy["policy_sha256"], **context})
    cache_reused = False
    if cached_decision is not None:
        if (
            cached_decision.get("status") == "accepted"
            and cached_decision.get("cache_key_sha256") == cache_key
            and cached_decision.get("policy_sha256") == policy["policy_sha256"]
        ):
            cache_reused = not issues
        else:
            issues.append("cache_reuse_stale_or_ambiguous")
    decision = {
        "schema_version": "1.0.0",
        "record_type": "bridge_artifact_binding_decision",
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "cache_key_sha256": cache_key,
        "cache_reused": cache_reused,
        "status": "accepted" if not issues else "rejected",
        "rejection_reasons": sorted(set(issues)),
        "consumed_context": context,
        "decision_sha256": "",
    }
    decision["decision_sha256"] = canonical_document_sha256(
        decision, excluded_top_level_fields=("decision_sha256",)
    )
    return decision


def validate_artifact_consumption_decision(decision: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate a materialized decision, its current policy, and self-hash."""
    issues: list[str] = []
    try:
        policy = _policy()
    except ArtifactConsumptionError as exc:
        return (str(exc),)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    for error in Draft202012Validator(schema).iter_errors(dict(decision)):
        issues.append(f"schema:{error.validator}")
    if (
        decision.get("policy_id") != policy["policy_id"]
        or decision.get("policy_sha256") != policy["policy_sha256"]
    ):
        issues.append("policy_drift")
    expected = canonical_document_sha256(decision, excluded_top_level_fields=("decision_sha256",))
    if decision.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")
    accepted = decision.get("status") == "accepted"
    if accepted != (not decision.get("rejection_reasons")):
        issues.append("decision_status_reasons")
    return tuple(sorted(set(issues)))
