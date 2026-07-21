import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from maskfactory.autonomy.multi_person_scope import (
    evaluate_multi_person_certification_scope,
)
from maskfactory.autonomy.tournament import CandidateEvidence, run_candidate_tournament


def _scope(**overrides):
    values = {
        "instance_context": "duo",
        "risk_bucket": "contact",
        "assigned_risk_bucket": "contact",
        "pipeline_fingerprint": "pipeline-v1",
        "evidence_pipeline_fingerprint": "pipeline-v1",
        "pooling_status": "exchangeable",
        "out_of_distribution": False,
        "distribution_drift": False,
        "critic_disagreement": False,
        "identity_ambiguous": False,
    }
    values.update(overrides)
    return evaluate_multi_person_certification_scope(**values)


def _certificate(**overrides):
    payload = {
        "schema_version": "2.0.0",
        "audit_authority": "human_anchor_gold",
        "passed": True,
        "risk_bucket": "contact",
        "instance_context": "duo",
        "covered_labels": ["hair"],
        "covered_contexts": ["duo"],
        "pipeline_fingerprint": "pipeline-v1",
        "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
    }
    payload.update(overrides)
    payload["sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload


def _candidate():
    return CandidateEvidence(
        "candidate",
        "candidate.png",
        "a" * 64,
        3,
        0.99,
        0.99,
        0.99,
        1.0,
        False,
        0.0,
        0.0,
        1,
        1,
        True,
        (),
    )


def _gate():
    from maskfactory.autonomy.multi_person_gate import MultiPersonCandidateGateResult

    return MultiPersonCandidateGateResult("duo", ("p0", "p1"), ())


def _config():
    return {
        "tournament": {
            "maximum_candidates_per_label": 8,
            "minimum_independent_sources": 2,
            "minimum_score": 0.5,
            "minimum_winner_margin": 0.0,
            "weights": {
                "consensus_iou": 0.25,
                "boundary_agreement": 0.25,
                "pose_consistency": 0.15,
                "source_diversity": 0.15,
                "critic_support": 0.20,
            },
            "hard_veto": {
                "require_format_valid": True,
                "reject_any_block_qc": True,
                "maximum_protected_overlap": 0.0,
                "maximum_exclusive_overlap": 0.0,
                "reject_component_overflow": True,
            },
        },
        "operations": {
            "cloud_disagreement_forces_residual_queue": True,
            "calibrated_status": "calibrated_auto_accepted",
            "uncalibrated_status": "machine_verified_candidate",
            "calibrated_truth_tier": "autonomous_certified_gold",
            "uncalibrated_truth_tier": "machine_candidate",
        },
        "truth_tiers": {
            "autonomous_certified_gold": {"training_weight": 0.65},
            "machine_candidate": {"training_weight": 0.0},
        },
    }


def _decision(scope, certificate=None):
    return run_candidate_tournament(
        (_candidate(),),
        label="hair",
        context="duo",
        instance_context="duo",
        multi_person_gate=_gate(),
        multi_person_scope=scope,
        pipeline_fingerprint="pipeline-v1",
        config=_config(),
        certificate=certificate,
    )


def test_exact_current_multi_person_scope_and_certificate_can_certify() -> None:
    decision = _decision(_scope(), _certificate())
    assert decision.status == "calibrated_auto_accepted"
    assert decision.truth_tier == "autonomous_certified_gold"


@pytest.mark.parametrize(
    ("overrides", "blocker"),
    [
        ({"assigned_risk_bucket": "occlusion"}, "risk_bucket_scope_mismatch"),
        ({"evidence_pipeline_fingerprint": "stale"}, "pipeline_fingerprint_drift"),
        ({"pooling_status": "sparse"}, "pooling_sparse"),
        ({"out_of_distribution": True}, "out_of_distribution"),
        ({"distribution_drift": True}, "distribution_drift"),
        ({"critic_disagreement": True}, "critic_disagreement"),
        ({"identity_ambiguous": True}, "identity_ambiguity"),
    ],
)
def test_ood_drift_disagreement_sparse_and_identity_cases_abstain(overrides, blocker) -> None:
    scope = _scope(**overrides)
    decision = _decision(scope, _certificate())
    assert decision.status == "residual_human_queue"
    assert f"multi_person_scope:{blocker}" in decision.ranking[0].vetoes


@pytest.mark.parametrize(
    "certificate",
    [
        _certificate(instance_context="small_group"),
        _certificate(risk_bucket="occlusion"),
        _certificate(pipeline_fingerprint="stale"),
        None,
    ],
)
def test_wrong_or_missing_multi_person_certificate_scope_routes_residual(certificate) -> None:
    decision = _decision(_scope(), certificate)
    assert decision.status == "residual_human_queue"
    assert not decision.certificate_valid
