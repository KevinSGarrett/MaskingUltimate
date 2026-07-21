"""Launch the bounded Qwen 27B fallback qualification on the governed RunPod."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

if __package__:
    from .audit_runpod_visual_runtime import RunPodVisualAuditError, load_env_value, runpod_get
else:
    from audit_runpod_visual_runtime import RunPodVisualAuditError, load_env_value, runpod_get


REMOTE_LAUNCH = r"""
set -euo pipefail
setup=/workspace/maskfactory/runtime_artifacts/visual_critic_setup
previous=/workspace/maskfactory/runtime_artifacts/visual_critic_qualification
base=/workspace/maskfactory/runtime_artifacts/visual_critic_qwen27_fallback
model=/workspace/models/visual_critics/qwen3_6_27b_fp8
mkdir -p "$base" "$model"
if pgrep -f -- '/workspace/models/visual_critics/qwen3_6_35b_a3b_fp8' >/dev/null; then
  echo '{"status":"PREVIOUS_SCOPE_STILL_RUNNING"}'
  exit 0
fi
if [ -s "$base/fallback.pid" ]; then
  old_pid=$(cat "$base/fallback.pid")
  if kill -0 "$old_pid" 2>/dev/null; then
    python3 - "$old_pid" "$base" <<'PY'
import hashlib,json,pathlib,sys
pid=int(sys.argv[1]);base=pathlib.Path(sys.argv[2])
print(json.dumps({'status':'ALREADY_RUNNING','pid':pid,'job_dir':str(base),'script_sha256':hashlib.sha256((base/'fallback.sh').read_bytes()).hexdigest()}))
PY
    exit 0
  fi
fi
cat > "$base/client.py" <<'PY'
import base64,hashlib,io,json,os,pathlib,subprocess,time,urllib.request
from PIL import Image

output=pathlib.Path(os.environ['RUN_OUTPUT'])
images=[]
for color in ((32,64,96),(255,255,255),(128,96,64)):
    buffer=io.BytesIO(); Image.new('RGB',(64,64),color).save(buffer,format='PNG')
    images.append('data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode())
content=[{'type':'image_url','image_url':{'url':url}} for url in images]
content.append({'type':'text','text':'Return only JSON with keys verdict and summary. Use verdict uncertain for these synthetic diagnostic panels.'})
payload={'model':'qwen3_6_27b_fp8','messages':[{'role':'user','content':content}],'temperature':0,'seed':1337,'max_tokens':96}
responses=[];latencies=[]
for _ in range(2):
    request=urllib.request.Request('http://127.0.0.1:18001/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
    started=time.perf_counter()
    with urllib.request.urlopen(request,timeout=300) as response: body=json.load(response)
    latencies.append((time.perf_counter()-started)*1000)
    text=str(body['choices'][0]['message']['content']).strip().removeprefix('```json').removesuffix('```').strip()
    parsed=json.loads(text)
    if set(parsed) != {'verdict','summary'}: raise RuntimeError('Qwen response contract mismatch')
    responses.append(json.dumps(parsed,sort_keys=True,separators=(',',':')))
if len(set(responses)) != 1: raise RuntimeError('Qwen warm replay changed')
rows=subprocess.check_output(['nvidia-smi','--query-compute-apps=used_memory','--format=csv,noheader,nounits'],text=True)
memory=sum(int(row.strip()) for row in rows.splitlines() if row.strip())*1024*1024
output.write_text(json.dumps({'status':'pass','pid':int(os.environ['SERVER_PID']),'cold_latency_ms':latencies[0],'warm_latency_ms':latencies[1],'peak_vram_bytes':memory,'response_sha256':hashlib.sha256(responses[-1].encode()).hexdigest()},sort_keys=True)+'\n',encoding='utf-8')
PY
cat > "$base/fallback.sh" <<'FALLBACK'
#!/usr/bin/env bash
set -euo pipefail
setup=/workspace/maskfactory/runtime_artifacts/visual_critic_setup
previous=/workspace/maskfactory/runtime_artifacts/visual_critic_qualification
base=/workspace/maskfactory/runtime_artifacts/visual_critic_qwen27_fallback
model=/workspace/models/visual_critics/qwen3_6_27b_fp8
exec 9>"$base/fallback.lock"
flock -n 9 || exit 73
state() { python3 - "$1" "$2" <<'PY'
import json,pathlib,sys
path=pathlib.Path('/workspace/maskfactory/runtime_artifacts/visual_critic_qwen27_fallback/state.json')
path.write_text(json.dumps({'stage':sys.argv[1],'status':sys.argv[2]},sort_keys=True)+'\n',encoding='utf-8')
PY
}
server_pid=
cleanup_server() {
  if [ -n "${server_pid:-}" ] && kill -0 "$server_pid" 2>/dev/null; then
    kill -- -"$server_pid" 2>/dev/null || true
    for _ in $(seq 1 60); do kill -0 "$server_pid" 2>/dev/null || break; sleep 1; done
    kill -9 -- -"$server_pid" 2>/dev/null || true
  fi
}
finish() {
  code=$?
  cleanup_server
  if [ "$code" -ne 0 ]; then state failed "exit_$code"; fi
  exit "$code"
}
trap finish EXIT
export HF_HOME=/workspace/.cache/huggingface
export HUGGINGFACE_HUB_CACHE=/workspace/.cache/huggingface/hub
export HF_HUB_OFFLINE=0
export TOKENIZERS_PARALLELISM=false
state download running
"$setup/download_env/bin/hf" download Qwen/Qwen3.6-27B-FP8 \
  --revision e89b16ebf1988b3d6befa7de50abc2d76f26eb09 --local-dir "$model"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1
state qualification running
for run in 1 2; do
  python3 - <<'PY'
import socket
s=socket.socket(); busy=s.connect_ex(('127.0.0.1',18001)) == 0; s.close()
raise SystemExit(74 if busy else 0)
PY
  setsid "$setup/qwen36_env/bin/vllm" serve "$model" \
    --host 127.0.0.1 --port 18001 --served-model-name qwen3_6_27b_fp8 \
    --max-model-len 8192 --max-num-seqs 1 --gpu-memory-utilization 0.90 \
    --limit-mm-per-prompt '{"image":3}' --trust-remote-code --seed 1337 \
    >"$base/server${run}.log" 2>&1 &
  server_pid=$!
  ready=0
  for _ in $(seq 1 900); do
    if python3 - <<'PY' >/dev/null 2>&1
import urllib.request
urllib.request.urlopen('http://127.0.0.1:18001/v1/models',timeout=2).read()
PY
    then ready=1; break; fi
    kill -0 "$server_pid" 2>/dev/null || break
    sleep 1
  done
  [ "$ready" = 1 ] || exit 75
  RUN_OUTPUT="$base/run${run}.json" SERVER_PID="$server_pid" "$setup/qwen36_env/bin/python" "$base/client.py"
  cleanup_server; server_pid=
done
state hashing running
python3 - <<'PY'
import hashlib,json,pathlib
base=pathlib.Path('/workspace/maskfactory/runtime_artifacts/visual_critic_qwen27_fallback')
previous=pathlib.Path('/workspace/maskfactory/runtime_artifacts/visual_critic_qualification')
specs={
 'qwen3_6_27b_fp8':{'family_id':'qwen','repository':'Qwen/Qwen3.6-27B-FP8','revision':'e89b16ebf1988b3d6befa7de50abc2d76f26eb09','quantization':'fp8','endpoint':'http://127.0.0.1:18001','root':pathlib.Path('/workspace/models/visual_critics/qwen3_6_27b_fp8'),'runs':[base/'run1.json',base/'run2.json']},
 'internvl3_5_8b_bf16':{'family_id':'internvl','repository':'OpenGVLab/InternVL3_5-8B','revision':'9bb6a56ad9cc69db95e2d4eeb15a52bbcac4ef79','quantization':'bf16','endpoint':'local-process://isolated','root':pathlib.Path('/workspace/models/visual_critics/internvl3_5_8b_bf16'),'runs':[previous/'internvl_run1.json',previous/'internvl_run2.json']},
}
prompt='Return only JSON with keys verdict and summary. Use verdict uncertain for these synthetic diagnostic panels.'
models=[]
for model_id,spec in specs.items():
 rows=[]
 for path in sorted(p for p in spec['root'].rglob('*') if p.is_file() and '.cache' not in p.parts):
  digest=hashlib.sha256()
  with path.open('rb') as stream:
   for chunk in iter(lambda:stream.read(8*1024*1024),b''): digest.update(chunk)
  rows.append({'path':path.relative_to(spec['root']).as_posix(),'bytes':path.stat().st_size,'sha256':digest.hexdigest()})
 runs=[json.loads(path.read_text()) for path in spec.pop('runs')]
 root=spec.pop('root')
 if len({run['response_sha256'] for run in runs}) != 1: raise RuntimeError(f'{model_id} restart response drift')
 models.append({'model_id':model_id,**spec,'artifact_tree_sha256':hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'downloaded_bytes':sum(row['bytes'] for row in rows),'file_count':len(rows),'image_budget':3,'context_token_budget':8192,'process_runs':runs})
evidence={'schema_version':'1.0.0','status':'RUNTIME_PASS_BOUNDED','hardware':{'tier_id':'runpod_single_gpu_48gb','gpu_name':'NVIDIA RTX 6000 Ada Generation','gpu_count':1,'vram_bytes':51527024640},'models':models,'authority_claimed':False}
(base/'result.json').write_text(json.dumps(evidence,indent=2,sort_keys=True)+'\n',encoding='utf-8')
PY
state complete pass
trap - EXIT
FALLBACK
chmod 700 "$base/fallback.sh"
nohup bash "$base/fallback.sh" >"$base/stdout.log" 2>"$base/stderr.log" </dev/null &
pid=$!
printf '%s\n' "$pid" > "$base/fallback.pid"
python3 - "$pid" "$base" <<'PY'
import hashlib,json,pathlib,sys
pid=int(sys.argv[1]);base=pathlib.Path(sys.argv[2])
print(json.dumps({'status':'STARTED','pid':pid,'job_dir':str(base),'script_sha256':hashlib.sha256((base/'fallback.sh').read_bytes()).hexdigest()}))
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
        input=REMOTE_LAUNCH.replace("\r\n", "\n").encode(),
        capture_output=True,
        check=False,
        timeout=45,
    )
    stderr = completed.stderr.decode(errors="replace")
    if completed.returncode != 0:
        raise RunPodVisualAuditError(
            f"RunPod fallback launch failed with exit {completed.returncode}: {stderr[:300]}"
        )
    lines = [line for line in completed.stdout.decode(errors="replace").splitlines() if line]
    if not lines:
        raise RunPodVisualAuditError("RunPod fallback launch returned no JSON")
    result = json.loads(lines[-1])
    allowed = {"STARTED", "ALREADY_RUNNING", "PREVIOUS_SCOPE_STILL_RUNNING"}
    if result.get("status") not in allowed:
        raise RunPodVisualAuditError("RunPod fallback launch returned an invalid status")
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
    port = int((pod.get("portMappings") or {}).get("22") or 0)
    if not host or not port:
        raise RunPodVisualAuditError("RunPod SSH endpoint is unavailable")
    print(json.dumps(run_remote_launch(host=host, port=port), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
