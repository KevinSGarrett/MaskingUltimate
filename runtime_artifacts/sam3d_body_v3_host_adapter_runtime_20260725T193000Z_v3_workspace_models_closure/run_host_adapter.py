from __future__ import annotations

import hashlib
import json
import subprocess
import traceback
from datetime import datetime, timezone
from pathlib import Path

from maskfactory.providers.contracts import BoxProposal
from maskfactory.providers.sam3d_body import Sam3dBodyGeometryProvider, Sam3dBodyV3RunpodBackend

ROOT = Path("/workspace/maskfactory")
OUT = Path(__file__).resolve().parent
IMAGE = ROOT / "qa/fixtures/smoke/ultralytics_bus_adults.jpg"
SOURCE_ROOT = Path("/workspace/models/runtime_cache/sam-3d-body_b5c765a")
CHECKPOINT_ROOT = Path("/workspace/models/runtime_cache/sam3d_body_checkpoint_11aaa346")
BBOX = (45.0, 390.0, 230.0, 920.0)
EXPECTED_SHA256 = {
    "image": "c02019c4979c191eb739ddd944445ef408dad5679acab6fd520ef9d434bfbc63",
    "model.ckpt": "b5a2f9d305dd02626b967aa2e86021fba07065df66ce7a7e00ffb9664f150abf",
    "model_config.yaml": "1012fc3f39cb5e90e3f8fbadf7bded31604bfafdce0321d17a7c1a2d3f08b88d",
    "assets/mhr_model.pt": "352e271a6c42729c68554ceaea0c955e866970160c31e35506d782dc0f7377bc",
    "host_adapter_lock": "a506ff07ca3ee26b7089ae8e37cbd67a2b1494a4127175626ff60742f2b51bd6",
    "v3_runtime_lock": "de207f0502299624c266f0325e92cc7c64dca832f6c2239688594237239e7b9f",
    "v3_runner": "54f2d9f8b12daa444531b43ca250ff2134feec951568f75c44594d2a90b85dfb",
    "prior_v2_receipt_file": "b5300145a82139c0b2d34cf97fc572ac250e9dec935cfda21e6f277e9a56eda6",
    "prior_v2_receipt_self": "66c2de6c953fbedc4c53c99c6afdd5f88856e754e46b0afcc78da25bf2707332",
}
EXPECTED_SOURCE_COMMIT = "b5c765a0d89d789985e186d396315e7590887b94"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_self(document: dict) -> str:
    body = {key: value for key, value in document.items() if key != "self_sha256"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def write_receipt(document: dict) -> None:
    document["self_sha256"] = canonical_self(document)
    destination = OUT / "HOST_ADAPTER_RUNTIME_RECEIPT.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)


def command_output(argv: tuple[str, ...]) -> str:
    return subprocess.check_output(argv, text=True, stderr=subprocess.STDOUT).strip()


def numeric_compute_processes() -> list[str]:
    raw = command_output(
        ("nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits")
    )
    return [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and line.split(",", 1)[0].strip().isdigit()
    ]


def validate_closure() -> dict[str, str]:
    paths = {
        "image": IMAGE,
        "model.ckpt": CHECKPOINT_ROOT / "model.ckpt",
        "model_config.yaml": CHECKPOINT_ROOT / "model_config.yaml",
        "assets/mhr_model.pt": CHECKPOINT_ROOT / "assets" / "mhr_model.pt",
        "host_adapter_lock": ROOT / "env/sam3d_body_runtime_v4_warmup.lock.json",
        "v3_runtime_lock": ROOT / "env/sam3d_body_repeatability_v3_runtime.lock.json",
        "v3_runner": ROOT / "tools/run_sam3d_body_repeatability_v3.py",
        "prior_v2_receipt_file": ROOT
        / "runtime_artifacts/sam3d_body_v3_host_adapter_runtime_20260725T162500Z_v2_numeric_pid_preflight/HOST_ADAPTER_RUNTIME_RECEIPT.json",
    }
    if not SOURCE_ROOT.is_dir() or not (SOURCE_ROOT / ".git").exists():
        raise RuntimeError("governed SAM3D source tree is unavailable")
    observed: dict[str, str] = {}
    for name, path in paths.items():
        if not path.is_file():
            raise RuntimeError(f"governed SAM3D input missing: {name}")
        observed[name] = sha256(path)
        if observed[name] != EXPECTED_SHA256[name]:
            raise RuntimeError(f"governed SAM3D input hash drift: {name}")
    source_commit = command_output(("git", "-C", str(SOURCE_ROOT), "rev-parse", "HEAD"))
    source_status = command_output(("git", "-C", str(SOURCE_ROOT), "status", "--porcelain"))
    if source_commit != EXPECTED_SOURCE_COMMIT or source_status:
        raise RuntimeError("governed SAM3D source tree drift")
    observed["source_commit"] = source_commit
    return observed


def main() -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    payload: dict = {
        "artifact_type": "sam3d_body_v3_host_adapter_runtime_receipt.v1",
        "started_at_utc": started_at,
        "scope": "one immutable fixture/box through a fresh V3 host-adapter binding with explicit existing /workspace/models source/checkpoint roots; one non-evaluated warm-up and two exact measured outputs only",
        "execution_identity": {
            "pod_id": "68psfqtaogg7s7",
            "pod_name": "vitreous_beige_centipede",
            "gpu_requirement": "NVIDIA RTX 6000 Ada Generation",
            "network_volume_id": "o9qv2ld91c",
            "volume_mount": "/workspace",
        },
        "authority": {
            "provider_lifecycle_state": "installed_unqualified",
            "may_author_gold": False,
            "may_promote_provider": False,
            "provider_matrix_or_registry_changed": False,
        },
        "bindings": {
            "image": str(IMAGE.relative_to(ROOT)),
            "bbox_xyxy": list(BBOX),
            "source_root": str(SOURCE_ROOT),
            "checkpoint_root": str(CHECKPOINT_ROOT),
            "supersedes": {
                "path": "runtime_artifacts/sam3d_body_v3_host_adapter_runtime_20260725T162500Z_v2_numeric_pid_preflight/HOST_ADAPTER_RUNTIME_RECEIPT.json",
                "file_sha256": EXPECTED_SHA256["prior_v2_receipt_file"],
                "self_sha256": EXPECTED_SHA256["prior_v2_receipt_self"],
                "reason": "V2 preserved its terminal failure; V3 corrects only the root binding to the already hash-verified /workspace/models assets.",
            },
        },
    }
    try:
        closure = validate_closure()
        gpu_csv = command_output(
            ("nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits")
        )
        gpu_rows = [row for row in gpu_csv.splitlines() if row.strip()]
        processes = numeric_compute_processes()
        payload["preflight"] = {
            "gpu_csv": gpu_csv,
            "numeric_compute_processes": processes,
            "closure_sha256": closure,
        }
        if len(gpu_rows) != 1 or not gpu_rows[0].startswith("NVIDIA RTX 6000 Ada Generation,"):
            raise RuntimeError("host-adapter requires exactly one RTX 6000 Ada")
        if processes:
            raise RuntimeError("host-adapter admission denied: numeric compute process present")
        backend = Sam3dBodyV3RunpodBackend(
            source_root=SOURCE_ROOT,
            checkpoint_root=CHECKPOINT_ROOT,
        )
        provider = Sam3dBodyGeometryProvider(backend, identity=backend.identity)
        result = provider.infer_geometry(
            IMAGE,
            person_box=BoxProposal(BBOX, 0.99, "person", "sam3d_body_v3_workspace_models_bus_person"),
        )
        evidence = result["provenance"]["runtime_evidence"]
        payload["result"] = {
            "provider": result["provider"],
            "person_instance_key": result["person_instance_key"],
            "requested_bbox_xyxy": list(result["requested_bbox_xyxy"]),
            "observed_bbox_xyxy": list(result["observed_bbox_xyxy"]),
            "geometry_output_sha256": result["provenance"]["output_sha256"],
            "runtime_evidence": evidence,
            "postrun_gpu_csv": command_output(
                ("nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits")
            ),
        }
        if (
            evidence.get("deterministic") is not True
            or evidence.get("measured_repeats") != 2
            or evidence.get("warmup", {}).get("evaluated_for_repeatability") is not False
            or evidence.get("repeat_comparison", {}).get("all_arrays_exact") is not True
            or evidence.get("authority") != "shadow_geometry_challenger_only"
            or result["provenance"].get("may_author_gold") is not False
        ):
            raise RuntimeError("host-adapter returned insufficient strict-repeatability evidence")
        payload["status"] = "RUNTIME_PASS_BOUNDED_HOST_ADAPTER_WORKSPACE_MODELS_CLOSURE"
        payload["next_safe_action"] = "Retain installed-unqualified shadow-only status; no provider promotion, matrix update, production routing, gold, or certification authority follows from this receipt."
        payload["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_receipt(payload)
        print(json.dumps({"status": payload["status"], "self_sha256": payload["self_sha256"]}, sort_keys=True))
        return 0
    except Exception as exc:
        payload["status"] = "RUNTIME_FAIL_HOST_ADAPTER_WORKSPACE_MODELS_CLOSURE"
        payload["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        payload["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_receipt(payload)
        print(json.dumps({"status": payload["status"], "self_sha256": payload["self_sha256"]}, sort_keys=True))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
