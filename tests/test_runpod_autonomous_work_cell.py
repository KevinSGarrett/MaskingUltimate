from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from maskfactory.autonomy.work_cell import (
    AutonomousWorkCell,
    WorkCellError,
    seal_manifest,
    validate_mission_manifest,
)

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


def receipt(stage: str, actor: str, status: str = "pass") -> dict[str, str]:
    return {
        "stage": stage,
        "status": status,
        "actor_kind": actor,
        "evidence_sha256": HEX,
    }


def test_schemas_are_closed_and_valid() -> None:
    root = Path("src/maskfactory/schemas")
    for name in (
        "runpod_autonomous_mission.schema.json",
        "runpod_autonomous_mission_report.schema.json",
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
    assert report["milestones"][0]["terminal_record_count"] == 1
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
