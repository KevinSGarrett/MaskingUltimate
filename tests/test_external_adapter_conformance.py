from __future__ import annotations

import copy
import json
from pathlib import Path

from maskfactory.bridge import (
    build_external_adapter_conformance_evidence,
    validate_external_adapter_conformance_evidence,
)
from maskfactory.contracts import (
    ADOPTED_CONTRACT_VERSIONS,
    ADOPTED_OPENAPI_PATHS,
    ADOPTED_WIRE_SCHEMA_VERSIONS,
    MaskFactoryAdapter,
    MaskFactoryAdapterError,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "external_adapter_conformance"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_external_contract_boundary_exports_are_explicit_and_versioned() -> None:
    assert MaskFactoryAdapter
    assert MaskFactoryAdapterError
    assert ADOPTED_CONTRACT_VERSIONS["bridge_contract"] == "maskfactory-comfyui-bridge/1.0"
    assert ADOPTED_CONTRACT_VERSIONS["api_contract"] == "maskfactory-api/1.0"
    assert ADOPTED_WIRE_SCHEMA_VERSIONS["mask_acquisition_request"] == "1.0.0"
    assert ADOPTED_WIRE_SCHEMA_VERSIONS["mask_acquisition_receipt"] == "1.0.0"
    assert ADOPTED_OPENAPI_PATHS == {"/health", "/models", "/predict", "/refine"}


def test_accepts_clean_adapter_using_only_published_contracts() -> None:
    evidence = build_external_adapter_conformance_evidence(
        _fixture("accepted_observation_v1.json"),
        decided_at="2026-07-19T12:00:00Z",
    )
    assert evidence["status"] == "accepted"
    assert evidence["rejection_reasons"] == []
    assert validate_external_adapter_conformance_evidence(evidence) == ()


def test_rejects_internal_module_node_id_and_mutable_path_coupling() -> None:
    evidence = build_external_adapter_conformance_evidence(
        _fixture("internal_dependency_observation_v1.json"),
        decided_at="2026-07-19T12:00:00Z",
    )
    assert evidence["status"] == "rejected"
    assert "adapter_internal_dependency" in evidence["rejection_reasons"]
    assert "adapter_node_id_coupling" in evidence["rejection_reasons"]
    assert "adapter_mutable_path_dependency" in evidence["rejection_reasons"]


def test_rejects_dirty_worktree_editable_installs_and_version_drift() -> None:
    evidence = build_external_adapter_conformance_evidence(
        _fixture("version_mismatch_observation_v1.json"),
        decided_at="2026-07-19T12:00:00Z",
    )
    assert evidence["status"] == "rejected"
    assert {
        "adapter_dirty_worktree",
        "adapter_editable_install",
        "producer_dirty_worktree",
        "producer_release_not_adopted",
        "adopted_contract_version_mismatch",
        "adopted_wire_schema_version_mismatch",
        "endpoint_not_published",
        "adapter_mutable_path_dependency",
    }.issubset(set(evidence["rejection_reasons"]))


def test_detects_hash_and_status_tampering_in_materialized_evidence() -> None:
    evidence = build_external_adapter_conformance_evidence(
        _fixture("accepted_observation_v1.json"),
        decided_at="2026-07-19T12:00:00Z",
    )
    tampered = copy.deepcopy(evidence)
    tampered["status"] = "accepted"
    tampered["rejection_reasons"] = ["adapter_internal_dependency"]
    tampered["decision_sha256"] = "0" * 64
    issues = set(validate_external_adapter_conformance_evidence(tampered))
    assert {"decision_hash_drift", "decision_status_reasons"}.issubset(issues)


def test_policy_binding_drift_is_rejected() -> None:
    evidence = build_external_adapter_conformance_evidence(
        _fixture("accepted_observation_v1.json"),
        decided_at="2026-07-19T12:00:00Z",
    )
    evidence["policy_sha256"] = "0" * 64
    assert "policy_drift" in set(validate_external_adapter_conformance_evidence(evidence))
