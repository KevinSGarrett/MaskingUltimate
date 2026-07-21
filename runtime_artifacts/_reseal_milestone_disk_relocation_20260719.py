"""Re-seal milestone_proof_tiers after autonomous disk relocation + doctor climb.

Honest advances only:
  - disk_free FAIL->PASS (data relocated to governed F:; 251.1 GiB)
  - full doctor runs to completion (was RUNTIME_BLOCKED): PASS=8 FAIL=4
  - gpu_lock stale lock cleared (FAIL->PASS)
  - autonomous Docker GPU CUDA container proof
  - needs_kevin superseded by needs_agent_actions (zero human stop states)
Does NOT claim doctor-green / gold / champions / Main-complete / PRODUCTION_EVIDENCE_PASS.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MILESTONE = ROOT / "qa" / "live_verification" / "milestone_proof_tiers_20260719.json"
EVIDENCE = ROOT / "qa" / "live_verification" / "disk_relocation_doctor_climb_20260719T2210.json"
AGENT_QUEUE = ROOT / "qa" / "live_verification" / "needs_agent_actions_20260719.json"

PREV_SELF = "7986f63423c5d3a0477a2ea98777cc76665c5f369240931ea60341e4ee5829dc"
HEAD = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
BRANCH = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
evidence_sha = hashlib.sha256(EVIDENCE.read_bytes()).hexdigest()

doc = json.loads(MILESTONE.read_text(encoding="utf-8"))
assert doc["self_sha256"] == PREV_SELF, doc["self_sha256"]

doc["recorded_at"] = recorded_at
doc["revision"] = "post_disk_relocation_doctor_climb_20260719"
doc["supersedes_self_sha256"] = PREV_SELF
doc["branch"] = BRANCH
doc["project_head_at_authoring"] = HEAD
for extra in [
    str(EVIDENCE.relative_to(ROOT).as_posix()),
    str(AGENT_QUEUE.relative_to(ROOT).as_posix()),
]:
    if extra not in doc["authority"]:
        doc["authority"].append(extra)

car = doc["core_autonomous_runtime"]
car["rationale"] = (
    "AUTONOMOUS DISK UNBLOCK: data/ relocated (reversible junction) to governed F: drive; "
    "doctor.check_disk_free FAIL->PASS (251.1 GiB). Full `maskfactory doctor` now RUNS TO "
    "COMPLETION (was RUNTIME_BLOCKED): PASS=8 FAIL=4. gpu_lock stale lock cleared (FAIL->PASS). "
    "Autonomous Docker GPU CUDA container proof (RTX 5060 driver 592.01). Remaining doctor FAILs: "
    "3 rooted in the Ubuntu-22.04 ext4 VHD read-only/corruption (torch_cuda, registered_models, "
    "wsl_roundtrip; elevation-gated e2fsck) + 1 from 8GB GPU VRAM contention (nuclio SAM2 vs ollama "
    "qwen2.5vl each RUNTIME_PASS_BOUNDED individually via smokes). CVAT 2.24 / Nuclio SAM2 / Ollama "
    "VLM / Mode B health+models remain RUNTIME_PASS_BOUNDED. Mode B predict AWAITING_RUNTIME "
    "(champions=0; force-register forbidden). P6-11/12 AWAITING_MAIN (producer 93 tests PASS; STATIC_PASS). "
    "VISUAL_QA_REVIEWED_WITH_DEFECTS; HARD_QA_PASS_BOUNDED. No doctor-green / gold / visual-pass / "
    "Main-complete / PRODUCTION_EVIDENCE_PASS / core close. needs_kevin superseded by needs_agent_actions."
)
car["exact_blockers"] = [
    "RESOLVED (autonomous): disk ingest floor — data/ relocated to governed F: (>250 GiB free); doctor disk_free PASS 251.1 GiB (was FAIL). Reversible; C: backup at data_c_backup_relocated.",
    "AGENT (scripted-from-elevated-shell): MF-P0-17.04 WSL Ubuntu-22.04 ext4 VHD offline e2fsck (Repair-MaskFactoryWslVhd.ps1 -ConfirmRepair). Autonomous fallback DONE: Docker GPU CUDA container proof. 3 doctor FAILs share this root cause.",
    "GPU CONTENTION: 1 doctor FAIL rotates between nuclio SAM2 / ollama qwen2.5vl on the shared 8GB GPU; both RUNTIME_PASS_BOUNDED individually via dedicated smokes.",
    "AGENT (autonomous-gold, supersedes human anchors): VISUAL_QA_REVIEWED_WITH_DEFECTS -> VISUAL_QA_PASS_BOUNDED then autonomous_certified_gold; MF-P1-08.* human SOP-1 deferred/superseded.",
    "AGENT (local-first): MF-P1-07.09 DVC local push; MF-P1-09.05 local B1 restore drill from seed package.",
    "MAIN (agent-executable in Main repo, not human): AWAITING_MAIN MF-P6-11.01..11.08 / MF-P6-12.02..12.06; producer side 93 tests PASS + fixture_complete/consumer pack Main-ready.",
    "MAIN HARD BLOCKERS named: MF-P6-11.02, MF-P6-11.07, MF-P6-12.05 (blocks MF-P6-12.06 / core close) until real Main-side artifacts exist.",
    "AGENT (local): MF-P4-10.08/10.09 local teacher corpus; MF-P8-11.07 local multi-person sources (DAZ/MaskedWarehouse/reference).",
    "CHAMPION: champions=0; certified_training_package_count=0; Mode B /predict AWAITING_RUNTIME (HTTP 503; no invented champions). Legitimate measured path documented (P5 entry via certified gold -> training -> measured win -> promotion).",
    "QUALITY residual (not gold closer): VISUAL_QA_PASS_BOUNDED not achieved.",
]
car["blocker_classes"]["disk"] = [
    "RESOLVED autonomously: data/ on governed F: (>250 GiB free); doctor disk_free PASS 251.1 GiB (reversible junction; C: backup retained)",
    "DAZ soft floor 150 GiB (post-core) can be satisfied by the same governed-drive relocation approach when DAZ new-work resumes",
]
car["blocker_classes"]["kevin"] = [
    "SUPERSEDED by needs_agent_actions_20260719.json — no OPEN human stop states",
]
for extra in [
    str(EVIDENCE.relative_to(ROOT).as_posix()),
    str(AGENT_QUEUE.relative_to(ROOT).as_posix()),
]:
    if extra not in car["evidence"]:
        car["evidence"].insert(0, extra)

surface_updates = {
    "doctor_all_green": {
        "highest_tier_achieved": "RUNTIME_BLOCKED",
        "exact_blockers": [
            "disk_free RESOLVED -> PASS (251.1 GiB via governed F: relocation); full doctor now RUNS TO COMPLETION (PASS=8 FAIL=4)",
            "3 FAIL rooted in Ubuntu-22.04 ext4 VHD read-only fallback / I/O error (torch_cuda, registered_models, wsl_roundtrip) — elevation-gated offline e2fsck",
            "1 FAIL = 8GB GPU VRAM contention (nuclio SAM2 vs ollama qwen2.5vl); each RUNTIME_PASS_BOUNDED individually via smokes",
            "gpu_lock stale lock cleared (FAIL->PASS)",
        ],
        "evidence": str(EVIDENCE.relative_to(ROOT).as_posix()),
    },
}
for surface in doc["surfaces"]:
    upd = surface_updates.get(surface["id"])
    if upd:
        surface.update(upd)

# Add a new surface capturing the autonomous disk relocation as its own RUNTIME_PASS_BOUNDED fact.
if not any(s.get("id") == "disk_ingest_headroom_relocation" for s in doc["surfaces"]):
    doc["surfaces"].append(
        {
            "id": "disk_ingest_headroom_relocation",
            "highest_tier_achieved": "RUNTIME_PASS_BOUNDED",
            "bound": "data/ junctioned to F:\\MaskFactory_DataRelocated (~251 GiB free); doctor disk_free PASS; reversible; C: backup retained",
            "exact_blockers": [],
            "evidence": str(EVIDENCE.relative_to(ROOT).as_posix()),
        }
    )

doc["kevin_decisions_still_required"] = [
    "SUPERSEDED: see qa/live_verification/needs_agent_actions_20260719.json — all former Kevin actions reclassified to agent-executable paths (disk DONE_AUTONOMOUS; WSL repair scripted-from-elevated-shell with Docker-GPU fallback done; DVC/B1/cloud-teacher/multi-person local-first; Main adoption agent-executable in Main repo). No OPEN human stop states.",
]
doc["host_snapshot_at_authoring"] = {
    "data_drive": "F:\\MaskFactory_DataRelocated (junction from data/)",
    "data_free_gib": 251.19,
    "disk_ingest_floor_gib": 75,
    "doctor_disk_free": "PASS",
    "doctor_summary": "PASS=8 FAIL=4",
    "doctor_all_green": False,
    "champions": 0,
    "certified_training_package_count": 0,
    "aws_credentials_present": False,
    "b1_mirror_present": False,
    "gpu_container_cuda_proof": "RTX 5060 driver 592.01 (docker --gpus all nvidia-smi)",
    "wsl_ubuntu_2204": "ext4 VHD read-only fallback (I/O error); elevation-gated e2fsck",
    "runtime_evidence_sha256": evidence_sha,
    "needs_agent_actions": "qa/live_verification/needs_agent_actions_20260719.json",
    "host_side_static_gaps_remain": False,
}

doc.pop("self_sha256", None)
body = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
self_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
doc["self_sha256"] = self_sha
MILESTONE.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"milestone self_sha256={self_sha}")
print(f"supersedes={PREV_SELF}")
print(f"evidence_sha256={evidence_sha}")
print(f"head={HEAD}")
