#!/usr/bin/env python3
"""Run the CPU-safe MaskFactory autonomy supervisor until signalled."""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from maskfactory.steward.fallback_dispatcher import (  # noqa: E402
    FallbackWorkDispatcher,
)
from maskfactory.steward.fallback_campaign_producer import (  # noqa: E402
    FallbackCampaignProducer,
)
from maskfactory.steward.openrouter_advisory import (  # noqa: E402
    MANAGER_PATH as OPENROUTER_MANAGER_PATH,
    POLICY_PATH as OPENROUTER_POLICY_PATH,
    STATE_ROOT as OPENROUTER_STATE_ROOT,
)
from maskfactory.steward.serverless_broker import (  # noqa: E402
    BROKER_ROOT,
    CONFIG_PATH,
    MANAGER_PATH as SERVERLESS_MANAGER_PATH,
)
from maskfactory.steward.supervisor import CpuSafeSupervisor  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--supervisor-id", required=True)
    parser.add_argument("--heartbeat-seconds", type=float, default=5.0)
    parser.add_argument("--fallback-inbox", type=Path)
    parser.add_argument(
        "--tracker-path",
        type=Path,
        default=PROJECT_ROOT / "Plan" / "Tracker" / "tracker.json",
    )
    parser.add_argument(
        "--no-auto-produce-openrouter",
        action="store_true",
        help="Disable tracker-driven governed OpenRouter campaign production.",
    )
    parser.add_argument("--serverless-manager", type=Path, default=SERVERLESS_MANAGER_PATH)
    parser.add_argument("--serverless-config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--serverless-broker-root", type=Path, default=BROKER_ROOT)
    parser.add_argument(
        "--serverless-api-key-file",
        type=Path,
        default=(Path("/tmp/maskfactory-runpod-api-key") if os.name != "nt" else None),
        help=(
            "Optional protected mode-0600 file used only to inject "
            "RUNPOD_API_KEY into broker subprocesses. When omitted, the "
            "broker inherits the process environment. The key is never "
            "placed in argv or artifacts."
        ),
    )
    parser.add_argument("--openrouter-manager", type=Path, default=OPENROUTER_MANAGER_PATH)
    parser.add_argument("--openrouter-policy", type=Path, default=OPENROUTER_POLICY_PATH)
    parser.add_argument(
        "--openrouter-state-root",
        type=Path,
        default=OPENROUTER_STATE_ROOT,
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Perform one governed fallback poll, heartbeat, and clean shutdown.",
    )
    parser.add_argument("--max-serverless-workers", type=int, default=4)
    parser.add_argument("--max-openrouter-workers", type=int, default=4)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.heartbeat_seconds <= 0:
        raise SystemExit("--heartbeat-seconds must be positive")
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_args: stop.set())
    supervisor = CpuSafeSupervisor(args.state_root, supervisor_id=args.supervisor_id)
    fallback_inbox = args.fallback_inbox or args.state_root / "fallback_inbox"
    dispatcher = FallbackWorkDispatcher(
        inbox_root=fallback_inbox,
        state_root=args.state_root / "fallback_dispatcher",
        serverless_manager_path=args.serverless_manager,
        serverless_config_path=args.serverless_config,
        serverless_broker_root=args.serverless_broker_root,
        serverless_api_key_file=args.serverless_api_key_file,
        openrouter_manager_path=args.openrouter_manager,
        openrouter_policy_path=args.openrouter_policy,
        openrouter_manager_state_root=args.openrouter_state_root,
        max_serverless_workers=args.max_serverless_workers,
        max_openrouter_workers=args.max_openrouter_workers,
    )
    producer = None
    if not args.no_auto_produce_openrouter:
        producer = FallbackCampaignProducer(
            tracker_path=args.tracker_path,
            inbox_root=fallback_inbox,
            openrouter_manager_path=args.openrouter_manager,
            openrouter_policy_path=args.openrouter_policy,
        )
    supervisor.start()
    try:
        while True:
            if producer is not None:
                try:
                    producer.produce()
                except Exception as exc:
                    supervisor.record_exception("recovery", f"fallback producer: {exc}")
            supervisor.update_queue(dispatcher.pending_ids())
            try:
                dispatcher.poll_once()
            except Exception as exc:
                supervisor.record_exception("recovery", str(exc))
            supervisor.heartbeat()
            if args.once or stop.wait(args.heartbeat_seconds):
                break
    finally:
        supervisor.shutdown(reason="signal_or_clean_exit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
