from __future__ import annotations

import copy
import runpy
from pathlib import Path

from maskfactory.bridge.consumer_requirements import evaluate_consumer_requirements_admission

ROOT = Path(__file__).resolve().parents[1]
BUILDER = runpy.run_path(
    str(ROOT / "tests" / "fixtures" / "mask_bridge_contracts" / "build_contract_fixtures.py")
)


def _requirements() -> dict:
    requirements = BUILDER["build_consumer_requirements"]()
    BUILDER["sign"](
        requirements,
        "requirements_sha256",
        "consumer_requirements",
        ("requirements_sha256", "signature"),
    )
    return requirements


def _offer() -> dict:
    return {
        "capability_id": "mask.package.read",
        "access_modes": ["mode_a_package_read", "mode_b_live_predict"],
        "labels": ["left_hand", "torso"],
        "artifact_kinds": ["atomic_visible", "protected_qa"],
        "media_scopes": ["still_image"],
        "transform_operations": ["inverse_project"],
        "maximum_person_count": 2,
        "authority_states": ["qa_passed_noncertified", "certified"],
        "truth_tiers": [
            "machine_candidate",
            "qa_passed_machine_candidate",
            "operationally_certified_artifact",
        ],
        "certificate_kinds": ["exact_serving_route_output"],
        "issuer_kinds": ["maskfactory_autonomous"],
        "versions": {
            "api_contracts": ["maskfactory-api/1.0"],
            "package_formats": ["maskfactory-package/1.0"],
            "ontology_versions": ["body_parts_v1"],
            "node_pack_versions": ["1.0.0"],
        },
        "runtime": {
            "maximum_p50_latency_ms": 2000,
            "maximum_p95_latency_ms": 4000,
            "maximum_vram_mb": 8192,
            "maximum_ram_mb": 16384,
            "maximum_output_bytes": 1000000,
            "minimum_concurrency": 1,
        },
        "evidence": [
            {"evidence_id": "certificate", "kind": "authority_certificate", "sha256": "a" * 64},
            {"evidence_id": "benchmark", "kind": "route_benchmark", "sha256": "b" * 64},
        ],
    }


def _admission(requirements: dict | None = None, offers: list[dict] | None = None) -> dict:
    return {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_consumer_requirements_admission",
        "requirements": requirements or _requirements(),
        "offered_capabilities": offers or [_offer()],
    }


def _evaluate(admission: dict, ledger: dict[str, str] | None = None, keys: dict | None = None):
    return evaluate_consumer_requirements_admission(
        admission,
        trusted_signing_keys=keys or BUILDER["TRUSTED_KEYS"],
        observed_at="2026-07-17T00:01:00Z",
        replay_ledger=ledger,
    )


def test_accepts_required_capabilities_while_optional_stays_distinct() -> None:
    decision, issues = _evaluate(_admission(), {})

    assert not issues
    assert decision["status"] == "accepted"
    assert {row["status"] for row in decision["required_outcomes"]} == {"met"}
    assert decision["optional_outcomes"] == (
        {
            "capability_id": "mask.live.predict",
            "status": "unmet",
            "unmet_constraints": ("capability_unavailable",),
        },
    )


def test_vram_fields_are_telemetry_and_cannot_refuse_admission() -> None:
    offer = _offer()
    offer["runtime"]["maximum_vram_mb"] = 999_999_999

    decision, issues = _evaluate(_admission(offers=[offer]), {})

    assert not issues
    assert decision["status"] == "accepted"
    assert "__global__.latency_resources" not in decision["rejection_reasons"]


def test_rejects_wrong_role_or_revoked_signer() -> None:
    requirements = _requirements()
    wrong_role_keys = copy.deepcopy(BUILDER["TRUSTED_KEYS"])
    wrong_role_keys["comfy-main-requirements-fixture"]["roles"] = ["consumer_request"]
    _, role_issues = _evaluate(_admission(requirements), keys=wrong_role_keys)
    assert "trusted_key_role" in {issue.validator for issue in role_issues}

    revoked_keys = copy.deepcopy(BUILDER["TRUSTED_KEYS"])
    revoked_keys["comfy-main-requirements-fixture"]["status"] = "revoked"
    _, revoked_issues = _evaluate(_admission(requirements), keys=revoked_keys)
    assert "trusted_key_status" in {issue.validator for issue in revoked_issues}


def test_rejects_nonce_replay_without_mutating_invalid_admission() -> None:
    ledger: dict[str, str] = {}
    admission = _admission()

    accepted, accepted_issues = _evaluate(admission, ledger)
    rejected, replay_issues = _evaluate(admission, ledger)

    assert accepted["status"] == "accepted"
    assert not accepted_issues
    assert rejected["status"] == "rejected"
    assert "requirements_replay" in {issue.validator for issue in replay_issues}


def test_rejects_ambiguous_or_unmet_required_capabilities() -> None:
    duplicate = _admission(offers=[_offer(), _offer()])
    ambiguous, ambiguous_issues = _evaluate(duplicate, {})
    assert ambiguous["status"] == "rejected"
    assert "capability_ambiguity" in {issue.validator for issue in ambiguous_issues}

    incomplete_offer = _offer()
    incomplete_offer["labels"] = ["left_hand"]
    unmet, unmet_issues = _evaluate(_admission(offers=[incomplete_offer]), {})
    assert unmet["status"] == "rejected"
    assert not unmet_issues
    assert "__global__.labels" in unmet["rejection_reasons"]


def test_rejects_unknown_or_malformed_requirements_without_crashing() -> None:
    requirements = _requirements()
    requirements["unknown_requirement"] = "not adopted"

    decision, issues = _evaluate(_admission(requirements), {})

    assert decision["status"] == "rejected"
    assert {"additionalProperties", "canonical_payload_hash"} <= {
        issue.validator for issue in issues
    }
