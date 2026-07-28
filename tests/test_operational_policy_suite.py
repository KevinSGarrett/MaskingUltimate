"""Focused MF-P6-08.05 verify-clause coverage for operational policy evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from maskfactory.authority import (
    load_operational_policy,
    validate_operational_policy_report_binding,
    verify_operational_policy_report,
)
from maskfactory.autonomy.operational_policy_suite import (
    PERTURBATIONS,
    SEEDED_DEFECT_KINDS,
    SYNTHETIC_CASE_KINDS,
    build_base_mask,
    build_candidate_scope,
    build_perturbation_variants,
    build_seeded_defect_synthetic_cases,
    run_operational_policy_evidence_suite,
)
from maskfactory.autonomy.stability import evaluate_candidate_stability, load_stability_policy
from maskfactory.validation import validate_document


def test_policy_requires_all_perturbations_and_seeded_defect_kinds() -> None:
    policy = load_operational_policy()
    assert set(policy["required_perturbations"]) == set(PERTURBATIONS)
    assert set(policy["required_synthetic_case_kinds"]) == set(SYNTHETIC_CASE_KINDS)
    assert SEEDED_DEFECT_KINDS <= set(policy["required_synthetic_case_kinds"])
    assert set(policy["required_gate_ids"]) == {
        "perturbation",
        "metamorphic",
        "stability_replay",
    }
    assert policy["replay_count"] == 2
    assert policy["fixed_seed"] == 1337


def test_stable_suite_retains_identical_decisions(tmp_path: Path) -> None:
    first = run_operational_policy_evidence_suite(tmp_path / "first")
    second = run_operational_policy_evidence_suite(tmp_path / "second")
    assert first == second
    assert first["decision"]["status"] == "pass"
    assert first["decision"]["may_issue_certificate"] is True
    assert first["synthetic_truth"]["passed"] is True
    assert first["replay"]["reproducible"] is True
    kinds = {row["case_kind"] for row in first["synthetic_truth"]["cases"]}
    assert kinds == SYNTHETIC_CASE_KINDS
    assert kinds - {"exact_truth"} == SEEDED_DEFECT_KINDS
    assert not validate_document(first, "operational_policy_evidence")
    verify_operational_policy_report(first)


@pytest.mark.parametrize("perturbation", sorted(PERTURBATIONS))
def test_each_unstable_perturbation_abstains(tmp_path: Path, perturbation: str) -> None:
    report = run_operational_policy_evidence_suite(
        tmp_path,
        unstable_perturbation=perturbation,
    )
    assert report["decision"]["status"] == "autonomous_abstention"
    assert report["decision"]["may_issue_certificate"] is False
    assert "perturbation_instability" in report["decision"]["abstention_codes"]


def test_flip_with_side_swap_inconsistency_abstains(tmp_path: Path) -> None:
    report = run_operational_policy_evidence_suite(tmp_path, side_inconsistent=True)
    assert report["decision"]["status"] == "autonomous_abstention"
    assert report["decision"]["may_issue_certificate"] is False
    assert "side_inconsistency" in report["decision"]["abstention_codes"]


def test_nonreproducible_replay_abstains(tmp_path: Path) -> None:
    report = run_operational_policy_evidence_suite(tmp_path, mutate_second_replay=True)
    assert report["decision"]["status"] == "autonomous_abstention"
    assert report["decision"]["may_issue_certificate"] is False
    assert "deterministic_replay_mismatch" in report["decision"]["abstention_codes"]


@pytest.mark.parametrize("kind", sorted(SYNTHETIC_CASE_KINDS))
def test_broken_seeded_defect_or_exact_truth_self_test_abstains(tmp_path: Path, kind: str) -> None:
    report = run_operational_policy_evidence_suite(
        tmp_path,
        break_seeded_defect_kind=kind,
    )
    assert report["decision"]["status"] == "autonomous_abstention"
    assert report["decision"]["may_issue_certificate"] is False
    assert "synthetic_policy_self_test_failed" in report["decision"]["abstention_codes"]
    assert report["synthetic_truth"]["passed"] is False


def test_flip_variant_requires_preinverse_geometry_and_swap_partner(tmp_path: Path) -> None:
    base_path, base = build_base_mask(tmp_path / "base")
    variants = build_perturbation_variants(
        tmp_path / "variants",
        base,
        label="left_hand",
        side_inconsistent=True,
    )
    flip = next(row for row in variants if row["perturbation"] == "horizontal_flip")
    assert flip["inverse_aligned"] is False
    assert flip["reported_label"] == "left_hand"
    evidence = evaluate_candidate_stability(
        base_path,
        variants,
        candidate_id="suite-flip",
        pipeline_fingerprint="pipeline",
        risk_bucket="large_parts",
        label="left_hand",
        policy=load_stability_policy(),
    )
    assert evidence["passed"] is False
    assert "horizontal_flip:swap_partner_label_mismatch" in evidence["failures"]


def test_seeded_defect_builder_covers_exact_truth_and_three_defects(tmp_path: Path) -> None:
    cases = build_seeded_defect_synthetic_cases(tmp_path, label="left_hand")
    assert [row["case_kind"] for row in cases] == [
        "exact_truth",
        "boundary_shift",
        "missing_area",
        "side_inconsistency",
    ]
    assert all(Path(row["truth_mask_path"]).is_file() for row in cases)
    assert all(Path(row["candidate_mask_path"]).is_file() for row in cases)


def test_policy_binding_detects_scope_drift_on_passing_report(tmp_path: Path) -> None:
    report = run_operational_policy_evidence_suite(tmp_path / "policy")
    assert report["decision"]["status"] == "pass"
    certificate = {
        "source_binding": {
            "decoded_pixel_sha256": report["candidate_scope"]["source_decoded_pixel_sha256"]
        },
        "certified_output_scope": {"artifact_identity_sha256s": ["0" * 64]},
        "execution_binding": {
            "execution_fingerprint_sha256": report["candidate_scope"]["pipeline_fingerprint"]
        },
        "qualified_route_scope": {"risk_buckets": [report["candidate_scope"]["risk_bucket"]]},
        "pipeline_policy_binding": {"seed": report["candidate_scope"]["seed"]},
        "qa_evidence": {
            "qa_policy_id": report["policy"]["policy_id"],
            "qa_policy_sha256": report["policy"]["policy_sha256"],
            "gate_results": [
                {
                    "gate_id": row["gate_id"],
                    "evidence_sha256": row["evidence_sha256"],
                    "executor_id": row["executor_id"],
                    "executor_sha256": row["executor_sha256"],
                }
                for row in report["gate_bindings"]
            ],
        },
        "bound_artifacts": [{"label": report["candidate_scope"]["label"]}],
    }
    codes = validate_operational_policy_report_binding(
        report,
        certificate,
        trusted_evaluators={
            report["evaluator"]["evaluator_id"]: report["evaluator"]["evaluator_sha256"]
        },
    )
    assert "operational_policy_output_scope_mismatch" in codes
    assert build_candidate_scope()["seed"] == 1337
