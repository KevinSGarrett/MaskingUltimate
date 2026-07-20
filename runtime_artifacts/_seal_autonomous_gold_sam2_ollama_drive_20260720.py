"""Seal the honest nuclio-SAM2 + Ollama autonomous-gold drive (2026-07-20).

Records a genuine attempt to drive machine_verified_candidate via the live
nuclio SAM2 interactor + Ollama VLM critic, GPU-sequenced, with F:/ gold-volume
roots read-when-present only. Fabricates nothing.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "qa/live_verification/autonomous_gold_sam2_ollama_drive_20260720T1520.json"
ADMISSION = (
    REPO_ROOT / "qa/live_verification/autonomous_gold_admission_sam2_ollama_20260720T1017.json"
)
GPU_SEQ = REPO_ROOT / "qa/live_verification/gpu_sequence_sam2_20260720T1445.json"


def _seal(evidence: dict) -> dict:
    evidence.pop("self_sha256", None)
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    return evidence


def _sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    admission = json.loads(ADMISSION.read_text(encoding="utf-8")) if ADMISSION.is_file() else {}
    pool = admission.get("autonomous_verified_pool") or {}
    gold_sources = admission.get("gold_volume_sources") or {}

    evidence = {
        "artifact_type": "autonomous_gold_sam2_ollama_drive",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authority": "autonomous_certified_gold_profile",
        "evidence_tier": "RUNTIME_PROBE_BOUNDED",
        "project_head_at_seal": "6b1ad4ef",
        "drive_path": {
            "mask_source": "nuclio_pth_sam2",
            "critic": "ollama_qwen2_5vl_7b",
            "gpu_policy": "Plan/GPU_SEQUENCING_AND_VRAM_BUDGET.md; sequential only; no foreign eviction",
            "warehouse_policy": "F: read-when-present only; never fabricate F:\\MaskedWarehouse",
        },
        "runtime_probe_start": {
            "docker_engine": "29.6.1 / docker-desktop UP (39 containers; nuclio-nuclio-pth-sam2 healthy)",
            "cvat_about": "2.24.0",
            "ollama_version": "0.32.1",
            "c_free_gib": 91.23,
            "f_free_gib": 181.21,
            "gpu_free_mib": 7858,
        },
        "gpu_sequencing": {
            "artifact": str(GPU_SEQ.relative_to(REPO_ROOT)).replace("\\", "/"),
            "artifact_sha256": _sha(GPU_SEQ),
            "consumer": "nuclio-sam2",
            "decision": "run_now",
            "baseline_free_mib": 7782,
            "reclaimed": ["ollama-vlm", "ollama-text"],
            "no_foreign_eviction": True,
        },
        "live_providers_probed": {
            "nuclio_sam2": {
                "kind": "independent_mask_source",
                "preflight": "listed as interactor via /api/lambda/functions (200)",
                "smoke_attempts": [
                    {
                        "at": "2026-07-20T14:46:15Z+",
                        "result": "fail",
                        "http": 503,
                        "url": "POST /api/lambda/functions/pth-sam2",
                        "note": "Service Unavailable after GPU-sequence; function listed, inference rejected",
                    },
                    {
                        "at": "2026-07-20T14:47:30Z",
                        "result": "fail",
                        "http": 503,
                        "note": "warm retry; django.request Service Unavailable",
                    },
                    {
                        "at": "2026-07-20T14:47:48Z",
                        "result": "fail",
                        "http": 503,
                        "note": "second warm retry",
                    },
                ],
                "smoke_result": "fail_503",
                "recovery_attempt": (
                    "docker restart nuclio-nuclio-pth-sam2 -> Docker Desktop EOF / named-pipe vanish; "
                    "engine DOWN. Subsequent Docker Desktop relaunches (incl. wsl --shutdown) did not "
                    "restore dockerDesktopLinuxEngine within bounded waits (6+ min)."
                ),
                "prior_same_day_pass": {
                    "report": "qa/reports/cvat_sam2_smoke.json",
                    "measured_at": "2026-07-20T14:33:06.362037+00:00",
                    "latency_seconds": 19.437,
                    "foreground_pixels": 21491,
                    "note": "stale prior PASS left on disk; this wave did not re-achieve PASS",
                },
            },
            "ollama_vlm": {
                "kind": "critic_only",
                "smoke": "pass",
                "model": "qwen2.5vl:7b",
                "verdict": "pass",
                "confidence": 1,
                "latency_seconds": 123.595,
                "governance": {
                    "role": "qa_router_only",
                    "may_author_masks": False,
                    "may_approve_gold": False,
                    "may_clear_blocks": False,
                },
                "tool": "tools/smoke_ollama_vlm.py",
            },
        },
        "independent_mask_family_analysis": {
            "tournament_minimum_independent_sources": 3,
            "this_wave_live_via_sam2_ollama_path": {
                "mask_families": 0,
                "note": (
                    "nuclio SAM2 was the intended live mask family for this drive but smoke failed "
                    "503 then engine DOWN; Ollama remains critic-only and is not a mask family"
                ),
            },
            "critic_only_not_a_mask_source": ["ollama_qwen2_5vl_7b", "ollama_llava_13b"],
            "sibling_host_cuda_families_online_elsewhere": {
                "evidence": "qa/live_verification/families_online_gold_drive_20260720T0957.json",
                "claimed_families": ["faceparse_bisenet", "birefnet_general", "schp_atr"],
                "note": "sibling stream; not re-claimed or re-run by this SAM2+Ollama drive",
            },
            "conclusion": (
                "This SAM2+Ollama drive cannot honestly emit machine_verified_candidate sidecars: "
                "SAM2 smoke failed and Docker engine is DOWN; Ollama cannot author masks; "
                "no Wilson samples fabricated."
            ),
        },
        "gold_volume_sources_read_when_present": {
            "policy": "read-when-present only; F:\\MaskedWarehouse absent is recorded as absent",
            "admission_embedded": True,
            "all_primary_sources_present": gold_sources.get("all_primary_sources_present"),
            "selected_roots": gold_sources.get("selected_roots"),
            "f_maskedwarehouse_present": False,
            "maskedwarehouse_selected": "C:\\Comfy_UI_Main\\MaskedWarehouse",
            "inventory_images": 57333,
            "inventory_masks": 410089,
            "inventory_sources": 5,
            "removable_drive_letters_present": gold_sources.get("removable_drive_letters_present"),
            "claim_boundary": gold_sources.get("claim_boundary"),
        },
        "admission_result": {
            "tool": "tools/build_autonomous_gold_admission.py",
            "artifact": str(ADMISSION.relative_to(REPO_ROOT)).replace("\\", "/"),
            "artifact_self_sha256": admission.get("self_sha256"),
            "status": admission.get("status"),
            "certificate_passed": admission.get("certificate_passed"),
            "exit_code": 1,
            "runs_pool": {
                "machine_verified_candidate_count": pool.get(
                    "machine_verified_candidate_count", 0
                ),
                "calibrated_auto_accepted_count": pool.get(
                    "calibrated_auto_accepted_count", 0
                ),
                "lifecycle_sidecars_seen": pool.get("lifecycle_sidecars_seen", 0),
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
        "runtime_probe_end": {
            "docker_engine": "DOWN (npipe dockerDesktopLinuxEngine missing)",
            "cvat_about_http": "connection_refused / unavailable",
            "ollama_version": "0.32.1 UP",
            "c_free_gib": 33.56,
            "f_free_gib": 127.63,
            "note": (
                "C: free collapsed during Docker VHDX recovery flap after SAM2 container restart "
                "attempt; no prune/volume wipe performed"
            ),
        },
        "honesty_boundary": {
            "no_fabricated_wilson_samples": True,
            "no_force_registered_champions": True,
            "wilson_and_zero_failure_math_unchanged": True,
            "external_labels_not_treated_as_gold": True,
            "vlm_is_advisory_critic_only": True,
            "f_warehouse_not_fabricated": True,
            "no_gpu_foreign_eviction": True,
            "no_prune_or_volume_wipe": True,
            "sam2_fail_not_hidden": True,
        },
        "next_agent_step": (
            "Restore Docker engine + CVAT/nuclio SAM2 (after C: headroom improves), GPU-sequence "
            "SAM2 smoke to PASS, then run the >=3-family host-CUDA tournament "
            "(faceparse/birefnet/schp per sibling families_online evidence) on gold-volume sources "
            "to emit genuine machine_verified_candidate sidecars under runs/, then "
            "build_autonomous_gold_admission.py --corpus."
        ),
    }
    _seal(evidence)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(OUTPUT.relative_to(REPO_ROOT)).replace("\\", "/"),
                "self_sha256": evidence["self_sha256"],
                "gold_counts": evidence["gold_counts"],
                "admission_status": evidence["admission_result"]["status"],
                "sam2_smoke": evidence["live_providers_probed"]["nuclio_sam2"]["smoke_result"],
                "ollama_smoke": evidence["live_providers_probed"]["ollama_vlm"]["smoke"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
