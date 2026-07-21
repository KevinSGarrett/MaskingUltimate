from __future__ import annotations

from maskfactory.bridge.adoption_receipt_matrix import (
    build_adoption_receipt_matrix_decision,
    validate_adoption_receipt_matrix_decision,
)
from maskfactory.validation import canonical_document_sha256

CHECKS = [
    "api_contract",
    "artifact_security",
    "authority_policy",
    "canonicalization",
    "capabilities",
    "contract_tests",
    "media_scope",
    "node_pack",
    "ontology",
    "package_format",
    "release_hash",
    "revocation_freshness",
    "signature",
    "signed_journal",
    "trust_anchor",
    "wire_schemas",
]


def _qualification_check(check: str) -> dict:
    row = {
        "check": check,
        "test_ids": [f"test:{check}"],
        "result": "pass",
        "result_sha256": canonical_document_sha256({"check": check, "result": "pass"}),
        "execution": {
            "command_sha256": canonical_document_sha256({"check": check, "part": "command"}),
            "stdout_sha256": canonical_document_sha256({"check": check, "part": "stdout"}),
            "stderr_sha256": canonical_document_sha256({"check": check, "part": "stderr"}),
            "status": "pass",
            "exit_code": 0,
        },
    }
    return row


def _executed_test_hash(row: dict) -> str:
    execution = row["execution"]
    return canonical_document_sha256(
        {
            "check": row["check"],
            "test_ids": sorted(set(row["test_ids"])),
            "result_sha256": row["result_sha256"],
            "execution": {
                "command_sha256": execution["command_sha256"],
                "stdout_sha256": execution["stdout_sha256"],
                "stderr_sha256": execution["stderr_sha256"],
                "status": execution["status"],
                "exit_code": execution["exit_code"],
            },
        }
    )


def _receipt(decision: str = "adopted") -> dict:
    return {
        "adoption_id": "mfadopt_0123456789abcdef01234567",
        "adoption_payload_sha256": "a" * 64,
        "decided_at": "2026-07-19T00:00:00Z",
        "valid_until": "2026-07-20T00:00:00Z",
        "decision": decision,
        "compatibility_checks": [],
        "capability_decisions": [
            {
                "capability_id": "mask.package.read",
                "requirement_class": "required",
                "decision": "accepted",
            },
            {
                "capability_id": "mask.live.predict",
                "requirement_class": "optional",
                "decision": "accepted",
            },
        ],
        "signature": {
            "key_id": "comfy-main-adoption-prod",
            "public_key_base64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "signed_payload_sha256": "b" * 64,
            "value_base64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        },
    }


def _qualification_bundle() -> dict:
    return {"compatibility_checks": [_qualification_check(check) for check in CHECKS]}


def test_accepts_adopted_receipt_with_bound_executed_hashes() -> None:
    receipt = _receipt("adopted")
    qualification = _qualification_bundle()
    by_check = {row["check"]: row for row in qualification["compatibility_checks"]}
    receipt["compatibility_checks"] = [
        {"check": check, "result": "pass", "evidence_sha256": _executed_test_hash(by_check[check])}
        for check in CHECKS
    ]
    decision = build_adoption_receipt_matrix_decision(
        receipt,
        at_time="2026-07-19T12:00:00Z",
        qualification_bundle=qualification,
        release_publication_issues=[],
        capability_decision={"status": "accepted"},
        consumer_requirements_admission={"status": "accepted"},
        compatibility_decision={"compatible": True},
    )
    assert decision["status"] == "accepted"
    assert decision["expected_decision"] == "adopted"
    assert decision["rejection_reasons"] == ["eligible"]
    assert validate_adoption_receipt_matrix_decision(decision) == ()


def test_rejects_missing_or_duplicate_check_and_missing_hashes() -> None:
    receipt = _receipt("adopted")
    qualification = _qualification_bundle()
    one = qualification["compatibility_checks"][0]
    receipt["compatibility_checks"] = [
        {"check": "api_contract", "result": "pass", "evidence_sha256": _executed_test_hash(one)},
        {"check": "api_contract", "result": "pass", "evidence_sha256": _executed_test_hash(one)},
    ]
    decision = build_adoption_receipt_matrix_decision(
        receipt,
        at_time="2026-07-19T12:00:00Z",
        qualification_bundle=qualification,
    )
    assert decision["status"] == "rejected"
    assert "compatibility_checks_missing_or_unknown" in decision["rejection_reasons"]
    assert "compatibility_checks_duplicate" in decision["rejection_reasons"]
    assert "required_executed_test_hashes_missing" in decision["rejection_reasons"]


def test_rejects_optional_only_blocker_for_adopted_receipt() -> None:
    receipt = _receipt("adopted")
    qualification = _qualification_bundle()
    by_check = {row["check"]: row for row in qualification["compatibility_checks"]}
    receipt["compatibility_checks"] = [
        {"check": check, "result": "pass", "evidence_sha256": _executed_test_hash(by_check[check])}
        for check in CHECKS
    ]
    receipt["capability_decisions"][1]["decision"] = "rejected"
    decision = build_adoption_receipt_matrix_decision(
        receipt,
        at_time="2026-07-19T12:00:00Z",
        qualification_bundle=qualification,
        release_publication_issues=[],
        capability_decision={"status": "accepted"},
        consumer_requirements_admission={"status": "accepted"},
        compatibility_decision={"compatible": True},
    )
    assert decision["status"] == "rejected"
    assert decision["expected_decision"] == "partially_adopted"
    assert "optional_only_blocker" in decision["rejection_reasons"]
    assert "receipt_decision_matrix_disagrees" in decision["rejection_reasons"]


def test_rejects_partial_required_coverage_for_adopted_receipt() -> None:
    receipt = _receipt("adopted")
    qualification = _qualification_bundle()
    by_check = {row["check"]: row for row in qualification["compatibility_checks"]}
    receipt["compatibility_checks"] = [
        {"check": check, "result": "pass", "evidence_sha256": _executed_test_hash(by_check[check])}
        for check in CHECKS
    ]
    receipt["capability_decisions"][0]["decision"] = "rejected"
    decision = build_adoption_receipt_matrix_decision(
        receipt,
        at_time="2026-07-19T12:00:00Z",
        qualification_bundle=qualification,
        release_publication_issues=[],
        capability_decision={"status": "accepted"},
        consumer_requirements_admission={"status": "accepted"},
        compatibility_decision={"compatible": True},
    )
    assert decision["status"] == "rejected"
    assert decision["expected_decision"] == "rejected"
    assert "required_capability_coverage_partial" in decision["rejection_reasons"]
    assert "receipt_decision_matrix_disagrees" in decision["rejection_reasons"]


def test_rejects_expired_decision_time_and_file_presence_claims() -> None:
    receipt = _receipt("adopted")
    qualification = _qualification_bundle()
    # Strip execution hashes from one check to simulate "file presence only".
    qualification["compatibility_checks"][0]["execution"] = {"status": "pass", "exit_code": 0}
    receipt["compatibility_checks"] = [
        {"check": check, "result": "pass", "evidence_sha256": "0" * 64} for check in CHECKS
    ]
    decision = build_adoption_receipt_matrix_decision(
        receipt,
        at_time="2026-07-21T12:00:00Z",
        qualification_bundle=qualification,
        release_publication_issues=[],
        capability_decision={"status": "accepted"},
        consumer_requirements_admission={"status": "accepted"},
        compatibility_decision={"compatible": True},
    )
    assert decision["status"] == "rejected"
    assert "decision_time_validity_failed" in decision["rejection_reasons"]
    assert "file_presence_only_claim" in decision["rejection_reasons"]
