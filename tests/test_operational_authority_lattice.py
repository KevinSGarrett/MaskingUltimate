from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from maskfactory.authority.authority_lattice import (
    AuthorityLatticeError,
    canonical_sha256,
    evaluate_authority_lattice,
    load_authority_lattice_policy,
    validate_authority_decision,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "operational_authority_lattice.yaml"
SCHEMA_PATH = (
    ROOT / "src" / "maskfactory" / "schemas" / "operational_authority_decision.schema.json"
)


def operational_inputs(**overrides: object) -> dict[str, object]:
    inputs: dict[str, object] = {
        "actor": "main_controller",
        "action": "evaluate_use",
        "access_mode": "mode_a_package_read",
        "artifact_class": "machine_candidate",
        "authority_namespace": "operational_output",
        "current_operational_authority_state": "draft",
        "requested_operational_authority_state": "draft",
        "current_training_truth_tier": None,
        "requested_training_truth_tier": None,
        "intended_use": "preview",
        "input_role": "standalone",
        "required_minimum_operational_authority_state": None,
        "parent_operational_authority_states": [],
        "exact_output_certificate_valid": False,
        "training_promotion_evidence_valid": False,
    }
    inputs.update(overrides)
    return inputs


def training_inputs(**overrides: object) -> dict[str, object]:
    inputs: dict[str, object] = {
        "actor": "maskfactory_training_governance",
        "action": "assign_training_truth",
        "access_mode": "none",
        "artifact_class": "weighted_pseudo_label",
        "authority_namespace": "training_truth",
        "current_operational_authority_state": None,
        "requested_operational_authority_state": None,
        "current_training_truth_tier": "machine_candidate",
        "requested_training_truth_tier": "weighted_pseudo_label",
        "intended_use": "training",
        "input_role": "standalone",
        "required_minimum_operational_authority_state": None,
        "parent_operational_authority_states": [],
        "exact_output_certificate_valid": False,
        "training_promotion_evidence_valid": True,
    }
    inputs.update(overrides)
    return inputs


def decide(inputs: dict[str, object], suffix: str = "case") -> dict[str, object]:
    return evaluate_authority_lattice(inputs, decision_id=f"decision-{suffix}")


def assert_rejected(decision: dict[str, object], reason: str) -> None:
    result = decision["result"]
    assert isinstance(result, dict)
    assert result["status"] == "reject"
    assert result["may_use"] is False
    assert result["may_mutate_authority"] is False
    assert reason in result["reasons"]


def test_policy_self_hash_and_decision_schema_are_current() -> None:
    policy = load_authority_lattice_policy(POLICY_PATH)
    unsigned = {key: value for key, value in policy.items() if key != "policy_sha256"}
    assert policy["policy_sha256"] == canonical_sha256(unsigned)

    decision = decide(operational_inputs(), "schema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(decision)
    validate_authority_decision(decision, policy=policy, schema_path=SCHEMA_PATH)


def test_access_mode_never_grants_authority() -> None:
    mode_a = decide(operational_inputs(), "mode-a-preview")
    assert mode_a["result"]["status"] == "allow"
    assert mode_a["result"]["effective_operational_authority_state"] == "draft"
    assert mode_a["result"]["may_mutate_authority"] is False

    production = decide(
        operational_inputs(intended_use="production_conditioning"),
        "mode-a-production",
    )
    assert_rejected(production, "operational_authority_below_required_floor")

    mode_b = decide(operational_inputs(access_mode="mode_b_live_predict"), "mode-b-preview")
    assert mode_b["result"]["status"] == "allow"
    assert mode_b["result"]["effective_operational_authority_state"] == "draft"


def test_exact_original_mode_b_output_can_be_certified_only_by_producer() -> None:
    certified = decide(
        operational_inputs(
            actor="maskfactory_producer",
            action="grant_operational_authority",
            access_mode="mode_b_live_predict",
            artifact_class="operationally_certified_artifact",
            requested_operational_authority_state="certified",
            intended_use="production_conditioning",
            exact_output_certificate_valid=True,
        ),
        "certified-mode-b",
    )
    assert certified["result"] == {
        "status": "allow",
        "may_use": True,
        "may_mutate_authority": True,
        "effective_operational_authority_state": "certified",
        "effective_training_truth_tier": None,
        "operational_floor_comparison": "meets_floor",
        "reasons": [],
    }

    untrusted = decide(
        operational_inputs(
            actor="provider",
            action="grant_operational_authority",
            access_mode="mode_b_live_predict",
            artifact_class="operationally_certified_artifact",
            requested_operational_authority_state="certified",
            intended_use="production_conditioning",
            exact_output_certificate_valid=True,
        ),
        "provider-cannot-certify",
    )
    assert_rejected(untrusted, "actor_cannot_grant_operational_authority")


@pytest.mark.parametrize(
    "artifact_class",
    ["refinement", "derived_mask", "projection", "inpaint_mask"],
)
def test_descendants_cannot_exceed_the_weakest_parent(artifact_class: str) -> None:
    above_parent = decide(
        operational_inputs(
            actor="maskfactory_producer",
            action="derive",
            access_mode="mode_b_live_refine",
            artifact_class=artifact_class,
            requested_operational_authority_state="certified",
            intended_use="production_conditioning",
            parent_operational_authority_states=["certified", "draft"],
            exact_output_certificate_valid=True,
        ),
        f"weak-parent-{artifact_class}",
    )
    assert_rejected(above_parent, "descendant_authority_above_weakest_parent")

    independently_certified = decide(
        operational_inputs(
            actor="maskfactory_producer",
            action="derive",
            access_mode="mode_b_live_refine",
            artifact_class=artifact_class,
            requested_operational_authority_state="certified",
            intended_use="production_conditioning",
            parent_operational_authority_states=["certified", "certified"],
            exact_output_certificate_valid=True,
        ),
        f"certified-descendant-{artifact_class}",
    )
    assert independently_certified["result"]["status"] == "allow"
    assert independently_certified["result"]["may_mutate_authority"] is True


def test_target_and_protected_inputs_enforce_explicit_floors() -> None:
    missing = decide(operational_inputs(input_role="protected"), "protected-no-floor")
    assert_rejected(missing, "input_role_authority_floor_missing")

    weak = decide(
        operational_inputs(
            input_role="target",
            required_minimum_operational_authority_state="qa_passed_noncertified",
        ),
        "target-weak",
    )
    assert_rejected(weak, "operational_authority_below_required_floor")


def test_operational_certificate_cannot_impersonate_training_truth() -> None:
    decision = decide(
        training_inputs(exact_output_certificate_valid=True), "certificate-not-training-gold"
    )
    assert_rejected(decision, "operational_certificate_cannot_create_training_truth")


def test_training_truth_assigners_and_evidence_are_closed() -> None:
    human = decide(
        training_inputs(
            actor="human_reviewer",
            artifact_class="human_anchor_gold",
            requested_training_truth_tier="human_anchor_gold",
        ),
        "human-anchor",
    )
    assert human["result"]["status"] == "allow"
    assert human["result"]["effective_training_truth_tier"] == "human_anchor_gold"

    autonomous = decide(
        training_inputs(
            artifact_class="autonomous_certified_gold",
            requested_training_truth_tier="autonomous_certified_gold",
        ),
        "autonomous-gold",
    )
    assert autonomous["result"]["status"] == "allow"

    wrong_actor = decide(
        training_inputs(
            actor="maskfactory_training_governance",
            artifact_class="human_anchor_gold",
            requested_training_truth_tier="human_anchor_gold",
        ),
        "governance-not-human",
    )
    assert_rejected(wrong_actor, "actor_cannot_assign_training_truth")

    no_evidence = decide(
        training_inputs(training_promotion_evidence_valid=False), "missing-training-evidence"
    )
    assert_rejected(no_evidence, "training_promotion_evidence_required")

    revoked = decide(
        training_inputs(
            action="revoke_training_truth",
            artifact_class="machine_candidate",
            current_training_truth_tier="weighted_pseudo_label",
            requested_training_truth_tier="machine_candidate",
            intended_use="training_governance",
        ),
        "revoke-training-truth",
    )
    assert revoked["result"]["status"] == "allow"
    assert revoked["result"]["may_mutate_authority"] is True
    assert revoked["result"]["effective_training_truth_tier"] == "machine_candidate"


def test_training_truth_is_not_comparable_to_operational_authority() -> None:
    decision = decide(
        training_inputs(required_minimum_operational_authority_state="certified"),
        "namespace-comparison",
    )
    assert_rejected(decision, "training_truth_not_operationally_comparable")


@pytest.mark.parametrize("actor", ["main_controller", "llm_vlm", "provider"])
@pytest.mark.parametrize(
    ("action", "requested", "reason"),
    [
        ("grant_operational_authority", "certified", "actor_cannot_grant_operational_authority"),
        ("revoke_operational_authority", "hypothesis", "actor_cannot_revoke_operational_authority"),
    ],
)
def test_non_producer_actors_cannot_mutate_operational_authority(
    actor: str, action: str, requested: str, reason: str
) -> None:
    decision = decide(
        operational_inputs(
            actor=actor,
            action=action,
            artifact_class="refinement",
            requested_operational_authority_state=requested,
            parent_operational_authority_states=["certified"],
            exact_output_certificate_valid=True,
        ),
        f"non-producer-{actor}-{action}",
    )
    assert_rejected(decision, reason)


def test_main_may_reject_without_upgrading() -> None:
    decision = decide(operational_inputs(action="reject"), "main-reject")
    assert_rejected(decision, "consumer_rejected")


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("actor", "unknown", "unknown_actor"),
        ("access_mode", "mode_c", "unknown_access_mode"),
        ("artifact_class", "mystery", "unknown_artifact_class"),
        ("current_operational_authority_state", "goldish", "unknown_operational_authority_state"),
    ],
)
def test_unknown_closed_world_values_fail_with_typed_codes(
    field: str, value: str, code: str
) -> None:
    with pytest.raises(AuthorityLatticeError) as caught:
        decide(operational_inputs(**{field: value}), f"unknown-{field}")
    assert caught.value.code == code


def test_extra_input_field_fails_closed() -> None:
    inputs = operational_inputs()
    inputs["provider_claimed_gold"] = True
    with pytest.raises(AuthorityLatticeError) as caught:
        decide(inputs, "extra-input")
    assert caught.value.code == "input_fields"


def test_decisions_are_deterministic_and_tamper_evident() -> None:
    inputs = operational_inputs()
    first = decide(inputs, "deterministic")
    second = decide(inputs, "deterministic")
    assert first == second

    tampered_hash = copy.deepcopy(first)
    tampered_hash["decision_sha256"] = "0" * 64
    with pytest.raises(AuthorityLatticeError) as caught:
        validate_authority_decision(tampered_hash, schema_path=SCHEMA_PATH)
    assert caught.value.code == "decision_hash_mismatch"

    tampered_result = copy.deepcopy(first)
    tampered_result["result"]["may_use"] = False
    unsigned = {key: value for key, value in tampered_result.items() if key != "decision_sha256"}
    tampered_result["decision_sha256"] = canonical_sha256(unsigned)
    with pytest.raises(AuthorityLatticeError) as caught:
        validate_authority_decision(tampered_result, schema_path=SCHEMA_PATH)
    assert caught.value.code == "decision_semantic_mismatch"

    tampered_policy = copy.deepcopy(first)
    tampered_policy["policy"]["policy_sha256"] = "f" * 64
    unsigned = {key: value for key, value in tampered_policy.items() if key != "decision_sha256"}
    tampered_policy["decision_sha256"] = canonical_sha256(unsigned)
    with pytest.raises(AuthorityLatticeError) as caught:
        validate_authority_decision(tampered_policy, schema_path=SCHEMA_PATH)
    assert caught.value.code == "decision_policy_binding"
