"""Type-specific DAZ asset smoke plans and repeatability result validation."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from ...validation import require_valid_document

SHA256_PATTERN = "0123456789abcdef"
SEMANTIC_REPEATABILITY_ROLES = ("silhouette", "instance_id", "mapping_pass")


class AssetSmokeError(ValueError):
    """A smoke policy, plan, binding, or result is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_asset_smoke_policy(path: Path, *, asset_classes: Iterable[str]) -> dict[str, Any]:
    policy = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_asset_smoke_policy(policy, asset_classes=asset_classes)
    return policy


def validate_asset_smoke_policy(policy: Mapping[str, Any], *, asset_classes: Iterable[str]) -> None:
    if policy.get("schema_version") != "1.0.0" or policy.get("policy_version") != "1.0.0":
        raise AssetSmokeError("smoke_policy_version_invalid", "versions must be 1.0.0")
    if policy.get("repetitions") != 2 or policy.get("separate_process_per_repetition") is not True:
        raise AssetSmokeError(
            "smoke_repeatability_policy_invalid",
            "exactly two separate-process repetitions required",
        )
    for field in ("required_artifact_roles", "universal_checks"):
        values = policy.get(field)
        if (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(values))
            or any(not isinstance(value, str) or not value for value in values)
        ):
            raise AssetSmokeError("smoke_policy_values_invalid", field)
    profiles = policy.get("profiles")
    if not isinstance(profiles, Mapping) or not profiles:
        raise AssetSmokeError("smoke_profiles_invalid", "profiles missing")
    covered = []
    for profile_id, profile in profiles.items():
        if not isinstance(profile_id, str) or not isinstance(profile, Mapping):
            raise AssetSmokeError("smoke_profiles_invalid", str(profile_id))
        for field in ("asset_classes", "fixture_ids", "checks"):
            values = profile.get(field)
            if (
                not isinstance(values, list)
                or not values
                or len(values) != len(set(values))
                or any(not isinstance(value, str) or not value for value in values)
            ):
                raise AssetSmokeError("smoke_profiles_invalid", f"{profile_id}:{field}")
        covered.extend(profile["asset_classes"])
    expected = sorted(set(asset_classes) - {"unknown"})
    if sorted(covered) != expected or len(covered) != len(set(covered)):
        raise AssetSmokeError(
            "smoke_profile_coverage_invalid",
            "every non-unknown class must occur in exactly one profile",
        )
    quarantine = policy.get("quarantine_codes")
    expected_codes = [f"Q-ASSET-{index:03d}" for index in range(1, 23)]
    if (
        not isinstance(quarantine, Mapping)
        or sorted(quarantine.values()) != expected_codes
        or len(quarantine) != 22
    ):
        raise AssetSmokeError(
            "smoke_quarantine_taxonomy_invalid", "exact Q-ASSET-001..022 coverage required"
        )


def build_asset_smoke_plan(
    graph: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    asset_id: str,
    created_at: str,
    bundle_version: str,
    runtime_snapshot_sha256: str,
    script_bundle_sha256: str,
    content_directories: tuple[Path, Path],
    mapping_bundle_id: str | None = None,
    mapping_bundle_sha256: str | None = None,
) -> dict[str, Any]:
    """Build two clean-process worker recipes for one statically eligible asset."""

    require_valid_document(graph, "daz_asset_compatibility_graph")
    classes = {
        str(asset_class)
        for profile in policy["profiles"].values()
        for asset_class in profile["asset_classes"]
    }
    classes.add("unknown")
    validate_asset_smoke_policy(policy, asset_classes=classes)
    nodes = {str(node["asset_id"]): node for node in graph["nodes"]}
    node = nodes.get(asset_id)
    if node is None:
        raise AssetSmokeError("smoke_asset_missing", asset_id)
    if not node["generation_pool_eligible"] or node["qualified"]:
        raise AssetSmokeError(
            "smoke_asset_not_statically_eligible", f"{asset_id}:{node['static_state']}"
        )
    for value, field in (
        (graph["graph_sha256"], "dependency_snapshot_sha256"),
        (runtime_snapshot_sha256, "runtime_snapshot_sha256"),
        (script_bundle_sha256, "script_bundle_sha256"),
    ):
        _require_sha256(value, field)
    mapping_required = node["mapping_requirement"] != "none"
    if mapping_required and (
        not isinstance(mapping_bundle_id, str)
        or not mapping_bundle_id
        or mapping_bundle_sha256 is None
    ):
        raise AssetSmokeError("smoke_mapping_binding_missing", f"mapping required for {asset_id}")
    if mapping_bundle_sha256 is not None:
        _require_sha256(mapping_bundle_sha256, "mapping_bundle_sha256")
    profile_id, profile = _profile_for_class(policy, str(node["primary_asset_class"]))
    required_checks = sorted(set(policy["universal_checks"]) | set(profile["checks"]))
    directories = [str(Path(path).resolve(strict=True)) for path in content_directories]
    if len(set(map(str.casefold, directories))) != 2:
        raise AssetSmokeError(
            "smoke_content_directories_invalid", "exactly two distinct content directories required"
        )
    content = {
        "created_at": created_at,
        "bundle_version": bundle_version,
        "content_directories": directories,
        "graph_id": graph["graph_id"],
        "dependency_snapshot_sha256": graph["graph_sha256"],
        "asset_id": asset_id,
        "asset_sha256": node["asset_sha256"],
        "profile_id": profile_id,
        "fixture_ids": list(profile["fixture_ids"]),
        "required_checks": required_checks,
        "required_artifact_roles": list(policy["required_artifact_roles"]),
        "runtime_snapshot_sha256": runtime_snapshot_sha256,
        "script_bundle_sha256": script_bundle_sha256,
        "mapping_bundle_id": mapping_bundle_id,
        "mapping_bundle_sha256": mapping_bundle_sha256,
        "repetitions": 2,
    }
    digest = _canonical_sha(content)
    plan_id = f"dsmk_{digest[:24]}"
    recipes = []
    for repetition in (1, 2):
        recipe = {
            "schema_version": "1.0.0",
            "job_id": f"{plan_id}_r{repetition}",
            "recipe_id": f"{plan_id}_recipe_r{repetition}",
            "created_at": created_at,
            "bundle_version": bundle_version,
            "operation": "asset_smoke",
            "requires_gpu": True,
            "content_directories": directories,
            "payload": {
                **content,
                "plan_id": plan_id,
                "repetition": repetition,
                "clean_process_required": True,
            },
        }
        require_valid_document(recipe, "daz_scene_recipe")
        recipes.append(recipe)
    plan = {
        "schema_version": "1.0.0",
        "plan_id": plan_id,
        "plan_sha256": digest,
        "created_at": created_at,
        "bundle_version": bundle_version,
        "content_directories": directories,
        **content,
        "recipes": recipes,
    }
    require_valid_document(plan, "daz_asset_smoke_plan")
    return plan


def evaluate_asset_smoke_result(
    plan: Mapping[str, Any], result: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate exact bindings, all checks, artifacts, and cross-process semantic replay."""

    require_valid_document(plan, "daz_asset_smoke_plan")
    require_valid_document(result, "daz_asset_smoke_result")
    issues: list[str] = []
    quarantine_codes: set[str] = set()
    for field in (
        "plan_id",
        "plan_sha256",
        "asset_id",
        "asset_sha256",
        "dependency_snapshot_sha256",
        "runtime_snapshot_sha256",
        "script_bundle_sha256",
        "mapping_bundle_id",
        "mapping_bundle_sha256",
    ):
        if result.get(field) != plan.get(field):
            issues.append(f"binding_mismatch:{field}")
    executions = result["executions"]
    if len(executions) != plan["repetitions"]:
        issues.append(f"execution_count:{len(executions)}!={plan['repetitions']}")
    repetitions = [int(execution["repetition"]) for execution in executions]
    if sorted(repetitions) != list(range(1, int(plan["repetitions"]) + 1)):
        issues.append("execution_repetitions_invalid")
        quarantine_codes.add(policy["quarantine_codes"]["repeatability_failure"])
    process_identities = [str(execution["process_identity"]) for execution in executions]
    if len(process_identities) != len(set(process_identities)):
        issues.append("separate_process_repetition_missing")
        quarantine_codes.add(policy["quarantine_codes"]["repeatability_failure"])
    expected_checks = set(plan["required_checks"])
    expected_artifacts = set(plan["required_artifact_roles"])
    artifact_hashes: dict[str, list[str]] = {role: [] for role in expected_artifacts}
    for execution in executions:
        repetition = int(execution["repetition"])
        checks = execution["checks"]
        if set(checks) != expected_checks:
            issues.append(f"check_coverage:{repetition}")
        for check in sorted(expected_checks):
            if checks.get(check) != "pass":
                issues.append(f"check_failed:{repetition}:{check}:{checks.get(check)}")
                quarantine_codes.add(_quarantine_for_check(check, policy))
        artifacts = {str(row["role"]): row for row in execution["artifacts"]}
        if len(artifacts) != len(execution["artifacts"]):
            issues.append(f"artifact_duplicate:{repetition}")
        if set(artifacts) != expected_artifacts:
            issues.append(f"artifact_coverage:{repetition}")
        for role in sorted(expected_artifacts):
            artifact = artifacts.get(role)
            if artifact is None:
                continue
            artifact_hashes[role].append(str(artifact["sha256"]))
        if execution["dialog_count"] != 0:
            issues.append(f"unexpected_dialog:{repetition}")
            quarantine_codes.add(policy["quarantine_codes"]["unexpected_dialog"])
        if execution["fatal_log_count"] != 0:
            issues.append(f"fatal_log:{repetition}")
            quarantine_codes.add(policy["quarantine_codes"]["load_error"])
    for role in SEMANTIC_REPEATABILITY_ROLES:
        hashes = artifact_hashes.get(role, [])
        if len(hashes) != plan["repetitions"] or len(set(hashes)) != 1:
            issues.append(f"semantic_hash_drift:{role}")
            quarantine_codes.add(policy["quarantine_codes"]["repeatability_failure"])
    unique_issues = sorted(set(issues))
    evaluation_content = {
        "plan_id": plan["plan_id"],
        "result_id": result["result_id"],
        "issues": unique_issues,
        "quarantine_codes": sorted(quarantine_codes),
    }
    return {
        "schema_version": "1.0.0",
        **evaluation_content,
        "evaluation_sha256": _canonical_sha(evaluation_content),
        "passed": not unique_issues,
    }


def publish_asset_smoke_document(
    document: Mapping[str, Any], output_root: Path, *, document_id: str
) -> tuple[Path, bool]:
    """Atomically publish one immutable smoke plan or evaluation document."""

    if not isinstance(document_id, str) or not document_id:
        raise AssetSmokeError("smoke_document_id_invalid", str(document_id))
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{document_id}.json"
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise AssetSmokeError("smoke_immutable_publication_conflict", str(target))
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


def _profile_for_class(
    policy: Mapping[str, Any], primary_asset_class: str
) -> tuple[str, Mapping[str, Any]]:
    matches = [
        (str(profile_id), profile)
        for profile_id, profile in policy["profiles"].items()
        if primary_asset_class in profile["asset_classes"]
    ]
    if len(matches) != 1:
        raise AssetSmokeError("smoke_profile_missing", f"{primary_asset_class}:{len(matches)}")
    return matches[0]


def _quarantine_for_check(check: str, policy: Mapping[str, Any]) -> str:
    mapping = (
        (("dependencies",), "missing_dependency"),
        (("plugins",), "required_plugin_missing"),
        (("external_roots",), "external_path_reference"),
        (("texture", "maps_resolved"), "missing_texture"),
        (("dialog",), "unexpected_dialog"),
        (("renderer_profile", "render_settings", "output_path"), "renderer_profile_mutation"),
        (("topology",), "topology_changed_unmapped"),
        (("finite", "geometry_integrity"), "geometry_nan_or_explosion"),
        (("intersection", "penetration"), "excessive_intersection"),
        (("fit_follow", "attachment"), "fit_or_follow_failure"),
        (("mapping",), "mapping_incomplete"),
        (("alpha",), "alpha_mask_unreliable"),
        (("simulation",), "simulation_nondeterministic"),
        (("repeatability",), "repeatability_failure"),
    )
    for needles, reason in mapping:
        if any(needle in check for needle in needles):
            return str(policy["quarantine_codes"][reason])
    return str(policy["quarantine_codes"]["load_error"])


def _require_sha256(value: object, field: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in SHA256_PATTERN for character in value)
    ):
        raise AssetSmokeError("smoke_hash_invalid", field)


def _canonical_sha(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


__all__ = [
    "AssetSmokeError",
    "build_asset_smoke_plan",
    "evaluate_asset_smoke_result",
    "load_asset_smoke_policy",
    "publish_asset_smoke_document",
    "validate_asset_smoke_policy",
]
