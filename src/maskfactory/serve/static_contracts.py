"""STATIC_PASS serving/ComfyUI contracts that need no Main adoption or champions.

Covers:
- closed source node-pack inventory hashes
- serving_provenance schema + redaction enforcement
- serving_route authority firewall
- frozen workflow preflight contract binding

Never claims Mode B predict, Main bridge, doctor-green, or production release install.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..validation import validate_document
from .workflow_performance import (
    CASE_IDS,
    DEFAULT_POLICY,
    LOCKED_POLICY_SHA256,
    ROLLBACK_ROLES,
    canonical_sha256,
    file_sha256,
    load_policy,
)
from .workflow_preflight import AUTHORITY as PREFLIGHT_AUTHORITY

ROOT = Path(__file__).resolve().parents[3]
SERVE_DIR = Path(__file__).resolve().parent
SOURCE_NODE_MODULE = SERVE_DIR / "comfy_export.py"
SOURCE_WORKFLOWS_DIR = SERVE_DIR / "maskfactory_nodes" / "workflows"
INVENTORY_FILENAME = "node_pack_inventory.json"

PROOF_TIER = "STATIC_PASS"
AUTHORITY = (
    "serving_static_contracts_only_no_mode_b_predict_main_adoption_"
    "champion_or_production_release_authority"
)
SCHEMA_VERSION = "1.0.0"

REQUIRED_WORKFLOWS: tuple[str, ...] = (
    "wf_bodypart_conditioned.json",
    "wf_inpaint_gold_hand.json",
    "wf_live_predict_inpaint.json",
    "wf_multi_instance_p1.json",
    "wf_person_index_default_p0.json",
    "wf_v2_anatomy_selector.json",
    "wf_v2_clothed_negative_guard.json",
)

_FORBIDDEN_PROVENANCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)https?://"),
    re.compile(r"(?i)[A-Za-z]:\\"),
    re.compile(r"(?i)/home/|/Users/|/mnt/"),
    re.compile(r"(?i)(api[_-]?key|password|secret|token|credential)"),
    re.compile(r"(?i)\.pth|\.safetensors|\.ckpt"),
    re.compile(r"(?i)license text|copyright notice"),
)

_OVERCLAIM_KEYS = frozenset(
    {
        "mode_b_predict_complete",
        "main_adoption_complete",
        "main_bridge_complete",
        "production_release_installed",
        "champion_backed_predict",
        "doctor_green",
        "human_approved_gold",
        "authoritative_human_gold",
    }
)


class ServingStaticContractError(ValueError):
    """A STATIC serving/ComfyUI contract drifted or overclaimed authority."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        rows: list[str] = []
        for key, nested in value.items():
            rows.extend(_walk_strings(str(key)))
            rows.extend(_walk_strings(nested))
        return rows
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        rows = []
        for nested in value:
            rows.extend(_walk_strings(nested))
        return rows
    return []


def build_source_node_pack_inventory() -> dict[str, Any]:
    """Build a closed hash inventory for the source dependency-light node pack."""
    if not SOURCE_NODE_MODULE.is_file():
        raise ServingStaticContractError(f"missing node module: {SOURCE_NODE_MODULE}")
    if not SOURCE_WORKFLOWS_DIR.is_dir():
        raise ServingStaticContractError(f"missing workflows dir: {SOURCE_WORKFLOWS_DIR}")

    workflow_paths = sorted(SOURCE_WORKFLOWS_DIR.glob("*.json"))
    found = tuple(path.name for path in workflow_paths)
    if found != REQUIRED_WORKFLOWS:
        raise ServingStaticContractError(
            "workflow inventory drift: " f"expected {list(REQUIRED_WORKFLOWS)} found {list(found)}"
        )

    files: list[dict[str, Any]] = [
        {
            "relative_path": "__init__.py",
            "role": "node_module",
            "sha256": file_sha256(SOURCE_NODE_MODULE),
            "size_bytes": SOURCE_NODE_MODULE.stat().st_size,
            "source_path": "src/maskfactory/serve/comfy_export.py",
        }
    ]
    for path in workflow_paths:
        files.append(
            {
                "relative_path": f"workflows/{path.name}",
                "role": "workflow",
                "sha256": file_sha256(path),
                "size_bytes": path.stat().st_size,
                "source_path": ("src/maskfactory/serve/maskfactory_nodes/workflows/" + path.name),
            }
        )

    core = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "maskfactory_node_pack_inventory",
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "inventory_kind": "source_tree",
        "closed_manifest": True,
        "node_pack_version": "1.0.0",
        "required_workflows": list(REQUIRED_WORKFLOWS),
        "file_count": len(files),
        "files": files,
        "mode_b_predict_complete": False,
        "main_adoption_complete": False,
        "production_release_installed": False,
        "editable_source_install_authority": False,
    }
    inventory_sha256 = canonical_sha256(core)
    return {
        **core,
        "inventory_sha256": inventory_sha256,
        "sha256": inventory_sha256,
    }


def write_installed_node_pack_inventory(target: Path) -> dict[str, Any]:
    """Write a closed inventory next to an installed developer node pack."""
    target = Path(target).resolve()
    source = build_source_node_pack_inventory()
    installed_files: list[dict[str, Any]] = []
    for row in source["files"]:
        relative = str(row["relative_path"])
        path = target / relative
        if not path.is_file():
            raise ServingStaticContractError(f"installed node-pack missing {relative}")
        digest = file_sha256(path)
        if digest != row["sha256"]:
            raise ServingStaticContractError(
                f"installed hash drift for {relative}: {digest} != {row['sha256']}"
            )
        installed_files.append(
            {
                "relative_path": relative,
                "role": row["role"],
                "sha256": digest,
                "size_bytes": path.stat().st_size,
            }
        )
    core = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "maskfactory_node_pack_inventory",
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "inventory_kind": "installed_developer_copy",
        "closed_manifest": True,
        "node_pack_version": source["node_pack_version"],
        "required_workflows": list(REQUIRED_WORKFLOWS),
        "source_inventory_sha256": source["inventory_sha256"],
        "file_count": len(installed_files),
        "files": installed_files,
        "mode_b_predict_complete": False,
        "main_adoption_complete": False,
        "production_release_installed": False,
        "editable_source_install_authority": False,
        "stale_unmanifested_files_allowed": False,
    }
    inventory_sha256 = canonical_sha256(core)
    document = {
        **core,
        "inventory_sha256": inventory_sha256,
        "sha256": inventory_sha256,
    }
    path = target / INVENTORY_FILENAME
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


def verify_installed_node_pack_inventory(target: Path) -> dict[str, Any]:
    """Fail closed if an installed tree drifts from the sealed inventory."""
    target = Path(target).resolve()
    inventory_path = target / INVENTORY_FILENAME
    if not inventory_path.is_file():
        raise ServingStaticContractError(f"missing {INVENTORY_FILENAME}")
    try:
        document = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ServingStaticContractError(f"unreadable inventory: {exc}") from exc
    if not isinstance(document, Mapping):
        raise ServingStaticContractError("inventory must be a JSON object")

    for key in _OVERCLAIM_KEYS:
        if document.get(key) is True:
            raise ServingStaticContractError(f"inventory overclaim refused: {key}=true")

    expected = {str(row["relative_path"]): row for row in document.get("files", ())}
    if set(expected) != {
        "__init__.py",
        *(f"workflows/{name}" for name in REQUIRED_WORKFLOWS),
    }:
        raise ServingStaticContractError("inventory file set is not the closed required set")

    observed: dict[str, dict[str, Any]] = {}
    for path in sorted(target.rglob("*"), key=lambda value: value.as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(target).as_posix()
        if relative == INVENTORY_FILENAME or relative == "config.json":
            continue
        observed[relative] = {
            "sha256": file_sha256(path),
            "size_bytes": path.stat().st_size,
        }

    extras = sorted(set(observed) - set(expected))
    missing = sorted(set(expected) - set(observed))
    if extras:
        raise ServingStaticContractError("stale_unmanifested_files: " + ", ".join(extras))
    if missing:
        raise ServingStaticContractError("missing_manifested_files: " + ", ".join(missing))

    for relative, row in expected.items():
        actual = observed[relative]
        if actual["sha256"] != row["sha256"]:
            raise ServingStaticContractError(f"hash_mismatch:{relative}")
        if int(actual["size_bytes"]) != int(row["size_bytes"]):
            raise ServingStaticContractError(f"size_mismatch:{relative}")

    body = {
        key: value for key, value in document.items() if key not in {"sha256", "inventory_sha256"}
    }
    expected_seal = canonical_sha256(body)
    if document.get("inventory_sha256") != expected_seal or document.get("sha256") != expected_seal:
        raise ServingStaticContractError("inventory seal mismatch")

    return {
        "status": "pass",
        "proof_tier": PROOF_TIER,
        "inventory_sha256": document["inventory_sha256"],
        "file_count": len(expected),
        "stale_unmanifested_files": False,
        "mode_b_predict_complete": False,
        "main_adoption_complete": False,
        "production_release_installed": False,
    }


def enforce_serving_provenance(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate serving_provenance schema and refuse path/credential leakage."""
    payload = dict(document)
    issues = validate_document(payload, "serving_provenance")
    if issues:
        detail = "; ".join(f"{issue.pointer or '/'} {issue.message}" for issue in issues)
        raise ServingStaticContractError(f"serving_provenance schema invalid: {detail}")

    if payload.get("truth_tier") != "machine_candidate":
        raise ServingStaticContractError("Mode B provenance truth_tier must be machine_candidate")
    if payload.get("certification", {}).get("status") != "not_certified":
        raise ServingStaticContractError("Mode B provenance cannot claim certification")
    if payload.get("routing", {}).get("destination") != "review_draft":
        raise ServingStaticContractError("Mode B provenance must route to review_draft")

    for text in _walk_strings(payload):
        for pattern in _FORBIDDEN_PROVENANCE_PATTERNS:
            if pattern.search(text):
                raise ServingStaticContractError(
                    f"serving_provenance redaction failure: matched {pattern.pattern!r}"
                )
    return payload


def enforce_serving_route_static(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate serving_route schema and authority firewall invariants."""
    payload = dict(document)
    issues = validate_document(payload, "serving_route")
    if issues:
        detail = "; ".join(f"{issue.pointer or '/'} {issue.message}" for issue in issues)
        raise ServingStaticContractError(f"serving_route schema invalid: {detail}")

    if payload.get("authoritative_human_gold") is not False:
        raise ServingStaticContractError("serving_route cannot claim authoritative_human_gold")
    for key in _OVERCLAIM_KEYS:
        if key in payload and payload[key] is True:
            raise ServingStaticContractError(f"serving_route overclaim refused: {key}")

    status = payload["serving_status"]
    routing = payload["routing"]
    if status == "certified_output":
        if payload["truth_tier"] != "autonomous_certified_gold":
            raise ServingStaticContractError("certified_output requires autonomous_certified_gold")
        if payload["certificate"]["status"] != "valid":
            raise ServingStaticContractError("certified_output requires valid certificate")
        if routing["destination"] != "served_without_routine_review":
            raise ServingStaticContractError("certified_output destination mismatch")
    if status == "withheld_for_residual_review":
        if payload["truth_tier"] != "machine_candidate":
            raise ServingStaticContractError("residual review must use machine_candidate")
        if routing["destination"] != "cvat_residual_review":
            raise ServingStaticContractError("residual review destination mismatch")
    if status == "withheld_for_preselected_audit":
        if routing["destination"] != "cvat_preselected_audit":
            raise ServingStaticContractError("audit destination mismatch")
    return payload


def verify_workflow_preflight_contract_static() -> dict[str, Any]:
    """Rebind frozen preflight/performance contracts without launching workflows."""
    policy = load_policy(DEFAULT_POLICY)
    if policy.get("sha256") != LOCKED_POLICY_SHA256:
        raise ServingStaticContractError("workflow performance policy hash drift")
    if tuple(CASE_IDS) != (
        "mode_b_predict_single",
        "mode_b_predict_multi",
        "mode_b_refine_single",
        "mode_b_refine_multi",
        "mode_a_package_single",
        "mode_a_package_multi",
    ):
        raise ServingStaticContractError("CASE_IDS drifted from frozen six-case contract")
    if tuple(ROLLBACK_ROLES) != (
        "champion_bodypart",
        "champion_hand",
        "champion_clothing",
        "interactive_segmenter",
    ):
        raise ServingStaticContractError("ROLLBACK_ROLES drifted")
    if PREFLIGHT_AUTHORITY != (
        "execution_preflight_only_no_serving_mutation_mask_truth_gold_"
        "promotion_or_completion_authority"
    ):
        raise ServingStaticContractError("preflight authority string drifted")

    schema_names = (
        "serving_workflow_preflight_report",
        "serving_workflow_execution_input",
        "serving_workflow_performance_policy",
        "serving_provenance",
        "serving_route",
        "serving_static_contracts_report",
    )
    schema_hashes: dict[str, str] = {}
    for name in schema_names:
        path = ROOT / "src" / "maskfactory" / "schemas" / f"{name}.schema.json"
        if not path.is_file():
            raise ServingStaticContractError(f"missing schema: {name}")
        schema_hashes[name] = file_sha256(path)

    inventory = build_source_node_pack_inventory()
    core = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "serving_workflow_preflight_static_binding",
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": _utc_now(),
        "ready_for_live_workflow_execution": False,
        "mode_b_predict_complete": False,
        "main_adoption_complete": False,
        "production_release_installed": False,
        "workflow_preflight": {
            "policy_path": "qa/governance/serving_workflow_performance_v1.json",
            "policy_sha256": LOCKED_POLICY_SHA256,
            "policy_file_sha256": file_sha256(DEFAULT_POLICY),
            "case_ids": list(CASE_IDS),
            "rollback_roles": list(ROLLBACK_ROLES),
            "preflight_authority": PREFLIGHT_AUTHORITY,
            "status": "pass_static_contract_bound",
        },
        "node_pack_inventory": {
            "inventory_sha256": inventory["inventory_sha256"],
            "file_count": inventory["file_count"],
            "required_workflows": list(REQUIRED_WORKFLOWS),
            "closed_manifest": True,
            "status": "pass_source_inventory",
        },
        "schemas": schema_hashes,
        "provenance_enforcement": {
            "schema": "serving_provenance",
            "status": "pass_schema_and_redaction_contract",
        },
        "serving_route_enforcement": {
            "schema": "serving_route",
            "status": "pass_schema_and_authority_firewall",
        },
    }
    return {**core, "sha256": canonical_sha256(core)}


def run_serving_static_contract_suite() -> dict[str, Any]:
    """Run all STATIC serving contract checks and return a sealed report."""
    inventory = build_source_node_pack_inventory()
    draft_provenance = {
        "source": "champion_models",
        "models": ["champion_bodypart"],
        "provider": {
            "key": "fixture_champion_bodypart",
            "role": "champion_bodypart",
            "lifecycle_state": "promoted",
            "license_eligibility": {"status": "eligible", "eligible": True},
            "benchmark_certificate": {
                "status": "missing",
                "target_role": None,
                "issued_at": None,
                "sha256": None,
            },
            "rollback": {"status": "missing", "provider_key": None},
        },
        "truth_tier": "machine_candidate",
        "certification": {"status": "not_certified", "scope": None},
        "routing": {
            "destination": "review_draft",
            "residual_reason": "model_draft_has_no_autonomy_certificate",
            "audit_reason": None,
        },
    }
    enforce_serving_provenance(draft_provenance)

    residual_route = {
        "schema_version": "1.0.0",
        "serving_status": "withheld_for_residual_review",
        "truth_tier": "machine_candidate",
        "historical_truth_tier": "machine_candidate",
        "authoritative_human_gold": False,
        "certificate": {
            "status": "invalid",
            "reason": "fixture_residual",
            "sha256": None,
            "scope": None,
        },
        "routing": {
            "destination": "cvat_residual_review",
            "residual_reason": "fixture_residual",
            "audit_reason": None,
        },
    }
    enforce_serving_route_static(residual_route)

    preflight = verify_workflow_preflight_contract_static()
    report = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "serving_static_contracts_report",
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": _utc_now(),
        "ready_for_live_workflow_execution": False,
        "mode_b_predict_complete": False,
        "main_adoption_complete": False,
        "production_release_installed": False,
        "checks": {
            "node_pack_inventory": "pass",
            "serving_provenance": "pass",
            "serving_route": "pass",
            "workflow_preflight_contract": "pass",
        },
        "node_pack_inventory_sha256": inventory["inventory_sha256"],
        "workflow_preflight_report_sha256": preflight["sha256"],
        "policy_sha256": LOCKED_POLICY_SHA256,
        "required_workflows": list(REQUIRED_WORKFLOWS),
        "honest_non_claims": [
            "mode_b_predict_complete",
            "main_adoption_complete",
            "production_release_installed",
            "champion_backed_predict",
            "doctor_green",
        ],
    }
    sealed = {**report, "sha256": canonical_sha256(report)}
    issues = validate_document(sealed, "serving_static_contracts_report")
    if issues:
        detail = "; ".join(f"{issue.pointer or '/'} {issue.message}" for issue in issues)
        raise ServingStaticContractError(f"serving_static_contracts_report invalid: {detail}")
    return sealed


__all__ = [
    "AUTHORITY",
    "INVENTORY_FILENAME",
    "PROOF_TIER",
    "REQUIRED_WORKFLOWS",
    "ServingStaticContractError",
    "build_source_node_pack_inventory",
    "enforce_serving_provenance",
    "enforce_serving_route_static",
    "run_serving_static_contract_suite",
    "verify_installed_node_pack_inventory",
    "verify_workflow_preflight_contract_static",
    "write_installed_node_pack_inventory",
]
