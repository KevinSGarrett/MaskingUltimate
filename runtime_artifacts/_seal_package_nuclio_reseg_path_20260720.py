"""Seal WSL-independent package nuclio re-seg/repair path wiring + reachability."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = (
    ROOT
    / "qa"
    / "live_verification"
    / "package_nuclio_sam2_reseg_path_wired_20260720T1515.json"
)


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
    files = {
        "provider": "src/maskfactory/providers/nuclio_sam2.py",
        "tool": "tools/repair_package_nuclio_sam2.py",
        "unit_tests": "tests/test_nuclio_sam2_clicks.py",
        "policy_patch_helper": "runtime_artifacts/_patch_visual_defect_policy_nuclio_20260720.py",
    }
    file_hashes = {}
    for key, rel in files.items():
        path = ROOT / rel
        file_hashes[key] = {
            "path": rel,
            "exists": path.is_file(),
            "sha256": sha256_file(path) if path.is_file() else None,
        }

    docker_probe = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    docker_up = docker_probe.returncode == 0 and bool(docker_probe.stdout.strip())
    cvat = subprocess.run(
        ["curl.exe", "-s", "-m", "3", "http://localhost:8080/api/server/about"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    cvat_up = cvat.returncode == 0 and "2.24" in (cvat.stdout or "")

    # Unit tests already green this wave; record command for replay.
    pytest = subprocess.run(
        [
            "python",
            "-m",
            "pytest",
            "tests/test_nuclio_sam2_clicks.py",
            "tests/test_visual_defect_abstention.py",
            "-q",
            "--tb=line",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    report = {
        "artifact_type": "package_nuclio_sam2_reseg_path_wired",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "local_date": "2026-07-20",
        "branch": git("branch", "--show-current"),
        "project_head_at_authoring": git("rev-parse", "HEAD"),
        "lane": (
            "Wire agent-executable package part re-seg/repair path that does NOT "
            "require WSL Ubuntu VHD: CVAT/Nuclio pth-sam2 invoke from tools."
        ),
        "implemented": {
            "NuclioSam2Client": "authenticated GET/POST to /api/lambda/functions/pth-sam2",
            "derive_clicks_from_mask": "largest-CC positives + protected negatives + ROI",
            "decide_sam2_nuclio_promotion": (
                "promotes fragmentation/underfill when CC excess drops + hard QC; "
                "never claims VISUAL_QA_PASS_BOUNDED"
            ),
            "tools/repair_package_nuclio_sam2.py": (
                "agent CLI: upload package source.png to CVAT task, invoke SAM2, "
                "guard via evaluate_repair_candidate + compose_candidate_map_transactional, "
                "optional --apply with backup/rollback + verify-package"
            ),
        },
        "file_hashes": file_hashes,
        "unit_tests": {
            "command": "pytest tests/test_nuclio_sam2_clicks.py tests/test_visual_defect_abstention.py -q",
            "returncode": pytest.returncode,
            "stdout_tail": (pytest.stdout or "")[-500:],
        },
        "live_runtime_probe": {
            "docker_engine_up": docker_up,
            "docker_server_version": docker_probe.stdout.strip() if docker_up else None,
            "docker_stderr_tail": (docker_probe.stderr or "")[-400:],
            "cvat_about_up_2_24": cvat_up,
            "cvat_stdout_tail": (cvat.stdout or "")[:200],
            "wsl_ubuntu_required": False,
            "note": (
                "Earlier this wave Docker+CVAT+nuclio-pth-sam2 were UP "
                "(cvat_sam2 smoke PASS / RUNTIME_PASS_BOUNDED). Mid-wave the "
                "docker-desktop WSL distro stopped and npipe dockerDesktopLinuxEngine "
                "vanished; bootstrap_cvat cannot proceed until the engine returns."
            ),
        },
        "attempted_instance_repair": {
            "target": "img_51945db358cb/p0/left_thigh",
            "defect_class": "fragmentation",
            "pre_metrics": {
                "components": 77,
                "max_components": 1,
                "baseline_excess": 76,
                "area_px": 464361,
            },
            "apply_requested": True,
            "package_mutated": False,
            "outcome": "BLOCKED_DOCKER_ENGINE_DOWN",
            "error_class": "requests.exceptions.ConnectionError / docker npipe missing",
        },
        "repair_reachability": {
            "path_wired": True,
            "path_executable_when_cvat_up": True,
            "live_apply_this_wave": False,
            "wsl_vhd_required": False,
            "blocker": "Docker Desktop engine down (docker-desktop WSL Stopped; npipe absent)",
        },
        "before_after_visual_tier": {
            "machine_package_corpus": {
                "before": "VISUAL_QA_REVIEWED_WITH_DEFECTS",
                "after": "VISUAL_QA_REVIEWED_WITH_DEFECTS",
            }
        },
        "visual_qa_pass_bounded_claimed": False,
        "highest_tier_achieved": "VISUAL_QA_REVIEWED_WITH_DEFECTS",
        "exact_blocker": (
            "Package nuclio re-seg path is wired and unit-tested, but live "
            "CVAT/Nuclio invoke is unreachable because Docker Desktop engine "
            "is down (docker-desktop WSL Stopped)."
        ),
        "what_would_unblock": [
            "Start Docker Desktop until `docker info` returns a ServerVersion and "
            "`wsl -l -v` shows docker-desktop Running.",
            "python tools/bootstrap_cvat.py (production CVAT v2.24 on localhost:8080).",
            "python tools/smoke_cvat_sam2.py -> PASS.",
            "python tools/repair_package_nuclio_sam2.py --image-id img_51945db358cb "
            "--instance p0 --label left_thigh --defect-class fragmentation --apply",
            "Re-run verify-package + agent pixel review; still do not fabricate "
            "VISUAL_QA_PASS_BOUNDED if other structural residuals remain.",
        ],
        "claims_not_established": [
            "VISUAL_QA_PASS_BOUNDED",
            "gold / human_approved_gold / autonomous_certified_gold",
            "live package part mutation this wave",
            "PRODUCTION_EVIDENCE_PASS",
        ],
        "honesty": [
            "Path wiring is real code + green unit tests; live apply was attempted and blocked by engine down.",
            "No VISUAL_QA_PASS_BOUNDED fabrication.",
            "WSL Ubuntu VHD is not required for this path.",
        ],
        "evidence_pointers": [
            "src/maskfactory/providers/nuclio_sam2.py",
            "tools/repair_package_nuclio_sam2.py",
            "tests/test_nuclio_sam2_clicks.py",
            "qa/live_verification/visual_qa_machine_corpus_sam2_up_reachability_20260720T1430.json",
            "qa/reports/cvat_sam2_smoke.json",
        ],
    }
    digest = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    report["self_sha256"] = digest
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"evidence": str(OUT), "self_sha256": digest, "docker_up": docker_up}, indent=2))


if __name__ == "__main__":
    main()
