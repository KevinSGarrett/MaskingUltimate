"""Re-seal milestone_proof_tiers after the 2026-07-20 honest re-verification wave.

No tier inflation. Champions still 0; Mode B /predict AWAITING_RUNTIME; no gold; no Main receipts;
no doctor-green; no PRODUCTION_EVIDENCE_PASS; core_autonomous_runtime NOT complete. This revision
records a fresh honest live re-verification and the precise champion/Main hard-gate root cause.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MILESTONE = ROOT / "qa" / "live_verification" / "milestone_proof_tiers_20260719.json"
EVIDENCE = ROOT / "qa" / "live_verification" / "autonomy_reverify_20260720T0430.json"

PREV_SELF = "8b87568ee7264fc2fbc33e2ed646edf245601cbab90d3b2196db0adc94019a20"
HEAD = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
BRANCH = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
evidence_sha = hashlib.sha256(EVIDENCE.read_bytes()).hexdigest()

doc = json.loads(MILESTONE.read_text(encoding="utf-8"))
assert doc["self_sha256"] == PREV_SELF, doc["self_sha256"]

doc["recorded_at"] = recorded_at
doc["revision"] = "post_autonomy_reverify_20260720"
doc["supersedes_self_sha256"] = PREV_SELF
doc["branch"] = BRANCH
doc["project_head_at_authoring"] = HEAD
rel = str(EVIDENCE.relative_to(ROOT).as_posix())
if rel not in doc["authority"]:
    doc["authority"].append(rel)

car = doc["core_autonomous_runtime"]
car["rationale"] = (
    "AUTONOMY RE-VERIFY WAVE (2026-07-20, honest): live re-probe confirmed Docker 29.4.3 / CVAT 2.24.0 / "
    "Ollama 0.32.1 / nuclio pth-sam2 healthy; GPU RTX 5060 ~2182 MiB free. Champions still 0 and the "
    "chain is precisely root-caused and NON-FABRICABLE: (1) data/packages has 0 approved_gold / 0 "
    "human_anchor_gold / 0 autonomous_certified_gold, so the autonomy calibration certificate (needs a "
    "frozen human-anchor-gold corpus, ~>=270 zero-defect audits for the 0.01 Wilson bound) cannot pass -> "
    "0 calibrated_auto_accepted lifecycle sidecars -> autonomy build-audit-queue population_count=0 "
    "(downstream symptom, not a code bug); (2) no CUDA training runtime (host torch 2.12.1+cpu, "
    "training-doctor ready=false; WSL Ubuntu-22.04 corrupt E_FAIL; IsAdmin=False so e2fsck is "
    "elevation-gated) and 0 gold training volume -> no registered candidate / no measured shadow win; "
    "(3) host `maskfactory serve` cannot start (FastAPI serve deps missing) so Mode B /predict is "
    "AWAITING_RUNTIME (also champions=0). force-register FORBIDDEN. DAZ not killed (live user GUI). "
    "Workstream B: producer bridge + cross-project PASS at HEAD; run_cross_project_qualification="
    "producer_partial; Main C:/Comfy_UI_Main HEAD b36001b9 is a separate unrelated active project with a "
    "dirty tree and no MaskFactory consumer surface -> real MF-P6-11.02/11.07/12.05 receipts require an "
    "isolated Main-side consumer build (not fabricated; Main branch untouched). No doctor-green / gold / "
    "visual-pass / Main-complete / PRODUCTION_EVIDENCE_PASS / core close."
)
if rel not in car["evidence"]:
    car["evidence"].insert(0, rel)

doc["host_snapshot_at_authoring"] = {
    "head": HEAD,
    "data_drive": "F:\\MaskFactory_DataRelocated (junction from data/)",
    "doctor_disk_free": "PASS",
    "doctor_all_green": False,
    "champions": 0,
    "certified_training_package_count": 0,
    "approved_gold_packages": 0,
    "human_anchor_gold_packages": 0,
    "autonomous_certified_gold_packages": 0,
    "audit_queue_population_count": 0,
    "host_torch": "2.12.1+cpu (no CUDA)",
    "training_doctor_ready": False,
    "mode_b_serve_host": "cannot start (FastAPI serve deps missing; runtime=WSL down)",
    "mode_b_predict": "AWAITING_RUNTIME",
    "gpu_free_vram_mib_approx": 2182,
    "gpu_consumers": "DAZStudio pid52340 + python pid10912 + Cursor",
    "wsl_ubuntu_2204": "corrupt (E_FAIL step 2, ext4 VHD)",
    "wsl_elevation_available": False,
    "producer_bridge_tests": "PASS at HEAD (15 modules)",
    "cross_project_qualification": "producer_partial (mf_p6_12_05_complete=false)",
    "main_repo_present": "C:/Comfy_UI_Main HEAD b36001b9 (separate git; no MaskFactory consumer surface)",
    "runtime_evidence_sha256": evidence_sha,
    "needs_agent_actions": "qa/live_verification/needs_agent_actions_20260719.json",
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
