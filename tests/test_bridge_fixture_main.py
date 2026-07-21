"""Focused tests: fixture Main closes producer verify loops honestly."""

from __future__ import annotations

import json
from pathlib import Path

from maskfactory.bridge.external_adapter_conformance import (
    build_external_adapter_conformance_evidence,
)
from maskfactory.bridge.fixture_main import (
    AUTHORITY_KIND,
    CONSUMER_KIND,
    SYNTHETIC_MAIN_GIT_COMMIT,
    FixtureMainRuntime,
    materialize_fixture_main,
    run_fixture_main_producer_verify,
)
from maskfactory.bridge.main_consumer_conformance import (
    run_main_consumer_conformance_harness,
    validate_main_consumer_conformance_evidence,
)
from maskfactory.bridge.receipt_arbitration_conformance import (
    validate_receipt_arbitration_conformance_evidence,
)

ROOT = Path(__file__).resolve().parents[1]


def test_fixture_main_materializes_inbox_and_related_evidence(tmp_path: Path) -> None:
    index = materialize_fixture_main(repo_root=tmp_path)
    assert index["authority_kind"] == AUTHORITY_KIND
    assert index["consumer_kind"] == CONSUMER_KIND
    assert index["synthetic_main_git_commit"] == SYNTHETIC_MAIN_GIT_COMMIT
    assert index["claim_boundary"]["production_main_adoption_complete"] is False
    assert index["claim_boundary"]["claims_kevin_sgarrett_comfy_ui_main_production_commit"] is False

    inbox = tmp_path / "runtime_artifacts" / "main_consumer_conformance" / "inbox"
    for name in (
        "adoption_receipt.json",
        "adapter_observation.json",
        "requirements_capability_bundle.json",
    ):
        assert (inbox / name).is_file()

    related = tmp_path / "runtime_artifacts" / "main_consumer_conformance"
    for relative in (
        "fixture_main_claim_boundary.json",
        "arbitration/main_decision.json",
        "arbitration/conformance_evidence.json",
        "journal/checkpoint_bundle.json",
        "failure_control/observation.json",
        "failure_control/fault_injection_evidence.json",
        "recovery/restart_marker.json",
        "comfyui/result_history_receipt.json",
        "fixture_main_materialization_index.json",
    ):
        assert (related / relative).is_file()

    receipt = json.loads((inbox / "adoption_receipt.json").read_text(encoding="utf-8"))
    assert receipt["consumer"]["git_commit"] == SYNTHETIC_MAIN_GIT_COMMIT
    assert receipt["signature"]["key_id"] == "comfy-main-adoption-fixture"
    assert receipt["decision"] == "adopted"


def test_fixture_main_closes_main_consumer_harness_without_adoption_claim(
    tmp_path: Path,
) -> None:
    materialize_fixture_main(repo_root=tmp_path)
    inbox = tmp_path / "runtime_artifacts" / "main_consumer_conformance" / "inbox"
    evidence = run_main_consumer_conformance_harness(main_artifact_root=inbox)
    assert evidence["status"] == "accepted"
    assert evidence["main_artifacts_present"] is True
    assert evidence["main_adoption_complete"] is False
    assert evidence["rejection_reasons"] == ["eligible"]
    assert validate_main_consumer_conformance_evidence(evidence) == ()


def test_fixture_main_adapter_observation_is_accepted(tmp_path: Path) -> None:
    runtime = FixtureMainRuntime(repo_root=tmp_path)
    observation = runtime.build_adapter_observation()
    evidence = build_external_adapter_conformance_evidence(
        observation, decided_at="2026-07-19T15:00:00Z"
    )
    assert evidence["status"] == "accepted"
    assert observation["adapter_identity"]["git_commit"] == SYNTHETIC_MAIN_GIT_COMMIT


def test_fixture_main_arbitration_decision_matches_oracle(tmp_path: Path) -> None:
    runtime = FixtureMainRuntime(repo_root=tmp_path)
    bundle = runtime.build_arbitration_bundle()
    evidence = bundle["evidence"]
    assert evidence["status"] == "accepted"
    assert validate_receipt_arbitration_conformance_evidence(evidence) == ()
    assert bundle["main_decision"]["signature"]["key_id"] == "comfy-main-adoption-fixture"
    assert bundle["main_decision"]["claim_boundary"]["authority_kind"] == AUTHORITY_KIND


def test_fixture_main_producer_verify_loops_all_pass(tmp_path: Path) -> None:
    evidence = run_fixture_main_producer_verify(repo_root=tmp_path)
    assert evidence["status"] == "accepted"
    assert evidence["authority_kind"] == AUTHORITY_KIND
    assert evidence["consumer_kind"] == CONSUMER_KIND
    assert evidence["claim_boundary"]["production_core_close_authorized"] is False
    assert evidence["claim_boundary"]["closed_fixture_producer_verify_complete"] is True
    assert evidence["harness"]["main_adoption_complete"] is False
    failed = [item for item, row in evidence["loops"].items() if not row["passed"]]
    assert failed == [], failed
    out = (
        tmp_path
        / "runtime_artifacts"
        / "main_consumer_conformance"
        / "fixture_main_producer_verify_evidence.json"
    )
    assert out.is_file()


def test_fixture_main_rejects_production_commit_impersonation(tmp_path: Path) -> None:
    runtime = FixtureMainRuntime(repo_root=tmp_path)
    boundary = runtime.claim_boundary()
    assert boundary["claims_kevin_sgarrett_comfy_ui_main_production_commit"] is False
    assert boundary["trusted_keys_usage_scope"] == "conformance_only"
    # Synthetic commit is deterministic and not an all-ones/all-zeros placeholder alone.
    assert len(SYNTHETIC_MAIN_GIT_COMMIT) == 40
    assert SYNTHETIC_MAIN_GIT_COMMIT != "0" * 40
