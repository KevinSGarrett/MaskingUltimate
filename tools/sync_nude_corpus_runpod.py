#!/usr/bin/env python3
"""Probe or stream the governed adult-corpus allowlist to a RunPod workspace."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

EXPECTED_MASKED_WAREHOUSE = "/workspace/assets/MaskedWarehouse"
DEFAULT_LOCAL_ROOT = Path(r"C:\Comfy_UI_Main\MaskedWarehouse\Nude")


def _ssh(host: str, port: int, command: str, *, timeout: int = 180) -> str:
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
            f"bash -lc {shlex.quote(command)}",
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )
    if completed.returncode:
        raise RuntimeError(
            f"remote command failed ({completed.returncode}): {completed.stderr.strip()[:500]}"
        )
    return completed.stdout.strip()


def probe(host: str, port: int) -> dict[str, object]:
    command = r"""set -euo pipefail
source /workspace/paths.env
test "$MASKED_WAREHOUSE" = "/workspace/assets/MaskedWarehouse"
python3 -c 'import json,pathlib; p=pathlib.Path("/workspace/assets/MaskedWarehouse/Nude"); print(json.dumps({"paths_env_binding": True, "nude_exists": p.is_dir(), "nude_entries": len(list(p.iterdir())) if p.is_dir() else 0}))'
"""
    payload = json.loads(_ssh(host, port, command))
    if payload.get("paths_env_binding") is not True:
        raise RuntimeError("RunPod paths.env binding failed closed")
    return payload


def _allowlist(local_root: Path) -> tuple[Path, list[str]]:
    manifest = local_root / "_MASKFACTORY_INTAKE" / "runpod_transfer_files.generated.txt"
    rows = [
        line.strip() for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if len(rows) != 82_639 or len(rows) != len(set(rows)):
        raise RuntimeError("transfer allowlist count or uniqueness drift")
    for relative in rows:
        if relative.startswith(("/", "\\")) or ".." in Path(relative).parts:
            raise RuntimeError(f"unsafe transfer path: {relative}")
        path = local_root / Path(relative)
        if not path.is_file():
            raise RuntimeError(f"allowlisted source missing: {relative}")
    return manifest, rows


def transfer(host: str, port: int, local_root: Path) -> dict[str, object]:
    manifest, rows = _allowlist(local_root)
    remote_command = r"""set -euo pipefail
source /workspace/paths.env
test "$MASKED_WAREHOUSE" = "/workspace/assets/MaskedWarehouse"
mkdir -p "$MASKED_WAREHOUSE/Nude"
tar -xf - -C "$MASKED_WAREHOUSE/Nude"
"""
    ssh = subprocess.Popen(
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
            f"bash -lc {shlex.quote(remote_command)}",
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    tar = subprocess.Popen(
        ["tar", "-cf", "-", "-T", str(manifest)],
        cwd=local_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if tar.stdout is None or ssh.stdin is None:
        raise RuntimeError("transfer pipes unavailable")
    archive_bytes = 0
    last_heartbeat = time.monotonic()
    try:
        while chunk := tar.stdout.read(8 * 1024 * 1024):
            ssh.stdin.write(chunk)
            archive_bytes += len(chunk)
            if time.monotonic() - last_heartbeat >= 30:
                print(json.dumps({"status": "TRANSFER_RUNNING", "archive_bytes": archive_bytes}))
                sys.stdout.flush()
                last_heartbeat = time.monotonic()
        ssh.stdin.close()
        tar_error = (tar.stderr.read() if tar.stderr else b"").decode("utf-8", errors="replace")
        tar_code = tar.wait(timeout=120)
        ssh_error = (ssh.stderr.read() if ssh.stderr else b"").decode("utf-8", errors="replace")
        ssh_code = ssh.wait(timeout=300)
    finally:
        if tar.poll() is None:
            tar.terminate()
        if ssh.poll() is None:
            ssh.terminate()
    if tar_code or ssh_code:
        raise RuntimeError(
            f"transfer failed: tar={tar_code} ssh={ssh_code}; "
            f"tar_stderr={tar_error[-500:]}; ssh_stderr={ssh_error[-500:]}"
        )
    return {
        "status": "TRANSFER_COMPLETE",
        "allowlisted_files": len(rows),
        "archive_bytes": archive_bytes,
    }


def verify(host: str, port: int) -> dict[str, object]:
    command = r"""set -euo pipefail
source /workspace/paths.env
test "$MASKED_WAREHOUSE" = "/workspace/assets/MaskedWarehouse"
cd "$MASKED_WAREHOUSE/Nude/_MASKFACTORY_INTAKE"
python3 validate_registry.py --intake . --platform runpod --rehash sample >/tmp/maskfactory_nude_validator.txt
python3 - <<'PY'
import json
from pathlib import Path
registry=json.loads(Path('dataset_registry.generated.json').read_text())
index=json.loads(Path('batch_shards/_index.json').read_text())
print(json.dumps({
  'validator_output': Path('/tmp/maskfactory_nude_validator.txt').read_text().strip(),
  'dataset_count': len(registry['datasets']),
  'record_count': registry['record_count'],
  'registry_sha256': registry['self_sha256'],
  'shard_count': index['shard_count'],
  'shards_per_platform': index['shard_count'] // 2,
  'shard_index_sha256': index['self_sha256'],
}, sort_keys=True))
PY
"""
    return json.loads(_ssh(host, port, command, timeout=300))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--local-root", type=Path, default=DEFAULT_LOCAL_ROOT)
    parser.add_argument("--transfer", action="store_true")
    args = parser.parse_args()
    result: dict[str, object] = {"probe": probe(args.host, args.port)}
    if args.transfer:
        if result["probe"].get("nude_exists"):
            raise RuntimeError(
                "remote Nude root already exists; compute the relative path/size/SHA-256 delta "
                "instead of replaying the initial all-missing transfer"
            )
        result["transfer"] = transfer(args.host, args.port, args.local_root.resolve(strict=True))
        result["verification"] = verify(args.host, args.port)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
