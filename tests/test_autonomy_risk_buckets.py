import copy
from datetime import UTC, datetime

import pytest

from maskfactory.autonomy.risk_buckets import (
    RISK_BUCKET_NAMES,
    RiskBucketError,
    assign_risk_bucket,
    evaluate_exchangeability,
    load_risk_bucket_policy,
    verify_exchangeability_evidence,
)
from maskfactory.validation import validate_document


def _features(label_family: str = "large_parts", **overrides):
    values = {
        "label_family": label_family,
        "occlusion_or_contact": False,
        "multi_person_overlap": False,
        "out_of_distribution": False,
    }
    values.update(overrides)
    return values


def _records(
    *,
    bucket: str = "large_parts",
    counts: tuple[int, ...] = (40, 40),
    defect_indexes: dict[int, set[int]] | None = None,
    serious_indexes: dict[int, set[int]] | None = None,
):
    defects = defect_indexes or {}
    serious = serious_indexes or {}
    records = []
    for stratum_index, count in enumerate(counts):
        for index in range(count):
            is_serious = index in serious.get(stratum_index, set())
            records.append(
                {
                    "record_id": f"s{stratum_index}-r{index:03d}",
                    "risk_bucket": bucket,
                    "stratum": f"label_{stratum_index}::solo",
                    "human_defect": index in defects.get(stratum_index, set()) or is_serious,
                    "serious_defect": is_serious,
                }
            )
    return records


def test_risk_policy_is_versioned_exact_and_schema_valid():
    policy = load_risk_bucket_policy()
    assert not validate_document(policy, "autonomy_risk_buckets")
    assert set(policy["buckets"]) == RISK_BUCKET_NAMES
    assert set(policy["assignment_priority"]) == RISK_BUCKET_NAMES
    assert policy["exchangeability"]["sparse_action"] == "abstain"
    assert policy["exchangeability"]["nonexchangeable_action"] == "split"


@pytest.mark.parametrize(
    ("features", "expected"),
    [
        (_features("large_parts"), "large_parts"),
        (_features("small_parts"), "small_parts"),
        (_features("hands_feet"), "hands_feet"),
        (_features("hair_boundaries"), "hair_boundaries"),
        (_features("clothing_materials"), "clothing_materials"),
        (_features("sensitive_anatomy"), "sensitive_anatomy"),
        (_features(occlusion_or_contact=True), "occlusion_contact"),
        (_features(multi_person_overlap=True), "multi_person_overlap"),
        (_features(out_of_distribution=True), "out_of_distribution"),
        (
            _features(
                "sensitive_anatomy",
                occlusion_or_contact=True,
                multi_person_overlap=True,
                out_of_distribution=True,
            ),
            "out_of_distribution",
        ),
    ],
)
def test_assignment_covers_every_required_risk_and_worst_risk_precedence(features, expected):
    assert assign_risk_bucket(features, load_risk_bucket_policy()) == expected


def test_exchangeable_strata_pool_and_evidence_recomputes_exactly():
    policy = load_risk_bucket_policy()
    records = _records()
    evidence = evaluate_exchangeability(
        records,
        risk_bucket="large_parts",
        policy=policy,
        generated_at=datetime(2026, 7, 14, tzinfo=UTC),
    )
    assert evidence["decision"] == "pool"
    assert evidence["pooling_allowed"] is True
    verify_exchangeability_evidence(evidence, records, risk_bucket="large_parts", policy=policy)


def test_sparse_stratum_abstains_instead_of_borrowing_confidence():
    evidence = evaluate_exchangeability(
        _records(counts=(40, 29)),
        risk_bucket="large_parts",
        policy=load_risk_bucket_policy(),
        generated_at=datetime(2026, 7, 14, tzinfo=UTC),
    )
    assert evidence["decision"] == "abstain"
    assert evidence["pooling_allowed"] is False
    assert evidence["reasons"] == ["sparse_stratum:label_1::solo"]


def test_nonexchangeable_strata_split_even_when_pooled_average_looks_small():
    evidence = evaluate_exchangeability(
        _records(counts=(100, 100), defect_indexes={1: set(range(8))}),
        risk_bucket="large_parts",
        policy=load_risk_bucket_policy(),
        generated_at=datetime(2026, 7, 14, tzinfo=UTC),
    )
    assert evidence["decision"] == "split"
    assert evidence["pooling_allowed"] is False
    assert evidence["comparisons"][0]["false_accept_rate_delta"] == 0.08


def test_tampered_or_nonpassing_exchangeability_evidence_cannot_authorize_pooling():
    policy = load_risk_bucket_policy()
    records = _records()
    evidence = evaluate_exchangeability(
        records,
        risk_bucket="large_parts",
        policy=policy,
        generated_at=datetime(2026, 7, 14, tzinfo=UTC),
    )
    tampered = copy.deepcopy(evidence)
    tampered["pooling_allowed"] = False
    with pytest.raises(RiskBucketError, match="hash mismatch"):
        verify_exchangeability_evidence(tampered, records, risk_bucket="large_parts", policy=policy)


def test_unknown_or_malformed_bucket_inputs_fail_closed():
    policy = load_risk_bucket_policy()
    with pytest.raises(RiskBucketError, match="unknown label-family"):
        assign_risk_bucket(_features("other"), policy)
    with pytest.raises(RiskBucketError, match="not registered"):
        evaluate_exchangeability(_records(), risk_bucket="unregistered", policy=policy)
