"""Seal the 2026-07-20 gold-stream wave: Docker restored, live smokes, honest gold=0."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = (
    REPO / "qa" / "live_verification" / "autonomous_gold_stream_docker_restored_20260720T0300.json"
)


def main() -> int:
    evidence: dict = {
        "artifact_type": "autonomous_gold_stream_docker_restored_wave",
        "schema_version": "1.0.0",
        "authority": "autonomous_certified_gold_profile",
        "branch": "codex/maskfactory-runtime-implementation",
        "project_head_at_authoring": "92a463ce35c8aac4c6751485f1a8ed797422f2cd",
        "recorded_at": "2026-07-20T08:03:00Z",
        "stream": (
            "autonomous_gold_candidate_population_and_certification: waited/polled for the "
            "sibling Docker restore, then live-probed and ran inference via restored "
            "nuclio/existing containers (no docker image build)."
        ),
        "wait_and_poll": {
            "mandate": "Zero human waits; reprobe ~30-60s up to ~10 min until Docker+CVAT+nuclio up.",
            "poller": "runtime_artifacts/_poll_docker_ready.ps1",
            "result": (
                "Docker engine transitioned DOWN->UP during the poll window (docker-desktop WSL "
                "distro Running; full production CVAT stack + nuclio-nuclio-pth-sam2 healthy)."
            ),
        },
        "live_runtime_probe": {
            "docker_engine": "UP (docker ps returns full stack; cvat_server + nuclio healthy)",
            "cvat_localhost_8080": "UP 2.24.0 (production)",
            "cvat269": "UP (migration rehearsal only; not used)",
            "nuclio_pth_sam2": "healthy; function name 'Segment Anything 2.1 (CPU)' (CPU variant)",
            "ollama_127_0_0_1_11434": "UP 0.32.1 (VLM critic only; not a segmentation family)",
            "gpu": "RTX 5060 8151 MiB total; ~1203 MiB free (DAZ + Ollama + Cursor resident)",
            "wsl_ubuntu_2204": "Stopped (ext4 VHD corrupt per prior waves; needs elevated e2fsck)",
            "host_torch": "2.12.1+cpu; torch.cuda.is_available()=False",
            "docker_images_relevant": [
                "cvat.pth.sam2:latest (8.08GB)",
                "cvat/server:v2.24.0 (2.31GB)",
                "cvat/server:v2.69.0 (2.65GB)",
                "nvidia/cuda:12.8.0-base-ubuntu22.04 (402MB)",
            ],
            "maskfactory_gpu_container_built": False,
        },
        "live_smokes": {
            "cvat_sam2": {
                "tool": "tools/smoke_cvat_sam2.py",
                "status": "PASS",
                "report": "qa/reports/cvat_sam2_smoke.json",
                "latency_seconds": 54.461,
                "foreground_pixels": 21491,
                "note": "First invocation 504 (cold start under tight VRAM); warm retry PASS.",
                "proof_tier": "RUNTIME_PASS_BOUNDED",
            },
            "ollama_vlm": {
                "tool": "tools/smoke_ollama_vlm.py",
                "status": "PASS",
                "report": "qa/reports/ollama_vlm_smoke.json",
                "model": "qwen2.5vl:7b",
                "verdict": "pass",
                "proof_tier": "RUNTIME_PASS_BOUNDED",
            },
        },
        "gold_count": {
            "autonomous_certified_gold": 0,
            "human_anchor_gold": 0,
            "machine_verified_candidate": 0,
        },
        "admission_result": {
            "tool": "tools/build_autonomous_gold_admission.py",
            "invocation": "--label torso --context solo --pipeline-fingerprint gold_stream_docker_up_20260720T030031",
            "status": "insufficient_autonomous_verified_samples",
            "certificate_passed": False,
            "machine_verified_candidate_count": 0,
            "lifecycle_sidecars_seen": 0,
            "output_evidence": "qa/live_verification/autonomous_gold_admission_20260720T030031.json",
            "output_self_sha256": "37aec15f2c1f2605293d7371376a5c7a2885513b4887fe9caef56d73a1605ed7",
        },
        "family_availability_analysis": {
            "independent_segmentation_families_required": 3,
            "independent_segmentation_families_available_for_autonomous_pipeline": 0,
            "why": (
                "The autonomous S00-S15 production pipeline resolves its segmentation families "
                "(S02 silhouette/BiRefNet, S03 parsing/SCHP, S04 pose, S06 openvocab/GroundingDINO, "
                "S07 SAM2 via WslSam2Provider, S08.5 densepose) through WSL/CUDA providers. "
                "WSL Ubuntu-22.04 is Stopped/corrupt, host torch is CPU-only, and no "
                "maskfactory/train:cu128 or serve:cu128 GPU container is built. The restored "
                "nuclio pth-sam2 is a CPU SAM2.1 CVAT-interactive assistor (human-in-loop), NOT the "
                "autonomous S07 provider, so it cannot by itself satisfy the >=3 independent-family "
                "consensus requirement. GPU free VRAM (~1.2 GiB) is also insufficient to run three "
                "concurrent segmentation families."
            ),
        },
        "blocker_root_cause": (
            "machine_verified_candidate requires a multi-provider tournament with >=3 INDEPENDENT "
            "model families producing consensus masks, each family needing a CUDA runtime via WSL "
            "or a GPU container. This wave restored the CVAT/nuclio (CPU) + Ollama runtime and "
            "proved them live, but the >=3-family GPU segmentation runtime is still unavailable "
            "(WSL corrupt; no GPU container; VRAM contended). Zero genuine candidates can be "
            "produced and fabrication is forbidden."
        ),
        "next_agent_step": (
            "Either (a) build maskfactory/train:cu128 (docker/Dockerfile.train) with sufficient C:/WSL2 "
            "headroom and free VRAM, then run the multi-provider tournament on MaskedWarehouse/reference/DAZ "
            "sources to write machine_verified_candidate sidecars under runs/ and re-run "
            "build_autonomous_gold_admission --corpus; or (b) repair Ubuntu-22.04 ext4 via an elevated "
            "e2fsck and run the WSL provider families."
        ),
        "multi_agent_coordination": (
            "HEAD advanced (b634c103 -> 92a463ce) during this wave; siblings are actively committing "
            "and hold in-flight working-tree edits. This stream committed only its own evidence via "
            "pathspec, did NOT build docker images (avoid conflicting builds + protect the freshly "
            "restored engine that crashed on a prior torch build under low C: headroom), and left all "
            "sibling edits untouched."
        ),
        "claims_not_established": [
            "autonomous_certified_gold",
            "machine_verified_candidate>0",
            "champions>0",
            "human_anchor_gold",
            "certificate_minted",
            "VISUAL_QA_PASS_BOUNDED",
        ],
        "no_fabricated_samples": True,
        "no_force_registered_champions": True,
        "no_tier_inflation": True,
    }

    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps({"output": str(OUT.relative_to(REPO)), "self_sha256": evidence["self_sha256"]})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
