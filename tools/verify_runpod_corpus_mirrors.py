"""Verify the required MaskedWarehouse and reference-library mirrors on RunPod.

The API key is read from a local env file and is never printed or written to
evidence. The remote operation is read-only: it verifies the two governed
paths and the exact hash of their authoritative inventory snapshot. This
avoids recursively walking almost half a million files on the FUSE volume.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from tools.verify_runpod_persistence import load_env_value, runpod_get
except ModuleNotFoundError:  # Direct ``python tools/...`` execution.
    from verify_runpod_persistence import load_env_value, runpod_get

MASKEDWAREHOUSE_ROOT = "/workspace/assets/MaskedWarehouse"
REFERENCE_ROOT = "/workspace/assets/Reference_Images/Ultimate_Masking_Reference_Images"
REMOTE_SNAPSHOT = (
    "/workspace/maskfactory/qa/live_verification/runpod_assets_authoritative_latest.json"
)
REMOTE_INVENTORY = r"""
set -euo pipefail
python3 - <<'PY'
import hashlib
import json
from pathlib import Path

sample_paths = __SAMPLE_PATHS__

roots = {
    'maskedwarehouse': Path('/workspace/assets/MaskedWarehouse'),
    'ultimate_reference_library': Path('/workspace/assets/Reference_Images/Ultimate_Masking_Reference_Images'),
}

def inventory(root):
    return {
        'path': str(root),
        'exists': root.is_dir(),
        'top_level': sorted(path.name for path in root.iterdir()) if root.is_dir() else [],
    }

snapshot = Path('/workspace/maskfactory/qa/live_verification/runpod_assets_authoritative_latest.json')
payload = {name: inventory(root) for name, root in roots.items()}
payload['maskedwarehouse']['sample_hashes'] = {
    relative: (
        hashlib.sha256((roots['maskedwarehouse'] / relative).read_bytes()).hexdigest()
        if (roots['maskedwarehouse'] / relative).is_file()
        else None
    )
    for relative in sample_paths
}
payload['snapshot'] = {
    'path': str(snapshot),
    'exists': snapshot.is_file(),
    'sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest() if snapshot.is_file() else None,
}
print(json.dumps(payload, sort_keys=True))
PY
"""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def maskedwarehouse_sample_bindings(inventory: dict[str, Any]) -> dict[str, str]:
    """Return the exact deterministic local sample paths and expected hashes."""

    bindings: dict[str, str] = {}
    for source in inventory.get("sources") or ():
        relative_root = Path(str(source.get("root", ""))).name
        source_name = str(source.get("source", ""))
        relative_roots = {
            "celebamask_hq": "CelebAMask-HQ",
            "lapa": "LaPa",
            "lv_mhp_v1": "Body/LV-MHP-v1",
            "swimsuit_preview": "Body/UniDataPro_swimsuit-human-segmentation-dataset",
            "body_archive": "Body/archive",
        }
        relative_root = relative_roots.get(source_name, relative_root)
        for role in ("image_samples", "mask_samples"):
            for row in source.get(role) or ():
                relative = (Path(relative_root) / str(row["path"])).as_posix()
                digest = str(row.get("sha256", ""))
                if relative in bindings or len(digest) != 64:
                    raise RuntimeError("MaskedWarehouse deterministic sample inventory is invalid")
                bindings[relative] = digest
    if not bindings:
        raise RuntimeError("MaskedWarehouse deterministic sample inventory is empty")
    return dict(sorted(bindings.items()))


def inventory_seal(inventory: dict[str, Any]) -> str:
    """Seal platform-neutral counts, extensions, and deterministic samples."""

    payload = {
        "schema_version": inventory.get("schema_version"),
        "sample_hash_policy": inventory.get("sample_hash_policy"),
        "sources": [
            {
                "source": source.get("source"),
                "counts": source.get("counts"),
                "extensions": source.get("extensions"),
                "image_samples": source.get("image_samples"),
                "mask_samples": source.get("mask_samples"),
            }
            for source in inventory.get("sources") or ()
        ],
    }
    return _sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def run_remote_inventory(
    *, host: str, port: int, sample_paths: tuple[str, ...] = ()
) -> dict[str, Any]:
    script = REMOTE_INVENTORY.replace(
        "__SAMPLE_PATHS__", json.dumps(list(sample_paths), separators=(",", ":"))
    )
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
        input=script.replace("\r\n", "\n").encode("utf-8"),
        capture_output=True,
        check=False,
        timeout=120,
    )
    stderr = completed.stderr.decode("utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError(
            f"RunPod corpus inventory failed with exit {completed.returncode}: "
            f"{stderr.strip()[:300]}"
        )
    lines = completed.stdout.decode("utf-8", errors="replace").splitlines()
    payload = json.loads(next(line for line in reversed(lines) if line.strip()))
    if not isinstance(payload, dict):
        raise RuntimeError("RunPod corpus inventory returned a non-object payload")
    return payload


def build_evidence(
    *,
    pod: dict[str, Any],
    remote: dict[str, Any],
    source: dict[str, Any],
    source_path: Path,
    local_inventory: dict[str, Any] | None = None,
    local_inventory_path: Path | None = None,
) -> dict[str, Any]:
    expected = {
        "maskedwarehouse": source["sanity_counts"]["masked_warehouse"],
        "ultimate_reference_library": source["sanity_counts"]["ultimate_masking_reference"],
    }
    source_sha256 = _sha256_file(source_path)
    checks: dict[str, bool] = {
        "pod_running": pod.get("desiredStatus") == "RUNNING",
        "remote_snapshot_path_exact": remote["snapshot"].get("path") == REMOTE_SNAPSHOT,
        "remote_snapshot_exists": remote["snapshot"].get("exists") is True,
        "remote_snapshot_hash_matches": remote["snapshot"].get("sha256") == source_sha256,
    }
    inventories: dict[str, Any] = {}
    for name, path in (
        ("maskedwarehouse", MASKEDWAREHOUSE_ROOT),
        ("ultimate_reference_library", REFERENCE_ROOT),
    ):
        observed = remote[name]
        wanted = expected[name]
        checks[f"{name}_path_exact"] = observed.get("path") == path
        checks[f"{name}_exists"] = observed.get("exists") is True
        required_top_level = (
            {"Body", "CelebAMask-HQ", "LaPa"}
            if name == "maskedwarehouse"
            else {"benchmark_reference", "manifests"}
        )
        checks[f"{name}_required_top_level_present"] = required_top_level.issubset(
            set(observed.get("top_level") or [])
        )
        inventories[name] = {
            "path": path,
            "top_level": observed.get("top_level"),
            "snapshot_file_count": wanted["file_count"],
            "snapshot_bytes": wanted["bytes"],
        }
    local_reconciliation: dict[str, Any] | None = None
    if local_inventory is not None:
        sample_bindings = maskedwarehouse_sample_bindings(local_inventory)
        remote_samples = remote["maskedwarehouse"].get("sample_hashes") or {}
        local_total = sum(
            int(item.get("counts", {}).get("total_files", 0))
            for item in local_inventory.get("sources") or ()
        )
        checks["maskedwarehouse_local_count_matches_snapshot"] = (
            local_total == expected["maskedwarehouse"]["file_count"]
        )
        checks["maskedwarehouse_sample_paths_exact"] = set(remote_samples) == set(sample_bindings)
        checks["maskedwarehouse_sample_hashes_match"] = remote_samples == sample_bindings
        local_reconciliation = {
            "inventory_path": (
                local_inventory_path.as_posix() if local_inventory_path is not None else None
            ),
            "inventory_file_sha256": (
                _sha256_file(local_inventory_path) if local_inventory_path is not None else None
            ),
            "inventory_seal_sha256": inventory_seal(local_inventory),
            "local_file_count": local_total,
            "remote_snapshot_file_count": expected["maskedwarehouse"]["file_count"],
            "sample_count": len(sample_bindings),
            "sample_set_sha256": _sha256_text(
                json.dumps(sample_bindings, sort_keys=True, separators=(",", ":"))
            ),
        }
    return {
        "schema_version": "1.0.0",
        "recorded_at": _utc_now(),
        "scope": "maskfactory_required_runpod_corpus_mirrors",
        "authority": {
            "api_calls": ["GET /v1/pods/{id}"],
            "mutating_api_calls": False,
            "remote_operation": "read_only_root_and_hash_bound_inventory_snapshot_check",
            "credentials_read_or_emitted": False,
        },
        "pod": {
            "id_sha256": _sha256_text(str(pod.get("id") or "")),
            "desired_status": pod.get("desiredStatus"),
        },
        "source_snapshot": {
            "path": source_path.as_posix(),
            "sha256": source_sha256,
            "verified_at_utc": source.get("verified_at_utc"),
        },
        "inventories": inventories,
        "maskedwarehouse_local_remote_reconciliation": local_reconciliation,
        "checks": checks,
        "tool": {
            "path": "tools/verify_runpod_corpus_mirrors.py",
            "sha256": _sha256_file(Path(__file__).resolve()),
        },
        "status": "RUNTIME_PASS_HASH_BOUND_SNAPSHOT" if all(checks.values()) else "RUNTIME_DRIFT",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--pod-id", required=True)
    parser.add_argument("--source-evidence", type=Path, required=True)
    parser.add_argument(
        "--local-maskedwarehouse-inventory",
        type=Path,
        default=Path("configs/maskedwarehouse_inventory.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    api_key = load_env_value(args.env_file, "RUNPOD_API_KEY")
    pod = runpod_get(f"pods/{args.pod_id}", api_key)
    mappings = pod.get("portMappings") or {}
    ssh_port = int(mappings.get("22") or 0)
    public_ip = str(pod.get("publicIp") or "")
    if not public_ip or not ssh_port:
        raise RuntimeError("RunPod pod has no public SSH endpoint")
    source = json.loads(args.source_evidence.read_text(encoding="utf-8-sig"))
    local_inventory = json.loads(
        args.local_maskedwarehouse_inventory.read_text(encoding="utf-8-sig")
    )
    sample_bindings = maskedwarehouse_sample_bindings(local_inventory)
    remote = run_remote_inventory(
        host=public_ip,
        port=ssh_port,
        sample_paths=tuple(sample_bindings),
    )
    evidence = build_evidence(
        pod=pod,
        remote=remote,
        source=source,
        source_path=args.source_evidence,
        local_inventory=local_inventory,
        local_inventory_path=args.local_maskedwarehouse_inventory,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "checks_passed": sum(evidence["checks"].values()),
                "checks_total": len(evidence["checks"]),
                "output": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0 if evidence["status"] == "RUNTIME_PASS_HASH_BOUND_SNAPSHOT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
