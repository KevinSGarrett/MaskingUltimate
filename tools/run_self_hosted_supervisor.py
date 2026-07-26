#!/usr/bin/env python3
"""Run the CPU-safe MaskFactory autonomy supervisor until signalled."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from maskfactory.steward.supervisor import CpuSafeSupervisor  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--supervisor-id", required=True)
    parser.add_argument("--heartbeat-seconds", type=float, default=5.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.heartbeat_seconds <= 0:
        raise SystemExit("--heartbeat-seconds must be positive")
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_args: stop.set())
    supervisor = CpuSafeSupervisor(args.state_root, supervisor_id=args.supervisor_id)
    supervisor.start()
    try:
        while not stop.wait(args.heartbeat_seconds):
            supervisor.heartbeat()
    finally:
        supervisor.shutdown(reason="signal_or_clean_exit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
