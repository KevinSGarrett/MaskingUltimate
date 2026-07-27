#!/usr/bin/env python3
"""Operate the shared ComfyUI/MaskFactory RunPod Serverless overflow broker.

This is the one canonical entry point used by the MaskFactory supervisor.  It
owns provider communication, while callers are limited to the broker's
decide/reserve/submit/reconcile protocol.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from maskfactory.autonomy.serverless_overflow import (  # noqa: E402
    OverflowBroker,
    OverflowConfig,
    OverflowError,
    RunPodClient,
    probe_local_gpu,
)
from maskfactory.steward.continuous_contract import canonical_sha256  # noqa: E402

ZERO_SHA256 = "0" * 64


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _execution_host_preflight(
    *,
    config: OverflowConfig,
    config_path: Path,
    broker_root: Path | None,
    session_id: str,
    expected_manager_sha256: str,
    expected_config_sha256: str,
) -> dict[str, Any]:
    """Return a sealed, provider-free receipt for one actual execution host.

    This command deliberately does not instantiate ``OverflowBroker``: doing
    so would create or change a ledger before the host mapping and source
    binding are proven.  It also makes no provider request.  A caller may only
    advance to the canonical ``decide`` command after this receipt is retained
    in its immutable parent contract.
    """

    manager = Path(__file__).resolve(strict=True)
    resolved_config = config_path.resolve(strict=True)
    if broker_root is None:
        raise SystemExit("preflight requires an explicit --root")
    resolved_root = broker_root.resolve(strict=True)
    configured_root = config.runpod_root.resolve(strict=True)
    if resolved_root != configured_root:
        raise SystemExit("preflight root does not match config durability.runpod_root")
    ledger = resolved_root / config.sqlite_filename
    if not ledger.is_file():
        raise SystemExit("preflight ledger is missing")
    with ledger.open("rb") as handle:
        ledger_header = handle.read(16)
    if ledger_header != b"SQLite format 3\x00":
        raise SystemExit("preflight ledger is not a SQLite database")
    profile = config.sessions.get(session_id)
    if profile is None:
        raise SystemExit("session is not authorized for shared overflow")

    manager_sha256 = _file_sha256(manager)
    config_sha256 = _file_sha256(resolved_config)
    if expected_manager_sha256 != manager_sha256:
        raise SystemExit("preflight manager hash mismatch")
    if expected_config_sha256 != config_sha256:
        raise SystemExit("preflight config hash mismatch")

    receipt: dict[str, Any] = {
        "schema_version": "maskfactory.serverless_execution_host_preflight.v1",
        "session_id": session_id,
        "profile": profile,
        "provider_calls": False,
        "broker_write": False,
        "execution_host": {
            "python": str(Path(sys.executable).resolve()),
            "manager_path": str(manager),
            "manager_sha256": manager_sha256,
            "config_path": str(resolved_config),
            "config_sha256": config_sha256,
            "broker_root": str(resolved_root),
            "ledger_path": str(ledger),
            "ledger_sha256": _file_sha256(ledger),
            "ledger_bytes": ledger.stat().st_size,
        },
        "canonical_decide_argv": [
            str(Path(sys.executable).resolve()),
            str(manager),
            "--config",
            str(resolved_config),
            "--root",
            str(resolved_root),
            "decide",
            "--session-id",
            session_id,
        ],
        "receipt_sha256": ZERO_SHA256,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("job payload must be a JSON object")
    return value


def _client() -> RunPodClient:
    return RunPodClient(os.environ.get("RUNPOD_API_KEY", ""))


def _ledger_observed_spend(broker: OverflowBroker) -> tuple[float, float]:
    """Return terminal-only ledger spend for a conservative billing fallback.

    ``OverflowBroker.reserve`` separately adds active reservations, so including
    them here would double count.  Terminal jobs without an exact provider
    amount retain their reservation, which is the conservative local estimate.
    """

    report = broker.report()
    now = time.time()
    hourly_cutoff = now - broker.config.rolling_hour_seconds
    daily = 0.0
    hourly = 0.0
    for row in report["jobs"]:
        if row.get("state") not in {"completed", "failed"}:
            continue
        amount = float(row.get("actual_usd") or row["reserved_usd"])
        daily += amount
        if float(row["created_at"]) >= hourly_cutoff:
            hourly += amount
    return daily, hourly


def _provider_spend_observation(
    *,
    broker: OverflowBroker,
    config: OverflowConfig,
    client: RunPodClient,
    observed_daily: float | None,
    observed_hourly: float | None,
) -> tuple[float, float, str]:
    """Read provider spend, falling back only for the known billing 403.

    A billing-permission failure is not evidence of capacity.  The durable
    broker ledger remains the conservative admission source for that case; all
    other provider failures stay fail-closed.
    """

    endpoint_ids = sorted(
        endpoint_id
        for endpoint_id in config.endpoints.values()
        if isinstance(endpoint_id, str) and endpoint_id
    )
    fallback_daily, fallback_hourly = _ledger_observed_spend(broker)
    source = "provider"
    if observed_daily is None:
        try:
            observed_daily = client.daily_endpoint_spend(endpoint_ids)
        except OverflowError as exc:
            if "HTTP 403" not in str(exc):
                raise
            observed_daily = fallback_daily
            source = "ledger_fallback"
    if observed_hourly is None:
        try:
            observed_hourly = client.rolling_hour_endpoint_spend(endpoint_ids)
        except OverflowError as exc:
            if "HTTP 403" not in str(exc):
                raise
            observed_hourly = fallback_hourly
            source = "ledger_fallback"
    return float(observed_daily), float(observed_hourly), source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "runpod_serverless_overflow.yaml",
    )
    parser.add_argument("--root", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)

    preflight = commands.add_parser("preflight")
    preflight.add_argument("--session-id", required=True)
    preflight.add_argument("--expected-manager-sha256", required=True)
    preflight.add_argument("--expected-config-sha256", required=True)

    decide = commands.add_parser("decide")
    decide.add_argument("--session-id", required=True)

    reserve = commands.add_parser("reserve")
    reserve.add_argument("--session-id", required=True)
    reserve.add_argument("--profile", choices=("comfyui", "maskfactory"), required=True)
    reserve.add_argument("--payload", type=Path, required=True)
    reserve.add_argument("--requested-seconds", type=int, required=True)
    reserve.add_argument("--observed-provider-spend-usd", type=float)
    reserve.add_argument("--observed-provider-hour-spend-usd", type=float)

    submit = commands.add_parser("submit")
    submit.add_argument("--job-id", required=True)
    submit.add_argument("--payload", type=Path, required=True)

    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("--job-id", required=True)

    commands.add_parser("reconcile-active")

    cancel = commands.add_parser("cancel")
    cancel.add_argument("--job-id", required=True)

    report = commands.add_parser("report")
    report.add_argument("--billing-day")

    args = parser.parse_args()
    config = OverflowConfig.load(args.config)
    if args.command == "preflight":
        output = _execution_host_preflight(
            config=config,
            config_path=args.config,
            broker_root=args.root,
            session_id=args.session_id,
            expected_manager_sha256=args.expected_manager_sha256,
            expected_config_sha256=args.expected_config_sha256,
        )
    else:
        broker = OverflowBroker(config, root=args.root)
        output = None
    if args.command == "decide":
        profile = config.sessions.get(args.session_id)
        if profile is None:
            raise SystemExit("session is not authorized for shared overflow")
        local = probe_local_gpu(config)
        output = {
            "session_id": args.session_id,
            "profile": profile,
            "route": "local_pod" if local["available"] else "serverless_overflow",
            "local_gpu": local,
        }
    elif args.command == "reserve":
        observed_daily, observed_hourly, spend_source = _provider_spend_observation(
            broker=broker,
            config=config,
            client=_client(),
            observed_daily=args.observed_provider_spend_usd,
            observed_hourly=args.observed_provider_hour_spend_usd,
        )
        output = broker.reserve(
            session_id=args.session_id,
            profile=args.profile,
            payload=_read(args.payload),
            requested_seconds=args.requested_seconds,
            observed_provider_spend_usd=observed_daily,
            observed_provider_hour_spend_usd=observed_hourly,
        )
        output["provider_spend_source"] = spend_source
    elif args.command == "submit":
        output = broker.submit_reserved(args.job_id, _read(args.payload), _client())
    elif args.command == "reconcile":
        output = broker.reconcile(args.job_id, _client())
    elif args.command == "reconcile-active":
        output = broker.reconcile_active(_client())
    elif args.command == "cancel":
        output = broker.cancel(args.job_id, _client())
    elif args.command == "report":
        output = broker.report(billing_day=args.billing_day)
    assert output is not None
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
