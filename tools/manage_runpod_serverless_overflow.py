#!/usr/bin/env python3
"""Operate the shared ComfyUI/MaskFactory RunPod Serverless overflow broker."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from maskfactory.autonomy.serverless_overflow import (  # noqa: E402
    OverflowBroker,
    OverflowConfig,
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
        observed_spend = args.observed_provider_spend_usd
        observed_hour_spend = args.observed_provider_hour_spend_usd
        endpoint_ids = [
            endpoint_id
            for endpoint_id in config.endpoints.values()
            if isinstance(endpoint_id, str) and endpoint_id
        ]
        if observed_spend is None:
            observed_spend = _client().daily_endpoint_spend(endpoint_ids)
        if observed_hour_spend is None:
            observed_hour_spend = _client().rolling_hour_endpoint_spend(endpoint_ids)
        output = broker.reserve(
            session_id=args.session_id,
            profile=args.profile,
            payload=_read(args.payload),
            requested_seconds=args.requested_seconds,
            observed_provider_spend_usd=observed_spend,
            observed_provider_hour_spend_usd=observed_hour_spend,
        )
    elif args.command == "submit":
        output = broker.submit_reserved(args.job_id, _read(args.payload), _client())
    elif args.command == "reconcile":
        output = broker.reconcile(args.job_id, _client())
    elif args.command == "cancel":
        output = broker.cancel(args.job_id, _client())
    else:
        output = broker.report(billing_day=args.billing_day)
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
