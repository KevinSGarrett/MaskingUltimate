"""Patch needs_agent_actions train item with train:cu128 blocked seal pointer."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PATH = REPO / "qa" / "live_verification" / "needs_agent_actions_20260720.json"
SEAL = REPO / "qa" / "live_verification" / "train_cu128_blocked_20260720T1526.json"


def main() -> None:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    seal = json.loads(SEAL.read_text(encoding="utf-8")) if SEAL.exists() else {}
    note = {
        "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "evidence": str(SEAL.relative_to(REPO)).replace("\\", "/"),
        "verdict": seal.get("verdict", "RUNTIME_BLOCKED"),
        "self_sha256": seal.get("self_sha256"),
        "c_free_gib": (seal.get("live_probe") or {}).get("c_free_gib"),
        "pipe": (seal.get("live_probe") or {}).get("named_pipe_dockerDesktopLinuxEngine"),
        "serve_present": (seal.get("live_probe") or {}).get("serve_cu128_present"),
        "build_attempted": False,
        "training_doctor_smoke_attempted": False,
        "note": (
            "FULL AUTONOMY train:cu128 wave aborted pre-build: serve absent, "
            "BuildKit unavailable (daemon DOWN), C: critical. No thrash."
        ),
    }
    data["train_cu128_blocked_20260720T1526"] = note
    for action in data.get("actions") or []:
        if action.get("action_id") == "docker_gpu_train_build_and_training_doctor":
            action["status"] = "BLOCKED_DOCKER_AND_DISK"
            action["train_blocked_evidence"] = note["evidence"]
            action["train_blocked_self_sha256"] = note["self_sha256"]
            action["why_now"] = (
                "Train image build heavy; blocked until C: >= 75 GiB AND durable "
                "Docker engine (named pipe + docker ps). serve:cu128 still absent; "
                "BuildKit not free while daemon DOWN."
            )
            break
    for p in data.get("live_priorities") or []:
        if p.get("action_id") == "docker_gpu_train_build_and_training_doctor":
            p["status"] = "BLOCKED_DOCKER_AND_DISK"
            p["why_now"] = (
                "Blocked: C: critical + Docker DOWN; seal "
                "train_cu128_blocked_20260720T1526.json"
            )
            break
    data["recorded_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    data.pop("self_sha256", None)
    payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    data["self_sha256"] = hashlib.sha256(payload).hexdigest()
    PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("UPDATED", PATH.name, data["self_sha256"][:16])


if __name__ == "__main__":
    main()
