from __future__ import annotations

import copy
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from maskfactory.completion_bundle import (
    DEFAULT_POLICY,
    POLICY_DOCUMENT_SHA256,
    POLICY_SHA256,
    CompletionBundleError,
    build_report,
    canonical_sha256,
    file_sha256,
    load_policy,
    validate_policy,
    verify_report,
)
from maskfactory.validation import validate_document

ROOT = Path(__file__).resolve().parents[1]
FIXED_NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def _seal(document: dict) -> dict:
    document["sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    return document


def _write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")


def _passing_measurements(requirement: dict) -> dict:
    values = {}
    for name, rule in requirement["measurement_rules"].items():
        values[name] = rule["value"]
    if "tests_collected" in values:
        values["tests_collected"] = 1376
        values["tests_passed"] = 1376
    return values


def _tracker() -> dict:
    items = {
        f"MF-FIXTURE-{index:04d}": {"status": "complete", "orphaned": False} for index in range(754)
    }
    items["MF-P7-07.09"] = {"status": "open", "orphaned": False}
    return {
        "meta": {"fixture": True},
        "items": items,
        "dod": {f"D{index}": {"status": "met"} for index in range(1, 12)},
        "goals": {f"G{index}": {"status": "met"} for index in range(1, 10)},
    }


def _input(
    tmp_path: Path,
    *,
    created_at: datetime = FIXED_NOW,
) -> tuple[dict, dict]:
    policy = load_policy()
    tracker_path = tmp_path / "tracker.json"
    _write_json(tracker_path, _tracker())
    receipts = []
    for domain, requirement in policy["required_domains"].items():
        artifacts = []
        for index in range(requirement["minimum_source_artifacts"]):
            path = tmp_path / "evidence" / domain / f"source_{index}.json"
            _write_json(
                path,
                {
                    "schema_version": "1.0.0",
                    "domain": domain,
                    "source_index": index,
                    "result": "pass",
                    "evidence_class": "real_operation",
                },
            )
            artifacts.append(
                {"path": path.relative_to(tmp_path).as_posix(), "sha256": file_sha256(path)}
            )
        receipt = _seal(
            {
                "schema_version": "1.0.0",
                "domain": domain,
                "evidence_id": f"{domain}-fixture-live-receipt",
                "observed_at": (created_at - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                "evidence_class": "real_operation",
                "result": "pass",
                "verifier_id": requirement["verifier_id"],
                "verifier_version": "fixture-verifier-1.0.0",
                "source_artifacts": artifacts,
                "measurements": _passing_measurements(requirement),
                "authority": "primary_domain_evidence",
            }
        )
        receipts.append(receipt)
    document = _seal(
        {
            "schema_version": "1.0.0",
            "bundle_id": "maskfactory-modernization-fixture",
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "policy_sha256": policy["sha256"],
            "tracker": {
                "path": tracker_path.relative_to(tmp_path).as_posix(),
                "sha256": file_sha256(tracker_path),
            },
            "evidence_receipts": receipts,
        }
    )
    return document, policy


def _receipt(document: dict, domain: str) -> dict:
    return next(row for row in document["evidence_receipts"] if row["domain"] == domain)


def _rewrite_tracker(document: dict, tmp_path: Path, mutation) -> None:
    path = tmp_path / document["tracker"]["path"]
    tracker = json.loads(path.read_text())
    mutation(tracker)
    _write_json(path, tracker)
    document["tracker"]["sha256"] = file_sha256(path)
    _seal(document)


def test_frozen_policy_has_every_completion_domain_and_current_schemas() -> None:
    policy = load_policy()
    assert DEFAULT_POLICY == ROOT / "qa/governance/completion/modernization_completion_v1.json"
    assert file_sha256(DEFAULT_POLICY) == POLICY_DOCUMENT_SHA256
    assert policy["sha256"] == POLICY_SHA256
    assert policy["completion_scope"] == "legacy_portfolio_research_evidence"
    assert policy["blocking_for_core_completion"] is False
    assert policy["core_completion_authority"] == "none"
    assert len(policy["required_domains"]) == 15
    assert set(policy["tracker_requirements"]["required_definition_of_done_ids"]) == {
        f"D{index}" for index in range(1, 12)
    }
    assert set(policy["tracker_requirements"]["required_goal_ids"]) == {
        f"G{index}" for index in range(1, 10)
    }
    for name in (
        "completion_bundle_policy",
        "completion_bundle_input",
        "completion_bundle_report",
    ):
        schema = json.loads((ROOT / f"src/maskfactory/schemas/{name}.schema.json").read_text())
        Draft202012Validator.check_schema(schema)


def test_complete_real_evidence_index_recomputes_and_denies_primary_authority(
    tmp_path: Path,
) -> None:
    document, policy = _input(tmp_path)
    report = build_report(
        document,
        policy=policy,
        artifact_root=tmp_path,
        now=FIXED_NOW,
    )
    assert validate_document(document, "completion_bundle_input") == ()
    assert validate_document(report, "completion_bundle_report") == ()
    assert report["result"] == "pass"
    assert report["required_domain_count"] == 15
    assert report["tracker_item_count"] == 755
    assert report["unresolved_item_count_excluding_bundle"] == 0
    assert report["definitions_of_done_met"] == 11 and report["goals_met"] == 9
    assert report["completion_scope"] == "legacy_portfolio_research_evidence"
    assert report["blocking_for_core_completion"] is False
    assert report["core_completion_authority"] == "none"
    assert report["authority"] == (
        "legacy_portfolio_evidence_index_verified_no_core_completion_authority"
    )


def test_current_live_tracker_cannot_yet_support_legacy_portfolio_bundle(tmp_path: Path) -> None:
    document, policy = _input(tmp_path)
    live = tmp_path / "live_tracker.json"
    live.write_bytes((ROOT / "Plan/Tracker/tracker.json").read_bytes())
    document["tracker"] = {"path": live.name, "sha256": file_sha256(live)}
    _seal(document)
    with pytest.raises(CompletionBundleError, match="unresolved items"):
        build_report(
            document,
            policy=policy,
            artifact_root=tmp_path,
            now=FIXED_NOW,
        )


def test_missing_duplicate_or_unknown_domain_fails(tmp_path: Path) -> None:
    document, policy = _input(tmp_path)
    document["evidence_receipts"].pop()
    _seal(document)
    with pytest.raises(CompletionBundleError, match="domain coverage"):
        build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)
    document, policy = _input(tmp_path)
    document["evidence_receipts"][1]["domain"] = document["evidence_receipts"][0]["domain"]
    _seal(document["evidence_receipts"][1])
    _seal(document)
    with pytest.raises(CompletionBundleError, match="invalid or duplicated"):
        build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("evidence_class", "synthetic_fixture", "identity or authority"),
        ("result", "fail", "identity or authority"),
        ("authority", "pre_result_contract", "identity or authority"),
        ("verifier_id", "self_asserted", "identity or authority"),
    ],
)
def test_synthetic_failed_or_self_asserted_receipt_fails(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    document, policy = _input(tmp_path)
    receipt = _receipt(document, "doctor")
    receipt[field] = value
    _seal(receipt)
    _seal(document)
    with pytest.raises(CompletionBundleError, match=message):
        build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)


def test_stale_or_future_dated_receipt_fails(tmp_path: Path) -> None:
    document, policy = _input(tmp_path)
    receipt = _receipt(document, "doctor")
    receipt["observed_at"] = (FIXED_NOW - timedelta(hours=25)).isoformat()
    _seal(receipt)
    _seal(document)
    with pytest.raises(CompletionBundleError, match="future-dated or stale"):
        build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)
    document, policy = _input(tmp_path)
    receipt = _receipt(document, "doctor")
    receipt["observed_at"] = (FIXED_NOW + timedelta(seconds=1)).isoformat()
    _seal(receipt)
    _seal(document)
    with pytest.raises(CompletionBundleError, match="future-dated or stale"):
        build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)


def test_source_artifact_missing_escape_hash_drift_and_cross_domain_reuse_fail(
    tmp_path: Path,
) -> None:
    document, policy = _input(tmp_path)
    receipt = _receipt(document, "doctor")
    receipt["source_artifacts"][0]["path"] = "missing.json"
    _seal(receipt)
    _seal(document)
    with pytest.raises(CompletionBundleError, match="does not exist"):
        build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)
    document, policy = _input(tmp_path)
    receipt = _receipt(document, "doctor")
    receipt["source_artifacts"][0]["path"] = "../escape.json"
    _seal(receipt)
    _seal(document)
    with pytest.raises(CompletionBundleError, match="escaped"):
        build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)
    document, policy = _input(tmp_path)
    receipt = _receipt(document, "doctor")
    receipt["source_artifacts"][0]["sha256"] = "f" * 64
    _seal(receipt)
    _seal(document)
    with pytest.raises(CompletionBundleError, match="hash drift"):
        build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)
    document, policy = _input(tmp_path)
    first = _receipt(document, "doctor")["source_artifacts"][0]
    second = _receipt(document, "live_provider_smokes")
    second["source_artifacts"][0] = copy.deepcopy(first)
    _seal(second)
    _seal(document)
    with pytest.raises(CompletionBundleError, match="cannot satisfy multiple"):
        build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)


@pytest.mark.parametrize(
    ("domain", "measurement", "bad_value"),
    [
        ("doctor", "fail_count", 1),
        ("live_provider_smokes", "live_hardware", False),
        ("runtime_matrix", "source_only_family_count", 1),
        ("frozen_benchmarks", "human_anchor_truth_only", False),
        ("cvat_rollback", "exact_state_restored", False),
        ("autonomy_certificate", "human_anchor_audit_count", 299),
        ("autonomy_revocation", "serving_eligibility_removed", False),
        ("retraining_lifecycle", "new_fingerprint_proven", False),
        ("single_person_headline", "image_count", 19),
        ("multi_person_headline", "cross_instance_bleed_failures", 1),
        ("signed_currency_review", "review_status_pass", False),
    ],
)
def test_every_primary_completion_family_fails_its_frozen_gate(
    tmp_path: Path, domain: str, measurement: str, bad_value
) -> None:
    document, policy = _input(tmp_path)
    receipt = _receipt(document, domain)
    receipt["measurements"][measurement] = bad_value
    _seal(receipt)
    _seal(document)
    with pytest.raises(CompletionBundleError, match="failed frozen rule"):
        build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)


def test_test_suite_requires_collected_equal_passed(tmp_path: Path) -> None:
    document, policy = _input(tmp_path)
    receipt = _receipt(document, "test_suite")
    receipt["measurements"]["tests_passed"] -= 1
    _seal(receipt)
    _seal(document)
    with pytest.raises(CompletionBundleError, match="collected and passed counts differ"):
        build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)


def test_tracker_requires_every_other_item_terminal(tmp_path: Path) -> None:
    document, policy = _input(tmp_path)
    _rewrite_tracker(
        document,
        tmp_path,
        lambda tracker: tracker["items"]["MF-FIXTURE-0000"].update(status="blocked"),
    )
    with pytest.raises(CompletionBundleError, match="unresolved items"):
        build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)


def test_tracker_requires_d1_d11_and_g1_g9_measured(tmp_path: Path) -> None:
    document, policy = _input(tmp_path)
    _rewrite_tracker(
        document,
        tmp_path,
        lambda tracker: tracker["dod"]["D11"].update(status="pending"),
    )
    with pytest.raises(CompletionBundleError, match="Definitions of Done"):
        build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)
    document, policy = _input(tmp_path)
    _rewrite_tracker(
        document,
        tmp_path,
        lambda tracker: tracker["goals"]["G9"].update(status="pending"),
    )
    with pytest.raises(CompletionBundleError, match="measured goals"):
        build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)


def test_tracker_receipt_must_equal_recomputed_tracker(tmp_path: Path) -> None:
    document, policy = _input(tmp_path)
    receipt = _receipt(document, "tracker_validation")
    receipt["measurements"]["tracker_item_count"] = 756
    _seal(receipt)
    _seal(document)
    with pytest.raises(CompletionBundleError, match="does not match live tracker"):
        build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)


def test_policy_tamper_and_extra_tracker_exclusion_fail(tmp_path: Path) -> None:
    policy = load_policy()
    unsafe_core_gate = copy.deepcopy(policy)
    unsafe_core_gate["blocking_for_core_completion"] = True
    unsafe_core_gate["core_completion_authority"] = "self_asserted"
    _seal(unsafe_core_gate)
    with pytest.raises(CompletionBundleError, match="policy identity is invalid"):
        validate_policy(unsafe_core_gate, expected_sha256=None)

    tampered = copy.deepcopy(policy)
    tampered["required_domains"]["doctor"]["maximum_age_hours"] = 999
    with pytest.raises(CompletionBundleError, match="policy hash mismatch"):
        validate_policy(tampered)
    _seal(tampered)
    with pytest.raises(CompletionBundleError, match="locked hash mismatch"):
        validate_policy(tampered)
    tampered = copy.deepcopy(policy)
    tampered["tracker_requirements"]["excluded_item_ids"].append("MF-P7-EXIT")
    _seal(tampered)
    with pytest.raises(CompletionBundleError, match="only the completion-bundle"):
        validate_policy(tampered, expected_sha256=None)


def test_governing_source_drift_fails(tmp_path: Path) -> None:
    policy = load_policy()
    for relative in policy["governing_source_hashes"]:
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    (tmp_path / "Plan/20_PROGRESSIVE_AUTONOMOUS_MASK_FACTORY_SPEC.md").write_text(
        "drift\n", encoding="utf-8"
    )
    with pytest.raises(CompletionBundleError, match="governing source hash drift"):
        validate_policy(policy, root=tmp_path, expected_sha256=None)


def test_report_and_input_tamper_fail(tmp_path: Path) -> None:
    document, policy = _input(tmp_path)
    report = build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)
    report["goals_met"] = 8
    with pytest.raises(CompletionBundleError, match="does not recompute exactly"):
        verify_report(
            report,
            document,
            policy=policy,
            artifact_root=tmp_path,
            now=FIXED_NOW,
        )
    document["bundle_id"] = "tampered"
    with pytest.raises(CompletionBundleError, match="input hash mismatch"):
        build_report(document, policy=policy, artifact_root=tmp_path, now=FIXED_NOW)


def test_cli_build_and_verify_round_trip(tmp_path: Path) -> None:
    current = datetime.now(UTC)
    document, _ = _input(tmp_path, created_at=current)
    input_path = tmp_path / "input.json"
    report_path = tmp_path / "report.json"
    _write_json(input_path, document)
    command = [
        sys.executable,
        str(ROOT / "tools/completion_bundle_report.py"),
        str(input_path),
        "--output",
        str(report_path),
        "--root",
        str(ROOT),
        "--artifact-root",
        str(tmp_path),
    ]
    built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert built.returncode == 0, built.stderr
    verified = subprocess.run(
        command + ["--verify"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert verified.returncode == 0, verified.stderr
    assert json.loads(report_path.read_text())["result"] == "pass"
