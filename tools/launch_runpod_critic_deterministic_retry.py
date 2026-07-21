"""Launch the final constant-schema Qwen 27B determinism qualification."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

if __package__:
    from .audit_runpod_visual_runtime import RunPodVisualAuditError, load_env_value, runpod_get
    from .launch_runpod_critic_protocol_retry import REMOTE_LAUNCH as PROTOCOL_REMOTE_LAUNCH
else:
    from audit_runpod_visual_runtime import RunPodVisualAuditError, load_env_value, runpod_get
    from launch_runpod_critic_protocol_retry import REMOTE_LAUNCH as PROTOCOL_REMOTE_LAUNCH

REMOTE_LAUNCH = (
    PROTOCOL_REMOTE_LAUNCH.replace(
        "visual_critic_qwen27_protocol_retry", "visual_critic_qwen27_deterministic_retry"
    )
    .replace(
        "'summary':{'type':'string','minLength':1}",
        "'summary':{'type':'string','const':'synthetic diagnostic panels'}",
    )
    .replace(
        "provide a short summary for these synthetic diagnostic panels.",
        "set summary exactly to synthetic diagnostic panels.",
    )
    .replace(
        "prompt='Return only JSON with keys verdict and summary. Use verdict uncertain for these synthetic diagnostic panels.'",
        "prompt='/no_think\\nReturn a JSON object. Set verdict to uncertain and set summary exactly to synthetic diagnostic panels.'",
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
        raise RunPodVisualAuditError(f"RunPod deterministic retry failed: {error[:300]}")
    lines = [line for line in completed.stdout.decode(errors="replace").splitlines() if line]
    if not lines:
        raise RunPodVisualAuditError("RunPod deterministic retry returned no JSON")
    result = json.loads(lines[-1])
    if result.get("status") not in {"STARTED", "ALREADY_RUNNING", "MODEL_NOT_READY"}:
        raise RunPodVisualAuditError("RunPod deterministic retry returned an invalid status")
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
