"""Mode A immutable package reads with fail-closed authority caps.

Raw package manifests, review statuses, filenames, and certificate references
are never production authority. Production eligibility requires a separate
active exact-output operational wrapper whose bindings match observed bytes.
This module exposes no package write path.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

from maskfactory.bridge.transforms import TransformValidationError, build_roundtrip_evidence
from maskfactory.validation import canonical_document_sha256

POLICY_PATH = Path(__file__).parents[3] / "configs" / "bridge_mode_a_package_read_policy.yaml"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "mode_a_package_read_evidence.schema.json"
POLICY_ID = "maskfactory-bridge-mode-a-package-read-v1"


class ModeAPackageReadError(ValueError):
    """Raised when Mode A policy or closed inputs cannot be evaluated."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ModeAPackageReadError("mode a package read policy is unavailable") from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise ModeAPackageReadError("unexpected mode a package read policy")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise ModeAPackageReadError("mode a package read policy hash mismatch")
    if policy.get("allow_write_methods") is not False:
        raise ModeAPackageReadError("mode a package read policy must forbid writes")
    return dict(policy)


def _ordered(policy: Mapping[str, Any], reasons: list[str]) -> list[str]:
    return [code for code in policy["reason_codes"] if code in set(reasons)]


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _require_bytes(value: object) -> bytes | None:
    return value if isinstance(value, bytes) else None


def _path_escape(package_root: object, relative: object) -> bool:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return True
    normalized = relative.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts) or normalized.startswith("/"):
        return True
    if package_root is None:
        return False
    root = Path(str(package_root)).resolve()
    candidate = (root / Path(*parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return True
    return candidate == root


def _catalog_entry(
    catalog: Mapping[str, Any], image_id: object, person_index: object, label: object
) -> Mapping[str, Any]:
    packages = catalog.get("packages")
    if not isinstance(packages, list):
        return {}
    for row in packages:
        if not isinstance(row, Mapping):
            continue
        if (
            row.get("image_id") == image_id
            and row.get("person_index") == person_index
            and row.get("label") == label
        ):
            return row
    return {}


def _signed_revocation_head(value: bytes | None, reasons: list[str]) -> str | None:
    if value is None:
        reasons.append("revocation_not_current")
        return None
    try:
        record = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        reasons.append("revocation_not_current")
        return _sha256(value)
    if not isinstance(record, Mapping):
        reasons.append("revocation_not_current")
        return _sha256(value)
    signature = record.get("signature")
    trust = record.get("trust_binding")
    payload = record.get("event_payload_sha256")
    if (
        not isinstance(signature, Mapping)
        or signature.get("signed_payload_sha256") != payload
        or not isinstance(payload, str)
        or not isinstance(trust, Mapping)
        or trust.get("key_role") != "producer_journal"
    ):
        reasons.append("revocation_not_current")
    return _sha256(value)


def _validate_transform(
    request: Mapping[str, Any], expected_chain_sha256: object, reasons: list[str]
) -> tuple[str | None, bool | None]:
    chain = request.get("transform_chain")
    if not isinstance(chain, Mapping):
        reasons.append("transform_not_validated")
        return None, None
    chain_sha = chain.get("chain_sha256")
    if not isinstance(chain_sha, str) or (
        isinstance(expected_chain_sha256, str) and chain_sha != expected_chain_sha256
    ):
        reasons.append("transform_drift")
    probes = request.get("transform_probes")
    if not isinstance(probes, list) or not probes:
        reasons.append("transform_not_validated")
        return chain_sha if isinstance(chain_sha, str) else None, False
    try:
        evidence = build_roundtrip_evidence(
            chain,
            probes,
            protected_regions=list(request.get("protected_regions") or ()),
            expected_protected_regions=list(request.get("expected_protected_regions") or ()),
        )
    except TransformValidationError:
        reasons.append("transform_not_validated")
        return chain_sha if isinstance(chain_sha, str) else None, False
    return evidence.get("transform_chain_sha256"), bool(evidence.get("roundtrip_passed"))


def _wrapper_status(
    *,
    policy: Mapping[str, Any],
    request: Mapping[str, Any],
    wrapper: Mapping[str, Any] | None,
    observed: Mapping[str, Any],
    revocation_head_sha256: str | None,
    decided_at: str,
    reasons: list[str],
) -> str:
    production = request.get("exact_use_scope") in set(policy["production_use_scopes"])
    if wrapper is None:
        if production:
            reasons.append("wrapper_missing")
        return "none"
    if wrapper.get("status") != "active":
        reasons.append("wrapper_stale")
        return "stale"
    valid_until = _utc(wrapper.get("valid_until"))
    use_time = _utc(decided_at)
    if valid_until is None or use_time is None or use_time > valid_until:
        reasons.append("wrapper_stale")
        return "stale"
    revoked = wrapper.get("revocation_status")
    if revoked in {"revoked", "superseded", "expired"}:
        reasons.append("wrapper_revoked")
        return "revoked"
    revoked_payloads = wrapper.get("revoked_by_head_sha256")
    if isinstance(revoked_payloads, str) and revocation_head_sha256 == revoked_payloads:
        reasons.append("wrapper_revoked")
        return "revoked"
    required_bindings = {
        "source_encoded_sha256": observed.get("source_encoded_sha256"),
        "source_decoded_pixel_sha256": observed.get("source_decoded_pixel_sha256"),
        "mask_encoded_sha256": observed.get("mask_encoded_sha256"),
        "mask_decoded_sha256": observed.get("mask_decoded_sha256"),
        "package_sha256": observed.get("package_sha256"),
        "manifest_sha256": observed.get("manifest_sha256"),
        "ontology_sha256": observed.get("ontology_sha256"),
        "transform_chain_sha256": observed.get("transform_chain_sha256"),
        "owner_id": observed.get("owner_id"),
        "scene_instance_id": observed.get("scene_instance_id"),
        "person_index": observed.get("person_index"),
        "label": observed.get("label"),
        "exact_use_scope": request.get("exact_use_scope"),
    }
    bindings = wrapper.get("exact_output_bindings")
    if not isinstance(bindings, Mapping):
        reasons.append("wrapper_out_of_scope")
        return "out_of_scope"
    for key, expected in required_bindings.items():
        if bindings.get(key) != expected:
            reasons.append("wrapper_out_of_scope")
            return "out_of_scope"
    permitted = wrapper.get("permitted_use_scopes")
    if not isinstance(permitted, list) or request.get("exact_use_scope") not in permitted:
        reasons.append("wrapper_out_of_scope")
        return "out_of_scope"
    certificate_sha = wrapper.get("certificate_payload_sha256")
    if not isinstance(certificate_sha, str):
        reasons.append("wrapper_out_of_scope")
        return "out_of_scope"
    return "active"


def evaluate_mode_a_package_read(
    request: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    decided_at: str,
) -> dict[str, Any]:
    """Evaluate an immutable Mode A package read and return typed evidence.

    ``evidence`` is byte- and catalog-bound. It must not mutate package truth.
    Raw part status never upgrades authority; production scopes require a
    separate active exact operational wrapper matched to observed bytes.
    """
    policy = _policy()
    reasons: list[str] = []
    catalog = _mapping(evidence.get("catalog"))
    package_bytes = _mapping(evidence.get("bytes"))
    relative_paths = _mapping(evidence.get("relative_paths"))
    subject = _mapping(request.get("subject"))
    image_id = request.get("image_id")
    person_index = request.get("person_index")
    label = request.get("label")
    exact_use_scope = request.get("exact_use_scope")
    artifact_kind = request.get("artifact_kind") or "atomic"
    production = exact_use_scope in set(policy["production_use_scopes"])
    allowed_scopes = set(policy["production_use_scopes"]) | set(policy["non_production_use_scopes"])
    if exact_use_scope not in allowed_scopes:
        raise ModeAPackageReadError("unknown exact use scope")

    if evidence.get("write_requested") is True or evidence.get("mutation_target") is not None:
        reasons.append("mutation_attempt")
        reasons.append("write_path_forbidden")

    if catalog.get("adoption_decision") != "adopted" or catalog.get("release_status") != "adopted":
        reasons.append("catalog_not_adopted")

    source_rel = relative_paths.get("source")
    mask_rel = relative_paths.get("mask")
    manifest_rel = relative_paths.get("manifest")
    package_root = evidence.get("package_root")
    for relative in (source_rel, mask_rel, manifest_rel):
        if relative is not None and _path_escape(package_root, relative):
            reasons.append("path_escape")
            break

    source_encoded = _require_bytes(package_bytes.get("source_encoded"))
    source_pixels = _require_bytes(package_bytes.get("source_decoded_pixels"))
    mask_encoded = _require_bytes(package_bytes.get("mask_encoded"))
    mask_pixels = _require_bytes(package_bytes.get("mask_decoded_pixels"))
    manifest_raw = _require_bytes(package_bytes.get("manifest"))
    ontology_raw = _require_bytes(package_bytes.get("ontology"))
    release_raw = _require_bytes(package_bytes.get("release"))
    capability_raw = _require_bytes(package_bytes.get("capability"))
    revocation_raw = _require_bytes(package_bytes.get("revocation_identity"))

    observed_source_encoded = _sha256(source_encoded) if source_encoded is not None else None
    observed_source_pixels = _sha256(source_pixels) if source_pixels is not None else None
    observed_mask_encoded = _sha256(mask_encoded) if mask_encoded is not None else None
    observed_mask_pixels = _sha256(mask_pixels) if mask_pixels is not None else None
    observed_manifest = _sha256(manifest_raw) if manifest_raw is not None else None
    observed_ontology = _sha256(ontology_raw) if ontology_raw is not None else None
    observed_release = _sha256(release_raw) if release_raw is not None else None
    observed_capability = _sha256(capability_raw) if capability_raw is not None else None
    package_material = {
        "source_encoded_sha256": observed_source_encoded,
        "source_decoded_pixel_sha256": observed_source_pixels,
        "mask_encoded_sha256": observed_mask_encoded,
        "mask_decoded_sha256": observed_mask_pixels,
        "manifest_sha256": observed_manifest,
        "ontology_sha256": observed_ontology,
        "image_id": image_id,
        "person_index": person_index,
        "label": label,
    }
    observed_package = canonical_document_sha256(package_material)

    entry = _catalog_entry(catalog, image_id, person_index, label)
    if not entry:
        reasons.append("catalog_not_adopted")
    else:
        checks = (
            ("source_encoded_sha256", observed_source_encoded, "source_hash_drift"),
            ("source_decoded_pixel_sha256", observed_source_pixels, "source_hash_drift"),
            ("mask_encoded_sha256", observed_mask_encoded, "mask_hash_drift"),
            ("mask_decoded_sha256", observed_mask_pixels, "mask_hash_drift"),
            ("manifest_sha256", observed_manifest, "manifest_hash_drift"),
            ("package_sha256", observed_package, "package_hash_drift"),
            ("ontology_sha256", observed_ontology, "ontology_mismatch"),
        )
        for field, actual, code in checks:
            expected = entry.get(field)
            if actual is None or not isinstance(expected, str) or actual != expected:
                reasons.append(code)
        if entry.get("ontology_version") != request.get("ontology_version"):
            reasons.append("ontology_mismatch")
        if entry.get("owner_id") != subject.get("canonical_person_id"):
            reasons.append("wrong_owner")
        if entry.get("scene_instance_id") != subject.get("scene_instance_id"):
            reasons.append("instance_mismatch")
        if entry.get("character_revision") != subject.get("character_revision"):
            reasons.append("character_revision_mismatch")
        if entry.get("person_index") != person_index:
            reasons.append("person_mismatch")

    if catalog.get("release_payload_sha256") != observed_release:
        reasons.append("release_capability_drift")
    if catalog.get("capability_snapshot_sha256") != observed_capability:
        reasons.append("release_capability_drift")

    raw_part_status = request.get("raw_part_status")
    if not isinstance(raw_part_status, str):
        raw_part_status = entry.get("raw_part_status") if entry else None
    if isinstance(raw_part_status, str) and raw_part_status in set(
        policy["rejected_part_statuses"]
    ):
        reasons.append("rejected_part_status")

    claimed = request.get("claimed_authority_state")
    if request.get("escalate_raw_status") is True:
        reasons.append("raw_status_escalation")
    if isinstance(claimed, str) and claimed not in {policy["raw_authority_ceiling"], "certified"}:
        reasons.append("raw_status_escalation")

    transform_sha, roundtrip_passed = _validate_transform(
        request, entry.get("transform_chain_sha256") if entry else None, reasons
    )
    revocation_head_sha256 = _signed_revocation_head(revocation_raw, reasons)

    observed = {
        "image_id": image_id if isinstance(image_id, str) else None,
        "person_index": (
            person_index
            if isinstance(person_index, int) and not isinstance(person_index, bool)
            else None
        ),
        "label": label if isinstance(label, str) else None,
        "artifact_kind": artifact_kind if isinstance(artifact_kind, str) else None,
        "raw_part_status": raw_part_status if isinstance(raw_part_status, str) else None,
        "owner_id": (
            subject.get("canonical_person_id")
            if isinstance(subject.get("canonical_person_id"), str)
            else None
        ),
        "scene_instance_id": (
            subject.get("scene_instance_id")
            if isinstance(subject.get("scene_instance_id"), str)
            else None
        ),
        "character_revision": (
            subject.get("character_revision")
            if isinstance(subject.get("character_revision"), str)
            else None
        ),
        "source_encoded_sha256": observed_source_encoded,
        "source_decoded_pixel_sha256": observed_source_pixels,
        "mask_encoded_sha256": observed_mask_encoded,
        "mask_decoded_sha256": observed_mask_pixels,
        "manifest_sha256": observed_manifest,
        "package_sha256": observed_package,
        "ontology_sha256": observed_ontology,
        "ontology_version": (
            request.get("ontology_version")
            if isinstance(request.get("ontology_version"), str)
            else None
        ),
        "transform_chain_sha256": transform_sha,
        "transform_roundtrip_passed": roundtrip_passed,
        "release_payload_sha256": observed_release,
        "capability_snapshot_sha256": observed_capability,
        "revocation_head_sha256": revocation_head_sha256,
        "wrapper_certificate_sha256": None,
        "wrapper_status": "none",
    }

    wrapper = evidence.get("wrapper")
    wrapper_map = wrapper if isinstance(wrapper, Mapping) else None
    wrapper_status = _wrapper_status(
        policy=policy,
        request=request,
        wrapper=wrapper_map,
        observed=observed,
        revocation_head_sha256=revocation_head_sha256,
        decided_at=decided_at,
        reasons=reasons,
    )
    observed["wrapper_status"] = wrapper_status
    if wrapper_map is not None and isinstance(wrapper_map.get("certificate_payload_sha256"), str):
        observed["wrapper_certificate_sha256"] = wrapper_map["certificate_payload_sha256"]

    if artifact_kind in set(policy["derived_kinds_requiring_own_wrapper"]):
        if request.get("claim_parent_authority") is True or (
            request.get("parent_authority_state") == "certified" and wrapper_status != "active"
        ):
            reasons.append("derived_authority_escalation")
        if production and wrapper_status != "active":
            reasons.append("derived_authority_escalation")

    # Raw status / claimed certified without an active exact wrapper never escalates.
    if claimed == "certified" and wrapper_status != "active":
        reasons.append("raw_status_escalation")
    if (
        isinstance(raw_part_status, str)
        and raw_part_status in {"human_approved_gold", "certificate_reference"}
        and wrapper_status != "active"
        and production
    ):
        reasons.append("raw_status_escalation")

    ordered = _ordered(policy, reasons)
    wrapper_ok = wrapper_status == "active" and not ordered
    if wrapper_ok:
        authority_ceiling = "certified"
        production_eligible = bool(production)
        accepted = True
    else:
        authority_ceiling = policy["raw_authority_ceiling"]
        production_eligible = False
        accepted = (not production) and (not ordered)

    entry_sha = (
        canonical_document_sha256(entry, excluded_top_level_fields=("catalog_entry_sha256",))
        if entry
        else None
    )
    evidence_doc = {
        "schema_version": "1.0.0",
        "record_type": "mode_a_package_read_evidence",
        "decided_at": decided_at,
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "access_mode": "mode_a_package_read",
        "exact_use_scope": exact_use_scope,
        "status": "accepted" if accepted else "rejected",
        "authority_ceiling": authority_ceiling,
        "production_eligible": production_eligible,
        "rejection_reasons": ordered,
        "observed": observed,
        "immutable_handles": {
            "package_id": entry.get("package_id") if entry else None,
            "package_revision": entry.get("package_revision") if entry else None,
            "artifact_id": entry.get("artifact_id") if entry else None,
            "catalog_entry_sha256": entry_sha,
            "mask_relative_path": mask_rel if isinstance(mask_rel, str) else None,
            "source_relative_path": source_rel if isinstance(source_rel, str) else None,
        },
        "write_methods_exposed": False,
        "decision_sha256": "",
    }
    evidence_doc["decision_sha256"] = canonical_document_sha256(
        evidence_doc, excluded_top_level_fields=("decision_sha256",)
    )
    return evidence_doc


def validate_mode_a_package_read_evidence(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate schema, policy binding, hash, and write-path closure."""
    issues: list[str] = []
    try:
        policy = _policy()
    except ModeAPackageReadError as exc:
        return (str(exc),)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    issues.extend(
        f"schema:{error.validator}"
        for error in Draft202012Validator(schema).iter_errors(dict(evidence))
    )
    if (
        evidence.get("policy_id") != policy["policy_id"]
        or evidence.get("policy_sha256") != policy["policy_sha256"]
    ):
        issues.append("policy_drift")
    expected = canonical_document_sha256(evidence, excluded_top_level_fields=("decision_sha256",))
    if evidence.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")
    allowed = set(policy["reason_codes"])
    reasons = evidence.get("rejection_reasons")
    if not isinstance(reasons, list) or not set(reasons).issubset(allowed):
        issues.append("decision_reason_code")
    if evidence.get("write_methods_exposed") is not False:
        issues.append("write_path_forbidden")
    if evidence.get("status") == "accepted" and reasons:
        issues.append("decision_status_reasons")
    if evidence.get("status") == "rejected" and not reasons:
        issues.append("decision_status_reasons")
    if (
        evidence.get("production_eligible") is True
        and evidence.get("authority_ceiling") != "certified"
    ):
        issues.append("production_authority_incoherent")
    if (
        evidence.get("authority_ceiling") == "certified"
        and _mapping(evidence.get("observed")).get("wrapper_status") != "active"
    ):
        issues.append("certified_without_active_wrapper")
    return tuple(sorted(set(issues)))


__all__ = [
    "ModeAPackageReadError",
    "evaluate_mode_a_package_read",
    "validate_mode_a_package_read_evidence",
]
