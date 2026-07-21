import pytest

from maskfactory.autonomy.multi_person_risk import (
    MULTI_PERSON_BUCKETS,
    MultiPersonRiskError,
    assign_multi_person_risk_bucket,
    evaluate_multi_person_exchangeability,
    load_multi_person_risk_policy,
)
from maskfactory.validation import validate_document


def _features(context="duo", **overrides):
    features = {
        "instance_context": context,
        "overlap": False,
        "contact": False,
        "occlusion": False,
        "scale_disparity": False,
        "truncation": False,
        "crowding": False,
        "identity_ambiguity": False,
    }
    features.update(overrides)
    return features


def _records(bucket="duo_overlap", context="duo", count=40):
    return [
        {
            "record_id": f"r{index:03d}",
            "risk_bucket": bucket,
            "stratum": "overlap_low",
            "source_instance_context": context,
            "human_defect": False,
            "serious_defect": False,
        }
        for index in range(count)
    ]


def test_multi_person_policy_is_exact_versioned_and_forbids_solo_evidence():
    policy = load_multi_person_risk_policy()
    assert not validate_document(policy, "autonomy_multi_person_risk_buckets")
    assert set(policy["buckets"]) == MULTI_PERSON_BUCKETS
    assert policy["allowed_instance_contexts"] == ["duo", "small_group"]
    assert policy["solo_evidence_allowed"] is False


@pytest.mark.parametrize(
    ("features", "expected"),
    [
        (_features(), "duo_baseline"),
        (_features("small_group"), "small_group_baseline"),
        (_features(overlap=True), "duo_overlap"),
        (_features("small_group", overlap=True), "small_group_overlap"),
        (_features(contact=True), "contact"),
        (_features(occlusion=True), "occlusion"),
        (_features(scale_disparity=True), "scale_disparity"),
        (_features(truncation=True), "truncation"),
        (_features(crowding=True), "crowding"),
        (_features(identity_ambiguity=True), "identity_ambiguity"),
        (
            _features(contact=True, occlusion=True, crowding=True, identity_ambiguity=True),
            "identity_ambiguity",
        ),
    ],
)
def test_assignment_separates_every_required_multi_person_risk(features, expected):
    assert assign_multi_person_risk_bucket(features, load_multi_person_risk_policy()) == expected


def test_solo_and_cross_context_evidence_cannot_borrow_multi_person_authority():
    policy = load_multi_person_risk_policy()
    with pytest.raises(MultiPersonRiskError, match="solo or unknown"):
        assign_multi_person_risk_bucket(_features("solo", overlap=True), policy)
    with pytest.raises(MultiPersonRiskError, match="solo evidence"):
        evaluate_multi_person_exchangeability(
            _records(context="solo"), risk_bucket="duo_overlap", policy=policy
        )
    with pytest.raises(MultiPersonRiskError, match="differs from bucket scope"):
        evaluate_multi_person_exchangeability(
            _records(context="small_group"), risk_bucket="duo_overlap", policy=policy
        )


def test_sparse_multi_person_stratum_abstains_instead_of_borrowing():
    evidence = evaluate_multi_person_exchangeability(
        _records(count=29),
        risk_bucket="duo_overlap",
        policy=load_multi_person_risk_policy(),
    )
    assert evidence["decision"] == "abstain"
    assert evidence["pooling_allowed"] is False


def test_sufficient_exact_context_stratum_is_eligible_without_solo_pooling():
    evidence = evaluate_multi_person_exchangeability(
        _records(),
        risk_bucket="duo_overlap",
        policy=load_multi_person_risk_policy(),
    )
    assert evidence["decision"] == "not_required_single_stratum"
    assert evidence["pooling_allowed"] is True
