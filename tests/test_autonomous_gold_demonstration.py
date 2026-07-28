from __future__ import annotations

import copy

import pytest

from maskfactory.autonomy.demonstration import (
    run_autonomous_gold_demonstration,
    verify_autonomous_gold_demonstration,
)
from maskfactory.validation import validate_document


def test_governed_single_and_multi_person_demonstration_is_deterministic(tmp_path) -> None:
    first = run_autonomous_gold_demonstration(tmp_path / "first")
    second = run_autonomous_gold_demonstration(tmp_path / "second")

    assert first == second
    assert not validate_document(first, "autonomous_gold_demonstration_report")
    verify_autonomous_gold_demonstration(first)
    assert first["manual_approval_used"] is False
    assert first["zero_hard_veto_bypass"] is True
    assert {row["case_id"]: row["outcome"] for row in first["branches"]} == {
        "accepted_single": "accepted_certified",
        "repaired_multi": "accepted_reversible_repair",
        "abstained_single": "rolled_back_abstain",
        "revoked_multi": "revoked_at_use",
    }
    assert next(row for row in first["branches"] if row["case_id"] == "revoked_multi")[
        "at_use_reasons"
    ] == ["certificate_revoked"]


def test_report_hash_and_authority_boundary_are_fail_closed(tmp_path) -> None:
    report = run_autonomous_gold_demonstration(tmp_path)
    tampered = copy.deepcopy(report)
    tampered["manual_approval_used"] = True
    with pytest.raises(ValueError, match="False was expected"):
        verify_autonomous_gold_demonstration(tampered)

    tampered = copy.deepcopy(report)
    tampered["branches"][0]["outcome"] = "forged"
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_autonomous_gold_demonstration(tampered)
