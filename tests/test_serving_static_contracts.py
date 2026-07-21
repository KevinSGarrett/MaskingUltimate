"""STATIC_PASS serving/ComfyUI contracts — no Main/champion claims."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.serve.comfy_install import install_node_pack
from maskfactory.serve.static_contracts import (
    INVENTORY_FILENAME,
    PROOF_TIER,
    REQUIRED_WORKFLOWS,
    ServingStaticContractError,
    build_source_node_pack_inventory,
    enforce_serving_provenance,
    enforce_serving_route_static,
    run_serving_static_contract_suite,
    verify_installed_node_pack_inventory,
    verify_workflow_preflight_contract_static,
)
from maskfactory.validation import validate_document


def _draft_provenance() -> dict:
    return {
        "source": "champion_models",
        "models": ["champion_bodypart"],
        "provider": {
            "key": "fixture_champion_bodypart",
            "role": "champion_bodypart",
            "lifecycle_state": "promoted",
            "content_compatibility": {
                "adult_nonexplicit": "allowed",
                "consensual_explicit_adult": "allowed",
            },
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


def _residual_route() -> dict:
    return {
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


def test_source_node_pack_inventory_is_closed_and_hash_sealed() -> None:
    inventory = build_source_node_pack_inventory()
    assert inventory["proof_tier"] == PROOF_TIER
    assert inventory["closed_manifest"] is True
    assert inventory["required_workflows"] == list(REQUIRED_WORKFLOWS)
    assert inventory["file_count"] == 1 + len(REQUIRED_WORKFLOWS)
    assert inventory["mode_b_predict_complete"] is False
    assert inventory["main_adoption_complete"] is False
    assert inventory["production_release_installed"] is False
    assert inventory["sha256"] == inventory["inventory_sha256"]
    assert {row["relative_path"] for row in inventory["files"]} == {
        "__init__.py",
        *(f"workflows/{name}" for name in REQUIRED_WORKFLOWS),
    }


def test_install_writes_inventory_and_detects_stale_files(tmp_path: Path) -> None:
    comfy_root = tmp_path / "ComfyUI"
    comfy_root.mkdir()
    packages = tmp_path / "packages"
    packages.mkdir()
    target = install_node_pack(comfy_root, packages_root=packages)
    inventory_path = target / INVENTORY_FILENAME
    assert inventory_path.is_file()
    verify_installed_node_pack_inventory(target)

    stale = target / "stale_unpublished_node.py"
    stale.write_text("# stale\n", encoding="utf-8")
    with pytest.raises(ServingStaticContractError, match="stale_unmanifested_files"):
        verify_installed_node_pack_inventory(target)


def test_serving_provenance_rejects_path_and_credential_leakage() -> None:
    enforce_serving_provenance(_draft_provenance())
    leaked = copy.deepcopy(_draft_provenance())
    leaked["provider"]["key"] = r"C:\models\champion.pth"
    with pytest.raises(ServingStaticContractError, match="redaction"):
        enforce_serving_provenance(leaked)

    overclaim = copy.deepcopy(_draft_provenance())
    overclaim["truth_tier"] = "human_anchor_gold"
    with pytest.raises(ServingStaticContractError):
        enforce_serving_provenance(overclaim)


def test_serving_route_static_firewall_rejects_human_gold_and_overclaims() -> None:
    enforce_serving_route_static(_residual_route())
    bad = copy.deepcopy(_residual_route())
    bad["authoritative_human_gold"] = True
    with pytest.raises(ServingStaticContractError, match="authoritative_human_gold"):
        enforce_serving_route_static(bad)

    certified = copy.deepcopy(_residual_route())
    certified["serving_status"] = "certified_output"
    certified["truth_tier"] = "autonomous_certified_gold"
    certified["certificate"] = {
        "status": "valid",
        "reason": "certificate_valid",
        "sha256": "a" * 64,
        "scope": {
            "risk_bucket": "hands",
            "covered_labels": ["left_hand_base"],
            "covered_contexts": ["solo"],
            "pipeline_fingerprint": "pipeline-v1",
        },
    }
    certified["routing"] = {
        "destination": "served_without_routine_review",
        "residual_reason": None,
        "audit_reason": None,
    }
    enforce_serving_route_static(certified)


def test_workflow_preflight_static_binding_refuses_live_execution_claim() -> None:
    binding = verify_workflow_preflight_contract_static()
    assert binding["proof_tier"] == PROOF_TIER
    assert binding["ready_for_live_workflow_execution"] is False
    assert binding["mode_b_predict_complete"] is False
    assert binding["workflow_preflight"]["status"] == "pass_static_contract_bound"
    assert len(binding["workflow_preflight"]["case_ids"]) == 6


def test_static_contract_suite_seals_schema_valid_report() -> None:
    report = run_serving_static_contract_suite()
    assert validate_document(report, "serving_static_contracts_report") == ()
    assert report["proof_tier"] == PROOF_TIER
    assert report["ready_for_live_workflow_execution"] is False
    assert report["checks"] == {
        "node_pack_inventory": "pass",
        "serving_provenance": "pass",
        "serving_route": "pass",
        "workflow_preflight_contract": "pass",
    }


def test_cli_verify_static_contracts_writes_evidence(tmp_path: Path) -> None:
    output = tmp_path / "serving_static_contracts_report.json"
    result = CliRunner().invoke(
        main,
        ["comfy", "verify-static-contracts", "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    document = json.loads(output.read_text(encoding="utf-8"))
    assert validate_document(document, "serving_static_contracts_report") == ()
