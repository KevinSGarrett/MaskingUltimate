#!/usr/bin/env python3
"""Operate the shared ComfyUI/MaskFactory RunPod Serverless overflow broker.

This is the one canonical entry point used by the MaskFactory supervisor.  It
owns provider communication, while callers are limited to the broker's
decide/reserve/submit/reconcile protocol.
"""

from __future__ import annotations

import argparse
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
    broker = OverflowBroker(config, root=args.root)
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
    else:
        output = broker.report(billing_day=args.billing_day)
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
