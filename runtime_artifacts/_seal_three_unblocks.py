"""Seal the three-unblocks execution wave evidence with a canonical self hash."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _head() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
    )
    return out.stdout.strip()


evidence = {
    "artifact_type": "three_unblocks_execution_wave",
    "schema_version": "1.0.0",
    "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "branch": "codex/maskfactory-runtime-implementation",
    "project_head": _head(),
    "authority": [
        "Kevin mandate: FULL AUTONOMY, zero human wait, proof tiers binding, "
        "no champion force-register, no false STATIC/runtime/visual/gold/doctor-green.",
        "Executes the three honest agent-executable unblocks from re-verify HEAD f3dc15a8.",
    ],
    "live_probe": {
        "docker_server": "29.4.3",
        "cvat_about": "http://localhost:8080/api/server/about -> 2.24.0 (production)",
        "ollama_version": "http://127.0.0.1:11434/api/version -> 0.32.1",
        "gpu_container": "docker run --gpus all nvidia/cuda:12.8.0-base nvidia-smi -> "
        "NVIDIA GeForce RTX 5060 Laptop GPU (cap 12,0) proven",
        "wsl_ubuntu_2204": "still corrupt (E_FAIL); Docker container path is the substitute",
    },
    "unblock_1_docker_gpu": {
        "assets_committed": [
            "docker/Dockerfile.serve",
            "docker/Dockerfile.train",
            "docker/compose.gpu.yml",
            "docker/requirements-serve.txt",
            ".dockerignore",
            "tools/smoke_docker_gpu_serve.py",
        ],
        "serve_image": "maskfactory/serve:cu128 (python3.11 + torch/torchvision cu128 + curated "
        "serve/doctor subset + maskfactory --no-deps)",
        "train_image": "maskfactory/train:cu128 (CUDA 12.8 devel; builds mmcv._ext from source "
        "for sm_120 per env/openmmlab_training_stack.lock.json)",
        "gpu_cuda_container_proof": "RUNTIME_PASS_BOUNDED (RTX 5060, cap 12,0, via --gpus all)",
        "serve_smoke_status": "BUILD_FAILED_RESOURCE: the serve image build reached the torch cu128 "
        "install (~7 GiB of torch+CUDA wheels) and the Docker Desktop daemon/buildkit disconnected "
        "('failed to receive status: rpc error: code = Unavailable ... EOF'), i.e. the constrained "
        "WSL2 backend was exhausted by the large install and the engine went down. Docker Desktop was "
        "then RESTARTED and production CVAT 2.24.0 (localhost:8080), nuclio pth-sam2, and Ollama 0.32.1 "
        "were verified restored. The Dockerfile/compose/.dockerignore/smoke assets are correct and "
        "committed. RETRY guidance: raise WSL2 memory/disk headroom (Docker Desktop settings or "
        ".wslconfig), or build with a runtime (not devel) base + prebuilt wheel cache, then run "
        "tools/smoke_docker_gpu_serve.py --serve-image maskfactory/serve:cu128 to seal the "
        "containerized serve RUNTIME_PASS_BOUNDED. Serve-container runtime is NOT claimed.",
        "honesty": "training-doctor full green (mmcv._ext sm_120) NOT claimed; requires the train "
        "image build + registered datasets. GPU container access is genuinely proven.",
    },
    "unblock_2_autonomous_gold": {
        "profile": "configs/autonomy_autonomous_gold_profile.yaml "
        "(profile_sha256 789d9e0af3a72cd8ff5fa4b0229cbcf662a3f904e9b336f6483a2fbfc287c823)",
        "code": "calibration.build_autonomous_gold_certificate + verify_autonomy_certificate "
        "allow_autonomous_profile (default OFF -> zero regression) threaded through run_tournament",
        "authority_replacement": "independent multi-provider agreement + stability + hard-veto QA "
        "REPLACES human-anchor calibration authority; exact one-sided Wilson and zero-failure "
        "bounds are PRESERVED unchanged (not weakened).",
        "tests": "tests/test_autonomous_gold_admission.py 7/7 PASS; autonomy regression 33 PASS; "
        "bridge conformance 18 PASS.",
        "admission_state": "tools/build_autonomous_gold_admission.py default run -> "
        "insufficient_autonomous_verified_samples (0 machine_verified_candidate sidecars in runs/). "
        "Tier IMPLEMENTED + gated; populating it requires the multi-provider tournament in the "
        "Docker GPU container on gold-volume data. No fabrication.",
    },
    "unblock_3_isolated_main_consumer": {
        "tool": "tools/run_isolated_main_consumer.py",
        "checks_all_pass": [
            "isolated_adoption_receipt_signed (isolated-main-consumer-adoption ed25519 key)",
            "isolated_adapter_conformance (accepted)",
            "isolated_signed_journal (3 events + checkpoint, valid)",
            "isolated_failure_control_circuit (outage/timeout/oom/incompatible_authority fail-closed)",
            "isolated_consumer_conformance_harness (accepted; main_adoption_complete=False)",
            "isolated_cross_project_producer_partial (mf_p6_12_05_complete=False)",
        ],
        "authority_kind": "isolated_main_consumer (NOT fixture_authority, NOT real Comfy_UI_Main)",
        "hard_blockers_open": ["MF-P6-11.02", "MF-P6-11.07", "MF-P6-12.05", "MF-P6-12.06"],
        "main_untouched": "C:/Comfy_UI_Main dirty Wave64 branch NOT modified.",
    },
    "claims_not_established": [
        "champions>0",
        "Mode B champion-backed predict/refine RUNTIME_PASS_BOUNDED",
        "training-doctor all-green in container (mmcv._ext sm_120)",
        "human_approved_gold / a minted autonomous_certified_gold certificate",
        "Main adoption receipts / MF-P6-11.02 / 11.07 / 12.05 / 12.06",
        "core_autonomous_runtime complete / PRODUCTION_EVIDENCE_PASS / doctor all-green",
    ],
    "no_open_human_stop_states": True,
}

payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
out = REPO / "qa" / "live_verification" / "three_unblocks_execution_20260720T0530.json"
out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("sealed", evidence["self_sha256"], "->", out.name)
