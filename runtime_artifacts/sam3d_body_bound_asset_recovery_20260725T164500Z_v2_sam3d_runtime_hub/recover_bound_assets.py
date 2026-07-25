from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/workspace/maskfactory")
OUT = Path(__file__).resolve().parent
LOCK_PATH = ROOT / "env/sam3d_body_runtime.lock.json"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_self(document: dict) -> str:
    body = {key: value for key, value in document.items() if key != "self_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def write_receipt(document: dict) -> None:
    document["self_sha256"] = canonical_self(document)
    (OUT / "ASSET_RECOVERY_RECEIPT.json").write_text(
        json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def run(argv: tuple[str, ...], *, cwd: Path | None = None) -> str:
    return subprocess.check_output(argv, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def main() -> int:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    source = lock["source"]
    checkpoint = lock["checkpoint"]
    source_target = ROOT / source["local_path"]
    checkpoint_target = ROOT / checkpoint["local_root"]
    stage = OUT / "staging"
    started = datetime.now(timezone.utc).isoformat()
    disk = shutil.disk_usage(ROOT)
    payload: dict = {
        "artifact_type": "sam3d_body_bound_asset_recovery_receipt.v2",
        "started_at_utc": started,
        "execution_identity": {
            "pod_id": "68psfqtaogg7s7",
            "pod_name": "vitreous_beige_centipede",
            "network_volume_id": "o9qv2ld91c",
            "volume_mount": "/workspace",
        },
        "preflight": {
            "free_bytes": disk.free,
            "required_checkpoint_bytes": checkpoint["total_size_bytes"],
            "source_target": str(source_target.relative_to(ROOT)),
            "checkpoint_target": str(checkpoint_target.relative_to(ROOT)),
            "source_target_exists": source_target.exists(),
            "checkpoint_target_exists": checkpoint_target.exists(),
        },
        "runtime_interpreter": "runtime_artifacts/sam3d_body_runpod_env/bin/python",
        "bindings": {
            "runtime_lock": "env/sam3d_body_runtime.lock.json",
            "runtime_lock_sha256": sha(LOCK_PATH),
            "source_repository": source["repository"],
            "source_commit": source["commit"],
            "source_tree": source["tree"],
            "checkpoint_repository": checkpoint["repository"],
            "checkpoint_revision": checkpoint["repository_revision"],
            "checkpoint_assets": checkpoint["assets"],
            "host_adapter_v2_failure_receipt": "runtime_artifacts/sam3d_body_v3_host_adapter_runtime_20260725T162500Z_v2_numeric_pid_preflight/HOST_ADAPTER_RUNTIME_RECEIPT.json",
        },
        "authority": {
            "provider_lifecycle_state": "installed_unqualified",
            "may_author_gold": False,
            "may_promote_provider": False,
            "overwrite_allowed": False,
            "replacement_model_allowed": False,
        },
    }
    try:
        from huggingface_hub import hf_hub_download
        if source_target.exists() or checkpoint_target.exists():
            raise RuntimeError("bound target exists; recovery refuses overwrite")
        if stage.exists():
            raise RuntimeError("recovery staging path already exists")
        if disk.free < checkpoint["total_size_bytes"] * 2:
            raise RuntimeError("insufficient durable free space for staged exact recovery")
        stage.mkdir(parents=True)
        source_stage = stage / "source"
        checkpoint_stage = stage / "checkpoint"
        run(("git", "clone", "--no-checkout", source["repository"], str(source_stage)))
        run(("git", "checkout", "--detach", source["commit"]), cwd=source_stage)
        actual_commit = run(("git", "rev-parse", "HEAD"), cwd=source_stage)
        actual_tree = run(("git", "rev-parse", "HEAD^{tree}"), cwd=source_stage)
        source_status = run(("git", "status", "--porcelain", "--untracked-files=no"), cwd=source_stage)
        if actual_commit != source["commit"] or actual_tree != source["tree"] or source_status:
            raise RuntimeError("restored source tree does not match immutable lock")
        recovered_assets: list[dict] = []
        for asset in checkpoint["assets"]:
            filename = asset["filename"]
            hf_hub_download(
                repo_id=checkpoint["repository"],
                repo_type="model",
                revision=checkpoint["repository_revision"],
                filename=filename,
                local_dir=checkpoint_stage,
            )
            local = checkpoint_stage / filename
            if not local.is_file():
                raise RuntimeError(f"locked checkpoint asset missing after download: {filename}")
            actual_sha = sha(local)
            actual_size = local.stat().st_size
            if actual_sha != asset["sha256"] or actual_size != asset["size_bytes"]:
                raise RuntimeError(f"locked checkpoint asset hash/size mismatch: {filename}")
            recovered_assets.append(
                {"filename": filename, "sha256": actual_sha, "size_bytes": actual_size}
            )
        source_target.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_target.parent.mkdir(parents=True, exist_ok=True)
        if source_target.exists() or checkpoint_target.exists():
            raise RuntimeError("bound target appeared during recovery; refusing overwrite")
        os.rename(source_stage, source_target)
        os.rename(checkpoint_stage, checkpoint_target)
        payload["result"] = {
            "source_commit": actual_commit,
            "source_tree": actual_tree,
            "source_status": source_status,
            "checkpoint_assets": recovered_assets,
            "source_target": str(source_target.relative_to(ROOT)),
            "checkpoint_target": str(checkpoint_target.relative_to(ROOT)),
        }
        payload["status"] = "ASSET_RECOVERY_PASS_EXACT_BOUND_BYTES"
        payload["next_safe_action"] = "Run a new immutable host-adapter runtime binding only after rechecking local broker route and zero numeric GPU compute processes. No provider promotion or matrix change is authorized."
        payload["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_receipt(payload)
        print(json.dumps({"status": payload["status"], "self_sha256": payload["self_sha256"]}, sort_keys=True))
        return 0
    except Exception as exc:
        payload["status"] = "ASSET_RECOVERY_FAIL"
        payload["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        payload["staging_preserved"] = str(stage.relative_to(ROOT)) if stage.exists() else None
        payload["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_receipt(payload)
        print(json.dumps({"status": payload["status"], "self_sha256": payload["self_sha256"]}, sort_keys=True))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
