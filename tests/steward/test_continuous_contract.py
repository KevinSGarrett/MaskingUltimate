from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from maskfactory.steward.continuous_contract import (
    ACCEPTANCE_SCHEMA_PATH,
    AUTHORITY_PATHS,
    FREEZE_REGISTRY_PATH,
    ITEM_PATH,
    ITEM_PATHS,
    TELEMETRY_SCHEMA_PATH,
    ContinuousContractError,
    canonical_sha256,
    file_sha256,
    read_json,
    validate_campaign_document,
    validate_freeze_registry,
)

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def valid_telemetry() -> dict:
    return {
        "schema_version": "maskfactory_self_hosted_autonomy_campaign_telemetry.v1",
        "campaign_id": "engineering-campaign-001",
        "campaign_kind": "engineering",
        "campaign_payload_sha256": H1,
        "source_commit_sha256": H2,
        "started_at": "2026-07-26T06:00:00Z",
        "ended_at": "2026-07-26T07:00:00Z",
        "counts": {
            "planned": 25,
            "eligible": 25,
            "completed": 25,
            "autonomously_prepared": 22,
            "accepted": 20,
        },
        "codex": {
            "interventions": 1,
            "routine_handoffs": 1,
            "review_seconds": 180,
            "baseline_usage_units_per_accepted_artifact": 100,
            "observed_usage_units_per_accepted_artifact": 25,
        },
        "timing": {
            "model_startup_seconds": 180,
            "inference_seconds": 900,
            "idle_gpu_seconds": 0,
            "local_gpu_work_cells": 1,
            "local_gpu_released_work_cells": 1,
        },
        "routes": {
            "local_pod": 20,
            "serverless": 0,
            "openrouter_advisory": 0,
            "cpu_safe": 5,
            "fallback_reasons": [],
        },
        "integrity": {
            "duplicate_inference_submissions": 0,
            "duplicate_promotions": 0,
            "admitted_missions": 25,
            "terminally_reconciled_missions": 25,
            "submitted_unknown_events": 0,
            "recovery_required_events": 1,
            "recovery_resolved_events": 1,
            "authority_bypasses": 0,
        },
        "engineering": {
            "patch_attempts": 20,
            "focused_test_runs": 25,
            "repair_attempts": 3,
            "repair_exhaustions": 0,
        },
        "masks": {
            "accept": 0,
            "repair": 0,
            "abstain": 0,
            "reject": 0,
            "quarantine": 0,
            "hard_qa_vetoes": 0,
            "critic_disagreements": 0,
        },
        "artifacts": {
            "produced": 25,
            "accepted": 20,
            "gpu_hours": 0.3,
            "accepted_per_gpu_hour": 66.6667,
        },
        "event_sha256": [H3, H4],
        "limitations": ["Bounded engineering campaign; no mask authority claimed."],
    }


def valid_acceptance(*, production: bool = False) -> dict:
    gates = {
        "authority_bytes_frozen": production,
        "schemas_closed": production,
        "real_engineering_campaign": production,
        "real_mask_campaign": production,
        "three_consecutive_target_campaigns": production,
        "recovery_and_routing_drills": production,
        "visual_authority_qualified": production,
        "zero_duplicates": production,
        "full_terminal_reconciliation": production,
        "full_local_gpu_release": production,
        "codex_reduction_target": production,
        "no_authority_bypass": production,
    }
    return {
        "schema_version": "maskfactory_self_hosted_autonomy_acceptance.v1",
        "acceptance_id": "continuous-autonomy-acceptance-001",
        "created_at": "2026-07-26T07:00:00Z",
        "throughput_claim": (
            "PRODUCTION_EVIDENCE_PASS"
            if production
            else "SELF_HOSTED_AUTONOMOUS_LLM_THROUGHPUT_INCOMPLETE"
        ),
        "authority_freeze_sha256": H1,
        "source_commit_sha256": H2,
        "telemetry_schema_sha256": H3,
        "acceptance_schema_sha256": H4,
        "campaign_telemetry_sha256": [H1],
        "evidence": {
            "engineering_campaign_missions": 25 if production else 0,
            "mask_campaign_records": 100 if production else 0,
            "consecutive_target_mixed_campaigns": 3 if production else 0,
            "interruption_drill_passed": production,
            "routing_fault_drill_passed": production,
            "persisted_terminal_adoption_passed": production,
            "unresolved_ambiguity_blocked_resend": production,
            "qualified_primary_visual_critic": production,
            "qualified_independent_family_juror": production,
            "clean_reconstruction_passed": production,
            "operating_procedure_sha256": H2,
            "consolidated_packet_sha256": H3,
        },
        "metrics": {
            "autonomously_prepared_fraction": 0.8 if production else 0,
            "routine_handoffs_per_campaign_bound": 1 if production else 0,
            "codex_usage_reduction_fraction": 0.7 if production else 0,
            "duplicate_inference_submissions": 0,
            "duplicate_promotions": 0,
            "terminal_reconciliation_fraction": 1 if production else 0,
            "local_gpu_release_fraction": 1 if production else 0,
            "authority_bypasses": 0,
        },
        "acceptance_gates": gates,
        "codex_recommendation": "ADOPT" if production else "PARTIALLY_ADOPT",
        "authority_claimed": {
            "git": False,
            "tracker_completion": False,
            "infrastructure": False,
            "credentials": False,
            "final_mask": False,
            "final_adoption": False,
        },
        "limitations": ([] if production else ["Required real campaigns have not yet passed."]),
    }


def copy_frozen_contract(target_root: Path) -> None:
    source_root = repo_root()
    registry = read_json(source_root / FREEZE_REGISTRY_PATH)
    paths = [
        FREEZE_REGISTRY_PATH.as_posix(),
        *[row["path"] for row in registry["authority_files"]],
        *[row["path"] for row in registry["schema_files"]],
    ]
    for relative in paths:
        destination = target_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / relative, destination)


def refresh_registry_binding(target_root: Path, relative: str) -> None:
    registry_path = target_root / FREEZE_REGISTRY_PATH
    registry = read_json(registry_path)
    rows = [*registry["authority_files"], *registry["schema_files"]]
    row = next(candidate for candidate in rows if candidate["path"] == relative)
    row["sha256"] = file_sha256(target_root / relative)
    unsigned = dict(registry)
    unsigned.pop("registry_sha256")
    registry["registry_sha256"] = canonical_sha256(unsigned)
    registry_path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_frozen_authority_schemas_and_item_ids_have_no_drift() -> None:
    root = repo_root()

    assert validate_freeze_registry(root) == []
    registry = read_json(root / FREEZE_REGISTRY_PATH)
    assert len(registry["item_ids"]) == 40
    assert len(registry["item_ids"]) == len(set(registry["item_ids"]))
    assert {row["path"] for row in registry["authority_files"]} == {
        path.as_posix() for path in AUTHORITY_PATHS
    }
    assert {row["path"] for row in registry["schema_files"]} == {
        TELEMETRY_SCHEMA_PATH.as_posix(),
        ACCEPTANCE_SCHEMA_PATH.as_posix(),
    }
    assert {path.as_posix() for path in ITEM_PATHS}.issubset(
        {row["path"] for row in registry["authority_files"]}
    )


def test_stale_authority_hash_fails_closed(tmp_path: Path) -> None:
    copy_frozen_contract(tmp_path)
    plan = tmp_path / "Plan/27_SELF_HOSTED_AUTONOMOUS_LLM_CONTINUOUS_OPERATIONS_SPEC.md"
    plan.write_text(plan.read_text(encoding="utf-8") + "\nstale mutation\n", encoding="utf-8")

    problems = validate_freeze_registry(tmp_path)

    assert any("stale hash" in problem and "Plan/27_" in problem for problem in problems)


def test_stale_schema_hash_fails_closed(tmp_path: Path) -> None:
    copy_frozen_contract(tmp_path)
    schema = tmp_path / TELEMETRY_SCHEMA_PATH
    schema.write_text(schema.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    problems = validate_freeze_registry(tmp_path)

    assert any(
        "stale hash" in problem and TELEMETRY_SCHEMA_PATH.as_posix() in problem
        for problem in problems
    )


def test_missing_authority_cross_reference_fails_with_refreshed_hash(
    tmp_path: Path,
) -> None:
    copy_frozen_contract(tmp_path)
    relative = AUTHORITY_PATHS[0].as_posix()
    authority = tmp_path / relative
    original = authority.read_text(encoding="utf-8")
    mutated = original.replace(
        FREEZE_REGISTRY_PATH.as_posix(),
        "configs/removed_contract_freeze_reference.json",
    )
    assert mutated != original
    authority.write_text(mutated, encoding="utf-8")
    refresh_registry_binding(tmp_path, relative)

    problems = validate_freeze_registry(tmp_path)

    assert any(
        "misses cross-references" in problem and FREEZE_REGISTRY_PATH.as_posix() in problem
        for problem in problems
    )


def test_duplicate_authority_item_id_fails_with_refreshed_hash(
    tmp_path: Path,
) -> None:
    copy_frozen_contract(tmp_path)
    relative = ITEM_PATH.as_posix()
    authority = tmp_path / relative
    authority.write_text(
        authority.read_text(encoding="utf-8") + "\n- [ ] MF-P6-13.01 duplicate authority fixture\n",
        encoding="utf-8",
    )
    refresh_registry_binding(tmp_path, relative)

    problems = validate_freeze_registry(tmp_path)

    assert "P6 item authority contains duplicate item IDs" in problems


def test_registry_requires_exact_authority_path_set(tmp_path: Path) -> None:
    copy_frozen_contract(tmp_path)
    registry_path = tmp_path / FREEZE_REGISTRY_PATH
    registry = read_json(registry_path)
    replacement = Path("Plan/unexpected_continuous_authority.md")
    replacement_path = tmp_path / replacement
    replacement_path.parent.mkdir(parents=True, exist_ok=True)
    replacement_path.write_text(
        "\n".join(
            (
                FREEZE_REGISTRY_PATH.as_posix(),
                TELEMETRY_SCHEMA_PATH.as_posix(),
                ACCEPTANCE_SCHEMA_PATH.as_posix(),
            )
        ),
        encoding="utf-8",
    )
    registry["authority_files"][0] = {
        "path": replacement.as_posix(),
        "sha256": file_sha256(replacement_path),
    }
    unsigned = dict(registry)
    unsigned.pop("registry_sha256")
    registry["registry_sha256"] = canonical_sha256(unsigned)
    registry_path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    problems = validate_freeze_registry(tmp_path)

    assert "freeze authority_files do not match the closed v1 authority set" in problems


def test_duplicate_registry_item_id_fails_even_with_valid_self_hash(
    tmp_path: Path,
) -> None:
    copy_frozen_contract(tmp_path)
    registry_path = tmp_path / FREEZE_REGISTRY_PATH
    registry = read_json(registry_path)
    registry["item_ids"].append(registry["item_ids"][-1])
    unsigned = dict(registry)
    unsigned.pop("registry_sha256")
    registry["registry_sha256"] = canonical_sha256(unsigned)
    registry_path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    problems = validate_freeze_registry(tmp_path)

    assert "freeze item_ids contains duplicates" in problems


def test_closed_telemetry_schema_accepts_complete_document_and_rejects_unknown() -> None:
    root = repo_root()
    telemetry = valid_telemetry()

    validate_campaign_document(root, telemetry, kind="telemetry")
    telemetry["unexpected"] = True

    with pytest.raises(ContinuousContractError, match="Additional properties"):
        validate_campaign_document(root, telemetry, kind="telemetry")


def test_acceptance_schema_keeps_throughput_claim_fail_closed() -> None:
    root = repo_root()
    incomplete = valid_acceptance()
    production = valid_acceptance(production=True)

    validate_campaign_document(root, incomplete, kind="acceptance")
    validate_campaign_document(root, production, kind="acceptance")
    unsafe = deepcopy(production)
    unsafe["acceptance_gates"]["full_local_gpu_release"] = False

    with pytest.raises(ContinuousContractError, match="True was expected"):
        validate_campaign_document(root, unsafe, kind="acceptance")


def test_acceptance_schema_rejects_authority_widening() -> None:
    acceptance = valid_acceptance()
    acceptance["authority_claimed"]["git"] = True

    with pytest.raises(ContinuousContractError, match="False was expected"):
        validate_campaign_document(repo_root(), acceptance, kind="acceptance")
