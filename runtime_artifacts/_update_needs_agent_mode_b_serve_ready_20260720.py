"""Update needs_agent_actions with Mode-B host serve readiness (serve:cu128 still open)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PATH = REPO / "qa" / "live_verification" / "needs_agent_actions_20260720.json"
data = json.loads(PATH.read_text(encoding="utf-8"))
head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()

note = {
    "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "evidence": "qa/live_verification/mode_b_serve_ready_20260720T1545.json",
    "self_sha256": "28da5c472f6110ba4a781526053f7d85fec7e1eefd378cca27e3d2b0fbdf893f",
    "verdict": "HOST_SERVE_READY_PREDICT_AWAITING_CHAMPIONS",
    "host_serve": {
        "fastapi": "0.139.0",
        "uvicorn": "0.51.0",
        "python_multipart": "0.0.32",
        "health": 200,
        "models": 200,
        "predict": "503 AWAITING_RUNTIME (champions=0)",
        "auto_wire": "create_production_runtime configures sequential predictor when all three champion roles exist",
    },
    "serve_cu128": {
        "built": False,
        "reason": "Docker engine flapping (npipe absent after orphan-CLI clear); build deferred to protect engine",
    },
    "mode_b_predict": "AWAITING_RUNTIME until champions>0; host serve path ready now",
}

data["mode_b_serve_ready_20260720T1545"] = note
data["recorded_at"] = note["at"]
data["project_head_at_authoring"] = head[:8]

for item in data.get("live_priorities_this_wave") or []:
    if item.get("action_id") == "docker_gpu_serve_build_and_containerized_smoke":
        item["status"] = "BLOCKED_DOCKER_ENGINE_FLAP"
        item["host_path_satisfied"] = True
        item["host_evidence"] = note["evidence"]
        item["why_now"] = (
            "Host FastAPI Mode-B serve is READY (OR gate satisfied). "
            "Container path still desired: wait for stable docker npipe, then "
            "docker compose -f docker/compose.gpu.yml build maskfactory-serve && "
            "python tools/smoke_docker_gpu_serve.py --serve-image maskfactory/serve:cu128."
        )
        break

snap = data.setdefault("host_snapshot", {})
snap["mode_b_host_serve"] = "READY (/health+/models 200; /predict 503 champions=0)"
snap["serve_cu128_built"] = False
snap["champions"] = 0
snap["docker_engine"] = "FLAPPING_DOWN_at_mode_b_serve_seal (pipe absent)"

data.pop("self_sha256", None)
payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
data["self_sha256"] = hashlib.sha256(payload).hexdigest()
PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("UPDATED", PATH.name, data["self_sha256"])
