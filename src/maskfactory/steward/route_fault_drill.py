"""CPU-only interruption and ambiguity drills for every governed route."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .route_control import (
    ROUTES,
    CanonicalMissionRouteLedger,
    RouteAlreadyActive,
    RouteControlError,
    RouteOutcomeUnknown,
)

DRILL_SCHEMA = "maskfactory.steward.all_route_fault_drill.v1"
READY_SCHEMA = "maskfactory.steward.route_fault_child_ready.v1"
ZERO_SHA256 = "0" * 64
SESSION_ID = "019f91d1-ea20-7d81-83ff-03d393eaa1f5"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_ROUTE_EVENTS = [
    "route_claimed",
    "route_outcome_unknown",
    "route_reconciled_not_submitted",
    "route_claimed",
    "route_terminal_persisted",
    "terminal_route_released",
]
ASSERTION_FIELDS = {
    "all_governed_routes_covered",
    "all_owner_tokens_removed_after_release",
    "no_active_route_attempts_remain",
    "no_external_gpu_provider_or_broker_action_attempted",
    "owned_process_interruptions_reconstructed_without_duplicate_claim",
    "persisted_terminals_block_resend",
    "stale_owner_tokens_rejected",
    "unresolved_ambiguity_blocks_resend",
}
ROUTE_CASE_FIELDS = {
    "route",
    "mission_id",
    "payload_sha256",
    "actual_owned_child_interrupted",
    "initial_generation",
    "reconstructed_generation",
    "stale_owner_token_blocked",
    "unresolved_ambiguity_blocked_resend",
    "no_submit_reconciliation_state",
    "terminal_state_reconstructed",
    "terminal_resend_blocked",
    "final_state",
    "active_attempts_after_release",
    "protected_token_removed",
    "route_events",
    "external_action_attempted",
}


class RouteFaultDrillError(RuntimeError):
    """The bounded route-fault drill failed closed."""


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    sealed = dict(value)
    sealed[field] = ZERO_SHA256
    sealed[field] = _canonical_sha256(sealed)
    return sealed


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _write_token(path: Path) -> str:
    token = "route-fault-drill-" + os.urandom(32).hex()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(token)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return token


def _read_token(path: Path) -> str:
    token = path.read_text(encoding="utf-8")
    if len(token) < 32:
        raise RouteFaultDrillError("protected owner token is absent or truncated")
    return token


def _wait_for_ready(
    process: subprocess.Popen[str],
    ready_path: Path,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if ready_path.is_file():
            ready = json.loads(ready_path.read_text(encoding="utf-8"))
            declared = ready.get("ready_sha256")
            zeroed = dict(ready)
            zeroed["ready_sha256"] = ZERO_SHA256
            if declared != _canonical_sha256(zeroed):
                raise RouteFaultDrillError("child ready receipt self-hash mismatch")
            return ready
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RouteFaultDrillError(
                "owned child exited before ready receipt: "
                f"code={process.returncode} stdout={stdout!r} stderr={stderr!r}"
            )
        time.sleep(0.02)
    raise RouteFaultDrillError("timed out waiting for owned child ready receipt")


def _child_claim(
    *,
    database: Path,
    mission_id: str,
    payload_sha256: str,
    route: str,
    token_file: Path,
    ready_path: Path,
) -> int:
    token = _read_token(token_file)
    ledger = CanonicalMissionRouteLedger(database)
    claim = ledger.claim_route(
        mission_id=mission_id,
        session_id=SESSION_ID,
        payload_sha256=payload_sha256,
        route=route,
        owner_token=token,
    )
    ready = _seal(
        {
            "schema_version": READY_SCHEMA,
            "mission_id": mission_id,
            "payload_sha256": payload_sha256,
            "route": route,
            "attempt_id": claim["attempt_id"],
            "generation": claim["generation"],
            "external_action_attempted": False,
            "ready_sha256": ZERO_SHA256,
        },
        "ready_sha256",
    )
    _write_json_exclusive(ready_path, ready)
    while True:
        time.sleep(60)


def _active_attempt_count(database: Path) -> int:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM route_attempts
            WHERE status IN ('active', 'outcome_unknown', 'terminal_pending_release')
            """
        ).fetchone()
    assert row is not None
    return int(row[0])


def _run_route_case(
    root: Path,
    *,
    route: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    route_root = root / route
    route_root.mkdir(parents=True, exist_ok=False)
    database = route_root / "routes.sqlite"
    token_file = route_root / "owner.token"
    ready_path = route_root / "child_ready.json"
    owner_token = _write_token(token_file)
    mission_id = hashlib.sha256(f"route-fault:{route}".encode()).hexdigest()
    payload_sha256 = hashlib.sha256(f"payload:{route}".encode()).hexdigest()
    environment = dict(os.environ)
    src_root = Path(__file__).resolve().parents[2]
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(src_root), environment.get("PYTHONPATH", "")) if part
    )
    command = [
        sys.executable,
        "-m",
        "maskfactory.steward.route_fault_drill",
        "child",
        "--database",
        str(database),
        "--mission-id",
        mission_id,
        "--payload-sha256",
        payload_sha256,
        "--route",
        route,
        "--token-file",
        str(token_file),
        "--ready-path",
        str(ready_path),
    ]
    process = subprocess.Popen(
        command,
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    ready: dict[str, Any] | None = None
    stdout = ""
    stderr = ""
    try:
        ready = _wait_for_ready(
            process,
            ready_path,
            timeout_seconds=timeout_seconds,
        )
        process.kill()
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    finally:
        if process.poll() is None:
            process.kill()
            stdout, stderr = process.communicate(timeout=timeout_seconds)
    if ready is None or process.returncode in (None, 0):
        raise RouteFaultDrillError("owned child was not forcibly interrupted")
    if stdout or stderr:
        raise RouteFaultDrillError("owned child emitted unexpected output")

    restarted = CanonicalMissionRouteLedger(database)
    reconstructed = restarted.claim_route(
        mission_id=mission_id,
        session_id=SESSION_ID,
        payload_sha256=payload_sha256,
        route=route,
        owner_token=owner_token,
    )
    if reconstructed["generation"] != ready["generation"]:
        raise RouteFaultDrillError("restart created a duplicate route generation")
    if len(restarted.events(mission_id)) != 1:
        raise RouteFaultDrillError("restart duplicated route-claim evidence")

    wrong_token_blocked = False
    try:
        restarted.claim_route(
            mission_id=mission_id,
            session_id=SESSION_ID,
            payload_sha256=payload_sha256,
            route=route,
            owner_token="wrong-owner-" + "x" * 32,
        )
    except RouteAlreadyActive:
        wrong_token_blocked = True
    if not wrong_token_blocked:
        raise RouteFaultDrillError("stale or foreign owner token was accepted")

    restarted.mark_outcome_unknown(
        mission_id=mission_id,
        owner_token=owner_token,
        reason="owned child interrupted before external action acknowledgement",
    )
    unresolved_resend_blocked = False
    alternate_route = next(value for value in sorted(ROUTES) if value != route)
    try:
        CanonicalMissionRouteLedger(database).claim_route(
            mission_id=mission_id,
            session_id=SESSION_ID,
            payload_sha256=payload_sha256,
            route=alternate_route,
            owner_token=owner_token,
        )
    except RouteOutcomeUnknown:
        unresolved_resend_blocked = True
    if not unresolved_resend_blocked:
        raise RouteFaultDrillError("unresolved ambiguity allowed another route")

    reconciled = CanonicalMissionRouteLedger(database).reconcile_unknown(
        mission_id=mission_id,
        owner_token=owner_token,
        resolution="not_submitted",
        reason="durable child receipt proves no external action was attempted",
    )
    if reconciled["state"] != "available":
        raise RouteFaultDrillError("no-submit reconciliation did not release route")
    second_claim = CanonicalMissionRouteLedger(database).claim_route(
        mission_id=mission_id,
        session_id=SESSION_ID,
        payload_sha256=payload_sha256,
        route=route,
        owner_token=owner_token,
    )
    if second_claim["generation"] != 2:
        raise RouteFaultDrillError("post-reconciliation generation is not exact")

    result_sha256 = hashlib.sha256(f"terminal:{route}".encode()).hexdigest()
    CanonicalMissionRouteLedger(database).terminalize(
        mission_id=mission_id,
        owner_token=owner_token,
        disposition="completed",
        result_sha256=result_sha256,
    )
    persisted = CanonicalMissionRouteLedger(database).inspect(mission_id)
    if persisted["state"] != "terminal_pending_release":
        raise RouteFaultDrillError("persisted terminal state was not reconstructed")
    terminal_resend_blocked = False
    try:
        CanonicalMissionRouteLedger(database).claim_route(
            mission_id=mission_id,
            session_id=SESSION_ID,
            payload_sha256=payload_sha256,
            route=alternate_route,
            owner_token=owner_token,
        )
    except RouteAlreadyActive:
        terminal_resend_blocked = True
    if not terminal_resend_blocked:
        raise RouteFaultDrillError("persisted terminal state allowed resend")
    final = CanonicalMissionRouteLedger(database).release_terminal(
        mission_id=mission_id,
        owner_token=owner_token,
    )
    if final["state"] != "completed" or _active_attempt_count(database) != 0:
        raise RouteFaultDrillError("terminal release left active durable state")
    token_file.unlink()
    if token_file.exists():
        raise RouteFaultDrillError("protected owner token survived durable release")

    events = CanonicalMissionRouteLedger(database).events(mission_id)
    return {
        "route": route,
        "mission_id": mission_id,
        "payload_sha256": payload_sha256,
        "actual_owned_child_interrupted": True,
        "initial_generation": ready["generation"],
        "reconstructed_generation": reconstructed["generation"],
        "stale_owner_token_blocked": wrong_token_blocked,
        "unresolved_ambiguity_blocked_resend": unresolved_resend_blocked,
        "no_submit_reconciliation_state": reconciled["state"],
        "terminal_state_reconstructed": persisted["state"],
        "terminal_resend_blocked": terminal_resend_blocked,
        "final_state": final["state"],
        "active_attempts_after_release": 0,
        "protected_token_removed": True,
        "route_events": [event["event"] for event in events],
        "external_action_attempted": False,
    }


def run_all_route_fault_drill(
    output_root: Path,
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Interrupt one owned CPU child per route and reconcile every route."""

    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    cases = [
        _run_route_case(
            output_root,
            route=route,
            timeout_seconds=timeout_seconds,
        )
        for route in sorted(ROUTES)
    ]
    receipt = _seal(
        {
            "schema_version": DRILL_SCHEMA,
            "session_id": SESSION_ID,
            "routes": cases,
            "assertions": {
                "all_governed_routes_covered": {case["route"] for case in cases} == set(ROUTES),
                "owned_process_interruptions_reconstructed_without_duplicate_claim": all(
                    case["initial_generation"] == case["reconstructed_generation"] == 1
                    for case in cases
                ),
                "stale_owner_tokens_rejected": all(
                    case["stale_owner_token_blocked"] for case in cases
                ),
                "unresolved_ambiguity_blocks_resend": all(
                    case["unresolved_ambiguity_blocked_resend"] for case in cases
                ),
                "persisted_terminals_block_resend": all(
                    case["terminal_resend_blocked"] for case in cases
                ),
                "no_active_route_attempts_remain": all(
                    case["active_attempts_after_release"] == 0 for case in cases
                ),
                "all_owner_tokens_removed_after_release": all(
                    case["protected_token_removed"] for case in cases
                ),
                "no_external_gpu_provider_or_broker_action_attempted": all(
                    not case["external_action_attempted"] for case in cases
                ),
            },
            "limitations": [
                "CPU-only canonical-route fault drill; no live GPU lease, broker reservation, or provider job was created.",
                "Production completion remains unclaimed until live route-specific evidence is independently reconciled.",
            ],
            "receipt_sha256": ZERO_SHA256,
        },
        "receipt_sha256",
    )
    if not all(receipt["assertions"].values()):
        raise RouteFaultDrillError("one or more route-fault assertions failed")
    _write_json_exclusive(output_root / "route_fault_drill_receipt.json", receipt)
    return receipt


def validate_route_fault_drill_receipt(receipt: Mapping[str, Any]) -> None:
    """Validate the closed receipt and its canonical self-hash."""

    expected_fields = {
        "schema_version",
        "session_id",
        "routes",
        "assertions",
        "limitations",
        "receipt_sha256",
    }
    if set(receipt) != expected_fields or receipt.get("schema_version") != DRILL_SCHEMA:
        raise RouteFaultDrillError("route-fault receipt field or schema mismatch")
    declared = receipt.get("receipt_sha256")
    zeroed = dict(receipt)
    zeroed["receipt_sha256"] = ZERO_SHA256
    if declared != _canonical_sha256(zeroed):
        raise RouteFaultDrillError("route-fault receipt self-hash mismatch")
    if receipt.get("session_id") != SESSION_ID:
        raise RouteFaultDrillError("route-fault receipt session binding mismatch")
    route_values = receipt.get("routes")
    if (
        not isinstance(route_values, list)
        or len(route_values) != len(ROUTES)
        or any(not isinstance(case, dict) for case in route_values)
        or {case.get("route") for case in route_values} != set(ROUTES)
    ):
        raise RouteFaultDrillError("route-fault receipt route coverage mismatch")
    for case in route_values:
        if set(case) != ROUTE_CASE_FIELDS:
            raise RouteFaultDrillError("route-fault case field set mismatch")
        if (
            not isinstance(case["mission_id"], str)
            or SHA256_RE.fullmatch(case["mission_id"]) is None
            or not isinstance(case["payload_sha256"], str)
            or SHA256_RE.fullmatch(case["payload_sha256"]) is None
            or case["initial_generation"] != 1
            or case["reconstructed_generation"] != 1
            or case["no_submit_reconciliation_state"] != "available"
            or case["terminal_state_reconstructed"] != "terminal_pending_release"
            or case["final_state"] != "completed"
            or case["active_attempts_after_release"] != 0
            or case["route_events"] != EXPECTED_ROUTE_EVENTS
            or not case["actual_owned_child_interrupted"]
            or not case["stale_owner_token_blocked"]
            or not case["unresolved_ambiguity_blocked_resend"]
            or not case["terminal_resend_blocked"]
            or not case["protected_token_removed"]
            or case["external_action_attempted"]
        ):
            raise RouteFaultDrillError("route-fault case semantic mismatch")
    assertions = receipt.get("assertions")
    if (
        not isinstance(assertions, dict)
        or set(assertions) != ASSERTION_FIELDS
        or any(value is not True for value in assertions.values())
    ):
        raise RouteFaultDrillError("route-fault receipt contains a failed assertion")
    limitations = receipt.get("limitations")
    if (
        not isinstance(limitations, list)
        or not limitations
        or any(not isinstance(value, str) or not value for value in limitations)
    ):
        raise RouteFaultDrillError("route-fault receipt limitations are invalid")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    child = subparsers.add_parser("child")
    child.add_argument("--database", type=Path, required=True)
    child.add_argument("--mission-id", required=True)
    child.add_argument("--payload-sha256", required=True)
    child.add_argument("--route", choices=sorted(ROUTES), required=True)
    child.add_argument("--token-file", type=Path, required=True)
    child.add_argument("--ready-path", type=Path, required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--output-root", type=Path, required=True)
    run.add_argument("--timeout-seconds", type=float, default=15.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "child":
            return _child_claim(
                database=args.database,
                mission_id=args.mission_id,
                payload_sha256=args.payload_sha256,
                route=args.route,
                token_file=args.token_file,
                ready_path=args.ready_path,
            )
        receipt = run_all_route_fault_drill(
            args.output_root,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, RouteControlError, RouteFaultDrillError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DRILL_SCHEMA",
    "READY_SCHEMA",
    "RouteFaultDrillError",
    "run_all_route_fault_drill",
    "validate_route_fault_drill_receipt",
]
