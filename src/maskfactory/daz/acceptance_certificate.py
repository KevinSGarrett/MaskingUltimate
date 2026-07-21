"""Hash-bound DAZ scene acceptance certificate and independent replay verification."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..validation import require_valid_document
from .repair_retry import validate_repair_history
from .validation_registry import (
    build_validation_set_report,
    validate_validation_registry,
    validate_validation_result,
)


class AcceptanceCertificateError(ValueError):
    """A certificate policy, input authority, certificate, or publication is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_acceptance_certificate_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_acceptance_certificate_policy(document)
    return document


def validate_acceptance_certificate_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "required_scene_validator_ids",
        "accepted_required_statuses",
        "warnings_satisfy_acceptance",
        "failures_satisfy_acceptance",
        "required_use_profile",
        "required_owner",
        "eligible_truth_tiers",
        "eligible_provider_ids",
        "authority_fields",
        "required_bindings",
        "replay",
        "package",
        "repair",
        "train_eligibility",
        "source_lineage_declaration",
        "publication",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise AcceptanceCertificateError("acceptance_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["policy_version"] != "1.0.0":
        raise AcceptanceCertificateError("acceptance_policy_identity_invalid", str(policy))
    if policy["required_scene_validator_ids"] != [f"DAZ-V{index}-001" for index in range(9)]:
        raise AcceptanceCertificateError("acceptance_policy_validators_invalid", str(policy))
    if (
        policy["accepted_required_statuses"] != ["pass", "not_applicable"]
        or policy["warnings_satisfy_acceptance"] is not False
        or policy["failures_satisfy_acceptance"] is not False
        or policy["required_use_profile"] != "private_personal_noncommercial"
        or policy["required_owner"] != "maskfactory"
        or policy["eligible_truth_tiers"] != ["synthetic_exact"]
        or policy["eligible_provider_ids"] != ["daz_exact_geometry"]
    ):
        raise AcceptanceCertificateError("acceptance_policy_authority_invalid", str(policy))
    if policy["authority_fields"] != [
        "provider_id",
        "authority_tier",
        "ontology_version",
        "ontology_sha256",
        "owner",
        "package_revision",
        "certificate_scope",
        "transform_chain_sha256",
    ] or policy["required_bindings"] != [
        "scene_sha256",
        "package_sha256",
        "recipe_sha256",
        "registry_sha256",
        "runtime_sha256",
        "mapping_set_sha256",
        "label_table_sha256",
        "training_weight_sha256",
        "source_lineage_sha256",
    ]:
        raise AcceptanceCertificateError("acceptance_policy_binding_fields_invalid", str(policy))
    if policy["replay"] != {
        "semantic_hashes_byte_identical_required": True,
        "scene_state_unchanged_required": True,
        "independent_runs_required": True,
        "authorities_identical_required": True,
    }:
        raise AcceptanceCertificateError("acceptance_policy_replay_invalid", str(policy))
    if policy["package"] != {
        "derivation_summary_passed_required": True,
        "file_map_hash_recomputed": True,
        "package_tree_hashes_required": True,
        "eligible_input_truth_tiers": ["weighted_pseudo_label"],
        "certified_output_truth_tier": "synthetic_exact",
        "exact_geometry_source_attribute_required": "synthetic_geometry_exact",
        "pre_certificate_autonomous_gold_must_be_false": True,
    }:
        raise AcceptanceCertificateError("acceptance_policy_package_invalid", str(policy))
    if policy["repair"] != {
        "scheduled_entries_require_post_repair_full_v0_v8_report": True,
        "exhausted_or_rejected_history_forbidden": True,
        "authority_freeze_must_match_certificate": True,
    }:
        raise AcceptanceCertificateError("acceptance_policy_repair_invalid", str(policy))
    if policy["train_eligibility"] != {
        "accepted_certificate_required": True,
        "source_lineage_declaration_required": True,
        "machine_draft_or_mode_b_forbidden": True,
        "authority_ceiling_inference_forbidden": True,
    }:
        raise AcceptanceCertificateError("acceptance_policy_train_invalid", str(policy))
    if policy["source_lineage_declaration"] != {
        "source_origin": "synthetic",
        "annotation_authority": "exact_geometry_render",
        "visible_only": True,
        "amodal_included": False,
        "human_annotation_used": False,
        "live_mode_b_result": False,
        "license_profile": "private_personal_noncommercial",
    }:
        raise AcceptanceCertificateError("acceptance_policy_source_invalid", str(policy))
    if policy["publication"] != {
        "immutable": True,
        "replay_required": True,
        "timestamp_must_be_utc": True,
        "worker_identity_required": True,
    }:
        raise AcceptanceCertificateError("acceptance_policy_publication_invalid", str(policy))


def build_acceptance_certificate(
    draft: Mapping[str, Any],
    validation_report: Mapping[str, Any],
    semantic_replay_report: Mapping[str, Any],
    package_contract: Mapping[str, Any],
    package_report: Mapping[str, Any],
    *,
    repair_history: Mapping[str, Any] | None,
    post_repair_reports: Mapping[str, Mapping[str, Any]],
    policy: Mapping[str, Any],
    repair_policy: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one accepted/train-eligible certificate from independently replayed authorities."""

    validate_acceptance_certificate_policy(policy)
    validate_validation_registry(registry)
    expected_draft = {
        "schema_version",
        "issued_at",
        "worker_identity",
        "use_profile",
        "scene_id",
        "bindings",
        "authority",
        "source_lineage_declaration",
        "train_eligible_requested",
    }
    if not isinstance(draft, Mapping) or set(draft) != expected_draft:
        raise AcceptanceCertificateError("acceptance_draft_fields_invalid", str(draft))
    if draft["schema_version"] != "1.0.0":
        raise AcceptanceCertificateError("acceptance_draft_version_invalid", str(draft))
    issued_at = _utc_timestamp(draft["issued_at"])
    if not _text(draft["worker_identity"]):
        raise AcceptanceCertificateError("acceptance_worker_identity_invalid", str(draft))
    if draft["use_profile"] != policy["required_use_profile"]:
        raise AcceptanceCertificateError(
            "acceptance_use_profile_invalid", str(draft["use_profile"])
        )
    if not _text(draft["scene_id"]):
        raise AcceptanceCertificateError("acceptance_scene_id_invalid", str(draft["scene_id"]))
    bindings = _validate_bindings(draft["bindings"], policy)
    authority = _validate_authority(draft["authority"], policy)
    if draft["source_lineage_declaration"] != policy["source_lineage_declaration"]:
        raise AcceptanceCertificateError("acceptance_source_lineage_invalid", str(draft))
    if draft["train_eligible_requested"] is not True:
        raise AcceptanceCertificateError("acceptance_train_eligibility_not_requested", str(draft))
    validation = _accepted_validation(validation_report, draft["scene_id"], policy, registry)
    replay = _accepted_replay(semantic_replay_report, draft["scene_id"])
    package = _accepted_package(package_contract, package_report, draft["scene_id"], policy)
    expected_scene_sha = package_contract["scene_state_sha256"]
    expected_package_sha = _canonical_sha(
        [
            {
                "package_id": row["package_id"],
                "package_tree_sha256": row["package_tree_sha256"],
                "file_hashes": row["file_hashes"],
            }
            for row in package_report["packages"]
        ]
    )
    if (
        bindings["scene_sha256"] != expected_scene_sha
        or bindings["package_sha256"] != expected_package_sha
        or bindings["registry_sha256"] != _canonical_sha(registry)
    ):
        raise AcceptanceCertificateError("acceptance_package_binding_invalid", draft["scene_id"])
    if (
        semantic_replay_report["scene_state_sha256"] != expected_scene_sha
        or semantic_replay_report["plan_id"] != package_contract["plan_id"]
        or semantic_replay_report["plan_sha256"] != package_contract["plan_sha256"]
    ):
        raise AcceptanceCertificateError(
            "acceptance_replay_package_binding_invalid", draft["scene_id"]
        )
    if (
        authority["ontology_version"] != package_contract["ontology_version"]
        or authority["ontology_sha256"] != package_contract["ontology_snapshot_sha256"]
        or authority["package_revision"] != package_contract["contract_id"]
    ):
        raise AcceptanceCertificateError("acceptance_package_authority_invalid", draft["scene_id"])
    if bindings["source_lineage_sha256"] != _canonical_sha(draft["source_lineage_declaration"]):
        raise AcceptanceCertificateError("acceptance_source_binding_invalid", draft["scene_id"])
    repair = _accepted_repair(
        repair_history,
        post_repair_reports,
        final_validation_report=validation_report,
        authority=authority,
        bindings=bindings,
        policy=policy,
        repair_policy=repair_policy,
        registry=registry,
        scene_id=draft["scene_id"],
    )
    content = {
        "policy_version": policy["policy_version"],
        "policy_sha256": _canonical_sha(policy),
        "issued_at": issued_at,
        "worker_identity": draft["worker_identity"],
        "use_profile": draft["use_profile"],
        "scene_id": draft["scene_id"],
        "bindings": bindings,
        "authority": authority,
        "validation": validation,
        "semantic_replay": replay,
        "package": package,
        "repair": repair,
        "source_lineage_declaration": dict(draft["source_lineage_declaration"]),
        "train_eligible": True,
        "accepted": True,
    }
    digest = _canonical_sha(content)
    certificate = {
        "schema_version": "1.0.0",
        "certificate_id": f"dacc_{digest[:24]}",
        "certificate_sha256": digest,
        **content,
    }
    require_valid_document(certificate, "daz_acceptance_certificate")
    return certificate


def verify_acceptance_certificate(
    certificate: Mapping[str, Any],
    validation_report: Mapping[str, Any],
    semantic_replay_report: Mapping[str, Any],
    package_contract: Mapping[str, Any],
    package_report: Mapping[str, Any],
    *,
    repair_history: Mapping[str, Any] | None,
    post_repair_reports: Mapping[str, Mapping[str, Any]],
    policy: Mapping[str, Any],
    repair_policy: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Rebuild every certificate field and reject stale or rebound authority."""

    require_valid_document(certificate, "daz_acceptance_certificate")
    draft = {
        "schema_version": "1.0.0",
        "issued_at": certificate["issued_at"],
        "worker_identity": certificate["worker_identity"],
        "use_profile": certificate["use_profile"],
        "scene_id": certificate["scene_id"],
        "bindings": certificate["bindings"],
        "authority": certificate["authority"],
        "source_lineage_declaration": certificate["source_lineage_declaration"],
        "train_eligible_requested": True,
    }
    rebuilt = build_acceptance_certificate(
        draft,
        validation_report,
        semantic_replay_report,
        package_contract,
        package_report,
        repair_history=repair_history,
        post_repair_reports=post_repair_reports,
        policy=policy,
        repair_policy=repair_policy,
        registry=registry,
    )
    if rebuilt != certificate:
        raise AcceptanceCertificateError(
            "acceptance_certificate_replay_mismatch", str(certificate["certificate_id"])
        )
    return {
        "certificate_id": certificate["certificate_id"],
        "certificate_sha256": certificate["certificate_sha256"],
        "scene_id": certificate["scene_id"],
        "accepted": True,
        "train_eligible": True,
        "authority_tier": certificate["authority"]["authority_tier"],
    }


def publish_acceptance_certificate(
    certificate: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    require_valid_document(certificate, "daz_acceptance_certificate")
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{certificate['certificate_id']}.json"
    payload = json.dumps(certificate, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise AcceptanceCertificateError("acceptance_publication_conflict", str(target))
        return target, False
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=root
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target, True


def _accepted_validation(
    report: Mapping[str, Any],
    scene_id: str,
    policy: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    rebuilt = _rebuild_validation(report, registry)
    required = policy["required_scene_validator_ids"]
    results = {row["validator_id"]: row for row in rebuilt["results"]}
    if (
        rebuilt["scope"] != "scene"
        or rebuilt["entity_id"] != scene_id
        or rebuilt["required_validator_ids"] != required
        or set(results) != set(required)
        or not rebuilt["summary"]["passed"]
        or any(
            row["status"] not in policy["accepted_required_statuses"] for row in results.values()
        )
        or rebuilt["summary"]["warning_count"] != 0
        or rebuilt["summary"]["failed_count"] != 0
    ):
        raise AcceptanceCertificateError("acceptance_validation_set_invalid", str(scene_id))
    measurements = [
        {
            "validator_id": validator_id,
            "status": results[validator_id]["status"],
            "reason_code": results[validator_id]["reason_code"],
            "metric": results[validator_id]["metric"],
            "observed": results[validator_id]["observed"],
            "expected": results[validator_id]["expected"],
        }
        for validator_id in required
    ]
    return {
        "report_id": rebuilt["report_id"],
        "report_sha256": rebuilt["report_sha256"],
        "registry_version": rebuilt["registry_version"],
        "required_validator_ids": list(required),
        "pass_count": rebuilt["summary"]["required_pass_count"],
        "not_applicable_count": rebuilt["summary"]["not_applicable_count"],
        "warning_count": 0,
        "failure_count": 0,
        "measurements": measurements,
    }


def _accepted_replay(report: Mapping[str, Any], scene_id: str) -> dict[str, Any]:
    require_valid_document(report, "daz_same_state_replay_report")
    _verify_hashed(report, "report_id", "report_sha256", "dssr")
    summary = report["summary"]
    if (
        report["scene_id"] != scene_id
        or not summary["passed"]
        or not summary["semantic_hashes_byte_identical"]
        or not summary["scene_state_unchanged"]
        or not summary["runs_independent"]
        or not summary["authorities_identical"]
    ):
        raise AcceptanceCertificateError("acceptance_semantic_replay_invalid", scene_id)
    semantic_set_sha = _canonical_sha(
        [
            {"role": row["role"], "sha256": row["original_sha256"], "bytes": row["original_bytes"]}
            for row in report["semantic_records"]
        ]
    )
    return {
        "report_id": report["report_id"],
        "report_sha256": report["report_sha256"],
        "semantic_set_sha256": semantic_set_sha,
        "semantic_hashes_byte_identical": True,
        "scene_state_unchanged": True,
        "runs_independent": True,
        "authorities_identical": True,
    }


def _accepted_package(
    contract: Mapping[str, Any],
    report: Mapping[str, Any],
    scene_id: str,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    require_valid_document(contract, "daz_package_derivation_contract")
    _verify_hashed(contract, "contract_id", "contract_sha256", "dpdc")
    require_valid_document(report, "daz_package_derivation_report")
    _verify_hashed(report, "report_id", "report_sha256", "dpdr")
    truth = contract["truth_contract"]
    if (
        report["scene_id"] != scene_id
        or contract["scene_id"] != scene_id
        or report["contract_id"] != contract["contract_id"]
        or report["contract_sha256"] != contract["contract_sha256"]
        or report["source_file_sha256s"] != contract["source_file_sha256s"]
        or not report["summary"]["passed"]
        or report["summary"]["package_count"] != len(report["packages"])
        or truth.get("truth_tier") not in policy["package"]["eligible_input_truth_tiers"]
        or policy["package"]["exact_geometry_source_attribute_required"]
        not in truth.get("source_attributes", [])
        or truth.get("counts_as_autonomous_certified_gold") is not False
        or truth.get("counts_as_human_anchor_gold") is not False
    ):
        raise AcceptanceCertificateError("acceptance_package_report_invalid", scene_id)
    packages = report["packages"]
    file_map_sha = _canonical_sha(
        [{"package_id": row["package_id"], "file_hashes": row["file_hashes"]} for row in packages]
    )
    return {
        "contract_id": contract["contract_id"],
        "contract_sha256": contract["contract_sha256"],
        "input_truth_contract_sha256": _canonical_sha(truth),
        "input_truth_tier": truth["truth_tier"],
        "certified_truth_tier": policy["package"]["certified_output_truth_tier"],
        "report_id": report["report_id"],
        "report_sha256": report["report_sha256"],
        "file_map_sha256": file_map_sha,
        "package_tree_sha256s": [row["package_tree_sha256"] for row in packages],
        "package_count": len(packages),
    }


def _accepted_repair(
    history: Mapping[str, Any] | None,
    reports: Mapping[str, Mapping[str, Any]],
    *,
    final_validation_report: Mapping[str, Any],
    authority: Mapping[str, Any],
    bindings: Mapping[str, Any],
    policy: Mapping[str, Any],
    repair_policy: Mapping[str, Any],
    registry: Mapping[str, Any],
    scene_id: str,
) -> dict[str, Any]:
    if history is None:
        if reports:
            raise AcceptanceCertificateError("acceptance_repair_reports_unexpected", scene_id)
        return {
            "history_id": None,
            "history_sha256": None,
            "entry_count": 0,
            "scheduled_count": 0,
            "post_repair_validations": [],
        }
    validate_repair_history(history, policy=repair_policy)
    if history["entity_id"] != scene_id or any(
        row["disposition"] != "scheduled" for row in history["entries"]
    ):
        raise AcceptanceCertificateError("acceptance_repair_history_invalid", scene_id)
    freeze = history["authority_freeze"]
    required_set_sha = _canonical_sha(policy["required_scene_validator_ids"])
    if freeze != {
        "ontology_sha256": authority["ontology_sha256"],
        "mapping_set_sha256": bindings["mapping_set_sha256"],
        "label_table_sha256": bindings["label_table_sha256"],
        "truth_tier": authority["authority_tier"],
        "training_weight_sha256": bindings["training_weight_sha256"],
        "required_validator_set_sha256": required_set_sha,
    }:
        raise AcceptanceCertificateError("acceptance_repair_authority_mismatch", scene_id)
    scheduled = history["entries"]
    revision_ids = [row["next_recipe_revision_id"] for row in scheduled]
    if list(reports) != revision_ids:
        raise AcceptanceCertificateError("acceptance_repair_report_set_invalid", str(reports))
    report_bindings = []
    for revision_id in revision_ids:
        report = _rebuild_validation(reports[revision_id], registry)
        if (
            report["scope"] != "scene"
            or report["entity_id"] != scene_id
            or report["required_validator_ids"] != policy["required_scene_validator_ids"]
        ):
            raise AcceptanceCertificateError("acceptance_repair_revalidation_invalid", revision_id)
        report_bindings.append(
            {
                "recipe_revision_id": revision_id,
                "report_id": report["report_id"],
                "report_sha256": report["report_sha256"],
            }
        )
    if report_bindings[-1]["report_sha256"] != final_validation_report["report_sha256"]:
        raise AcceptanceCertificateError("acceptance_final_revalidation_mismatch", scene_id)
    return {
        "history_id": history["history_id"],
        "history_sha256": history["history_sha256"],
        "entry_count": history["summary"]["entry_count"],
        "scheduled_count": history["summary"]["scheduled_count"],
        "post_repair_validations": report_bindings,
    }


def _rebuild_validation(report: Mapping[str, Any], registry: Mapping[str, Any]) -> dict[str, Any]:
    require_valid_document(report, "daz_validation_set_report")
    _verify_hashed(report, "report_id", "report_sha256", "dvsr")
    for result in report["results"]:
        validate_validation_result(result, registry)
    rebuilt = build_validation_set_report(
        report["results"],
        entity_id=report["entity_id"],
        scope=report["scope"],
        registry=registry,
        required_validator_ids=report["required_validator_ids"],
    )
    if rebuilt != report:
        raise AcceptanceCertificateError(
            "acceptance_validation_replay_mismatch", report["report_id"]
        )
    return rebuilt


def _validate_bindings(bindings: Any, policy: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(bindings, Mapping) or list(bindings) != policy["required_bindings"]:
        raise AcceptanceCertificateError("acceptance_binding_fields_invalid", str(bindings))
    if any(not _sha256(value) for value in bindings.values()):
        raise AcceptanceCertificateError("acceptance_binding_hash_invalid", str(bindings))
    return dict(bindings)


def _validate_authority(authority: Any, policy: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(authority, Mapping) or list(authority) != policy["authority_fields"]:
        raise AcceptanceCertificateError("acceptance_authority_fields_invalid", str(authority))
    if (
        authority["provider_id"] not in policy["eligible_provider_ids"]
        or authority["authority_tier"] not in policy["eligible_truth_tiers"]
        or authority["owner"] != policy["required_owner"]
        or not _text(authority["ontology_version"])
        or not _sha256(authority["ontology_sha256"])
        or not _text(authority["package_revision"])
        or not _text(authority["certificate_scope"])
        or not _sha256(authority["transform_chain_sha256"])
    ):
        raise AcceptanceCertificateError("acceptance_authority_invalid", str(authority))
    return dict(authority)


def _utc_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AcceptanceCertificateError("acceptance_timestamp_invalid", str(value))
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise AcceptanceCertificateError("acceptance_timestamp_invalid", value) from exc
    if parsed.tzinfo != UTC or parsed.microsecond != 0:
        raise AcceptanceCertificateError("acceptance_timestamp_invalid", value)
    canonical = parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
    if canonical != value:
        raise AcceptanceCertificateError("acceptance_timestamp_invalid", value)
    return canonical


def _verify_hashed(
    document: Mapping[str, Any], id_field: str, hash_field: str, prefix: str
) -> None:
    content = {
        key: value
        for key, value in document.items()
        if key not in {"schema_version", id_field, hash_field}
    }
    digest = _canonical_sha(content)
    if document[hash_field] != digest or document[id_field] != f"{prefix}_{digest[:24]}":
        raise AcceptanceCertificateError("acceptance_bound_report_hash_invalid", str(document))


def _canonical_sha(document: Any) -> str:
    try:
        payload = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise AcceptanceCertificateError("acceptance_canonical_json_invalid", str(exc)) from exc
    return hashlib.sha256(payload).hexdigest()


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 256
