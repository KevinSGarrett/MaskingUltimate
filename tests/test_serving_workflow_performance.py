from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.serve.workflow_performance import (
    CASE_IDS,
    DEFAULT_POLICY,
    LOCKED_POLICY_SHA256,
    ROLLBACK_ROLES,
    WorkflowPerformanceError,
    canonical_sha256,
    file_sha256,
    load_policy,
    verify_workflow_performance_report,
)
from maskfactory.validation import validate_document


def _artifact(path: Path, value: str) -> tuple[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return str(path), file_sha256(path)


def _build_report(tmp_path: Path) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    sources = []
    for scope, source_id, people, color in (
        ("single_person", "single", 1, "red"),
        ("multi_person", "multi", 3, "blue"),
    ):
        image_path = tmp_path / f"{source_id}.png"
        Image.new("RGB", (64, 48), color).save(image_path)
        governance_path, governance_sha = _artifact(
            tmp_path / f"{source_id}_governance.json",
            json.dumps(
                {
                    "source_id": source_id,
                    "scope": scope,
                    "people": people,
                    "rights": "owned_fixture",
                },
                sort_keys=True,
            ),
        )
        sources.append(
            {
                "source_id": source_id,
                "scope": scope,
                "image_id": f"image_{source_id}",
                "image_path": str(image_path),
                "image_sha256": file_sha256(image_path),
                "governance_decision_path": governance_path,
                "governance_decision_sha256": governance_sha,
                "person_count": people,
                "unseen_before_measurement": True,
                "image_disjoint": True,
            }
        )

    policy = load_policy()
    case_results = []
    for index, case in enumerate(policy["cases"]):
        case_id = case["case_id"]
        output_path, output_sha = _artifact(tmp_path / f"{case_id}_output.bin", f"output:{case_id}")
        provenance_path, provenance_sha = _artifact(
            tmp_path / f"{case_id}_provenance.json",
            json.dumps(
                {
                    "case_id": case_id,
                    "provider_roles": case["required_provider_roles"],
                    "truth_authority": False,
                },
                sort_keys=True,
            ),
        )
        providers = [
            {
                "role": role,
                "provider_key": f"provider_{role}",
                "lifecycle_state": "promoted",
                "checkpoint_sha256": f"{index + 1:064x}",
                "runtime_sha256": f"{index + 11:064x}",
                "benchmark_certificate_sha256": f"{index + 21:064x}",
            }
            for role in case["required_provider_roles"]
        ]
        latency = {}
        for name, requirement in case["required_latency_checks"].items():
            maximum = requirement["maximum_seconds"]
            value = 0.5 if maximum is None else maximum / 2
            latency[name] = {"samples_seconds": [value] * requirement["minimum_samples"]}
        read_only = None
        if case["mode"] == "mode_a":
            manifest_path, manifest_sha = _artifact(
                tmp_path / f"{case_id}_manifest.json",
                json.dumps(
                    {
                        "status": "human_approved_gold",
                        "truth_tier": "human_anchor_gold",
                    },
                    sort_keys=True,
                ),
            )
            tree_sha = f"{index + 31:064x}"
            read_only = {
                "package_manifest_path": manifest_path,
                "package_manifest_sha256": manifest_sha,
                "truth_tier": "human_anchor_gold",
                "package_tree_sha256_before": tree_sha,
                "package_tree_sha256_after": tree_sha,
                "model_load_count": 0,
                "write_attempt_count": 0,
            }
        case_results.append(
            {
                "case_id": case_id,
                "source_id": "single" if case["source_scope"] == "single_person" else "multi",
                "mode": case["mode"],
                "operation": case["operation"],
                "providers": providers,
                "latency": latency,
                "vram": {
                    "before_bytes": 100,
                    "peak_bytes": 200,
                    "after_bytes": 100,
                },
                "oom_count": 0,
                "crash_count": 0,
                "determinism": {
                    "repetitions": 2,
                    "output_sha256s": [output_sha, output_sha],
                },
                "strict_output": True,
                "provenance_path": provenance_path,
                "provenance_sha256": provenance_sha,
                "output_artifact_path": output_path,
                "output_artifact_sha256": output_sha,
                "read_only": read_only,
                "passed": True,
            }
        )

    rollback_results = []
    for index, role in enumerate(ROLLBACK_ROLES):
        rollback_path, rollback_sha = _artifact(
            tmp_path / f"{role}_rollback.json", json.dumps({"role": role, "mode": "rollback"})
        )
        restored_path, restored_sha = _artifact(
            tmp_path / f"{role}_restored.json", json.dumps({"role": role, "mode": "restored"})
        )
        before = f"{index + 41:064x}"
        rollback_results.append(
            {
                "role": role,
                "active_provider": f"active_{role}",
                "rollback_provider": f"rollback_{role}",
                "active_lifecycle_state": "promoted",
                "rollback_lifecycle_state": "benchmarked",
                "selection_sha256_before": before,
                "selection_sha256_during_rollback": f"{index + 51:064x}",
                "selection_sha256_restored": before,
                "rollback_smoke_path": rollback_path,
                "rollback_smoke_sha256": rollback_sha,
                "restored_smoke_path": restored_path,
                "restored_smoke_sha256": restored_sha,
                "rollback_smoke_passed": True,
                "restored_smoke_passed": True,
                "lifecycle_round_trip_passed": True,
                "frozen_artifacts_unchanged": True,
                "passed": True,
            }
        )
    report = {
        "schema_version": "1.0.0",
        "policy_id": "serving_workflow_performance_v1",
        "policy_sha256": policy["sha256"],
        "measured_at": "2026-07-15T17:00:00Z",
        "pipeline_fingerprint": "f" * 64,
        "sources": sources,
        "case_results": case_results,
        "rollback_results": rollback_results,
        "result": "pass_complete_live_measurements",
        "authority": "measurement_evidence_only_no_serving_training_mask_truth_gold_promotion_or_completion_authority",
    }
    report["sha256"] = canonical_sha256(report)
    return report


def _reseal(report: dict) -> dict:
    report["sha256"] = canonical_sha256(
        {key: value for key, value in report.items() if key != "sha256"}
    )
    return report


def test_policy_is_schema_valid_hash_locked_and_source_current() -> None:
    policy = json.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))
    assert not validate_document(policy, "serving_workflow_performance_policy")
    assert policy["sha256"] == LOCKED_POLICY_SHA256
    assert tuple(row["case_id"] for row in policy["cases"]) == CASE_IDS
    assert tuple(policy["rollback_roles"]) == ROLLBACK_ROLES
    assert load_policy() == policy


def test_complete_report_recomputes_every_case_source_artifact_and_rollback(tmp_path: Path) -> None:
    report = _build_report(tmp_path)
    assert not validate_document(report, "serving_workflow_performance_report")
    result = verify_workflow_performance_report(report, artifact_root=tmp_path)
    assert result == {
        "status": "pass_complete_live_measurements",
        "policy_sha256": LOCKED_POLICY_SHA256,
        "report_sha256": report["sha256"],
        "source_count": 2,
        "case_count": 6,
        "rollback_role_count": 4,
    }


def test_cli_verifies_a_complete_report_and_rejects_a_partial_one(tmp_path: Path) -> None:
    report = _build_report(tmp_path)
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    result = CliRunner().invoke(
        main,
        ["verify-serving-workflows", str(report_path), "--artifact-root", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["case_count"] == 6

    report["case_results"].pop()
    _reseal(report)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    result = CliRunner().invoke(
        main,
        ["verify-serving-workflows", str(report_path), "--artifact-root", str(tmp_path)],
    )
    assert result.exit_code != 0
    assert "too short" in result.output or "incomplete" in result.output


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda report: report["case_results"][0]["latency"]["predict_all_warm"].update(
                samples_seconds=[4.000001, 1.0, 1.0]
            ),
            "latency gate failed",
        ),
        (
            lambda report: report["case_results"][0].update(oom_count=1),
            "OOM gate failed",
        ),
        (
            lambda report: report["case_results"][0]["determinism"].update(
                output_sha256s=["a" * 64, "b" * 64]
            ),
            "determinism gate failed",
        ),
        (
            lambda report: report["case_results"][4]["read_only"].update(
                package_tree_sha256_after="e" * 64
            ),
            "mutated the package tree",
        ),
        (
            lambda report: report["case_results"][4]["read_only"].update(model_load_count=1),
            "loaded a model in Mode A",
        ),
        (
            lambda report: report["case_results"][0].update(providers=[]),
            "provider coverage mismatch",
        ),
        (
            lambda report: report["rollback_results"][0].update(
                rollback_provider=report["rollback_results"][0]["active_provider"]
            ),
            "rollback provider is not distinct",
        ),
        (
            lambda report: report["rollback_results"][0].update(selection_sha256_restored="d" * 64),
            "selection was not restored",
        ),
    ],
)
def test_report_fails_closed_on_performance_authority_and_rollback_gaps(
    tmp_path: Path, mutation, message: str
) -> None:
    report = _build_report(tmp_path)
    mutation(report)
    _reseal(report)
    with pytest.raises(WorkflowPerformanceError, match=message):
        verify_workflow_performance_report(report, artifact_root=tmp_path)


def test_report_rejects_tampered_source_output_provenance_and_report_seal(tmp_path: Path) -> None:
    for index, field in enumerate(("source", "output", "provenance", "seal")):
        folder = tmp_path / str(index)
        report = _build_report(folder)
        if field == "source":
            Path(report["sources"][0]["image_path"]).write_bytes(b"tampered")
        elif field == "output":
            Path(report["case_results"][0]["output_artifact_path"]).write_bytes(b"tampered")
        elif field == "provenance":
            Path(report["case_results"][0]["provenance_path"]).write_bytes(b"tampered")
        else:
            report["pipeline_fingerprint"] = "0" * 64
        with pytest.raises(WorkflowPerformanceError, match="hash mismatch"):
            verify_workflow_performance_report(report, artifact_root=folder)


def test_report_rejects_duplicate_or_missing_cases_even_when_schema_and_seal_pass(
    tmp_path: Path,
) -> None:
    report = _build_report(tmp_path)
    report["case_results"][-1] = copy.deepcopy(report["case_results"][0])
    _reseal(report)
    with pytest.raises(WorkflowPerformanceError, match="coverage is incomplete or duplicated"):
        verify_workflow_performance_report(report, artifact_root=tmp_path)
