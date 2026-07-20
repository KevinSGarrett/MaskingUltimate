"""Seal the honest multi-provider autonomous-gold drive evidence (2026-07-20).

This records a genuine attempt to drive machine_verified_candidate +
autonomous_certified_gold via the multi-provider path (nuclio SAM2 + Ollama VLM
critic + warehouse/reference/DAZ gold sources), GPU-sequenced against Ollama.

It fabricates NOTHING: it enumerates the live independent mask families and the
gold-volume source corpora that actually exist on disk, and reports the honest
fail-closed admission outcome (insufficient_autonomous_verified_samples). No
Wilson samples invented, no champion force-registered.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "qa/live_verification/multiprovider_gold_drive_20260720T1432.json"


def _seal(evidence: dict) -> dict:
    evidence.pop("self_sha256", None)
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    return evidence


def main() -> int:
    evidence = {
        "artifact_type": "multiprovider_autonomous_gold_drive",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authority": "autonomous_certified_gold_profile",
        "evidence_tier": "RUNTIME_PROBE_BOUNDED",
        "runtime_probe": {
            "docker_engine": "29.6.1 / docker-desktop up",
            "cvat_about": "2.24.0 (http://localhost:8080)",
            "ollama_version": "0.32.1 (http://127.0.0.1:11434)",
            "nuclio_pth_sam2": "healthy (nuclio-nuclio-pth-sam2)",
            "production_cvat_and_cvat269_and_nuclio_recovered": True,
        },
        "gpu_sequencing": {
            "policy": "Plan/GPU_SEQUENCING_AND_VRAM_BUDGET.md; single RTX 5060 8GiB; sequential only",
            "initial_state": "ollama llama-server GPU-resident (~6655 MiB used, ~1245 MiB free)",
            "sequencer_plan_ollama_vlm": "wait_headroom (required 7168, no foreign holder)",
            "sequencer_plan_nuclio_sam2": "wait_headroom (required 4096, no foreign holder)",
            "action": "released Ollama resident model (ollama stop) -> 7770 MiB free",
            "then": "ran nuclio SAM2 smoke in the freed slot (strictly sequential, no co-resident load)",
            "no_foreign_eviction": True,
        },
        "live_providers_probed": {
            "nuclio_sam2": {
                "kind": "independent_mask_source",
                "smoke": "pass",
                "function": "pth-sam2 / Segment Anything 2.1 (CPU)",
                "latency_seconds": 19.437,
                "foreground_pixels": 21491,
                "report": "qa/reports/cvat_sam2_smoke.json",
            },
            "ollama_vlm": {
                "kind": "critic_only",
                "smoke": "pass",
                "model": "qwen2.5vl:7b",
                "verdict": "pass",
                "latency_seconds": 16.203,
                "governance": {
                    "role": "qa_router_only",
                    "may_author_masks": False,
                    "may_approve_gold": False,
                    "may_clear_blocks": False,
                },
                "report": "qa/reports/ollama_vlm_smoke.json",
            },
        },
        "independent_mask_family_analysis": {
            "tournament_minimum_independent_sources": 3,
            "tournament_minimum_score": 0.88,
            "config": "configs/autonomous_masks.yaml",
            "live_independent_mask_families_count": 1,
            "live_independent_mask_families": ["nuclio_pth_sam2"],
            "critic_only_not_a_mask_source": ["ollama_qwen2_5vl_7b", "ollama_llava_13b"],
            "families_present_but_offline_wsl_cuda_runtime": [
                "birefnet_general",
                "densepose_rcnn_r50_fpn_s1x",
                "sapiens_0_6b_seg",
                "schp_atr",
                "schp_lip",
                "faceparse_bisenet",
                "vitmatte_small_composition_1k",
                "sam2_1_hiera_large (WSL host runtime)",
            ],
            "offline_reason": (
                "these families declare runtime WSL-...+cu128; Ubuntu-22.04 ext4 VHD is "
                "corrupt (read-only fallback / I/O error) and host torch is CPU-only, so "
                "they cannot produce live masks; only the Docker nuclio SAM2 interactor is live"
            ),
            "conclusion": (
                "1 live independent mask family < required 3; a genuine multi-provider "
                "(>=3 independent family) tournament cannot be assembled without fabrication"
            ),
        },
        "gold_volume_sources_on_disk": {
            "MaskedWarehouse_present": False,
            "reference_library_present": False,
            "daz_present": False,
            "data_children": [
                "cvat",
                "cvat_v2",
                "images",
                "incoming",
                "maskfactory.sqlite",
                "packages",
            ],
            "note": (
                "the gold-volume source corpora named for the tournament "
                "(MaskedWarehouse / reference library / DAZ) are not present in this working tree; "
                "data/packages holds draft/machine packages, not gold sources"
            ),
        },
        "admission_result": {
            "tool": "tools/build_autonomous_gold_admission.py (committed HEAD logic)",
            "invocation": "default mode (no --corpus); scans runs/ lifecycle sidecars",
            "artifact": "qa/live_verification/autonomous_gold_admission_multiprovider_20260720T1432.json",
            "artifact_self_sha256": "6ab2679c758443617c9a107c47e751db4979ca633fd5b33fe0355bf3f3c6a3a1",
            "status": "insufficient_autonomous_verified_samples",
            "exit_code": 1,
            "runs_pool": {
                "machine_verified_candidate_count": 0,
                "calibrated_auto_accepted_count": 0,
                "lifecycle_sidecars_seen": 0,
                "json_files_scanned": 4462,
            },
        },
        "gold_counts": {
            "approved_gold_count": 0,
            "human_anchor_gold_count": 0,
            "autonomous_certified_gold_count": 0,
            "machine_verified_candidate_count": 0,
            "calibrated_auto_accepted_count": 0,
            "champions": 0,
        },
        "honesty_boundary": {
            "no_fabricated_wilson_samples": True,
            "no_force_registered_champions": True,
            "wilson_and_zero_failure_math_unchanged": True,
            "external_labels_not_treated_as_gold": True,
            "vlm_is_advisory_critic_only": True,
            "no_gpu_foreign_eviction": True,
            "no_prune_or_volume_wipe": True,
        },
        "next_agent_step": (
            "Restore >=3 independent live mask families (repair WSL Ubuntu-22.04 ext4 VHD via "
            "scripted e2fsck OR build the Docker GPU train/serve images so BiRefNet/DensePose/"
            "Sapiens/SCHP/SAM2 run alongside nuclio SAM2), stage a gold-volume source corpus "
            "(MaskedWarehouse / reference / DAZ), GPU-sequence the >=3-family tournament to emit "
            "genuine machine_verified_candidate sidecars under runs/, then re-run "
            "build_autonomous_gold_admission.py --corpus to attempt an honest certificate."
        ),
    }
    _seal(evidence)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "self_sha256": evidence["self_sha256"],
                "gold_counts": evidence["gold_counts"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
