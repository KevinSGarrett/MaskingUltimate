"""Append OPS_LOG + commit/push the nuclio package re-seg path wiring."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OPS_ENTRY = """

## 2026-07-20 — Package nuclio SAM2 re-seg path wired (WSL-independent; live apply blocked)
**Item:** agent-executable package part re-seg/repair without WSL Ubuntu VHD
**Command:** pytest tests/test_nuclio_sam2_clicks.py tests/test_visual_defect_abstention.py -q; python tools/repair_package_nuclio_sam2.py --image-id img_51945db358cb --instance p0 --label left_thigh --defect-class fragmentation --apply; python runtime_artifacts/_seal_package_nuclio_reseg_path_20260720.py
**Result:** PATH_WIRED. Added `NuclioSam2Client` + click derivation + `decide_sam2_nuclio_promotion` and agent CLI `tools/repair_package_nuclio_sam2.py` (CVAT/Nuclio pth-sam2; no WSL VHD). Unit tests green. Live `--apply` on img_51945db358cb/p0/left_thigh (77 CC fragmentation) blocked mid-wave by Docker Desktop engine DOWN (docker-desktop WSL Stopped; npipe missing) after earlier RUNTIME_PASS_BOUNDED SAM2 smoke. Package not mutated. No VISUAL_QA_PASS_BOUNDED claim.

Evidence: qa/live_verification/package_nuclio_sam2_reseg_path_wired_20260720T1515.json (self_sha256 79d6d153e5a6...). Next: restore Docker/CVAT, smoke_cvat_sam2, re-run repair --apply.

"""

FILES = [
    "src/maskfactory/providers/nuclio_sam2.py",
    "tools/repair_package_nuclio_sam2.py",
    "tests/test_nuclio_sam2_clicks.py",
    "qa/live_verification/package_nuclio_sam2_reseg_path_wired_20260720T1515.json",
    "runtime_artifacts/_seal_package_nuclio_reseg_path_20260720.py",
    "runtime_artifacts/_patch_visual_defect_policy_nuclio_20260720.py",
    "runtime_artifacts/_commit_nuclio_reseg_path_20260720.py",
    "Plan/OPS_LOG.md",
]


def run(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=check)


def main() -> None:
    ops = ROOT / "Plan" / "OPS_LOG.md"
    text = ops.read_text(encoding="utf-8")
    if "Package nuclio SAM2 re-seg path wired" not in text:
        ops.write_text(text.rstrip() + OPS_ENTRY, encoding="utf-8")
        print("ops_log_appended")
    else:
        print("ops_log_already_present")

    # morphology test is optional; include if modified
    morph = ROOT / "tests" / "test_visual_defect_abstention.py"
    if "test_morphology_still_abstains_on_fragmentation" in morph.read_text(encoding="utf-8"):
        diff = run(["git", "diff", "--", "tests/test_visual_defect_abstention.py"], check=False)
        if diff.stdout.strip():
            FILES.append("tests/test_visual_defect_abstention.py")

    existing = [f for f in FILES if (ROOT / f).exists()]
    run(["git", "add", "--", *existing])
    status = run(["git", "status", "--short", "--", *existing], check=False)
    print(status.stdout)
    msg = (
        "feat(repair): wire WSL-independent nuclio package re-seg path\n\n"
        "Add CVAT/Nuclio pth-sam2 client + agent CLI for part refine with "
        "promotion gates that never claim VISUAL_QA_PASS. Live apply blocked "
        "this wave by Docker engine down; seal reachability + next step."
    )
    commit = subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    print(commit.stdout)
    print(commit.stderr)
    if commit.returncode != 0:
        raise SystemExit(f"commit_failed rc={commit.returncode}")
    push = run(["git", "push"], check=False)
    print(push.stdout)
    print(push.stderr)
    print("push_rc", push.returncode)
    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    dirty = run(["git", "status", "--porcelain"], check=False).stdout
    # Report stream cleanliness for our files only
    stream_dirty = [
        line
        for line in dirty.splitlines()
        if any(f in line for f in existing)
    ]
    print("HEAD", head)
    print("stream_clean", not stream_dirty)
    print("repo_dirty_lines", len(dirty.splitlines()))


if __name__ == "__main__":
    main()
