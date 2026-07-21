"""Producer-side verifier for the external Main `MaskFactoryAdapter` boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

from maskfactory.validation import canonical_document_sha256

POLICY_PATH = (
    Path(__file__).parents[3] / "configs" / "bridge_external_adapter_conformance_policy.yaml"
)
SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "external_adapter_conformance_evidence.schema.json"
)
POLICY_ID = "maskfactory-bridge-external-adapter-conformance-v1"


class ExternalAdapterConformanceError(ValueError):
    """Raised when conformance inputs or policy material are unusable."""


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ExternalAdapterConformanceError(
            "external adapter conformance policy unavailable"
        ) from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise ExternalAdapterConformanceError("unexpected external adapter conformance policy")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise ExternalAdapterConformanceError("external adapter conformance policy hash mismatch")
    return dict(policy)


def _strings(values: object) -> set[str]:
    return (
        {value for value in values if isinstance(value, str)} if isinstance(values, list) else set()
    )


def _disallowed_imports(policy: Mapping[str, Any], imports: set[str]) -> set[str]:
    allowed = tuple(_strings(policy.get("allowed_maskfactory_import_prefixes")))
    forbidden = tuple(_strings(policy.get("forbidden_maskfactory_import_prefixes")))
    disallowed: set[str] = set()
    for name in imports:
        if not name.startswith("maskfactory."):
            continue
        if any(name.startswith(prefix) for prefix in forbidden):
            disallowed.add(name)
            continue
        if not any(name.startswith(prefix) for prefix in allowed):
            disallowed.add(name)
    return disallowed


def _mutable_path_coupling(policy: Mapping[str, Any], paths: set[str]) -> bool:
    fragments = tuple(value.lower() for value in _strings(policy.get("forbidden_path_fragments")))
    for path in paths:
        normalized = path.replace("\\", "/").lower()
        if normalized.startswith("/") or ":/" in normalized:
            return True
        if ".." in normalized.split("/"):
            return True
        if any(fragment in normalized for fragment in fragments):
            return True
    return False


def _wire_schema_versions(wire_schemas: object) -> dict[str, str]:
    if not isinstance(wire_schemas, list):
        return {}
    rows = [row for row in wire_schemas if isinstance(row, Mapping)]
    names = [row.get("name") for row in rows]
    if len(names) != len(set(names)):
        return {}
    return {
        str(row.get("name")): str(row.get("version"))
        for row in rows
        if isinstance(row.get("name"), str) and isinstance(row.get("version"), str)
    }


def build_external_adapter_conformance_evidence(
    observation: Mapping[str, Any], *, decided_at: str
) -> dict[str, Any]:
    """Derive a fail-closed conformance decision from adapter observations."""
    policy = _policy()
    reasons: list[str] = []

    adapter = observation.get("adapter_identity")
    adapter = adapter if isinstance(adapter, Mapping) else {}
    producer_state = observation.get("producer_state")
    producer_state = producer_state if isinstance(producer_state, Mapping) else {}
    bindings = observation.get("contract_bindings")
    bindings = bindings if isinstance(bindings, Mapping) else {}
    boundary = observation.get("boundary_observations")
    boundary = boundary if isinstance(boundary, Mapping) else {}

    if adapter.get("repository_clean") is not True:
        reasons.append("adapter_dirty_worktree")
    if adapter.get("install_mode") in {"editable", "path"}:
        reasons.append("adapter_editable_install")
    if producer_state.get("repository_clean") is not True:
        reasons.append("producer_dirty_worktree")
    if producer_state.get("release_status") not in _strings(policy.get("required_release_states")):
        reasons.append("producer_release_not_adopted")
    if producer_state.get("adoption_decision") not in _strings(
        policy.get("required_adoption_decisions")
    ):
        reasons.append("producer_release_not_adopted")

    for field, expected in (policy.get("adopted_contract_versions") or {}).items():
        if bindings.get(field) != expected:
            reasons.append("adopted_contract_version_mismatch")
            break

    observed_wire_versions = _wire_schema_versions(bindings.get("wire_schemas"))
    expected_wire_versions = {
        str(name): str(version)
        for name, version in (policy.get("adopted_wire_schema_versions") or {}).items()
    }
    if observed_wire_versions != expected_wire_versions:
        reasons.append("adopted_wire_schema_version_mismatch")

    used_paths = _strings(bindings.get("used_openapi_paths"))
    allowed_paths = _strings(policy.get("allowed_openapi_paths"))
    if not used_paths or not used_paths.issubset(allowed_paths):
        reasons.append("endpoint_not_published")

    imports = _strings(boundary.get("imports"))
    documented = _strings(boundary.get("documented_dependencies"))
    internal = {name for name in imports if name.startswith("maskfactory.")}
    if _disallowed_imports(policy, imports):
        reasons.append("adapter_internal_dependency")
    if {name for name in internal if name not in documented}:
        reasons.append("adapter_internal_dependency")

    observed_node_ids = _strings(boundary.get("comfyui_node_ids"))
    forbidden_node_markers = _strings(policy.get("forbidden_comfyui_node_ids"))
    if observed_node_ids or forbidden_node_markers & imports:
        reasons.append("adapter_node_id_coupling")

    mutable_paths = _strings(boundary.get("mutable_path_dependencies"))
    if _mutable_path_coupling(policy, mutable_paths):
        reasons.append("adapter_mutable_path_dependency")

    reason_order = [code for code in policy["rejection_reason_codes"] if code in set(reasons)]
    evidence = {
        "schema_version": "1.0.0",
        "record_type": "external_adapter_conformance_evidence",
        "decided_at": decided_at,
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "adapter_identity": {
            "package_name": adapter.get("package_name"),
            "package_version": adapter.get("package_version"),
            "package_sha256": adapter.get("package_sha256"),
            "git_commit": adapter.get("git_commit"),
            "git_tree": adapter.get("git_tree"),
            "repository_clean": adapter.get("repository_clean"),
            "install_mode": adapter.get("install_mode"),
        },
        "producer_state": {
            "release_status": producer_state.get("release_status"),
            "adoption_decision": producer_state.get("adoption_decision"),
            "repository_clean": producer_state.get("repository_clean"),
        },
        "contract_bindings": {
            "bridge_contract": bindings.get("bridge_contract"),
            "api_contract": bindings.get("api_contract"),
            "package_format": bindings.get("package_format"),
            "ontology_version": bindings.get("ontology_version"),
            "node_pack_version": bindings.get("node_pack_version"),
            "wire_schemas": sorted(
                [
                    {"name": name, "version": version}
                    for name, version in observed_wire_versions.items()
                ],
                key=lambda row: row["name"],
            ),
            "used_openapi_paths": sorted(used_paths),
        },
        "boundary_observations": {
            "imports": sorted(imports),
            "documented_dependencies": sorted(documented),
            "comfyui_node_ids": sorted(observed_node_ids),
            "mutable_path_dependencies": sorted(mutable_paths),
        },
        "status": "accepted" if not reason_order else "rejected",
        "rejection_reasons": reason_order,
        "decision_sha256": "",
    }
    evidence["decision_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("decision_sha256",)
    )
    return evidence


def validate_external_adapter_conformance_evidence(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate schema, policy binding, canonical hash, and status/reason coherence."""
    issues: list[str] = []
    try:
        policy = _policy()
    except ExternalAdapterConformanceError as exc:
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
    allowed_codes = _strings(policy.get("rejection_reason_codes"))
    reasons = _strings(evidence.get("rejection_reasons"))
    if not reasons.issubset(allowed_codes):
        issues.append("decision_reason_code")
    if evidence.get("status") == "accepted" and reasons:
        issues.append("decision_status_reasons")
    if evidence.get("status") == "rejected" and not reasons:
        issues.append("decision_status_reasons")
    return tuple(sorted(set(issues)))


__all__ = [
    "ExternalAdapterConformanceError",
    "build_external_adapter_conformance_evidence",
    "validate_external_adapter_conformance_evidence",
]
