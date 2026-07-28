#!/usr/bin/env python3
"""Stage one exact prepared payload for CPU-only Serverless discovery."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from maskfactory.steward.serverless_work_producer import (  # noqa: E402
    PAYLOAD_NAME,
    WORKLOAD_NAME,
    WORKLOAD_SCHEMA,
    canonical_sha256,
    file_sha256,
    seal_serverless_workload,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--ready-root", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--requested-seconds", type=int, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--profile", choices=("maskfactory",), default="maskfactory")
    parser.add_argument("--source-receipt", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.requested_seconds <= 0:
        raise SystemExit("--requested-seconds must be positive")
    if Path(args.label).name != args.label or args.label in {".", ".."}:
        raise SystemExit("--label must be a safe single path component")
    try:
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"payload is unreadable: {exc}") from exc
    if not isinstance(payload, dict) or not payload:
        raise SystemExit("payload must be a non-empty JSON object")
    identity = {
        "schema_version": WORKLOAD_SCHEMA,
        "session_id": args.session_id,
        "profile": args.profile,
        "payload_sha256": canonical_sha256(payload),
        "requested_seconds": args.requested_seconds,
    }
    destination = args.ready_root / args.label
    if destination.exists():
        raise SystemExit("prepared workload destination already exists")
    temporary = args.ready_root / f".{args.label}.{os.getpid()}.tmp"
    args.ready_root.mkdir(parents=True, exist_ok=True)
    temporary.mkdir(mode=0o700)
    try:
        target_payload = temporary / PAYLOAD_NAME
        shutil.copyfile(args.payload, target_payload)
        manifest = seal_serverless_workload(
            {
                **identity,
                "mission_id": canonical_sha256(identity),
                "payload_file": PAYLOAD_NAME,
                "payload_raw_sha256": file_sha256(target_payload),
                "source_receipt_sha256": (
                    file_sha256(args.source_receipt) if args.source_receipt is not None else None
                ),
            }
        )
        (temporary / WORKLOAD_NAME).write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    print(
        json.dumps(
            {
                "mission_id": manifest["mission_id"],
                "payload_sha256": manifest["payload_sha256"],
                "payload_raw_sha256": manifest["payload_raw_sha256"],
                "workload_sha256": manifest["self_sha256"],
                "destination": str(destination),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
