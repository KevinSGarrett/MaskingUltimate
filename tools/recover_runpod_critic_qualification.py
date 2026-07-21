"""Contain only the owned Qwen qualification processes after a failed run."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

if __package__:
    from .audit_runpod_visual_runtime import (
        RunPodVisualAuditError,
        load_env_value,
        runpod_get,
    )
else:
    from audit_runpod_visual_runtime import (
        RunPodVisualAuditError,
        load_env_value,
        runpod_get,
    )

REMOTE_RECOVERY = r"""
set -euo pipefail
needle='/workspace/models/visual_critics/qwen3_6_35b_a3b_fp8'
base=/workspace/maskfactory/runtime_artifacts/visual_critic_qualification
before=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -n1 | tr -d ' ')
mapfile -t roots < <(pgrep -f -- "$needle" || true)
all=()
if [ "${#roots[@]}" -gt 0 ]; then
  mapfile -t rows < <(ps -eo pid=,ppid=)
  all=("${roots[@]}")
  changed=1
  while [ "$changed" -eq 1 ]; do
    changed=0
    for row in "${rows[@]}"; do
      read -r pid ppid <<<"$row"
      for parent in "${all[@]}"; do
        if [ "$ppid" = "$parent" ]; then
          present=0
          for known in "${all[@]}"; do [ "$pid" = "$known" ] && present=1; done
          if [ "$present" -eq 0 ]; then all+=("$pid"); changed=1; fi
        fi
      done
    done
  done
  for pid in "${all[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
  for _ in $(seq 1 30); do
    alive=0
    for pid in "${all[@]}"; do kill -0 "$pid" 2>/dev/null && alive=1; done
    [ "$alive" -eq 0 ] && break
    sleep 1
  done
  for pid in "${all[@]}"; do kill -KILL "$pid" 2>/dev/null || true; done
fi
sleep 3
remaining=$(pgrep -f -- "$needle" | wc -l || true)
port_busy=$(python3 - <<'PY'
import socket
s=socket.socket(); print(int(s.connect_ex(('127.0.0.1',18001))==0)); s.close()
PY
)
after=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -n1 | tr -d ' ')
python3 - "$base" "$before" "$after" "${#all[@]}" "$remaining" "$port_busy" <<'PY'
import json,pathlib,sys
base=pathlib.Path(sys.argv[1])
state={'stage':'qwen','status':'failed','reason':'vllm_weight_load_out_of_memory'}
(base/'state.json').write_text(json.dumps(state,sort_keys=True)+'\n',encoding='utf-8')
print(json.dumps({
 'status':'CONTAINED' if int(sys.argv[5])==0 and int(sys.argv[6])==0 else 'CONTAINMENT_INCOMPLETE',
 'gpu_memory_used_before_mib':int(sys.argv[2]),
 'gpu_memory_used_after_mib':int(sys.argv[3]),
 'owned_process_count_signaled':int(sys.argv[4]),
 'remaining_exact_scope_processes':int(sys.argv[5]),
 'loopback_port_still_bound':bool(int(sys.argv[6])),
 'reason':'vllm_weight_load_out_of_memory',
}))
PY
"""


def run_remote_recovery(*, host: str, port: int) -> dict[str, Any]:
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
        input=REMOTE_RECOVERY.replace("\r\n", "\n").encode("utf-8"),
        capture_output=True,
        check=False,
        timeout=60,
    )
    stderr = completed.stderr.decode("utf-8", errors="replace")
    if completed.returncode != 0:
        raise RunPodVisualAuditError(
            f"RunPod qualification recovery failed with exit {completed.returncode}: {stderr[:300]}"
        )
    lines = [
        line for line in completed.stdout.decode("utf-8", errors="replace").splitlines() if line
    ]
    if not lines:
        raise RunPodVisualAuditError("RunPod qualification recovery returned no JSON")
    result = json.loads(lines[-1])
    if result.get("status") not in {"CONTAINED", "CONTAINMENT_INCOMPLETE"}:
        raise RunPodVisualAuditError("RunPod qualification recovery returned an invalid status")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--pod-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = load_env_value(args.env_file, "RUNPOD_API_KEY")
    pod = runpod_get(f"pods/{args.pod_id}", api_key)
    if pod.get("desiredStatus") != "RUNNING":
        raise RunPodVisualAuditError(f"RunPod pod is not running: {pod.get('desiredStatus')}")
    host = str(pod.get("publicIp") or "")
    mappings = pod.get("portMappings") or {}
    port = int(mappings.get("22") or 0)
    if not host or not port:
        raise RunPodVisualAuditError("RunPod SSH endpoint is unavailable")
    print(json.dumps(run_remote_recovery(host=host, port=port), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
