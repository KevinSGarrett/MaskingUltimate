"""Deterministic bounded-repair decisions and per-demand retry ledgers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..validation import require_valid_document
from .validation_registry import (
    build_validation_set_report,
    validate_validation_registry,
    validate_validation_result,
)


class RepairRetryError(ValueError):
    """A repair policy, request, history, or publication is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_repair_retry_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_repair_retry_policy(document)
    return document


def validate_repair_retry_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "authority_freeze_fields",
        "retry_budgets",
        "repair_rules",
        "non_repairable_reason_codes",
        "quarantine_reason_codes",
        "numeric_limits",
        "publication",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise RepairRetryError("repair_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["policy_version"] != "1.0.0":
        raise RepairRetryError("repair_policy_identity_invalid", str(policy))
    if policy["authority_freeze_fields"] != [
        "ontology_sha256",
        "mapping_set_sha256",
        "label_table_sha256",
        "truth_tier",
        "training_weight_sha256",
        "required_validator_set_sha256",
    ]:
        raise RepairRetryError("repair_policy_authority_invalid", str(policy))
    expected_budgets = {
        "same_recipe_clean_rerender": 1,
        "camera_support_correction": 2,
        "cloth_hair_settle": 1,
        "asset_combination_replacement": 3,
        "full_recipe_regeneration": 5,
    }
    if policy["retry_budgets"] != expected_budgets:
        raise RepairRetryError("repair_policy_budgets_invalid", str(policy["retry_budgets"]))
    expected_rules = {
        "CAMERA_RECENTER": (
            "ASSEMBLY_FRAMING_INVALID",
            "adjusted_recipe",
            "framing",
            "camera_support_correction",
            "camera_recenter_distance",
            ["camera_target_offset_cm", "distance_delta_cm"],
        ),
        "CAMERA_CLIP_PLANES": (
            "ASSEMBLY_FRAMING_INVALID",
            "adjusted_recipe",
            "camera_clip",
            "camera_support_correction",
            "camera_clip_planes",
            ["near_plane_delta_cm", "far_plane_delta_cm"],
        ),
        "SUPPORT_TRANSLATION": (
            "ASSEMBLY_FIT_INVALID",
            "adjusted_recipe",
            "support_contact",
            "camera_support_correction",
            "support_contact_translation",
            ["construction_id", "translation_delta_cm"],
        ),
        "CLOTH_HAIR_SETTLE": (
            "ASSEMBLY_FIT_INVALID",
            "adjusted_recipe",
            "cloth_hair_settle",
            "cloth_hair_settle",
            "rerun_pinned_simulation_cache",
            ["node_id", "simulation_seed", "cache_sha256"],
        ),
        "SMOOTHING_FIT_ADJUSTMENT": (
            "GEOMETRY_PENETRATION_EXCESS",
            "adjusted_recipe",
            "mild_hair_garment_penetration",
            "cloth_hair_settle",
            "configured_smoothing_fit_adjustment",
            ["node_id", "adjustment_profile_id"],
        ),
        "PLACEMENT_SEPARATION": (
            "GEOMETRY_PENETRATION_EXCESS",
            "adjusted_recipe",
            "unintended_near_contact",
            "camera_support_correction",
            "placement_separation",
            ["construction_id", "translation_delta_cm"],
        ),
        "CLEAN_WORKER_RERENDER": (
            "RENDER_PROCESS_FAILED",
            "same_recipe",
            "transient_render",
            "same_recipe_clean_rerender",
            "clean_worker_rerender",
            ["worker_restart_nonce"],
        ),
        "COVERAGE_ASSET_POSE_RESAMPLE": (
            "CORPUS_COVERAGE_DEFICIT",
            "adjusted_recipe",
            "coverage_deficit",
            "asset_combination_replacement",
            "resample_compatible_asset_pose",
            ["replacement_stream_seed", "excluded_asset_ids"],
        ),
        "FULL_RECIPE_REGENERATION": (
            "RECIPE_RANGE_INVALID",
            "adjusted_recipe",
            "recipe_regeneration",
            "full_recipe_regeneration",
            "regenerate_from_clean_registry_snapshot",
            ["replacement_master_seed"],
        ),
    }
    rules = policy["repair_rules"]
    if not isinstance(rules, Mapping) or set(rules) != set(expected_rules):
        raise RepairRetryError("repair_policy_rules_invalid", str(rules))
    for defect_code, values in expected_rules.items():
        reason, retryability, family, retry_class, action, delta_fields = values
        if rules[defect_code] != {
            "reason_code": reason,
            "retryability": retryability,
            "reason_family": family,
            "retry_class": retry_class,
            "action": action,
            "delta_fields": delta_fields,
        }:
            raise RepairRetryError("repair_policy_rules_invalid", defect_code)
    non_repairable = policy["non_repairable_reason_codes"]
    quarantine = policy["quarantine_reason_codes"]
    if (
        not _unique_strings(non_repairable)
        or non_repairable != sorted(non_repairable)
        or not _unique_strings(quarantine)
        or quarantine != sorted(quarantine)
        or not set(quarantine) <= set(non_repairable)
        or set(non_repairable) & {row[0] for row in expected_rules.values()}
    ):
        raise RepairRetryError("repair_policy_nonrepairable_invalid", str(policy))
    if policy["numeric_limits"] != {
        "scalar_delta_cm_abs_max": 25.0,
        "vector_delta_cm_abs_max": 10.0,
        "near_plane_delta_cm_abs_max": 5.0,
        "far_plane_delta_cm_abs_max": 100.0,
        "seed_max": 18446744073709551615,
    }:
        raise RepairRetryError("repair_policy_limits_invalid", str(policy["numeric_limits"]))
    if policy["publication"] != {
        "immutable": True,
        "hash_chained": True,
        "full_revalidation_required": True,
        "coverage_deficit_on_exhaustion": True,
    }:
        raise RepairRetryError("repair_policy_publication_invalid", str(policy["publication"]))


def build_repair_request(
    draft: Mapping[str, Any],
    validation_report: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal one exact repair/non-repairable decision request to failed evidence."""

    validate_repair_retry_policy(policy)
    validate_validation_registry(registry)
    _validate_report(validation_report, registry)
    expected = {
        "schema_version",
        "demand_id",
        "entity_id",
        "parent_recipe_sha256",
        "parent_recipe_revision",
        "validator_id",
        "defect_code",
        "proposed_delta",
        "authority_freeze",
    }
    if not isinstance(draft, Mapping) or set(draft) != expected:
        raise RepairRetryError("repair_request_draft_fields_invalid", str(draft))
    if (
        draft["schema_version"] != "1.0.0"
        or not _bounded_string(draft["demand_id"])
        or not _bounded_string(draft["entity_id"])
        or draft["entity_id"] != validation_report["entity_id"]
        or not _sha256(draft["parent_recipe_sha256"])
        or isinstance(draft["parent_recipe_revision"], bool)
        or not isinstance(draft["parent_recipe_revision"], int)
        or draft["parent_recipe_revision"] < 0
        or not isinstance(draft["validator_id"], str)
        or not isinstance(draft["defect_code"], str)
        or not isinstance(draft["proposed_delta"], Mapping)
    ):
        raise RepairRetryError("repair_request_draft_invalid", str(draft))
    _validate_authority_freeze(draft["authority_freeze"], policy)
    results = {
        row["validator_id"]: row
        for row in validation_report["results"]
        if row.get("status") == "fail"
    }
    result = results.get(draft["validator_id"])
    if result is None:
        raise RepairRetryError("repair_request_failed_result_missing", draft["validator_id"])
    reason_code = result["reason_code"]
    defect_code = draft["defect_code"]
    if reason_code in policy["non_repairable_reason_codes"]:
        if defect_code != "NON_REPAIRABLE" or draft["proposed_delta"]:
            raise RepairRetryError("repair_request_nonrepairable_delta_invalid", reason_code)
    else:
        rule = policy["repair_rules"].get(defect_code)
        if rule is None or rule["reason_code"] != reason_code:
            raise RepairRetryError("repair_request_rule_mismatch", f"{reason_code}:{defect_code}")
        if result["retryability"] != rule["retryability"]:
            raise RepairRetryError("repair_request_retryability_mismatch", reason_code)
        _validate_delta(defect_code, draft["proposed_delta"], policy)
    content = {
        "demand_id": draft["demand_id"],
        "entity_id": draft["entity_id"],
        "parent_recipe_sha256": draft["parent_recipe_sha256"],
        "parent_recipe_revision": draft["parent_recipe_revision"],
        "validation_report_id": validation_report["report_id"],
        "validation_report_sha256": validation_report["report_sha256"],
        "validator_id": draft["validator_id"],
        "reason_code": reason_code,
        "defect_code": defect_code,
        "proposed_delta": dict(draft["proposed_delta"]),
        "authority_freeze": dict(draft["authority_freeze"]),
        "policy_sha256": _canonical_sha(policy),
    }
    digest = _canonical_sha(content)
    request = {
        "schema_version": "1.0.0",
        "request_id": f"drrq_{digest[:24]}",
        "request_sha256": digest,
        **content,
    }
    require_valid_document(request, "daz_repair_request")
    return request


def append_repair_decision(
    request: Mapping[str, Any],
    validation_report: Mapping[str, Any],
    history: Mapping[str, Any] | None,
    *,
    policy: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Append one deterministic scheduled/rejected/exhausted hash-chained entry."""

    validate_repair_retry_policy(policy)
    validate_validation_registry(registry)
    _validate_report(validation_report, registry)
    _validate_request(request, validation_report, policy, registry)
    if history is None:
        entries: list[dict[str, Any]] = []
    else:
        validate_repair_history(history, policy=policy)
        if (
            history["demand_id"] != request["demand_id"]
            or history["entity_id"] != request["entity_id"]
            or history["authority_freeze"] != request["authority_freeze"]
            or history["policy_sha256"] != request["policy_sha256"]
        ):
            raise RepairRetryError("repair_history_request_lineage_invalid", request["request_id"])
        entries = [dict(row) for row in history["entries"]]
        duplicates = [row for row in entries if row["request_id"] == request["request_id"]]
        if duplicates:
            if len(duplicates) != 1 or duplicates[0]["request_sha256"] != request["request_sha256"]:
                raise RepairRetryError("repair_history_request_collision", request["request_id"])
            return dict(history)
        latest_scheduled = next(
            (row for row in reversed(entries) if row["disposition"] == "scheduled"), None
        )
        if (
            latest_scheduled is not None
            and request["parent_recipe_revision"] != latest_scheduled["next_recipe_revision"]
        ):
            raise RepairRetryError(
                "repair_history_parent_revision_invalid", str(request["parent_recipe_revision"])
            )
    rule = policy["repair_rules"].get(request["defect_code"])
    nonrepairable = request["reason_code"] in policy["non_repairable_reason_codes"]
    if nonrepairable:
        disposition = "rejected_nonrepairable"
        retry_class = action = None
        reason_family = request["reason_code"]
        attempt = maximum = 0
        next_revision = next_revision_id = None
        delta: dict[str, Any] = {}
        coverage_deficit = False
        prior_same_rejections = sum(
            row["disposition"] == "rejected_nonrepairable"
            and row["reason_code"] == request["reason_code"]
            for row in entries
        )
        quarantine = (
            request["reason_code"] in policy["quarantine_reason_codes"]
            and prior_same_rejections >= 1
        )
    else:
        retry_class = rule["retry_class"]
        reason_family = rule["reason_family"]
        maximum = policy["retry_budgets"][retry_class]
        if any(
            row["disposition"] == "budget_exhausted" and row["reason_family"] == reason_family
            for row in entries
        ):
            raise RepairRetryError("repair_budget_already_exhausted", reason_family)
        used = sum(
            row["disposition"] == "scheduled" and row["reason_family"] == reason_family
            for row in entries
        )
        attempt = used + 1
        if attempt > maximum:
            disposition = "budget_exhausted"
            action = None
            next_revision = next_revision_id = None
            delta = {}
            coverage_deficit = True
        else:
            disposition = "scheduled"
            action = rule["action"]
            next_revision = request["parent_recipe_revision"] + 1
            delta = dict(request["proposed_delta"])
            revision_seed = {
                "request_sha256": request["request_sha256"],
                "attempt": attempt,
                "parent_recipe_revision": request["parent_recipe_revision"],
                "delta": delta,
            }
            next_revision_id = f"daz_recipe_revision_{_canonical_sha(revision_seed)[:24]}"
            coverage_deficit = False
        quarantine = False
    entry_content = {
        "sequence": len(entries) + 1,
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "validation_report_id": request["validation_report_id"],
        "validation_report_sha256": request["validation_report_sha256"],
        "validator_id": request["validator_id"],
        "reason_code": request["reason_code"],
        "defect_code": request["defect_code"],
        "reason_family": reason_family,
        "disposition": disposition,
        "retry_class": retry_class,
        "action": action,
        "attempt": attempt,
        "maximum_attempts": maximum,
        "parent_recipe_sha256": request["parent_recipe_sha256"],
        "parent_recipe_revision": request["parent_recipe_revision"],
        "next_recipe_revision": next_revision,
        "next_recipe_revision_id": next_revision_id,
        "delta": delta,
        "previous_entry_sha256": entries[-1]["entry_sha256"] if entries else None,
        "full_revalidation_required": True,
        "coverage_deficit": coverage_deficit,
        "quarantine_recommended": quarantine,
    }
    entry = {**entry_content, "entry_sha256": _canonical_sha(entry_content)}
    entries.append(entry)
    history_content = {
        "demand_id": request["demand_id"],
        "entity_id": request["entity_id"],
        "authority_freeze": dict(request["authority_freeze"]),
        "policy_sha256": request["policy_sha256"],
        "entries": entries,
        "summary": _history_summary(entries),
    }
    digest = _canonical_sha(history_content)
    result = {
        "schema_version": "1.0.0",
        "history_id": f"drrh_{digest[:24]}",
        "history_sha256": digest,
        **history_content,
    }
    validate_repair_history(result, policy=policy)
    return result


def validate_repair_history(history: Mapping[str, Any], *, policy: Mapping[str, Any]) -> None:
    validate_repair_retry_policy(policy)
    require_valid_document(history, "daz_repair_history")
    _verify_hashed(history, "history_id", "history_sha256", "drrh")
    if history["policy_sha256"] != _canonical_sha(policy):
        raise RepairRetryError("repair_history_policy_mismatch", history["history_id"])
    _validate_authority_freeze(history["authority_freeze"], policy)
    previous = None
    seen_requests: set[str] = set()
    scheduled_by_family: dict[str, int] = {}
    exhausted_families: set[str] = set()
    rejected_by_reason: dict[str, int] = {}
    latest_scheduled_revision: int | None = None
    for index, entry in enumerate(history["entries"], start=1):
        if entry["sequence"] != index or entry["previous_entry_sha256"] != previous:
            raise RepairRetryError("repair_history_chain_invalid", str(index))
        content = {key: value for key, value in entry.items() if key != "entry_sha256"}
        if entry["entry_sha256"] != _canonical_sha(content):
            raise RepairRetryError("repair_history_entry_hash_invalid", str(index))
        if entry["request_id"] in seen_requests:
            raise RepairRetryError("repair_history_duplicate_request", entry["request_id"])
        seen_requests.add(entry["request_id"])
        _validate_entry_semantics(entry, policy)
        if (
            latest_scheduled_revision is not None
            and entry["parent_recipe_revision"] != latest_scheduled_revision
        ):
            raise RepairRetryError("repair_history_parent_revision_invalid", str(index))
        if entry["disposition"] == "scheduled":
            if entry["reason_family"] in exhausted_families:
                raise RepairRetryError("repair_history_after_exhaustion", entry["reason_family"])
            expected_attempt = scheduled_by_family.get(entry["reason_family"], 0) + 1
            if entry["attempt"] != expected_attempt:
                raise RepairRetryError("repair_history_attempt_invalid", str(index))
            scheduled_by_family[entry["reason_family"]] = expected_attempt
            latest_scheduled_revision = entry["next_recipe_revision"]
            revision_seed = {
                "request_sha256": entry["request_sha256"],
                "attempt": entry["attempt"],
                "parent_recipe_revision": entry["parent_recipe_revision"],
                "delta": entry["delta"],
            }
            expected_revision_id = f"daz_recipe_revision_{_canonical_sha(revision_seed)[:24]}"
            if entry["next_recipe_revision_id"] != expected_revision_id:
                raise RepairRetryError("repair_history_revision_id_invalid", str(index))
        elif entry["disposition"] == "budget_exhausted":
            used = scheduled_by_family.get(entry["reason_family"], 0)
            if used != entry["maximum_attempts"] or entry["attempt"] != used + 1:
                raise RepairRetryError("repair_history_exhaustion_count_invalid", str(index))
            if entry["reason_family"] in exhausted_families:
                raise RepairRetryError(
                    "repair_history_duplicate_exhaustion", entry["reason_family"]
                )
            exhausted_families.add(entry["reason_family"])
        elif entry["disposition"] == "rejected_nonrepairable":
            previous_rejections = rejected_by_reason.get(entry["reason_code"], 0)
            expected_quarantine = (
                entry["reason_code"] in policy["quarantine_reason_codes"]
                and previous_rejections >= 1
            )
            if entry["quarantine_recommended"] != expected_quarantine:
                raise RepairRetryError("repair_history_quarantine_invalid", str(index))
            rejected_by_reason[entry["reason_code"]] = previous_rejections + 1
        previous = entry["entry_sha256"]
    if history["summary"] != _history_summary(history["entries"]):
        raise RepairRetryError("repair_history_summary_invalid", history["history_id"])


def publish_repair_history(history: Mapping[str, Any], output_root: Path) -> tuple[Path, bool]:
    require_valid_document(history, "daz_repair_history")
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{history['history_id']}.json"
    payload = json.dumps(history, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise RepairRetryError("repair_history_publication_conflict", str(target))
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


def _validate_request(
    request: Mapping[str, Any],
    report: Mapping[str, Any],
    policy: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> None:
    require_valid_document(request, "daz_repair_request")
    _verify_hashed(request, "request_id", "request_sha256", "drrq")
    draft = {
        key: request[key]
        for key in (
            "demand_id",
            "entity_id",
            "parent_recipe_sha256",
            "parent_recipe_revision",
            "validator_id",
            "defect_code",
            "proposed_delta",
            "authority_freeze",
        )
    }
    draft["schema_version"] = "1.0.0"
    rebuilt = build_repair_request(draft, report, policy=policy, registry=registry)
    if rebuilt != request:
        raise RepairRetryError("repair_request_replay_mismatch", request["request_id"])


def _validate_report(report: Mapping[str, Any], registry: Mapping[str, Any]) -> None:
    require_valid_document(report, "daz_validation_set_report")
    _verify_hashed(report, "report_id", "report_sha256", "dvsr")
    if report["scope"] not in {"scene", "corpus"}:
        raise RepairRetryError("repair_report_scope_invalid", str(report["scope"]))
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
        raise RepairRetryError("repair_report_replay_mismatch", report["report_id"])


def _validate_authority_freeze(authority: Any, policy: Mapping[str, Any]) -> None:
    if not isinstance(authority, Mapping) or list(authority) != policy["authority_freeze_fields"]:
        raise RepairRetryError("repair_authority_fields_invalid", str(authority))
    for field in policy["authority_freeze_fields"]:
        value = authority[field]
        if field == "truth_tier":
            if not _bounded_string(value):
                raise RepairRetryError("repair_authority_value_invalid", field)
        elif not _sha256(value):
            raise RepairRetryError("repair_authority_value_invalid", field)


def _validate_delta(defect_code: str, delta: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    expected_fields = policy["repair_rules"][defect_code]["delta_fields"]
    if list(delta) != expected_fields:
        raise RepairRetryError("repair_delta_fields_invalid", f"{defect_code}:{list(delta)}")
    limits = policy["numeric_limits"]
    for field, value in delta.items():
        if field in {"camera_target_offset_cm", "translation_delta_cm"}:
            if not _vector(value, limits["vector_delta_cm_abs_max"]):
                raise RepairRetryError("repair_delta_range_invalid", field)
        elif field == "near_plane_delta_cm":
            if not _scalar(value, limits["near_plane_delta_cm_abs_max"]):
                raise RepairRetryError("repair_delta_range_invalid", field)
        elif field == "far_plane_delta_cm":
            if not _scalar(value, limits["far_plane_delta_cm_abs_max"]):
                raise RepairRetryError("repair_delta_range_invalid", field)
        elif field == "distance_delta_cm":
            if not _scalar(value, limits["scalar_delta_cm_abs_max"]):
                raise RepairRetryError("repair_delta_range_invalid", field)
        elif field in {"simulation_seed", "replacement_stream_seed", "replacement_master_seed"}:
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= limits["seed_max"]
            ):
                raise RepairRetryError("repair_delta_seed_invalid", field)
        elif field == "construction_id":
            if value not in {"c0", "c1", "c2", "c3"}:
                raise RepairRetryError("repair_delta_construction_invalid", str(value))
        elif field == "cache_sha256":
            if not _sha256(value):
                raise RepairRetryError("repair_delta_hash_invalid", field)
        elif field == "excluded_asset_ids":
            if not _unique_strings(value) or value != sorted(value):
                raise RepairRetryError("repair_delta_assets_invalid", str(value))
        elif not _bounded_string(value):
            raise RepairRetryError("repair_delta_string_invalid", field)


def _validate_entry_semantics(entry: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    disposition = entry["disposition"]
    if disposition == "rejected_nonrepairable":
        if (
            entry["reason_code"] not in policy["non_repairable_reason_codes"]
            or entry["defect_code"] != "NON_REPAIRABLE"
            or entry["retry_class"] is not None
            or entry["action"] is not None
            or entry["attempt"] != 0
            or entry["maximum_attempts"] != 0
            or entry["next_recipe_revision"] is not None
            or entry["next_recipe_revision_id"] is not None
            or entry["delta"]
            or entry["coverage_deficit"]
        ):
            raise RepairRetryError("repair_history_rejection_invalid", entry["request_id"])
        return
    rule = policy["repair_rules"].get(entry["defect_code"])
    if (
        rule is None
        or entry["reason_code"] != rule["reason_code"]
        or entry["reason_family"] != rule["reason_family"]
        or entry["retry_class"] != rule["retry_class"]
        or entry["maximum_attempts"] != policy["retry_budgets"][rule["retry_class"]]
        or entry["quarantine_recommended"]
    ):
        raise RepairRetryError("repair_history_rule_invalid", entry["request_id"])
    if disposition == "scheduled":
        if (
            entry["action"] != rule["action"]
            or not 1 <= entry["attempt"] <= entry["maximum_attempts"]
            or entry["next_recipe_revision"] != entry["parent_recipe_revision"] + 1
            or entry["next_recipe_revision_id"] is None
            or entry["coverage_deficit"]
        ):
            raise RepairRetryError("repair_history_scheduled_invalid", entry["request_id"])
        _validate_delta(entry["defect_code"], entry["delta"], policy)
    elif disposition == "budget_exhausted":
        if (
            entry["action"] is not None
            or entry["attempt"] <= entry["maximum_attempts"]
            or entry["next_recipe_revision"] is not None
            or entry["next_recipe_revision_id"] is not None
            or entry["delta"]
            or not entry["coverage_deficit"]
        ):
            raise RepairRetryError("repair_history_exhaustion_invalid", entry["request_id"])
    else:
        raise RepairRetryError("repair_history_disposition_invalid", str(disposition))


def _history_summary(entries: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "entry_count": len(entries),
        "scheduled_count": sum(row["disposition"] == "scheduled" for row in entries),
        "rejected_count": sum(row["disposition"] == "rejected_nonrepairable" for row in entries),
        "exhausted_count": sum(row["disposition"] == "budget_exhausted" for row in entries),
        "coverage_deficit_count": sum(bool(row["coverage_deficit"]) for row in entries),
        "latest_entry_sha256": entries[-1]["entry_sha256"],
    }


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
        raise RepairRetryError("repair_document_hash_invalid", str(document[id_field]))


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
        raise RepairRetryError("repair_canonical_json_invalid", str(exc)) from exc
    return hashlib.sha256(payload).hexdigest()


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _bounded_string(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 256


def _unique_strings(values: Any) -> bool:
    return (
        isinstance(values, list)
        and bool(values)
        and len(values) == len(set(values))
        and all(_bounded_string(value) for value in values)
    )


def _scalar(value: Any, limit: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and abs(float(value)) <= limit
        and float(value) != 0
    )


def _vector(value: Any, limit: float) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 3
        and all(
            not isinstance(row, bool)
            and isinstance(row, (int, float))
            and math.isfinite(float(row))
            and abs(float(row)) <= limit
            for row in value
        )
        and any(float(row) != 0 for row in value)
    )
