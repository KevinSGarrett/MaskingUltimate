from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from maskfactory.steward.route_control import ROUTES
from maskfactory.steward.route_fault_drill import (
    DRILL_SCHEMA,
    RouteFaultDrillError,
    run_all_route_fault_drill,
    validate_route_fault_drill_receipt,
)


def test_all_route_fault_drill_interrupts_reconstructs_and_releases(
    tmp_path: Path,
) -> None:
    root = tmp_path / "all-route-fault-drill"
    receipt = run_all_route_fault_drill(root, timeout_seconds=10)

    assert receipt["schema_version"] == DRILL_SCHEMA
    assert {case["route"] for case in receipt["routes"]} == set(ROUTES)
    assert all(receipt["assertions"].values())
    assert all(
        case["initial_generation"] == case["reconstructed_generation"] == 1
        for case in receipt["routes"]
    )
    assert all(case["final_state"] == "completed" for case in receipt["routes"])
    assert all(case["active_attempts_after_release"] == 0 for case in receipt["routes"])
    assert all(case["protected_token_removed"] for case in receipt["routes"])
    assert all(not (root / case["route"] / "owner.token").exists() for case in receipt["routes"])
    persisted = json.loads((root / "route_fault_drill_receipt.json").read_text(encoding="utf-8"))
    assert persisted == receipt
    validate_route_fault_drill_receipt(persisted)


def test_route_fault_drill_never_overwrites_existing_root(tmp_path: Path) -> None:
    root = tmp_path / "existing"
    root.mkdir()

    with pytest.raises(FileExistsError):
        run_all_route_fault_drill(root)


def test_route_fault_receipt_hash_drift_fails_closed(tmp_path: Path) -> None:
    receipt = run_all_route_fault_drill(tmp_path / "drill", timeout_seconds=10)
    drifted = copy.deepcopy(receipt)
    drifted["routes"][0]["final_state"] = "active"

    with pytest.raises(RouteFaultDrillError, match="self-hash mismatch"):
        validate_route_fault_drill_receipt(drifted)


def test_route_fault_receipt_rejects_missing_route(tmp_path: Path) -> None:
    receipt = run_all_route_fault_drill(tmp_path / "drill", timeout_seconds=10)
    receipt["routes"].pop()
    receipt["receipt_sha256"] = "0" * 64

    with pytest.raises(RouteFaultDrillError):
        validate_route_fault_drill_receipt(receipt)


def test_rehashed_route_fault_semantic_drift_fails_closed(tmp_path: Path) -> None:
    receipt = run_all_route_fault_drill(tmp_path / "drill", timeout_seconds=10)
    receipt["routes"][0]["final_state"] = "active"
    receipt["receipt_sha256"] = "0" * 64
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(
            receipt,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()

    with pytest.raises(RouteFaultDrillError, match="case semantic mismatch"):
        validate_route_fault_drill_receipt(receipt)
