"""Fail-closed consumer binding for fixture Main artifacts.

Loads hash-bound synthetic Main adoption/adapter/ComfyUI receipts when present
and exposes a normalized observation for Mode A/B slices, qualification, and
handoff. Never promotes ``fixture_authority`` to production adoption or
``independent_real_accuracy``.
"""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any, Mapping

from maskfactory.bridge.fixture_main.runtime import (
    AUTHORITY_KIND,
    CONSUMER_KIND,
    REPO_ROOT,
    SYNTHETIC_MAIN_GIT_COMMIT,
)
from maskfactory.validation import canonical_document_sha256

INBOX_RELATIVE = Path("runtime_artifacts/main_consumer_conformance/inbox")
EVIDENCE_RELATIVE = Path("runtime_artifacts/main_consumer_conformance")


class FixtureMainBindingError(ValueError):
    """Raised when fixture Main artifacts are present but unusable."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _builder() -> dict[str, Any]:
    path = REPO_ROOT / "tests" / "fixtures" / "mask_bridge_contracts" / "build_contract_fixtures.py"
    return runpy.run_path(str(path))


def _claim_firewall(boundary: Mapping[str, Any] | None) -> dict[str, Any]:
    claim = _mapping(boundary)
    return {
        "authority_kind": claim.get("authority_kind") or AUTHORITY_KIND,
        "consumer_kind": claim.get("consumer_kind") or CONSUMER_KIND,
        "fixture_authority": True,
        "synthetic_main_consumer": True,
        "production_main_adoption_complete": False,
        "main_adoption_complete": False,
        "independent_real_accuracy_claim": False,
        "establishes_production_qualification": False,
        "claims_kevin_sgarrett_comfy_ui_main_production_commit": False,
        "trusted_keys_usage_scope": "conformance_only",
        "synthetic_main_git_commit": SYNTHETIC_MAIN_GIT_COMMIT,
    }


def _build_fixture_qualification_bundle(
    adoption: Mapping[str, Any], *, decided_at: str
) -> dict[str, Any]:
    """Signed fixture-only qualification envelope bound to the adoption pins."""
    builder = _builder()
    bundle: dict[str, Any] = {
        "schema_version": "1.0.0",
        "record_type": "fixture_main_qualification_bundle",
        "qualification_id": adoption.get("qualification_bundle_id"),
        "decided_at": decided_at,
        "authority_kind": AUTHORITY_KIND,
        "consumer_kind": CONSUMER_KIND,
        "fixture_only": True,
        "release_id": adoption.get("release_id"),
        "release_payload_sha256": adoption.get("release_payload_sha256"),
        "capability_snapshot_id": adoption.get("capability_snapshot_id"),
        "capability_snapshot_sha256": adoption.get("capability_snapshot_sha256"),
        "consumer_requirements_id": adoption.get("consumer_requirements_id"),
        "consumer_requirements_sha256": adoption.get("consumer_requirements_sha256"),
        "synthetic_main_git_commit": SYNTHETIC_MAIN_GIT_COMMIT,
        "claim_boundary": _claim_firewall({"authority_kind": AUTHORITY_KIND}),
        "qualification_payload_sha256": "0" * 64,
    }
    builder["sign"](
        bundle,
        "qualification_payload_sha256",
        "consumer_qualification",
        ("qualification_payload_sha256", "signature"),
    )
    return bundle


def load_fixture_main_binding(
    repo_root: Path | str | None = None,
    *,
    decided_at: str = "2026-07-19T15:00:00Z",
    require_present: bool = False,
) -> dict[str, Any]:
    """Load fixture Main artifacts; fail closed when absent or invalid.

    Returns a normalized binding. When artifacts are absent and
    ``require_present`` is false, ``present`` is false and consumers must keep
    their honest Main-absence blockers.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    inbox = root / INBOX_RELATIVE
    evidence = root / EVIDENCE_RELATIVE

    adoption = _load_json(inbox / "adoption_receipt.json")
    adapter_observation = _load_json(inbox / "adapter_observation.json")
    requirements_bundle = _load_json(inbox / "requirements_capability_bundle.json")
    claim_boundary_doc = _load_json(evidence / "fixture_main_claim_boundary.json")
    comfyui = _load_json(evidence / "comfyui" / "result_history_receipt.json")
    index = _load_json(evidence / "fixture_main_materialization_index.json")
    arbitration = _load_json(evidence / "arbitration" / "main_decision.json")
    failure_obs = _load_json(evidence / "failure_control" / "observation.json")

    any_present = any(
        doc is not None
        for doc in (
            adoption,
            adapter_observation,
            comfyui,
            index,
            claim_boundary_doc,
        )
    )
    if not any_present:
        if require_present:
            raise FixtureMainBindingError("fixture Main artifacts absent")
        return {
            "present": False,
            "valid": False,
            "binding_status": "absent",
            "authority_kind": AUTHORITY_KIND,
            "consumer_kind": CONSUMER_KIND,
            "synthetic_main_git_commit": None,
            "adoption_receipt": None,
            "adapter_observation": None,
            "requirements_capability_bundle": None,
            "qualification_bundle": None,
            "comfyui_result_history_receipt": None,
            "adapter_execution_receipt": None,
            "arbitration_decision": None,
            "failure_control_observation": None,
            "result_sha256": None,
            "history_sha256": None,
            "workflow_sha256": None,
            "person_binding_count": 0,
            "main_adapter_execution_receipt_present": False,
            "comfyui_result_history_present": False,
            "claim_boundary": _claim_firewall(None),
            "rejection_reasons": ["fixture_main_absent"],
            "decision_sha256": "",
        }

    reasons: list[str] = []
    claim = _claim_firewall(claim_boundary_doc or _mapping(index).get("claim_boundary"))

    if adoption is None:
        reasons.append("adoption_receipt_absent")
    else:
        commit = _mapping(adoption.get("consumer")).get("git_commit")
        if commit != SYNTHETIC_MAIN_GIT_COMMIT:
            reasons.append("adoption_commit_not_synthetic_main")
        if _mapping(adoption.get("signature")).get("key_id") != "comfy-main-adoption-fixture":
            reasons.append("adoption_key_not_fixture")
        if adoption.get("decision") not in {"adopted", "partially_adopted", "conformance_only"}:
            reasons.append("adoption_decision_invalid")

    if adapter_observation is None:
        reasons.append("adapter_observation_absent")
    else:
        identity = _mapping(adapter_observation.get("adapter_identity"))
        if identity.get("git_commit") != SYNTHETIC_MAIN_GIT_COMMIT:
            reasons.append("adapter_commit_not_synthetic_main")

    if comfyui is None:
        reasons.append("comfyui_result_history_absent")
    else:
        if comfyui.get("authority_kind") != AUTHORITY_KIND:
            reasons.append("comfyui_authority_not_fixture")
        if not isinstance(comfyui.get("result_sha256"), str) or len(comfyui["result_sha256"]) != 64:
            reasons.append("comfyui_result_hash_invalid")
        if (
            not isinstance(comfyui.get("history_sha256"), str)
            or len(comfyui["history_sha256"]) != 64
        ):
            reasons.append("comfyui_history_hash_invalid")

    if claim.get("independent_real_accuracy_claim") is True:
        reasons.append("independent_real_accuracy_overclaim")
    if claim.get("production_main_adoption_complete") is True:
        reasons.append("production_adoption_overclaim")
    if claim.get("main_adoption_complete") is True:
        reasons.append("main_adoption_complete_overclaim")

    qualification = None
    if adoption is not None and not reasons:
        qualification = _build_fixture_qualification_bundle(adoption, decided_at=decided_at)

    adapter_exec = _mapping(_mapping(comfyui).get("adapter_execution_receipt")) if comfyui else {}
    adapter_present = bool(adapter_observation) and bool(adapter_exec.get("execution_sha256"))
    history_present = isinstance(_mapping(comfyui).get("result_sha256"), str) and isinstance(
        _mapping(comfyui).get("history_sha256"), str
    )
    valid = not reasons and adoption is not None and adapter_present and history_present
    if not valid and not reasons:
        reasons.append("fixture_main_incomplete")

    binding = {
        "present": True,
        "valid": valid,
        "binding_status": "fixture_main_bound" if valid else "rejected_invalid",
        "authority_kind": AUTHORITY_KIND,
        "consumer_kind": CONSUMER_KIND,
        "synthetic_main_git_commit": SYNTHETIC_MAIN_GIT_COMMIT,
        "adoption_receipt": adoption,
        "adapter_observation": adapter_observation,
        "requirements_capability_bundle": requirements_bundle,
        "qualification_bundle": qualification,
        "comfyui_result_history_receipt": comfyui,
        "adapter_execution_receipt": adapter_exec or None,
        "arbitration_decision": arbitration,
        "failure_control_observation": failure_obs,
        "result_sha256": _mapping(comfyui).get("result_sha256"),
        "history_sha256": _mapping(comfyui).get("history_sha256"),
        "workflow_sha256": _mapping(comfyui).get("workflow_sha256"),
        "person_binding_count": len(_mapping(comfyui).get("person_bindings") or ()),
        "main_adapter_execution_receipt_present": adapter_present and valid,
        "comfyui_result_history_present": history_present and valid,
        "release_payload_sha256": _mapping(adoption).get("release_payload_sha256"),
        "capability_snapshot_sha256": _mapping(adoption).get("capability_snapshot_sha256"),
        "requirements_sha256": _mapping(adoption).get("consumer_requirements_sha256"),
        "claim_boundary": claim,
        "rejection_reasons": sorted(set(reasons)),
        "decision_sha256": "",
    }
    binding["decision_sha256"] = canonical_document_sha256(
        binding, excluded_top_level_fields=("decision_sha256",)
    )
    if require_present and not valid:
        raise FixtureMainBindingError(
            "fixture Main artifacts invalid: " + ",".join(binding["rejection_reasons"])
        )
    return binding


def observation_from_fixture_main_binding(binding: Mapping[str, Any]) -> dict[str, Any]:
    """Project a binding into the observation shape used by qualification/handoff."""
    if not binding.get("present") or not binding.get("valid"):
        return {}
    return {
        "pinned_main_runtime_git_commit": binding.get("synthetic_main_git_commit"),
        "adoption_receipt": binding.get("adoption_receipt"),
        "qualification_bundle": binding.get("qualification_bundle"),
        "main_adapter_execution_receipt_present": True,
        "comfyui_result_history_present": True,
        "release_payload_sha256": binding.get("release_payload_sha256"),
        "capability_snapshot_sha256": binding.get("capability_snapshot_sha256"),
        "requirements_sha256": binding.get("requirements_sha256"),
        "fixture_main_binding": {
            "present": True,
            "valid": True,
            "authority_kind": AUTHORITY_KIND,
            "consumer_kind": CONSUMER_KIND,
            "binding_status": "fixture_main_bound",
            "decision_sha256": binding.get("decision_sha256"),
        },
        # Explicitly refuse production / accuracy escalation.
        "claim_production_qualification": False,
    }


__all__ = [
    "FixtureMainBindingError",
    "load_fixture_main_binding",
    "observation_from_fixture_main_binding",
]
