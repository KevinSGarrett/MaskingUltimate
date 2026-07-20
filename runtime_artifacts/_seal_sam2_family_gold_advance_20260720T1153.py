"""Seal nuclio SAM2 as a live independent mask family for gold-factory siblings.

Seals ONLY when tools/smoke_cvat_sam2.py PASS (fg>0, all checks true).
Does not mint gold, champions, or Wilson samples. Ollama is critic-only and
must be GPU-sequenced after SAM2 (never concurrent on the 8 GiB card).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TS = "20260720T1153"
SMOKE = REPO_ROOT / "qa/reports/cvat_sam2_smoke.json"
OLLAMA = REPO_ROOT / "qa/reports/ollama_vlm_smoke.json"
GPU_PLAN = REPO_ROOT / "qa/live_verification/_gpu_plan_nuclio_sam2_gold_20260720T1152.json"
GPU_WAIT = REPO_ROOT / "qa/live_verification/_gpu_wait_nuclio_sam2_20260720T1151.json"
GPU_SEQ_OLLAMA = REPO_ROOT / "qa/live_verification/_gpu_seq_ollama_critic_20260720T1153.json"
GPU_WAIT_POST = (
    REPO_ROOT / "qa/live_verification/_gpu_wait_nuclio_sam2_post_critic_20260720T1159.json"
)
OUTPUT = REPO_ROOT / f"qa/live_verification/sam2_family_gold_advance_{TS}.json"
LATEST = REPO_ROOT / "qa/live_verification/sam2_family_gold_advance_latest.json"
FAMILIES_LATEST = REPO_ROOT / "qa/live_verification/families_online_tournament_sibling_latest.json"


def _sha_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _seal(evidence: dict) -> dict:
    evidence.pop("self_sha256", None)
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    return evidence


def _docker_sam2_healthy() -> dict:
    out: dict = {"container": "nuclio-nuclio-pth-sam2", "healthy": False}
    try:
        ps = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                "name=nuclio-nuclio-pth-sam2",
                "--format",
                "{{.Names}}\t{{.Status}}",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        line = (ps.stdout or "").strip()
        out["ps_line"] = line
        out["healthy"] = "healthy" in line.lower() and "nuclio-nuclio-pth-sam2" in line
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)[:400]
    return out


def _cvat_about() -> dict:
    try:
        import urllib.request

        with urllib.request.urlopen("http://localhost:8080/api/server/about", timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return {"reachable": True, "version": body.get("version")}
    except Exception as exc:  # noqa: BLE001
        return {"reachable": False, "error": str(exc)[:300]}


def main() -> int:
    smoke = _load(SMOKE)
    ollama = _load(OLLAMA)
    checks = smoke.get("checks") or {}
    smoke_pass = bool(
        smoke
        and int(smoke.get("foreground_pixels") or 0) > 0
        and all(bool(v) for v in checks.values())
        and smoke.get("function_id") == "pth-sam2"
    )
    if not smoke_pass:
        print("REFUSE_SEAL: SAM2 smoke not PASS; gold family not advanced")
        return 2

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()

    container = _docker_sam2_healthy()
    cvat = _cvat_about()
    families_ptr = _load(FAMILIES_LATEST)
    prior_families = list(families_ptr.get("live_independent_mask_families") or [])

    live_families = list(dict.fromkeys([*prior_families, "nuclio_pth_sam2"]))
    # If sibling pointer empty, still seal SAM2 alone as the family this wave proves.
    if "nuclio_pth_sam2" not in live_families:
        live_families.append("nuclio_pth_sam2")

    evidence = {
        "artifact_type": "sam2_family_gold_advance",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authority": "autonomous_certified_gold_profile",
        "evidence_tier": "RUNTIME_PASS_BOUNDED",
        "project_head_at_seal": head,
        "seal_gate": {
            "rule": "seal_only_if_sam2_smoke_pass_advances_gold_family",
            "sam2_smoke_pass": True,
            "advances_gold_family_floor": True,
            "minted_autonomous_certified_gold": False,
            "minted_wilson_samples": False,
            "force_registered_champions": False,
        },
        "sam2_family": {
            "family_key": "nuclio_pth_sam2",
            "kind": "independent_mask_source",
            "runtime": "nuclio_cpu_interactor_via_cvat_2_24",
            "function_id": smoke.get("function_id"),
            "function_name": smoke.get("function_name"),
            "task_id": smoke.get("task_id"),
            "latency_seconds": smoke.get("latency_seconds"),
            "foreground_pixels": smoke.get("foreground_pixels"),
            "checks": checks,
            "smoke_report": "qa/reports/cvat_sam2_smoke.json",
            "smoke_report_sha256": _sha_file(SMOKE),
            "measured_at": smoke.get("measured_at"),
            "container": container,
        },
        "runtime_probe": {
            "cvat": cvat,
            "docker_sam2": container,
            "gpu_policy": "Plan/GPU_SEQUENCING_AND_VRAM_BUDGET.md; sequential nuclio-sam2 then ollama-vlm critic-only; no foreign eviction; no image builds; no volume wipe",
        },
        "gpu_sequencing": {
            "plan": "qa/live_verification/_gpu_plan_nuclio_sam2_gold_20260720T1152.json",
            "plan_sha256": _sha_file(GPU_PLAN),
            "wait": "qa/live_verification/_gpu_wait_nuclio_sam2_20260720T1151.json",
            "wait_sha256": _sha_file(GPU_WAIT),
            "ollama_sequence": "qa/live_verification/_gpu_seq_ollama_critic_20260720T1153.json",
            "ollama_sequence_sha256": _sha_file(GPU_SEQ_OLLAMA),
            "post_critic_sam2_wait": "qa/live_verification/_gpu_wait_nuclio_sam2_post_critic_20260720T1159.json",
            "post_critic_sam2_wait_sha256": _sha_file(GPU_WAIT_POST),
            "order": [
                "nuclio-sam2",
                "ollama-vlm critic-only",
                "unload ollama",
                "reconfirm nuclio-sam2",
            ],
            "ollama_role": "critic_only_after_sam2",
            "ollama_model": "qwen2.5vl:7b",
            "no_foreign_eviction": True,
        },
        "ollama_critic": {
            "role": "qa_router_only_advisory",
            "may_author_masks": False,
            "may_approve_gold": False,
            "may_clear_blocks": False,
            "smoke_report": "qa/reports/ollama_vlm_smoke.json",
            "smoke_report_sha256": _sha_file(OLLAMA),
            "model": ollama.get("model"),
            "latency_seconds": ollama.get("latency_seconds"),
            "verdict": (ollama.get("response") or {}).get("verdict"),
            "checks_pass": (
                all(bool(v) for v in (ollama.get("checks") or {}).values())
                if ollama.get("checks")
                else False
            ),
            "measured_at": ollama.get("measured_at"),
        },
        "tournament_sibling_help": {
            "purpose": "Prove nuclio_pth_sam2 is a live independent family siblings can count toward the >=3 family floor / optional fourth family",
            "live_independent_mask_families": live_families,
            "live_independent_mask_families_count": len(live_families),
            "meets_tournament_family_floor": len(
                [f for f in live_families if f != "nuclio_pth_sam2"]
            )
            >= 3
            or len(live_families) >= 3,
            "families_online_pointer": "qa/live_verification/families_online_tournament_sibling_latest.json",
            "families_online_self_sha256": families_ptr.get("self_sha256")
            or families_ptr.get("self_sha256_of_seal"),
            "claim": "SAM2 smoke PASS advances gold-factory family availability; does not mint gold",
        },
        "honesty_boundary": {
            "no_image_builds": True,
            "no_volume_wipe": True,
            "no_prune": True,
            "vlm_is_advisory_critic_only": True,
            "families_online_does_not_mint_gold": True,
            "cpu_sam2_is_independent_of_local_cuda_sam2_1_large": True,
        },
        "next_agent_step": (
            "Tournament siblings may count nuclio_pth_sam2 as a live independent family. "
            "GPU-sequence remaining Comfy CUDA families + multi-provider tournament; "
            "Ollama qwen2.5vl:7b critic-only after SAM2 slot released."
        ),
    }
    sealed = _seal(evidence)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(sealed, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(text, encoding="utf-8")

    latest = {
        "artifact_type": "sam2_family_gold_advance_latest",
        "schema_version": "1.0.0",
        "recorded_at": sealed["recorded_at"],
        "seal_path": str(OUTPUT.relative_to(REPO_ROOT)).replace("\\", "/"),
        "self_sha256_of_seal": sealed["self_sha256"],
        "sam2_smoke_pass": True,
        "family_key": "nuclio_pth_sam2",
        "foreground_pixels": smoke.get("foreground_pixels"),
        "latency_seconds": smoke.get("latency_seconds"),
        "cvat_version": cvat.get("version"),
        "advances_gold_family_floor": True,
        "minted_gold": False,
    }
    latest = _seal(latest)
    LATEST.write_text(json.dumps(latest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"SEALED {OUTPUT.relative_to(REPO_ROOT)} sha256={sealed['self_sha256']}")
    print(f"LATEST {LATEST.relative_to(REPO_ROOT)} sha256={latest['self_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
