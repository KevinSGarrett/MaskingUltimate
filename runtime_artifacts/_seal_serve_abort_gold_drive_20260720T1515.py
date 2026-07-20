"""Seal serve:cu128 abort + host-side gold tournament F: drive wave (2026-07-20T1515).

Honesty: no serve image, no smoke, no gold mint, no Docker hammer after flap.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LV = REPO / "qa" / "live_verification"
OUT = LV / "serve_abort_gold_drive_20260720T1515.json"
HEAD = "e3ee17f357af86ee42563cc4fb6bad9f43fdc2de"


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def seal(obj: dict, out: Path) -> str:
    payload = json.dumps(
        {k: v for k, v in obj.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    obj["self_sha256"] = hashlib.sha256(payload).hexdigest()
    out.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return obj["self_sha256"]


def main() -> int:
    drive = _load(LV / "gold_tournament_drive_fdrive_20260720T1515.json")
    corpus = _load(LV / "f_drive_gold_source_corpus_20260720T1515.json")
    admission = _load(LV / "autonomous_gold_admission_20260720T1515.json")
    if not admission:
        admission = _load(LV / "autonomous_gold_admission_20260720T1446.json")
    families = _load(LV / "families_online_gold_drive_20260720T0957.json")
    coord = _load(REPO / "runtime_artifacts" / "_serve_cu128_build_coordination_20260720.json")

    evidence = {
        "artifact_type": "serve_abort_gold_drive_wave",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "project_head_at_authoring": HEAD,
        "branch": "codex/maskfactory-runtime-implementation",
        "authority": "autonomous_full_autonomy_parallel_safe_zero_human_wait",
        "model": "cursor-grok-4.5-high-fast",
        "lanes": {
            "serve_cu128_build_smoke": {
                "verdict": "RUNTIME_BLOCKED_ABORTED_TO_PROTECT_DOCKER",
                "image_present": False,
                "smoke": "NOT_RUN",
                "attempts": [
                    {
                        "at": "2026-07-20T14:45:49Z",
                        "cmd": "docker build -f docker/Dockerfile.serve -t maskfactory/serve:cu128 .",
                        "result": "CLI EXIT=-1 during nvidia-cudnn-cu12 657.9MB download; engine stayed up initially",
                        "log": "qa/live_verification/_serve_cu128_build_20260720T094550.log",
                    },
                    {
                        "at": "2026-07-20T14:48:00Z",
                        "cmd": "Start-Process docker build ... (redirected)",
                        "result": "stuck resolving dockerfile:1.7; orphaned docker.exe CLI pile; Desktop flap",
                    },
                ],
                "coordination": {
                    "sibling_sole_builder": coord,
                    "policy_honored_after_discovery": (
                        "Discovered runtime_artifacts/_serve_cu128_build_coordination_20260720.json "
                        "(sole_builder_pid=53784). Stopped further serve builds from this stream. "
                        "Sibling retry log empty; err=daemon npipe missing."
                    ),
                },
                "docker_engine_final": {
                    "pipe_dockerDesktopLinuxEngine": False,
                    "cvat": "UNREACHABLE",
                    "ollama_host": "UP 0.32.1",
                    "destructive_ops": "none",
                    "stop_hammering": True,
                },
            },
            "gold_tournament_host_parallel_safe": {
                "verdict": "RUNTIME_PASS_BOUNDED_SOURCE_CORPUS_ONLY",
                "tool": "runtime_artifacts/_drive_gold_tournament_fdrive_20260720.py --ts 20260720T1515",
                "drive_evidence": "qa/live_verification/gold_tournament_drive_fdrive_20260720T1515.json",
                "drive_self_sha256": drive.get("self_sha256"),
                "corpus_evidence": "qa/live_verification/f_drive_gold_source_corpus_20260720T1515.json",
                "corpus_self_sha256": corpus.get("self_sha256"),
                "staged_source_record_count": corpus.get("record_count")
                or drive.get("staged_source_corpus", {}).get("record_count"),
                "staged_source_collection_count": corpus.get("collection_count")
                or drive.get("staged_source_corpus", {}).get("collection_count"),
                "f_used_read_only": True,
                "no_junction_to_f": True,
                "admission": {
                    "status": admission.get("status"),
                    "certificate_passed": admission.get("certificate_passed"),
                    "machine_verified_candidate_count": (
                        (admission.get("autonomous_verified_pool") or {}).get(
                            "machine_verified_candidate_count"
                        )
                    ),
                    "self_sha256": admission.get("self_sha256"),
                    "path": (
                        "qa/live_verification/autonomous_gold_admission_20260720T1515.json"
                        if (LV / "autonomous_gold_admission_20260720T1515.json").is_file()
                        else "qa/live_verification/autonomous_gold_admission_20260720T1446.json"
                    ),
                },
                "families_online_prior": {
                    "evidence": "qa/live_verification/families_online_gold_drive_20260720T0957.json",
                    "live_independent_mask_families_count": (
                        (families.get("gold_counts") or {}).get(
                            "live_independent_mask_families_count"
                        )
                    ),
                    "runtime": "local_cuda_comfyui_venv_torch_2.11.0+cu128",
                    "note": (
                        "Family-count gate (>=3) already cleared on host CUDA; "
                        "drive script's embedded 1-family blocker text is stale relative "
                        "to families_online seal. Sidecar emission still pending."
                    ),
                },
            },
        },
        "gold_counts": {
            "approved_gold_count": 0,
            "autonomous_certified_gold_count": 0,
            "calibrated_auto_accepted_count": 0,
            "machine_verified_candidate_count": 0,
            "champions": 0,
        },
        "claims_not_established": [
            "serve_cu128_built",
            "smoke_docker_gpu_serve_pass",
            "doctor_all_green",
            "autonomous_certified_gold",
            "champions>0",
            "machine_verified_candidate>0",
            "PRODUCTION_EVIDENCE_PASS",
        ],
        "claims_established_this_wave": [
            "serve_build_attempted_then_aborted_to_protect_docker",
            "sibling_serve_sole_builder_coordination_honored",
            "f_drive_gold_source_corpus_staged_read_only_41_records",
            "autonomous_gold_admission_insufficient_samples_reconfirmed",
        ],
        "honesty": [
            "No tier inflation: gold=0, champions=0, serve image absent, smoke not run.",
            "Stopped Docker relaunch loops after pipe flap; Ollama host remains UP.",
            "Host F: gold-volume SOURCE corpus is not a certificate and does not mint candidates.",
            "Parallel-safe: no concurrent GPU Docker tournament while engine unstable.",
        ],
        "next_agent_step": (
            "When Docker Desktop is stable AND C: free stays >=75 GiB AND no sibling "
            "sole-builder coordination lock: one deliberate maskfactory/serve:cu128 build "
            "then tools/smoke_docker_gpu_serve.py. In parallel on host CUDA (no Docker): "
            "GPU-sequence >=3-family tournament over the staged F:/Ultimate sample corpus "
            "to emit genuine machine_verified_candidate sidecars under runs/, then "
            "build_autonomous_gold_admission.py --corpus."
        ),
        "self_sha256": "",
    }
    digest = seal(evidence, OUT)
    print(json.dumps({"out": str(OUT.relative_to(REPO)), "self_sha256": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
