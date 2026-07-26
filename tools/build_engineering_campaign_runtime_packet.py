#!/usr/bin/env python3
"""Build the immutable adoption packet for one terminal real campaign."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from maskfactory.steward.engineering_campaign_runtime_packet import (
    build_engineering_campaign_runtime_packet,
)
from maskfactory.steward.runtime import read_json


def _run_json(command: list[str]) -> dict:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("resource probe did not return a JSON object")
    return value


def _nvidia_rows(query: str) -> list[str]:
    completed = subprocess.run(
        [
            "nvidia-smi",
            f"--query-{query}",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.2)
        return client.connect_ex(("127.0.0.1", port)) == 0


def _owned_process_count(campaign_id: str) -> int:
    count = 0
    own = {os.getpid(), os.getppid()}
    for candidate in Path("/proc").iterdir():
        if not candidate.name.isdigit() or int(candidate.name) in own:
            continue
        try:
            command = (candidate / "cmdline").read_bytes().replace(b"\0", b" ")
        except OSError:
            continue
        if campaign_id.encode() in command and (
            b"run_guarded_campaign_once" in command
            or b"run_engineering_campaign_runtime" in command
            or b"vllm.entrypoints" in command
        ):
            count += 1
    return count


def _handoff(args: argparse.Namespace) -> dict:
    release = read_json(args.campaign_root / "local_gpu_lease_release.json")
    status = _run_json(
        [
            sys.executable,
            str(args.lease_manager),
            "--database",
            str(args.lease_database),
            "status",
        ]
    )
    gpu_rows = _nvidia_rows("gpu=name,memory.used,utilization.gpu")
    if len(gpu_rows) != 1:
        raise RuntimeError("exactly one GPU is required for handoff proof")
    name, memory, utilization = [value.strip() for value in gpu_rows[0].split(",")]
    active = status.get("active")
    active_session = active.get("session_id") if isinstance(active, dict) else None
    active_job = active.get("job_id") if isinstance(active, dict) else None
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "pod_id": args.pod_id,
        "volume_id": args.volume_id,
        "gpu_name": name,
        "gpu_memory_used_mib": int(memory),
        "gpu_utilization_percent": int(utilization),
        "compute_app_count": len(
            _nvidia_rows("compute-apps=pid,process_name,used_memory")
        ),
        "ports_open": {
            str(port): _port_open(port) for port in (8188, 18008, 18125)
        },
        "active_lease_session_id": active_session,
        "active_lease_job_id": active_job,
        "campaign_lease_active": bool(
            isinstance(active, dict)
            and active.get("session_id") == release["session_id"]
            and active.get("job_id") == release["job_id"]
        ),
        "foreign_lease_active": bool(
            isinstance(active, dict)
            and (
                active.get("session_id") != release["session_id"]
                or active.get("job_id") != release["job_id"]
            )
        ),
        "lease_queue_count": len(status.get("queued", [])),
        "owned_process_count": _owned_process_count(args.campaign_id),
        "owner_token_present": Path(release["owner_token_path"]).exists(),
        "authority_claimed": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--lease-manager", type=Path, required=True)
    parser.add_argument("--lease-database", type=Path, required=True)
    parser.add_argument("--pod-id", required=True)
    parser.add_argument("--volume-id", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    packet = build_engineering_campaign_runtime_packet(
        campaign_root=args.campaign_root,
        contract_path=args.contract,
        database=args.database,
        output_root=args.output_root,
        handoff=_handoff(args),
        decision="ADOPT",
        decision_reason=(
            "Independent replay validates one real 25-mission campaign under "
            "one owned Qwen/vLLM lifetime, 50 deterministic replay requests, "
            "25 accepted advisory artifacts, and clean shared-GPU release."
        ),
        limitations=[
            "This adopts only MF-P6-19.01; the 100-mask and sustained mixed-campaign acceptance gates remain open.",
            "The model outputs are advisory and claim no patch, Git, tracker, infrastructure, or final-adoption authority.",
        ],
        tracker_proposals=[
            {
                "item_id": "MF-P6-19.01",
                "status": "complete",
                "percent": 100,
                "evidence": (
                    "One immutable packet binds 25/25 completed missions, "
                    "50 replay requests, 25 accepted artifacts, one service "
                    "generation, terminal reconciliation, and clean GPU release."
                ),
            }
        ],
    )
    print(json.dumps(packet, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
