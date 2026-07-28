"""Append-only OPS_LOG entry for serve:cu128 daemon-abort seal."""

ENTRY = """
## 2026-07-20 15:10 UTC - serve:cu128 build ABORTED (Docker daemon death; protect engine)
**Item:** maskfactory/serve:cu128 build + tools/smoke_docker_gpu_serve.py (FULL AUTONOMY; abort-if-daemon-dies mandate)
**Command:** live docker/CVAT/Ollama/disk probe; Docker Desktop wake; observed short engine-up window with cvat v2.24 containers; bootstrap_cvat.py (failed on dead pipe); careful wsl --shutdown + Desktop relaunch x2 (no prune/wipe); abort further thrash; seal RUNTIME_BLOCKED.
**Result:** ABORTED / RUNTIME_BLOCKED (honest). `maskfactory/serve:cu128` **NOT built**; smoke **NOT run**. Docker named pipe `dockerDesktopLinuxEngine` absent at abort. Prior sibling build log (`runtime_artifacts/_serve_cu128_build_20260720.log`) reached torch cu128 `nvidia-cudnn-cu12` (~657.9 MB) then `rpc error: Unavailable ... EOF` (daemon died mid-layer). Brief engine-up window showed production `cvat/server:v2.24.0` containers recovering, then daemon died again before `/api/server/about` could be restored. CVAT restore incomplete (bootstrap failed; about timeout at abort). Ollama host remained UP at 0.32.1. C: free collapsed ~75.21 -> ~30.76 GiB during failed wake cycles (`docker_data.vhdx` still 68.11 GiB on C:); further restarts/builds aborted to protect the engine and disk. No `docker system prune`, no volume wipe, no factory reset.

Evidence: qa/live_verification/serve_cu128_daemon_abort_20260720T1510.json; script runtime_artifacts/_seal_serve_cu128_daemon_abort_20260720T1510.py.
"""

with open("Plan/OPS_LOG.md", "a", encoding="utf-8", newline="\n") as f:
    f.write(ENTRY)
print("APPENDED", len(ENTRY), "chars")
