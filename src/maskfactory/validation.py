"""Schema validation and package-level invariants for MaskFactory artifacts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_DIR = Path(__file__).with_name("schemas")
SCHEMA_NAMES = frozenset(
    {
        "manifest",
        "manifest_v2",
        "manifest_synthetic_v1",
        "manifest_synthetic_v2",
        "qa_report",
        "model_registry",
        "acquisition_plan",
        "failure_queue",
        "failure_mining_static_report",
        "cloud_teacher_static_report",
        "shadow_teacher_judgment",
        "geometry_variant_benchmark_cases",
        "geometry_variant_benchmark_policy",
        "geometry_variant_benchmark_report",
        "coverage_matrix",
        "coverage_matrix_v2",
        "leaderboard",
        "training_static_gates_report",
        "mediapipe_vote_ablation_cases",
        "mediapipe_vote_ablation_policy",
        "mediapipe_vote_ablation_report",
        "pose_variant_benchmark_cases",
        "pose_variant_benchmark_policy",
        "pose_variant_benchmark_report",
        "provider_benchmark_matrix_manifest",
        "provider_benchmark_matrix_observations",
        "provider_benchmark_matrix_policy",
        "provider_benchmark_matrix_report",
        "matrix_promotion_certificate",
        "interactive_provider_promotion_certificate",
        "interactive_provider_transaction",
        "interactive_provider_rollback",
        "multi_person_family_availability_policy",
        "multi_person_lifecycle_route",
        "multi_person_static_contracts_report",
        "multi_person_tournament_evidence",
        "multi_person_tournament_execution",
        "sam31_shadow_candidate_package",
        "sam31_shadow_orchestration",
        "sam31_repair_orchestration",
        "sam31_visual_exemplar",
        "qwen_challenger_benchmark_cases",
        "qwen_challenger_benchmark_policy",
        "qwen_challenger_benchmark_report",
        "retraining_operations_input",
        "retraining_operations_policy",
        "retraining_operations_report",
        "silhouette_variant_benchmark_cases",
        "silhouette_variant_benchmark_policy",
        "silhouette_variant_benchmark_report",
        "crop_transform",
        "autonomy_lifecycle",
        "autonomy_multi_person_risk_buckets",
        "autonomy_metrics",
        "autonomy_metrics_inputs",
        "autonomy_risk_buckets",
        "autonomy_stability",
        "operational_policy_evidence",
        "completion_bundle_input",
        "completion_bundle_policy",
        "completion_bundle_report",
        "currency_review",
        "custom_segmenter_tournament_policy",
        "custom_segmenter_tournament_report",
        "custom_segmenter_tournament_runs",
        "custom_segmenter_benchmark_margins",
        "custom_segmenter_champion_rollback",
        "custom_segmenter_champion_transaction",
        "daz_operating_profile",
        "daz_acquisition_capacity",
        "daz_asset_identity_snapshot",
        "daz_asset_compatibility_graph",
        "daz_asset_pool_report",
        "daz_asset_smoke_plan",
        "daz_asset_smoke_result",
        "daz_asset_smoke_certificate",
        "daz_asset_quarantine",
        "daz_resolved_scene_recipe",
        "daz_character_foundation_selection",
        "daz_character_variation_profile",
        "daz_character_profile_batch_report",
        "daz_character_appearance_selection",
        "daz_coverage_vocabulary_report",
        "daz_candidate_batch_report",
        "daz_candidate_selection_report",
        "daz_concentration_report",
        "daz_planner_feedback_report",
        "daz_real_deficit_signal_report",
        "daz_solo_pose_selection",
        "daz_duo_recipe_selection",
        "daz_multi_person_identity_report",
        "daz_multi_person_relationship_record",
        "daz_p_index_assignment",
        "daz_scene_formation_selection",
        "daz_scene_preflight_report",
        "daz_resolved_scene_state",
        "daz_render_pass_plan",
        "daz_render_pass_execution_report",
        "daz_pristine_rgb_request",
        "daz_pristine_rgb_fixture_report",
        "daz_instance_pass_contract",
        "daz_instance_pass_report",
        "daz_part_pass_contract",
        "daz_part_pass_report",
        "daz_material_protected_contract",
        "daz_material_protected_report",
        "daz_coverage_alpha_contract",
        "daz_coverage_alpha_report",
        "daz_geometry_coordinates",
        "daz_geometry_pass_contract",
        "daz_geometry_pass_report",
        "daz_relationship_pass_contract",
        "daz_relationship_pass_report",
        "daz_package_derivation_contract",
        "daz_package_derivation_report",
        "daz_same_state_replay_report",
        "daz_validation_result",
        "daz_validation_set_report",
        "daz_repair_request",
        "daz_repair_history",
        "daz_acceptance_certificate",
        "daz_s00_adapter_report",
        "daz_adapted_package_qc_report",
        "daz_paths",
        "daz_runtime",
        "daz_cms_snapshot",
        "daz_dim_manifest_snapshot",
        "daz_filesystem_inventory_snapshot",
        "daz_ontology_snapshot",
        "daz_ontology_v2_snapshot",
        "daz_engineering_fixture_set",
        "daz_procedural_primitive_bundle",
        "daz_worker_mode_decision_static_report",
        "daz_clean_restart_static_report",
        "external_supervision_holdout_ablation_report",
        "daz_scene_recipe",
        "daz_training_policy",
        "daz_worker",
        "daz_worker_result",
        "serving_provenance",
        "serving_route",
        "serving_static_contracts_report",
        "serving_workflow_performance_policy",
        "serving_workflow_performance_report",
        "serving_workflow_execution_input",
        "serving_workflow_preflight_report",
        "specialist_benchmark_margins",
        "specialist_champion_rollback",
        "specialist_champion_transaction",
        "specialist_evidence_package",
        "completion_profile",
        "maskfactory_qualification_bundle",
        "operational_autonomy_certificate",
        "operational_invalidation_event",
        "autonomous_gold_demonstration_report",
        "bridge_error_decision",
        "bridge_artifact_binding_decision",
        "bridge_use_eligibility_decision",
        "bridge_adoption_receipt_matrix_decision",
        "bridge_final_release_handoff_evidence",
        "bridge_consumer_invalidation_decision",
        "bridge_crosswalk",
        "cross_project_qualification_evidence",
        "external_adapter_conformance_evidence",
        "main_consumer_conformance_evidence",
        "mode_b_localhost_client_response",
        "mode_a_vertical_slice_evidence",
        "mode_b_vertical_slice_evidence",
        "multi_person_mode_a_vertical_slice_evidence",
        "maskfactory_release_publication_evidence",
        "maskfactory_integration_release_evidence",
        "maskfactory_release_snapshot",
        "maskfactory_clean_release_manifest",
        "maskfactory_capability_decision",
        "maskfactory_capability_snapshot",
        "maskfactory_consumer_requirements_admission",
        "maskfactory_consumer_requirements",
        "mask_acquisition_request",
        "mask_acquisition_receipt",
        "mask_bridge_error",
        "maskfactory_adoption_receipt",
        "mask_authority_invalidation_event",
        "mask_repair_feedback",
        "mask_bridge_event",
        "mask_bridge_semantic_invariant_profile",
        "bridge_identity_decision",
        "bridge_transform_roundtrip_evidence",
        "mode_a_package_read_evidence",
        "receipt_arbitration_conformance_evidence",
        "bridge_failure_control_evidence",
        "bridge_recovery_evidence",
        "bridge_journal_reconstruction_evidence",
        "feedback_intake_evidence",
        "external_supervision_qualification_evidence",
        "external_supervision_source_hash_manifest",
        "external_supervision_identity_evidence",
        "external_supervision_split_dedup_evidence",
    }
)
VISIBLE_STATES = frozenset({"visible", "partially_visible"})
AUTHORITY_RANK = {
    "invalid": 0,
    "hypothesis": 1,
    "draft": 2,
    "qa_passed_noncertified": 3,
    "certified": 4,
}


def _escape_pointer(token: object) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def _pointer(path: Iterable[object]) -> str:
    tokens = [_escape_pointer(token) for token in path]
    return "" if not tokens else "/" + "/".join(tokens)


@dataclass(frozen=True, order=True)
class ValidationIssue:
    """One stable validation finding with an RFC 6901 JSON pointer."""

    pointer: str
    validator: str
    message: str


class ArtifactValidationError(ValueError):
    """Raised when schema or package-invariant validation fails."""

    def __init__(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues = tuple(sorted(issues))
        detail = "; ".join(
            f"{issue.pointer or '/'} [{issue.validator}] {issue.message}" for issue in self.issues
        )
        super().__init__(detail)


@lru_cache(maxsize=None)
def schema_validator(schema_name: str) -> Draft202012Validator:
    """Load and compile one named, bundled Draft 2020-12 schema."""
    if schema_name not in SCHEMA_NAMES:
        allowed = ", ".join(sorted(SCHEMA_NAMES))
        raise KeyError(f"unknown schema {schema_name!r}; expected one of: {allowed}")
    path = SCHEMA_DIR / f"{schema_name}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_document(document: Any, schema_name: str) -> tuple[ValidationIssue, ...]:
    """Return deterministic structural findings for a JSON-compatible document."""
    errors = schema_validator(schema_name).iter_errors(document)
    issues = (
        ValidationIssue(
            pointer=_pointer(error.absolute_path),
            validator=str(error.validator),
            message=error.message,
        )
        for error in errors
    )
    return tuple(sorted(issues))


def _manifest_invariant_issues(
    manifest: Mapping[str, Any], enabled_labels: Iterable[str]
) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    parts = manifest.get("parts")
    if not isinstance(parts, Mapping):
        return ()

    enabled = set(enabled_labels)
    missing = sorted(enabled.difference(parts))
    if missing:
        issues.append(
            ValidationIssue(
                pointer="/parts",
                validator="enabled_labels_complete",
                message="missing enabled ontology labels: " + ", ".join(missing),
            )
        )

    gold_present = False
    for label, raw_entry in sorted(parts.items()):
        if not isinstance(raw_entry, Mapping):
            continue
        entry = raw_entry
        pointer = "/parts/" + _escape_pointer(label)
        if (
            entry.get("mask_type") == "atomic_exclusive"
            and entry.get("visibility") not in VISIBLE_STATES
            and entry.get("mask_file") is not None
        ):
            issues.append(
                ValidationIssue(
                    pointer=pointer + "/mask_file",
                    validator="nonvisible_atomic_has_no_mask",
                    message="atomic mask_file must be null unless visibility is visible or partially_visible",
                )
            )
        gold_present = gold_present or entry.get("status") == "human_approved_gold"

    if gold_present:
        qa = manifest.get("qa")
        qa_overall = qa.get("qa_overall") if isinstance(qa, Mapping) else None
        if qa_overall != "pass":
            issues.append(
                ValidationIssue(
                    pointer="/qa/qa_overall",
                    validator="gold_requires_qa_pass",
                    message="human_approved_gold requires qa_overall=pass",
                )
            )
        review = manifest.get("review")
        review_complete = isinstance(review, Mapping) and all(
            review.get(field) is not None
            for field in ("reviewer", "approved_at", "review_time_sec")
        )
        if not review_complete:
            issues.append(
                ValidationIssue(
                    pointer="/review",
                    validator="gold_requires_review",
                    message="human_approved_gold requires reviewer, approved_at, and review_time_sec",
                )
            )
    return tuple(sorted(issues))


def validate_manifest(
    manifest: Mapping[str, Any], *, enabled_labels: Iterable[str]
) -> tuple[ValidationIssue, ...]:
    """Validate the manifest schema and non-overridable packager invariants."""
    structural = validate_document(manifest, "manifest")
    invariants = _manifest_invariant_issues(manifest, enabled_labels)
    return tuple(sorted((*structural, *invariants)))


def require_valid_document(document: Any, schema_name: str) -> None:
    """Raise with pointer-addressed findings unless a document is structurally valid."""
    issues = validate_document(document, schema_name)
    if issues:
        raise ArtifactValidationError(issues)


def require_valid_manifest(manifest: Mapping[str, Any], *, enabled_labels: Iterable[str]) -> None:
    """Raise unless a manifest passes schema and packager invariants."""
    issues = validate_manifest(manifest, enabled_labels=enabled_labels)
    if issues:
        raise ArtifactValidationError(issues)


# ---------------------------------------------------------------------------
# MaskFactory <-> ComfyUI bridge hardening layer (wire contract v1.0.0)
# ---------------------------------------------------------------------------

BRIDGE_SCHEMA_NAMES = (
    "maskfactory_release_snapshot",
    "maskfactory_capability_snapshot",
    "maskfactory_consumer_requirements",
    "mask_acquisition_request",
    "mask_acquisition_receipt",
    "mask_bridge_error",
    "maskfactory_adoption_receipt",
    "mask_authority_invalidation_event",
    "mask_repair_feedback",
    "mask_bridge_event",
    "operational_autonomy_certificate",
    "mask_bridge_semantic_invariant_profile",
)

OPERATIONAL_QA_GATES = frozenset(
    {
        "schema_conformance",
        "source_identity",
        "ontology_label",
        "left_right_semantics",
        "subject_assignment",
        "ownership_isolation",
        "contact_occlusion",
        "protected_region",
        "transform_replay",
        "output_identity",
        "deterministic_quality",
        "critic_quality",
        "critic_independence",
        "perturbation",
        "metamorphic",
        "stability_replay",
        "repair_budget",
        "abstention",
        "temporal_consistency",
    }
)

ADOPTION_COMPATIBILITY_CHECKS = frozenset(
    {
        "trust_anchor",
        "signature",
        "release_hash",
        "canonicalization",
        "signed_journal",
        "revocation_freshness",
        "artifact_security",
        "wire_schemas",
        "api_contract",
        "package_format",
        "ontology",
        "node_pack",
        "capabilities",
        "media_scope",
        "authority_policy",
        "contract_tests",
    }
)

ADOPTION_REVALIDATION_TRIGGERS = frozenset(
    {
        "release_superseded",
        "release_revoked",
        "producer_signing_key_revoked",
        "producer_signing_key_rotated",
        "consumer_adoption_key_revoked",
        "consumer_adoption_key_rotated",
        "trust_policy_changed",
        "wire_schema_changed",
        "semantic_invariant_profile_changed",
        "api_contract_changed",
        "package_format_changed",
        "ontology_changed",
        "node_pack_changed",
        "capability_snapshot_changed",
        "capability_policy_changed",
        "package_invalidated",
        "artifact_invalidated",
        "artifact_hash_drift",
        "certificate_expired",
        "certificate_revoked",
        "provider_stack_changed",
        "consumer_requirements_changed",
        "signed_journal_stale",
        "signed_journal_fork_detected",
        "revocation_checkpoint_stale",
        "validity_expired",
        "qa_regression",
    }
)

COMPLETION_PROFILE_IDS = frozenset(
    {"core_autonomous_runtime", "independent_real_accuracy", "scale_daz_maturity"}
)

REQUIRED_RELEASE_ARTIFACT_KINDS = frozenset(
    {
        "python_wheel",
        "comfyui_node_pack",
        "schema_bundle",
        "openapi_document",
        "compatibility_manifest",
        "certificate_index",
    }
)

INVALIDATION_REASON_POLICY = {
    "release_superseded": ({"release"}, {"refresh_release", "revalidate_adoption"}),
    "release_revoked": ({"release"}, {"rollback_release", "revalidate_adoption"}),
    "producer_signing_key_revoked": (
        {"signing_key"},
        {"rotate_trust_anchor", "revalidate_adoption"},
    ),
    "producer_signing_key_rotated": (
        {"signing_key"},
        {"rotate_trust_anchor", "revalidate_adoption"},
    ),
    "consumer_adoption_key_revoked": (
        {"signing_key"},
        {"rotate_trust_anchor", "revalidate_adoption"},
    ),
    "consumer_adoption_key_rotated": (
        {"signing_key"},
        {"rotate_trust_anchor", "revalidate_adoption"},
    ),
    "trust_policy_changed": (
        {"trust_policy", "policy"},
        {"rotate_trust_anchor", "revalidate_adoption"},
    ),
    "wire_schema_changed": ({"wire_schema"}, {"refresh_contract", "revalidate_adoption"}),
    "semantic_invariant_profile_changed": (
        {"semantic_profile"},
        {"refresh_contract", "revalidate_adoption"},
    ),
    "api_contract_changed": ({"api_contract"}, {"refresh_contract", "revalidate_adoption"}),
    "package_format_changed": ({"package_format"}, {"refresh_contract", "revalidate_adoption"}),
    "ontology_changed": ({"ontology"}, {"refresh_contract", "revalidate_adoption"}),
    "node_pack_changed": ({"node_pack"}, {"reinstall_node_pack", "revalidate_adoption"}),
    "capability_snapshot_changed": (
        {"capability_snapshot"},
        {"refresh_capability_snapshot", "revalidate_adoption"},
    ),
    "capability_policy_changed": (
        {"policy", "capability_snapshot"},
        {"refresh_capability_snapshot", "revalidate_adoption"},
    ),
    "package_invalidated": ({"package"}, {"invalidate_cache", "revalidate_adoption"}),
    "artifact_invalidated": ({"artifact"}, {"tombstone_cached_artifact", "revalidate_adoption"}),
    "artifact_hash_drift": ({"artifact"}, {"quarantine_artifact", "revalidate_adoption"}),
    "certificate_expired": ({"certificate"}, {"block_dependent_pass", "revalidate_adoption"}),
    "certificate_revoked": ({"certificate"}, {"block_dependent_pass", "revalidate_adoption"}),
    "provider_stack_changed": (
        {"provider_stack", "execution_fingerprint"},
        {"reroute_to_eligible_authority", "revalidate_adoption"},
    ),
    "consumer_requirements_changed": (
        {"consumer_requirements"},
        {"refresh_consumer_requirements", "revalidate_adoption"},
    ),
    "signed_journal_stale": (
        {"journal_checkpoint"},
        {"replay_signed_journal", "revalidate_adoption"},
    ),
    "signed_journal_fork_detected": (
        {"journal_checkpoint"},
        {"reject_forked_journal", "revalidate_adoption"},
    ),
    "revocation_checkpoint_stale": (
        {"journal_checkpoint"},
        {"refresh_revocation_checkpoint", "revalidate_adoption"},
    ),
    "validity_expired": ({"adoption_receipt"}, {"expire_adoption", "revalidate_adoption"}),
    "qa_regression": (
        {"artifact", "certificate", "provider_stack"},
        {"quarantine_artifact", "block_dependent_pass"},
    ),
}

OPERATIONAL_INVALIDATION_REASON_TARGET_KIND = {
    "signing_key_rotated": "signing_key",
    "signing_key_revoked": "signing_key",
    "certificate_revoked": "certificate",
    "certificate_superseded": "certificate",
    "package_invalidated": "package",
    "provider_stack_changed": "provider_stack",
    "ontology_changed": "ontology",
    "policy_changed": "policy",
    "capability_changed": "capability_snapshot",
    "release_superseded": "release",
    "release_revoked": "release",
}


def _canonical_number(value: float) -> str:
    """Encode a finite IEEE-754 number using the declared bridge-v1 rules."""
    if not math.isfinite(value):
        raise ValueError("MaskFactory canonical JSON rejects non-finite numbers")
    if value == 0:
        return "0"
    encoded = repr(value).lower()
    if "e" in encoded:
        mantissa, exponent = encoded.split("e", 1)
        sign = ""
        if exponent.startswith(("+", "-")):
            sign, exponent = exponent[0], exponent[1:]
        exponent = exponent.lstrip("0") or "0"
        if sign == "+":
            sign = ""
        encoded = f"{mantissa}e{sign}{exponent}"
    return encoded


def _canonical_json_text(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _canonical_number(value)
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        return json.dumps(normalized, ensure_ascii=False, allow_nan=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical_json_text(item) for item in value) + "]"
    if isinstance(value, Mapping):
        normalized_items: dict[str, Any] = {}
        original_keys: dict[str, str] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise TypeError("MaskFactory canonical JSON requires string object keys")
            key = unicodedata.normalize("NFC", raw_key)
            if key in normalized_items:
                raise ValueError(
                    "MaskFactory canonical JSON rejects duplicate keys after NFC normalization: "
                    f"{original_keys[key]!r}, {raw_key!r}"
                )
            normalized_items[key] = item
            original_keys[key] = raw_key
        return (
            "{"
            + ",".join(
                _canonical_json_text(key) + ":" + _canonical_json_text(normalized_items[key])
                for key in sorted(normalized_items)
            )
            + "}"
        )
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Return MaskFactory canonical-json-v1 bytes (NFC, UTF-8, stable numbers/keys)."""
    return _canonical_json_text(value).encode("utf-8")


def canonical_document_sha256(
    document: Mapping[str, Any], *, excluded_top_level_fields: Iterable[str] = ()
) -> str:
    """Hash a document under the portable MaskFactory canonical-json-v1 contract."""
    excluded = frozenset(excluded_top_level_fields)
    payload = {key: value for key, value in document.items() if key not in excluded}
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def load_canonical_json(raw: str | bytes) -> Any:
    """Parse JSON while rejecting duplicate (including NFC-colliding) object keys."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="strict")

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            normalized = unicodedata.normalize("NFC", key)
            if normalized in result:
                raise ValueError(f"duplicate JSON key after NFC normalization: {key!r}")
            result[normalized] = value
        return result

    return json.loads(
        raw,
        object_pairs_hook=pairs_hook,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON number: {value}")
        ),
    )


def _issue(pointer: str, validator: str, message: str) -> ValidationIssue:
    return ValidationIssue(pointer=pointer, validator=validator, message=message)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _timestamp_order_issues(
    values: Iterable[tuple[str, Any]], *, allow_equal: bool = True
) -> list[ValidationIssue]:
    rows = list(values)
    issues: list[ValidationIssue] = []
    parsed: list[tuple[str, datetime]] = []
    for pointer, raw in rows:
        value = _parse_timestamp(raw)
        if value is None:
            issues.append(
                _issue(
                    pointer,
                    "canonical_utc_timestamp",
                    "timestamp must be canonical RFC3339 UTC with a trailing Z",
                )
            )
        else:
            parsed.append((pointer, value))
    if len(parsed) == len(rows):
        for (left_pointer, left), (right_pointer, right) in zip(parsed, parsed[1:]):
            bad = right < left if allow_equal else right <= left
            if bad:
                issues.append(
                    _issue(
                        right_pointer, "timestamp_order", f"timestamp must follow {left_pointer}"
                    )
                )
    return issues


def _declared_hash_issue(
    document: Mapping[str, Any], *, hash_field: str, excluded: Iterable[str]
) -> ValidationIssue | None:
    try:
        observed = canonical_document_sha256(document, excluded_top_level_fields=excluded)
    except (TypeError, ValueError) as exc:
        return _issue("", "canonical_json", str(exc))
    if document.get(hash_field) != observed:
        return _issue(
            f"/{hash_field}",
            "canonical_payload_hash",
            f"{hash_field} does not match the canonical document body",
        )
    return None


def _trust_record(
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None, key_id: Any
) -> Mapping[str, Any] | None:
    if not isinstance(trusted_signing_keys, Mapping) or not isinstance(key_id, str):
        return None
    record = trusted_signing_keys.get(key_id)
    return record if isinstance(record, Mapping) else None


def _ed25519_signature_issues(
    document: Mapping[str, Any],
    *,
    payload_hash_field: str,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None,
    required_role: str,
    decision_time: Any,
) -> list[ValidationIssue]:
    """Verify a signature only after the embedded key is anchored out of band."""
    issues: list[ValidationIssue] = []
    signature = document.get("signature")
    trust = (
        document.get("trust_binding")
        or document.get("signing_trust")
        or document.get("release_binding")
    )
    if not isinstance(signature, Mapping):
        return [
            _issue(
                "/signature", "signature_required", "a signed bridge record requires a signature"
            )
        ]
    key_id = signature.get("key_id")
    record = _trust_record(trusted_signing_keys, key_id)
    if record is None:
        return [
            _issue(
                "/signature/key_id",
                "missing_trust_anchor",
                "signature key_id is not present in the independently adopted trusted-key registry",
            )
        ]
    try:
        raw_public_key = base64.b64decode(str(signature.get("public_key_base64")), validate=True)
        raw_signature = base64.b64decode(str(signature.get("value_base64")), validate=True)
    except (ValueError, TypeError, binascii.Error):
        return [
            _issue("/signature", "ed25519_encoding", "signature or public key is not valid base64")
        ]
    public_key_sha256 = hashlib.sha256(raw_public_key).hexdigest()
    if record.get("public_key_sha256") != public_key_sha256:
        issues.append(
            _issue(
                "/signature/public_key_base64",
                "trusted_key_hash",
                "embedded public key does not match the out-of-band trust anchor",
            )
        )
    roles = set(record.get("roles") or ())
    if required_role not in roles:
        issues.append(
            _issue(
                "/signature/key_id",
                "trusted_key_role",
                f"trusted key is not authorized for role {required_role!r}",
            )
        )
    if record.get("status") != "active":
        issues.append(
            _issue("/signature/key_id", "trusted_key_status", "signing key is not active")
        )
    signed_at = _parse_timestamp(decision_time)
    valid_from = _parse_timestamp(record.get("valid_from"))
    valid_until = _parse_timestamp(record.get("valid_until"))
    if (
        signed_at is None
        or valid_from is None
        or valid_until is None
        or not (valid_from <= signed_at < valid_until)
    ):
        issues.append(
            _issue(
                "/signature/key_id",
                "trusted_key_validity",
                "signing time is outside the trusted key validity interval",
            )
        )
    if isinstance(trust, Mapping):
        comparisons = {
            "signing_key_id": key_id,
            "release_signing_key_id": key_id,
            "consumer_adoption_key_id": key_id,
            "signing_public_key_sha256": public_key_sha256,
            "release_signing_public_key_sha256": public_key_sha256,
            "consumer_adoption_public_key_sha256": public_key_sha256,
            "key_set_id": record.get("key_set_id"),
            "key_set_version": record.get("key_set_version"),
            "key_set_sha256": record.get("key_set_sha256"),
            "signing_key_set_id": record.get("key_set_id"),
            "signing_key_set_version": record.get("key_set_version"),
            "signing_key_set_sha256": record.get("key_set_sha256"),
            "consumer_key_set_id": record.get("key_set_id"),
            "consumer_key_set_version": record.get("key_set_version"),
            "consumer_key_set_sha256": record.get("key_set_sha256"),
        }
        for field, expected in comparisons.items():
            if field in trust and expected is not None and trust.get(field) != expected:
                issues.append(
                    _issue(
                        f"/trust_binding/{field}",
                        "trusted_key_set_binding",
                        "record trust binding does not match the adopted trust registry",
                    )
                )
        if trust.get("key_role") is not None and trust.get("key_role") != required_role:
            issues.append(
                _issue(
                    "/trust_binding/key_role",
                    "trusted_key_role",
                    "record-declared key role does not match required signer role",
                )
            )
    if signature.get("signed_payload_sha256") != document.get(payload_hash_field):
        issues.append(
            _issue(
                "/signature/signed_payload_sha256",
                "signature_payload_binding",
                "signature payload hash does not bind the declared document hash",
            )
        )
    if signature.get("key_id") != key_id:
        issues.append(
            _issue(
                "/signature/key_id",
                "signature_key_binding",
                "signature key identifier is inconsistent",
            )
        )
    try:
        Ed25519PublicKey.from_public_bytes(raw_public_key).verify(
            raw_signature, bytes.fromhex(str(document.get(payload_hash_field)))
        )
    except (ValueError, TypeError, InvalidSignature):
        issues.append(
            _issue(
                "/signature/value_base64",
                "ed25519_signature_verification",
                "Ed25519 signature does not verify over canonical SHA-256 digest bytes",
            )
        )
    return issues


def _production_signing_key_issues(
    document: Mapping[str, Any],
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None,
) -> list[ValidationIssue]:
    """Reject conformance-only or unclassified trust anchors at production use sites."""
    signature = document.get("signature")
    key_id = signature.get("key_id") if isinstance(signature, Mapping) else None
    record = _trust_record(trusted_signing_keys, key_id)
    if not isinstance(record, Mapping) or record.get("usage_scope") != "production":
        return [
            _issue(
                "/signature/key_id",
                "production_trust_anchor_required",
                "production authority requires an independently adopted key explicitly scoped for production, never a conformance-only key",
            )
        ]
    return []


def _authentication_issues(
    document: Mapping[str, Any], *, decision_time: Any
) -> list[ValidationIssue]:
    authentication = document.get("authentication")
    if not isinstance(authentication, Mapping):
        return []
    issues = _timestamp_order_issues(
        (
            ("/authentication/issued_at", authentication.get("issued_at")),
            ("/authentication/expires_at", authentication.get("expires_at")),
        ),
        allow_equal=False,
    )
    at = _parse_timestamp(decision_time)
    issued = _parse_timestamp(authentication.get("issued_at"))
    expires = _parse_timestamp(authentication.get("expires_at"))
    if at is None or issued is None or expires is None or not (issued <= at < expires):
        issues.append(
            _issue(
                "/authentication",
                "authentication_validity",
                "record decision time is outside the authentication validity window",
            )
        )
    return issues


def _owner_identity_sha256(owner: Any) -> str | None:
    if not isinstance(owner, Mapping):
        return None
    return canonical_document_sha256(owner)


_ARTIFACT_IDENTITY_FIELDS = (
    "artifact_id",
    "encoded_sha256",
    "decoded_mask_sha256",
    "source_decoded_pixel_sha256",
    "format",
    "channel_layout",
    "dtype",
    "allowed_values",
    "mask_type",
    "label",
    "visibility",
    "empty_semantics",
    "content_summary",
    "owner",
    "owner_kind",
    "entity_id",
    "scene_instance_id",
    "canonical_person_id",
    "person_index",
    "artifact_kind",
    "width",
    "height",
    "coordinate_space",
    "transform_chain_sha256",
)


def artifact_identity_sha256(artifact: Mapping[str, Any]) -> str:
    """Compute identity over mask bytes plus decoding, ownership and coordinate semantics."""
    body = {
        field: artifact[field]
        for field in _ARTIFACT_IDENTITY_FIELDS
        if field in artifact
        and field
        not in {
            "owner",
            "owner_kind",
            "entity_id",
            "scene_instance_id",
            "canonical_person_id",
            "person_index",
        }
    }
    if isinstance(artifact.get("owner"), Mapping):
        body["owner"] = artifact["owner"]
    elif all(
        field in artifact
        for field in (
            "owner_kind",
            "entity_id",
            "scene_instance_id",
            "canonical_person_id",
            "person_index",
        )
    ):
        body["owner"] = {
            field: artifact[field]
            for field in (
                "owner_kind",
                "entity_id",
                "scene_instance_id",
                "canonical_person_id",
                "person_index",
            )
        }
    return canonical_document_sha256(body)


def _artifact_semantic_issues(
    artifact: Mapping[str, Any], *, pointer: str
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    declared_identity = artifact.get("artifact_identity_sha256")
    if isinstance(declared_identity, str):
        expected_identity = artifact_identity_sha256(artifact)
        if declared_identity != expected_identity:
            issues.append(
                _issue(
                    f"{pointer}/artifact_identity_sha256",
                    "artifact_identity",
                    "artifact identity hash does not bind encoded/decoded content, ownership, dimensions and transform semantics",
                )
            )
    width, height = artifact.get("width"), artifact.get("height")
    summary = artifact.get("content_summary")
    if isinstance(width, int) and isinstance(height, int) and isinstance(summary, Mapping):
        area = summary.get("area_pixels")
        ppm = summary.get("area_ppm")
        empty = summary.get("is_empty")
        bounds = summary.get("bounds")
        total = width * height
        if isinstance(area, int):
            if area > total:
                issues.append(
                    _issue(
                        f"{pointer}/content_summary/area_pixels",
                        "mask_area_bounds",
                        "mask area cannot exceed raster area",
                    )
                )
            expected_ppm = (area * 1_000_000) // total
            if ppm != expected_ppm:
                issues.append(
                    _issue(
                        f"{pointer}/content_summary/area_ppm",
                        "mask_area_ppm",
                        "area_ppm must be the floor of area_pixels / raster area in millionths",
                    )
                )
            if empty is not (area == 0):
                issues.append(
                    _issue(
                        f"{pointer}/content_summary/is_empty",
                        "empty_mask_semantics",
                        "is_empty must agree with area_pixels",
                    )
                )
        if empty is True and bounds is not None:
            issues.append(
                _issue(
                    f"{pointer}/content_summary/bounds",
                    "empty_mask_semantics",
                    "empty masks must have null content bounds",
                )
            )
        if empty is False and not isinstance(bounds, Mapping):
            issues.append(
                _issue(
                    f"{pointer}/content_summary/bounds",
                    "mask_content_bounds",
                    "non-empty masks require content bounds",
                )
            )
        if isinstance(bounds, Mapping):
            x, y = bounds.get("x"), bounds.get("y")
            bw, bh = bounds.get("width"), bounds.get("height")
            if all(isinstance(v, int) for v in (x, y, bw, bh)) and (
                x + bw > width or y + bh > height
            ):
                issues.append(
                    _issue(
                        f"{pointer}/content_summary/bounds",
                        "mask_content_bounds",
                        "content bounds extend outside the mask raster",
                    )
                )
    if (
        artifact.get("empty_semantics") == "forbidden"
        and isinstance(summary, Mapping)
        and summary.get("is_empty") is True
    ):
        issues.append(
            _issue(
                f"{pointer}/content_summary/is_empty",
                "empty_mask_forbidden",
                "this artifact declares empty masks forbidden",
            )
        )
    return issues


def _transform_chain_issues(
    chain: Any, *, pointer: str = "/transform_chain", source: Mapping[str, Any] | None = None
) -> list[ValidationIssue]:
    if not isinstance(chain, Mapping):
        return []
    issues: list[ValidationIssue] = []
    expected_chain_hash = canonical_document_sha256(
        chain, excluded_top_level_fields=("chain_sha256",)
    )
    if chain.get("chain_sha256") != expected_chain_hash:
        issues.append(
            _issue(
                f"{pointer}/chain_sha256",
                "transform_chain_hash",
                "transform chain hash does not bind the executable chain",
            )
        )
    chain_source, chain_output = chain.get("source"), chain.get("output")
    if isinstance(source, Mapping) and isinstance(chain_source, Mapping):
        if (
            chain_source.get("coordinate_space"),
            chain_source.get("width"),
            chain_source.get("height"),
        ) != (source.get("coordinate_space"), source.get("width"), source.get("height")):
            issues.append(
                _issue(
                    f"{pointer}/source",
                    "transform_source_binding",
                    "transform source state does not match source raster",
                )
            )
    steps = chain.get("steps")
    previous = chain_source
    if isinstance(steps, list):
        seen_hashes: set[str] = set()
        for index, step in enumerate(steps):
            if not isinstance(step, Mapping):
                continue
            if step.get("sequence") != index:
                issues.append(
                    _issue(
                        f"{pointer}/steps/{index}/sequence",
                        "transform_sequence",
                        "transform step sequence must be contiguous and zero-based",
                    )
                )
            expected_step_hash = canonical_document_sha256(
                step, excluded_top_level_fields=("step_sha256",)
            )
            if step.get("step_sha256") != expected_step_hash:
                issues.append(
                    _issue(
                        f"{pointer}/steps/{index}/step_sha256",
                        "transform_step_hash",
                        "transform step hash does not bind its operation, states and parameters",
                    )
                )
            if step.get("step_sha256") in seen_hashes:
                issues.append(
                    _issue(
                        f"{pointer}/steps/{index}/step_sha256",
                        "transform_step_unique",
                        "transform step hashes must be unique",
                    )
                )
            if isinstance(step.get("step_sha256"), str):
                seen_hashes.add(step["step_sha256"])
            input_state, output_state = step.get("input"), step.get("output")
            if isinstance(previous, Mapping) and input_state != previous:
                issues.append(
                    _issue(
                        f"{pointer}/steps/{index}/input",
                        "transform_contiguity",
                        "step input must exactly equal the preceding output state",
                    )
                )
            params, operation = step.get("parameters"), step.get("operation")
            if isinstance(params, Mapping):
                parameter_type = params.get("parameter_type")
                if operation not in {
                    parameter_type,
                    "project" if parameter_type == "project" else None,
                    "inverse_project" if parameter_type == "inverse_project" else None,
                }:
                    issues.append(
                        _issue(
                            f"{pointer}/steps/{index}/parameters/parameter_type",
                            "transform_operation_parameters",
                            "typed parameters must match step operation",
                        )
                    )
                if isinstance(input_state, Mapping) and isinstance(output_state, Mapping):
                    iw, ih = input_state.get("width"), input_state.get("height")
                    ow, oh = output_state.get("width"), output_state.get("height")
                    if operation == "crop" and all(
                        isinstance(v, int)
                        for v in (
                            iw,
                            ih,
                            ow,
                            oh,
                            params.get("x"),
                            params.get("y"),
                            params.get("width"),
                            params.get("height"),
                        )
                    ):
                        if (
                            params["x"] + params["width"] > iw
                            or params["y"] + params["height"] > ih
                            or (ow, oh) != (params["width"], params["height"])
                        ):
                            issues.append(
                                _issue(
                                    f"{pointer}/steps/{index}",
                                    "transform_crop_geometry",
                                    "crop must be in bounds and output dimensions must equal crop dimensions",
                                )
                            )
                    elif operation == "resize" and (ow, oh) != (
                        params.get("width"),
                        params.get("height"),
                    ):
                        issues.append(
                            _issue(
                                f"{pointer}/steps/{index}/output",
                                "transform_resize_geometry",
                                "resize output dimensions must equal parameters",
                            )
                        )
                    elif operation == "pad" and all(
                        isinstance(v, int)
                        for v in (
                            iw,
                            ih,
                            ow,
                            oh,
                            params.get("left"),
                            params.get("right"),
                            params.get("top"),
                            params.get("bottom"),
                        )
                    ):
                        if (ow, oh) != (
                            iw + params["left"] + params["right"],
                            ih + params["top"] + params["bottom"],
                        ):
                            issues.append(
                                _issue(
                                    f"{pointer}/steps/{index}/output",
                                    "transform_pad_geometry",
                                    "pad output dimensions do not match padding parameters",
                                )
                            )
                    elif operation == "horizontal_flip" and (ow, oh) != (iw, ih):
                        issues.append(
                            _issue(
                                f"{pointer}/steps/{index}/output",
                                "transform_flip_geometry",
                                "horizontal flip must preserve raster dimensions",
                            )
                        )
                if operation in {"project", "inverse_project"}:
                    matrix = params.get("matrix_3x3")
                    if isinstance(matrix, list) and len(matrix) == 9:
                        a, b, c, d, e, f, g, h, i = matrix
                        determinant = (
                            a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
                        )
                        if not math.isfinite(float(determinant)) or abs(determinant) <= 1e-12:
                            issues.append(
                                _issue(
                                    f"{pointer}/steps/{index}/parameters/matrix_3x3",
                                    "transform_invertible",
                                    "projection matrix must be finite and invertible",
                                )
                            )
            previous = output_state
        if previous != chain_output:
            issues.append(
                _issue(
                    f"{pointer}/output",
                    "transform_output_binding",
                    "chain output must exactly equal final step output (or source for an empty chain)",
                )
            )
    policy = chain.get("roundtrip_policy")
    if isinstance(policy, Mapping) and (
        policy.get("required") is not True or policy.get("reject_noninvertible") is not True
    ):
        issues.append(
            _issue(
                f"{pointer}/roundtrip_policy",
                "transform_roundtrip_policy",
                "bridge transforms must require roundtrip validation and reject non-invertible chains",
            )
        )
    return issues


def _media_scope_issues(media: Any, *, pointer: str = "/media_scope") -> list[ValidationIssue]:
    if not isinstance(media, Mapping):
        return []
    issues: list[ValidationIssue] = []
    kind = media.get("scope_kind")
    video_fields = (
        "source_video_sha256",
        "decoded_frame_sha256",
        "frame_index",
        "pts",
        "timebase_numerator",
        "timebase_denominator",
        "timestamp_ns",
    )
    if kind == "still_image":
        if (
            any(media.get(field) is not None for field in video_fields)
            or media.get("frame_span") is not None
            or media.get("neighbor_frames")
        ):
            issues.append(
                _issue(
                    pointer,
                    "media_scope_closed_world",
                    "still-image scope must not carry video/frame identity fields",
                )
            )
    elif kind == "video_frame":
        if (
            any(media.get(field) is None for field in video_fields)
            or media.get("frame_span") is not None
        ):
            issues.append(
                _issue(
                    pointer,
                    "media_scope_closed_world",
                    "video-frame scope requires exact video/frame/PTS/timebase identity and no frame span",
                )
            )
    elif kind == "frame_span":
        span = media.get("frame_span")
        if media.get("source_video_sha256") is None or not isinstance(span, Mapping):
            issues.append(
                _issue(
                    pointer,
                    "media_scope_closed_world",
                    "frame-span scope requires source video and exact span manifest",
                )
            )
        elif (
            isinstance(span.get("start_frame"), int)
            and isinstance(span.get("end_frame"), int)
            and span["end_frame"] < span["start_frame"]
        ):
            issues.append(
                _issue(
                    f"{pointer}/frame_span/end_frame",
                    "frame_span_order",
                    "frame-span end must not precede start",
                )
            )
    return issues


def _source_media_issues(source: Any, media: Any) -> list[ValidationIssue]:
    if not isinstance(source, Mapping) or not isinstance(media, Mapping):
        return []
    extraction = source.get("frame_extraction")
    issues: list[ValidationIssue] = []
    if media.get("scope_kind") == "still_image" and extraction is not None:
        issues.append(
            _issue(
                "/source/frame_extraction",
                "source_media_binding",
                "still-image sources cannot claim frame extraction",
            )
        )
    if media.get("scope_kind") in {"video_frame", "frame_span"}:
        if not isinstance(extraction, Mapping):
            issues.append(
                _issue(
                    "/source/frame_extraction",
                    "source_media_binding",
                    "video-scoped source requires exact frame-extraction identity",
                )
            )
        else:
            for field in (
                "source_video_sha256",
                "frame_index",
                "pts",
                "timebase_numerator",
                "timebase_denominator",
            ):
                if media.get(field) is not None and extraction.get(field) != media.get(field):
                    issues.append(
                        _issue(
                            f"/source/frame_extraction/{field}",
                            "source_media_binding",
                            "source frame extraction does not match media scope",
                        )
                    )
    return issues


def _region_authority_issues(region: Mapping[str, Any], *, pointer: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    binding = region.get("authority_binding")
    if not isinstance(binding, Mapping):
        return issues
    required = region.get("required_minimum_authority_state")
    observed = binding.get("authority_state")
    if (
        required in AUTHORITY_RANK
        and observed in AUTHORITY_RANK
        and AUTHORITY_RANK[observed] < AUTHORITY_RANK[required]
    ):
        issues.append(
            _issue(
                f"{pointer}/authority_binding/authority_state",
                "input_authority_minimum",
                "input region does not meet its declared minimum authority",
            )
        )
    if observed == "certified" and not (
        binding.get("issuer_kind") == "maskfactory_autonomous"
        and binding.get("certificate_kind") == "exact_serving_route_output"
        and isinstance(binding.get("certificate_id"), str)
        and isinstance(binding.get("certificate_sha256"), str)
        and binding.get("certificate_status") == "active"
        and binding.get("certificate_exact_scope_match") is True
        and isinstance(binding.get("revocation_checked_at"), str)
        and isinstance(binding.get("revocation_checkpoint_sha256"), str)
    ):
        issues.append(
            _issue(
                f"{pointer}/authority_binding",
                "input_exact_operational_certificate",
                "certified input regions require an active exact-output operational certificate and fresh revocation binding",
            )
        )
    return issues


def _geometry_issues(request: Mapping[str, Any]) -> list[ValidationIssue]:
    payload = request.get("mode_payload")
    source = request.get("source")
    chain = request.get("transform_chain")
    if not isinstance(payload, Mapping) or not isinstance(source, Mapping):
        return []
    output = chain.get("output") if isinstance(chain, Mapping) else None
    dimensions = {
        "source_pixel": (source.get("width"), source.get("height")),
        "crop_pixel": ((output or {}).get("width"), (output or {}).get("height")),
        "output_pixel": ((output or {}).get("width"), (output or {}).get("height")),
        "normalized_0_1": (1.0, 1.0),
    }
    issues: list[ValidationIssue] = []
    for collection in ("positive_points", "negative_points", "positive_clicks", "negative_clicks"):
        for index, point in enumerate(payload.get(collection) or ()):
            if not isinstance(point, Mapping):
                continue
            width, height = dimensions.get(point.get("coordinate_space"), (None, None))
            if (
                isinstance(width, (int, float))
                and isinstance(height, (int, float))
                and (
                    not isinstance(point.get("x"), (int, float))
                    or not isinstance(point.get("y"), (int, float))
                    or point["x"] >= width
                    or point["y"] >= height
                )
            ):
                issues.append(
                    _issue(
                        f"/mode_payload/{collection}/{index}",
                        "prompt_geometry_bounds",
                        "prompt point lies outside its declared coordinate space",
                    )
                )
    for index, box in enumerate(payload.get("boxes") or ()):
        if not isinstance(box, Mapping):
            continue
        width, height = dimensions.get(box.get("coordinate_space"), (None, None))
        values = (box.get("x0"), box.get("y0"), box.get("x1"), box.get("y1"))
        if all(isinstance(value, (int, float)) for value in values):
            x0, y0, x1, y1 = values
            if (
                x1 <= x0
                or y1 <= y0
                or (isinstance(width, (int, float)) and (x1 > width or y1 > height))
            ):
                issues.append(
                    _issue(
                        f"/mode_payload/boxes/{index}",
                        "prompt_box_geometry",
                        "prompt box must be ordered and within its declared coordinate space",
                    )
                )
    return issues


def validate_mask_acquisition_request(
    request: Mapping[str, Any],
    *,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[ValidationIssue, ...]:
    """Validate an authenticated request, exact inputs, ownership and executable geometry."""
    issues: list[ValidationIssue] = list(validate_document(request, "mask_acquisition_request"))
    hash_issue = _declared_hash_issue(
        request,
        hash_field="request_payload_sha256",
        excluded=("request_payload_sha256", "signature"),
    )
    if hash_issue:
        issues.append(hash_issue)
    issues.extend(
        _ed25519_signature_issues(
            request,
            payload_hash_field="request_payload_sha256",
            trusted_signing_keys=trusted_signing_keys,
            required_role="consumer_request",
            decision_time=request.get("created_at"),
        )
    )
    issues.extend(_authentication_issues(request, decision_time=request.get("created_at")))
    issues.extend(
        _timestamp_order_issues(
            (
                ("/created_at", request.get("created_at")),
                ("/deadline_at", request.get("deadline_at")),
            ),
            allow_equal=False,
        )
    )
    media = request.get("media_scope")
    source = request.get("source")
    issues.extend(_media_scope_issues(media))
    issues.extend(_source_media_issues(source, media))
    issues.extend(
        _transform_chain_issues(
            request.get("transform_chain"), source=source if isinstance(source, Mapping) else None
        )
    )
    issues.extend(_geometry_issues(request))

    subject = request.get("subject")
    target_regions = request.get("target_regions") or ()
    protected_regions = request.get("protected_regions") or ()
    roster = request.get("protected_owner_roster") or ()
    roster_owners: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(roster):
        if not isinstance(row, Mapping) or not isinstance(row.get("owner"), Mapping):
            continue
        owner_hash = _owner_identity_sha256(row["owner"])
        if owner_hash in roster_owners:
            issues.append(
                _issue(
                    f"/protected_owner_roster/{index}/owner",
                    "protected_owner_unique",
                    "protected-owner roster contains a duplicate owner",
                )
            )
        else:
            roster_owners[str(owner_hash)] = row
        if isinstance(subject, Mapping):
            is_self = row["owner"].get("owner_kind") == "character_instance" and all(
                row["owner"].get(field) == subject.get(field)
                for field in ("scene_instance_id", "canonical_person_id", "person_index")
            )
            if (row.get("relationship") == "self") is not is_self:
                issues.append(
                    _issue(
                        f"/protected_owner_roster/{index}/relationship",
                        "protected_owner_relationship",
                        "self relationship must exactly identify the request subject",
                    )
                )
    target_ids: set[str] = set()
    protected_ids: set[str] = set()
    target_identities: set[str] = set()
    protected_identities: set[str] = set()
    for collection, regions, identifiers in (
        ("target_regions", target_regions, target_ids),
        ("protected_regions", protected_regions, protected_ids),
    ):
        for index, region in enumerate(regions):
            if not isinstance(region, Mapping):
                continue
            pointer = f"/{collection}/{index}"
            region_id = region.get("region_id")
            if isinstance(region_id, str):
                if region_id in identifiers:
                    issues.append(
                        _issue(
                            f"{pointer}/region_id",
                            "unique_region_id",
                            "region_id must be unique in its collection",
                        )
                    )
                identifiers.add(region_id)
            issues.extend(_artifact_semantic_issues(region, pointer=pointer))
            issues.extend(_region_authority_issues(region, pointer=pointer))
            identity = region.get("artifact_identity_sha256")
            identity_set = (
                target_identities if collection == "target_regions" else protected_identities
            )
            if isinstance(identity, str):
                if identity in identity_set:
                    issues.append(
                        _issue(
                            f"{pointer}/artifact_identity_sha256",
                            "unique_artifact_identity",
                            "region artifact identity must be unique",
                        )
                    )
                identity_set.add(identity)
            owner = region.get("owner")
            if (
                collection == "target_regions"
                and isinstance(owner, Mapping)
                and isinstance(subject, Mapping)
            ):
                if owner.get("owner_kind") != "character_instance" or any(
                    owner.get(field) != subject.get(field)
                    for field in ("scene_instance_id", "canonical_person_id", "person_index")
                ):
                    issues.append(
                        _issue(
                            f"{pointer}/owner",
                            "target_owner_matches_subject",
                            "target owner must exactly match canonical request subject identity",
                        )
                    )
            if collection == "protected_regions" and isinstance(owner, Mapping):
                owner_hash = _owner_identity_sha256(owner)
                if owner_hash not in roster_owners:
                    issues.append(
                        _issue(
                            f"{pointer}/owner",
                            "protected_owner_authorized",
                            "protected owner is not present in the explicit authorized owner roster",
                        )
                    )
            if isinstance(source, Mapping) and region.get(
                "source_decoded_pixel_sha256"
            ) != source.get("decoded_pixel_sha256"):
                issues.append(
                    _issue(
                        f"{pointer}/source_decoded_pixel_sha256",
                        "region_source_identity",
                        "region does not bind the exact decoded source raster",
                    )
                )
            chain = request.get("transform_chain")
            if isinstance(chain, Mapping) and region.get("transform_chain_sha256") != chain.get(
                "chain_sha256"
            ):
                issues.append(
                    _issue(
                        f"{pointer}/transform_chain_sha256",
                        "region_transform_binding",
                        "region transform hash must bind the request executable transform chain",
                    )
                )
    if target_ids & protected_ids or target_identities & protected_identities:
        issues.append(
            _issue(
                "/protected_regions",
                "target_protected_disjoint",
                "target and protected input bindings must be disjoint by both region and artifact identity",
            )
        )

    intents = request.get("mask_intents") or ()
    intent_ids: set[str] = set()
    for index, intent in enumerate(intents):
        if not isinstance(intent, Mapping):
            continue
        intent_id = intent.get("intent_id")
        if intent_id in intent_ids:
            issues.append(
                _issue(
                    f"/mask_intents/{index}/intent_id",
                    "unique_intent_id",
                    "mask intent IDs must be unique",
                )
            )
        if isinstance(intent_id, str):
            intent_ids.add(intent_id)
        if not set(intent.get("target_region_ids") or ()).issubset(target_ids):
            issues.append(
                _issue(
                    f"/mask_intents/{index}/target_region_ids",
                    "declared_target_region_reference",
                    "mask intent references an unknown target region",
                )
            )
        if not set(intent.get("protected_region_ids") or ()).issubset(protected_ids):
            issues.append(
                _issue(
                    f"/mask_intents/{index}/protected_region_ids",
                    "declared_protected_region_reference",
                    "mask intent references an unknown protected region",
                )
            )

    payload = request.get("mode_payload")
    if isinstance(payload, Mapping):
        expected_payload_hash = canonical_document_sha256(
            payload, excluded_top_level_fields=("mode_payload_sha256",)
        )
        if payload.get("mode_payload_sha256") != expected_payload_hash:
            issues.append(
                _issue(
                    "/mode_payload/mode_payload_sha256",
                    "mode_payload_hash",
                    "mode payload hash does not bind the complete mode-specific payload",
                )
            )
        prompt = payload.get("prompt")
        if (
            isinstance(prompt, Mapping)
            and prompt.get("sha256")
            != hashlib.sha256(str(prompt.get("text", "")).encode("utf-8")).hexdigest()
        ):
            issues.append(
                _issue(
                    "/mode_payload/prompt/sha256",
                    "prompt_hash",
                    "prompt hash must bind the exact UTF-8 prompt text",
                )
            )
        if request.get("access_mode") == "mode_a_package_read":
            selectors = payload.get("artifact_selectors") or ()
            selector_ids = {
                row.get("artifact_identity_sha256") for row in selectors if isinstance(row, Mapping)
            }
            if selector_ids != target_identities:
                issues.append(
                    _issue(
                        "/mode_payload/artifact_selectors",
                        "mode_a_selector_target_binding",
                        "Mode A selectors must exactly equal the requested package artifact identities",
                    )
                )
        if request.get("access_mode") == "mode_b_live_refine":
            parents = payload.get("parent_artifacts") or ()
            prior = payload.get("prior_mask")
            parent_ids = {
                row.get("artifact_identity_sha256") for row in parents if isinstance(row, Mapping)
            }
            if (
                isinstance(prior, Mapping)
                and prior.get("artifact_identity_sha256") not in parent_ids
            ):
                issues.append(
                    _issue(
                        "/mode_payload/prior_mask/artifact_identity_sha256",
                        "refine_prior_is_parent",
                        "refinement prior must be one of the exact immutable parent artifacts",
                    )
                )
            if isinstance(prior, Mapping) and isinstance(subject, Mapping):
                prior_owner = prior.get("owner")
                if not isinstance(prior_owner, Mapping) or any(
                    prior_owner.get(field) != subject.get(field)
                    for field in ("scene_instance_id", "canonical_person_id", "person_index")
                ):
                    issues.append(
                        _issue(
                            "/mode_payload/prior_mask/owner",
                            "refine_prior_owner_binding",
                            "refinement prior owner must exactly match the canonical request subject",
                        )
                    )
            for index, parent in enumerate(parents):
                if not isinstance(parent, Mapping):
                    continue
                if isinstance(subject, Mapping):
                    parent_owner = parent.get("owner")
                    if not isinstance(parent_owner, Mapping) or any(
                        parent_owner.get(field) != subject.get(field)
                        for field in ("scene_instance_id", "canonical_person_id", "person_index")
                    ):
                        issues.append(
                            _issue(
                                f"/mode_payload/parent_artifacts/{index}/owner",
                                "refine_parent_owner_binding",
                                "refinement parent owner must exactly match the canonical request subject",
                            )
                        )
                if request.get("minimum_authority_state") == "certified" and not (
                    parent.get("authority_state") == "certified"
                    and parent.get("truth_tier") == "operationally_certified_artifact"
                    and parent.get("certificate_kind") == "exact_serving_route_output"
                    and parent.get("certificate_status") == "active"
                    and parent.get("certificate_exact_scope_match") is True
                    and isinstance(parent.get("revocation_checkpoint_sha256"), str)
                ):
                    issues.append(
                        _issue(
                            f"/mode_payload/parent_artifacts/{index}",
                            "certified_refine_requires_operational_parent",
                            "certified refinement requires active exact-output operational parents",
                        )
                    )
    if request.get("minimum_authority_state") == "certified":
        accepted = request.get("accepted_authority")
        if (
            not isinstance(accepted, Mapping)
            or set(accepted.get("certificate_kinds") or ()) != {"exact_serving_route_output"}
            or set(accepted.get("issuer_kinds") or ()) != {"maskfactory_autonomous"}
        ):
            issues.append(
                _issue(
                    "/accepted_authority",
                    "certified_request_exact_operational_only",
                    "certified requests may accept only MaskFactory exact-output operational certificates",
                )
            )
    return tuple(sorted(set(issues)))


def validate_canonical_json_golden_vectors(
    vectors: Mapping[str, Any],
) -> tuple[ValidationIssue, ...]:
    """Run portable canonicalization positive and negative vectors."""
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for index, vector in enumerate(vectors.get("vectors") or ()):
        if not isinstance(vector, Mapping):
            continue
        vector_id = vector.get("vector_id")
        if vector_id in seen:
            issues.append(
                _issue(
                    f"/vectors/{index}/vector_id",
                    "canonical_vector_unique",
                    "canonical vector IDs must be unique",
                )
            )
        if isinstance(vector_id, str):
            seen.add(vector_id)
        try:
            encoded = canonical_json_bytes(vector.get("input"))
        except (TypeError, ValueError) as exc:
            issues.append(_issue(f"/vectors/{index}/input", "canonical_vector", str(exc)))
            continue
        if encoded.decode("utf-8") != vector.get("canonical_utf8"):
            issues.append(
                _issue(
                    f"/vectors/{index}/canonical_utf8",
                    "canonical_vector_bytes",
                    "golden canonical bytes differ from implementation",
                )
            )
        if hashlib.sha256(encoded).hexdigest() != vector.get("sha256"):
            issues.append(
                _issue(
                    f"/vectors/{index}/sha256",
                    "canonical_vector_hash",
                    "golden canonical hash differs from implementation",
                )
            )
    for index, vector in enumerate(vectors.get("negative_vectors") or ()):
        if not isinstance(vector, Mapping):
            continue
        try:
            if "raw_json" in vector:
                load_canonical_json(str(vector["raw_json"]))
            elif "raw_hex" in vector:
                load_canonical_json(bytes.fromhex(str(vector["raw_hex"])))
            else:
                raise ValueError("negative vector has no input")
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            continue
        issues.append(
            _issue(
                f"/negative_vectors/{index}",
                "canonical_negative_vector",
                "negative canonicalization vector was unexpectedly accepted",
            )
        )
    return tuple(sorted(set(issues)))


def validate_mask_bridge_semantic_profile(
    profile: Mapping[str, Any], *, fixture_root: Path | None = None
) -> tuple[ValidationIssue, ...]:
    """Validate semantic profile content, verifier uniqueness and fixture byte index."""
    issues: list[ValidationIssue] = list(
        validate_document(profile, "mask_bridge_semantic_invariant_profile")
    )
    hash_issue = _declared_hash_issue(
        profile, hash_field="profile_sha256", excluded=("profile_sha256",)
    )
    if hash_issue:
        issues.append(hash_issue)
    invariants = profile.get("invariants") or ()
    invariant_ids = [row.get("invariant_id") for row in invariants if isinstance(row, Mapping)]
    if len(invariant_ids) != len(set(invariant_ids)):
        issues.append(
            _issue(
                "/invariants", "semantic_invariant_unique", "semantic invariant IDs must be unique"
            )
        )
    fixture_index = profile.get("conformance_fixture_index")
    if isinstance(fixture_index, Mapping):
        rows = fixture_index.get("included_fixtures") or ()
        paths = [row.get("relative_path") for row in rows if isinstance(row, Mapping)]
        if len(paths) != len(set(paths)):
            issues.append(
                _issue(
                    "/conformance_fixture_index/included_fixtures",
                    "fixture_index_unique",
                    "fixture paths must be unique",
                )
            )
        positives = sum(
            1 for row in rows if isinstance(row, Mapping) and row.get("role") == "positive"
        )
        negatives = sum(
            1 for row in rows if isinstance(row, Mapping) and row.get("role") == "negative"
        )
        if (
            fixture_index.get("positive_count") != positives
            or fixture_index.get("negative_count") != negatives
        ):
            issues.append(
                _issue(
                    "/conformance_fixture_index",
                    "fixture_index_counts",
                    "fixture counts do not match indexed rows",
                )
            )
        if fixture_root is not None:
            index_body: list[dict[str, Any]] = []
            for index, row in enumerate(rows):
                if not isinstance(row, Mapping):
                    continue
                path, path_issues = _safe_release_file(fixture_root, row.get("relative_path"))
                issues.extend(
                    _issue(
                        f"/conformance_fixture_index/included_fixtures/{index}",
                        issue.validator,
                        issue.message,
                    )
                    for issue in path_issues
                )
                if path is None:
                    continue
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if digest != row.get("sha256"):
                    issues.append(
                        _issue(
                            f"/conformance_fixture_index/included_fixtures/{index}/sha256",
                            "fixture_file_hash",
                            "fixture raw bytes differ from indexed hash",
                        )
                    )
                index_body.append(
                    {
                        "relative_path": row.get("relative_path"),
                        "role": row.get("role"),
                        "sha256": digest,
                    }
                )
            expected_index_hash = hashlib.sha256(canonical_json_bytes(index_body)).hexdigest()
            if fixture_index.get("sha256") != expected_index_hash:
                issues.append(
                    _issue(
                        "/conformance_fixture_index/sha256",
                        "fixture_index_hash",
                        "fixture-set hash does not bind ordered exact fixture rows",
                    )
                )
    return tuple(sorted(set(issues)))


def validate_mask_authority_invalidation_event(
    event: Mapping[str, Any],
    *,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[ValidationIssue, ...]:
    """Validate signed, per-target, strictly lowering and actionable invalidation."""
    issues: list[ValidationIssue] = list(
        validate_document(event, "mask_authority_invalidation_event")
    )
    hash_issue = _declared_hash_issue(
        event, hash_field="event_payload_sha256", excluded=("event_payload_sha256", "signature")
    )
    if hash_issue:
        issues.append(hash_issue)
    issues.extend(
        _ed25519_signature_issues(
            event,
            payload_hash_field="event_payload_sha256",
            trusted_signing_keys=trusted_signing_keys,
            required_role="producer_journal",
            decision_time=event.get("occurred_at"),
        )
    )
    issues.extend(
        _timestamp_order_issues(
            (
                ("/occurred_at", event.get("occurred_at")),
                ("/effective_at", event.get("effective_at")),
            )
        )
    )
    if event.get("fixture_only") is True and event.get("evidence_context") != "conformance_fixture":
        issues.append(
            _issue(
                "/evidence_context",
                "fixture_evidence_firewall",
                "fixture invalidation cannot affect production authority",
            )
        )
    if event.get("fixture_only") is False and event.get("evidence_context") != "runtime_evidence":
        issues.append(
            _issue(
                "/evidence_context",
                "production_evidence_firewall",
                "production invalidation requires runtime evidence",
            )
        )
    if event.get("fixture_only") is False:
        issues.extend(_production_signing_key_issues(event, trusted_signing_keys))
    transitions = event.get("target_transitions") or ()
    reason = event.get("reason")
    reason_policy = INVALIDATION_REASON_POLICY.get(reason)
    transition_ids: set[str] = set()
    target_keys: set[tuple[Any, Any, Any]] = set()
    for index, transition in enumerate(transitions):
        if not isinstance(transition, Mapping):
            continue
        pointer = f"/target_transitions/{index}"
        transition_id = transition.get("transition_id")
        if transition_id in transition_ids:
            issues.append(
                _issue(
                    f"{pointer}/transition_id",
                    "invalidation_transition_unique",
                    "transition IDs must be unique",
                )
            )
        if isinstance(transition_id, str):
            transition_ids.add(transition_id)
        key = (
            transition.get("target_kind"),
            transition.get("target_id"),
            transition.get("target_sha256"),
        )
        if key in target_keys:
            issues.append(
                _issue(
                    pointer,
                    "invalidation_target_unique",
                    "each exact target may transition only once per event",
                )
            )
        target_keys.add(key)
        if reason_policy is None or transition.get("target_kind") not in reason_policy[0]:
            issues.append(
                _issue(
                    f"{pointer}/target_kind",
                    "invalidation_reason_target_matrix",
                    "target kind is not permitted for this exact invalidation reason",
                )
            )
        previous, new = transition.get("previous_authority_state"), transition.get(
            "new_authority_state"
        )
        if (
            previous not in AUTHORITY_RANK
            or new not in AUTHORITY_RANK
            or AUTHORITY_RANK[new] >= AUTHORITY_RANK[previous]
        ):
            issues.append(
                _issue(
                    f"{pointer}/new_authority_state",
                    "invalidation_strictly_lowers_authority",
                    "every target transition must strictly lower authority",
                )
            )
        if (
            transition.get("previous_certificate_status") == "active"
            and transition.get("new_certificate_status") == "none"
            and transition.get("target_kind") == "certificate"
        ):
            issues.append(
                _issue(
                    f"{pointer}/new_certificate_status",
                    "invalidation_certificate_status",
                    "certificate invalidation must preserve an explicit expired/revoked/superseded terminal status",
                )
            )
    covered: set[str] = set()
    action_ids: set[str] = set()
    observed_actions: set[str] = set()
    for index, action in enumerate(event.get("required_actions") or ()):
        if not isinstance(action, Mapping):
            continue
        if action.get("action_id") in action_ids:
            issues.append(
                _issue(
                    f"/required_actions/{index}/action_id",
                    "invalidation_action_unique",
                    "action IDs must be unique",
                )
            )
        if isinstance(action.get("action_id"), str):
            action_ids.add(action["action_id"])
        if isinstance(action.get("action"), str):
            observed_actions.add(action["action"])
        referenced = set(action.get("transition_ids") or ())
        if not referenced.issubset(transition_ids):
            issues.append(
                _issue(
                    f"/required_actions/{index}/transition_ids",
                    "invalidation_action_reference",
                    "required action references an unknown transition",
                )
            )
        covered.update(referenced)
        issues.extend(
            _timestamp_order_issues(
                (
                    ("/effective_at", event.get("effective_at")),
                    (f"/required_actions/{index}/deadline_at", action.get("deadline_at")),
                )
            )
        )
    if covered != transition_ids:
        issues.append(
            _issue(
                "/required_actions",
                "invalidation_actions_complete",
                "every invalidated target must have at least one explicit consumer action",
            )
        )
    if reason_policy is None or not reason_policy[1].issubset(observed_actions):
        issues.append(
            _issue(
                "/required_actions",
                "invalidation_reason_action_matrix",
                "required actions do not cover the closed policy for this invalidation reason",
            )
        )
    if event.get("reason") == "release_superseded" and not isinstance(
        event.get("superseding_binding"), Mapping
    ):
        issues.append(
            _issue(
                "/superseding_binding",
                "invalidation_superseding_binding",
                "release supersession requires exact replacement release binding",
            )
        )
    if event.get("reason") != "release_superseded" and event.get("superseding_binding") is not None:
        issues.append(
            _issue(
                "/superseding_binding",
                "invalidation_superseding_binding",
                "superseding binding is only valid for release supersession",
            )
        )
    if event.get("severity") != "blocking":
        issues.append(
            _issue(
                "/severity",
                "invalidation_severity",
                "authority, trust, contract and adoption invalidations must block until exact revalidation",
            )
        )
    return tuple(sorted(set(issues)))


def validate_operational_invalidation_event(
    event: Mapping[str, Any],
    *,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
    expected_journal_position: Mapping[str, Any] | None = None,
    seen_event_ids: Iterable[str] | None = None,
    seen_idempotency_keys: Mapping[str, str] | None = None,
) -> tuple[ValidationIssue, ...]:
    """Validate trusted, idempotent operational invalidation continuity."""
    issues: list[ValidationIssue] = list(validate_document(event, "operational_invalidation_event"))
    hash_issue = _declared_hash_issue(
        event, hash_field="event_payload_sha256", excluded=("event_payload_sha256", "signature")
    )
    if hash_issue:
        issues.append(hash_issue)
    issues.extend(
        _ed25519_signature_issues(
            event,
            payload_hash_field="event_payload_sha256",
            trusted_signing_keys=trusted_signing_keys,
            required_role="producer_journal",
            decision_time=event.get("occurred_at"),
        )
    )
    if event.get("fixture_only") is False:
        issues.extend(_production_signing_key_issues(event, trusted_signing_keys))
    issues.extend(
        _timestamp_order_issues(
            (
                ("/occurred_at", event.get("occurred_at")),
                ("/effective_at", event.get("effective_at")),
            ),
            allow_equal=True,
        )
    )

    reason = event.get("reason")
    target_scope = event.get("target_scope")
    if isinstance(target_scope, Mapping):
        target_kind = target_scope.get("target_kind")
        expected_kind = OPERATIONAL_INVALIDATION_REASON_TARGET_KIND.get(reason)
        if expected_kind is not None and target_kind != expected_kind:
            issues.append(
                _issue(
                    "/target_scope/target_kind",
                    "operational_invalidation_reason_target_kind",
                    "reason requires an exact target-kind scope",
                )
            )
        targets = target_scope.get("targets")
        dedupe: set[tuple[Any, Any, Any]] = set()
        canonical_targets: list[dict[str, Any]] = []
        if isinstance(targets, list):
            for index, target in enumerate(targets):
                pointer = f"/target_scope/targets/{index}"
                if not isinstance(target, Mapping):
                    continue
                row_kind = target.get("target_kind")
                if row_kind != target_kind:
                    issues.append(
                        _issue(
                            f"{pointer}/target_kind",
                            "operational_invalidation_target_set_non_homogeneous",
                            "all scoped targets must be homogeneous for one target kind",
                        )
                    )
                key = (row_kind, target.get("target_id"), target.get("target_sha256"))
                if key in dedupe:
                    issues.append(
                        _issue(
                            pointer,
                            "operational_invalidation_target_set_duplicate",
                            "exact target rows must be unique per event",
                        )
                    )
                dedupe.add(key)
                canonical_targets.append(
                    {
                        "target_kind": target.get("target_kind"),
                        "target_id": target.get("target_id"),
                        "target_sha256": target.get("target_sha256"),
                    }
                )
            try:
                expected_scope_sha256 = canonical_document_sha256(
                    {"target_kind": target_kind, "targets": canonical_targets}
                )
            except (TypeError, ValueError):
                expected_scope_sha256 = None
            if (
                expected_scope_sha256 is not None
                and target_scope.get("scope_sha256") != expected_scope_sha256
            ):
                issues.append(
                    _issue(
                        "/target_scope/scope_sha256",
                        "operational_invalidation_scope_hash",
                        "target scope hash must bind the exact target set",
                    )
                )

    if reason == "release_superseded" and not isinstance(event.get("supersession"), Mapping):
        issues.append(
            _issue(
                "/supersession",
                "operational_invalidation_supersession",
                "release supersession invalidation requires exact supersession binding",
            )
        )
    if reason != "release_superseded" and event.get("supersession") is not None:
        issues.append(
            _issue(
                "/supersession",
                "operational_invalidation_supersession",
                "supersession binding is only legal for release_superseded reason",
            )
        )
    if reason == "release_revoked" and not isinstance(event.get("rollback"), Mapping):
        issues.append(
            _issue(
                "/rollback",
                "operational_invalidation_rollback",
                "release revocation invalidation requires exact rollback binding",
            )
        )
    if reason != "release_revoked" and event.get("rollback") is not None:
        issues.append(
            _issue(
                "/rollback",
                "operational_invalidation_rollback",
                "rollback binding is only legal for release_revoked reason",
            )
        )

    sequence = event.get("sequence")
    causation = event.get("causation_id")
    journal_position = event.get("journal_position")
    if isinstance(journal_position, Mapping):
        previous_sequence = journal_position.get("previous_sequence")
        previous_event_id = journal_position.get("previous_event_id")
        if isinstance(sequence, int) and isinstance(previous_sequence, int):
            if previous_sequence != sequence - 1:
                issues.append(
                    _issue(
                        "/journal_position/previous_sequence",
                        "operational_invalidation_journal_reorder",
                        "journal previous sequence must be exactly one less than event sequence",
                    )
                )
            if sequence == 1 and previous_sequence != 0:
                issues.append(
                    _issue(
                        "/journal_position/previous_sequence",
                        "operational_invalidation_journal_genesis",
                        "genesis invalidation event must start from previous sequence zero",
                    )
                )
        if sequence == 1:
            if causation is not None:
                issues.append(
                    _issue(
                        "/causation_id",
                        "operational_invalidation_journal_genesis",
                        "genesis invalidation event cannot declare a causation id",
                    )
                )
            if (
                previous_event_id is not None
                or journal_position.get("previous_event_sha256") is not None
            ):
                issues.append(
                    _issue(
                        "/journal_position",
                        "operational_invalidation_journal_genesis",
                        "genesis invalidation event cannot bind a prior event pointer",
                    )
                )
        elif isinstance(sequence, int) and sequence > 1:
            if not isinstance(causation, str) or not causation:
                issues.append(
                    _issue(
                        "/causation_id",
                        "operational_invalidation_journal_causation",
                        "non-genesis invalidation event must declare a causation id",
                    )
                )
            elif previous_event_id != causation:
                issues.append(
                    _issue(
                        "/journal_position/previous_event_id",
                        "operational_invalidation_journal_causation",
                        "journal previous_event_id must equal causation_id",
                    )
                )

    if isinstance(expected_journal_position, Mapping):
        if expected_journal_position.get("stream_id") is not None and event.get(
            "stream_id"
        ) != expected_journal_position.get("stream_id"):
            issues.append(
                _issue(
                    "/stream_id",
                    "operational_invalidation_journal_fork",
                    "event stream id does not match pinned journal stream",
                )
            )
        expected_sequence = expected_journal_position.get("next_sequence")
        if isinstance(expected_sequence, int) and event.get("sequence") != expected_sequence:
            issues.append(
                _issue(
                    "/sequence",
                    "operational_invalidation_journal_reorder",
                    "event sequence does not match pinned next journal sequence",
                )
            )
        if isinstance(journal_position, Mapping):
            if expected_journal_position.get("head_event_id") is not None and journal_position.get(
                "previous_event_id"
            ) != expected_journal_position.get("head_event_id"):
                issues.append(
                    _issue(
                        "/journal_position/previous_event_id",
                        "operational_invalidation_journal_fork",
                        "event previous_event_id does not match pinned journal head",
                    )
                )
            if expected_journal_position.get(
                "head_event_sha256"
            ) is not None and journal_position.get(
                "previous_event_sha256"
            ) != expected_journal_position.get(
                "head_event_sha256"
            ):
                issues.append(
                    _issue(
                        "/journal_position/previous_event_sha256",
                        "operational_invalidation_journal_fork",
                        "event previous_event_sha256 does not match pinned journal head hash",
                    )
                )
    event_id = event.get("event_id")
    if isinstance(event_id, str) and event_id in set(seen_event_ids or ()):
        issues.append(
            _issue(
                "/event_id",
                "operational_invalidation_journal_replay",
                "event id has already been observed in this journal stream",
            )
        )
    if isinstance(seen_idempotency_keys, Mapping):
        idempotency_key = event.get("idempotency_key")
        if isinstance(idempotency_key, str) and idempotency_key in seen_idempotency_keys:
            previous_hash = seen_idempotency_keys[idempotency_key]
            if previous_hash == event.get("event_payload_sha256"):
                issues.append(
                    _issue(
                        "/idempotency_key",
                        "operational_invalidation_idempotency_replay",
                        "idempotency key was already consumed by the same event payload",
                    )
                )
            else:
                issues.append(
                    _issue(
                        "/idempotency_key",
                        "operational_invalidation_idempotency_fork",
                        "idempotency key was already consumed by a different payload hash",
                    )
                )
    return tuple(sorted(set(issues)))


def validate_mask_repair_feedback(
    feedback: Mapping[str, Any],
    *,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
    parent_receipt: Mapping[str, Any] | None = None,
    parent_request: Mapping[str, Any] | None = None,
    certificate: Mapping[str, Any] | None = None,
) -> tuple[ValidationIssue, ...]:
    """Validate advisory repair feedback as an exact, bounded child hypothesis."""
    issues: list[ValidationIssue] = list(validate_document(feedback, "mask_repair_feedback"))
    hash_issue = _declared_hash_issue(
        feedback,
        hash_field="feedback_payload_sha256",
        excluded=("feedback_payload_sha256", "signature"),
    )
    if hash_issue:
        issues.append(hash_issue)
    issues.extend(
        _ed25519_signature_issues(
            feedback,
            payload_hash_field="feedback_payload_sha256",
            trusted_signing_keys=trusted_signing_keys,
            required_role="consumer_feedback",
            decision_time=feedback.get("created_at"),
        )
    )
    issues.extend(_authentication_issues(feedback, decision_time=feedback.get("created_at")))
    output_rows = feedback.get("output_artifact_bindings") or ()
    protected_rows = feedback.get("protected_artifact_bindings") or ()
    output_ids = [
        row.get("artifact_identity_sha256") for row in output_rows if isinstance(row, Mapping)
    ]
    protected_ids = [
        row.get("artifact_identity_sha256") for row in protected_rows if isinstance(row, Mapping)
    ]
    if (
        len(output_ids) != len(set(output_ids))
        or len(protected_ids) != len(set(protected_ids))
        or set(output_ids) & set(protected_ids)
    ):
        issues.append(
            _issue(
                "/protected_artifact_bindings",
                "repair_artifact_partition",
                "repair output/protected identities must be unique and disjoint",
            )
        )
    budget = feedback.get("retry_budget")
    if isinstance(budget, Mapping):
        attempt, maximum, remaining = (
            budget.get("attempt"),
            budget.get("maximum_attempts"),
            budget.get("remaining_attempts"),
        )
        if all(
            isinstance(value, int) for value in (attempt, maximum, remaining)
        ) and remaining != max(maximum - attempt, 0):
            issues.append(
                _issue(
                    "/retry_budget/remaining_attempts",
                    "repair_retry_budget",
                    "remaining attempts must exactly equal maximum minus current attempt",
                )
            )
    progress = feedback.get("progress_guard")
    if isinstance(progress, Mapping):
        no_progress, maximum = progress.get("no_progress_count"), progress.get(
            "maximum_no_progress_count"
        )
        if (
            isinstance(no_progress, int)
            and isinstance(maximum, int)
            and no_progress >= maximum
            and feedback.get("requested_action") != "quarantine_and_abstain"
        ):
            issues.append(
                _issue(
                    "/requested_action",
                    "repair_no_progress_abstention",
                    "exhausted no-progress budget must quarantine and abstain",
                )
            )
        previous, current, minimum = (
            progress.get("previous_score_ppm"),
            progress.get("current_score_ppm"),
            progress.get("minimum_improvement_ppm"),
        )
        if all(isinstance(value, int) for value in (previous, current, minimum)):
            actual_no_progress = current - previous < minimum
            if actual_no_progress and no_progress == 0:
                issues.append(
                    _issue(
                        "/progress_guard/no_progress_count",
                        "repair_progress_accounting",
                        "no-progress counter must reflect insufficient score improvement",
                    )
                )
    if any(
        feedback.get(field) is not value
        for field, value in (
            ("immutable_accepted_parent", True),
            ("advisory_only", True),
            ("consumer_may_mutate_gold", False),
            ("consumer_may_escalate_authority", False),
        )
    ):
        issues.append(
            _issue(
                "",
                "repair_authority_firewall",
                "consumer feedback is advisory and cannot mutate accepted parents or escalate authority",
            )
        )
    if isinstance(parent_receipt, Mapping):
        parent = feedback.get("parent_receipt_binding")
        if isinstance(parent, Mapping):
            expected = {
                "receipt_id": parent_receipt.get("receipt_id"),
                "receipt_payload_sha256": parent_receipt.get("receipt_payload_sha256"),
                "request_id": parent_receipt.get("request_id"),
                "request_payload_sha256": parent_receipt.get("request_payload_sha256"),
            }
            issues.extend(
                _exact_mapping_issues(
                    expected,
                    parent,
                    pointer="/parent_receipt_binding",
                    validator="repair_parent_receipt_binding",
                )
            )
        for field in ("project_id", "run_id", "job_id", "pass_id"):
            if feedback.get(field) != parent_receipt.get(field):
                issues.append(
                    _issue(
                        f"/{field}",
                        "repair_execution_binding",
                        "repair feedback differs from parent execution identity",
                    )
                )
        release = feedback.get("release_binding")
        parent_release = parent_receipt.get("release_binding")
        if isinstance(release, Mapping) and isinstance(parent_release, Mapping):
            for field in (
                "release_id",
                "release_payload_sha256",
                "capability_snapshot_id",
                "capability_snapshot_sha256",
            ):
                if release.get(field) != parent_release.get(field):
                    issues.append(
                        _issue(
                            f"/release_binding/{field}",
                            "repair_release_binding",
                            "repair feedback differs from parent release/capability binding",
                        )
                    )
        expected_outputs = {
            row.get("artifact_identity_sha256"): row
            for row in parent_receipt.get("artifacts") or ()
            if isinstance(row, Mapping)
        }
        if set(output_ids) != set(expected_outputs):
            issues.append(
                _issue(
                    "/output_artifact_bindings",
                    "repair_output_binding",
                    "repair feedback must bind every exact parent output artifact",
                )
            )
        transform = feedback.get("transform_binding")
        parent_transform = parent_receipt.get("transform_validation")
        if isinstance(transform, Mapping) and isinstance(parent_transform, Mapping):
            for field in ("transform_chain_id", "transform_chain_sha256", "executed_step_sha256s"):
                if transform.get(field) != parent_transform.get(field):
                    issues.append(
                        _issue(
                            f"/transform_binding/{field}",
                            "repair_transform_binding",
                            "repair feedback transform differs from parent receipt",
                        )
                    )
        qa = feedback.get("qa_binding")
        parent_qa = parent_receipt.get("qa")
        if (
            isinstance(qa, Mapping)
            and isinstance(parent_qa, Mapping)
            and qa.get("qa_report_sha256") != parent_qa.get("report_sha256")
        ):
            issues.append(
                _issue(
                    "/qa_binding/qa_report_sha256",
                    "repair_qa_binding",
                    "repair feedback QA report differs from parent receipt",
                )
            )
        authority = feedback.get("authority_binding")
        parent_authority = parent_receipt.get("authority")
        if (
            isinstance(authority, Mapping)
            and isinstance(parent_authority, Mapping)
            and authority.get("authority_state") != parent_authority.get("authority_state")
        ):
            issues.append(
                _issue(
                    "/authority_binding/authority_state",
                    "repair_authority_binding",
                    "repair feedback authority differs from parent",
                )
            )
        hypothesis = feedback.get("hypothesis")
        if isinstance(hypothesis, Mapping) and hypothesis.get(
            "hypothesis_id"
        ) == parent_receipt.get("hypothesis_id"):
            issues.append(
                _issue(
                    "/hypothesis/hypothesis_id",
                    "repair_material_hypothesis",
                    "quality repair must introduce a distinct child hypothesis",
                )
            )
    if isinstance(parent_request, Mapping):
        source = feedback.get("source_binding")
        request_source = parent_request.get("source")
        if isinstance(source, Mapping) and isinstance(request_source, Mapping):
            for field in ("artifact_id", "encoded_sha256", "decoded_pixel_sha256"):
                if source.get(field) != request_source.get(field):
                    issues.append(
                        _issue(
                            f"/source_binding/{field}",
                            "repair_source_binding",
                            "repair feedback differs from parent source raster",
                        )
                    )
        if feedback.get("media_scope_sha256") != canonical_document_sha256(
            parent_request.get("media_scope") or {}
        ):
            issues.append(
                _issue(
                    "/media_scope_sha256",
                    "repair_media_binding",
                    "repair feedback does not bind exact parent media scope",
                )
            )
    if isinstance(certificate, Mapping):
        binding = feedback.get("certificate_binding")
        output_scope = certificate.get("certified_output_scope")
        revocation = certificate.get("revocation")
        if isinstance(binding, Mapping):
            expected = {
                "certificate_id": certificate.get("certificate_id"),
                "certificate_sha256": certificate.get("certificate_payload_sha256"),
                "certificate_scope_sha256": (
                    output_scope.get("scope_sha256") if isinstance(output_scope, Mapping) else None
                ),
                "status": certificate.get("status"),
                "revocation_checked_at": (
                    revocation.get("checked_at") if isinstance(revocation, Mapping) else None
                ),
                "revocation_checkpoint_sha256": (
                    revocation.get("revocation_index_sha256")
                    if isinstance(revocation, Mapping)
                    else None
                ),
            }
            issues.extend(
                _exact_mapping_issues(
                    expected,
                    binding,
                    pointer="/certificate_binding",
                    validator="repair_certificate_binding",
                )
            )
    return tuple(sorted(set(issues)))


# category, retryable, impact_scope, remediation action, retry_after required,
# replacement route required. This is deliberately closed-world: a code cannot
# quietly change operational meaning between producer and consumer releases.
BRIDGE_ERROR_POLICY: dict[str, tuple[str, bool, str, str, bool, bool]] = {
    "SERVICE_UNAVAILABLE": ("availability", True, "request_only", "retry", True, False),
    "TIMEOUT": ("availability", True, "request_only", "retry", True, False),
    "RATE_LIMITED": ("availability", True, "request_only", "retry", True, False),
    "RESOURCE_LIMIT_EXCEEDED": (
        "resource",
        False,
        "request_only",
        "reduce_resource_envelope",
        False,
        False,
    ),
    "OUT_OF_MEMORY": ("resource", False, "request_only", "reduce_resource_envelope", False, False),
    "CIRCUIT_OPEN": ("availability", True, "release", "wait_for_circuit", True, False),
    "RELEASE_NOT_ADOPTED": (
        "compatibility",
        False,
        "consumer_adoption",
        "refresh_release",
        False,
        False,
    ),
    "RELEASE_REVOKED": ("authority", False, "release", "refresh_release", False, False),
    "API_VERSION_MISMATCH": (
        "compatibility",
        False,
        "consumer_adoption",
        "refresh_release",
        False,
        False,
    ),
    "WIRE_SCHEMA_MISMATCH": (
        "compatibility",
        False,
        "consumer_adoption",
        "refresh_release",
        False,
        False,
    ),
    "CONTRACT_VERSION_MISMATCH": (
        "compatibility",
        False,
        "consumer_adoption",
        "refresh_release",
        False,
        False,
    ),
    "PACKAGE_FORMAT_MISMATCH": (
        "compatibility",
        False,
        "dependent_pass",
        "refresh_capabilities",
        False,
        False,
    ),
    "ONTOLOGY_MISMATCH": (
        "compatibility",
        False,
        "dependent_pass",
        "refresh_capabilities",
        False,
        False,
    ),
    "SOURCE_HASH_MISMATCH": ("identity", False, "run", "quarantine", False, False),
    "SOURCE_DIMENSION_MISMATCH": (
        "identity",
        False,
        "dependent_pass",
        "repair_request",
        False,
        False,
    ),
    "PERSON_INDEX_AMBIGUOUS": ("identity", False, "dependent_pass", "repair_request", False, False),
    "OWNERSHIP_AMBIGUOUS": ("identity", False, "dependent_pass", "repair_request", False, False),
    "TRANSFORM_MISMATCH": ("geometry", False, "dependent_pass", "repair_request", False, False),
    "TRANSFORM_ROUNDTRIP_FAILED": (
        "geometry",
        False,
        "dependent_pass",
        "repair_request",
        False,
        False,
    ),
    "LABEL_UNSUPPORTED": (
        "compatibility",
        False,
        "dependent_pass",
        "refresh_capabilities",
        False,
        False,
    ),
    "ARTIFACT_HASH_MISMATCH": ("security", False, "run", "quarantine", False, False),
    "CERTIFICATE_MISSING": (
        "authority",
        False,
        "dependent_pass",
        "refresh_capabilities",
        False,
        False,
    ),
    "CERTIFICATE_EXPIRED": (
        "authority",
        False,
        "dependent_pass",
        "refresh_capabilities",
        False,
        False,
    ),
    "CERTIFICATE_REVOKED": ("authority", False, "run", "quarantine", False, False),
    "CERTIFICATE_OUT_OF_SCOPE": ("authority", False, "dependent_pass", "reroute", False, True),
    "AUTHORITY_INSUFFICIENT": ("authority", False, "dependent_pass", "reroute", False, True),
    "PROVIDER_UNAVAILABLE": ("availability", True, "request_only", "reroute", False, True),
    "NO_ELIGIBLE_ROUTE": (
        "availability",
        False,
        "run",
        "operator_authorization_required",
        False,
        False,
    ),
    "QA_GATE_FAILED": ("quality", False, "dependent_pass", "repair_request", False, False),
    "PATH_ESCAPE_REJECTED": ("security", False, "run", "quarantine", False, False),
    "STALE_CACHE": ("compatibility", True, "dependent_pass", "invalidate_cache", False, False),
    "MALFORMED_RESPONSE": ("internal", True, "request_only", "retry", True, False),
    "UNKNOWN_SUBMISSION": (
        "availability",
        False,
        "request_only",
        "reconcile_submission",
        False,
        False,
    ),
    "INVARIANT_VIOLATION": ("internal", False, "run", "quarantine", False, False),
    "IDEMPOTENCY_CONFLICT": ("request", False, "run", "quarantine", False, False),
    "INVALID_REQUEST": ("request", False, "request_only", "none", False, False),
    "INTERNAL_ERROR": ("internal", True, "request_only", "retry", True, False),
}


def validate_mask_bridge_error(error: Mapping[str, Any]) -> tuple[ValidationIssue, ...]:
    """Validate typed error meaning against the deterministic policy matrix."""
    issues: list[ValidationIssue] = list(validate_document(error, "mask_bridge_error"))
    policy = BRIDGE_ERROR_POLICY.get(str(error.get("code")))
    remediation = error.get("remediation")
    if policy is not None and isinstance(remediation, Mapping):
        category, retryable, impact, action, retry_after_required, replacement = policy
        expected = {
            "/category": (error.get("category"), category),
            "/retryable": (error.get("retryable"), retryable),
            "/impact_scope": (error.get("impact_scope"), impact),
            "/remediation/action": (remediation.get("action"), action),
            "/remediation/replacement_route_required": (
                remediation.get("replacement_route_required"),
                replacement,
            ),
        }
        for pointer, (observed, wanted) in expected.items():
            if observed != wanted:
                issues.append(
                    _issue(pointer, "error_policy_matrix", f"error code requires {wanted!r}")
                )
        retry_after = remediation.get("retry_after_ms")
        if retry_after_required and not isinstance(retry_after, int):
            issues.append(
                _issue(
                    "/remediation/retry_after_ms",
                    "error_retry_after",
                    "retryable delay-based error requires retry_after_ms",
                )
            )
        if not retry_after_required and retry_after is not None:
            issues.append(
                _issue(
                    "/remediation/retry_after_ms",
                    "error_retry_after",
                    "this error code forbids retry_after_ms",
                )
            )
        if action == "none" and any(
            remediation.get(field) is not None for field in ("runbook_id", "runbook_sha256")
        ):
            issues.append(
                _issue(
                    "/remediation",
                    "error_runbook_binding",
                    "no-remediation errors cannot bind a runbook",
                )
            )
        if action != "none" and not (
            isinstance(remediation.get("runbook_id"), str)
            and isinstance(remediation.get("runbook_sha256"), str)
        ):
            issues.append(
                _issue(
                    "/remediation",
                    "error_runbook_binding",
                    "actionable error requires exact runbook ID and hash",
                )
            )
    return tuple(sorted(set(issues)))


def validate_idempotency_records(
    records: Iterable[Mapping[str, Any]],
) -> tuple[ValidationIssue, ...]:
    """Reject body conflicts, nonce replay, and quality retries without a material hypothesis."""
    issues: list[ValidationIssue] = []
    idempotency: dict[str, tuple[Any, ...]] = {}
    nonces: dict[tuple[Any, Any], str] = {}
    attempt_hypotheses: dict[tuple[Any, Any, Any], tuple[Any, Any]] = {}
    for index, record in enumerate(records):
        key = record.get("idempotency_key")
        identity = (
            record.get("request_payload_sha256"),
            record.get("receipt_payload_sha256"),
            record.get("request_id"),
            record.get("attempt_id"),
        )
        if isinstance(key, str):
            previous = idempotency.get(key)
            if previous is not None and previous != identity:
                issues.append(
                    _issue(
                        f"/{index}/idempotency_key",
                        "idempotency_collision",
                        "idempotency key maps to a different request/attempt/body",
                    )
                )
            else:
                idempotency[key] = identity
        auth = record.get("authentication")
        if isinstance(auth, Mapping):
            nonce_key = (auth.get("principal_id"), auth.get("nonce"))
            digest = (
                record.get("request_payload_sha256")
                or record.get("receipt_payload_sha256")
                or record.get("feedback_payload_sha256")
                or record.get("requirements_sha256")
            )
            if nonce_key in nonces and nonces[nonce_key] != digest:
                issues.append(
                    _issue(
                        f"/{index}/authentication/nonce",
                        "authentication_nonce_replay",
                        "authentication nonce was replayed for different payload bytes",
                    )
                )
            elif isinstance(digest, str):
                nonces[nonce_key] = digest
        hypothesis = record.get("hypothesis")
        if isinstance(hypothesis, Mapping):
            attempt_key = (record.get("project_id"), record.get("run_id"), record.get("pass_id"))
            current = (hypothesis.get("hypothesis_id"), hypothesis.get("material_change_sha256"))
            previous = attempt_hypotheses.get(attempt_key)
            if hypothesis.get("retry_kind") == "quality_hypothesis" and previous == current:
                issues.append(
                    _issue(
                        f"/{index}/hypothesis",
                        "quality_retry_material_change",
                        "quality retry requires a distinct, materially changed hypothesis",
                    )
                )
            if hypothesis.get("retry_kind") != "transport_replay":
                attempt_hypotheses[attempt_key] = current
    return tuple(sorted(set(issues)))


_EVENT_TRANSITIONS: dict[str, tuple[str, frozenset[str], str, str]] = {
    "release_published": ("release", frozenset({"none"}), "published", "MaskFactory"),
    "release_adopted": (
        "release",
        frozenset({"published", "partially_adopted", "revalidation_required", "invalidated"}),
        "adopted",
        "Comfy_UI_Main",
    ),
    "release_partially_adopted": (
        "release",
        frozenset({"published", "revalidation_required", "invalidated"}),
        "partially_adopted",
        "Comfy_UI_Main",
    ),
    "release_rejected": (
        "release",
        frozenset({"published", "revalidation_required"}),
        "rejected",
        "Comfy_UI_Main",
    ),
    "release_superseded": (
        "release",
        frozenset({"published", "adopted", "partially_adopted", "revalidation_required"}),
        "superseded",
        "MaskFactory",
    ),
    "release_revoked": (
        "release",
        frozenset({"published", "adopted", "partially_adopted", "revalidation_required"}),
        "revoked",
        "MaskFactory",
    ),
    "adoption_revalidation_required": (
        "release",
        frozenset({"adopted", "partially_adopted"}),
        "revalidation_required",
        "Comfy_UI_Main",
    ),
    "adoption_invalidated": (
        "release",
        frozenset({"adopted", "partially_adopted", "revalidation_required"}),
        "invalidated",
        "Comfy_UI_Main",
    ),
    "capability_snapshot_published": (
        "capability_snapshot",
        frozenset({"none"}),
        "published",
        "MaskFactory",
    ),
    "capabilities_changed": (
        "capability_snapshot",
        frozenset({"published", "active"}),
        "invalidated",
        "MaskFactory",
    ),
    "consumer_requirements_published": (
        "consumer_requirements",
        frozenset({"none"}),
        "published",
        "Comfy_UI_Main",
    ),
    "consumer_requirements_superseded": (
        "consumer_requirements",
        frozenset({"published"}),
        "invalidated",
        "Comfy_UI_Main",
    ),
    "request_submitted": (
        "request",
        frozenset({"none", "reconciled_not_found"}),
        "submitted",
        "Comfy_UI_Main",
    ),
    "request_admitted": ("request", frozenset({"submitted"}), "admitted", "MaskFactory"),
    "request_queued": ("request", frozenset({"admitted"}), "queued", "MaskFactory"),
    "request_started": ("request", frozenset({"queued"}), "running", "MaskFactory"),
    "submission_unknown": (
        "request",
        frozenset({"submitted", "admitted", "queued", "running"}),
        "submission_unknown",
        "Comfy_UI_Main",
    ),
    "submission_reconciled_found_running": (
        "request",
        frozenset({"submission_unknown"}),
        "running",
        "MaskFactory",
    ),
    "submission_reconciled_found_completed_pending_receipt": (
        "request",
        frozenset({"submission_unknown"}),
        "completed_pending_receipt",
        "MaskFactory",
    ),
    "submission_reconciled_found_failed": (
        "request",
        frozenset({"submission_unknown"}),
        "failed",
        "MaskFactory",
    ),
    "submission_reconciled_not_found_safe_to_submit": (
        "request",
        frozenset({"submission_unknown"}),
        "reconciled_not_found",
        "MaskFactory",
    ),
    "request_completed_pending_receipt": (
        "request",
        frozenset({"running"}),
        "completed_pending_receipt",
        "MaskFactory",
    ),
    "receipt_committed": (
        "receipt",
        frozenset({"completed_pending_receipt"}),
        "receipt_committed",
        "MaskFactory",
    ),
    "request_blocked": (
        "request",
        frozenset({"submitted", "admitted", "queued", "running", "submission_unknown"}),
        "blocked",
        "MaskFactory",
    ),
    "request_failed": (
        "request",
        frozenset({"running", "submission_unknown"}),
        "failed",
        "MaskFactory",
    ),
    "request_retry_scheduled": (
        "request",
        frozenset({"blocked", "failed"}),
        "retry_scheduled",
        "Comfy_UI_Main",
    ),
    "circuit_opened": ("circuit", frozenset({"none", "closed"}), "open", "Comfy_UI_Main"),
    "circuit_closed": ("circuit", frozenset({"open"}), "closed", "Comfy_UI_Main"),
    "cache_tombstoned": ("cache", frozenset({"active"}), "tombstoned", "Comfy_UI_Main"),
    "cache_rebuilt": ("cache", frozenset({"tombstoned"}), "active", "Comfy_UI_Main"),
    "authority_certified": ("certificate", frozenset({"none"}), "certified", "MaskFactory"),
    "authority_invalidated": (
        "certificate",
        frozenset({"certified"}),
        "invalidated",
        "MaskFactory",
    ),
    "repair_requested": ("repair", frozenset({"none"}), "requested", "Comfy_UI_Main"),
    "repair_feedback_accepted": ("repair", frozenset({"requested"}), "accepted", "MaskFactory"),
    "repair_feedback_rejected": ("repair", frozenset({"requested"}), "rejected", "MaskFactory"),
    "repair_completed": ("repair", frozenset({"accepted"}), "receipt_committed", "MaskFactory"),
    "recovery_started": (
        "recovery",
        frozenset({"none", "failed", "submission_unknown"}),
        "recovering",
        "Comfy_UI_Main",
    ),
    "recovery_completed": ("recovery", frozenset({"recovering"}), "recovered", "Comfy_UI_Main"),
    "rollback_started": ("rollback", frozenset({"none"}), "rolling_back", "Comfy_UI_Main"),
    "rollback_completed": ("rollback", frozenset({"rolling_back"}), "rolled_back", "Comfy_UI_Main"),
}


def _event_resource_identity(event: Mapping[str, Any], kind: str) -> str:
    subject = event.get("subject")
    subject = subject if isinstance(subject, Mapping) else {}
    field = {
        "release": "release_id",
        "capability_snapshot": "capability_snapshot_id",
        "consumer_requirements": "consumer_requirements_id",
        "request": "request_id",
        "receipt": "request_id",
        "certificate": "certificate_id",
        "cache": "artifact_sha256",
        "repair": "artifact_sha256",
        "circuit": "release_id",
        "recovery": "request_id",
        "rollback": "release_id",
    }.get(kind)
    return f"{kind}:{subject.get(field) or event.get('correlation_id')}"


def validate_bridge_event_chain(
    events: Iterable[Mapping[str, Any]],
    *,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
    expected_head_sha256: str | None = None,
    expected_stream_id: str | None = None,
    checkpoint: Mapping[str, Any] | None = None,
) -> tuple[ValidationIssue, ...]:
    """Validate signed append-only lifecycle journal, legal transitions and pinned head."""
    rows = list(events)
    issues: list[ValidationIssue] = []
    previous_hash: str | None = None
    previous_id: str | None = None
    previous_time: datetime | None = None
    stream_id = expected_stream_id or (rows[0].get("stream_id") if rows else None)
    epoch = rows[0].get("journal_epoch") if rows else None
    states: dict[str, str] = {}
    safe_resubmissions: set[str] = set()
    seen_event_ids: set[str] = set()
    for index, event in enumerate(rows):
        pointer = f"/{index}"
        issues.extend(validate_document(event, "mask_bridge_event"))
        if event.get("event_id") in seen_event_ids:
            issues.append(
                _issue(f"{pointer}/event_id", "event_id_unique", "event IDs must be unique")
            )
        if isinstance(event.get("event_id"), str):
            seen_event_ids.add(event["event_id"])
        if event.get("sequence") != index + 1:
            issues.append(
                _issue(
                    f"{pointer}/sequence",
                    "event_sequence",
                    "journal sequence must be contiguous and start at one",
                )
            )
        if event.get("stream_id") != stream_id or event.get("journal_epoch") != epoch:
            issues.append(
                _issue(
                    pointer,
                    "event_stream_identity",
                    "all journal events must share stream and epoch",
                )
            )
        if event.get("previous_event_sha256") != previous_hash:
            issues.append(
                _issue(
                    f"{pointer}/previous_event_sha256",
                    "previous_event_hash",
                    "event does not bind exact previous event hash",
                )
            )
        if event.get("causation_id") != previous_id:
            issues.append(
                _issue(
                    f"{pointer}/causation_id",
                    "event_causation",
                    "each event must causally bind the immediately preceding journal event",
                )
            )
        occurred = _parse_timestamp(event.get("occurred_at"))
        if occurred is None:
            issues.append(
                _issue(
                    f"{pointer}/occurred_at",
                    "canonical_utc_timestamp",
                    "event timestamp must be canonical UTC Z",
                )
            )
        elif previous_time is not None and occurred < previous_time:
            issues.append(
                _issue(
                    f"{pointer}/occurred_at", "event_time_monotonic", "event time must be monotonic"
                )
            )
        hash_issue = _declared_hash_issue(
            event, hash_field="event_payload_sha256", excluded=("event_payload_sha256", "signature")
        )
        if hash_issue:
            issues.append(
                _issue(f"{pointer}/event_payload_sha256", hash_issue.validator, hash_issue.message)
            )
        role = "producer_journal" if event.get("producer") == "MaskFactory" else "consumer_journal"
        for issue in _ed25519_signature_issues(
            event,
            payload_hash_field="event_payload_sha256",
            trusted_signing_keys=trusted_signing_keys,
            required_role=role,
            decision_time=event.get("occurred_at"),
        ):
            issues.append(_issue(pointer + issue.pointer, issue.validator, issue.message))
        if event.get("fixture_only") is False:
            for issue in _production_signing_key_issues(event, trusted_signing_keys):
                issues.append(_issue(pointer + issue.pointer, issue.validator, issue.message))
        transition = event.get("state_transition")
        rule = _EVENT_TRANSITIONS.get(str(event.get("event_type")))
        if rule is None:
            issues.append(
                _issue(
                    f"{pointer}/event_type",
                    "closed_event_transition_matrix",
                    "event type is absent from the authoritative lifecycle transition matrix",
                )
            )
        if isinstance(transition, Mapping) and rule is not None:
            kind, allowed_from, expected_to, producer = rule
            if (
                transition.get("resource_kind") != kind
                or transition.get("from_state") not in allowed_from
                or transition.get("to_state") != expected_to
                or event.get("producer") != producer
            ):
                issues.append(
                    _issue(
                        f"{pointer}/state_transition",
                        "legal_lifecycle_transition",
                        "event type, producer and state transition do not match the closed lifecycle matrix",
                    )
                )
            resource = _event_resource_identity(event, kind)
            known = states.get(resource)
            if known is not None and transition.get("from_state") != known:
                issues.append(
                    _issue(
                        f"{pointer}/state_transition/from_state",
                        "journal_state_replay",
                        "event from_state does not match replayed journal state",
                    )
                )
            if known is None and transition.get("from_state") not in {
                "none",
                "active",
                "completed_pending_receipt",
                "failed",
                "submission_unknown",
            }:
                # Cross-resource transitions (receipt/certificate/cache/recovery) may start from
                # a state established by their parent record; their signed submission hash binds it.
                if transition.get("submission_identity_sha256") is None:
                    issues.append(
                        _issue(
                            f"{pointer}/state_transition/submission_identity_sha256",
                            "journal_state_bootstrap",
                            "non-genesis resource state requires exact signed bootstrap identity",
                        )
                    )
            states[resource] = str(transition.get("to_state"))
            event_type = event.get("event_type")
            reconciliation = transition.get("reconciliation")
            reconciliation_expectations = {
                "submission_reconciled_found_running": ("found_running", "running", False),
                "submission_reconciled_found_completed_pending_receipt": (
                    "found_completed_pending_receipt",
                    "completed",
                    False,
                ),
                "submission_reconciled_found_failed": ("found_failed", "failed", False),
                "submission_reconciled_not_found_safe_to_submit": (
                    "not_found_safe_to_submit",
                    "not_found",
                    True,
                ),
            }
            expected_reconciliation = reconciliation_expectations.get(str(event_type))
            if expected_reconciliation is None:
                if reconciliation is not None:
                    issues.append(
                        _issue(
                            f"{pointer}/state_transition/reconciliation",
                            "reconciliation_event_only",
                            "only a reconciliation-outcome event may carry remote reconciliation evidence",
                        )
                    )
            elif not isinstance(reconciliation, Mapping):
                issues.append(
                    _issue(
                        f"{pointer}/state_transition/reconciliation",
                        "reconciliation_evidence_required",
                        "reconciliation outcome requires exact remote execution evidence",
                    )
                )
            else:
                expected_outcome, expected_status, may_resubmit = expected_reconciliation
                remote_identity_present = isinstance(
                    reconciliation.get("remote_execution_id"), str
                ) and isinstance(reconciliation.get("remote_execution_sha256"), str)
                result_present = isinstance(reconciliation.get("remote_result_sha256"), str)
                not_found_present = isinstance(reconciliation.get("not_found_evidence_sha256"), str)
                coherent = (
                    reconciliation.get("outcome") == expected_outcome
                    and reconciliation.get("remote_status") == expected_status
                    and reconciliation.get("resubmission_authorized") is may_resubmit
                    and _parse_timestamp(reconciliation.get("checked_at")) is not None
                )
                if may_resubmit:
                    coherent = (
                        coherent
                        and not remote_identity_present
                        and not result_present
                        and not_found_present
                    )
                    if coherent:
                        safe_resubmissions.add(resource)
                elif expected_status == "completed":
                    coherent = (
                        coherent
                        and remote_identity_present
                        and result_present
                        and not not_found_present
                    )
                else:
                    coherent = coherent and remote_identity_present and not not_found_present
                if not coherent:
                    issues.append(
                        _issue(
                            f"{pointer}/state_transition/reconciliation",
                            "reconciliation_outcome_binding",
                            "reconciliation event does not exactly bind its remote outcome, identity, result and resubmission authority",
                        )
                    )
            if event_type == "request_submitted" and known == "reconciled_not_found":
                if resource not in safe_resubmissions:
                    issues.append(
                        _issue(
                            f"{pointer}/event_type",
                            "unknown_submission_no_resubmit",
                            "only a verified remote not-found outcome may authorize one new submission",
                        )
                    )
                else:
                    safe_resubmissions.remove(resource)
            elif event_type == "request_submitted" and known == "submission_unknown":
                issues.append(
                    _issue(
                        f"{pointer}/event_type",
                        "unknown_submission_no_resubmit",
                        "unknown submission must reconcile before any new submission",
                    )
                )
            invalidation_driven = {
                "release_superseded",
                "release_revoked",
                "adoption_revalidation_required",
                "adoption_invalidated",
                "authority_invalidated",
            }
            if event_type in invalidation_driven and not (
                isinstance(transition.get("invalidation_event_id"), str)
                and isinstance(transition.get("invalidation_event_sha256"), str)
                and transition.get("invalidation_event_sha256") == event.get("payload_sha256")
                and (event.get("payload_schema") or {}).get("name")
                == "mask_authority_invalidation_event"
            ):
                issues.append(
                    _issue(
                        f"{pointer}/state_transition",
                        "invalidation_event_binding",
                        "invalidation-driven lifecycle changes must bind the exact signed invalidation document ID and payload hash",
                    )
                )
            elif event_type not in invalidation_driven and (
                transition.get("invalidation_event_id") is not None
                or transition.get("invalidation_event_sha256") is not None
            ):
                issues.append(
                    _issue(
                        f"{pointer}/state_transition",
                        "invalidation_event_binding",
                        "non-invalidation lifecycle events cannot carry invalidation bindings",
                    )
                )
            if (event.get("event_type") == "receipt_committed") is not (
                transition.get("receipt_last_atomic_commit") is True
            ):
                issues.append(
                    _issue(
                        f"{pointer}/state_transition/receipt_last_atomic_commit",
                        "receipt_last_atomic_commit",
                        "only receipt_committed may mark the receipt-last atomic boundary",
                    )
                )
        previous_hash = (
            event.get("event_payload_sha256")
            if isinstance(event.get("event_payload_sha256"), str)
            else None
        )
        previous_id = event.get("event_id") if isinstance(event.get("event_id"), str) else None
        previous_time = occurred or previous_time
    if expected_head_sha256 is not None and previous_hash != expected_head_sha256:
        issues.append(
            _issue(
                "",
                "journal_expected_head",
                "journal head differs from independently pinned expected head",
            )
        )
    if isinstance(checkpoint, Mapping):
        issues.extend(_journal_checkpoint_issues(checkpoint, pointer="/checkpoint"))
        if rows:
            bindings = {
                "stream_id": rows[0].get("stream_id"),
                "genesis_event_id": rows[0].get("event_id"),
                "genesis_event_sha256": rows[0].get("event_payload_sha256"),
                "first_sequence": rows[0].get("sequence"),
                "last_sequence": rows[-1].get("sequence"),
                "event_count": len(rows),
                "head_event_id": rows[-1].get("event_id"),
                "head_event_sha256": rows[-1].get("event_payload_sha256"),
            }
            for field, expected in bindings.items():
                if checkpoint.get(field) != expected:
                    issues.append(
                        _issue(
                            f"/checkpoint/{field}",
                            "journal_checkpoint_binding",
                            "checkpoint does not bind exact complete journal range/head",
                        )
                    )
    return tuple(sorted(set(issues)))


def validate_maskfactory_capability_snapshot(
    snapshot: Mapping[str, Any], *, at_time: Any = None
) -> tuple[ValidationIssue, ...]:
    """Validate a release-bound, partial-library-safe capability snapshot."""
    issues: list[ValidationIssue] = list(
        validate_document(snapshot, "maskfactory_capability_snapshot")
    )
    hash_issue = _declared_hash_issue(
        snapshot, hash_field="snapshot_sha256", excluded=("snapshot_sha256",)
    )
    if hash_issue:
        issues.append(hash_issue)
    if (
        snapshot.get("fixture_only") is True
        and snapshot.get("evidence_context") != "conformance_fixture"
    ):
        issues.append(
            _issue(
                "/evidence_context",
                "fixture_evidence_firewall",
                "fixture capability snapshot must remain conformance-only",
            )
        )
    if (
        snapshot.get("fixture_only") is False
        and snapshot.get("evidence_context") != "runtime_evidence"
    ):
        issues.append(
            _issue(
                "/evidence_context",
                "production_evidence_firewall",
                "production capability snapshot requires live runtime evidence",
            )
        )
    availability = snapshot.get("availability")
    promoted_by_mode: dict[str, set[str]] = {
        "mode_a_package_read": set(),
        "mode_b_live_predict": set(),
        "mode_b_live_refine": set(),
    }
    stack_ids: set[str] = set()
    stack_hashes: set[str] = set()
    route_ids: set[str] = set()
    for index, stack in enumerate(snapshot.get("provider_stacks") or ()):
        if not isinstance(stack, Mapping):
            continue
        pointer = f"/provider_stacks/{index}"
        for field, seen in (("stack_id", stack_ids), ("stack_sha256", stack_hashes)):
            value = stack.get(field)
            if isinstance(value, str):
                if value in seen:
                    issues.append(
                        _issue(f"{pointer}/{field}", f"unique_{field}", f"{field} must be unique")
                    )
                seen.add(value)
        route = stack.get("route_key")
        if isinstance(route, Mapping):
            route_id = route.get("route_key_id")
            if route_id in route_ids:
                issues.append(
                    _issue(
                        f"{pointer}/route_key/route_key_id",
                        "unique_route_id",
                        "route key IDs must be unique",
                    )
                )
            if isinstance(route_id, str):
                route_ids.add(route_id)
        qualification = stack.get("qualification_scope")
        valid_until = (
            _parse_timestamp(qualification.get("valid_until"))
            if isinstance(qualification, Mapping)
            else None
        )
        now = _parse_timestamp(at_time)
        if stack.get("lifecycle") == "promoted":
            if (
                not stack.get("certificate_ids")
                or valid_until is None
                or (now is not None and now >= valid_until)
            ):
                issues.append(
                    _issue(
                        pointer,
                        "promoted_stack_qualification",
                        "promoted stack requires active qualification certificates and unexpired scope",
                    )
                )
            if isinstance(route, Mapping):
                for mode in stack.get("access_modes") or ():
                    promoted_by_mode.setdefault(mode, set()).add(str(route.get("route_key_id")))
        if stack.get("lifecycle") in {"suspended", "retired"} and stack.get("certificate_ids"):
            issues.append(
                _issue(
                    f"{pointer}/certificate_ids",
                    "inactive_stack_certificates",
                    "suspended/retired stacks cannot advertise active certificate IDs",
                )
            )
    if isinstance(availability, Mapping):
        issues.extend(
            _timestamp_order_issues(
                (
                    ("/availability/observed_at", availability.get("observed_at")),
                    ("/availability/valid_until", availability.get("valid_until")),
                ),
                allow_equal=False,
            )
        )
        mode_rows = availability.get("mode_eligibility") or ()
        row_map = {row.get("access_mode"): row for row in mode_rows if isinstance(row, Mapping)}
        expected_modes = {"mode_a_package_read", "mode_b_live_predict", "mode_b_live_refine"}
        if len(row_map) != len(mode_rows) or set(row_map) != expected_modes:
            issues.append(
                _issue(
                    "/availability/mode_eligibility",
                    "capability_mode_matrix",
                    "availability must declare every mode exactly once",
                )
            )
        status_fields = {
            "mode_a_package_read": "mode_a",
            "mode_b_live_predict": "mode_b_predict",
            "mode_b_live_refine": "mode_b_refine",
        }
        advertised_modes = set(snapshot.get("access_modes") or ())
        for mode, field in status_fields.items():
            row = row_map.get(mode)
            if not isinstance(row, Mapping):
                continue
            routes = set(row.get("route_ids") or ())
            status = availability.get(field)
            if row.get("eligible") is True:
                if (
                    mode not in advertised_modes
                    or status not in {"available", "degraded"}
                    or not routes
                    or not routes.issubset(promoted_by_mode.get(mode, set()))
                ):
                    issues.append(
                        _issue(
                            f"/availability/{field}",
                            "capability_mode_eligibility",
                            "eligible mode must be advertised, healthy, and backed only by promoted qualified routes",
                        )
                    )
            else:
                if routes:
                    issues.append(
                        _issue(
                            "/availability/mode_eligibility",
                            "capability_mode_eligibility",
                            "ineligible mode cannot publish route IDs",
                        )
                    )
                if status == "available":
                    issues.append(
                        _issue(
                            f"/availability/{field}",
                            "capability_health_consistency",
                            "available status requires an eligible route",
                        )
                    )
            if mode not in advertised_modes and status != "unavailable":
                issues.append(
                    _issue(
                        f"/availability/{field}",
                        "capability_advertisement_consistency",
                        "unadvertised modes must be unavailable",
                    )
                )
        now = _parse_timestamp(at_time)
        valid = _parse_timestamp(availability.get("valid_until"))
        if now is not None and (valid is None or now >= valid):
            issues.append(
                _issue(
                    "/availability/valid_until",
                    "capability_snapshot_expired",
                    "capability health snapshot is expired at use time",
                )
            )
    endpoints = {
        row.get("operation"): row
        for row in snapshot.get("endpoints") or ()
        if isinstance(row, Mapping)
    }
    for mode, operation in (("mode_b_live_predict", "predict"), ("mode_b_live_refine", "refine")):
        if mode in set(snapshot.get("access_modes") or ()) and (
            not isinstance(endpoints.get(operation), Mapping)
            or endpoints[operation].get("enabled") is not True
        ):
            issues.append(
                _issue(
                    "/endpoints",
                    "capability_endpoint_mode",
                    f"advertised {mode} requires enabled /{operation} endpoint",
                )
            )
    return tuple(sorted(set(issues)))


def validate_maskfactory_consumer_requirements(
    requirements: Mapping[str, Any],
    *,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[ValidationIssue, ...]:
    """Validate authenticated consumer requirements and independently pinned trust roots."""
    issues: list[ValidationIssue] = list(
        validate_document(requirements, "maskfactory_consumer_requirements")
    )
    hash_issue = _declared_hash_issue(
        requirements,
        hash_field="requirements_sha256",
        excluded=("requirements_sha256", "signature"),
    )
    if hash_issue:
        issues.append(hash_issue)
    issues.extend(
        _ed25519_signature_issues(
            requirements,
            payload_hash_field="requirements_sha256",
            trusted_signing_keys=trusted_signing_keys,
            required_role="consumer_requirements",
            decision_time=requirements.get("created_at"),
        )
    )
    issues.extend(
        _authentication_issues(requirements, decision_time=requirements.get("created_at"))
    )
    wire = requirements.get("accepted_wire_schemas") or ()
    names = [row.get("name") for row in wire if isinstance(row, Mapping)]
    if len(names) != len(set(names)) or set(names) != set(BRIDGE_SCHEMA_NAMES):
        issues.append(
            _issue(
                "/accepted_wire_schemas",
                "wire_schema_closed_set",
                "consumer requirements must pin all bridge schemas exactly once",
            )
        )
    seen_capabilities: set[str] = set()
    for collection in ("required_capabilities", "optional_capabilities"):
        for index, capability in enumerate(requirements.get(collection) or ()):
            if not isinstance(capability, Mapping):
                continue
            capability_id = capability.get("capability_id")
            if capability_id in seen_capabilities:
                issues.append(
                    _issue(
                        f"/{collection}/{index}/capability_id",
                        "capability_requirement_unique",
                        "capability IDs must be unique across required and optional sets",
                    )
                )
            if isinstance(capability_id, str):
                seen_capabilities.add(capability_id)
    key_ids: set[str] = set()
    authorities: set[str] = set()
    for set_index, key_set in enumerate(requirements.get("trusted_signing_key_sets") or ()):
        if not isinstance(key_set, Mapping):
            continue
        authority = key_set.get("authority")
        if authority in authorities:
            issues.append(
                _issue(
                    f"/trusted_signing_key_sets/{set_index}/authority",
                    "trust_authority_unique",
                    "each trust authority must appear once",
                )
            )
        if isinstance(authority, str):
            authorities.add(authority)
        for key_index, key in enumerate(key_set.get("trusted_keys") or ()):
            if not isinstance(key, Mapping):
                continue
            key_id = key.get("key_id")
            if key_id in key_ids:
                issues.append(
                    _issue(
                        f"/trusted_signing_key_sets/{set_index}/trusted_keys/{key_index}/key_id",
                        "trusted_key_unique",
                        "trusted key IDs must be globally unique",
                    )
                )
            if isinstance(key_id, str):
                key_ids.add(key_id)
            issues.extend(
                _timestamp_order_issues(
                    (
                        (
                            f"/trusted_signing_key_sets/{set_index}/trusted_keys/{key_index}/valid_from",
                            key.get("valid_from"),
                        ),
                        (
                            f"/trusted_signing_key_sets/{set_index}/trusted_keys/{key_index}/valid_until",
                            key.get("valid_until"),
                        ),
                    ),
                    allow_equal=False,
                )
            )
    authority = requirements.get("authority_requirements")
    if isinstance(authority, Mapping) and set(
        authority.get("accepted_certificate_kinds") or ()
    ) != {"exact_serving_route_output"}:
        issues.append(
            _issue(
                "/authority_requirements/accepted_certificate_kinds",
                "exact_operational_certificate_only",
                "core consumer requirements must accept only exact-output operational certificates for certified use",
            )
        )
    runtime = requirements.get("runtime_requirements")
    if isinstance(runtime, Mapping):
        if runtime.get("maximum_p50_latency_ms", 0) > runtime.get("maximum_p95_latency_ms", 0):
            issues.append(
                _issue(
                    "/runtime_requirements/maximum_p50_latency_ms",
                    "latency_percentile_order",
                    "p50 latency ceiling cannot exceed p95",
                )
            )
        if runtime.get("request_timeout_ms", 0) < runtime.get("maximum_queue_ms", 0) + runtime.get(
            "maximum_p95_latency_ms", 0
        ):
            issues.append(
                _issue(
                    "/runtime_requirements/request_timeout_ms",
                    "runtime_timeout_budget",
                    "request timeout must cover maximum queue plus p95 execution",
                )
            )
    return tuple(sorted(set(issues)))


def _journal_checkpoint_issues(
    checkpoint: Any, *, pointer: str, use_time: Any = None
) -> list[ValidationIssue]:
    if not isinstance(checkpoint, Mapping):
        return []
    issues: list[ValidationIssue] = []
    first, last, count = (
        checkpoint.get("first_sequence"),
        checkpoint.get("last_sequence"),
        checkpoint.get("event_count"),
    )
    if all(isinstance(value, int) for value in (first, last, count)) and count != last - first + 1:
        issues.append(
            _issue(
                f"{pointer}/event_count",
                "journal_checkpoint_contiguous",
                "event_count must exactly cover the pinned contiguous sequence range",
            )
        )
    issues.extend(
        _timestamp_order_issues(
            (
                (f"{pointer}/checkpointed_at", checkpoint.get("checkpointed_at")),
                (f"{pointer}/fresh_until", checkpoint.get("fresh_until")),
            ),
            allow_equal=False,
        )
    )
    use = _parse_timestamp(use_time)
    fresh = _parse_timestamp(checkpoint.get("fresh_until"))
    if use is not None and (fresh is None or use >= fresh):
        issues.append(
            _issue(
                f"{pointer}/fresh_until",
                "revocation_checkpoint_freshness",
                "journal/revocation checkpoint is stale at use time",
            )
        )
    if checkpoint.get("first_sequence") == 1 and checkpoint.get("event_count") == 1:
        if checkpoint.get("genesis_event_id") != checkpoint.get("head_event_id") or checkpoint.get(
            "genesis_event_sha256"
        ) != checkpoint.get("head_event_sha256"):
            issues.append(
                _issue(
                    pointer,
                    "journal_singleton_checkpoint",
                    "single-event checkpoint must have identical genesis and head",
                )
            )
    return issues


def validate_maskfactory_release_snapshot(
    snapshot: Mapping[str, Any],
    *,
    completion_profiles: Iterable[Mapping[str, Any]] | None = None,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
    at_time: Any = None,
) -> tuple[ValidationIssue, ...]:
    """Validate immutable producer release, trust, journal bootstrap and claim firewall."""
    issues: list[ValidationIssue] = list(
        validate_document(snapshot, "maskfactory_release_snapshot")
    )
    hash_issue = _declared_hash_issue(
        snapshot,
        hash_field="release_payload_sha256",
        excluded=("release_payload_sha256", "signature"),
    )
    if hash_issue:
        issues.append(hash_issue)
    issues.extend(
        _ed25519_signature_issues(
            snapshot,
            payload_hash_field="release_payload_sha256",
            trusted_signing_keys=trusted_signing_keys,
            required_role="producer_release",
            decision_time=snapshot.get("published_at"),
        )
    )
    if snapshot.get("fixture_only") is True and not (
        snapshot.get("release_status") == "fixture"
        and snapshot.get("evidence_context") == "conformance_fixture"
    ):
        issues.append(
            _issue(
                "/evidence_context",
                "fixture_evidence_firewall",
                "fixture releases cannot be published runtime evidence",
            )
        )
    if (
        snapshot.get("fixture_only") is False
        and snapshot.get("evidence_context") != "runtime_evidence"
    ):
        issues.append(
            _issue(
                "/evidence_context",
                "production_evidence_firewall",
                "production release requires runtime evidence",
            )
        )
    if snapshot.get("fixture_only") is False:
        issues.extend(_production_signing_key_issues(snapshot, trusted_signing_keys))
    security_policy = snapshot.get("artifact_security_policy")
    if isinstance(security_policy, Mapping):
        expected_policy_sha256 = canonical_document_sha256(
            security_policy, excluded_top_level_fields=("policy_sha256",)
        )
        if security_policy.get("policy_sha256") != expected_policy_sha256:
            issues.append(
                _issue(
                    "/artifact_security_policy/policy_sha256",
                    "artifact_security_policy_hash",
                    "artifact security policy hash does not bind the complete signed policy body",
                )
            )
    issues.extend(
        _journal_checkpoint_issues(
            snapshot.get("journal_checkpoint"), pointer="/journal_checkpoint", use_time=at_time
        )
    )
    producer = snapshot.get("producer")
    if isinstance(producer, Mapping) and producer.get("dirty") is not False:
        issues.append(
            _issue(
                "/producer/dirty",
                "clean_release_tree",
                "producer release must come from a clean exact git tree",
            )
        )
    wire = snapshot.get("wire_schemas") or ()
    names = [row.get("name") for row in wire if isinstance(row, Mapping)]
    if len(names) != len(set(names)) or set(names) != set(BRIDGE_SCHEMA_NAMES):
        issues.append(
            _issue(
                "/wire_schemas",
                "wire_schema_closed_set",
                "release must publish all 12 wire schemas exactly once",
            )
        )
    for index, row in enumerate(wire):
        if not isinstance(row, Mapping):
            continue
        name = row.get("name")
        if isinstance(name, str):
            expected_path = f"src/maskfactory/schemas/{name}.schema.json"
            expected_id = f"https://maskfactory.local/schemas/{name}.schema.json"
            if row.get("relative_path") != expected_path or row.get("schema_id") != expected_id:
                issues.append(
                    _issue(
                        f"/wire_schemas/{index}",
                        "wire_schema_identity",
                        "wire schema name, $id and canonical path must agree",
                    )
                )
    declared_profile_rows = [
        row for row in snapshot.get("completion_profiles") or () if isinstance(row, Mapping)
    ]
    declared_profiles = {row.get("profile_id"): row for row in declared_profile_rows}
    if (
        len(declared_profile_rows) != len(declared_profiles)
        or set(declared_profiles) != COMPLETION_PROFILE_IDS
    ):
        issues.append(
            _issue(
                "/completion_profiles",
                "completion_profile_closed_set",
                "release must bind the three completion tracks exactly once",
            )
        )
    supplied_profiles = None if completion_profiles is None else tuple(completion_profiles)
    if snapshot.get("fixture_only") is False and supplied_profiles is None:
        issues.append(
            _issue(
                "/completion_profiles",
                "completion_profile_evidence_required",
                "production release validation requires all three exact completion-profile documents or an independently trusted catalog",
            )
        )
    if supplied_profiles is not None:
        actual_profiles = {
            profile.get("profile_id"): profile
            for profile in supplied_profiles
            if isinstance(profile, Mapping)
        }
        if (
            len(supplied_profiles) != len(actual_profiles)
            or set(actual_profiles) != COMPLETION_PROFILE_IDS
        ):
            issues.append(
                _issue(
                    "/completion_profiles",
                    "completion_profile_evidence_closed_set",
                    "completion-profile evidence must contain the three exact profile documents once each and no extras",
                )
            )
        for profile_id in COMPLETION_PROFILE_IDS:
            profile = actual_profiles.get(profile_id)
            declared = declared_profiles.get(profile_id)
            if not isinstance(profile, Mapping) or not isinstance(declared, Mapping):
                continue
            profile_issues = validate_document(profile, "completion_profile")
            issues.extend(
                _issue(
                    f"/completion_profiles/{profile_id}{issue.pointer}",
                    issue.validator,
                    issue.message,
                )
                for issue in profile_issues
            )
            expected_hash = canonical_document_sha256(
                profile, excluded_top_level_fields=("policy_sha256",)
            )
            expected_path = f"qa/governance/completion/{profile_id}_v1.json"
            if profile.get("policy_sha256") != expected_hash:
                issues.append(
                    _issue(
                        f"/completion_profiles/{profile_id}/policy_sha256",
                        "completion_profile_self_hash",
                        "completion profile policy_sha256 does not bind its canonical body",
                    )
                )
            if (
                declared.get("policy_sha256") != expected_hash
                or declared.get("profile_version") != profile.get("profile_version")
                or declared.get("required_for_core_runtime")
                is not profile.get("required_for_core_runtime")
                or declared.get("relative_path") != expected_path
            ):
                issues.append(
                    _issue(
                        "/completion_profiles",
                        "completion_profile_hash_binding",
                        f"release does not bind completion profile {profile_id!r} exactly",
                    )
                )
    artifact_rows = [row for row in snapshot.get("artifacts") or () if isinstance(row, Mapping)]
    artifact_kinds = [row.get("kind") for row in artifact_rows]
    artifact_paths = [row.get("relative_path") for row in artifact_rows]
    if (
        len(artifact_rows) != len(REQUIRED_RELEASE_ARTIFACT_KINDS)
        or set(artifact_kinds) != REQUIRED_RELEASE_ARTIFACT_KINDS
        or len(artifact_kinds) != len(set(artifact_kinds))
    ):
        issues.append(
            _issue(
                "/artifacts",
                "release_artifact_kind_closed_set",
                "release artifacts must contain every required artifact kind exactly once",
            )
        )
    if len(artifact_paths) != len(set(artifact_paths)) or len(
        {str(path).casefold() for path in artifact_paths}
    ) != len(artifact_paths):
        issues.append(
            _issue(
                "/artifacts",
                "release_artifact_path_unique",
                "release artifact paths must be unique without case-fold aliases",
            )
        )
    artifacts_by_kind = {row.get("kind"): row for row in artifact_rows}
    for field, kind in (
        ("openapi", "openapi_document"),
        ("certificate_index", "certificate_index"),
    ):
        binding = snapshot.get(field)
        artifact = artifacts_by_kind.get(kind)
        if (
            not isinstance(binding, Mapping)
            or not isinstance(artifact, Mapping)
            or any(binding.get(name) != artifact.get(name) for name in ("relative_path", "sha256"))
        ):
            issues.append(
                _issue(
                    f"/{field}",
                    "release_artifact_cross_binding",
                    f"{field} must resolve to its one exact catalog artifact",
                )
            )
    if snapshot.get("release_id") in set(snapshot.get("revoked_release_ids") or ()):
        issues.append(
            _issue(
                "/revoked_release_ids",
                "release_self_revocation",
                "release cannot list itself as a prior revoked release",
            )
        )
    return tuple(sorted(set(issues)))


def _safe_release_file(root: Path, relative_path: Any) -> tuple[Path | None, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    pointer = str(relative_path)
    if not isinstance(relative_path, str):
        return None, [_issue("", "release_path", "release path must be a string")]
    pure = PurePosixPath(relative_path)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or "\\" in relative_path
        or ":" in pure.parts[0]
        or relative_path.startswith(("//", "\\\\"))
    ):
        return None, [_issue("", "path_containment", f"unsafe release path rejected: {pointer!r}")]
    root_resolved = root.resolve(strict=True)
    candidate = root.joinpath(*pure.parts)
    try:
        for parent in (candidate, *candidate.parents):
            if parent == root.parent:
                break
            if parent.exists():
                stat = parent.lstat()
                is_reparse = bool(getattr(stat, "st_file_attributes", 0) & 0x400)
                if parent.is_symlink() or is_reparse:
                    issues.append(
                        _issue(
                            "",
                            "path_indirection",
                            f"symlink/reparse path rejected: {relative_path!r}",
                        )
                    )
                    return None, issues
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (FileNotFoundError, ValueError, OSError):
        return None, [
            _issue(
                "", "path_containment", f"release file missing or escapes root: {relative_path!r}"
            )
        ]
    stat = resolved.stat()
    if not resolved.is_file():
        issues.append(
            _issue(
                "", "release_regular_file", f"release path is not a regular file: {relative_path!r}"
            )
        )
    if stat.st_nlink > 1:
        issues.append(
            _issue("", "hardlink_rejected", f"hardlinked release file rejected: {relative_path!r}")
        )
    return resolved, issues


def _archive_security_issues(
    path: Path, policy: Mapping[str, Any], *, pointer: str
) -> list[ValidationIssue]:
    if path.suffix.lower() not in {".zip", ".whl"}:
        return []
    issues: list[ValidationIssue] = []
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > int(policy.get("maximum_archive_files", 0)):
                issues.append(
                    _issue(pointer, "archive_file_count", "archive exceeds maximum file count")
                )
            expanded = sum(row.file_size for row in entries)
            if expanded > int(policy.get("maximum_archive_expanded_bytes", 0)):
                issues.append(
                    _issue(
                        pointer, "archive_expanded_size", "archive exceeds maximum expanded bytes"
                    )
                )
            seen_members: set[str] = set()
            seen_casefold: dict[str, str] = {}
            for row in entries:
                pure = PurePosixPath(row.filename)
                if (
                    pure.is_absolute()
                    or any(part in {"", ".", ".."} for part in pure.parts)
                    or "\\" in row.filename
                    or ":" in (pure.parts[0] if pure.parts else "")
                ):
                    issues.append(
                        _issue(
                            pointer,
                            "archive_path_escape",
                            f"unsafe archive member: {row.filename!r}",
                        )
                    )
                normalized_name = unicodedata.normalize("NFC", row.filename)
                folded_name = normalized_name.casefold()
                if normalized_name in seen_members:
                    issues.append(
                        _issue(
                            pointer,
                            "archive_duplicate_member",
                            f"duplicate archive member rejected: {row.filename!r}",
                        )
                    )
                seen_members.add(normalized_name)
                if folded_name in seen_casefold and seen_casefold[folded_name] != normalized_name:
                    issues.append(
                        _issue(
                            pointer,
                            "archive_member_case_collision",
                            f"case-colliding archive members rejected: {seen_casefold[folded_name]!r}, {normalized_name!r}",
                        )
                    )
                else:
                    seen_casefold[folded_name] = normalized_name
                unix_mode = (row.external_attr >> 16) & 0xFFFF
                file_type = stat.S_IFMT(unix_mode)
                dos_attributes = row.external_attr & 0xFFFF
                if (
                    stat.S_ISLNK(unix_mode)
                    or (file_type not in {0, stat.S_IFREG, stat.S_IFDIR})
                    or (dos_attributes & 0x400)
                ):
                    issues.append(
                        _issue(
                            pointer,
                            "archive_indirection_or_special",
                            f"archive symlink, reparse, hardlink-like or special member rejected: {row.filename!r}",
                        )
                    )
                if row.flag_bits & 0x1:
                    issues.append(
                        _issue(
                            pointer,
                            "archive_encrypted_member",
                            f"encrypted archive member rejected: {row.filename!r}",
                        )
                    )
                compressed = max(row.compress_size, 1)
                if row.file_size / compressed > int(policy.get("maximum_compression_ratio", 0)):
                    issues.append(
                        _issue(
                            pointer,
                            "archive_compression_ratio",
                            f"archive member exceeds compression-ratio ceiling: {row.filename!r}",
                        )
                    )
    except (zipfile.BadZipFile, OSError):
        issues.append(
            _issue(pointer, "archive_integrity", "declared archive cannot be safely opened")
        )
    return issues


def validate_maskfactory_release_bundle(
    snapshot: Mapping[str, Any],
    *,
    root: Path,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
    completion_profiles: Iterable[Mapping[str, Any]] | None = None,
) -> tuple[ValidationIssue, ...]:
    """Verify exact file closure, raw hashes and archive safety for one release root."""
    issues: list[ValidationIssue] = list(
        validate_maskfactory_release_snapshot(
            snapshot,
            completion_profiles=completion_profiles,
            trusted_signing_keys=trusted_signing_keys,
        )
    )
    declared: list[tuple[str, str, str, int | None]] = []
    for row in snapshot.get("wire_schemas") or ():
        if isinstance(row, Mapping):
            declared.append(
                (
                    f"/wire_schemas/{row.get('name')}",
                    str(row.get("relative_path")),
                    str(row.get("sha256")),
                    None,
                )
            )
    canonicalization_spec = snapshot.get("canonicalization_spec")
    if isinstance(canonicalization_spec, Mapping):
        declared.extend(
            (
                (
                    "/canonicalization_spec",
                    str(canonicalization_spec.get("relative_path")),
                    str(canonicalization_spec.get("sha256")),
                    None,
                ),
                (
                    "/canonicalization_spec/golden_vectors",
                    str(canonicalization_spec.get("golden_vectors_relative_path")),
                    str(canonicalization_spec.get("golden_vectors_sha256")),
                    None,
                ),
            )
        )
    semantic = snapshot.get("semantic_invariant_profile")
    if isinstance(semantic, Mapping):
        declared.append(
            (
                "/semantic_invariant_profile",
                str(semantic.get("relative_path")),
                str(semantic.get("document_sha256")),
                None,
            )
        )
    capability = snapshot.get("capability_snapshot")
    if isinstance(capability, Mapping):
        declared.append(
            (
                "/capability_snapshot",
                str(capability.get("relative_path")),
                str(capability.get("document_sha256")),
                None,
            )
        )
    for field in ("workflow_inventory", "node_inventory", "evidence_index"):
        row = snapshot.get(field)
        if isinstance(row, Mapping):
            declared.append(
                (f"/{field}", str(row.get("relative_path")), str(row.get("sha256")), None)
            )
    for index, row in enumerate(snapshot.get("completion_profiles") or ()):
        if isinstance(row, Mapping):
            declared.append(
                (
                    f"/completion_profiles/{index}",
                    str(row.get("relative_path")),
                    str(row.get("document_sha256")),
                    None,
                )
            )
    for index, row in enumerate(snapshot.get("artifacts") or ()):
        if isinstance(row, Mapping):
            declared.append(
                (
                    f"/artifacts/{index}",
                    str(row.get("relative_path")),
                    str(row.get("sha256")),
                    row.get("size_bytes") if isinstance(row.get("size_bytes"), int) else None,
                )
            )
    declared_paths = [relative for _, relative, _, _ in declared]
    if len(declared_paths) != len(set(declared_paths)) or len(
        {path.casefold() for path in declared_paths}
    ) != len(declared_paths):
        issues.append(
            _issue(
                "/",
                "release_catalog_path_unique",
                "release catalog contains duplicate or case-aliased paths",
            )
        )
    seen_casefold: dict[str, str] = {}
    policy = snapshot.get("artifact_security_policy")
    policy = policy if isinstance(policy, Mapping) else {}
    for pointer, relative, expected_hash, expected_size in declared:
        folded = relative.casefold()
        if folded in seen_casefold and seen_casefold[folded] != relative:
            issues.append(
                _issue(
                    pointer,
                    "path_case_collision",
                    f"case-colliding release paths: {seen_casefold[folded]!r}, {relative!r}",
                )
            )
        else:
            seen_casefold[folded] = relative
        path, path_issues = _safe_release_file(root, relative)
        issues.extend(_issue(pointer, issue.validator, issue.message) for issue in path_issues)
        if path is None:
            continue
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_hash:
            issues.append(
                _issue(
                    pointer, "release_file_hash", "declared file SHA-256 does not match raw bytes"
                )
            )
        if expected_size is not None and len(raw) != expected_size:
            issues.append(
                _issue(pointer, "release_file_size", "declared file size does not match raw bytes")
            )
        if len(raw) > int(policy.get("maximum_file_bytes", 2**63 - 1)):
            issues.append(
                _issue(
                    pointer,
                    "release_file_size_limit",
                    "release file exceeds security-policy ceiling",
                )
            )
        issues.extend(_archive_security_issues(path, policy, pointer=pointer))
        if relative.startswith("src/maskfactory/schemas/"):
            try:
                schema = load_canonical_json(raw)
                name = Path(relative).name.removesuffix(".schema.json")
                if schema.get("$id") != f"https://maskfactory.local/schemas/{name}.schema.json":
                    issues.append(
                        _issue(
                            pointer,
                            "wire_schema_content_identity",
                            "wire schema $id does not match release row name/path",
                        )
                    )
                Draft202012Validator.check_schema(schema)
            except Exception as exc:  # schema bundle is a trust boundary
                issues.append(
                    _issue(pointer, "wire_schema_content", f"wire schema content is invalid: {exc}")
                )
    manifest_relative = policy.get("allowed_root_manifest_relative_path")
    manifest_path, manifest_path_issues = _safe_release_file(root, manifest_relative)
    issues.extend(
        _issue(
            "/artifact_security_policy/allowed_root_manifest_relative_path",
            issue.validator,
            issue.message,
        )
        for issue in manifest_path_issues
    )
    if manifest_path is not None:
        manifest_raw = manifest_path.read_bytes()
        if hashlib.sha256(manifest_raw).hexdigest() != policy.get("allowed_root_manifest_sha256"):
            issues.append(
                _issue(
                    "/artifact_security_policy/allowed_root_manifest_sha256",
                    "allowed_root_manifest_hash",
                    "allowed-root manifest raw hash differs from the signed release policy",
                )
            )
        try:
            manifest = load_canonical_json(manifest_raw)
        except Exception as exc:
            manifest = None
            issues.append(
                _issue(
                    "/artifact_security_policy/allowed_root_manifest_relative_path",
                    "allowed_root_manifest_parse",
                    f"allowed-root manifest is invalid JSON: {exc}",
                )
            )
        if isinstance(manifest, Mapping):
            if (
                set(manifest) != {"schema_version", "record_type", "files"}
                or manifest.get("schema_version") != "1.0.0"
                or manifest.get("record_type") != "maskfactory_allowed_root_manifest"
            ):
                issues.append(
                    _issue(
                        "/artifact_security_policy/allowed_root_manifest_relative_path",
                        "allowed_root_manifest_contract",
                        "allowed-root manifest envelope is not the exact supported contract",
                    )
                )
            manifest_rows = [row for row in manifest.get("files") or () if isinstance(row, Mapping)]
            manifest_paths = [row.get("relative_path") for row in manifest_rows]
            if (
                len(manifest_rows) != len(declared)
                or len(manifest_paths) != len(set(manifest_paths))
                or len({str(path).casefold() for path in manifest_paths}) != len(manifest_paths)
            ):
                issues.append(
                    _issue(
                        "/artifact_security_policy/allowed_root_manifest_relative_path",
                        "allowed_root_manifest_closed_set",
                        "allowed-root manifest must enumerate each release catalog file exactly once without aliases",
                    )
                )
            expected_catalog = {
                relative: (expected_hash, expected_size)
                for _, relative, expected_hash, expected_size in declared
            }
            observed_catalog = {
                str(row.get("relative_path")): (row.get("sha256"), row.get("size_bytes"))
                for row in manifest_rows
            }
            if set(observed_catalog) != set(expected_catalog):
                issues.append(
                    _issue(
                        "/artifact_security_policy/allowed_root_manifest_relative_path",
                        "allowed_root_manifest_closed_set",
                        "allowed-root manifest path set differs from the signed release catalog",
                    )
                )
            for relative, (expected_hash, expected_size) in expected_catalog.items():
                observed = observed_catalog.get(relative)
                if (
                    observed is None
                    or observed[0] != expected_hash
                    or (expected_size is not None and observed[1] != expected_size)
                ):
                    issues.append(
                        _issue(
                            "/artifact_security_policy/allowed_root_manifest_relative_path",
                            "allowed_root_manifest_binding",
                            f"allowed-root manifest does not exactly bind {relative!r}",
                        )
                    )
    try:
        root_resolved = root.resolve(strict=True)
        actual_files = {
            path.relative_to(root_resolved).as_posix()
            for path in root_resolved.rglob("*")
            if path.is_file()
        }
        expected_files = set(declared_paths)
        if isinstance(manifest_relative, str):
            expected_files.add(manifest_relative)
        if actual_files != expected_files:
            issues.append(
                _issue(
                    "/artifact_security_policy",
                    "release_root_closed_set",
                    "release root contains missing or unmanifested files",
                )
            )
    except (FileNotFoundError, OSError, ValueError) as exc:
        issues.append(
            _issue(
                "/artifact_security_policy",
                "release_root_enumeration",
                f"release root cannot be enumerated safely: {exc}",
            )
        )
    return tuple(sorted(set(issues)))


def validate_maskfactory_qualification_bundle(
    bundle: Mapping[str, Any],
    *,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
    evidence_root: Path | None = None,
    release_snapshot: Mapping[str, Any] | None = None,
    capability_snapshot: Mapping[str, Any] | None = None,
    consumer_requirements: Mapping[str, Any] | None = None,
    completion_profiles: Iterable[Mapping[str, Any]] | None = None,
) -> tuple[ValidationIssue, ...]:
    """Validate executed qualification results and every referenced evidence byte."""
    issues: list[ValidationIssue] = list(
        validate_document(bundle, "maskfactory_qualification_bundle")
    )
    hash_issue = _declared_hash_issue(
        bundle,
        hash_field="qualification_payload_sha256",
        excluded=("qualification_payload_sha256", "signature"),
    )
    if hash_issue:
        issues.append(hash_issue)
    issues.extend(
        _ed25519_signature_issues(
            bundle,
            payload_hash_field="qualification_payload_sha256",
            trusted_signing_keys=trusted_signing_keys,
            required_role="consumer_qualification",
            decision_time=bundle.get("executed_at"),
        )
    )
    issues.extend(_authentication_issues(bundle, decision_time=bundle.get("executed_at")))
    production = bundle.get("fixture_only") is False
    if (
        bundle.get("fixture_only") is True
        and bundle.get("evidence_context") != "conformance_fixture"
    ):
        issues.append(
            _issue(
                "/evidence_context",
                "fixture_evidence_firewall",
                "fixture qualification is conformance evidence only",
            )
        )
    if production:
        if bundle.get("evidence_context") != "runtime_evidence":
            issues.append(
                _issue(
                    "/evidence_context",
                    "production_evidence_firewall",
                    "production qualification requires runtime evidence",
                )
            )
        issues.extend(_production_signing_key_issues(bundle, trusted_signing_keys))
        if evidence_root is None:
            issues.append(
                _issue(
                    "/evidence_catalog",
                    "qualification_evidence_root_required",
                    "production qualification requires byte access to the complete evidence catalog",
                )
            )

    checks = [row for row in bundle.get("compatibility_checks") or () if isinstance(row, Mapping)]
    check_ids = [row.get("check") for row in checks]
    if len(check_ids) != len(set(check_ids)) or set(check_ids) != ADOPTION_COMPATIBILITY_CHECKS:
        issues.append(
            _issue(
                "/compatibility_checks",
                "qualification_check_closed_set",
                "qualification must execute every adoption compatibility check exactly once",
            )
        )
    catalog = [row for row in bundle.get("evidence_catalog") or () if isinstance(row, Mapping)]
    catalog_ids = [row.get("evidence_id") for row in catalog]
    catalog_paths = [row.get("relative_path") for row in catalog]
    if (
        len(catalog_ids) != len(set(catalog_ids))
        or len(catalog_paths) != len(set(catalog_paths))
        or len({str(path).casefold() for path in catalog_paths}) != len(catalog_paths)
    ):
        issues.append(
            _issue(
                "/evidence_catalog",
                "qualification_evidence_catalog_unique",
                "qualification evidence IDs and paths must be unique without aliases",
            )
        )
    if (
        bundle.get("evidence_catalog_sha256")
        != hashlib.sha256(canonical_json_bytes(catalog)).hexdigest()
    ):
        issues.append(
            _issue(
                "/evidence_catalog_sha256",
                "qualification_evidence_catalog_hash",
                "evidence catalog hash does not bind the exact ordered catalog",
            )
        )
    catalog_by_id = {row.get("evidence_id"): row for row in catalog}
    all_test_ids: set[str] = set()
    all_execution_pass = True
    for index, check in enumerate(checks):
        pointer = f"/compatibility_checks/{index}"
        test_ids = set(check.get("test_ids") or ())
        if all_test_ids & test_ids:
            issues.append(
                _issue(
                    f"{pointer}/test_ids",
                    "qualification_test_id_unique",
                    "qualification test IDs must identify one exact executed check",
                )
            )
        all_test_ids.update(test_ids)
        execution = check.get("execution")
        if isinstance(execution, Mapping):
            issues.extend(
                _timestamp_order_issues(
                    (
                        (f"{pointer}/execution/started_at", execution.get("started_at")),
                        (f"{pointer}/execution/completed_at", execution.get("completed_at")),
                    )
                )
            )
            honest_pass = execution.get("status") == "pass" and execution.get("exit_code") == 0
            honest_fail = execution.get("status") == "fail" and execution.get("exit_code") != 0
            if not (honest_pass or honest_fail) or check.get("result") != execution.get("status"):
                issues.append(
                    _issue(
                        f"{pointer}/execution",
                        "qualification_execution_honesty",
                        "check result, process status and exit code disagree",
                    )
                )
        expected_result_hash = canonical_document_sha256(
            check, excluded_top_level_fields=("result_sha256",)
        )
        if check.get("result_sha256") != expected_result_hash:
            issues.append(
                _issue(
                    f"{pointer}/result_sha256",
                    "qualification_check_result_hash",
                    "check result hash does not bind its complete executed result",
                )
            )
        unknown_evidence = set(check.get("evidence_ids") or ()) - set(catalog_by_id)
        if unknown_evidence:
            issues.append(
                _issue(
                    f"{pointer}/evidence_ids",
                    "qualification_evidence_reference",
                    "check references evidence absent from the signed catalog",
                )
            )
        all_execution_pass = all_execution_pass and check.get("result") == "pass"
    slices = [row for row in bundle.get("vertical_slices") or () if isinstance(row, Mapping)]
    modes = [row.get("access_mode") for row in slices]
    if len(modes) != len(set(modes)) or set(modes) != {
        "mode_a_package_read",
        "mode_b_live_predict",
        "mode_b_live_refine",
    }:
        issues.append(
            _issue(
                "/vertical_slices",
                "qualification_vertical_slice_closed_set",
                "qualification must execute all three access-mode vertical slices exactly once",
            )
        )
    for index, row in enumerate(slices):
        execution = row.get("execution")
        if (
            not isinstance(execution, Mapping)
            or execution.get("status") != "pass"
            or execution.get("exit_code") != 0
        ):
            all_execution_pass = False
            issues.append(
                _issue(
                    f"/vertical_slices/{index}/execution",
                    "qualification_vertical_slice_pass",
                    "every production vertical slice must execute successfully",
                )
            )
        if (
            row.get("access_mode") in {"mode_b_live_predict", "mode_b_live_refine"}
            and row.get("observed_authority_state") == "certified"
            and not isinstance(row.get("certificate_payload_sha256"), str)
        ):
            issues.append(
                _issue(
                    f"/vertical_slices/{index}/certificate_payload_sha256",
                    "qualification_vertical_slice_certificate",
                    "certified Mode B slice requires its exact output certificate",
                )
            )
    installation = bundle.get("installation_verification")
    if (
        not isinstance(installation, Mapping)
        or installation.get("status") != "pass"
        or installation.get("exit_code") != 0
    ):
        all_execution_pass = False
        issues.append(
            _issue(
                "/installation_verification",
                "qualification_installation_pass",
                "qualification requires an executed successful install/verification workflow",
            )
        )
    if bundle.get("all_required_checks_passed") is not all_execution_pass:
        issues.append(
            _issue(
                "/all_required_checks_passed",
                "qualification_summary_honesty",
                "qualification summary does not equal all check, install and vertical-slice results",
            )
        )

    if evidence_root is not None:
        for index, row in enumerate(catalog):
            path, path_issues = _safe_release_file(evidence_root, row.get("relative_path"))
            issues.extend(
                _issue(f"/evidence_catalog/{index}", issue.validator, issue.message)
                for issue in path_issues
            )
            if path is None:
                continue
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != row.get("sha256") or len(raw) != row.get(
                "size_bytes"
            ):
                issues.append(
                    _issue(
                        f"/evidence_catalog/{index}",
                        "qualification_evidence_byte_binding",
                        "qualification evidence bytes differ from the signed hash/size catalog",
                    )
                )

    release_binding = bundle.get("release_binding")
    requirements_binding = bundle.get("requirements_binding")
    if isinstance(release_snapshot, Mapping) and isinstance(release_binding, Mapping):
        release_cap = release_snapshot.get("capability_snapshot")
        expected = {
            "release_id": release_snapshot.get("release_id"),
            "release_payload_sha256": release_snapshot.get("release_payload_sha256"),
            "capability_snapshot_id": (
                release_cap.get("record_id") if isinstance(release_cap, Mapping) else None
            ),
            "capability_snapshot_sha256": (
                release_cap.get("payload_sha256") if isinstance(release_cap, Mapping) else None
            ),
            "adopted_wire_schema_manifest_sha256": hashlib.sha256(
                canonical_json_bytes(release_snapshot.get("wire_schemas") or ())
            ).hexdigest(),
        }
        for field, value in expected.items():
            if release_binding.get(field) != value:
                issues.append(
                    _issue(
                        f"/release_binding/{field}",
                        "qualification_release_binding",
                        "qualification does not bind the exact release contract",
                    )
                )
        semantic = release_snapshot.get("semantic_invariant_profile")
        semantic_binding = bundle.get("semantic_profile_binding")
        if (
            isinstance(semantic, Mapping)
            and isinstance(semantic_binding, Mapping)
            and semantic_binding.get("profile_sha256") != semantic.get("profile_sha256")
        ):
            issues.append(
                _issue(
                    "/semantic_profile_binding/profile_sha256",
                    "qualification_semantic_profile_binding",
                    "qualification semantic profile differs from release",
                )
            )
    if isinstance(capability_snapshot, Mapping) and isinstance(release_binding, Mapping):
        if release_binding.get("capability_snapshot_id") != capability_snapshot.get(
            "snapshot_id"
        ) or release_binding.get("capability_snapshot_sha256") != capability_snapshot.get(
            "snapshot_sha256"
        ):
            issues.append(
                _issue(
                    "/release_binding/capability_snapshot_id",
                    "qualification_capability_binding",
                    "qualification does not bind exact capability snapshot",
                )
            )
    if isinstance(consumer_requirements, Mapping) and isinstance(requirements_binding, Mapping):
        if requirements_binding.get("requirements_id") != consumer_requirements.get(
            "requirements_id"
        ) or requirements_binding.get("requirements_sha256") != consumer_requirements.get(
            "requirements_sha256"
        ):
            issues.append(
                _issue(
                    "/requirements_binding",
                    "qualification_requirements_binding",
                    "qualification does not bind exact consumer requirements",
                )
            )
    profiles = {
        row.get("profile_id"): row
        for row in (completion_profiles or ())
        if isinstance(row, Mapping)
    }
    core_binding = bundle.get("core_completion_profile_binding")
    core = profiles.get("core_autonomous_runtime")
    if (
        isinstance(core, Mapping)
        and isinstance(core_binding, Mapping)
        and core_binding.get("policy_sha256") != core.get("policy_sha256")
    ):
        issues.append(
            _issue(
                "/core_completion_profile_binding/policy_sha256",
                "qualification_completion_profile_binding",
                "qualification does not bind exact core completion policy",
            )
        )
    return tuple(sorted(set(issues)))


def validate_maskfactory_adoption_receipt(
    receipt: Mapping[str, Any],
    *,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
    release_snapshot: Mapping[str, Any] | None = None,
    consumer_requirements: Mapping[str, Any] | None = None,
    capability_snapshot: Mapping[str, Any] | None = None,
    completion_profiles: Iterable[Mapping[str, Any]] | None = None,
    qualification_bundle: Mapping[str, Any] | None = None,
    qualification_evidence_root: Path | None = None,
    production_required: bool = False,
    at_time: Any = None,
) -> tuple[ValidationIssue, ...]:
    """Validate a closed adoption matrix with exact capability and artifact pins."""
    if production_required and at_time is None:
        at_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    issues: list[ValidationIssue] = list(validate_document(receipt, "maskfactory_adoption_receipt"))
    hash_issue = _declared_hash_issue(
        receipt,
        hash_field="adoption_payload_sha256",
        excluded=("adoption_payload_sha256", "signature"),
    )
    if hash_issue:
        issues.append(hash_issue)
    issues.extend(
        _ed25519_signature_issues(
            receipt,
            payload_hash_field="adoption_payload_sha256",
            trusted_signing_keys=trusted_signing_keys,
            required_role="consumer_adoption",
            decision_time=receipt.get("decided_at"),
        )
    )
    issues.extend(
        _timestamp_order_issues(
            (
                ("/decided_at", receipt.get("decided_at")),
                ("/valid_until", receipt.get("valid_until")),
            ),
            allow_equal=False,
        )
    )
    issues.extend(
        _journal_checkpoint_issues(
            receipt.get("journal_checkpoint"),
            pointer="/journal_checkpoint",
            use_time=at_time or receipt.get("decided_at"),
        )
    )
    use = _parse_timestamp(at_time)
    valid = _parse_timestamp(receipt.get("valid_until"))
    if use is not None and (valid is None or use >= valid):
        issues.append(
            _issue(
                "/valid_until",
                "adoption_expired",
                "adoption must be revalidated before use after valid_until",
            )
        )
    scope = receipt.get("adoption_scope")
    decision = receipt.get("decision")
    production_authorized = receipt.get("production_use_authorized")
    if receipt.get("fixture_only") is True:
        if not (
            receipt.get("evidence_context") == "conformance_fixture"
            and scope == "conformance_validation"
            and decision == "conformance_only"
            and production_authorized is False
            and not receipt.get("pinned_artifacts")
            and not receipt.get("accepted_capabilities")
        ):
            issues.append(
                _issue(
                    "/adoption_scope",
                    "fixture_evidence_firewall",
                    "conformance fixtures cannot establish adoption, production-use authority, active pins, or accepted capabilities",
                )
            )
    if scope == "production_authority":
        issues.extend(_production_signing_key_issues(receipt, trusted_signing_keys))
        if (
            receipt.get("fixture_only") is not False
            or receipt.get("evidence_context") != "runtime_evidence"
        ):
            issues.append(
                _issue(
                    "/evidence_context",
                    "production_evidence_firewall",
                    "production adoption requires non-fixture runtime qualification evidence",
                )
            )
        if decision in {"adopted", "partially_adopted"} and production_authorized is not True:
            issues.append(
                _issue(
                    "/production_use_authorized",
                    "production_adoption_authority",
                    "successful production adoption must explicitly authorize production use",
                )
            )
        if decision == "rejected" and production_authorized is not False:
            issues.append(
                _issue(
                    "/production_use_authorized",
                    "production_adoption_authority",
                    "rejected production adoption cannot authorize use",
                )
            )
        missing_evidence = [
            name
            for name, value in (
                ("release_snapshot", release_snapshot),
                ("capability_snapshot", capability_snapshot),
                ("consumer_requirements", consumer_requirements),
                ("completion_profiles", completion_profiles),
                ("qualification_bundle", qualification_bundle),
                ("qualification_evidence_root", qualification_evidence_root),
            )
            if value is None
        ]
        if missing_evidence:
            issues.append(
                _issue(
                    "/adoption_scope",
                    "production_adoption_evidence_required",
                    f"production adoption validation is missing exact evidence: {', '.join(missing_evidence)}",
                )
            )
        if isinstance(release_snapshot, Mapping):
            issues.extend(
                validate_maskfactory_release_snapshot(
                    release_snapshot,
                    completion_profiles=completion_profiles,
                    trusted_signing_keys=trusted_signing_keys,
                    at_time=at_time or receipt.get("decided_at"),
                )
            )
            if (
                release_snapshot.get("fixture_only") is not False
                or release_snapshot.get("release_status") != "published"
            ):
                issues.append(
                    _issue(
                        "/release_id",
                        "production_release_required",
                        "production adoption requires a non-fixture published release",
                    )
                )
        if isinstance(capability_snapshot, Mapping):
            issues.extend(
                validate_maskfactory_capability_snapshot(
                    capability_snapshot, at_time=at_time or receipt.get("decided_at")
                )
            )
            if (
                capability_snapshot.get("fixture_only") is not False
                or capability_snapshot.get("evidence_context") != "runtime_evidence"
            ):
                issues.append(
                    _issue(
                        "/capability_snapshot_id",
                        "production_capability_snapshot_required",
                        "production adoption requires a non-fixture runtime capability snapshot",
                    )
                )
        if isinstance(consumer_requirements, Mapping):
            issues.extend(
                validate_maskfactory_consumer_requirements(
                    consumer_requirements, trusted_signing_keys=trusted_signing_keys
                )
            )
            issues.extend(
                _production_signing_key_issues(consumer_requirements, trusted_signing_keys)
            )
        if isinstance(qualification_bundle, Mapping):
            issues.extend(
                validate_maskfactory_qualification_bundle(
                    qualification_bundle,
                    trusted_signing_keys=trusted_signing_keys,
                    evidence_root=qualification_evidence_root,
                    release_snapshot=release_snapshot,
                    capability_snapshot=capability_snapshot,
                    consumer_requirements=consumer_requirements,
                    completion_profiles=completion_profiles,
                )
            )
            if receipt.get("qualification_bundle_id") != qualification_bundle.get(
                "qualification_id"
            ) or receipt.get("qualification_bundle_sha256") != qualification_bundle.get(
                "qualification_payload_sha256"
            ):
                issues.append(
                    _issue(
                        "/qualification_bundle_sha256",
                        "production_qualification_binding",
                        "adoption does not bind the exact signed executed qualification bundle",
                    )
                )
    if production_required and not (
        scope == "production_authority"
        and decision in {"adopted", "partially_adopted"}
        and production_authorized is True
    ):
        issues.append(
            _issue(
                "/adoption_scope",
                "production_adoption_required",
                "this use site requires an active production-authority adoption, not conformance or rejection evidence",
            )
        )
    checks = receipt.get("compatibility_checks") or ()
    check_names = [row.get("check") for row in checks if isinstance(row, Mapping)]
    if (
        len(check_names) != len(set(check_names))
        or set(check_names) != ADOPTION_COMPATIBILITY_CHECKS
    ):
        issues.append(
            _issue(
                "/compatibility_checks",
                "adoption_check_matrix",
                "every required compatibility check must occur exactly once",
            )
        )
    check_results = {
        row.get("check"): row.get("result") for row in checks if isinstance(row, Mapping)
    }
    if decision in {"adopted", "partially_adopted"} and any(
        check_results.get(name) != "pass" for name in ADOPTION_COMPATIBILITY_CHECKS
    ):
        issues.append(
            _issue(
                "/compatibility_checks",
                "adoption_core_checks_pass",
                "adopted and partially adopted decisions require every core compatibility check to pass",
            )
        )
    if decision == "rejected" and "fail" not in set(check_results.values()):
        issues.append(
            _issue(
                "/compatibility_checks",
                "adoption_rejection_evidence",
                "rejected adoption requires at least one failed core check",
            )
        )
    if isinstance(qualification_bundle, Mapping):
        qualified_checks = {
            row.get("check"): row
            for row in qualification_bundle.get("compatibility_checks") or ()
            if isinstance(row, Mapping)
        }
        for index, row in enumerate(checks):
            if not isinstance(row, Mapping):
                continue
            qualified = qualified_checks.get(row.get("check"))
            if (
                not isinstance(qualified, Mapping)
                or row.get("result") != qualified.get("result")
                or row.get("evidence_sha256") != qualified.get("result_sha256")
            ):
                issues.append(
                    _issue(
                        f"/compatibility_checks/{index}",
                        "adoption_qualification_check_binding",
                        "adoption check must bind the exact executed qualification result",
                    )
                )
    trigger_rows = receipt.get("revalidation_triggers") or ()
    if (
        len(trigger_rows) != len(set(trigger_rows))
        or set(trigger_rows) != ADOPTION_REVALIDATION_TRIGGERS
    ):
        issues.append(
            _issue(
                "/revalidation_triggers",
                "adoption_revalidation_trigger_closed_set",
                "adoption must declare every authority, trust, contract, artifact, journal, revocation and validity recheck trigger exactly once",
            )
        )
    decisions = receipt.get("capability_decisions") or ()
    capability_ids = [row.get("capability_id") for row in decisions if isinstance(row, Mapping)]
    if len(capability_ids) != len(set(capability_ids)):
        issues.append(
            _issue(
                "/capability_decisions",
                "capability_decisions_unique",
                "each capability must have exactly one adoption decision",
            )
        )
    accepted = set(receipt.get("accepted_capabilities") or ())
    rejected = set(receipt.get("rejected_capabilities") or ())
    if accepted & rejected:
        issues.append(
            _issue(
                "/rejected_capabilities",
                "adoption_capability_sets_disjoint",
                "accepted and rejected capabilities overlap",
            )
        )
    decision_map = {row.get("capability_id"): row for row in decisions if isinstance(row, Mapping)}
    if accepted != {
        key for key, row in decision_map.items() if row.get("decision") == "accepted"
    } or rejected != {
        key for key, row in decision_map.items() if row.get("decision") == "rejected"
    }:
        issues.append(
            _issue(
                "/capability_decisions",
                "capability_decision_mapping",
                "accepted/rejected sets must exactly equal unique capability decisions",
            )
        )
    if isinstance(consumer_requirements, Mapping):
        if receipt.get("consumer_requirements_id") != consumer_requirements.get(
            "requirements_id"
        ) or receipt.get("consumer_requirements_sha256") != consumer_requirements.get(
            "requirements_sha256"
        ):
            issues.append(
                _issue(
                    "/consumer_requirements_id",
                    "adoption_requirements_binding",
                    "adoption does not bind exact consumer requirements",
                )
            )
        required_ids = {
            row.get("capability_id")
            for row in consumer_requirements.get("required_capabilities") or ()
            if isinstance(row, Mapping)
        }
        optional_ids = {
            row.get("capability_id")
            for row in consumer_requirements.get("optional_capabilities") or ()
            if isinstance(row, Mapping)
        }
        for capability_id in required_ids | optional_ids:
            expected_class = "required" if capability_id in required_ids else "optional"
            row = decision_map.get(capability_id)
            if not isinstance(row, Mapping) or row.get("requirement_class") != expected_class:
                issues.append(
                    _issue(
                        "/capability_decisions",
                        "required_capability_coverage",
                        "every required and optional capability must be decided exactly once with correct class",
                    )
                )
        required_accepted = required_ids.issubset(accepted)
        if receipt.get("required_capabilities_satisfied") is not required_accepted:
            issues.append(
                _issue(
                    "/required_capabilities_satisfied",
                    "required_capability_coverage",
                    "required_capabilities_satisfied does not match exact required decisions",
                )
            )
        if decision in {"adopted", "partially_adopted"} and not required_accepted:
            issues.append(
                _issue(
                    "/decision",
                    "required_capability_coverage",
                    "adoption cannot succeed while a required capability is rejected or missing",
                )
            )
    if isinstance(consumer_requirements, Mapping) and isinstance(capability_snapshot, Mapping):
        global_checks = (
            (
                "/required_access_modes",
                set(consumer_requirements.get("required_access_modes") or ()),
                set(capability_snapshot.get("access_modes") or ()),
            ),
            (
                "/required_labels",
                set(consumer_requirements.get("required_labels") or ()),
                set(capability_snapshot.get("labels") or ()),
            ),
            (
                "/required_artifact_kinds",
                set(consumer_requirements.get("required_artifact_kinds") or ()),
                set(capability_snapshot.get("artifact_kinds") or ()),
            ),
            (
                "/required_coordinate_spaces",
                set(consumer_requirements.get("required_coordinate_spaces") or ()),
                set(capability_snapshot.get("coordinate_spaces") or ()),
            ),
            (
                "/required_transform_operations",
                set(consumer_requirements.get("required_transform_operations") or ()),
                set(capability_snapshot.get("transform_operations") or ()),
            ),
        )
        for pointer, required_values, available_values in global_checks:
            if not required_values.issubset(available_values):
                issues.append(
                    _issue(
                        pointer,
                        "adoption_snapshot_global_coverage",
                        "capability snapshot does not cover the complete consumer requirement set",
                    )
                )
        limits = capability_snapshot.get("limits")
        if (
            isinstance(limits, Mapping)
            and isinstance(consumer_requirements.get("minimum_person_count"), int)
            and limits.get("max_person_count", 0) < consumer_requirements["minimum_person_count"]
        ):
            issues.append(
                _issue(
                    "/minimum_person_count",
                    "adoption_snapshot_global_coverage",
                    "capability snapshot person limit is below the consumer minimum",
                )
            )
        availability = capability_snapshot.get("availability")
        eligible_by_mode = {
            row.get("access_mode"): row
            for row in (
                availability.get("mode_eligibility") if isinstance(availability, Mapping) else ()
            )
            or ()
            if isinstance(row, Mapping) and row.get("eligible") is True
        }
        stacks = [
            row
            for row in capability_snapshot.get("provider_stacks") or ()
            if isinstance(row, Mapping)
        ]
        requirement_rows = {
            row.get("capability_id"): row
            for collection in (
                consumer_requirements.get("required_capabilities") or (),
                consumer_requirements.get("optional_capabilities") or (),
            )
            for row in collection
            if isinstance(row, Mapping)
        }
        snapshot_capability_ids = {
            capability_id for stack in stacks for capability_id in stack.get("capability_ids") or ()
        }
        decision_time = _parse_timestamp(receipt.get("decided_at"))
        for capability_id, row in decision_map.items():
            if not isinstance(capability_id, str):
                continue
            requirement = requirement_rows.get(capability_id)
            if row.get("requirement_class") == "producer_extra":
                if (
                    capability_id in requirement_rows
                    or capability_id not in snapshot_capability_ids
                ):
                    issues.append(
                        _issue(
                            "/capability_decisions",
                            "producer_extra_snapshot_binding",
                            "producer_extra decisions must name a real snapshot capability absent from consumer requirements",
                        )
                    )
                continue
            if row.get("decision") != "accepted" or not isinstance(requirement, Mapping):
                continue
            candidates: list[Mapping[str, Any]] = []
            for stack in stacks:
                qualification = stack.get("qualification_scope")
                route = stack.get("route_key")
                mode = requirement.get("access_mode")
                mode_eligibility = eligible_by_mode.get(mode)
                valid_until = (
                    _parse_timestamp(qualification.get("valid_until"))
                    if isinstance(qualification, Mapping)
                    else None
                )
                maximum_authority = (
                    (capability_snapshot.get("authority_crosswalk") or {})
                    .get(mode, {})
                    .get("maximum_authority_state")
                )
                minimum_authority = requirement.get("minimum_authority_state")
                authority_covered = (
                    maximum_authority in AUTHORITY_RANK
                    and minimum_authority in AUTHORITY_RANK
                    and AUTHORITY_RANK[maximum_authority] >= AUTHORITY_RANK[minimum_authority]
                )
                exact_certificate_covered = minimum_authority != "certified" or (
                    (capability_snapshot.get("authority_policy") or {}).get(
                        "certified_requires_exact_output_certificate"
                    )
                    is True
                    and bool(stack.get("certificate_ids"))
                    and isinstance(mode_eligibility, Mapping)
                    and bool(
                        set(stack.get("certificate_ids") or ())
                        & set(mode_eligibility.get("certificate_ids") or ())
                    )
                )
                if (
                    stack.get("lifecycle") == "promoted"
                    and capability_id in set(stack.get("capability_ids") or ())
                    and mode in set(stack.get("access_modes") or ())
                    and isinstance(route, Mapping)
                    and isinstance(mode_eligibility, Mapping)
                    and route.get("route_key_id") in set(mode_eligibility.get("route_ids") or ())
                    and set(requirement.get("labels") or ()).issubset(
                        set(stack.get("labels") or ())
                    )
                    and isinstance(qualification, Mapping)
                    and set(requirement.get("labels") or ()).issubset(
                        set(qualification.get("labels") or ())
                    )
                    and set(requirement.get("artifact_kinds") or ()).issubset(
                        set(qualification.get("artifact_kinds") or ())
                    )
                    and set(consumer_requirements.get("accepted_media_scopes") or ()).issubset(
                        set(stack.get("media_scopes") or ())
                    )
                    and qualification.get("max_person_count", 0)
                    >= consumer_requirements.get("minimum_person_count", 0)
                    and decision_time is not None
                    and valid_until is not None
                    and decision_time < valid_until
                    and authority_covered
                    and exact_certificate_covered
                ):
                    candidates.append(stack)
            candidate_evidence = {
                canonical_document_sha256(
                    {
                        "requirement": requirement,
                        "snapshot_id": capability_snapshot.get("snapshot_id"),
                        "snapshot_sha256": capability_snapshot.get("snapshot_sha256"),
                        "stack_id": stack.get("stack_id"),
                        "stack_sha256": stack.get("stack_sha256"),
                        "qualification_scope_sha256": (stack.get("qualification_scope") or {}).get(
                            "scope_sha256"
                        ),
                    }
                )
                for stack in candidates
            }
            if not candidates:
                issues.append(
                    _issue(
                        "/capability_decisions",
                        "accepted_capability_qualified_route",
                        f"accepted capability {capability_id!r} has no promoted, live, scope-qualified snapshot route",
                    )
                )
            elif row.get("evidence_sha256") not in candidate_evidence:
                issues.append(
                    _issue(
                        "/capability_decisions",
                        "accepted_capability_evidence_binding",
                        f"accepted capability {capability_id!r} evidence does not bind any exact qualified route",
                    )
                )
    if isinstance(release_snapshot, Mapping):
        for receipt_field, release_field in (
            ("release_id", "release_id"),
            ("release_payload_sha256", "release_payload_sha256"),
        ):
            if receipt.get(receipt_field) != release_snapshot.get(release_field):
                issues.append(
                    _issue(
                        f"/{receipt_field}",
                        "adoption_release_binding",
                        "adoption does not bind exact release",
                    )
                )
        release_cap = release_snapshot.get("capability_snapshot")
        if isinstance(release_cap, Mapping) and receipt.get(
            "capability_snapshot_sha256"
        ) != release_cap.get("payload_sha256"):
            issues.append(
                _issue(
                    "/capability_snapshot_sha256",
                    "adoption_release_binding",
                    "adoption capability snapshot hash differs from release",
                )
            )
        expected_pins: set[tuple[str, str]] = set()
        for row in release_snapshot.get("wire_schemas") or ():
            if isinstance(row, Mapping):
                expected_pins.add((f"wire_schema:{row.get('name')}", str(row.get("sha256"))))
        for index, row in enumerate(release_snapshot.get("artifacts") or ()):
            if isinstance(row, Mapping):
                expected_pins.add(
                    (
                        f"artifact:{row.get('kind')}:{row.get('relative_path')}",
                        str(row.get("sha256")),
                    )
                )
        for field in (
            "workflow_inventory",
            "node_inventory",
            "certificate_index",
            "evidence_index",
            "openapi",
        ):
            row = release_snapshot.get(field)
            if isinstance(row, Mapping):
                expected_pins.add((field, str(row.get("sha256"))))
        semantic = release_snapshot.get("semantic_invariant_profile")
        if isinstance(semantic, Mapping):
            expected_pins.add(
                ("semantic_invariant_profile_payload", str(semantic.get("profile_sha256")))
            )
            expected_pins.add(
                ("semantic_invariant_profile_document", str(semantic.get("document_sha256")))
            )
        capability_binding = release_snapshot.get("capability_snapshot")
        if isinstance(capability_binding, Mapping):
            expected_pins.add(
                ("capability_snapshot_payload", str(capability_binding.get("payload_sha256")))
            )
            expected_pins.add(
                ("capability_snapshot_document", str(capability_binding.get("document_sha256")))
            )
        canonical = release_snapshot.get("canonicalization_spec")
        if isinstance(canonical, Mapping):
            expected_pins.add(("canonicalization_spec", str(canonical.get("sha256"))))
            expected_pins.add(
                ("canonicalization_golden_vectors", str(canonical.get("golden_vectors_sha256")))
            )
        security = release_snapshot.get("artifact_security_policy")
        if isinstance(security, Mapping):
            expected_pins.add(
                ("allowed_root_manifest", str(security.get("allowed_root_manifest_sha256")))
            )
        for row in release_snapshot.get("completion_profiles") or ():
            if isinstance(row, Mapping):
                expected_pins.add(
                    (f"completion_profile:{row.get('profile_id')}", str(row.get("document_sha256")))
                )
        observed_pins = {
            (str(row.get("kind")), str(row.get("sha256")))
            for row in receipt.get("pinned_artifacts") or ()
            if isinstance(row, Mapping)
        }
        if decision in {"adopted", "partially_adopted"} and observed_pins != expected_pins:
            issues.append(
                _issue(
                    "/pinned_artifacts",
                    "adoption_exact_artifact_pins",
                    "successful adoption must pin every release-critical artifact exactly and no extras",
                )
            )
        trust = receipt.get("trust_binding")
        signing = release_snapshot.get("signing_trust")
        if isinstance(trust, Mapping) and isinstance(signing, Mapping):
            mapping = {
                "producer_key_set_id": "key_set_id",
                "producer_key_set_version": "key_set_version",
                "producer_key_set_sha256": "key_set_sha256",
                "producer_release_key_id": "release_signing_key_id",
                "producer_release_public_key_sha256": "release_signing_public_key_sha256",
            }
            for adoption_field, release_field in mapping.items():
                if trust.get(adoption_field) != signing.get(release_field):
                    issues.append(
                        _issue(
                            f"/trust_binding/{adoption_field}",
                            "adoption_producer_trust_binding",
                            "adoption trust pin differs from producer release",
                        )
                    )
    if isinstance(capability_snapshot, Mapping):
        if receipt.get("capability_snapshot_id") != capability_snapshot.get(
            "snapshot_id"
        ) or receipt.get("capability_snapshot_sha256") != capability_snapshot.get(
            "snapshot_sha256"
        ):
            issues.append(
                _issue(
                    "/capability_snapshot_id",
                    "adoption_capability_snapshot_binding",
                    "adoption does not bind exact capability snapshot",
                )
            )
    return tuple(sorted(set(issues)))


def _input_region_lineage_view(region: Mapping[str, Any]) -> dict[str, Any]:
    authority = region.get("authority_binding")
    authority = authority if isinstance(authority, Mapping) else {}
    return {
        "region_id": region.get("region_id"),
        "artifact_identity_sha256": region.get("artifact_identity_sha256"),
        "encoded_sha256": region.get("encoded_sha256"),
        "decoded_mask_sha256": region.get("decoded_mask_sha256"),
        "source_decoded_pixel_sha256": region.get("source_decoded_pixel_sha256"),
        "artifact_type": region.get("mask_type"),
        "owner_identity_sha256": _owner_identity_sha256(region.get("owner")),
        "coordinate_space": region.get("coordinate_space"),
        "width": region.get("width"),
        "height": region.get("height"),
        "transform_chain_sha256": region.get("transform_chain_sha256"),
        "transform_step_sequence": region.get("transform_step_sequence"),
        "required_minimum_authority_state": region.get("required_minimum_authority_state"),
        "authority_state": authority.get("authority_state"),
        "issuer_kind": authority.get("issuer_kind"),
        "certificate_kind": authority.get("certificate_kind"),
        "certificate_id": authority.get("certificate_id"),
        "certificate_sha256": authority.get("certificate_sha256"),
        "certificate_scope_sha256": authority.get("certificate_scope_sha256"),
        "certificate_status": authority.get("certificate_status"),
        "certificate_exact_scope_match": authority.get("certificate_exact_scope_match"),
        "revocation_checked_at": authority.get("revocation_checked_at"),
        "revocation_checkpoint_sha256": authority.get("revocation_checkpoint_sha256"),
    }


def _source_receipt_view(source: Mapping[str, Any]) -> dict[str, Any]:
    decoder = source.get("decoder")
    decoder = decoder if isinstance(decoder, Mapping) else {}
    transform = source.get("color_transform")
    transform = transform if isinstance(transform, Mapping) else {}
    extraction = source.get("frame_extraction")
    return {
        "artifact_id": source.get("artifact_id"),
        "encoded_sha256": source.get("encoded_sha256"),
        "decoded_pixel_sha256": source.get("decoded_pixel_sha256"),
        "decoder_id": decoder.get("decoder_id"),
        "decoder_version": decoder.get("version"),
        "decoder_binary_sha256": decoder.get("binary_sha256"),
        "exif_orientation": source.get("exif_orientation"),
        "orientation_applied": source.get("orientation_applied"),
        "width": source.get("width"),
        "height": source.get("height"),
        "channel_layout": source.get("channel_layout"),
        "alpha_mode": source.get("alpha_mode"),
        "bit_depth": source.get("bit_depth"),
        "dtype": source.get("dtype"),
        "color_space": source.get("color_space"),
        "icc_profile_sha256": source.get("icc_profile_sha256"),
        "color_transform_sha256": transform.get("transform_sha256"),
        "frame_extraction_sha256": (
            None if extraction is None else canonical_document_sha256(extraction)
        ),
        "coordinate_space": source.get("coordinate_space"),
    }


def _exact_mapping_issues(
    expected: Mapping[str, Any], observed: Any, *, pointer: str, validator: str
) -> list[ValidationIssue]:
    if not isinstance(observed, Mapping):
        return []
    issues: list[ValidationIssue] = []
    for field, value in expected.items():
        if observed.get(field) != value:
            issues.append(
                _issue(
                    f"{pointer}/{field}",
                    validator,
                    "value does not match the exact upstream binding",
                )
            )
    return issues


def validate_bridge_exchange(
    request: Mapping[str, Any],
    receipt: Mapping[str, Any],
    certificate: Mapping[str, Any] | None = None,
    *,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
    production_required: bool = True,
    release_snapshot: Mapping[str, Any] | None = None,
    capability_snapshot: Mapping[str, Any] | None = None,
    completion_profiles: Iterable[Mapping[str, Any]] | None = None,
    at_time: Any = None,
) -> tuple[ValidationIssue, ...]:
    """Validate the full request -> receipt -> optional exact certificate transaction."""
    if production_required and at_time is None:
        at_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    issues: list[ValidationIssue] = [
        *validate_mask_acquisition_request(request, trusted_signing_keys=trusted_signing_keys),
        *validate_mask_acquisition_receipt(receipt, trusted_signing_keys=trusted_signing_keys),
    ]
    direct_fields = (
        "request_id",
        "request_payload_sha256",
        "project_id",
        "run_id",
        "job_id",
        "pass_id",
        "attempt_id",
        "attempt_number",
        "idempotency_key",
        "access_mode",
    )
    for field in direct_fields:
        if request.get(field) != receipt.get(field):
            issues.append(
                _issue(
                    f"/{field}",
                    "request_receipt_binding",
                    "receipt does not bind the exact request value",
                )
            )
    hypothesis = request.get("hypothesis")
    if isinstance(hypothesis, Mapping) and receipt.get("hypothesis_id") != hypothesis.get(
        "hypothesis_id"
    ):
        issues.append(
            _issue(
                "/hypothesis_id",
                "request_receipt_hypothesis",
                "receipt hypothesis differs from request",
            )
        )
    if receipt.get("media_scope") != request.get("media_scope"):
        issues.append(
            _issue(
                "/media_scope",
                "request_receipt_media_scope",
                "receipt must bind the exact still/frame/span identity",
            )
        )

    request_source = request.get("source")
    receipt_source = receipt.get("source_binding")
    if isinstance(request_source, Mapping):
        issues.extend(
            _exact_mapping_issues(
                _source_receipt_view(request_source),
                receipt_source,
                pointer="/source_binding",
                validator="request_receipt_source_binding",
            )
        )
    request_subject = request.get("subject")
    receipt_subject = receipt.get("subject_binding")
    if isinstance(request_subject, Mapping):
        expected_subject = {
            field: request_subject.get(field)
            for field in (
                "scene_id",
                "shot_id",
                "take_id",
                "character_id",
                "character_revision",
                "scene_instance_id",
                "canonical_person_id",
                "person_index",
                "provider_person_index",
            )
        }
        assignment = request_subject.get("assignment_evidence")
        if isinstance(assignment, Mapping):
            expected_subject["assignment_evidence_sha256"] = assignment.get("mapping_sha256")
        issues.extend(
            _exact_mapping_issues(
                expected_subject,
                receipt_subject,
                pointer="/subject_binding",
                validator="request_receipt_subject_binding",
            )
        )
    compatibility = request.get("compatibility")
    release = receipt.get("release_binding")
    if isinstance(compatibility, Mapping):
        issues.extend(
            _exact_mapping_issues(
                {
                    field: compatibility.get(field)
                    for field in (
                        "release_id",
                        "capability_snapshot_id",
                        "capability_snapshot_sha256",
                        "bridge_contract",
                    )
                },
                release,
                pointer="/release_binding",
                validator="request_receipt_release_binding",
            )
        )
    chain = request.get("transform_chain")
    transform = receipt.get("transform_validation")
    if isinstance(chain, Mapping) and isinstance(transform, Mapping):
        expected_transform = {
            "transform_chain_id": chain.get("chain_id"),
            "transform_chain_sha256": chain.get("chain_sha256"),
            "source_coordinate_space": (chain.get("source") or {}).get("coordinate_space"),
            "source_width": (chain.get("source") or {}).get("width"),
            "source_height": (chain.get("source") or {}).get("height"),
            "output_coordinate_space": (chain.get("output") or {}).get("coordinate_space"),
            "output_width": (chain.get("output") or {}).get("width"),
            "output_height": (chain.get("output") or {}).get("height"),
            "executed_step_sha256s": [
                step.get("step_sha256")
                for step in chain.get("steps") or ()
                if isinstance(step, Mapping)
            ],
        }
        issues.extend(
            _exact_mapping_issues(
                expected_transform,
                transform,
                pointer="/transform_validation",
                validator="request_receipt_transform_binding",
            )
        )
        policy = chain.get("roundtrip_policy")
        if (
            isinstance(policy, Mapping)
            and isinstance(transform.get("maximum_roundtrip_error_px"), (int, float))
            and transform["maximum_roundtrip_error_px"] > policy.get("maximum_error_px", -1)
        ):
            issues.append(
                _issue(
                    "/transform_validation/maximum_roundtrip_error_px",
                    "transform_roundtrip_tolerance",
                    "observed transform roundtrip error exceeds request policy",
                )
            )

    lineage = receipt.get("lineage")
    if isinstance(lineage, Mapping):
        for key, regions in (
            ("input_target_regions", request.get("target_regions") or ()),
            ("input_protected_regions", request.get("protected_regions") or ()),
        ):
            expected_rows = {
                _input_region_lineage_view(row)["region_id"]: _input_region_lineage_view(row)
                for row in regions
                if isinstance(row, Mapping)
            }
            observed_rows = {
                row.get("region_id"): row
                for row in lineage.get(key) or ()
                if isinstance(row, Mapping)
            }
            if set(expected_rows) != set(observed_rows):
                issues.append(
                    _issue(
                        f"/lineage/{key}",
                        "request_receipt_input_lineage",
                        "receipt input lineage region set differs from request",
                    )
                )
            else:
                for region_id, expected in expected_rows.items():
                    if observed_rows[region_id] != expected:
                        issues.append(
                            _issue(
                                f"/lineage/{key}",
                                "request_receipt_input_lineage",
                                "receipt input lineage does not preserve every exact input identity/owner/transform/authority field",
                            )
                        )

    intents = {
        row.get("intent_id"): row
        for row in request.get("mask_intents") or ()
        if isinstance(row, Mapping)
    }
    outputs_by_intent: dict[Any, list[Mapping[str, Any]]] = {}
    for artifact in receipt.get("artifacts") or ():
        if isinstance(artifact, Mapping):
            outputs_by_intent.setdefault(artifact.get("intent_id"), []).append(artifact)
    if set(outputs_by_intent) != set(intents) or any(
        len(rows) != 1 for rows in outputs_by_intent.values()
    ):
        issues.append(
            _issue(
                "/artifacts",
                "exactly_one_output_per_intent",
                "successful receipt must return exactly one output artifact for every requested intent and no extras",
            )
        )
    else:
        for intent_id, intent in intents.items():
            artifact = outputs_by_intent[intent_id][0]
            expected = {
                "label": intent.get("label"),
                "artifact_kind": intent.get("artifact_kind"),
                "coordinate_space": intent.get("target_coordinate_space"),
            }
            for field, value in expected.items():
                if artifact.get(field) != value:
                    issues.append(
                        _issue(
                            f"/artifacts/{field}",
                            "intent_output_binding",
                            "output artifact semantics do not match its intent",
                        )
                    )
            if isinstance(request_subject, Mapping):
                owner = artifact.get("owner")
                if not isinstance(owner, Mapping) or any(
                    owner.get(field) != request_subject.get(field)
                    for field in ("scene_instance_id", "canonical_person_id", "person_index")
                ):
                    issues.append(
                        _issue(
                            "/artifacts/owner",
                            "intent_output_owner",
                            "output artifact owner must exactly match canonical subject",
                        )
                    )
    payload = request.get("mode_payload")
    if request.get("access_mode") == "mode_a_package_read" and isinstance(payload, Mapping):
        selector_map = {
            row.get("artifact_identity_sha256"): row
            for row in payload.get("artifact_selectors") or ()
            if isinstance(row, Mapping)
        }
        output_map = {
            row.get("artifact_identity_sha256"): row
            for row in receipt.get("artifacts") or ()
            if isinstance(row, Mapping)
        }
        if set(selector_map) != set(output_map):
            issues.append(
                _issue(
                    "/artifacts",
                    "mode_a_exact_artifact_read",
                    "Mode A output identities must exactly equal selected package artifact identities",
                )
            )
        package = payload.get("package_selector")
        if isinstance(package, Mapping) and isinstance(lineage, Mapping):
            for field in (
                "package_id",
                "package_revision",
                "package_manifest_sha256",
                "package_certificate_kind",
                "package_certificate_id",
                "package_certificate_sha256",
                "package_certificate_status",
                "package_certificate_exact_scope_match",
            ):
                if package.get(field) != lineage.get(field):
                    issues.append(
                        _issue(
                            f"/lineage/{field}",
                            "mode_a_package_lineage",
                            "Mode A receipt does not bind exact requested package lineage",
                        )
                    )

    envelope = request.get("resource_envelope")
    execution = receipt.get("execution_observation")
    if isinstance(envelope, Mapping) and isinstance(execution, Mapping):
        resources = execution.get("resources")
        checks = (("runtime_ms", "maximum_runtime_ms"), ("queue_ms", "maximum_queue_ms"))
        for observed_field, max_field in checks:
            if (
                isinstance(execution.get(observed_field), int)
                and isinstance(envelope.get(max_field), int)
                and execution[observed_field] > envelope[max_field]
            ):
                issues.append(
                    _issue(
                        f"/execution_observation/{observed_field}",
                        "resource_envelope",
                        f"execution exceeds {max_field}",
                    )
                )
        if isinstance(resources, Mapping):
            for observed_field, max_field in (
                ("peak_vram_mb", "maximum_vram_mb"),
                ("peak_ram_mb", "maximum_ram_mb"),
                ("output_bytes", "maximum_output_bytes"),
            ):
                if (
                    isinstance(resources.get(observed_field), int)
                    and isinstance(envelope.get(max_field), int)
                    and resources[observed_field] > envelope[max_field]
                ):
                    issues.append(
                        _issue(
                            f"/execution_observation/resources/{observed_field}",
                            "resource_envelope",
                            f"execution exceeds {max_field}",
                        )
                    )
        completed, deadline = _parse_timestamp(receipt.get("completed_at")), _parse_timestamp(
            request.get("deadline_at")
        )
        deadline_met = completed is not None and deadline is not None and completed <= deadline
        if execution.get("deadline_met") is not deadline_met:
            issues.append(
                _issue(
                    "/execution_observation/deadline_met",
                    "deadline_observation",
                    "deadline_met does not agree with request deadline and completion time",
                )
            )

    authority = receipt.get("authority")
    certified = isinstance(authority, Mapping) and authority.get("authority_state") == "certified"
    if production_required and not certified:
        issues.append(
            _issue(
                "/authority/authority_state",
                "production_certificate_required",
                "production consumption requires certified receipt authority and its exact operational certificate",
            )
        )
    if certified and certificate is None:
        issues.append(
            _issue(
                "/authority/certificate_id",
                "certified_receipt_requires_certificate",
                "certified receipt is unusable without its exact operational certificate",
            )
        )
    if certificate is not None:
        issues.extend(
            validate_operational_autonomy_certificate(
                certificate,
                trusted_signing_keys=trusted_signing_keys,
                at_time=at_time if production_required else None,
                production_required=production_required,
            )
        )
        if not certified:
            issues.append(
                _issue(
                    "/authority/authority_state",
                    "certificate_authority_binding",
                    "attached operational certificate requires certified receipt authority",
                )
            )
        if isinstance(authority, Mapping):
            if authority.get("certificate_id") != certificate.get(
                "certificate_id"
            ) or authority.get("certificate_sha256") != certificate.get(
                "certificate_payload_sha256"
            ):
                issues.append(
                    _issue(
                        "/authority",
                        "receipt_certificate_binding",
                        "receipt does not bind exact certificate identity and payload hash",
                    )
                )
            revocation_time = _parse_timestamp(authority.get("revocation_checked_at"))
            completed = _parse_timestamp(receipt.get("completed_at"))
            if revocation_time is None or completed is None or revocation_time < completed:
                issues.append(
                    _issue(
                        "/authority/revocation_checked_at",
                        "revocation_fresh_at_decision",
                        "revocation evidence must be at or after receipt decision time",
                    )
                )
            use_time = _parse_timestamp(at_time)
            if production_required and (
                revocation_time is None
                or use_time is None
                or revocation_time > use_time
                or (use_time - revocation_time).total_seconds() > 300
            ):
                issues.append(
                    _issue(
                        "/authority/revocation_checked_at",
                        "revocation_fresh_at_use",
                        "production use requires revocation evidence no more than 300 seconds old at the exact use time",
                    )
                )
        for field in ("media_scope",):
            if certificate.get(field) != request.get(field):
                issues.append(
                    _issue(
                        f"/{field}",
                        "certificate_exchange_binding",
                        "certificate does not bind exact exchange media scope",
                    )
                )
        cert_source = certificate.get("source_binding")
        if isinstance(receipt_source, Mapping) and cert_source != {
            key: value for key, value in receipt_source.items() if key != "coordinate_space"
        }:
            issues.append(
                _issue(
                    "/source_binding",
                    "receipt_certificate_source_binding",
                    "certificate source identity differs from receipt source identity",
                )
            )
        cert_subject = certificate.get("subject_binding")
        if cert_subject != receipt_subject:
            issues.append(
                _issue(
                    "/subject_binding",
                    "receipt_certificate_subject_binding",
                    "certificate subject differs from receipt subject",
                )
            )
        cert_release = certificate.get("release_binding")
        if isinstance(release, Mapping) and isinstance(cert_release, Mapping):
            for field in (
                "release_id",
                "release_payload_sha256",
                "capability_snapshot_id",
                "capability_snapshot_sha256",
                "bridge_contract",
            ):
                if cert_release.get(field) != release.get(field):
                    issues.append(
                        _issue(
                            f"/release_binding/{field}",
                            "receipt_certificate_release_binding",
                            "certificate release binding differs from receipt",
                        )
                    )
        cert_coordinate = certificate.get("coordinate_binding")
        if isinstance(transform, Mapping) and isinstance(cert_coordinate, Mapping):
            mapping = {
                "transform_chain_id": "transform_chain_id",
                "transform_chain_sha256": "transform_chain_sha256",
                "source_coordinate_space": "source_coordinate_space",
                "source_width": "source_width",
                "source_height": "source_height",
                "output_coordinate_space": "output_coordinate_space",
                "output_width": "output_width",
                "output_height": "output_height",
                "executed_step_sha256s": "executed_step_sha256s",
                "roundtrip_checked": "roundtrip_checked",
                "roundtrip_passed": "roundtrip_passed",
                "maximum_roundtrip_error_px": "maximum_roundtrip_error_px",
            }
            for receipt_field, cert_field in mapping.items():
                if transform.get(receipt_field) != cert_coordinate.get(cert_field):
                    issues.append(
                        _issue(
                            f"/coordinate_binding/{cert_field}",
                            "receipt_certificate_transform_binding",
                            "certificate transform evidence differs from receipt",
                        )
                    )
        receipt_outputs = {
            row.get("artifact_identity_sha256"): row
            for row in receipt.get("artifacts") or ()
            if isinstance(row, Mapping)
        }
        cert_outputs = {
            row.get("artifact_identity_sha256"): row
            for row in certificate.get("bound_artifacts") or ()
            if isinstance(row, Mapping)
        }
        if set(receipt_outputs) != set(cert_outputs):
            issues.append(
                _issue(
                    "/bound_artifacts",
                    "receipt_certificate_output_binding",
                    "certificate bound outputs differ from receipt artifact identities",
                )
            )
        else:
            for identity in receipt_outputs:
                receipt_artifact = receipt_outputs[identity]
                cert_artifact = cert_outputs[identity]
                normalized_cert = dict(cert_artifact)
                normalized_cert["owner"] = {
                    field: normalized_cert.pop(field)
                    for field in (
                        "owner_kind",
                        "entity_id",
                        "scene_instance_id",
                        "canonical_person_id",
                        "person_index",
                    )
                }
                if any(
                    normalized_cert.get(field) != receipt_artifact.get(field)
                    for field in receipt_artifact
                    if field not in {"relative_path", "size_bytes"}
                ):
                    issues.append(
                        _issue(
                            "/bound_artifacts",
                            "receipt_certificate_output_binding",
                            "certificate output metadata differs from receipt",
                        )
                    )
        accepted = request.get("accepted_authority")
        output_scope = certificate.get("certified_output_scope")
        if (
            isinstance(accepted, Mapping)
            and isinstance(output_scope, Mapping)
            and accepted.get("required_certificate_scope_sha256")
            != output_scope.get("scope_sha256")
        ):
            issues.append(
                _issue(
                    "/certified_output_scope/scope_sha256",
                    "request_certificate_scope_binding",
                    "certificate scope differs from request exact scope",
                )
            )
    if production_required:
        issues.extend(_production_signing_key_issues(request, trusted_signing_keys))
        issues.extend(_production_signing_key_issues(receipt, trusted_signing_keys))
        if not isinstance(release_snapshot, Mapping) or not isinstance(
            capability_snapshot, Mapping
        ):
            issues.append(
                _issue(
                    "/release_binding",
                    "production_release_evidence_required",
                    "production exchange requires exact non-fixture release and capability documents",
                )
            )
        else:
            issues.extend(
                validate_maskfactory_release_snapshot(
                    release_snapshot,
                    completion_profiles=completion_profiles,
                    trusted_signing_keys=trusted_signing_keys,
                    at_time=at_time,
                )
            )
            issues.extend(
                validate_maskfactory_capability_snapshot(capability_snapshot, at_time=at_time)
            )
            if (
                release_snapshot.get("fixture_only") is not False
                or release_snapshot.get("release_status") != "published"
            ):
                issues.append(
                    _issue(
                        "/release_binding",
                        "production_release_evidence_required",
                        "production exchange cannot use a fixture, superseded or revoked release",
                    )
                )
            if (
                capability_snapshot.get("fixture_only") is not False
                or capability_snapshot.get("evidence_context") != "runtime_evidence"
            ):
                issues.append(
                    _issue(
                        "/release_binding",
                        "production_capability_evidence_required",
                        "production exchange cannot use fixture capability evidence",
                    )
                )
            release_binding = receipt.get("release_binding")
            if isinstance(release_binding, Mapping):
                if release_binding.get("release_id") != release_snapshot.get(
                    "release_id"
                ) or release_binding.get("release_payload_sha256") != release_snapshot.get(
                    "release_payload_sha256"
                ):
                    issues.append(
                        _issue(
                            "/release_binding",
                            "production_release_binding",
                            "receipt does not bind the exact supplied production release",
                        )
                    )
                if release_binding.get("capability_snapshot_id") != capability_snapshot.get(
                    "snapshot_id"
                ) or release_binding.get("capability_snapshot_sha256") != capability_snapshot.get(
                    "snapshot_sha256"
                ):
                    issues.append(
                        _issue(
                            "/release_binding",
                            "production_capability_binding",
                            "receipt does not bind the exact supplied production capability snapshot",
                        )
                    )
            if capability_snapshot.get("release_id") != release_snapshot.get("release_id"):
                issues.append(
                    _issue(
                        "/release_binding",
                        "production_capability_binding",
                        "capability snapshot is not release-bound to the supplied production release",
                    )
                )
    return tuple(sorted(set(issues)))


def validate_operational_autonomy_certificate(
    certificate: Mapping[str, Any],
    *,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
    at_time: Any = None,
    production_required: bool = False,
) -> tuple[ValidationIssue, ...]:
    """Validate an exact-output operational certificate without creating truth-gold claims."""
    if production_required and at_time is None:
        at_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    issues: list[ValidationIssue] = list(
        validate_document(certificate, "operational_autonomy_certificate")
    )
    hash_issue = _declared_hash_issue(
        certificate,
        hash_field="certificate_payload_sha256",
        excluded=("certificate_payload_sha256", "signature"),
    )
    if hash_issue:
        issues.append(hash_issue)
    issues.extend(
        _ed25519_signature_issues(
            certificate,
            payload_hash_field="certificate_payload_sha256",
            trusted_signing_keys=trusted_signing_keys,
            required_role="producer_authority",
            decision_time=certificate.get("issued_at"),
        )
    )
    issues.extend(
        _timestamp_order_issues(
            (
                ("/issued_at", certificate.get("issued_at")),
                ("/expires_at", certificate.get("expires_at")),
            ),
            allow_equal=False,
        )
    )
    issued = _parse_timestamp(certificate.get("issued_at"))
    expires = _parse_timestamp(certificate.get("expires_at"))
    use_time = _parse_timestamp(at_time)
    if use_time is not None:
        if certificate.get("status") == "active" and (
            issued is None or expires is None or not (issued <= use_time < expires)
        ):
            issues.append(
                _issue(
                    "/status",
                    "certificate_use_time",
                    "active certificate is future-issued or expired at the requested use time",
                )
            )
        if certificate.get("status") != "active":
            issues.append(
                _issue(
                    "/status", "certificate_use_time", "non-active certificate cannot authorize use"
                )
            )
    if (
        certificate.get("fixture_only") is True
        and certificate.get("evidence_context") != "conformance_fixture"
    ):
        issues.append(
            _issue(
                "/evidence_context",
                "fixture_evidence_firewall",
                "fixture-only certificate must be conformance evidence",
            )
        )
    if (
        certificate.get("fixture_only") is False
        and certificate.get("evidence_context") != "runtime_evidence"
    ):
        issues.append(
            _issue(
                "/evidence_context",
                "production_evidence_firewall",
                "production certificate requires runtime evidence",
            )
        )
    if (at_time is not None or production_required) and (
        certificate.get("fixture_only") is not False
        or certificate.get("evidence_context") != "runtime_evidence"
    ):
        issues.append(
            _issue(
                "/fixture_only",
                "fixture_certificate_use_forbidden",
                "conformance fixtures may test contracts but can never authorize operational use",
            )
        )
    if at_time is not None or production_required:
        issues.extend(_production_signing_key_issues(certificate, trusted_signing_keys))
    issues.extend(_media_scope_issues(certificate.get("media_scope")))

    qa = certificate.get("qa_evidence")
    if isinstance(qa, Mapping):
        gates = qa.get("gate_results") or ()
        gate_ids = [row.get("gate_id") for row in gates if isinstance(row, Mapping)]
        if len(gate_ids) != len(set(gate_ids)) or set(gate_ids) != OPERATIONAL_QA_GATES:
            issues.append(
                _issue(
                    "/qa_evidence/gate_results",
                    "operational_qa_gate_vector",
                    "certificate must contain every required QA gate exactly once",
                )
            )
        if any(not isinstance(row, Mapping) or row.get("status") != "pass" for row in gates):
            issues.append(
                _issue(
                    "/qa_evidence/gate_results",
                    "operational_qa_gate_pass",
                    "every certificate QA gate must pass",
                )
            )
        if qa.get("critic_independent_from_generator") is not True:
            issues.append(
                _issue(
                    "/qa_evidence/critic_independent_from_generator",
                    "critic_independence",
                    "operational certificate requires an independent critic",
                )
            )
        critic = qa.get("critic_binding")
        generator = certificate.get("execution_binding")
        if not isinstance(critic, Mapping) or not isinstance(generator, Mapping):
            issues.append(
                _issue(
                    "/qa_evidence/critic_binding",
                    "critic_independence",
                    "operational certificate requires exact generator and qualified critic bindings",
                )
            )
        else:
            generator_model_hashes = {
                row.get("sha256")
                for row in generator.get("model_artifacts") or ()
                if isinstance(row, Mapping)
            }
            critic_model_hashes = {
                row.get("sha256")
                for row in critic.get("model_artifacts") or ()
                if isinstance(row, Mapping)
            }
            separated = (
                critic.get("critic_role") == "independent_quality_critic"
                and critic.get("qualification_status") == "active"
                and critic.get("critic_stack_id") != generator.get("provider_stack_id")
                and critic.get("critic_stack_sha256") != generator.get("provider_stack_sha256")
                and critic.get("workflow_sha256") != generator.get("workflow_sha256")
                and critic.get("execution_fingerprint_sha256")
                != generator.get("execution_fingerprint_sha256")
                and not (critic_model_hashes & generator_model_hashes)
            )
            qualified_until = _parse_timestamp(critic.get("qualified_until"))
            if issued is None or qualified_until is None or issued >= qualified_until:
                separated = False
            critic_gate_rows = {
                row.get("gate_id"): row for row in gates if isinstance(row, Mapping)
            }
            for gate_id in ("critic_quality", "critic_independence"):
                row = critic_gate_rows.get(gate_id)
                if (
                    not isinstance(row, Mapping)
                    or row.get("executor_id") != critic.get("critic_stack_id")
                    or row.get("executor_sha256") != critic.get("critic_stack_sha256")
                ):
                    separated = False
            if not separated:
                issues.append(
                    _issue(
                        "/qa_evidence/critic_binding",
                        "critic_identity_separation",
                        "critic must be actively qualified and differ from the generator by stack, model, workflow and execution identity; critic gates must bind that exact critic",
                    )
                )

    artifacts = certificate.get("bound_artifacts") or ()
    identities: set[str] = set()
    labels: set[str] = set()
    kinds: set[str] = set()
    owners: set[str] = set()
    spaces: set[str] = set()
    source = certificate.get("source_binding")
    subject = certificate.get("subject_binding")
    coordinate = certificate.get("coordinate_binding")
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, Mapping):
            continue
        pointer = f"/bound_artifacts/{index}"
        issues.extend(_artifact_semantic_issues(artifact, pointer=pointer))
        identity = artifact.get("artifact_identity_sha256")
        if isinstance(identity, str):
            if identity in identities:
                issues.append(
                    _issue(
                        f"{pointer}/artifact_identity_sha256",
                        "unique_artifact_identity",
                        "certificate output artifact identities must be unique",
                    )
                )
            identities.add(identity)
        if isinstance(artifact.get("label"), str):
            labels.add(artifact["label"])
        if isinstance(artifact.get("artifact_kind"), str):
            kinds.add(artifact["artifact_kind"])
        if isinstance(artifact.get("scene_instance_id"), str):
            owners.add(artifact["scene_instance_id"])
        if isinstance(artifact.get("coordinate_space"), str):
            spaces.add(artifact["coordinate_space"])
        if isinstance(source, Mapping) and artifact.get(
            "source_decoded_pixel_sha256"
        ) != source.get("decoded_pixel_sha256"):
            issues.append(
                _issue(
                    f"{pointer}/source_decoded_pixel_sha256",
                    "certificate_source_binding",
                    "certificate artifact does not bind exact decoded source pixels",
                )
            )
        if isinstance(subject, Mapping) and any(
            artifact.get(field) != subject.get(field)
            for field in ("scene_instance_id", "canonical_person_id", "person_index")
        ):
            issues.append(
                _issue(
                    pointer,
                    "certificate_subject_binding",
                    "certificate artifact owner does not exactly match canonical subject",
                )
            )
        if isinstance(coordinate, Mapping) and artifact.get(
            "transform_chain_sha256"
        ) != coordinate.get("transform_chain_sha256"):
            issues.append(
                _issue(
                    f"{pointer}/transform_chain_sha256",
                    "certificate_transform_binding",
                    "certificate artifact does not bind executed transform",
                )
            )

    output_scope = certificate.get("certified_output_scope")
    qualified = certificate.get("qualified_route_scope")
    if isinstance(output_scope, Mapping):
        exact_sets = {
            "artifact_identity_sha256s": identities,
            "labels": labels,
            "artifact_kinds": kinds,
            "owners": owners,
            "coordinate_spaces": spaces,
        }
        for field, expected in exact_sets.items():
            if set(output_scope.get(field) or ()) != expected:
                issues.append(
                    _issue(
                        f"/certified_output_scope/{field}",
                        "certified_scope_exact_outputs",
                        f"{field} must exactly equal bound outputs",
                    )
                )
        if "train_only" in set(output_scope.get("permitted_uses") or ()):
            issues.append(
                _issue(
                    "/certified_output_scope/permitted_uses",
                    "operational_truth_firewall",
                    "operational certificates cannot authorize training-gold use",
                )
            )
        if isinstance(qualified, Mapping):
            if not labels.issubset(set(qualified.get("labels") or ())) or not kinds.issubset(
                set(qualified.get("artifact_kinds") or ())
            ):
                issues.append(
                    _issue(
                        "/certified_output_scope",
                        "output_scope_within_qualified_route",
                        "certified outputs exceed the qualified route scope",
                    )
                )
            if (
                isinstance(subject, Mapping)
                and isinstance(qualified.get("max_person_count"), int)
                and subject.get("person_index", 0) >= qualified["max_person_count"]
            ):
                issues.append(
                    _issue(
                        "/qualified_route_scope/max_person_count",
                        "qualified_person_scope",
                        "actual canonical subject is outside route person-count qualification",
                    )
                )
    lineage = certificate.get("lineage")
    expected_operation = {
        "mode_a_package_read": "package_read",
        "mode_b_live_predict": "original_prediction",
        "mode_b_live_refine": "refinement",
    }.get(certificate.get("access_mode"))
    if isinstance(lineage, Mapping):
        if lineage.get("operation_kind") != expected_operation:
            issues.append(
                _issue(
                    "/lineage/operation_kind",
                    "access_mode_lineage_operation",
                    "certificate lineage does not match access mode",
                )
            )
        if set(lineage.get("output_artifact_identity_sha256s") or ()) != identities:
            issues.append(
                _issue(
                    "/lineage/output_artifact_identity_sha256s",
                    "certificate_output_lineage",
                    "certificate output lineage must exactly equal bound output identities",
                )
            )
        target_ids = {
            row.get("artifact_identity_sha256")
            for row in lineage.get("input_target_regions") or ()
            if isinstance(row, Mapping)
        }
        protected_ids = {
            row.get("artifact_identity_sha256")
            for row in lineage.get("input_protected_regions") or ()
            if isinstance(row, Mapping)
        }
        if target_ids & protected_ids:
            issues.append(
                _issue(
                    "/lineage/input_protected_regions",
                    "certificate_input_disjoint",
                    "certificate target and protected inputs overlap",
                )
            )
        if certificate.get("access_mode") in {
            "mode_b_live_predict",
            "mode_b_live_refine",
        } and identities & (target_ids | protected_ids):
            issues.append(
                _issue(
                    "/lineage/output_artifact_identity_sha256s",
                    "mode_b_new_output_identity",
                    "Mode B certificate outputs must be new identities",
                )
            )
        if certificate.get("access_mode") == "mode_b_live_refine":
            for index, parent in enumerate(lineage.get("parents") or ()):
                if not isinstance(parent, Mapping) or not (
                    parent.get("authority_state") == "certified"
                    and parent.get("truth_tier") == "operationally_certified_artifact"
                    and parent.get("certificate_kind") == "exact_serving_route_output"
                    and parent.get("certificate_status") == "active"
                    and parent.get("certificate_exact_scope_match") is True
                ):
                    issues.append(
                        _issue(
                            f"/lineage/parents/{index}",
                            "certified_refinement_parent",
                            "certified refinement requires exact operationally certified parents",
                        )
                    )
    claims = certificate.get("claim_limits")
    if (
        not isinstance(claims, Mapping)
        or claims.get("training_gold_claim") is not False
        or claims.get("counts_toward_training_or_accuracy_gates") is not False
        or claims.get("promotion_transaction_required_for_training_gold") is not True
    ):
        issues.append(
            _issue(
                "/claim_limits",
                "operational_truth_firewall",
                "operational certificate must explicitly reject training/accuracy-gold claims and require a separate promotion transaction",
            )
        )
    revocation = certificate.get("revocation")
    if isinstance(revocation, Mapping):
        checked = _parse_timestamp(revocation.get("checked_at"))
        if issued is None or checked is None or checked < issued:
            issues.append(
                _issue(
                    "/revocation/checked_at",
                    "certificate_revocation_time",
                    "revocation evidence must be at or after issuance",
                )
            )
        if certificate.get("status") == "active" and revocation.get("is_revoked") is not False:
            issues.append(
                _issue(
                    "/revocation/is_revoked",
                    "certificate_revocation_status",
                    "active certificate cannot be revoked",
                )
            )
        if use_time is not None and (
            checked is None or checked > use_time or (use_time - checked).total_seconds() > 300
        ):
            issues.append(
                _issue(
                    "/revocation/checked_at",
                    "certificate_revocation_fresh_at_use",
                    "certificate revocation evidence must be no more than 300 seconds old at use time",
                )
            )
    return tuple(sorted(set(issues)))


def _duration_ms(start: Any, end: Any) -> int | None:
    left, right = _parse_timestamp(start), _parse_timestamp(end)
    if left is None or right is None:
        return None
    return round((right - left).total_seconds() * 1000)


def validate_mask_acquisition_receipt(
    receipt: Mapping[str, Any],
    *,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[ValidationIssue, ...]:
    """Validate producer authentication, execution evidence and closed authority derivation."""
    issues: list[ValidationIssue] = list(validate_document(receipt, "mask_acquisition_receipt"))
    hash_issue = _declared_hash_issue(
        receipt,
        hash_field="receipt_payload_sha256",
        excluded=("receipt_payload_sha256", "signature"),
    )
    if hash_issue:
        issues.append(hash_issue)
    issues.extend(
        _ed25519_signature_issues(
            receipt,
            payload_hash_field="receipt_payload_sha256",
            trusted_signing_keys=trusted_signing_keys,
            required_role="producer_receipt",
            decision_time=receipt.get("completed_at"),
        )
    )
    issues.extend(_authentication_issues(receipt, decision_time=receipt.get("completed_at")))
    issues.extend(_media_scope_issues(receipt.get("media_scope")))
    execution = receipt.get("execution_observation")
    if isinstance(execution, Mapping):
        issues.extend(
            _timestamp_order_issues(
                (
                    ("/execution_observation/admitted_at", execution.get("admitted_at")),
                    ("/execution_observation/queued_at", execution.get("queued_at")),
                    ("/execution_observation/started_at", execution.get("started_at")),
                    ("/execution_observation/completed_at", execution.get("completed_at")),
                )
            )
        )
        if execution.get("completed_at") != receipt.get("completed_at"):
            issues.append(
                _issue(
                    "/execution_observation/completed_at",
                    "execution_completion_binding",
                    "execution completion must equal receipt completion",
                )
            )
        expected_queue = _duration_ms(execution.get("queued_at"), execution.get("started_at"))
        expected_runtime = _duration_ms(execution.get("started_at"), execution.get("completed_at"))
        expected_total = _duration_ms(execution.get("admitted_at"), execution.get("completed_at"))
        for field, expected in (
            ("queue_ms", expected_queue),
            ("runtime_ms", expected_runtime),
            ("total_ms", expected_total),
        ):
            if expected is not None and execution.get(field) != expected:
                issues.append(
                    _issue(
                        f"/execution_observation/{field}",
                        "execution_duration",
                        f"{field} must equal timestamp-derived duration",
                    )
                )
        worker = execution.get("worker")
        if isinstance(worker, Mapping):
            issues.extend(
                _timestamp_order_issues(
                    (
                        (
                            "/execution_observation/worker/lease_acquired_at",
                            worker.get("lease_acquired_at"),
                        ),
                        (
                            "/execution_observation/worker/lease_expires_at",
                            worker.get("lease_expires_at"),
                        ),
                    ),
                    allow_equal=False,
                )
            )
            completed = _parse_timestamp(receipt.get("completed_at"))
            acquired = _parse_timestamp(worker.get("lease_acquired_at"))
            expires = _parse_timestamp(worker.get("lease_expires_at"))
            if (
                completed is None
                or acquired is None
                or expires is None
                or not (acquired <= completed < expires)
            ):
                issues.append(
                    _issue(
                        "/execution_observation/worker",
                        "worker_lease_validity",
                        "worker lease must cover execution completion",
                    )
                )
        route = execution.get("route_selection")
        if isinstance(route, Mapping):
            alternatives = route.get("eligible_alternatives") or ()
            alternative_ids = [
                row.get("route_id") for row in alternatives if isinstance(row, Mapping)
            ]
            if len(alternative_ids) != len(set(alternative_ids)):
                issues.append(
                    _issue(
                        "/execution_observation/route_selection/eligible_alternatives",
                        "route_alternatives_unique",
                        "eligible route alternatives must be unique by route_id",
                    )
                )
            if route.get("selected_route_id") in alternative_ids:
                issues.append(
                    _issue(
                        "/execution_observation/route_selection/eligible_alternatives",
                        "route_selection_partition",
                        "selected route must not be repeated among alternatives",
                    )
                )

    qa = receipt.get("qa")
    result = receipt.get("result")
    artifacts = receipt.get("artifacts") or ()
    error = receipt.get("error")
    if isinstance(qa, Mapping):
        status, report, failures = (
            qa.get("status"),
            qa.get("report_sha256"),
            qa.get("blocking_failures") or (),
        )
        if status == "pass" and (not isinstance(report, str) or failures):
            issues.append(
                _issue(
                    "/qa",
                    "qa_evidence_honesty",
                    "QA pass requires a report and zero blocking failures",
                )
            )
        if status == "fail" and (not isinstance(report, str) or not failures):
            issues.append(
                _issue(
                    "/qa",
                    "qa_evidence_honesty",
                    "QA fail requires a report and one or more blocking failures",
                )
            )
        if status == "not_run" and (report is not None or failures):
            issues.append(
                _issue(
                    "/qa",
                    "qa_evidence_honesty",
                    "QA not_run cannot carry a report or blocking failures",
                )
            )
    if result == "succeeded" and (not artifacts or error is not None):
        issues.append(
            _issue(
                "/result",
                "receipt_result_honesty",
                "successful receipt requires outputs and no error",
            )
        )
    if result in {"blocked", "failed"} and (artifacts or not isinstance(error, Mapping)):
        issues.append(
            _issue(
                "/result",
                "receipt_result_honesty",
                "blocked/failed receipt requires no outputs and a typed error",
            )
        )

    artifact_ids: set[str] = set()
    artifact_identities: set[str] = set()
    intent_ids: set[str] = set()
    source = receipt.get("source_binding")
    transform = receipt.get("transform_validation")
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, Mapping):
            continue
        pointer = f"/artifacts/{index}"
        issues.extend(_artifact_semantic_issues(artifact, pointer=pointer))
        for field, seen in (
            ("artifact_id", artifact_ids),
            ("artifact_identity_sha256", artifact_identities),
            ("intent_id", intent_ids),
        ):
            value = artifact.get(field)
            if isinstance(value, str):
                if value in seen:
                    issues.append(
                        _issue(f"{pointer}/{field}", f"unique_{field}", f"{field} must be unique")
                    )
                seen.add(value)
        if isinstance(source, Mapping) and artifact.get(
            "source_decoded_pixel_sha256"
        ) != source.get("decoded_pixel_sha256"):
            issues.append(
                _issue(
                    f"{pointer}/source_decoded_pixel_sha256",
                    "artifact_source_binding",
                    "output artifact must bind exact decoded source pixels",
                )
            )
        if isinstance(transform, Mapping) and artifact.get(
            "transform_chain_sha256"
        ) != transform.get("transform_chain_sha256"):
            issues.append(
                _issue(
                    f"{pointer}/transform_chain_sha256",
                    "artifact_transform_binding",
                    "output artifact must bind executed transform chain",
                )
            )
    lineage = receipt.get("lineage")
    if isinstance(lineage, Mapping):
        expected_operation = {
            "mode_a_package_read": "package_read",
            "mode_b_live_predict": "original_prediction",
            "mode_b_live_refine": "refinement",
        }.get(receipt.get("access_mode"))
        if lineage.get("operation_kind") != expected_operation:
            issues.append(
                _issue(
                    "/lineage/operation_kind",
                    "access_mode_lineage_operation",
                    "lineage operation_kind must match access_mode",
                )
            )
        if set(lineage.get("output_artifact_identity_sha256s") or ()) != artifact_identities:
            issues.append(
                _issue(
                    "/lineage/output_artifact_identity_sha256s",
                    "output_lineage_identity",
                    "output lineage must exactly equal receipt artifact identities",
                )
            )
        target_ids = {
            row.get("artifact_identity_sha256")
            for row in lineage.get("input_target_regions") or ()
            if isinstance(row, Mapping)
        }
        protected_ids = {
            row.get("artifact_identity_sha256")
            for row in lineage.get("input_protected_regions") or ()
            if isinstance(row, Mapping)
        }
        if target_ids & protected_ids:
            issues.append(
                _issue(
                    "/lineage/input_protected_regions",
                    "input_lineage_disjoint",
                    "target and protected input lineages must be disjoint",
                )
            )
        if receipt.get("access_mode") in {
            "mode_b_live_predict",
            "mode_b_live_refine",
        } and artifact_identities & (target_ids | protected_ids):
            issues.append(
                _issue(
                    "/lineage/output_artifact_identity_sha256s",
                    "mode_b_new_output_identity",
                    "Mode B outputs must have new identities distinct from input control/protected artifacts",
                )
            )

    authority = receipt.get("authority")
    truth = receipt.get("truth_tier")
    expected_truth = {
        "invalid": "invalid",
        "hypothesis": "machine_candidate",
        "draft": "machine_candidate",
        "qa_passed_noncertified": "qa_passed_machine_candidate",
        "certified": "operationally_certified_artifact",
    }
    if isinstance(authority, Mapping):
        state = authority.get("authority_state")
        if isinstance(lineage, Mapping) and lineage.get("operation_kind") in {
            "refinement",
            "derived_union",
            "inpaint_derivative",
            "projection",
        }:
            for index, parent in enumerate(lineage.get("parents") or ()):
                if not isinstance(parent, Mapping):
                    continue
                parent_state = parent.get("authority_state")
                if (
                    state in AUTHORITY_RANK
                    and parent_state in AUTHORITY_RANK
                    and AUTHORITY_RANK[state] > AUTHORITY_RANK[parent_state]
                ):
                    issues.append(
                        _issue(
                            "/authority/authority_state",
                            "derived_authority_not_above_parent",
                            f"derived authority cannot exceed parent {index} authority without an exact independent promotion certificate",
                        )
                    )
                if state == "certified" and not (
                    parent_state == "certified"
                    and parent.get("truth_tier") == "operationally_certified_artifact"
                    and parent.get("certificate_kind") == "exact_serving_route_output"
                    and parent.get("certificate_status") == "active"
                    and parent.get("certificate_exact_scope_match") is True
                ):
                    issues.append(
                        _issue(
                            f"/lineage/parents/{index}",
                            "certified_refine_requires_certified_parents",
                            "certified refinement requires every exact parent to be actively operationally certified",
                        )
                    )
        if truth != expected_truth.get(state):
            issues.append(
                _issue(
                    "/truth_tier",
                    "operational_truth_firewall",
                    "truth tier does not match authority and cannot self-promote into training gold",
                )
            )
        if state == "certified" and not (
            authority.get("issuer_kind") == "maskfactory_autonomous"
            and authority.get("certificate_kind") == "exact_serving_route_output"
            and authority.get("decision_basis") == "exact_output_certificate"
            and authority.get("certificate_status") == "active"
            and authority.get("certificate_exact_scope_match") is True
            and isinstance(authority.get("revocation_checked_at"), str)
            and isinstance(authority.get("revocation_index_sha256"), str)
            and isinstance(qa, Mapping)
            and qa.get("status") == "pass"
            and isinstance(transform, Mapping)
            and transform.get("roundtrip_passed") is True
        ):
            issues.append(
                _issue(
                    "/authority",
                    "certified_exact_operational_evidence",
                    "certified authority requires active exact-output certificate, fresh revocation, QA pass and transform roundtrip",
                )
            )
    eligibility = receipt.get("use_eligibility")
    if isinstance(eligibility, Mapping) and eligibility.get("eligible") is True:
        required, observed = eligibility.get("required_authority_state"), (
            authority.get("authority_state") if isinstance(authority, Mapping) else None
        )
        if (
            result != "succeeded"
            or required not in AUTHORITY_RANK
            or observed not in AUTHORITY_RANK
            or AUTHORITY_RANK[observed] < AUTHORITY_RANK[required]
        ):
            issues.append(
                _issue(
                    "/use_eligibility/eligible",
                    "use_eligibility_authority",
                    "eligible use requires successful output at or above policy authority",
                )
            )
    return tuple(sorted(set(issues)))
