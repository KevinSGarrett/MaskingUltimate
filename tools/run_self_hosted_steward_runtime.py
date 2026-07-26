#!/usr/bin/env python3
"""Operate one hash-bound self-hosted steward mission on the authorized Pod."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.steward.runtime import (
    StewardRuntimeController,
    load_runtime_contract,
    validate_runtime_files,
)


def _controller(args: argparse.Namespace) -> StewardRuntimeController:
    return StewardRuntimeController(
        contract_path=args.contract,
        mission_root=args.mission_root,
        database=args.database,
        port=args.port,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate", help="Validate contract and accepted runtime bytes."
    )
    validate.add_argument(
        "--skip-validated-mission",
        action="store_true",
        help="Skip the historical V3 executable/receipt byte checks.",
    )

    for command in ("admit", "launch", "health", "reconcile", "shutdown"):
        child = subparsers.add_parser(command)
        child.add_argument("--mission-root", type=Path, required=True)
        child.add_argument("--database", type=Path, required=True)
        child.add_argument("--port", type=int)

    submit = subparsers.add_parser("submit")
    submit.add_argument("--mission-root", type=Path, required=True)
    submit.add_argument("--database", type=Path, required=True)
    submit.add_argument("--port", type=int)
    submit.add_argument("--request", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "validate":
        contract = load_runtime_contract(args.contract)
        observed = validate_runtime_files(
            contract,
            include_validated_mission=not args.skip_validated_mission,
        )
        result = {
            "status": "PASS",
            "contract_sha256": contract["contract_sha256"],
            "validated_sha256": observed,
        }
    else:
        controller = _controller(args)
        if args.command == "admit":
            result = controller.admit()
        elif args.command == "launch":
            result = controller.launch()
        elif args.command == "health":
            result = controller.health()
        elif args.command == "submit":
            result = controller.submit(args.request)
        elif args.command == "reconcile":
            result = controller.reconcile()
        elif args.command == "shutdown":
            result = controller.shutdown()
        else:  # pragma: no cover - argparse guarantees the closed command set
            raise RuntimeError(f"unsupported command: {args.command}")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
