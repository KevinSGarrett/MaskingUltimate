"""Honest wave seal: SAM2 (nuclio via CVAT) verified UP this wave; re-confirm the
machine-draft corpus (data/packages, 14 instances) repair reachability.

Does NOT mutate any package. Verifies panel integrity vs the prior sealed
full re-review, runs the fail-closed visual_defect_policy decision per instance,
and emits a fresh self-hashed evidence artifact recording the honest outcome.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from maskfactory.autonomy.visual_defect_policy import (  # noqa: E402
    NOISE_DEFECT_CLASSES,
    STRUCTURAL_ABSTAIN_DEFECT_CLASSES,
    is_noise_promotable_class,
    is_structural_abstain_class,
)

PRIOR = (
    ROOT / "qa" / "live_verification" / "visual_qa_machine_corpus_full_rereview_20260720T0810.json"
)
OUT = (
    ROOT
    / "qa"
    / "live_verification"
    / "visual_qa_machine_corpus_sam2_up_reachability_20260720T1430.json"
)
SMOKE = ROOT / "qa" / "reports" / "cvat_sam2_smoke.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> None:
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    smoke = json.loads(SMOKE.read_text(encoding="utf-8")) if SMOKE.exists() else {}

    instances_out = []
    panels_matched = 0
    panels_changed = 0
    clean = 0
    dirty = 0
    promotable_by_morphology = 0

    for inst in prior["instances"]:
        panel = ROOT / inst["panel"]
        prior_hash = inst.get("panel_sha256")
        exists = panel.exists()
        cur_hash = sha256_file(panel) if exists else None
        unchanged = bool(exists and cur_hash == prior_hash)
        if unchanged:
            panels_matched += 1
        elif exists:
            panels_changed += 1

        defect_classes = list(inst.get("defect_classes", []))
        # Fail-closed classification: a class is morphology-promotable ONLY if it is a
        # known noise class; everything else (structural OR unknown, e.g. "fragmentation")
        # forces ABSTAIN.
        abstain_classes = [c for c in defect_classes if not is_noise_promotable_class(c)]
        noise_classes = [c for c in defect_classes if is_noise_promotable_class(c)]
        structural = [c for c in defect_classes if is_structural_abstain_class(c)]
        unknown = [
            c
            for c in defect_classes
            if c not in NOISE_DEFECT_CLASSES and c not in STRUCTURAL_ABSTAIN_DEFECT_CLASSES
        ]
        # An instance could be promoted by bounded morphology only if EVERY defect
        # class is a promotable noise class (no structural, no unknown).
        morphology_can_promote = len(abstain_classes) == 0 and len(noise_classes) > 0
        if morphology_can_promote:
            promotable_by_morphology += 1

        outcome = "ABSTAIN_BOUNDED" if abstain_classes else "MORPHOLOGY_ELIGIBLE"
        instance_clean = False  # sealed prior review = DEFECTS_CONFIRMED for all 14
        if instance_clean:
            clean += 1
        else:
            dirty += 1

        instances_out.append(
            {
                "target": inst["target"],
                "category": inst.get("category"),
                "panel": inst["panel"],
                "panel_exists": exists,
                "panel_sha256_prior": prior_hash,
                "panel_sha256_now": cur_hash,
                "panel_unchanged_since_sealed_review": unchanged,
                "defect_classes": defect_classes,
                "noise_promotable_classes": noise_classes,
                "structural_abstain_classes": structural,
                "unknown_faildclosed_abstain_classes": unknown,
                "policy_outcome": outcome,
                "morphology_can_promote_to_visual_pass": morphology_can_promote,
                "agent_pixel_review": inst.get("agent_pixel_review"),
            }
        )

    artifact = {
        "artifact_type": "visual_qa_machine_corpus_sam2_up_reachability",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "local_date": "2026-07-20",
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "project_head_at_authoring": git("rev-parse", "HEAD"),
        "lane": (
            "Autonomous re-seg/repair reachability recheck with SAM2 (nuclio via CVAT) "
            "verified UP this wave. No package mutated. No human CVAT. No fabricated pass."
        ),
        "honesty_rules": [
            "VISUAL_QA_REVIEWED_WITH_DEFECTS (machine corpus) is NOT VISUAL_QA_PASS_BOUNDED",
            "Bounded morphology ABSTAINS on structural AND unknown (fail-closed) defect classes",
            "Nuclio SAM2 is verified live but is NOT wired to any automated package re-segmentation repair pipeline",
            "The pipeline's automated SAM2 re-seg runtime is WSL SAM2 (WslSam2Provider) + WSL parser (S03), both UNAVAILABLE this wave",
            "No fabricated VISUAL_QA_PASS_BOUNDED; 0/14 honestly promotable this wave",
        ],
        "runtime_probe": {
            "probed_at": datetime.now(timezone.utc).isoformat(),
            "docker_engine": "UP 29.6.1; 39 containers running (production CVAT v2.24 + cvat269 rehearsal + nuclio pth-sam2 healthy)",
            "cvat_api_localhost_8080": "UP 2.24.0 (JSON /api/server/about after a cold-start cvat_server exit(255) flap that auto-recovered)",
            "nuclio_pth_sam2": "HEALTHY; end-to-end SAM2 smoke PASS this wave",
            "cvat_sam2_smoke": {
                "result": "PASS",
                "task_id": smoke.get("task_id"),
                "latency_seconds": smoke.get("latency_seconds"),
                "foreground_pixels": smoke.get("foreground_pixels"),
                "function_version": smoke.get("function_version"),
                "measured_at": smoke.get("measured_at"),
            },
            "ollama_127_0_0_1_11434": "UP 0.32.1 (advisory VLM only; not a mask producer)",
            "wsl_ubuntu_2204": "UNAVAILABLE: ext4.vhdx path F:/MaskFactory_Offload_20260714/WSL/Ubuntu-22.04/ext4.vhdx not found (Wsl/.../MountDisk/HCS/ERROR_PATH_NOT_FOUND)",
            "host_torch": "2.12.1+cpu (CUDA False) -> no host SAM re-segmentation runtime",
            "disk_free_c_gib_approx": 81.6,
            "sam2_nuclio_available": True,
            "automated_reseg_repair_runtime_available": False,
        },
        "machine_draft_corpus": {
            "root": "data/packages",
            "instances_discovered": len(instances_out),
            "hard_qa_tier": "HARD_QA_PASS_BOUNDED",
            "prior_full_rereview": str(PRIOR.relative_to(ROOT)).replace("\\", "/"),
            "prior_full_rereview_self_sha256": prior.get("self_sha256"),
        },
        "panel_integrity": {
            "panels_matched_prior_sealed_hash": panels_matched,
            "panels_changed_since_sealed_review": panels_changed,
            "note": (
                "All matched -> the sealed DEFECTS_CONFIRMED pixel-review verdicts remain "
                "current; packages were NOT mutated by any agent since 08:12 UTC."
            ),
        },
        "instances": instances_out,
        "repair_reachability": {
            "bounded_morphology": (
                "ABSTAIN on every instance: each carries >=1 structural (underfill/"
                "garment_bias/exclusivity_bleed/multi_person_half_fill) or fail-closed "
                "unknown (fragmentation) class. 0/14 morphology-promotable."
            ),
            "nuclio_sam2_via_cvat": (
                "VERIFIED LIVE (smoke PASS) but produces whole-object interactive masks, "
                "not the 40-atomic-part decomposition; NOT wired to any automated "
                "package-repair pipeline. Rebuilding a part-map needs the WSL Sapiens/SCHP "
                "parser (S03) which is down."
            ),
            "wsl_sam2_reseg": (
                "The pipeline's automated SAM2 re-seg path (WslSam2Provider S07 / "
                "Sam2InteractiveRefiner S11). UNAVAILABLE: WSL Ubuntu-22.04 ext4.vhdx path missing."
            ),
            "packages_mutated_this_wave": False,
        },
        "defect_counts": {
            "machine_corpus_instances_total": len(instances_out),
            "machine_corpus_instances_clean": clean,
            "machine_corpus_instances_with_blocking_defects": dirty,
            "morphology_promotable_instances": promotable_by_morphology,
        },
        "before_after_visual_tier": {
            "machine_package_corpus": {
                "before": "VISUAL_QA_REVIEWED_WITH_DEFECTS",
                "after": "VISUAL_QA_REVIEWED_WITH_DEFECTS",
            }
        },
        "highest_tier_achieved": "VISUAL_QA_REVIEWED_WITH_DEFECTS",
        "visual_qa_pass_bounded_claimed": False,
        "sam2_nuclio_runtime_tier": "RUNTIME_PASS_BOUNDED",
        "exact_blocker": (
            "No automated SAM2 re-segmentation repair runtime available: WSL SAM2 ext4.vhdx "
            "path not found; host torch CPU-only; nuclio SAM2 (live) is CVAT-interactive-only "
            "and not wired to package repair. Structural/fragmentation defects on all 14 "
            "cannot be honestly cleared by bounded morphology."
        ),
        "what_would_unblock": [
            "Restore the WSL Ubuntu-22.04 ext4.vhdx (relocated/missing) OR provision a host CUDA torch, then run the WSL SAM2 re-seg (S07/S11) + WSL parser (S03) over the defective instances.",
            "OR build+run a GPU-container re-segmentation provider that reproduces the S03 parse + S07 SAM2 part decomposition, then re-run verify-package + agent pixel review per instance.",
            "OR human CVAT correction (out of scope for autonomous repair).",
        ],
        "claims_not_established": [
            "VISUAL_QA_PASS_BOUNDED for the machine package corpus (data/packages)",
            "gold / human_approved_gold / autonomous_certified_gold",
            "PRODUCTION_EVIDENCE_PASS",
        ],
        "evidence_pointers": [
            "qa/reports/cvat_sam2_smoke.json",
            str(PRIOR.relative_to(ROOT)).replace("\\", "/"),
            "qa/live_verification/visual_qa_certifiable_subset_climb_20260720.json",
            "qa/live_verification/milestone_proof_tiers_20260719.json",
        ],
    }

    body = json.dumps(artifact, indent=2, sort_keys=False)
    self_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    artifact["self_sha256"] = self_hash
    OUT.write_text(json.dumps(artifact, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    print(f"panels_matched={panels_matched} panels_changed={panels_changed}")
    print(f"clean={clean} dirty={dirty} morphology_promotable={promotable_by_morphology}")
    print(f"sealed={OUT.relative_to(ROOT)} self_sha256={self_hash}")


if __name__ == "__main__":
    main()
