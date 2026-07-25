#!/usr/bin/env python3
"""Read-only verifier for the exact P0-17.25 package after Pod replacement."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys


ROOT = pathlib.Path(
    "/workspace/maskfactory/releases/package_sync/"
    "3b7f659cce57672467be14457b367e13b90599817ab74bc3fd1c3d3219a2105a"
)
PRIOR_RECEIPT = pathlib.Path(
    "/workspace/maskfactory/qa/live_verification/"
    "runpod_package_persistence_and_restore_20260722.json"
)
DESCRIPTOR = pathlib.Path("/workspace/maskfactory/data/packages.dvc")
EXPECTED = {
    "prior_receipt_sha256": "0954318c66c5a5f97ea1a1da4774bdc8339564df0160f78e9ffb30de6541a9db",
    "descriptor_sha256": "1a15b90a1741874d8e5c1dedfca3f6599bca92d9e4d09af2351cfeaba4ff892c",
    "manifest_sha256": "3b7f659cce57672467be14457b367e13b90599817ab74bc3fd1c3d3219a2105a",
    "archive_sha256": "20525ba54c02e788f72d76ce50adf51ba0bba4c9aafc49c60895984148701cce",
    "file_count": 15,
    "chunk_count": 5,
}


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    self_hash = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    checks: dict[str, bool] = {
        "prior_receipt_hash": sha256(PRIOR_RECEIPT) == EXPECTED["prior_receipt_sha256"],
        "descriptor_hash": sha256(DESCRIPTOR) == EXPECTED["descriptor_sha256"],
        "manifest_directory_binding": (
            ROOT.name == manifest["manifest_sha256"] == EXPECTED["manifest_sha256"]
        ),
        "manifest_self_hash": self_hash == manifest["manifest_sha256"],
        "archive_claim": manifest["archive_sha256"] == EXPECTED["archive_sha256"],
        "file_count": len(manifest["files"]) == EXPECTED["file_count"],
        "chunk_count": len(manifest["chunks"]) == EXPECTED["chunk_count"],
    }
    parts: list[bytes] = []
    for index, chunk in enumerate(manifest["chunks"]):
        part = ROOT / chunk["name"]
        data = part.read_bytes()
        checks[f"chunk_{index:06d}"] = (
            chunk["index"] == index
            and chunk["name"] == f"part-{index:06d}"
            and len(data) == chunk["size"]
            and hashlib.sha256(data).hexdigest() == chunk["sha256"]
        )
        parts.append(data)
    archive = b"".join(parts)
    checks["reconstructed_archive"] = (
        len(archive) == manifest["archive_bytes"]
        and hashlib.sha256(archive).hexdigest() == manifest["archive_sha256"]
    )
    child_code = (
        "import hashlib,json,os,pathlib,sys; "
        "root=pathlib.Path(sys.argv[1]); m=json.loads((root/'manifest.json').read_text()); "
        "restored=root/'restored'; actual=sorted(p.relative_to(restored).as_posix() for p in restored.rglob('*') if p.is_file()); "
        "expected=sorted(m['files']); ok=actual==expected and all(hashlib.sha256((restored/k).read_bytes()).hexdigest()==v for k,v in m['files'].items()); "
        "print(json.dumps({'pid':os.getpid(),'ok':ok,'files':len(actual)}))"
    )
    child = json.loads(
        subprocess.check_output([sys.executable, "-c", child_code, str(ROOT)], text=True)
    )
    checks["separate_process_restore_tree"] = (
        child["ok"]
        and child["files"] == EXPECTED["file_count"]
        and child["pid"] != os.getpid()
    )
    result = {
        "schema_version": "1.0.0",
        "scope": "read_only_exact_package_restore_after_distinct_pod_lifecycle",
        "status": "RUNTIME_PASS_POD_REPLACEMENT_RESTORE"
        if all(checks.values())
        else "RUNTIME_BLOCKED",
        "checks": checks,
        "manifest_sha256": manifest["manifest_sha256"],
        "archive_sha256": manifest["archive_sha256"],
        "restored_files": child["files"],
        "reader_pid": child["pid"],
        "authority": {
            "writes": False,
            "sync": False,
            "fault_seed": False,
            "package_or_model_authority": False,
        },
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "RUNTIME_PASS_POD_REPLACEMENT_RESTORE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
