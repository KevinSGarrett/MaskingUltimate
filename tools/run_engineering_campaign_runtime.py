#!/usr/bin/env python3
"""Build, validate, or execute one guarded 25-mission steward campaign."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from maskfactory.steward.engineering_campaign_runtime import (  # noqa: E402
    BINDING_NAME,
    EngineeringCampaignRuntimeController,
    EngineeringCampaignRuntimeError,
    build_engineering_campaign_runtime_binding,
    validate_engineering_campaign_runtime_binding,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--campaign-root", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--campaign-id", required=True)
    build.add_argument(
        "--mission-root",
        action="append",
        type=Path,
        required=True,
        help="Repeat exactly 25 times in execution order.",
    )
    build.add_argument("--request-name", default="request.json")

    subparsers.add_parser("validate")

    run = subparsers.add_parser("run")
    run.add_argument("--database", type=Path, required=True)
    run.add_argument("--port", type=int)
    return parser


def _require_guard_context(
    *,
    campaign_root: Path,
    campaign_id: str,
    payload_sha256: str,
) -> dict[str, str]:
    expected = {
        "MASKFACTORY_SHARED_GPU_GUARD_ACTIVE": "1",
        "MASKFACTORY_SHARED_GPU_GUARD_JOB_ID": campaign_id,
        "MASKFACTORY_SHARED_GPU_GUARD_PAYLOAD_SHA256": payload_sha256,
        "MASKFACTORY_SHARED_GPU_GUARD_RECEIPT_ROOT": str(
            campaign_root.resolve()
        ),
    }
    for name, value in expected.items():
        if os.environ.get(name) != value:
            raise EngineeringCampaignRuntimeError(
                f"guarded campaign child context mismatch: {name}"
            )
    request_id = os.environ.get("MASKFACTORY_SHARED_GPU_GUARD_REQUEST_ID")
    if not request_id or any(character in request_id for character in "/\\\0"):
        raise EngineeringCampaignRuntimeError(
            "guarded campaign lease request identity is unavailable"
        )
    return {**expected, "MASKFACTORY_SHARED_GPU_GUARD_REQUEST_ID": request_id}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    campaign_root = args.campaign_root.resolve()
    if args.command == "build":
        result = build_engineering_campaign_runtime_binding(
            campaign_root=campaign_root,
            campaign_id=args.campaign_id,
            contract_path=args.contract,
            mission_roots=args.mission_root,
            request_name=args.request_name,
        )
    else:
        result = validate_engineering_campaign_runtime_binding(
            campaign_root / BINDING_NAME,
            campaign_root=campaign_root,
            contract_path=args.contract,
        )
        if args.command == "run":
            _require_guard_context(
                campaign_root=campaign_root,
                campaign_id=result["campaign_id"],
                payload_sha256=result["binding_sha256"],
            )
            result = EngineeringCampaignRuntimeController(
                contract_path=args.contract,
                campaign_root=campaign_root,
                database=args.database,
                port=args.port,
            ).run()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
