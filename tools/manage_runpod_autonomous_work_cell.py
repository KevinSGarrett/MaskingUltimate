#!/usr/bin/env python3
"""Operate the durable RunPod autonomous work-cell queue."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from maskfactory.autonomy.work_cell import AutonomousWorkCell


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    admit = commands.add_parser("admit")
    admit.add_argument("--manifest", type=Path, required=True)

    seed = commands.add_parser("seed")
    seed.add_argument("--mission-id", required=True)
    seed.add_argument("--records", type=Path, required=True)

    claim = commands.add_parser("claim")
    claim.add_argument("--mission-id", required=True)
    claim.add_argument("--owner", required=True)

    heartbeat = commands.add_parser("heartbeat")
    heartbeat.add_argument("--mission-id", required=True)
    heartbeat.add_argument("--record-id", required=True)
    heartbeat.add_argument("--lease-token", required=True)

    result = commands.add_parser("result")
    result.add_argument("--mission-id", required=True)
    result.add_argument("--record-id", required=True)
    result.add_argument("--lease-token", required=True)
    result.add_argument("--receipt", type=Path, required=True)

    recover = commands.add_parser("recover")
    recover.add_argument("--mission-id", required=True)

    report = commands.add_parser("report")
    report.add_argument("--mission-id", required=True)
    report.add_argument("--output", type=Path)

    args = parser.parse_args()
    cell = AutonomousWorkCell(args.root)
    if args.command == "admit":
        output = cell.admit(_read(args.manifest))
    elif args.command == "seed":
        output = cell.seed_records(args.mission_id, _read(args.records))
    elif args.command == "claim":
        output = cell.claim(args.mission_id, owner=args.owner)
    elif args.command == "heartbeat":
        output = {
            "lease_expires_at": cell.heartbeat(args.mission_id, args.record_id, args.lease_token)
        }
    elif args.command == "result":
        output = cell.apply_result(
            args.mission_id, args.record_id, args.lease_token, _read(args.receipt)
        )
    elif args.command == "recover":
        output = cell.recover_expired(args.mission_id)
    else:
        output = (
            cell.write_report(args.mission_id, args.output)
            if args.output
            else cell.report(args.mission_id)
        )
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
