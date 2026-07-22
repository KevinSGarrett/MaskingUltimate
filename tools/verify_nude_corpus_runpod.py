#!/usr/bin/env python3
"""Compare every adult-corpus allowlisted file to RunPod by path, size, and SHA-256."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_LOCAL_ROOT = Path(r"C:\Comfy_UI_Main\MaskedWarehouse\Nude")
REMOTE_ROOT = "/workspace/assets/MaskedWarehouse/Nude"
REMOTE_PROGRAM = r"""
import hashlib,json,pathlib,sys
root=pathlib.Path("/workspace/assets/MaskedWarehouse/Nude").resolve()
counts={"records":0,"matched":0,"missing":0,"size_mismatch":0,"hash_mismatch":0}
seal=hashlib.sha256()
for line in sys.stdin:
    seal.update(line.encode("utf-8"))
    row=json.loads(line)
    relative=row["path"]
    candidate=(root/pathlib.Path(relative)).resolve()
    try: candidate.relative_to(root)
    except ValueError: raise SystemExit("unsafe manifest path")
    counts["records"]+=1
    if not candidate.is_file(): counts["missing"]+=1; continue
    if candidate.stat().st_size!=row["size"]: counts["size_mismatch"]+=1; continue
    digest=hashlib.sha256()
    with candidate.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4*1024*1024),b""): digest.update(chunk)
    if digest.hexdigest()!=row["sha256"]: counts["hash_mismatch"]+=1
    else: counts["matched"]+=1
print(json.dumps({"counts":counts,"manifest_stream_sha256":seal.hexdigest()},sort_keys=True))
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(host: str, port: int, local_root: Path) -> dict[str, object]:
    allowlist = local_root / "_MASKFACTORY_INTAKE" / "runpod_transfer_files.generated.txt"
    rows = [line.strip() for line in allowlist.read_text(encoding="utf-8").splitlines() if line]
    if len(rows) != 82_639 or len(rows) != len(set(rows)):
        raise RuntimeError("transfer allowlist count or uniqueness drift")
    if any(
        path.lower().endswith(".zip")
        or "/.cache/" in f"/{path.lower()}/"
        or "huggingface" in path.lower()
        for path in rows
    ):
        raise RuntimeError("ZIP or cache path entered the governed allowlist")
    remote_command = f"python3 -c {shlex.quote(REMOTE_PROGRAM)}"
    remote = subprocess.Popen(
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
            remote_command,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if remote.stdin is None:
        raise RuntimeError("remote verification input unavailable")
    local_seal = hashlib.sha256()
    total_bytes = 0
    last_heartbeat = time.monotonic()
    for index, relative in enumerate(rows, start=1):
        path = local_root / Path(relative)
        if not path.is_file():
            remote.terminate()
            raise RuntimeError(f"allowlisted source missing: {relative}")
        size = path.stat().st_size
        line = (
            json.dumps(
                {"path": relative.replace("\\", "/"), "size": size, "sha256": _sha256(path)},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        local_seal.update(line.encode("utf-8"))
        remote.stdin.write(line.encode("utf-8"))
        total_bytes += size
        if time.monotonic() - last_heartbeat >= 30:
            print(json.dumps({"status": "VERIFY_RUNNING", "files": index, "bytes": total_bytes}))
            sys.stdout.flush()
            last_heartbeat = time.monotonic()
    remote.stdin.close()
    stdout = (remote.stdout.read() if remote.stdout else b"").decode("utf-8", errors="replace")
    stderr = (remote.stderr.read() if remote.stderr else b"").decode("utf-8", errors="replace")
    code = remote.wait(timeout=900)
    if code:
        raise RuntimeError(f"remote verification failed ({code}): {stderr[-500:]}")
    result = json.loads(stdout.strip())
    counts = result["counts"]
    result.update(
        {
            "status": "PASS" if counts["matched"] == len(rows) else "DRIFT",
            "local_manifest_stream_sha256": local_seal.hexdigest(),
            "local_total_bytes": total_bytes,
            "allowlisted_files": len(rows),
            "remote_root": REMOTE_ROOT,
        }
    )
    if result["manifest_stream_sha256"] != local_seal.hexdigest():
        result["status"] = "DRIFT"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--local-root", type=Path, default=DEFAULT_LOCAL_ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.host, args.port, args.local_root.resolve(strict=True))
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
