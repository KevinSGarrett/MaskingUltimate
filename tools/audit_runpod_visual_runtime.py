"""Read-only, sanitized preflight for the RunPod visual-model runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RUNPOD_REST = "https://rest.runpod.io/v1"
REMOTE_AUDIT = r"""
set -euo pipefail
python3 - <<'PY'
import importlib.metadata as metadata
import hashlib
import json
import os
import pathlib
import subprocess

def command(args):
    return subprocess.check_output(args, text=True).strip()

def package_version(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None

def directory_bytes(path):
    target = pathlib.Path(path)
    if not target.exists():
        return None
    value = command(['du', '-sB1', str(target)]).split()[0]
    return int(value)

def read_json(path):
    target = pathlib.Path(path)
    if not target.is_file():
        return None
    try:
        value = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None

def file_record(path):
    target = pathlib.Path(path)
    if not target.is_file():
        return {'exists': False, 'bytes': 0, 'sha256': None}
    data = target.read_bytes()
    return {'exists': True, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

gpu_fields = [part.strip() for part in command([
    'nvidia-smi',
    '--query-gpu=name,driver_version,memory.total,memory.used,memory.free,utilization.gpu',
    '--format=csv,noheader,nounits',
]).splitlines()[0].split(',')]

apps = []
try:
    rows = command([
        'nvidia-smi',
        '--query-compute-apps=pid,process_name,used_memory',
        '--format=csv,noheader,nounits',
    ])
except subprocess.CalledProcessError:
    rows = ''
for row in rows.splitlines():
    fields = [part.strip() for part in row.split(',', 2)]
    if len(fields) == 3:
        pid = int(fields[0])
        apps.append({
            'pid': pid,
            'process_name': fields[1],
            'used_memory_mib': int(fields[2]),
            'pid_alive': pathlib.Path(f'/proc/{pid}').exists(),
        })

stat = os.statvfs('/workspace')
cache_root = pathlib.Path('/workspace/.cache/huggingface/hub')
snapshots = []
if cache_root.is_dir():
    snapshots = sorted(path.name for path in cache_root.glob('models--*') if path.is_dir())

bound_names = []
paths_env = pathlib.Path('/workspace/paths.env')
if paths_env.is_file():
    for raw in paths_env.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name = line.split('=', 1)[0].removeprefix('export ').strip()
        if name.startswith(('HF_', 'HUGGINGFACE_', 'TRANSFORMERS_', 'MODEL', 'MASKFACTORY')):
            bound_names.append(name)

job_base = pathlib.Path('/workspace/maskfactory/runtime_artifacts/visual_critic_setup')
setup_pid = None
setup_pid_alive = False
try:
    setup_pid = int((job_base / 'setup.pid').read_text(encoding='utf-8').strip())
    setup_pid_alive = pathlib.Path(f'/proc/{setup_pid}').exists()
except (OSError, ValueError):
    pass
process_tree = []
if setup_pid_alive:
    try:
        rows = command(['ps', '-eo', 'pid=,ppid=,comm=,etime=,%cpu=,%mem=,stat=']).splitlines()
        parsed = []
        for row in rows:
            fields = row.split()
            if len(fields) == 7:
                parsed.append({
                    'pid':int(fields[0]), 'ppid':int(fields[1]), 'comm':fields[2],
                    'etime':fields[3], 'cpu_percent':float(fields[4]),
                    'memory_percent':float(fields[5]), 'state':fields[6],
                })
        descendants = {setup_pid}
        changed = True
        while changed:
            changed = False
            for row in parsed:
                if row['ppid'] in descendants and row['pid'] not in descendants:
                    descendants.add(row['pid'])
                    changed = True
        process_tree = [row for row in parsed if row['pid'] in descendants]
    except (OSError, subprocess.CalledProcessError, ValueError):
        process_tree = []

payload = {
    'gpu': {
        'name': gpu_fields[0],
        'driver_version': gpu_fields[1],
        'memory_total_mib': int(gpu_fields[2]),
        'memory_used_mib': int(gpu_fields[3]),
        'memory_free_mib': int(gpu_fields[4]),
        'utilization_percent': int(gpu_fields[5]),
        'compute_apps': apps,
    },
    'workspace': {
        'total_bytes': stat.f_frsize * stat.f_blocks,
        'free_bytes': stat.f_frsize * stat.f_bavail,
        'paths_env_exists': paths_env.is_file(),
        'bound_variable_names': sorted(set(bound_names)),
    },
    'persistent_directories': {
        'huggingface_cache_bytes': directory_bytes('/workspace/.cache/huggingface'),
        'models_bytes': directory_bytes('/workspace/models'),
        'maskfactory_models_bytes': directory_bytes('/workspace/maskfactory/models'),
    },
    'huggingface_model_cache_names': snapshots,
    'packages': {
        name: package_version(name)
        for name in (
            'accelerate',
            'bitsandbytes',
            'flash-attn',
            'huggingface-hub',
            'sglang',
            'torch',
            'transformers',
            'vllm',
        )
    },
    'visual_setup_job': {
        'exists': job_base.is_dir(),
        'pid': setup_pid,
        'pid_alive': setup_pid_alive,
        'process_tree': process_tree,
        'state': read_json(job_base / 'state.json'),
        'inventory': read_json(job_base / 'inventory.json'),
        'stdout': file_record(job_base / 'stdout.log'),
        'stderr': file_record(job_base / 'stderr.log'),
        'script': file_record(job_base / 'setup.sh'),
    },
}
print(json.dumps(payload, sort_keys=True))
PY
"""


class RunPodVisualAuditError(RuntimeError):
    """The read-only RunPod visual-runtime audit could not complete."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_env_value(path: Path, key: str) -> str:
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for delimiter in ("=", ":"):
            prefix = f"{key}{delimiter}"
            if line.startswith(prefix):
                value = line[len(prefix) :].strip().strip('"').strip("'")
                if value:
                    return value
    raise RunPodVisualAuditError(f"{key} not found in {path}")


def runpod_get(path: str, api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{RUNPOD_REST}/{path.lstrip('/')}",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RunPodVisualAuditError(f"RunPod GET failed with HTTP {exc.code}") from exc
    if not isinstance(payload, dict):
        raise RunPodVisualAuditError("RunPod GET returned a non-object payload")
    return payload


def run_remote_audit(*, host: str, port: int) -> dict[str, Any]:
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
        input=REMOTE_AUDIT.replace("\r\n", "\n").encode("utf-8"),
        capture_output=True,
        check=False,
        timeout=60,
    )
    stderr = completed.stderr.decode("utf-8", errors="replace")
    if completed.returncode != 0:
        raise RunPodVisualAuditError(
            f"RunPod SSH audit failed with exit {completed.returncode}: {stderr.strip()[:300]}"
        )
    lines = [
        line for line in completed.stdout.decode("utf-8", errors="replace").splitlines() if line
    ]
    if not lines:
        raise RunPodVisualAuditError("RunPod SSH audit returned no JSON")
    payload = json.loads(lines[-1])
    if not isinstance(payload, dict):
        raise RunPodVisualAuditError("RunPod SSH audit returned a non-object payload")
    return payload


def build_result(pod: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    pod_id = str(pod.get("id") or "")
    network_volume_id = str(pod.get("networkVolumeId") or "")
    return {
        "schema_version": "1.0.0",
        "recorded_at": _utc_now(),
        "operation": "read_only_visual_runtime_audit",
        "pod": {
            "id_sha256": _sha256_text(pod_id),
            "desired_status": pod.get("desiredStatus"),
            "network_volume_id_sha256": _sha256_text(network_volume_id),
            "network_volume_attached": bool(network_volume_id),
            "volume_mount_path": pod.get("volumeMountPath"),
        },
        "remote": remote,
        "checks": {
            "pod_running": pod.get("desiredStatus") == "RUNNING",
            "persistent_workspace_bound": bool(network_volume_id)
            and pod.get("volumeMountPath") == "/workspace",
            "paths_env_present": remote["workspace"]["paths_env_exists"],
            "gpu_is_current_tier": remote["gpu"]["name"] == "NVIDIA RTX 6000 Ada Generation"
            and int(remote["gpu"]["memory_total_mib"]) >= 48000,
            "workspace_has_model_capacity": int(remote["workspace"]["free_bytes"])
            >= 60_000_000_000,
            "no_active_gpu_compute_apps": not any(
                bool(app.get("pid_alive")) for app in remote["gpu"]["compute_apps"]
            ),
        },
        "secrets_or_endpoint_committed": False,
    }


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
    result = build_result(pod, run_remote_audit(host=host, port=port))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
