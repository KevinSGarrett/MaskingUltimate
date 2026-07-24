from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from tools.run_visual_critic_protocol_v3 import _abstention

from maskfactory.vlm.critic_catalog import canonical_sha256
from maskfactory.vlm.critic_protocol_v3_execution import (
    CriticProtocolV3ExecutionError,
    build_calibration_observations,
    execution_manifest_sha256,
    resolve_protocol_v3_execution_cases,
    validate_protocol_v3_execution_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def _corpus() -> dict:
    return json.loads((ROOT / "qa/vlm_eval/visual_critic_calibration_v2/manifest.json").read_text())


def _registry() -> dict:
    return yaml.safe_load((ROOT / "configs/visual_critic_protocol_v3.yaml").read_text())


def _manifest(corpus: dict, registry: dict) -> dict:
    calibration = [case for case in corpus["cases"] if case["partition"] == "calibration"]
    reference = next(case for case in calibration if case["expected_outcome"] == "valid_mask")
    candidate = next(
        case
        for case in calibration
        if case["case_id"] != reference["case_id"]
        and case["target_contract"]["target"]["label_id"]
        == reference["target_contract"]["target"]["label_id"]
    )
    value = {
        "schema_version": "1.0.0",
        "execution_id": "vc2-v3-calibration-test",
        "protocol_id": registry["protocol_id"],
        "protocol_version": registry["protocol_version"],
        "corpus_sha256": corpus["corpus_sha256"],
        "registry_sha256": canonical_sha256(registry),
        "cases": [
            {
                "case_id": candidate["case_id"],
                "reference_case_id": reference["case_id"],
                "source_authority_tier": "external_labeled_reference",
                "label_scale": "small",
            }
        ],
    }
    value["execution_manifest_sha256"] = execution_manifest_sha256(value)
    return value


def test_execution_overlay_requires_hash_bound_image_disjoint_known_good_reference() -> None:
    corpus = _corpus()
    registry = _registry()
    manifest = _manifest(corpus, registry)
    validate_protocol_v3_execution_manifest(manifest, corpus, registry)
    resolved = resolve_protocol_v3_execution_cases(manifest, corpus, registry)
    assert resolved[0]["partition"] == "calibration"
    assert resolved[0]["candidate_panel_set_sha256"] != resolved[0]["reference_panel_set_sha256"]


def test_execution_overlay_rejects_same_image_cross_partition_and_registry_drift() -> None:
    corpus = _corpus()
    registry = _registry()
    manifest = _manifest(corpus, registry)
    same = deepcopy(manifest)
    same["cases"][0]["reference_case_id"] = same["cases"][0]["case_id"]
    same["execution_manifest_sha256"] = execution_manifest_sha256(same)
    with pytest.raises(CriticProtocolV3ExecutionError, match="identity"):
        validate_protocol_v3_execution_manifest(same, corpus, registry)

    drift = deepcopy(manifest)
    drift["registry_sha256"] = "0" * 64
    drift["execution_manifest_sha256"] = execution_manifest_sha256(drift)
    with pytest.raises(CriticProtocolV3ExecutionError, match="registry hash"):
        validate_protocol_v3_execution_manifest(drift, corpus, registry)


def test_only_complete_calibration_valid_rows_can_become_budget_observations() -> None:
    corpus = _corpus()
    registry = _registry()
    resolved = resolve_protocol_v3_execution_cases(_manifest(corpus, registry), corpus, registry)
    fit_case = dict(resolved[0])
    fit_case.update({"case_id": "bound-valid-calibration-case", "expected_outcome": "valid_mask"})
    result = {
        "case_id": fit_case["case_id"],
        "verdict": "pass_with_findings",
        "serious_dimensions": [],
        "minor_dimensions": ["boundary"],
    }
    observations = build_calibration_observations([fit_case], [result])
    assert observations[0]["minor_finding_count"] == 1
    with pytest.raises(CriticProtocolV3ExecutionError, match="incomplete"):
        build_calibration_observations([fit_case], [])


def test_runner_abstention_cannot_claim_authority_or_role_certificate() -> None:
    value = _abstention(reason="malformed")
    assert value["verdict"] == "abstain"
    assert value["authority_claimed"] is False
    assert value["role_certificate_issuance_allowed"] is False
