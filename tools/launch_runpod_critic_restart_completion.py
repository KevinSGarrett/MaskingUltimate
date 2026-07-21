"""Complete Qwen restart evidence after enforcing an observed GPU-release barrier."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

if __package__:
    from .audit_runpod_visual_runtime import RunPodVisualAuditError, load_env_value, runpod_get
    from .launch_runpod_critic_deterministic_retry import REMOTE_LAUNCH as DETERMINISTIC_REMOTE
else:
    from audit_runpod_visual_runtime import RunPodVisualAuditError, load_env_value, runpod_get
    from launch_runpod_critic_deterministic_retry import REMOTE_LAUNCH as DETERMINISTIC_REMOTE

RELEASE_BARRIER = r"""state release_barrier running
released=0
for _ in $(seq 1 180); do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -n1 | tr -d ' ')
  if [ "$used" -le 2048 ]; then released=1; break; fi
  sleep 1
done
[ "$released" = 1 ] || exit 76
state qualification running
for run in 2; do"""

REMOTE_LAUNCH = (
    DETERMINISTIC_REMOTE.replace(
        "visual_critic_qwen27_deterministic_retry", "visual_critic_qwen27_restart_completion"
    )
    .replace("state qualification running\nfor run in 1 2; do", RELEASE_BARRIER)
    .replace(
        "'run_paths':[base/'run1.json',base/'run2.json']",
        "'run_paths':[pathlib.Path('/workspace/maskfactory/runtime_artifacts/visual_critic_qwen27_deterministic_retry/run1.json'),base/'run2.json']",
    )
)


def run_remote_launch(*, host: str, port: int) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ConnectTimeout=15",
            "-p",
            str(port),
            f"root@{host}",
            "bash",
            "-s",
        ],
        input=REMOTE_LAUNCH.replace("\r\n", "\n").encode(),
        capture_output=True,
        check=False,
        timeout=45,
    )
    if completed.returncode != 0:
        error = completed.stderr.decode(errors="replace")
        raise RunPodVisualAuditError(f"RunPod restart completion failed: {error[:300]}")
    lines = [line for line in completed.stdout.decode(errors="replace").splitlines() if line]
    if not lines:
        raise RunPodVisualAuditError("RunPod restart completion returned no JSON")
    result = json.loads(lines[-1])
    if result.get("status") not in {"STARTED", "ALREADY_RUNNING", "MODEL_NOT_READY"}:
        raise RunPodVisualAuditError("RunPod restart completion returned an invalid status")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--pod-id", required=True)
    args = parser.parse_args()
    key = load_env_value(args.env_file, "RUNPOD_API_KEY")
    pod = runpod_get(f"pods/{args.pod_id}", key)
    host = str(pod.get("publicIp") or "")
    port = int((pod.get("portMappings") or {}).get("22") or 0)
    if pod.get("desiredStatus") != "RUNNING" or not host or not port:
        raise RunPodVisualAuditError("RunPod SSH endpoint is unavailable")
    print(json.dumps(run_remote_launch(host=host, port=port), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
