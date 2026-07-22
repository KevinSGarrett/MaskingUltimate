from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from maskfactory.autonomy.work_cell import (
    AutonomousWorkCell,
    WorkCellError,
    seal_manifest,
    validate_mission_manifest,
)
from maskfactory.autonomy.work_cell_command_handlers import command_binding_sha256
from maskfactory.autonomy.work_cell_mission_builder import build_mission_artifacts
from maskfactory.autonomy.work_cell_runner import WorkCellRunner

HEX = "a" * 64


def manifest(*, record_count: int = 1, authority: str = "operationally_certified_artifact"):
    role = {
        "status": "qualified",
        "model_id": "model-a",
        "family": "family-a",
        "revision_sha256": HEX,
        "role_certificate_sha256": HEX,
        "revoked": False,
    }
    return seal_manifest(
        {
            "schema_version": "maskfactory.runpod_autonomous_mission.v1",
            "mission_id": "mission-test-0001",
            "input": {
                "manifest_path": "batch_shards/runpod/index.json",
                "manifest_sha256": HEX,
                "record_count": record_count,
                "shard_count": 1,
            },
            "bindings": {
                "ontology_sha256": HEX,
                "target_contract_schema_sha256": HEX,
                "qa_threshold_registry_sha256": HEX,
                "provider_catalog_sha256": HEX,
                "critic_catalog_sha256": HEX,
                "certification_policy_sha256": HEX,
            },
            "provider_bindings": [
                {
                    "provider_id": "sam31",
                    "family": "sam",
                    "checkpoint_sha256": HEX,
                    "runtime_sha256": HEX,
                },
                {
                    "provider_id": "birefnet",
                    "family": "birefnet",
                    "checkpoint_sha256": HEX,
                    "runtime_sha256": HEX,
                },
            ],
            "stage_versions": {
                "source_decode": HEX,
                "detection_ownership": HEX,
                "provider_tournament": HEX,
                "hard_qc": HEX,
                "primary_visual_review": HEX,
                "independent_visual_review": HEX,
                "repair_planning": HEX,
                "repair_execution": HEX,
                "package_freeze": HEX,
                "certification": HEX,
            },
            "role_bindings": {
                "primary_visual_critic": role,
                "independent_juror": {**role, "model_id": "model-b", "family": "family-b"},
            },
            "repair_policy": {
                "max_attempts": 2,
                "max_changed_pixel_fraction": 0.2,
                "max_elapsed_seconds": 300,
                "allowed_operations": ["box_refine", "point_refine"],
            },
            "bulk_policy": {
                "workload_scope": [
                    "source_decode",
                    "person_ownership",
                    "mask_generation",
                    "deterministic_hard_qa",
                    "strict_visual_review",
                    "bounded_repair",
                    "mask_correction",
                    "package_freeze",
                    "certification",
                    "milestone_reporting",
                ],
                "reporting_mode": "milestone_only",
                "suppress_per_record_chat": True,
                "require_no_routine_human_review": True,
                "allow_optional_exception_queue": True,
                "self_hosted_llm_bulk_review": True,
                "material_incident_threshold_fraction": 0.1,
                "terminal_outcomes": ["accepted", "abstained", "quarantined", "rejected"],
            },
            "execution": {
                "lease_seconds": 10,
                "max_record_attempts": 3,
                "checkpoint_records": 1,
                "milestone_records": 1,
            },
            "authority_ceiling": authority,
            "allowed_output_prefix": "missions/mission-test-0001",
        }
    )


def stage_detail(stage: str, status: str = "pass") -> dict[str, object]:
    details: dict[str, dict[str, object]] = {
        "source_decode": {
            "decoded_pixel_sha256": HEX,
            "alpha_policy": "absent",
            "width": 32,
            "height": 32,
        },
        "detection_ownership": {
            "target_contract_sha256": HEX,
            "person_count": 1,
            "ownership_status": "verified",
        },
        "provider_tournament": {
            "tournament_report_sha256": HEX,
            "family_count": 2,
            "candidate_count": 2,
            "winner_mask_sha256": HEX,
        },
        "hard_qc": {"qa_vector_sha256": HEX, "hard_veto_count": 0},
        "primary_visual_review": {
            "panel_sha256": HEX,
            "critic_report_sha256": HEX,
            "verdict": "pass",
        },
        "independent_visual_review": {
            "panel_sha256": HEX,
            "critic_report_sha256": HEX,
            "verdict": "pass",
        },
        "repair_planning": {
            "defect_hypothesis_sha256": HEX,
            "roi_sha256": HEX,
            "operation": "box_refine",
        },
        "repair_execution": {
            "parent_mask_sha256": HEX,
            "new_mask_sha256": "b" * 64,
            "changed_pixel_fraction": 0.1,
        },
        "package_freeze": {"package_sha256": HEX, "active_label_count": 1},
        "certification": {
            "certificate_sha256": HEX,
            "authority_tier": "operationally_certified_artifact",
        },
    }
    detail = dict(details[stage])
    if status == "repairable" and stage in {
        "hard_qc",
        "primary_visual_review",
        "independent_visual_review",
    }:
        if stage == "hard_qc":
            detail["hard_veto_count"] = 1
        else:
            detail["verdict"] = "repairable"
    return detail


def receipt(stage: str, actor: str, status: str = "pass") -> dict[str, object]:
    return {
        "stage": stage,
        "status": status,
        "actor_kind": actor,
        "evidence_sha256": HEX,
        "detail": stage_detail(stage, status),
    }


def test_schemas_are_closed_and_valid() -> None:
    root = Path("src/maskfactory/schemas")
    for name in (
        "runpod_autonomous_mission.schema.json",
        "runpod_autonomous_mission_report.schema.json",
        "runpod_work_cell_handlers.schema.json",
    ):
        schema = json.loads((root / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False


def test_manifest_rejects_drift_correlated_roles_and_unqualified_authority() -> None:
    document = manifest()
    document["unexpected"] = True
    with pytest.raises(WorkCellError, match="schema invalid"):
        validate_mission_manifest(document)

    document = manifest()
    document["role_bindings"]["independent_juror"]["family"] = "family-a"
    document = seal_manifest(document)
    with pytest.raises(WorkCellError, match="independent model families"):
        validate_mission_manifest(document)

    document = manifest()
    document["role_bindings"]["independent_juror"] = {
        "status": "unavailable",
        "model_id": None,
        "family": None,
        "revision_sha256": None,
        "role_certificate_sha256": None,
        "revoked": False,
    }
    document = seal_manifest(document)
    with pytest.raises(WorkCellError, match="two qualified visual roles"):
        validate_mission_manifest(document)


def test_manifest_requires_bulk_masking_review_repair_and_milestone_policy() -> None:
    document = manifest()
    document["bulk_policy"]["workload_scope"].remove("mask_correction")
    document = seal_manifest(document)
    with pytest.raises(WorkCellError, match="bulk mission scope incomplete"):
        validate_mission_manifest(document)

    document = manifest()
    document["bulk_policy"]["reporting_mode"] = "per_record_chat"
    document = seal_manifest(document)
    with pytest.raises(WorkCellError, match="schema invalid"):
        validate_mission_manifest(document)

    document = manifest()
    document["bulk_policy"]["require_no_routine_human_review"] = False
    document = seal_manifest(document)
    with pytest.raises(WorkCellError, match="schema invalid"):
        validate_mission_manifest(document)

    document = manifest()
    document["bulk_policy"]["material_incident_threshold_fraction"] = 0.5
    document = seal_manifest(document)
    with pytest.raises(WorkCellError, match="incident threshold"):
        validate_mission_manifest(document)


def test_complete_mission_advances_all_authority_stages(tmp_path: Path) -> None:
    cell = AutonomousWorkCell(tmp_path)
    document = manifest()
    assert cell.admit(document)["admitted"] is True
    assert cell.admit(document)["idempotent"] is True
    cell.seed_records(
        document["mission_id"],
        [{"record_id": "r1", "source_sha256": HEX, "input_payload_sha256": HEX}],
    )
    actors = {
        "source_decode": "deterministic_qa",
        "detection_ownership": "deterministic_qa",
        "provider_tournament": "segmentation_provider",
        "hard_qc": "deterministic_qa",
        "primary_visual_review": "visual_critic",
        "independent_visual_review": "visual_critic",
        "package_freeze": "deterministic_qa",
        "certification": "certificate_service",
    }
    while True:
        work = cell.claim(document["mission_id"], owner="worker-1")
        if work is None:
            break
        cell.apply_result(
            document["mission_id"],
            work["record_id"],
            work["lease_token"],
            receipt(work["stage"], actors[work["stage"]]),
        )
    report = cell.report(document["mission_id"])
    assert report["mission_state"] == "complete"
    assert report["outcome_counts"] == {"accepted": 1}
    assert report["stage_receipt_count"] == 8
    assert report["stage_status_counts"]["certification:pass"] == 1
    assert report["last_error_counts"] == {}
    assert report["milestones"][0]["terminal_record_count"] == 1
    assert report["reporting_mode"] == "milestone_only"
    assert report["bulk_policy_sha256"]
    assert report["material_incidents"] == []
    assert report["integrity_errors"] == []
    assert report["self_sha256"]


def test_visual_critic_cannot_execute_repairs_or_clear_unqualified_role(tmp_path: Path) -> None:
    cell = AutonomousWorkCell(tmp_path)
    document = manifest(authority="machine_verified_candidate")
    unavailable = {
        "status": "unavailable",
        "model_id": None,
        "family": None,
        "revision_sha256": None,
        "role_certificate_sha256": None,
        "revoked": False,
    }
    document["role_bindings"]["primary_visual_critic"] = unavailable
    document["role_bindings"]["independent_juror"] = unavailable
    document = seal_manifest(document)
    cell.admit(document)
    cell.seed_records(
        document["mission_id"],
        [{"record_id": "r1", "source_sha256": HEX, "input_payload_sha256": HEX}],
    )
    actors = [
        ("source_decode", "deterministic_qa"),
        ("detection_ownership", "deterministic_qa"),
        ("provider_tournament", "segmentation_provider"),
        ("hard_qc", "deterministic_qa"),
    ]
    for expected, actor in actors:
        work = cell.claim(document["mission_id"], owner="worker")
        assert work["stage"] == expected
        cell.apply_result(
            document["mission_id"], "r1", work["lease_token"], receipt(expected, actor)
        )
    work = cell.claim(document["mission_id"], owner="worker")
    with pytest.raises(WorkCellError, match="unqualified visual role"):
        cell.apply_result(
            document["mission_id"],
            "r1",
            work["lease_token"],
            receipt("primary_visual_review", "visual_critic"),
        )


def test_repair_loop_requires_provider_pixel_author_and_rechecks_hard_qc(tmp_path: Path) -> None:
    cell = AutonomousWorkCell(tmp_path)
    document = manifest()
    cell.admit(document)
    cell.seed_records(
        document["mission_id"],
        [{"record_id": "r1", "source_sha256": HEX, "input_payload_sha256": HEX}],
    )
    for stage, actor in (
        ("source_decode", "deterministic_qa"),
        ("detection_ownership", "deterministic_qa"),
        ("provider_tournament", "segmentation_provider"),
    ):
        work = cell.claim(document["mission_id"], owner="worker")
        cell.apply_result(document["mission_id"], "r1", work["lease_token"], receipt(stage, actor))
    work = cell.claim(document["mission_id"], owner="worker")
    result = cell.apply_result(
        document["mission_id"],
        "r1",
        work["lease_token"],
        receipt("hard_qc", "deterministic_qa", "repairable"),
    )
    assert result["stage"] == "repair_planning"
    work = cell.claim(document["mission_id"], owner="worker")
    cell.apply_result(
        document["mission_id"],
        "r1",
        work["lease_token"],
        receipt("repair_planning", "visual_critic"),
    )
    work = cell.claim(document["mission_id"], owner="worker")
    with pytest.raises(WorkCellError, match="actor visual_critic"):
        cell.apply_result(
            document["mission_id"],
            "r1",
            work["lease_token"],
            receipt("repair_execution", "visual_critic"),
        )
    cell.apply_result(
        document["mission_id"],
        "r1",
        work["lease_token"],
        receipt("repair_execution", "segmentation_provider"),
    )
    assert cell.claim(document["mission_id"], owner="worker")["stage"] == "hard_qc"


def test_stage_receipts_require_exact_mask_qa_visual_repair_and_certificate_detail(
    tmp_path: Path,
) -> None:
    cell = AutonomousWorkCell(tmp_path)
    document = manifest()
    cell.admit(document)
    cell.seed_records(
        document["mission_id"],
        [{"record_id": "r1", "source_sha256": HEX, "input_payload_sha256": HEX}],
    )
    work = cell.claim(document["mission_id"], owner="worker")
    bad = receipt("source_decode", "deterministic_qa")
    bad.pop("detail")
    with pytest.raises(WorkCellError, match="stage detail object required"):
        cell.apply_result(document["mission_id"], "r1", work["lease_token"], bad)

    cell.apply_result(
        document["mission_id"],
        "r1",
        work["lease_token"],
        receipt("source_decode", "deterministic_qa"),
    )
    work = cell.claim(document["mission_id"], owner="worker")
    bad = receipt("detection_ownership", "deterministic_qa")
    bad["detail"]["ownership_status"] = "ambiguous"
    with pytest.raises(WorkCellError, match="ownership must be verified"):
        cell.apply_result(document["mission_id"], "r1", work["lease_token"], bad)

    cell.apply_result(
        document["mission_id"],
        "r1",
        work["lease_token"],
        receipt("detection_ownership", "deterministic_qa"),
    )
    work = cell.claim(document["mission_id"], owner="worker")
    bad = receipt("provider_tournament", "segmentation_provider")
    bad["detail"]["family_count"] = 1
    with pytest.raises(WorkCellError, match="provider pass requires"):
        cell.apply_result(document["mission_id"], "r1", work["lease_token"], bad)


def test_expired_leases_requeue_then_abstain_at_retry_cap(tmp_path: Path) -> None:
    now = [100.0]
    cell = AutonomousWorkCell(tmp_path, clock=lambda: now[0])
    document = manifest()
    document["execution"]["max_record_attempts"] = 1
    document = seal_manifest(document)
    cell.admit(document)
    cell.seed_records(
        document["mission_id"],
        [{"record_id": "r1", "source_sha256": HEX, "input_payload_sha256": HEX}],
    )
    cell.claim(document["mission_id"], owner="dead-worker")
    now[0] = 111.0
    assert cell.recover_expired(document["mission_id"]) == {"requeued": 0, "abstained": 1}
    assert cell.report(document["mission_id"])["outcome_counts"] == {"abstained": 1}


def test_report_is_immutable_and_schema_valid(tmp_path: Path) -> None:
    cell = AutonomousWorkCell(tmp_path)
    document = manifest()
    cell.admit(document)
    cell.seed_records(
        document["mission_id"],
        [{"record_id": "r1", "source_sha256": HEX, "input_payload_sha256": HEX}],
    )
    output = tmp_path / "reports" / "milestone.json"
    report = cell.write_report(document["mission_id"], output)
    schema = json.loads(
        Path("src/maskfactory/schemas/runpod_autonomous_mission_report.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(report)
    with pytest.raises(WorkCellError, match="already exists"):
        cell.write_report(document["mission_id"], output)


def test_record_seed_drift_fails_closed(tmp_path: Path) -> None:
    cell = AutonomousWorkCell(tmp_path)
    document = manifest()
    cell.admit(document)
    record = {"record_id": "r1", "source_sha256": HEX, "input_payload_sha256": HEX}
    cell.seed_records(document["mission_id"], [record])
    changed = copy.deepcopy(record)
    changed["source_sha256"] = "b" * 64
    with pytest.raises(WorkCellError, match="record seed drift"):
        cell.seed_records(document["mission_id"], [changed])


class _Handler:
    implementation_sha256 = HEX

    def __init__(self, actor: str, *, fail: bool = False) -> None:
        self.actor = actor
        self.fail = fail

    def __call__(self, work):
        if self.fail:
            raise RuntimeError("seeded stage failure")
        return receipt(work["stage"], self.actor)


def _handlers(*, failing_stage: str | None = None):
    actors = {
        "source_decode": "deterministic_qa",
        "detection_ownership": "deterministic_qa",
        "provider_tournament": "segmentation_provider",
        "hard_qc": "deterministic_qa",
        "primary_visual_review": "visual_critic",
        "independent_visual_review": "visual_critic",
        "repair_planning": "visual_critic",
        "repair_execution": "segmentation_provider",
        "package_freeze": "deterministic_qa",
        "certification": "certificate_service",
    }
    return {stage: _Handler(actor, fail=stage == failing_stage) for stage, actor in actors.items()}


def test_runner_completes_whole_mission_and_reports_only_milestones(tmp_path: Path) -> None:
    cell = AutonomousWorkCell(tmp_path)
    document = manifest(record_count=2)
    cell.admit(document)
    cell.seed_records(
        document["mission_id"],
        [
            {"record_id": "r1", "source_sha256": HEX, "input_payload_sha256": HEX},
            {"record_id": "r2", "source_sha256": "b" * 64, "input_payload_sha256": HEX},
        ],
    )
    milestones = []
    runner = WorkCellRunner(
        cell,
        _handlers(),
        owner="runpod-daemon",
        milestone_callback=lambda report: milestones.append(report["terminal_record_count"]),
    )
    report = runner.run(document["mission_id"])
    assert report["mission_state"] == "complete"
    assert report["outcome_counts"] == {"accepted": 2}
    assert report["runner_stage_operations"] == 16
    assert milestones == [1, 2]


def test_runner_isolates_stage_failure_and_continues_other_records(tmp_path: Path) -> None:
    cell = AutonomousWorkCell(tmp_path)
    document = manifest(record_count=2)
    cell.admit(document)
    cell.seed_records(
        document["mission_id"],
        [
            {"record_id": "r1", "source_sha256": HEX, "input_payload_sha256": HEX},
            {"record_id": "r2", "source_sha256": "b" * 64, "input_payload_sha256": HEX},
        ],
    )
    runner = WorkCellRunner(cell, _handlers(failing_stage="source_decode"), owner="daemon")
    report = runner.run(document["mission_id"])
    assert report["mission_state"] == "complete"
    assert report["outcome_counts"] == {"abstained": 2}
    assert report["stage_receipt_count"] == 0
    assert report["last_error_counts"] == {"stage_executor_failure:source_decode:RuntimeError": 2}
    assert report["material_incidents"] == [
        {
            "incident_type": "stage_executor_failure_rate",
            "count": 2,
            "record_count": 2,
            "fraction": 1.0,
            "threshold_fraction": 0.1,
        }
    ]
    assert len(list((tmp_path / "executor_failures").rglob("*.json"))) == 2


def test_runner_rejects_deployed_stage_hash_drift(tmp_path: Path) -> None:
    cell = AutonomousWorkCell(tmp_path)
    document = manifest()
    cell.admit(document)
    cell.seed_records(
        document["mission_id"],
        [{"record_id": "r1", "source_sha256": HEX, "input_payload_sha256": HEX}],
    )
    handlers = _handlers()
    handlers["source_decode"].implementation_sha256 = "b" * 64
    runner = WorkCellRunner(cell, handlers, owner="daemon")
    with pytest.raises(WorkCellError, match="implementation drift"):
        runner.run(document["mission_id"])


def test_cli_run_loads_hash_bound_handlers_and_writes_milestones(tmp_path: Path) -> None:
    handler_source = tmp_path / "stage_handlers.py"
    handler_source.write_text(
        "\n".join(
            [
                "ACTORS = {",
                "    'source_decode': 'deterministic_qa',",
                "    'detection_ownership': 'deterministic_qa',",
                "    'provider_tournament': 'segmentation_provider',",
                "    'hard_qc': 'deterministic_qa',",
                "    'primary_visual_review': 'visual_critic',",
                "    'independent_visual_review': 'visual_critic',",
                "    'repair_planning': 'visual_critic',",
                "    'repair_execution': 'segmentation_provider',",
                "    'package_freeze': 'deterministic_qa',",
                "    'certification': 'certificate_service',",
                "}",
                "def handle(work):",
                "    details = {",
                "        'source_decode': {'decoded_pixel_sha256': 'a' * 64, 'alpha_policy': 'absent', 'width': 32, 'height': 32},",
                "        'detection_ownership': {'target_contract_sha256': 'a' * 64, 'person_count': 1, 'ownership_status': 'verified'},",
                "        'provider_tournament': {'tournament_report_sha256': 'a' * 64, 'family_count': 2, 'candidate_count': 2, 'winner_mask_sha256': 'a' * 64},",
                "        'hard_qc': {'qa_vector_sha256': 'a' * 64, 'hard_veto_count': 0},",
                "        'primary_visual_review': {'panel_sha256': 'a' * 64, 'critic_report_sha256': 'a' * 64, 'verdict': 'pass'},",
                "        'independent_visual_review': {'panel_sha256': 'a' * 64, 'critic_report_sha256': 'a' * 64, 'verdict': 'pass'},",
                "        'repair_planning': {'defect_hypothesis_sha256': 'a' * 64, 'roi_sha256': 'a' * 64, 'operation': 'box_refine'},",
                "        'repair_execution': {'parent_mask_sha256': 'a' * 64, 'new_mask_sha256': 'b' * 64, 'changed_pixel_fraction': 0.1},",
                "        'package_freeze': {'package_sha256': 'a' * 64, 'active_label_count': 1},",
                "        'certification': {'certificate_sha256': 'a' * 64, 'authority_tier': 'operationally_certified_artifact'},",
                "    }",
                "    return {",
                "        'stage': work['stage'],",
                "        'status': 'pass',",
                "        'actor_kind': ACTORS[work['stage']],",
                "        'evidence_sha256': 'a' * 64,",
                "        'detail': details[work['stage']],",
                "    }",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    source_hash = _sha256_file_for_test(handler_source)
    document = manifest(record_count=1)
    document["mission_id"] = "mission-cli-0001"
    document["input"]["record_count"] = 1
    document["allowed_output_prefix"] = "missions/mission-cli-0001"
    document["stage_versions"] = {stage: source_hash for stage in document["stage_versions"]}
    document = seal_manifest(document)
    manifest_path = tmp_path / "mission.json"
    records_path = tmp_path / "records.json"
    handlers_path = tmp_path / "handlers.json"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    records_path.write_text(
        json.dumps([{"record_id": "r1", "source_sha256": HEX, "input_payload_sha256": HEX}]),
        encoding="utf-8",
    )
    handlers_path.write_text(
        json.dumps(
            {
                "schema_version": "maskfactory.runpod_work_cell_handlers.v1",
                "handlers": {
                    stage: {
                        "kind": "python_callable",
                        "source_path": str(handler_source),
                        "callable": "handle",
                        "implementation_sha256": source_hash,
                    }
                    for stage in document["stage_versions"]
                },
            }
        ),
        encoding="utf-8",
    )

    env = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    root = tmp_path / "queue"
    cli = Path.cwd() / "tools" / "manage_runpod_autonomous_work_cell.py"
    for command in (
        ["--root", str(root), "admit", "--manifest", str(manifest_path)],
        [
            "--root",
            str(root),
            "seed",
            "--mission-id",
            document["mission_id"],
            "--records",
            str(records_path),
        ],
        [
            "--root",
            str(root),
            "run",
            "--mission-id",
            document["mission_id"],
            "--owner",
            "runpod-daemon",
            "--handlers",
            str(handlers_path),
            "--milestone-output-dir",
            str(tmp_path / "milestones"),
        ],
    ):
        subprocess.run([sys.executable, str(cli), *command], check=True, env=env, cwd=Path.cwd())

    report = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                str(cli),
                "--root",
                str(root),
                "report",
                "--mission-id",
                document["mission_id"],
            ],
            env=env,
            cwd=Path.cwd(),
            text=True,
        )
    )
    assert report["mission_state"] == "complete"
    assert report["outcome_counts"] == {"accepted": 1}
    assert report["stage_status_counts"]["provider_tournament:pass"] == 1
    snapshots = list((tmp_path / "milestones").glob("mission-cli-0001_terminal_*.json"))
    assert len(snapshots) == 1


def test_cli_run_rejects_incomplete_handler_manifest_before_work(tmp_path: Path) -> None:
    document = manifest(record_count=1)
    manifest_path = tmp_path / "mission.json"
    records_path = tmp_path / "records.json"
    handlers_path = tmp_path / "handlers.json"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    records_path.write_text(
        json.dumps([{"record_id": "r1", "source_sha256": HEX, "input_payload_sha256": HEX}]),
        encoding="utf-8",
    )
    handlers_path.write_text(
        json.dumps(
            {
                "schema_version": "maskfactory.runpod_work_cell_handlers.v1",
                "handlers": {
                    "source_decode": {
                        "kind": "python_callable",
                        "source_path": "stage_handlers.py",
                        "callable": "handle",
                        "implementation_sha256": HEX,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    env = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    root = tmp_path / "queue"
    cli = Path.cwd() / "tools" / "manage_runpod_autonomous_work_cell.py"
    subprocess.run(
        [sys.executable, str(cli), "--root", str(root), "admit", "--manifest", str(manifest_path)],
        check=True,
        env=env,
        cwd=Path.cwd(),
    )
    subprocess.run(
        [
            sys.executable,
            str(cli),
            "--root",
            str(root),
            "seed",
            "--mission-id",
            document["mission_id"],
            "--records",
            str(records_path),
        ],
        check=True,
        env=env,
        cwd=Path.cwd(),
    )
    result = subprocess.run(
        [
            sys.executable,
            str(cli),
            "--root",
            str(root),
            "run",
            "--mission-id",
            document["mission_id"],
            "--owner",
            "runpod-daemon",
            "--handlers",
            str(handlers_path),
        ],
        env=env,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "handler manifest schema invalid" in result.stderr
    report = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                str(cli),
                "--root",
                str(root),
                "report",
                "--mission-id",
                document["mission_id"],
            ],
            env=env,
            cwd=Path.cwd(),
            text=True,
        )
    )
    assert report["stage_counts"] == {"source_decode": 1}


def test_cli_run_executes_subprocess_json_handlers_for_full_batch(tmp_path: Path) -> None:
    command_source = tmp_path / "stage_command.py"
    command_source.write_text(
        "\n".join(
            [
                "import json",
                "import sys",
                "work = json.loads(sys.stdin.read())",
                "stage = work['stage']",
                "actors = {",
                "    'source_decode': 'deterministic_qa',",
                "    'detection_ownership': 'deterministic_qa',",
                "    'provider_tournament': 'segmentation_provider',",
                "    'hard_qc': 'deterministic_qa',",
                "    'primary_visual_review': 'visual_critic',",
                "    'independent_visual_review': 'visual_critic',",
                "    'repair_planning': 'visual_critic',",
                "    'repair_execution': 'segmentation_provider',",
                "    'package_freeze': 'deterministic_qa',",
                "    'certification': 'certificate_service',",
                "}",
                "details = {",
                "    'source_decode': {'decoded_pixel_sha256': 'a' * 64, 'alpha_policy': 'absent', 'width': 32, 'height': 32},",
                "    'detection_ownership': {'target_contract_sha256': 'a' * 64, 'person_count': 1, 'ownership_status': 'verified'},",
                "    'provider_tournament': {'tournament_report_sha256': 'a' * 64, 'family_count': 2, 'candidate_count': 2, 'winner_mask_sha256': 'a' * 64},",
                "    'hard_qc': {'qa_vector_sha256': 'a' * 64, 'hard_veto_count': 0},",
                "    'primary_visual_review': {'panel_sha256': 'a' * 64, 'critic_report_sha256': 'a' * 64, 'verdict': 'pass'},",
                "    'independent_visual_review': {'panel_sha256': 'a' * 64, 'critic_report_sha256': 'a' * 64, 'verdict': 'pass'},",
                "    'repair_planning': {'defect_hypothesis_sha256': 'a' * 64, 'roi_sha256': 'a' * 64, 'operation': 'box_refine'},",
                "    'repair_execution': {'parent_mask_sha256': 'a' * 64, 'new_mask_sha256': 'b' * 64, 'changed_pixel_fraction': 0.1},",
                "    'package_freeze': {'package_sha256': 'a' * 64, 'active_label_count': 1},",
                "    'certification': {'certificate_sha256': 'a' * 64, 'authority_tier': 'operationally_certified_artifact'},",
                "}",
                "print(json.dumps({'stage': stage, 'status': 'pass', 'actor_kind': actors[stage], 'evidence_sha256': 'a' * 64, 'detail': details[stage]}))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    base_spec = {
        "kind": "subprocess_json",
        "command": [sys.executable, str(command_source)],
        "timeout_seconds": 10,
    }
    command_hash = command_binding_sha256(base_spec)
    document = manifest(record_count=1)
    document["mission_id"] = "mission-cmd-0001"
    document["allowed_output_prefix"] = "missions/mission-cmd-0001"
    document["stage_versions"] = {stage: command_hash for stage in document["stage_versions"]}
    document = seal_manifest(document)
    manifest_path = tmp_path / "mission.json"
    records_path = tmp_path / "records.json"
    handlers_path = tmp_path / "handlers.json"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    records_path.write_text(
        json.dumps([{"record_id": "r1", "source_sha256": HEX, "input_payload_sha256": HEX}]),
        encoding="utf-8",
    )
    handlers_path.write_text(
        json.dumps(
            {
                "schema_version": "maskfactory.runpod_work_cell_handlers.v1",
                "handlers": {
                    stage: {**base_spec, "implementation_sha256": command_hash}
                    for stage in document["stage_versions"]
                },
            }
        ),
        encoding="utf-8",
    )

    env = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    root = tmp_path / "queue"
    cli = Path.cwd() / "tools" / "manage_runpod_autonomous_work_cell.py"
    for command in (
        ["--root", str(root), "admit", "--manifest", str(manifest_path)],
        [
            "--root",
            str(root),
            "seed",
            "--mission-id",
            document["mission_id"],
            "--records",
            str(records_path),
        ],
        [
            "--root",
            str(root),
            "run",
            "--mission-id",
            document["mission_id"],
            "--owner",
            "runpod-daemon",
            "--handlers",
            str(handlers_path),
        ],
    ):
        subprocess.run([sys.executable, str(cli), *command], check=True, env=env, cwd=Path.cwd())

    report = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                str(cli),
                "--root",
                str(root),
                "report",
                "--mission-id",
                document["mission_id"],
            ],
            env=env,
            cwd=Path.cwd(),
            text=True,
        )
    )
    assert report["mission_state"] == "complete"
    assert report["outcome_counts"] == {"accepted": 1}


def test_cli_run_rejects_subprocess_handler_binding_drift(tmp_path: Path) -> None:
    spec = {
        "kind": "subprocess_json",
        "command": [sys.executable, "-c", "print('{}')"],
        "timeout_seconds": 10,
    }
    document = manifest(record_count=1)
    command_hash = command_binding_sha256(spec)
    document["stage_versions"] = {stage: command_hash for stage in document["stage_versions"]}
    document = seal_manifest(document)
    manifest_path = tmp_path / "mission.json"
    records_path = tmp_path / "records.json"
    handlers_path = tmp_path / "handlers.json"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    records_path.write_text(
        json.dumps([{"record_id": "r1", "source_sha256": HEX, "input_payload_sha256": HEX}]),
        encoding="utf-8",
    )
    handlers_path.write_text(
        json.dumps(
            {
                "schema_version": "maskfactory.runpod_work_cell_handlers.v1",
                "handlers": {
                    stage: {**spec, "implementation_sha256": "f" * 64}
                    for stage in document["stage_versions"]
                },
            }
        ),
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    root = tmp_path / "queue"
    cli = Path.cwd() / "tools" / "manage_runpod_autonomous_work_cell.py"
    subprocess.run(
        [sys.executable, str(cli), "--root", str(root), "admit", "--manifest", str(manifest_path)],
        check=True,
        env=env,
        cwd=Path.cwd(),
    )
    subprocess.run(
        [
            sys.executable,
            str(cli),
            "--root",
            str(root),
            "seed",
            "--mission-id",
            document["mission_id"],
            "--records",
            str(records_path),
        ],
        check=True,
        env=env,
        cwd=Path.cwd(),
    )
    result = subprocess.run(
        [
            sys.executable,
            str(cli),
            "--root",
            str(root),
            "run",
            "--mission-id",
            document["mission_id"],
            "--owner",
            "runpod-daemon",
            "--handlers",
            str(handlers_path),
        ],
        env=env,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "command handler binding hash mismatch" in result.stderr


def test_prepare_builder_emits_artifacts_that_run_without_manual_json_handoff(
    tmp_path: Path,
) -> None:
    command_source = tmp_path / "stage_command.py"
    command_source.write_text(
        "\n".join(
            [
                "import json",
                "import sys",
                "work = json.loads(sys.stdin.read())",
                "stage = work['stage']",
                "actors = {",
                "    'source_decode': 'deterministic_qa',",
                "    'detection_ownership': 'deterministic_qa',",
                "    'provider_tournament': 'segmentation_provider',",
                "    'hard_qc': 'deterministic_qa',",
                "    'primary_visual_review': 'visual_critic',",
                "    'independent_visual_review': 'visual_critic',",
                "    'repair_planning': 'visual_critic',",
                "    'repair_execution': 'segmentation_provider',",
                "    'package_freeze': 'deterministic_qa',",
                "    'certification': 'certificate_service',",
                "}",
                "details = {",
                "    'source_decode': {'decoded_pixel_sha256': 'a' * 64, 'alpha_policy': 'absent', 'width': 32, 'height': 32},",
                "    'detection_ownership': {'target_contract_sha256': 'a' * 64, 'person_count': 1, 'ownership_status': 'verified'},",
                "    'provider_tournament': {'tournament_report_sha256': 'a' * 64, 'family_count': 2, 'candidate_count': 2, 'winner_mask_sha256': 'a' * 64},",
                "    'hard_qc': {'qa_vector_sha256': 'a' * 64, 'hard_veto_count': 0},",
                "    'primary_visual_review': {'panel_sha256': 'a' * 64, 'critic_report_sha256': 'a' * 64, 'verdict': 'pass'},",
                "    'independent_visual_review': {'panel_sha256': 'a' * 64, 'critic_report_sha256': 'a' * 64, 'verdict': 'pass'},",
                "    'repair_planning': {'defect_hypothesis_sha256': 'a' * 64, 'roi_sha256': 'a' * 64, 'operation': 'box_refine'},",
                "    'repair_execution': {'parent_mask_sha256': 'a' * 64, 'new_mask_sha256': 'b' * 64, 'changed_pixel_fraction': 0.1},",
                "    'package_freeze': {'package_sha256': 'a' * 64, 'active_label_count': 1},",
                "    'certification': {'certificate_sha256': 'a' * 64, 'authority_tier': 'operationally_certified_artifact'},",
                "}",
                "print(json.dumps({'stage': stage, 'status': 'pass', 'actor_kind': actors[stage], 'evidence_sha256': 'a' * 64, 'detail': details[stage]}))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    input_manifest = tmp_path / "input_manifest.json"
    input_manifest.write_text('{"shard":"canary"}\n', encoding="utf-8")
    handlers = {
        stage: {
            "kind": "subprocess_json",
            "command": [sys.executable, str(command_source)],
            "timeout_seconds": 10,
        }
        for stage in (
            "source_decode",
            "detection_ownership",
            "provider_tournament",
            "hard_qc",
            "primary_visual_review",
            "independent_visual_review",
            "repair_planning",
            "repair_execution",
            "package_freeze",
            "certification",
        )
    }
    role = {
        "status": "qualified",
        "model_id": "critic-a",
        "family": "family-a",
        "revision_sha256": HEX,
        "role_certificate_sha256": HEX,
        "revoked": False,
    }
    result = build_mission_artifacts(
        mission_id="mission-build-0001",
        input_manifest_path=input_manifest,
        records=[{"record_id": "r1", "source_sha256": HEX, "input_payload_sha256": HEX}],
        shard_count=1,
        bindings={
            "ontology_sha256": HEX,
            "target_contract_schema_sha256": HEX,
            "qa_threshold_registry_sha256": HEX,
            "provider_catalog_sha256": HEX,
            "critic_catalog_sha256": HEX,
            "certification_policy_sha256": HEX,
        },
        provider_bindings=[
            {
                "provider_id": "sam31",
                "family": "sam",
                "checkpoint_sha256": HEX,
                "runtime_sha256": HEX,
            },
            {
                "provider_id": "sam3d_body",
                "family": "sam3d",
                "checkpoint_sha256": HEX,
                "runtime_sha256": HEX,
            },
        ],
        role_bindings={
            "primary_visual_critic": role,
            "independent_juror": {**role, "model_id": "critic-b", "family": "family-b"},
        },
        handlers=handlers,
        output_dir=tmp_path / "mission_artifacts",
        authority_ceiling="operationally_certified_artifact",
    )
    assert Path(result["mission_path"]).is_file()
    assert Path(result["records_path"]).is_file()
    assert Path(result["handlers_path"]).is_file()

    env = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    root = tmp_path / "queue"
    cli = Path.cwd() / "tools" / "manage_runpod_autonomous_work_cell.py"
    for command in (
        ["--root", str(root), "admit", "--manifest", result["mission_path"]],
        [
            "--root",
            str(root),
            "seed",
            "--mission-id",
            "mission-build-0001",
            "--records",
            result["records_path"],
        ],
        [
            "--root",
            str(root),
            "run",
            "--mission-id",
            "mission-build-0001",
            "--owner",
            "runpod-daemon",
            "--handlers",
            result["handlers_path"],
        ],
    ):
        subprocess.run([sys.executable, str(cli), *command], check=True, env=env, cwd=Path.cwd())
    report = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                str(cli),
                "--root",
                str(root),
                "report",
                "--mission-id",
                "mission-build-0001",
            ],
            env=env,
            cwd=Path.cwd(),
            text=True,
        )
    )
    assert report["mission_state"] == "complete"
    assert report["outcome_counts"] == {"accepted": 1}


def _sha256_file_for_test(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()
