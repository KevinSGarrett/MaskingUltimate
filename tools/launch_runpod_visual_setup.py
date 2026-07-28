"""Launch the bounded persistent RunPod visual-model setup as an owned job."""

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

REMOTE_LAUNCH = r"""
set -euo pipefail
base=/workspace/maskfactory/runtime_artifacts/visual_critic_setup
mkdir -p "$base" /workspace/models/visual_critics /workspace/.cache/pip /workspace/.cache/huggingface /workspace/tmp
if [ -s "$base/setup.pid" ]; then
  old_pid=$(cat "$base/setup.pid")
  if kill -0 "$old_pid" 2>/dev/null; then
    python3 - "$old_pid" "$base" <<'PY'
import hashlib, json, pathlib, sys
pid = int(sys.argv[1]); base = pathlib.Path(sys.argv[2])
print(json.dumps({'status':'ALREADY_RUNNING','pid':pid,'job_dir':str(base),'script_sha256':hashlib.sha256((base/'setup.sh').read_bytes()).hexdigest()}))
PY
    exit 0
  fi
fi
cat > "$base/setup.sh" <<'SETUP'
#!/usr/bin/env bash
set -euo pipefail
base=/workspace/maskfactory/runtime_artifacts/visual_critic_setup
exec 9>"$base/setup.lock"
flock -n 9 || exit 73
export HF_HOME=/workspace/.cache/huggingface
export HUGGINGFACE_HUB_CACHE=/workspace/.cache/huggingface/hub
export PIP_CACHE_DIR=/workspace/.cache/pip
export TMPDIR=/workspace/tmp
export PYTHONUNBUFFERED=1
state() {
  python3 - "$1" "$2" <<'PY'
import json, pathlib, sys
path = pathlib.Path('/workspace/maskfactory/runtime_artifacts/visual_critic_setup/state.json')
path.write_text(json.dumps({'stage':sys.argv[1],'status':sys.argv[2]},sort_keys=True)+'\n',encoding='utf-8')
PY
}
state bootstrap running
python3 -m venv "$base/download_env"
"$base/download_env/bin/python" -m pip install --upgrade pip 'huggingface-hub>=0.36,<1.0'
state qwen_download running
"$base/download_env/bin/hf" download Qwen/Qwen3.6-35B-A3B-FP8 \
  --revision 95a723d08a9490559dae23d0cff1d9466213d989 \
  --local-dir /workspace/models/visual_critics/qwen3_6_35b_a3b_fp8
state internvl_download running
"$base/download_env/bin/hf" download OpenGVLab/InternVL3_5-8B \
  --revision 9bb6a56ad9cc69db95e2d4eeb15a52bbcac4ef79 \
  --local-dir /workspace/models/visual_critics/internvl3_5_8b_bf16
state internvl_runtime running
python3 -m venv --system-site-packages "$base/internvl_env"
"$base/internvl_env/bin/python" -m pip install --upgrade pip 'transformers>=4.52.1,<5' 'accelerate>=1,<2'
state qwen_runtime running
python3 -m venv "$base/qwen36_env"
"$base/qwen36_env/bin/python" -m pip install --upgrade pip
if "$base/qwen36_env/bin/python" -m pip install 'vllm>=0.19.0,<0.20'; then
  printf 'pass\n' > "$base/vllm_install.status"
else
  printf 'failed\n' > "$base/vllm_install.status"
fi
state inventory running
python3 - <<'PY'
import hashlib, json, pathlib
base = pathlib.Path('/workspace/maskfactory/runtime_artifacts/visual_critic_setup')
models = pathlib.Path('/workspace/models/visual_critics')
rows = []
for model in sorted(path for path in models.iterdir() if path.is_dir()):
    files = [path for path in model.rglob('*') if path.is_file() and '.cache' not in path.parts]
    rows.append({'model_id':model.name,'file_count':len(files),'total_bytes':sum(path.stat().st_size for path in files)})
payload = {
    'models': rows,
    'vllm_install_status': (base/'vllm_install.status').read_text(encoding='utf-8').strip(),
}
payload['sha256'] = hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
(base/'inventory.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8')
PY
state complete pass
SETUP
chmod 700 "$base/setup.sh"
nohup bash "$base/setup.sh" >"$base/stdout.log" 2>"$base/stderr.log" </dev/null &
pid=$!
printf '%s\n' "$pid" > "$base/setup.pid"
python3 - "$pid" "$base" <<'PY'
import hashlib, json, pathlib, sys
pid = int(sys.argv[1]); base = pathlib.Path(sys.argv[2])
print(json.dumps({'status':'STARTED','pid':pid,'job_dir':str(base),'script_sha256':hashlib.sha256((base/'setup.sh').read_bytes()).hexdigest()}))
PY
"""


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
        input=REMOTE_LAUNCH.replace("\r\n", "\n").encode("utf-8"),
        capture_output=True,
        check=False,
        timeout=45,
    )
    stderr = completed.stderr.decode("utf-8", errors="replace")
    if completed.returncode != 0:
        raise RunPodVisualAuditError(
            f"RunPod setup launch failed with exit {completed.returncode}: {stderr.strip()[:300]}"
        )
    lines = [
        line for line in completed.stdout.decode("utf-8", errors="replace").splitlines() if line
    ]
    if not lines:
        raise RunPodVisualAuditError("RunPod setup launch returned no JSON")
    result = json.loads(lines[-1])
    if result.get("status") not in {"STARTED", "ALREADY_RUNNING"}:
        raise RunPodVisualAuditError("RunPod setup launch returned an invalid status")
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
    print(json.dumps(run_remote_launch(host=host, port=port), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
