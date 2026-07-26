#!/usr/bin/env python3
"""Run the CPU-safe MaskFactory autonomy supervisor until signalled."""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from maskfactory.steward.fallback_dispatcher import (  # noqa: E402
    FallbackWorkDispatcher,
)
from maskfactory.steward.fallback_campaign_producer import (  # noqa: E402
    DEFAULT_ADVISORY_WORK_KINDS,
    FallbackCampaignProducer,
)
from maskfactory.steward.openrouter_advisory import (  # noqa: E402
    MANAGER_PATH as OPENROUTER_MANAGER_PATH,
    POLICY_PATH as OPENROUTER_POLICY_PATH,
    STATE_ROOT as OPENROUTER_STATE_ROOT,
)
from maskfactory.steward.local_campaign_dispatcher import (  # noqa: E402
    LocalEngineeringCampaignDispatcher,
)
from maskfactory.steward.serverless_broker import (  # noqa: E402
    BROKER_ROOT,
    CONFIG_PATH,
    MANAGER_PATH as SERVERLESS_MANAGER_PATH,
)
from maskfactory.steward.serverless_work_producer import (  # noqa: E402
    ServerlessWorkProducer,
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
    parser.add_argument(
        "--openrouter-work-kinds",
        default=",".join(DEFAULT_ADVISORY_WORK_KINDS),
        help="Comma-separated governed advisory modes produced per campaign.",
    )
    parser.add_argument(
        "--serverless-ready-root",
        type=Path,
        default=PROJECT_ROOT / ".codex-ops" / "serverless-ready",
    )
    parser.add_argument(
        "--no-auto-produce-serverless",
        action="store_true",
        help="Disable immutable prepared-Serverless workload discovery.",
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
    parser.add_argument("--local-campaign-inbox", type=Path)
    parser.add_argument("--local-runtime-contract", type=Path)
    parser.add_argument("--local-steward-database", type=Path)
    parser.add_argument(
        "--local-lease-database",
        type=Path,
        default=Path(
            "/workspace/.maskfactory/shared_pod_coordination/"
            "shared_gpu_leases_v1.sqlite"
        ),
    )
    parser.add_argument(
        "--local-lease-manager",
        type=Path,
        default=Path(
            "/workspace/.maskfactory/shared_pod_coordination/tools/"
            "manage_shared_pod_gpu_lease_v2.py"
        ),
    )
    parser.add_argument(
        "--local-guard-tool",
        type=Path,
        default=PROJECT_ROOT / "tools" / "run_with_shared_pod_gpu_lease.py",
    )
    parser.add_argument(
        "--local-runtime-tool",
        type=Path,
        default=PROJECT_ROOT / "tools" / "run_engineering_campaign_runtime.py",
    )
    parser.add_argument("--local-max-runtime-seconds", type=int, default=3600)
    return parser


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _append_event(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o600,
    )
    with os.fdopen(descriptor, "ab") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def _reconstruct_cumulative(path: Path) -> dict[str, int]:
    totals = {
        "openrouter_created": 0,
        "serverless_created": 0,
        "dispatch_terminal": 0,
        "duplicates_blocked": 0,
        "dispatch_cycles": 0,
    }
    if not path.is_file():
        return totals
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise SystemExit("fallback throughput event ledger is unreadable") from exc
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit("fallback throughput event ledger is corrupt") from exc
        cycle = event.get("cycle")
        if not isinstance(cycle, dict):
            raise SystemExit("fallback throughput event ledger is contradictory")
        totals["openrouter_created"] += int(cycle.get("openrouter_created") or 0)
        totals["serverless_created"] += int(cycle.get("serverless_created") or 0)
        totals["dispatch_terminal"] += int(cycle.get("terminal_results") or 0)
        totals["duplicates_blocked"] += int(cycle.get("duplicates_blocked") or 0)
        totals["dispatch_cycles"] += 1
    return totals


def main() -> int:
    args = build_parser().parse_args()
    if args.heartbeat_seconds <= 0:
        raise SystemExit("--heartbeat-seconds must be positive")
    canonical_tracker = PROJECT_ROOT / "Plan" / "Tracker" / "tracker.json"
    if args.tracker_path.resolve() != canonical_tracker.resolve():
        raise SystemExit(
            "refusing non-authoritative tracker path; deploy from the current "
            "project root instead of a stale worktree"
        )
    work_kinds = tuple(
        value.strip()
        for value in args.openrouter_work_kinds.split(",")
        if value.strip()
    )
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
            advisory_work_kinds=work_kinds,
            openrouter_manager_path=args.openrouter_manager,
            openrouter_policy_path=args.openrouter_policy,
        )
    serverless_producer = None
    if not args.no_auto_produce_serverless:
        serverless_producer = ServerlessWorkProducer(
            ready_root=args.serverless_ready_root,
            inbox_root=fallback_inbox,
        )
    local_dispatcher = None
    local_arguments = (
        args.local_campaign_inbox,
        args.local_runtime_contract,
        args.local_steward_database,
    )
    if any(value is not None for value in local_arguments):
        if not all(value is not None for value in local_arguments):
            raise SystemExit(
                "--local-campaign-inbox, --local-runtime-contract, and "
                "--local-steward-database must be supplied together"
            )
        local_dispatcher = LocalEngineeringCampaignDispatcher(
            inbox_root=args.local_campaign_inbox,
            state_root=args.state_root / "local_campaign_dispatcher",
            runtime_contract_path=args.local_runtime_contract,
            steward_database=args.local_steward_database,
            lease_database=args.local_lease_database,
            lease_manager_path=args.local_lease_manager,
            guard_tool_path=args.local_guard_tool,
            runtime_tool_path=args.local_runtime_tool,
            max_runtime_seconds=args.local_max_runtime_seconds,
        )
    throughput_path = args.state_root / "fallback_throughput.json"
    throughput_events_path = args.state_root / "fallback_throughput_events.jsonl"
    cumulative = _reconstruct_cumulative(throughput_events_path)
    supervisor.start()
    try:
        while True:
            openrouter_receipts: list[dict[str, object]] = []
            serverless_receipts: list[dict[str, object]] = []
            if producer is not None:
                try:
                    openrouter_receipts = producer.produce()
                except Exception as exc:
                    supervisor.record_exception("recovery", f"fallback producer: {exc}")
            if serverless_producer is not None:
                try:
                    serverless_receipts = serverless_producer.produce()
                except Exception as exc:
                    supervisor.record_exception(
                        "recovery",
                        f"serverless producer: {exc}",
                    )
            fallback_ids = dispatcher.pending_ids()
            local_ids = (
                local_dispatcher.pending_ids()
                if local_dispatcher is not None
                else ()
            )
            overlap = set(fallback_ids).intersection(local_ids)
            supervisor.update_queue(
                tuple(dict.fromkeys((*local_ids, *fallback_ids)))
            )
            if local_dispatcher is not None:
                try:
                    local_results = local_dispatcher.poll_once(
                        excluded_campaign_ids=tuple(sorted(overlap))
                    )
                    active = next(
                        (
                            row
                            for row in local_results
                            if row.get("state") == "active"
                        ),
                        None,
                    )
                    if active is not None:
                        supervisor.update_campaign(
                            str(active["campaign_id"]),
                            state="active",
                        )
                    elif local_results and any(
                        row.get("outcome") in {"terminal", "failed_closed"}
                        for row in local_results
                    ):
                        terminal_result = next(
                            row
                            for row in local_results
                            if row.get("outcome") in {"terminal", "failed_closed"}
                        )
                        supervisor.update_campaign(
                            str(terminal_result["campaign_id"]),
                            state="terminal",
                        )
                    elif local_ids:
                        supervisor.update_campaign(local_ids[0], state="planned")
                    else:
                        supervisor.update_campaign(None, state="idle")
                except Exception as exc:
                    supervisor.record_exception(
                        "campaign",
                        f"local campaign dispatcher: {exc}",
                    )
            if overlap:
                supervisor.record_exception(
                    "authority",
                    "dual-route identity conflict: " + ", ".join(sorted(overlap)),
                )
                supervisor.heartbeat()
                if args.once or stop.wait(args.heartbeat_seconds):
                    break
                continue
            try:
                dispatch_results = dispatcher.poll_once()
            except Exception as exc:
                supervisor.record_exception("recovery", str(exc))
                dispatch_results = []
            cumulative["openrouter_created"] += sum(
                receipt.get("created") is True for receipt in openrouter_receipts
            )
            cumulative["serverless_created"] += sum(
                receipt.get("created") is True for receipt in serverless_receipts
            )
            terminal_results = sum(
                result.get("state") == "terminal"
                or result.get("disposition") in {"completed", "failed"}
                for result in dispatch_results
            )
            duplicates_blocked = sum(
                result.get("state") == "route_unavailable"
                and "terminal reservation already exists"
                in str(result.get("detail") or "")
                for result in dispatch_results
            )
            cumulative["dispatch_terminal"] += terminal_results
            cumulative["duplicates_blocked"] += duplicates_blocked
            cumulative["dispatch_cycles"] += 1
            discovered = dispatcher.discover()
            queue_by_route = {
                route: sum(item["route"] == route for _, item in discovered)
                for route in ("openrouter_advisory", "serverless_overflow")
            }
            cycle = {
                "openrouter_candidates": len(openrouter_receipts),
                "openrouter_created": sum(
                    receipt.get("created") is True
                    for receipt in openrouter_receipts
                ),
                "serverless_candidates": len(serverless_receipts),
                "serverless_created": sum(
                    receipt.get("created") is True
                    for receipt in serverless_receipts
                ),
                "dispatch_results": len(dispatch_results),
                "terminal_results": terminal_results,
                "duplicates_blocked": duplicates_blocked,
            }
            updated_at = time.time()
            event = {
                "schema_version": "maskfactory.fallback_throughput_event.v1",
                "updated_at": updated_at,
                "supervisor_source_sha256": _file_sha256(Path(__file__)),
                "tracker_sha256": _file_sha256(args.tracker_path),
                "cycle": cycle,
            }
            _append_event(throughput_events_path, event)
            _atomic_json(
                throughput_path,
                {
                    "schema_version": "maskfactory.fallback_throughput.v1",
                    "status": "productive" if dispatch_results else "idle",
                    "updated_at": updated_at,
                    "project_root": str(PROJECT_ROOT),
                    "supervisor_source_sha256": _file_sha256(Path(__file__)),
                    "tracker_path": str(args.tracker_path.resolve()),
                    "tracker_sha256": _file_sha256(args.tracker_path),
                    "openrouter_work_kinds": list(work_kinds),
                    "serverless_ready_root": str(args.serverless_ready_root.resolve()),
                    "cycle": cycle,
                    "queue_by_route": queue_by_route,
                    "cumulative": cumulative,
                    "event_ledger_path": str(throughput_events_path.resolve()),
                },
            )
            supervisor.heartbeat()
            if args.once or stop.wait(args.heartbeat_seconds):
                break
    finally:
        supervisor.shutdown(reason="signal_or_clean_exit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
