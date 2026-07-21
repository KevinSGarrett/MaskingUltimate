"""Hash-bound DAZ smoke certificates, quarantine, revocation, and retest policy."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from typing import Any, Iterable, Mapping, Sequence

from ...validation import require_valid_document
from .catalog import validate_asset_compatibility_graph


class AssetQualificationError(ValueError):
    """An asset qualification artifact or transition is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def issue_asset_smoke_certificate(
    plan: Mapping[str, Any],
    result: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    graph: Mapping[str, Any],
    *,
    created_at: str,
    limitations: Sequence[str] = (),
) -> dict[str, Any]:
    """Issue authority only for an exact passing smoke result and current graph node."""

    require_valid_document(plan, "daz_asset_smoke_plan")
    require_valid_document(result, "daz_asset_smoke_result")
    validate_asset_compatibility_graph(graph)
    _validate_evaluation(evaluation, plan=plan, result=result)
    if evaluation["passed"] is not True:
        raise AssetQualificationError("certificate_smoke_not_passed", plan["asset_id"])
    nodes = {node["asset_id"]: node for node in graph["nodes"]}
    node = nodes.get(plan["asset_id"])
    if node is None or not node["generation_pool_eligible"]:
        raise AssetQualificationError("certificate_asset_not_statically_eligible", plan["asset_id"])
    if graph["graph_sha256"] != plan["dependency_snapshot_sha256"]:
        raise AssetQualificationError("certificate_dependency_snapshot_mismatch", plan["asset_id"])
    if node["asset_sha256"] != plan["asset_sha256"]:
        raise AssetQualificationError("certificate_asset_hash_mismatch", plan["asset_id"])
    if len(limitations) != len(set(limitations)) or any(
        not isinstance(value, str) or not value for value in limitations
    ):
        raise AssetQualificationError("certificate_limitations_invalid", str(limitations))
    content = {
        "asset_id": plan["asset_id"],
        "asset_sha256": plan["asset_sha256"],
        "dependency_snapshot_sha256": plan["dependency_snapshot_sha256"],
        "runtime_snapshot_sha256": plan["runtime_snapshot_sha256"],
        "script_bundle_sha256": plan["script_bundle_sha256"],
        "mapping_bundle_id": plan["mapping_bundle_id"],
        "mapping_bundle_sha256": plan["mapping_bundle_sha256"],
        "plan_id": plan["plan_id"],
        "plan_sha256": plan["plan_sha256"],
        "result_id": result["result_id"],
        "evaluation_sha256": evaluation["evaluation_sha256"],
        "fixture_ids": plan["fixture_ids"],
        "checks": {check: "pass" for check in plan["required_checks"]},
        "eligible_generations": node["figure_generations"],
        "eligible_scene_categories": node["scene_categories"],
        "limitations": sorted(limitations),
        "created_at": created_at,
        "expires_on_change": True,
    }
    digest = _canonical_sha(content)
    certificate = {
        "schema_version": "1.0.0",
        "certificate_id": f"daz_smoke_{digest[:24]}",
        "certificate_sha256": digest,
        **content,
    }
    require_valid_document(certificate, "daz_asset_smoke_certificate")
    return certificate


def validate_asset_smoke_certificate(
    certificate: Mapping[str, Any],
    graph: Mapping[str, Any],
    *,
    runtime_snapshot_sha256: str,
    script_bundle_sha256: str,
    mapping_bundle_hashes: Mapping[str, str] | None = None,
    revoked_certificate_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Return deterministic active/stale/revoked state against exact current bindings."""

    require_valid_document(certificate, "daz_asset_smoke_certificate")
    validate_asset_compatibility_graph(graph)
    reasons: list[str] = []
    content = {
        key: value
        for key, value in certificate.items()
        if key not in {"schema_version", "certificate_id", "certificate_sha256"}
    }
    expected_sha = _canonical_sha(content)
    if certificate["certificate_sha256"] != expected_sha:
        reasons.append("certificate_hash_mismatch")
    if certificate["certificate_id"] != f"daz_smoke_{expected_sha[:24]}":
        reasons.append("certificate_id_mismatch")
    if certificate["certificate_id"] in set(revoked_certificate_ids):
        reasons.append("explicitly_revoked")
    if certificate["dependency_snapshot_sha256"] != graph["graph_sha256"]:
        reasons.append("dependency_snapshot_changed")
    nodes = {node["asset_id"]: node for node in graph["nodes"]}
    node = nodes.get(certificate["asset_id"])
    if node is None:
        reasons.append("asset_removed")
    else:
        if node["asset_sha256"] != certificate["asset_sha256"]:
            reasons.append("asset_hash_changed")
        if not node["generation_pool_eligible"]:
            reasons.append("asset_statically_ineligible")
    if certificate["runtime_snapshot_sha256"] != runtime_snapshot_sha256:
        reasons.append("runtime_snapshot_changed")
    if certificate["script_bundle_sha256"] != script_bundle_sha256:
        reasons.append("script_bundle_changed")
    mapping_id = certificate["mapping_bundle_id"]
    if mapping_id is not None:
        current_mapping_hash = (mapping_bundle_hashes or {}).get(mapping_id)
        if current_mapping_hash != certificate["mapping_bundle_sha256"]:
            reasons.append("mapping_bundle_changed")
    reasons = sorted(set(reasons))
    return {
        "certificate_id": certificate["certificate_id"],
        "asset_id": certificate["asset_id"],
        "state": "active" if not reasons else "revoked_or_stale",
        "reasons": reasons,
    }


def project_active_qualified_asset_ids(
    certificates: Sequence[Mapping[str, Any]],
    graph: Mapping[str, Any],
    *,
    runtime_snapshot_sha256: str,
    script_bundle_sha256: str,
    mapping_bundle_hashes: Mapping[str, str] | None = None,
    revoked_certificate_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Project exact active certificate authority into a deterministic asset-ID set."""

    validate_asset_compatibility_graph(graph)
    certificate_ids: set[str] = set()
    asset_ids: set[str] = set()
    active = []
    excluded = []
    revoked = tuple(revoked_certificate_ids)
    for certificate in certificates:
        require_valid_document(certificate, "daz_asset_smoke_certificate")
        certificate_id = str(certificate["certificate_id"])
        if certificate_id in certificate_ids:
            raise AssetQualificationError("qualification_certificate_duplicate", certificate_id)
        certificate_ids.add(certificate_id)
        status = validate_asset_smoke_certificate(
            certificate,
            graph,
            runtime_snapshot_sha256=runtime_snapshot_sha256,
            script_bundle_sha256=script_bundle_sha256,
            mapping_bundle_hashes=mapping_bundle_hashes,
            revoked_certificate_ids=revoked,
        )
        if status["state"] == "active":
            asset_id = str(certificate["asset_id"])
            if asset_id in asset_ids:
                raise AssetQualificationError(
                    "qualification_multiple_active_certificates", asset_id
                )
            asset_ids.add(asset_id)
            active.append(
                {
                    "asset_id": asset_id,
                    "certificate_id": certificate_id,
                    "certificate_sha256": certificate["certificate_sha256"],
                }
            )
        else:
            excluded.append(status)
    content = {
        "active": sorted(active, key=lambda row: row["asset_id"]),
        "excluded": sorted(excluded, key=lambda row: row["certificate_id"]),
    }
    return {
        **content,
        "qualified_asset_ids": sorted(asset_ids),
        "projection_sha256": _canonical_sha(content),
    }


def build_asset_quarantine_record(
    plan: Mapping[str, Any],
    result: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    *,
    observed_at: str,
    log_excerpt_sha256: str,
    retry_count: int,
) -> dict[str, Any]:
    """Create one immutable reason-coded quarantine record from failed smoke evidence."""

    require_valid_document(plan, "daz_asset_smoke_plan")
    require_valid_document(result, "daz_asset_smoke_result")
    _validate_evaluation(evaluation, plan=plan, result=result)
    if evaluation["passed"] is not False or not evaluation["quarantine_codes"]:
        raise AssetQualificationError("quarantine_requires_failed_smoke", plan["asset_id"])
    _require_sha256(log_excerpt_sha256, "log_excerpt_sha256")
    if not isinstance(retry_count, int) or retry_count < 0:
        raise AssetQualificationError("quarantine_retry_count_invalid", str(retry_count))
    codes = sorted(set(evaluation["quarantine_codes"]))
    content = {
        "asset_id": plan["asset_id"],
        "asset_sha256": plan["asset_sha256"],
        "dependency_snapshot_sha256": plan["dependency_snapshot_sha256"],
        "runtime_snapshot_sha256": plan["runtime_snapshot_sha256"],
        "script_bundle_sha256": plan["script_bundle_sha256"],
        "mapping_bundle_id": plan["mapping_bundle_id"],
        "mapping_bundle_sha256": plan["mapping_bundle_sha256"],
        "plan_id": plan["plan_id"],
        "result_id": result["result_id"],
        "fixture_ids": plan["fixture_ids"],
        "quarantine_codes": codes,
        "log_excerpt_sha256": log_excerpt_sha256,
        "output_evidence_sha256": evaluation["evaluation_sha256"],
        "first_occurrence": observed_at,
        "last_occurrence": observed_at,
        "retry_count": retry_count,
        "recommended_actions": sorted({_recommended_action(code) for code in codes}),
        "state": "quarantined",
    }
    digest = _canonical_sha(content)
    record = {
        "schema_version": "1.0.0",
        "quarantine_id": f"daz_quarantine_{digest[:24]}",
        "quarantine_sha256": digest,
        **content,
    }
    require_valid_document(record, "daz_asset_quarantine")
    return record


def decide_asset_retest(
    quarantine: Mapping[str, Any],
    *,
    registry_changed: bool = False,
    content_repaired: bool = False,
    rule_or_mapping_changed: bool = False,
    suppression_documented: bool = False,
    clean_process_retries: int = 0,
) -> dict[str, Any]:
    """Apply the bounded code-specific retry/retest gates from the blueprint."""

    require_valid_document(quarantine, "daz_asset_quarantine")
    codes = set(quarantine["quarantine_codes"])
    blockers: list[str] = []
    if (
        codes
        & {"Q-ASSET-001", "Q-ASSET-002", "Q-ASSET-003", "Q-ASSET-004", "Q-ASSET-005", "Q-ASSET-022"}
        and not registry_changed
    ):
        blockers.append("registry_change_required")
    if codes & {"Q-ASSET-006", "Q-ASSET-007"} and not content_repaired:
        blockers.append("content_repair_required")
    if (
        codes
        & {
            "Q-ASSET-010",
            "Q-ASSET-011",
            "Q-ASSET-012",
            "Q-ASSET-013",
            "Q-ASSET-014",
            "Q-ASSET-015",
            "Q-ASSET-016",
            "Q-ASSET-017",
            "Q-ASSET-018",
            "Q-ASSET-019",
            "Q-ASSET-020",
        }
        and not rule_or_mapping_changed
    ):
        blockers.append("rule_mapping_or_profile_change_required")
    if "Q-ASSET-009" in codes and not suppression_documented:
        blockers.append("documented_dialog_suppression_required")
    if codes & {"Q-ASSET-008", "Q-ASSET-021"} and clean_process_retries >= 1:
        blockers.append("clean_process_retry_exhausted")
    blockers = sorted(set(blockers))
    return {
        "quarantine_id": quarantine["quarantine_id"],
        "asset_id": quarantine["asset_id"],
        "decision": "eligible_for_retest" if not blockers else "retest_blocked",
        "blockers": blockers,
        "next_clean_process_retry": clean_process_retries + 1 if not blockers else None,
    }


def build_asset_change_impact(
    graph: Mapping[str, Any],
    certificates: Sequence[Mapping[str, Any]],
    queued_recipes: Sequence[Mapping[str, Any]],
    *,
    changed_asset_ids: Iterable[str] = (),
    changed_plugin_ids: Iterable[str] = (),
    runtime_snapshot_sha256: str,
    script_bundle_sha256: str,
    mapping_bundle_hashes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Revoke changed/dependent certificates and block their already queued recipes."""

    validate_asset_compatibility_graph(graph)
    nodes = {node["asset_id"]: node for node in graph["nodes"]}
    changed_assets = set(changed_asset_ids)
    affected = set(changed_assets)
    changed_plugins = set(changed_plugin_ids)
    affected.update(
        node["asset_id"]
        for node in graph["nodes"]
        if changed_plugins.intersection(node["required_plugins"])
    )
    reverse_dependencies: dict[str, set[str]] = {}
    for edge in graph["edges"]:
        if edge["resolved"]:
            reverse_dependencies.setdefault(edge["target_asset_id"], set()).add(
                edge["source_asset_id"]
            )
    pending = deque(sorted(affected))
    while pending:
        changed = pending.popleft()
        for dependent in sorted(reverse_dependencies.get(changed, ())):
            if dependent not in affected:
                affected.add(dependent)
                pending.append(dependent)

    revoked = []
    for certificate in certificates:
        status = validate_asset_smoke_certificate(
            certificate,
            graph,
            runtime_snapshot_sha256=runtime_snapshot_sha256,
            script_bundle_sha256=script_bundle_sha256,
            mapping_bundle_hashes=mapping_bundle_hashes,
        )
        reasons = set(status["reasons"])
        if certificate["asset_id"] in affected:
            reasons.add(
                "asset_or_dependency_changed"
                if certificate["asset_id"] not in changed_assets
                else "asset_changed"
            )
        if reasons:
            revoked.append(
                {
                    "certificate_id": certificate["certificate_id"],
                    "asset_id": certificate["asset_id"],
                    "reasons": sorted(reasons),
                }
            )
    revoked_assets = {row["asset_id"] for row in revoked}
    blocked_recipes = []
    for recipe in queued_recipes:
        require_valid_document(recipe, "daz_scene_recipe")
        payload = recipe["payload"]
        asset_id = payload.get("asset_id")
        if asset_id in revoked_assets:
            blocked_recipes.append(
                {
                    "recipe_id": recipe["recipe_id"],
                    "asset_id": asset_id,
                    "reason": "qualification_certificate_revoked",
                }
            )
    content = {
        "changed_asset_ids": sorted(changed_assets),
        "changed_plugin_ids": sorted(changed_plugins),
        "affected_asset_ids": sorted(asset_id for asset_id in affected if asset_id in nodes),
        "revoked_certificates": sorted(revoked, key=lambda row: row["certificate_id"]),
        "blocked_recipes": sorted(blocked_recipes, key=lambda row: row["recipe_id"]),
    }
    return {
        **content,
        "impact_sha256": _canonical_sha(content),
    }


def _validate_evaluation(
    evaluation: Mapping[str, Any], *, plan: Mapping[str, Any], result: Mapping[str, Any]
) -> None:
    required = {
        "schema_version",
        "plan_id",
        "result_id",
        "issues",
        "quarantine_codes",
        "evaluation_sha256",
        "passed",
    }
    if set(evaluation) != required:
        raise AssetQualificationError("smoke_evaluation_shape_invalid", str(sorted(evaluation)))
    content = {
        "plan_id": evaluation["plan_id"],
        "result_id": evaluation["result_id"],
        "issues": evaluation["issues"],
        "quarantine_codes": evaluation["quarantine_codes"],
    }
    if evaluation["schema_version"] != "1.0.0" or evaluation["evaluation_sha256"] != _canonical_sha(
        content
    ):
        raise AssetQualificationError("smoke_evaluation_hash_invalid", plan["asset_id"])
    if evaluation["plan_id"] != plan["plan_id"] or evaluation["result_id"] != result["result_id"]:
        raise AssetQualificationError("smoke_evaluation_binding_invalid", plan["asset_id"])
    if (
        not isinstance(evaluation["issues"], list)
        or not isinstance(evaluation["quarantine_codes"], list)
        or len(evaluation["issues"]) != len(set(evaluation["issues"]))
        or len(evaluation["quarantine_codes"]) != len(set(evaluation["quarantine_codes"]))
    ):
        raise AssetQualificationError("smoke_evaluation_values_invalid", plan["asset_id"])
    if evaluation["passed"] != (not evaluation["issues"]):
        raise AssetQualificationError("smoke_evaluation_outcome_invalid", plan["asset_id"])
    if evaluation["passed"] and evaluation["quarantine_codes"]:
        raise AssetQualificationError("smoke_evaluation_outcome_invalid", plan["asset_id"])


def _recommended_action(code: str) -> str:
    mapping = {
        "Q-ASSET-001": "classify_asset_and_refresh_registry",
        "Q-ASSET-002": "install_or_resolve_dependency_then_refresh_registry",
        "Q-ASSET-003": "resolve_content_hash_conflict",
        "Q-ASSET-004": "update_generation_compatibility_or_exclude",
        "Q-ASSET-005": "install_pin_or_remove_plugin_requirement",
        "Q-ASSET-006": "repair_external_content_path",
        "Q-ASSET-007": "repair_missing_texture",
        "Q-ASSET-008": "one_clean_process_retry",
        "Q-ASSET-009": "document_suppression_or_exclude",
        "Q-ASSET-010": "pin_or_repair_render_profile",
        "Q-ASSET-011": "create_new_topology_mapping_or_exclude",
        "Q-ASSET-012": "add_asset_specific_geometry_rule_or_exclude",
        "Q-ASSET-013": "add_asset_specific_fit_rule_or_exclude",
        "Q-ASSET-014": "repair_fit_follow_rule_or_exclude",
        "Q-ASSET-015": "create_or_repair_mapping_bundle",
        "Q-ASSET-016": "repair_alpha_policy_or_exclude",
        "Q-ASSET-017": "run_three_seed_two_process_investigation",
        "Q-ASSET-018": "register_supported_character_configuration",
        "Q-ASSET-019": "register_anatomy_configuration_and_mapping",
        "Q-ASSET-020": "change_replay_profile_or_exclude",
        "Q-ASSET-021": "one_clean_process_retry",
        "Q-ASSET-022": "resolve_duplicate_or_shadow_identity",
    }
    try:
        return mapping[code]
    except KeyError as exc:
        raise AssetQualificationError("quarantine_code_unknown", code) from exc


def _require_sha256(value: object, field: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AssetQualificationError("qualification_hash_invalid", field)


def _canonical_sha(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


__all__ = [
    "AssetQualificationError",
    "build_asset_change_impact",
    "build_asset_quarantine_record",
    "decide_asset_retest",
    "issue_asset_smoke_certificate",
    "project_active_qualified_asset_ids",
    "validate_asset_smoke_certificate",
]
