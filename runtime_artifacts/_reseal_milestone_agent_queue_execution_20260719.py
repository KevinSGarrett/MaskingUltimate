"""Re-seal milestone_proof_tiers after the agent-queue execution wave (late 2026-07-19).

Honest advances only (no tier inflation):
  - DVC local-first push/cache PASS (local remote; 52 objects in sync) — cloud s3 still deferred
  - Local B1 restore drill PASS (restored package verify-package p0+p1)
  - Multi-person + cloud-teacher + release STATIC contracts PASS
  - Producer bridge / consumer conformance re-verified (90 tests PASS at HEAD)
  - Shadow currency-registry STATIC seal rebound to current signed review (policy still fail)
  - WSL repair: elevation proven unavailable in this shell; Docker-GPU substitute active
Does NOT claim doctor-green / gold / VISUAL_QA_PASS_BOUNDED / champions / Main-complete /
cloud DVC S3 push / PRODUCTION_EVIDENCE_PASS / core close.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MILESTONE = ROOT / "qa" / "live_verification" / "milestone_proof_tiers_20260719.json"
EVIDENCE = ROOT / "qa" / "live_verification" / "agent_queue_execution_20260719T2300.json"
AGENT_QUEUE = ROOT / "qa" / "live_verification" / "needs_agent_actions_20260719.json"

PREV_SELF = "0581b4ab08b060f3738d48463ffe5bfbea80590b5bbe1f75bb41a54b9f457e34"
HEAD = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
BRANCH = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
evidence_sha = hashlib.sha256(EVIDENCE.read_bytes()).hexdigest()

doc = json.loads(MILESTONE.read_text(encoding="utf-8"))
assert doc["self_sha256"] == PREV_SELF, doc["self_sha256"]

doc["recorded_at"] = recorded_at
doc["revision"] = "post_agent_queue_execution_20260719"
doc["supersedes_self_sha256"] = PREV_SELF
doc["branch"] = BRANCH
doc["project_head_at_authoring"] = HEAD
if str(EVIDENCE.relative_to(ROOT).as_posix()) not in doc["authority"]:
    doc["authority"].append(str(EVIDENCE.relative_to(ROOT).as_posix()))

car = doc["core_autonomous_runtime"]
car["rationale"] = (
    "AGENT QUEUE EXECUTION WAVE (honest, local-first): local DVC push/cache PASS (52 objects to a "
    "local F: remote; dvc status -c in sync; cloud s3 still deferred — needs dvc-s3 + AWS creds); "
    "local B1 restore drill PASS (restored package verify-package p0+p1); multi-person + cloud-teacher "
    "+ release STATIC contracts PASS; producer bridge / consumer conformance re-verified (90 tests PASS "
    "at HEAD); shadow currency-registry STATIC seal rebound to the current signed review 38a72efc "
    "(policy still honestly fail). WSL Ubuntu-22.04 ext4 VHD repair remains elevation-gated: this "
    "session's shell is non-elevated (IsInRole=False; schtasks /rl HIGHEST access denied; RunAs=UAC) — "
    "Docker GPU CUDA container proof (RTX 5060 driver 592.01) is the active substitute and the scripted "
    "e2fsck is deferred to the next elevated shell. Champions still 0: autonomy build-audit-queue "
    "population_count=0 (empty lifecycle) + VISUAL_QA_REVIEWED_WITH_DEFECTS + ~0.4 GiB free VRAM + "
    "human_anchor=0; force-register FORBIDDEN. No doctor-green / gold / visual-pass / Main-complete / "
    "cloud DVC S3 / PRODUCTION_EVIDENCE_PASS / core close."
)
# Update the local-first DVC/B1 blocker line to reflect the local tier DONE.
car["exact_blockers"] = [
    b.replace(
        "AGENT (local-first): MF-P1-07.09 DVC local push; MF-P1-09.05 local B1 restore drill from seed package.",
        "DONE (local tier): MF-P1-07.09 DVC local push/cache PASS (52 objects to local F: remote, in sync); "
        "MF-P1-09.05 local B1 restore drill PASS (verify-package p0+p1). Cloud DVC S3 push still deferred.",
    )
    for b in car["exact_blockers"]
]
if str(EVIDENCE.relative_to(ROOT).as_posix()) not in car["evidence"]:
    car["evidence"].insert(0, str(EVIDENCE.relative_to(ROOT).as_posix()))

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
    "dvc_local_push": "DONE (maskfactory-dvc-local on F:; 52 objects; in sync)",
    "dvc_cloud_s3_push": False,
    "b1_restore_drill_local": "PASS (img_a3d2663ad90d p0+p1)",
    "producer_bridge_tests": "90 PASS at HEAD",
    "main_repo_present": "C:/Comfy_UI_Main HEAD 2393fbb7 (separate git)",
    "gpu_container_cuda_proof": "RTX 5060 driver 592.01 (docker --gpus all nvidia-smi)",
    "gpu_free_vram_mib_approx": 377,
    "wsl_ubuntu_2204": "Stopped; /bin/true -> distribution failed to start (E_FAIL); on-disk ext4 corruption; elevation-gated e2fsck",
    "wsl_elevation_available": False,
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
