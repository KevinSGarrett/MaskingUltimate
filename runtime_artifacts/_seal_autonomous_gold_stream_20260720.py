"""Seal the autonomous-gold stream readiness + honest admission evidence.

No tier inflation, no fabricated samples, no force-registered champions.
Records this session's live runtime probe, the abundantly-ready corpus SOURCE
side, and the honest `insufficient_autonomous_verified_samples` admission at HEAD.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qa/live_verification/autonomous_gold_stream_readiness_20260720T0230.json"

mw_datasets = {
    "celebamask_hq": {"images": 30000, "masks": 372767, "role": "face_components"},
    "lapa": {"images": 22168, "masks": 22168, "role": "face_parsing"},
    "lv_mhp_v1": {"images": 4980, "masks": 14969, "role": "multi_person_full_body_parsing"},
    "swimsuit_preview": {"images": 10, "masks": 10, "role": "clothing_body_color_preview"},
    "body_archive": {"images": 175, "masks": 175, "role": "seven_group_body_color"},
}

evidence: dict = {
    "artifact_type": "autonomous_gold_stream_readiness_and_admission",
    "schema_version": "1.0.0",
    "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "authority": "autonomous_certified_gold_profile",
    "stream": (
        "autonomous_gold_candidate_population_and_certification "
        "(build_autonomous_gold_admission path; NOT docker image builds — sibling owns disk/serve/train build)"
    ),
    "branch": "codex/maskfactory-runtime-implementation",
    "project_head_at_authoring": "447b0f9b642e568e54467d592fb3307525810489",
    "no_tier_inflation": True,
    "no_fabricated_samples": True,
    "no_force_registered_champions": True,
    "live_runtime_probe": {
        "docker_engine": (
            "DOWN — com.docker.service Stopped; `docker info`/`docker version` hang >60s; "
            "Docker Desktop relaunched this session but the engine did not come up; "
            "`wsl --list --running` shows no running distributions"
        ),
        "cvat_localhost_8080": "DOWN — connection refused (nuclio SAM2 provider unavailable)",
        "ollama_127_0_0_1_11434": (
            "UP — version 0.32.1 (VLM critic only; NOT one of the >=3 required independent "
            "segmentation model families)"
        ),
        "wsl": (
            "DOWN — no running distributions; Ubuntu-22.04 ext4 VHD corrupt per prior waves; "
            "non-interactive elevation unavailable (e2fsck deferred)"
        ),
        "host_torch": "2.12.1+cpu; torch.cuda.is_available()=False",
        "gpu": "RTX 5060 8 GiB; DAZ + Ollama resident (prior probe ~377 MiB free)",
    },
    "source_readiness": {
        "note": "Corpus SOURCE side is abundantly ready; only the multi-provider RUNTIME blocks production.",
        "maskedwarehouse": {
            "root": "C:\\Comfy_UI_Main\\MaskedWarehouse",
            "present": True,
            "datasets": mw_datasets,
            "total_images": sum(d["images"] for d in mw_datasets.values()),
            "total_masks": sum(d["masks"] for d in mw_datasets.values()),
        },
        "reference_library": {
            "working_db": "C:\\Temp\\MaskFactory_Reference_Library\\reference_working.sqlite",
            "exists": True,
            "bytes": 446554112,
            "exact_representatives": 69398,
            "index_complete": True,
            "index_percent": 100.0,
        },
        "daz_foundation": {
            "root": "F:\\DAZ",
            "root_exists": True,
            "daz_studio_executable_present": True,
            "storage_free_gib": 249.424,
            "acquisition_queue_readable": True,
            "capacity_guard_hash_matched": True,
            "note": (
                "tools/daz_status.py exited nonzero on a live-skipped queue-count check; "
                "foundation roots/executable/storage/capacity-guard checks all PASS"
            ),
        },
    },
    "admission_result": {
        "tool": "tools/build_autonomous_gold_admission.py",
        "mode": "default no-corpus honest state report",
        "invocation": "--label torso --context solo --pipeline-fingerprint autonomous_gold_stream_probe_20260720T022935",
        "output_evidence": "qa/live_verification/autonomous_gold_admission_20260720T022935.json",
        "output_self_sha256": "b76f1564c2ec1b262571b32d8e2eb97341225381e6f0f0d531507ee4f462ab8a",
        "machine_verified_candidate_count": 0,
        "calibrated_auto_accepted_count": 0,
        "lifecycle_sidecars_seen": 0,
        "status": "insufficient_autonomous_verified_samples",
        "certificate_passed": False,
        "exit_code": 1,
    },
    "gold_count": {
        "autonomous_certified_gold": 0,
        "machine_verified_candidate": 0,
        "human_anchor_gold": 0,
    },
    "root_cause": (
        "The autonomous-gold certificate requires machine_verified_candidate lifecycle sidecars "
        "produced by a multi-provider tournament with >=3 INDEPENDENT model families "
        "(profile independent_provider_families_minimum=3; tournament minimum_independent_sources=3) "
        "plus ~>=270 zero-defect samples to clear the 0.01 one-sided Wilson bound. Every segmentation "
        "family (SAM2/SAM3.1, parsing, silhouette, geometry, pose) requires a CUDA runtime via WSL or "
        "Docker/nuclio. This session live-probed all of those DOWN; host torch is CPU-only; only Ollama "
        "(a VLM critic, not a segmentation family) is up. Zero genuine machine_verified_candidate "
        "samples can be produced this session, and fabricating them is forbidden (no tier inflation)."
    ),
    "blocker_is_out_of_my_lane": (
        "Producing the candidates requires the multi-provider tournament in the Docker GPU container / "
        "restored nuclio SAM2 — the disk/serve/train Docker image build lane owned by the sibling stream. "
        "Per directive this stream did NOT run docker build and did NOT edit docker/Dockerfile.*."
    ),
    "advanced_this_session": [
        "Quantified the corpus SOURCE side as abundantly ready: MaskedWarehouse ~57k image/mask pairs "
        "across 5 datasets; reference library 69,398 indexed representatives (100% classified); DAZ "
        "foundation healthy (root/executable/queue/capacity-guard verified, 249 GiB free).",
        "Live-probed the runtime and confirmed the SINGLE remaining blocker is the multi-provider "
        "segmentation runtime (Docker engine / nuclio SAM2 / WSL / CUDA all down); Ollama VLM up.",
        "Re-sealed the honest autonomous-gold admission at HEAD 447b0f9b: gold count 0, "
        "insufficient_autonomous_verified_samples.",
    ],
    "next_agent_step": (
        "Restore the Docker engine (or an elevated WSL e2fsck of Ubuntu-22.04) so nuclio SAM2 + >=2 "
        "additional independent families (parsing / silhouette / geometry) run; execute the multi-provider "
        "tournament on MaskedWarehouse/reference/DAZ sources to write machine_verified_candidate lifecycle "
        "sidecars under runs/; assemble a frozen image-disjoint corpus; re-run "
        "build_autonomous_gold_admission --corpus."
    ),
    "claims_not_established": [
        "autonomous_certified_gold",
        "machine_verified_candidate>0",
        "champions>0",
        "human_anchor_gold",
        "certificate_minted",
    ],
    "multi_agent_coordination": (
        "A sibling stream has in-flight staged/unstaged edits to tracker.json / DASHBOARD.md / phases/P6.md "
        "/ src. tracker.json was NOT modified by this stream (no honest status transition — gold=0). "
        "Committed only this stream's evidence via pathspec to avoid clobbering sibling work; coordinated "
        "via this evidence file."
    ),
}

payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(
    json.dumps(
        {
            "output": str(OUT.relative_to(ROOT)).replace("\\", "/"),
            "self_sha256": evidence["self_sha256"],
            "gold_count": evidence["gold_count"],
            "status": evidence["admission_result"]["status"],
        },
        indent=2,
    )
)
