"""STATIC cloud-teacher binders: budget breaker, shadow schema, incremental audit."""

from __future__ import annotations

from pathlib import Path

import pytest

from maskfactory.validation import validate_document
from maskfactory.vlm.cloud_teacher_static import (
    HONEST_NON_CLAIMS,
    MINIMUM_INCREMENTAL_CASES,
    REQUIRED_COVERAGE_THEMES,
    CloudTeacherStaticError,
    assess_shadow_consensus_authority,
    audit_incremental_value_corpus,
    build_shadow_teacher_judgment,
    prove_budget_circuit_breaker,
    prove_config_shadow_budget_defaults,
    refuse_mf_p4_10_08_09_claim,
    run_cloud_teacher_static_suite,
)


def test_budget_circuit_breaker_trips_without_paid_calls(tmp_path: Path) -> None:
    proof = prove_budget_circuit_breaker(ledger_path=tmp_path / "ledger.jsonl")
    assert proof["circuit_breaker_tripped"] is True
    assert proof["duplicate_request_refused"] is True
    assert proof["paid_cloud_calls_executed"] is False
    assert proof["hard_limit_usd"] == "15.000000"


def test_config_remains_shadow_only_with_budget_contract() -> None:
    proof = prove_config_shadow_budget_defaults()
    assert proof["mode"] == "shadow_only"
    assert proof["operational_limit_usd"] == 14.5
    assert proof["hard_limit_usd"] == 15.0
    assert proof["reservation_usd"] == 1.0
    assert proof["maximum_calls_per_image"] == 3
    assert proof["minimum_incremental_cases"] == MINIMUM_INCREMENTAL_CASES
    assert proof["paid_cloud_calls_executed"] is False


def test_shadow_teacher_judgment_schema_and_consensus_residual() -> None:
    judgments = [
        build_shadow_teacher_judgment(
            provider="gemini", model="m", verdict="pass", confidence=0.9, defects=[]
        ),
        build_shadow_teacher_judgment(
            provider="openai", model="m", verdict="pass", confidence=0.8, defects=[]
        ),
    ]
    assert not validate_document(judgments[0], "shadow_teacher_judgment")
    vetoed = assess_shadow_consensus_authority(judgments=judgments, deterministic_veto=True)
    assert vetoed["destination"] == "residual_human_queue"
    assert vetoed["may_create_quick_pass"] is False
    assert vetoed["may_approve_gold"] is False

    advisory = assess_shadow_consensus_authority(judgments=judgments, deterministic_veto=False)
    assert advisory["destination"] == "shadow_advisory_only"
    assert advisory["may_create_quick_pass"] is False


def test_incremental_audit_rejects_undersize_leakage_coverage_gaps() -> None:
    cases = []
    for index, theme in enumerate(REQUIRED_COVERAGE_THEMES):
        severity = "none" if theme == "good_mask" else "serious"
        human = "pass" if theme == "good_mask" else "fail"
        cases.append(
            {
                "case_id": f"c{index}",
                "image_id": f"img_{index:012x}",
                "label": "hair",
                "coverage_theme": theme,
                "naturally_occurring": True,
                "severity": severity,
                "human_verdict": human,
            }
        )
    small = audit_incremental_value_corpus(
        {
            "schema_version": "1.0.0",
            "frozen": True,
            "provider": "gemini",
            "model": "fixture",
            "human_anchor_truth": False,
            "cases": cases,
        }
    )
    assert small["structural_pass"] is False
    assert small["mf_p4_10_08_complete"] is False
    assert small["mf_p4_10_09_complete"] is False
    assert any("case_count_below_200" in item for item in small["failures"])

    leak_cases = list(cases)
    leak_cases.append({**cases[0], "case_id": "dup", "image_id": cases[0]["image_id"]})
    leak = audit_incremental_value_corpus(
        {
            "schema_version": "1.0.0",
            "frozen": True,
            "provider": "openai",
            "model": "fixture",
            "human_anchor_truth": False,
            "cases": leak_cases,
        },
        train_image_ids={cases[0]["image_id"]},
    )
    assert "image_disjoint_violation" in leak["failures"]
    assert any(item.startswith("train_leakage:") for item in leak["failures"])

    gap = audit_incremental_value_corpus(
        {
            "schema_version": "1.0.0",
            "frozen": True,
            "provider": "anthropic",
            "model": "fixture",
            "human_anchor_truth": False,
            "cases": [case for case in cases if case["coverage_theme"] != "hair"],
        }
    )
    assert any(item.startswith("coverage_gap:") for item in gap["failures"])


def test_refuse_mf_p4_10_08_09_overclaim() -> None:
    with pytest.raises(CloudTeacherStaticError, match="overclaim_mf_p4_10_08_09"):
        refuse_mf_p4_10_08_09_claim({"mf_p4_10_08_complete": True})
    with pytest.raises(CloudTeacherStaticError, match="overclaim_mf_p4_10_08_09"):
        refuse_mf_p4_10_08_09_claim({"human_anchor_ge_200_corpus": True})


def test_static_suite_seals_binder(tmp_path: Path) -> None:
    report = run_cloud_teacher_static_suite(tmp_path / "ledgers")
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["mf_p4_10_08_complete"] is False
    assert report["mf_p4_10_09_complete"] is False
    assert report["paid_cloud_calls_executed"] is False
    assert report["human_anchor_ge_200_corpus"] is False
    assert set(report["honest_non_claims"]) == set(HONEST_NON_CLAIMS)
    assert not validate_document(report, "cloud_teacher_static_report")
    assert report["report_id"].startswith("cts_")
    assert len(report["seal_sha256"]) == 64
