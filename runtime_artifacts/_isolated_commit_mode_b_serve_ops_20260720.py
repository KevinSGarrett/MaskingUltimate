"""Land OPS_LOG + needs_agent Mode-B serve readiness updates via private index CAS."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/maskfactory-runtime-implementation"
MSG = ROOT / "runtime_artifacts" / "_commit_msg_mode_b_serve_ops.txt"
TMP_INDEX = ROOT / ".git" / "mf_mode_b_serve_ops_tmp_index"
MARKER = "mode_b_serve_ready_20260720T1545"
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
PATHS = [
    "Plan/OPS_LOG.md",
    "qa/live_verification/needs_agent_actions_20260720.json",
    "runtime_artifacts/_isolated_commit_mode_b_serve_ready_20260720.py",
    "runtime_artifacts/_isolated_commit_mode_b_serve_ops_20260720.py",
    "runtime_artifacts/_commit_msg_mode_b_serve_ops.txt",
]

ENTRY = """
## 2026-07-20 15:45 UTC - Mode B serve ready on host FastAPI path (predict auto-wires when champions>0)
**Item:** Mode B serve start readiness (host FastAPI deps OR serve:cu128)
**Command:** `.venv\\Scripts\\maskfactory.exe serve --port 8765`; curl /health /models /predict; create_production_runtime probe; docker compose build maskfactory-serve (aborted - engine flap)
**Result:** HOST_SERVE_READY_PREDICT_AWAITING_CHAMPIONS. serve:cu128 NOT built (Docker engine flapping).

Host .venv serve deps present and live-proven:
- python 3.13.11, fastapi 0.139.0, uvicorn 0.51.0, python-multipart 0.0.32
- GET /health -> 200 ok (pipeline 0.0.1, mode_b_api 1.0.0, ontology body_parts_v1, RTX 5060 8151 MiB)
- GET /models -> 200, 17 verified foundation models, 0 champion keys
- POST /predict -> 503 "champion prediction provider is not configured" = honest AWAITING_RUNTIME
- create_production_runtime: predictor=None (champions=0), refiner configured; sequential champion
  predictor auto-wires when champion_bodypart+hand+clothing all present (no code change needed)

serve:cu128 deferred honestly: Docker Desktop briefly answered Server 29.6.1 and enumerated CVAT/nuclio,
then the npipe vanished mid-build attempt. Cleared orphan docker.exe CLI processes; pipe stayed absent
through a 3-minute wait. No prune, no volume wipe, no factory reset. Container smoke remains next
when the engine is stable.

Champions=0; Mode B /predict usable only after promoted champion roles exist. Evidence:
qa/live_verification/mode_b_serve_ready_20260720T1545.json
(self_sha256 28da5c472f6110ba4a781526053f7d85fec7e1eefd378cca27e3d2b0fbdf893f).
"""

MSG.write_text(
    "docs(ops): seal Mode B host serve readiness in OPS_LOG + needs_agent\n",
    encoding="utf-8",
)


def run(args, env=None, check=True):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=check, env=env)


def ensure() -> None:
    ops = ROOT / "Plan" / "OPS_LOG.md"
    text = ops.read_text(encoding="utf-8")
    if MARKER not in text:
        with ops.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(ENTRY)

    needs_path = ROOT / "qa" / "live_verification" / "needs_agent_actions_20260720.json"
    data = json.loads(needs_path.read_text(encoding="utf-8"))
    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
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
    data[MARKER] = note
    data["recorded_at"] = note["at"]
    data["project_head_at_authoring"] = head[:8]
    for item in data.get("live_priorities_this_wave") or []:
        if item.get("action_id") == "docker_gpu_serve_build_and_containerized_smoke":
            item["status"] = "BLOCKED_DOCKER_ENGINE_FLAP"
            item["host_path_satisfied"] = True
            item["host_evidence"] = note["evidence"]
            item["why_now"] = (
                "Host FastAPI Mode-B serve is READY (OR gate satisfied). "
                "Container path still desired when docker npipe is stable."
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
    needs_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Hard verify before staging.
    if MARKER not in ops.read_text(encoding="utf-8"):
        raise SystemExit("OPS_LOG missing marker after write")
    if MARKER not in json.loads(needs_path.read_text(encoding="utf-8")):
        raise SystemExit("needs_agent missing marker after write")


def main() -> None:
    for attempt in range(1, 15):
        ensure()
        head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(TMP_INDEX)
        if TMP_INDEX.exists():
            TMP_INDEX.unlink()
        run(["git", "read-tree", head], env=env)
        # Re-ensure immediately before add to beat sibling clobber.
        ensure()
        run(["git", "add", "--", *PATHS], env=env)
        # Verify staged blobs contain marker.
        ops_blob = run(["git", "show", ":Plan/OPS_LOG.md"], env=env).stdout
        needs_blob = run(
            ["git", "show", ":qa/live_verification/needs_agent_actions_20260720.json"],
            env=env,
        ).stdout
        if MARKER not in ops_blob or MARKER not in needs_blob:
            print(f"staged blobs missing marker (attempt {attempt}); retry")
            time.sleep(0.8)
            continue
        tree = run(["git", "write-tree"], env=env).stdout.strip()
        commit = run(["git", "commit-tree", tree, "-p", head, "-F", str(MSG)]).stdout.strip()
        cas = run(
            ["git", "update-ref", f"refs/heads/{BRANCH}", commit, head],
            check=False,
        )
        if cas.returncode == 0:
            print(f"committed {commit} parent {head} (attempt {attempt})")
            if TMP_INDEX.exists():
                TMP_INDEX.unlink()
            return
        print(f"CAS lost (attempt {attempt}); retrying")
        time.sleep(1.0)
    raise SystemExit("failed to land ops commit")


if __name__ == "__main__":
    main()
