"""Verify that an active RunPod uses persistent storage for MaskFactory.

The API key is read from a local env file and is never printed or written to
evidence.  The live probe is bounded to RunPod REST GET calls and an SSH
filesystem sentinel under ``/workspace/maskfactory/runtime_artifacts``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"
RUNPOD_REST = "https://rest.runpod.io/v1"
REMOTE_PROBE = r"""
set -euo pipefail
python3 - "$1" <<'PY'
import hashlib
import json
import os
import pathlib
import subprocess
import sys

token = sys.argv[1]
workspace = pathlib.Path('/workspace')
artifact_dir = workspace / 'maskfactory' / 'runtime_artifacts'
artifact_dir.mkdir(parents=True, exist_ok=True)
sentinel = artifact_dir / '.maskfactory_persistence_probe'
sentinel.write_text(token + '\n', encoding='utf-8')
with sentinel.open('rb') as handle:
    os.fsync(handle.fileno())
os.sync()

child_code = (
    "import json,os,pathlib,sys; "
    "p=pathlib.Path(sys.argv[1]); "
    "print(json.dumps({'pid':os.getpid(),'value':p.read_text(encoding='utf-8').strip()}))"
)
child = json.loads(
    subprocess.check_output([sys.executable, '-c', child_code, str(sentinel)], text=True)
)

def fs(path):
    stat = os.statvfs(path)
    return {
        'total_bytes': stat.f_frsize * stat.f_blocks,
        'free_bytes': stat.f_frsize * stat.f_bavail,
        'device': os.stat(path).st_dev,
    }

findmnt = json.loads(
    subprocess.check_output(['findmnt', '-J', '-T', str(workspace)], text=True)
)
filesystem = findmnt['filesystems'][0]
source = str(filesystem.get('source') or '')
gpu_line = subprocess.check_output(
    [
        'nvidia-smi',
        '--query-gpu=name,driver_version,memory.total',
        '--format=csv,noheader,nounits',
    ],
    text=True,
).strip().splitlines()[0]
gpu_name, driver, memory_mib = [part.strip() for part in gpu_line.split(',', 2)]
paths_env = workspace / 'paths.env'
payload = {
    'workspace': fs(workspace),
    'container_root': fs('/'),
    'mount': {
        'target': filesystem.get('target'),
        'fstype': filesystem.get('fstype'),
        'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
        'source_present': bool(source),
    },
    'sentinel': {
        'path': str(sentinel),
        'sha256': hashlib.sha256(sentinel.read_bytes()).hexdigest(),
        'write_pid': os.getpid(),
        'read_pid': int(child['pid']),
        'readback_matches': child['value'] == token,
        'distinct_processes': int(child['pid']) != os.getpid(),
    },
    'paths_env': {
        'exists': paths_env.is_file(),
        'sha256': hashlib.sha256(paths_env.read_bytes()).hexdigest()
        if paths_env.is_file()
        else None,
    },
    'gpu': {
        'name': gpu_name,
        'driver_version': driver,
        'memory_mib': int(memory_mib),
    },
}
print(json.dumps(payload, sort_keys=True))
PY
"""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_env_value(path: Path, key: str) -> str:
    """Read ``KEY=value`` or ``KEY: value`` without logging the value."""

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for delimiter in ("=", ":"):
            prefix = f"{key}{delimiter}"
            if line.startswith(prefix):
                value = line[len(prefix) :].strip().strip('"').strip("'")
                if value:
                    return value
    raise ValueError(f"{key} not found in {path}")


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
        raise RuntimeError(f"RunPod GET failed with HTTP {exc.code}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("RunPod GET returned a non-object payload")
    return payload


def run_remote_probe(
    *,
    host: str,
    port: int,
    token: str,
) -> dict[str, Any]:
    command = [
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
        "--",
        token,
    ]
    completed = subprocess.run(
        command,
        input=REMOTE_PROBE.replace("\r\n", "\n").encode("utf-8"),
        capture_output=True,
        check=False,
        timeout=45,
    )
    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError(
            f"RunPod SSH probe failed with exit {completed.returncode}: " f"{stderr.strip()[:300]}"
        )
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("RunPod SSH probe returned no JSON")
    payload = json.loads(lines[-1])
    if not isinstance(payload, dict):
        raise RuntimeError("RunPod SSH probe returned a non-object payload")
    return payload


def build_evidence(
    *,
    pod: dict[str, Any],
    network_volume: dict[str, Any],
    remote: dict[str, Any],
    source_evidence: Path | None,
) -> dict[str, Any]:
    network_volume_id = str(pod.get("networkVolumeId") or "")
    pod_id = str(pod.get("id") or "")
    image_name = str(pod.get("imageName") or "")
    workspace = remote["workspace"]
    root = remote["container_root"]
    api_size_gib = int(network_volume.get("size") or 0)
    mount_target = str(remote["mount"].get("target") or "")
    required_checks = {
        "pod_running": pod.get("desiredStatus") == "RUNNING",
        "network_volume_attached": bool(network_volume_id),
        "network_volume_identity_matches": network_volume_id == str(network_volume.get("id") or ""),
        "network_volume_size_positive": api_size_gib > 0,
        "workspace_mount_path_exact": pod.get("volumeMountPath") == "/workspace"
        and mount_target == "/workspace",
        "workspace_is_distinct_device_from_container_root": workspace["device"] != root["device"],
        "workspace_capacity_consistent_with_api": int(workspace["total_bytes"])
        >= api_size_gib * 1_000_000_000 * 0.9,
        "workspace_has_free_space": int(workspace["free_bytes"]) > 0,
        "sentinel_readback_matches": bool(remote["sentinel"]["readback_matches"]),
        "sentinel_read_from_distinct_process": bool(remote["sentinel"]["distinct_processes"]),
        "paths_env_present": bool(remote["paths_env"]["exists"]),
        "gpu_identity_present": bool(remote["gpu"]["name"]),
        "container_root_is_bounded": int(pod.get("containerDiskInGb") or 0) <= 20,
    }
    source_record = None
    if source_evidence:
        source_record = {
            "path": source_evidence.as_posix(),
            "sha256": _sha256_file(source_evidence),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": _utc_now(),
        "scope": "maskfactory_runpod_persistent_volume_binding",
        "authority": {
            "api_calls": ["GET /v1/pods/{id}", "GET /v1/networkvolumes/{id}"],
            "mutating_api_calls": False,
            "ssh_scope": "bounded_workspace_sentinel_and_read_only_runtime_probe",
            "credentials_read_or_emitted": False,
        },
        "pod": {
            "id_sha256": _sha256_text(pod_id),
            "desired_status": pod.get("desiredStatus"),
            "image_sha256": _sha256_text(image_name),
            "container_disk_gib": pod.get("containerDiskInGb"),
            "pod_volume_gib": pod.get("volumeInGb"),
            "volume_mount_path": pod.get("volumeMountPath"),
        },
        "network_volume": {
            "id_sha256": _sha256_text(network_volume_id),
            "name_sha256": _sha256_text(str(network_volume.get("name") or "")),
            "data_center_id_sha256": _sha256_text(str(network_volume.get("dataCenterId") or "")),
            "size_gib": api_size_gib,
        },
        "filesystem": {
            "workspace": {
                "total_bytes": workspace["total_bytes"],
                "free_bytes": workspace["free_bytes"],
            },
            "container_root": {
                "total_bytes": root["total_bytes"],
                "free_bytes": root["free_bytes"],
            },
            "mount": remote["mount"],
            "sentinel": remote["sentinel"],
            "paths_env": remote["paths_env"],
        },
        "runtime": {"gpu": remote["gpu"]},
        "source_evidence": source_record,
        "checks": required_checks,
        "status": "RUNTIME_PASS_BOUNDED" if all(required_checks.values()) else "RUNTIME_BLOCKED",
        "tool": {
            "path": "tools/verify_runpod_persistence.py",
            "sha256": _sha256_file(Path(__file__).resolve()),
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--pod-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-evidence", type=Path)
    args = parser.parse_args()
    api_key = load_env_value(args.env_file, "RUNPOD_API_KEY")
    pod = runpod_get(f"pods/{args.pod_id}", api_key)
    network_volume_id = str(pod.get("networkVolumeId") or "")
    if not network_volume_id:
        raise RuntimeError("RunPod pod has no attached networkVolumeId")
    volume = runpod_get(f"networkvolumes/{network_volume_id}", api_key)
    mappings = pod.get("portMappings") or {}
    ssh_port = int(mappings.get("22") or 0)
    public_ip = str(pod.get("publicIp") or "")
    if not public_ip or not ssh_port:
        raise RuntimeError("RunPod pod has no public SSH endpoint")
    token = secrets.token_hex(32)
    remote = run_remote_probe(host=public_ip, port=ssh_port, token=token)
    evidence = build_evidence(
        pod=pod,
        network_volume=volume,
        remote=remote,
        source_evidence=args.source_evidence,
    )
    _write_json(args.output.resolve(), evidence)
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "output": str(args.output.resolve()),
                "network_volume_gib": evidence["network_volume"]["size_gib"],
                "workspace_free_bytes": evidence["filesystem"]["workspace"]["free_bytes"],
                "checks_passed": sum(evidence["checks"].values()),
                "checks_total": len(evidence["checks"]),
            },
            sort_keys=True,
        )
    )
    return 0 if evidence["status"] == "RUNTIME_PASS_BOUNDED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
