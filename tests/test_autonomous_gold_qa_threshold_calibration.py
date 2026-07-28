import hashlib
import json

import pytest

from maskfactory.autonomy.qa_threshold_calibration import (
    QaThresholdCalibrationError,
    build_calibration_report,
)
from maskfactory.autonomy.qa_thresholds import expand_registry
from maskfactory.validation import validate_document


def _sha(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _policy(**overrides: object) -> dict:
    body = {
        "policy_id": "qa-threshold-calibration-fixture-v1",
        "frozen_at": "2026-07-22T00:00:00Z",
        "minimum_calibration_positive_per_label": 1,
        "minimum_calibration_negative_per_label": 1,
        "minimum_holdout_positive_per_label": 1,
        "minimum_holdout_negative_per_label": 1,
        "required_domains": ["photographic"],
        "required_risks": ["small_part"],
        "required_size_buckets": ["small"],
    }
    body.update(overrides)
    return {**body, "policy_sha256": _sha(body)}


def _record(
    index: int,
    *,
    label: str = "hair",
    partition: str = "calibration",
    outcome: str = "positive",
    source: str | None = None,
) -> dict:
    return {
        "record_id": f"record-{index}",
        "partition": partition,
        "source_sha256": source or f"{index + 1:064x}",
        "package_sha256": f"{index + 1000:064x}",
        "label": label,
        "contexts": ["default"],
        "domain": "photographic",
        "risks": ["small_part"],
        "size_bucket": "small",
        "expected_outcome": outcome,
        "reference_authority": "qualified_external_supervision",
        "measured_at": "2026-07-23T00:00:00Z",
        "qa_vector_sha256": f"{index + 2000:064x}",
    }


def test_sparse_evidence_is_valid_but_non_authorizing_and_reports_all_gaps():
    result = build_calibration_report(
        calibration_run_id="sparse-fixture",
        policy=_policy(),
        records=[_record(1)],
    )
    assert not validate_document(result, "autonomous_gold_qa_threshold_calibration")
    assert result["report"]["status"] == "insufficient_evidence"
    assert result["report"]["authority_claim"] == ("calibration_candidate_only_not_gold_authority")
    assert result["registry_binding"]["authority_eligible"] is False
    assert "left_breast" in result["report"]["missing"]["labels"]
    assert "hair:calibration_negative" in result["report"]["missing"]["label_partition_counts"]


def test_complete_fixture_can_only_be_ready_for_holdout_not_gold_authority():
    records = []
    index = 1
    for label in sorted(row["label"] for row in expand_registry()["labels"]):
        for partition in ("calibration", "qualification_holdout"):
            for outcome in ("positive", "negative"):
                records.append(_record(index, label=label, partition=partition, outcome=outcome))
                index += 1
    records[0]["contexts"] = [
        "default",
        "crop_edge",
        "multi_person_overlap",
        "occlusion_contact",
        "out_of_frame",
        "thin_structure",
    ]
    result = build_calibration_report(
        calibration_run_id="complete-fixture",
        policy=_policy(),
        records=records,
    )
    assert result["report"]["status"] == "ready_for_qualification_holdout"
    assert result["report"]["missing"] == {
        "labels": [],
        "contexts": [],
        "domains": [],
        "risks": [],
        "size_buckets": [],
        "label_partition_counts": [],
    }
    assert result["registry_binding"]["authority_eligible"] is False


def test_cross_partition_source_or_package_leakage_fails_closed():
    records = [
        _record(1, partition="calibration", source="a" * 64),
        _record(2, partition="qualification_holdout", source="a" * 64),
    ]
    with pytest.raises(QaThresholdCalibrationError, match="leakage"):
        build_calibration_report(
            calibration_run_id="leaked-source",
            policy=_policy(),
            records=records,
        )
    records[1]["source_sha256"] = "b" * 64
    records[1]["package_sha256"] = records[0]["package_sha256"]
    with pytest.raises(QaThresholdCalibrationError, match="leakage"):
        build_calibration_report(
            calibration_run_id="leaked-package",
            policy=_policy(),
            records=records,
        )


def test_holdout_measured_before_frozen_policy_fails_closed():
    record = _record(1, partition="qualification_holdout")
    record["measured_at"] = "2026-07-21T23:59:59Z"
    with pytest.raises(QaThresholdCalibrationError, match="before"):
        build_calibration_report(
            calibration_run_id="after-the-fact",
            policy=_policy(),
            records=[record],
        )


def test_unknown_context_label_and_forged_policy_fail_closed():
    record = _record(1)
    record["contexts"] = ["invented_context"]
    with pytest.raises(QaThresholdCalibrationError, match="unregistered"):
        build_calibration_report(
            calibration_run_id="unknown-context",
            policy=_policy(),
            records=[record],
        )
    record = _record(2, label="invented_anatomy")
    with pytest.raises(QaThresholdCalibrationError, match="unknown enabled label"):
        build_calibration_report(
            calibration_run_id="unknown-label",
            policy=_policy(),
            records=[record],
        )
    forged = _policy()
    forged["minimum_calibration_positive_per_label"] = 0
    with pytest.raises(QaThresholdCalibrationError, match="hash mismatch"):
        build_calibration_report(
            calibration_run_id="forged-policy",
            policy=forged,
            records=[],
        )


def test_record_contract_rejects_unqualified_reference_or_extra_fields():
    record = _record(1)
    record["reference_authority"] = "provider_consensus"
    with pytest.raises(QaThresholdCalibrationError, match="closed contract"):
        build_calibration_report(
            calibration_run_id="bad-authority",
            policy=_policy(),
            records=[record],
        )
    record = _record(2)
    record["provider_confidence"] = 0.99
    with pytest.raises(QaThresholdCalibrationError, match="closed contract"):
        build_calibration_report(
            calibration_run_id="extra-field",
            policy=_policy(),
            records=[record],
        )


def test_frozen_project_policy_is_hash_bound_and_remains_non_authorizing():
    policy = json.loads(
        open(
            "configs/autonomous_gold_qa_threshold_calibration_policy.json",
            encoding="utf-8",
        ).read()
    )
    result = build_calibration_report(
        calibration_run_id="project-policy-empty-probe",
        policy=policy,
        records=[],
    )
    assert result["report"]["status"] == "insufficient_evidence"
    assert result["report"]["record_count"] == 0
    assert result["registry_binding"]["authority_eligible"] is False
