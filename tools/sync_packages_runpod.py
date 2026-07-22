"""Resumably sync and independently restore one package tree on persistent RunPod storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from verify_runpod_persistence import load_env_value, runpod_get


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def manifest_sha256(manifest: dict) -> str:
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build(source: Path, root: Path, chunk_size: int = 262144) -> dict:
    files = sorted(p for p in source.rglob("*") if p.is_file())
    file_map = {p.relative_to(source).as_posix(): sha(p) for p in files}
    archive = root / "packages.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zf:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            zf.writestr(info, path.read_bytes())
    chunks = []
    with archive.open("rb") as stream:
        index = 0
        while payload := stream.read(chunk_size):
            part = root / f"part-{index:06d}"
            part.write_bytes(payload)
            chunks.append(
                {"index": index, "name": part.name, "size": len(payload), "sha256": sha(part)}
            )
            index += 1
    manifest = {
        "schema_version": "1.0.0",
        "archive_sha256": sha(archive),
        "archive_bytes": archive.stat().st_size,
        "files": file_map,
        "chunks": chunks,
    }
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def ssh(host: str, port: int, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    bootstrap = f"import sys;sys.argv={['remote', *args]!r};exec({script!r})"
    remote_command = f"python3 -c {shlex.quote(bootstrap)}"
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
        remote_command,
    ]
    for attempt in range(3):
        completed = subprocess.run(
            command, check=False, text=True, capture_output=True, timeout=120
        )
        if completed.returncode == 0:
            return completed
        if attempt < 2:
            time.sleep(2**attempt)
    raise subprocess.CalledProcessError(
        completed.returncode, command, completed.stdout, completed.stderr
    )


def scp(host: str, port: int, source: Path, target: str) -> None:
    command = [
        "scp",
        "-q",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=15",
        "-P",
        str(port),
        str(source),
        f"root@{host}:{target}",
    ]
    for attempt in range(3):
        completed = subprocess.run(
            command, check=False, text=True, capture_output=True, timeout=120
        )
        if completed.returncode == 0:
            return
        if attempt < 2:
            time.sleep(2**attempt)
    raise subprocess.CalledProcessError(
        completed.returncode, command, completed.stdout, completed.stderr
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", type=Path, required=True)
    ap.add_argument("--pod-id", required=True)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--seed-fault", choices=("missing", "corrupt", "partial"))
    args = ap.parse_args()
    key = load_env_value(args.env_file, "RUNPOD_API_KEY")
    pod = runpod_get(f"pods/{args.pod_id}", key)
    host, port = str(pod["publicIp"]), int(pod["portMappings"]["22"])
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        manifest = build(args.source, root)
        remote = f"/workspace/maskfactory/releases/package_sync/{manifest['manifest_sha256']}"
        ssh(
            host,
            port,
            "import pathlib,sys; pathlib.Path(sys.argv[1]).mkdir(parents=True,exist_ok=True)",
            remote,
        )
        if args.seed_fault:
            fault_script = {
                "missing": "import pathlib,sys; (pathlib.Path(sys.argv[1])/'part-000000').unlink(missing_ok=True)",
                "corrupt": "import pathlib,sys; (pathlib.Path(sys.argv[1])/'part-000000').write_bytes(b'corrupt')",
                "partial": "import pathlib,sys; p=pathlib.Path(sys.argv[1])/'part-000000'; p.write_bytes(p.read_bytes()[:17])",
            }[args.seed_fault]
            ssh(host, port, fault_script, remote)
        uploaded = skipped = 0
        for chunk in manifest["chunks"]:
            target = f"{remote}/{chunk['name']}"
            probe = ssh(
                host,
                port,
                "import hashlib,pathlib,sys; p=pathlib.Path(sys.argv[1]); print(hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else '')",
                target,
            ).stdout.strip()
            if probe == chunk["sha256"]:
                skipped += 1
                continue
            scp(host, port, root / chunk["name"], target)
            uploaded += 1
        scp(host, port, root / "manifest.json", f"{remote}/manifest.json")
        script = """import hashlib,json,pathlib,subprocess,sys,zipfile
r=pathlib.Path(sys.argv[1]); m=json.loads((r/'manifest.json').read_text()); claimed=m['manifest_sha256']; unsigned={k:v for k,v in m.items() if k!='manifest_sha256'}; actual=hashlib.sha256(json.dumps(unsigned,sort_keys=True,separators=(',',':')).encode()).hexdigest(); assert actual==claimed==r.name; chunks=m['chunks']; assert [c['index'] for c in chunks]==list(range(len(chunks))); assert all(c['name']==f\"part-{c['index']:06d}\" for c in chunks); parts=[]
for c in chunks:
 p=r/c['name']; data=p.read_bytes(); assert len(data)==c['size']; assert hashlib.sha256(data).hexdigest()==c['sha256']; parts.append(data)
a=r/'packages.zip'; b=b''.join(parts); assert len(b)==m['archive_bytes']; assert hashlib.sha256(b).hexdigest()==m['archive_sha256']; tmp=r/'restore.partial'; final=r/'restored'; a.write_bytes(b); tmp.mkdir(exist_ok=True); zipfile.ZipFile(a).extractall(tmp); subprocess.check_call([sys.executable,'-c',\"import hashlib,json,pathlib,sys; p=pathlib.Path(sys.argv[1]); m=json.loads(pathlib.Path(sys.argv[2]).read_text()); assert sorted(x.relative_to(p).as_posix() for x in p.rglob('*') if x.is_file())==sorted(m['files']); assert all(hashlib.sha256((p/k).read_bytes()).hexdigest()==v for k,v in m['files'].items())\",str(tmp),str(r/'manifest.json')]);
if not final.exists(): tmp.rename(final)
elif tmp.exists():
 import shutil; shutil.rmtree(tmp)
print(json.dumps({'status':'PASS','manifest_sha256':claimed,'chunk_verification':True,'separate_process_file_verification':True,'restored_files':len(m['files']),'archive_sha256':m['archive_sha256'],'remote_root':str(r)}))"""
        receipt = json.loads(ssh(host, port, script, remote).stdout.strip().splitlines()[-1])
    report = {
        "schema_version": "1.0.0",
        "status": "RUNTIME_PASS_BOUNDED",
        "pod_id": args.pod_id,
        "network_volume_id": pod.get("networkVolumeId"),
        "manifest": manifest,
        "chunks_uploaded": uploaded,
        "chunks_reused": skipped,
        "seeded_fault": args.seed_fault,
        "remote": receipt,
        "authority": "persistent_package_transport_only_not_gold",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "uploaded": uploaded,
                "reused": skipped,
                "files": receipt["restored_files"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
