from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

ROOT = Path("/workspace/maskfactory")
OUT = ROOT / "runtime_artifacts/eomt_dinov3_cpu_shadow_load_20260725T203000Z"
BINDING = OUT / "cpu_shadow_load_binding.json"
RECEIPT = OUT / "EOMT_CPU_SHADOW_LOAD_RECEIPT.json"
LOCK = ROOT / "env/eomt_dinov3_runtime_v2.lock.json"
CLOSURE = ROOT / "runtime_artifacts/eomt_dinov3_clean_isolated_runtime_closure_20260725T202000Z/CLEAN_ISOLATED_RUNTIME_RECEIPT.json"
SNAPSHOT = ROOT / "models/runtime_cache/eomt_dinov3_small_602edaa"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps({key: value for key, value in payload.items() if key != "self_sha256"}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_receipt(payload: dict) -> None:
    payload["self_sha256"] = canonical(payload)
    RECEIPT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main() -> int:
    receipt = {
        "artifact_type": "eomt_dinov3_cpu_shadow_load_receipt.v1",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": None,
        "controls": {"cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"), "network_access": False, "model_load": "cpu_only", "inference": False, "gpu_execution": False, "provider_promotion": False},
        "binding": {"path": str(BINDING.relative_to(ROOT)), "sha256": sha(BINDING)},
    }
    try:
        if RECEIPT.exists():
            raise RuntimeError("receipt already exists; refusing duplicate launch")
        binding = json.loads(BINDING.read_text())
        if binding["self_sha256"] != canonical(binding):
            raise RuntimeError("binding canonical self hash mismatch")
        if sha(LOCK) != binding["inputs"]["eomt_lock_sha256"]:
            raise RuntimeError("EoMT lock hash mismatch")
        if sha(CLOSURE) != binding["inputs"]["runtime_closure_receipt_sha256"]:
            raise RuntimeError("clean runtime closure receipt hash mismatch")
        closure = json.loads(CLOSURE.read_text())
        if closure.get("status") != "CLEAN_ISOLATED_RUNTIME_CLOSURE_IMPORT_PASS" or closure.get("self_sha256") != binding["inputs"]["runtime_closure_receipt_self_sha256"]:
            raise RuntimeError("clean runtime closure is not an accepted import pass")
        lock = json.loads(LOCK.read_text())
        if lock["target_contract"]["class_count"] != binding["target_contract"]["class_count"] or lock["target_contract"]["authority"] != "training_and_shadow_evaluation_only":
            raise RuntimeError("target authority or class-count contract drift")
        snapshot_rows = lock["snapshot"]["files"]
        verified = []
        for row in snapshot_rows:
            path = SNAPSHOT / row["filename"]
            if not path.is_file() or path.stat().st_size != row["size_bytes"] or sha(path) != row["sha256"]:
                raise RuntimeError("snapshot drift: " + row["filename"])
            verified.append({"filename": row["filename"], "sha256": row["sha256"], "size_bytes": row["size_bytes"]})
        from transformers import EomtDinov3ForUniversalSegmentation
        model = EomtDinov3ForUniversalSegmentation.from_pretrained(
            str(SNAPSHOT), local_files_only=True, use_safetensors=True
        )
        receipt["snapshot_verified"] = verified
        receipt["model"] = {
            "class": type(model).__name__,
            "config_model_type": getattr(model.config, "model_type", None),
            "config_num_labels": getattr(model.config, "num_labels", None),
            "device": str(next(model.parameters()).device),
            "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
            "pretrained_head_status": "loaded_upstream_coco_panoptic_head_only; 66-class body_parts_v2 target head remains uninstantiated and unpromoted",
        }
        del model
        receipt["status"] = "EOMT_CPU_SHADOW_LOAD_PASS"
        receipt["next_safe_action"] = "A new binding must independently admit GPU use, instantiate the random 66-class target head, and run shadow-only inference on governed real-adult assets before any provider/tournament claim."
        receipt["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_receipt(receipt)
        print(json.dumps({"status": receipt["status"], "self_sha256": receipt["self_sha256"]}, sort_keys=True))
        return 0
    except Exception as exc:
        receipt["status"] = "EOMT_CPU_SHADOW_LOAD_FAIL"
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        receipt["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_receipt(receipt)
        print(json.dumps({"status": receipt["status"], "self_sha256": receipt["self_sha256"]}, sort_keys=True))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
