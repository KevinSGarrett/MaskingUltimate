from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from maskfactory.daz.control import DazControlError
from maskfactory.daz.recovery import evaluate_recovery_matrix, load_recovery_policy

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs/daz/recovery.yaml"
SCHEMA = ROOT / "src/maskfactory/schemas/daz_recovery.schema.json"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _record(artifact_id: str, tier: str, strategy: str, **extra):
    return {
        "artifact_id": artifact_id,
        "artifact_type": "generic",
        "tier": tier,
        "strategy": strategy,
        "referenced": False,
        "bytes": 10,
        "content_sha256": HASH_A,
        **extra,
    }


def test_recovery_policy_schema_is_closed() -> None:
    Draft202012Validator.check_schema(json.loads(SCHEMA.read_text(encoding="utf-8")))
    policy = load_recovery_policy(POLICY)
    assert tuple(policy.document["tiers"]) == ("A", "B", "C")


def test_complete_recovery_matrix_is_deterministic_and_accounts_bulk_bytes() -> None:
    policy = load_recovery_policy(POLICY)
    records = [
        _record("control", "A", "backup"),
        _record("accepted_map", "B", "backup", referenced=True),
        _record(
            "diagnostic",
            "C",
            "omit",
            source_sha256=HASH_B,
            rebuild_recipe_id="recipe_a",
            toolchain_sha256=HASH_C,
            bytes=30,
        ),
    ]
    first = evaluate_recovery_matrix(policy, records)
    second = evaluate_recovery_matrix(policy, list(reversed(records)))
    assert first == second
    assert first["recoverable"] is True
    assert first["backup_bytes"] == 20
    assert first["optional_bulk_bytes"] == 30


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        (_record("unknown", "D", "backup"), "unknown_tier"),
        (_record("tier_a_omit", "A", "omit"), "strategy_not_allowed_for_tier"),
        (
            _record("accepted", "B", "rebuild", referenced=True),
            "referenced_authority_requires_backup",
        ),
        (
            _record("package", "B", "backup", artifact_type="package_metadata"),
            "package_metadata_not_tier_a",
        ),
        (_record("bulk", "C", "omit"), "missing_source_sha256"),
    ],
)
def test_recovery_matrix_blocks_unrecoverable_or_misclassified_rows(record, reason: str) -> None:
    report = evaluate_recovery_matrix(load_recovery_policy(POLICY), [record])
    assert report["recoverable"] is False
    assert report["blockers"] == [{"artifact_id": record["artifact_id"], "reason": reason}]


def test_rebuild_requires_all_hash_bound_inputs() -> None:
    report = evaluate_recovery_matrix(
        load_recovery_policy(POLICY),
        [
            _record(
                "bulk",
                "C",
                "rebuild",
                source_sha256=HASH_B,
                rebuild_recipe_id="recipe_a",
                toolchain_sha256="short",
            )
        ],
    )
    assert report["blockers"][0]["reason"] == "missing_toolchain_sha256"


def test_duplicate_ids_and_invalid_bytes_fail_closed() -> None:
    policy = load_recovery_policy(POLICY)
    with pytest.raises(DazControlError, match="unique"):
        evaluate_recovery_matrix(policy, [_record("a", "A", "backup")] * 2)
    with pytest.raises(DazControlError, match="bytes invalid"):
        evaluate_recovery_matrix(policy, [_record("a", "A", "backup", bytes=-1)])
