"""Race-safe commit for B1 local restore drill reseal (no WT scoop)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/maskfactory-runtime-implementation"
STAMP = "20260720T1517Z"
EVIDENCE_REL = f"qa/live_verification/b1_restore_drill_local_c_backup_{STAMP}.json"
SEAL_REL = "runtime_artifacts/_seal_b1_restore_drill_local_c_backup_20260720.py"
COMMIT_HELPER_REL = "runtime_artifacts/_isolated_commit_b1_restore_drill_20260720.py"
MSG_REL = "runtime_artifacts/_commit_msg_b1_restore_drill_local_20260720.txt"
TMP_INDEX = ROOT / ".git" / "mf_b1_restore_tmp_index"
MARKER = "B1 restore drill re-run from C: backup seed"

OPS_ENTRY = f"""
## 2026-07-20 15:17 UTC - B1 restore drill re-run from C: backup seed (verify-package PASS)
**Item:** MF-P1-09.05
**Command:** `robocopy data_c_backup_relocated\\packages\\img_a3d2663ad90d runtime_artifacts\\b1_restore_drill\\img_a3d2663ad90d /E /COPY:DAT /R:2 /W:2`; `maskfactory verify-package img_a3d2663ad90d --root runtime_artifacts/b1_restore_drill`; `maskfactory verify-package img_51945db358cb --root data/packages`
**Result:** PASS (local-tier RUNTIME_PASS_BOUNDED). Restored seed package **img_a3d2663ad90d** (252 files / 8,367,171 bytes) from on-C: backup `data_c_backup_relocated/packages` into empty drill target `runtime_artifacts/b1_restore_drill`. `verify-package` PASS for instances **p0** and **p1**. Independent source integrity PASS for `img_51945db358cb/p0`. `data/` junction unchanged (still C: backup). Official `D:\\MaskFactoryBackup` B1 media **absent** — not claimed. DVC local C: backup already PASS (prior seal). No doctor-green / gold / visual-pass inflation.

Evidence: {EVIDENCE_REL}
"""

NOTE = (
    "2026-07-20 FULL AUTONOMY re-run: local B1 restore drill from C: backup seed "
    "img_a3d2663ad90d -> runtime_artifacts/b1_restore_drill; verify-package PASS p0+p1; "
    f"independent img_51945db358cb PASS. D:\\MaskFactoryBackup absent (not claimed). Evidence: {EVIDENCE_REL}"
)


def run(args, env=None, check=True, input_text=None):
    return subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
        env=env,
        input=input_text,
    )


def write_blob(env: dict, content: str) -> str:
    return run(
        ["git", "hash-object", "-w", "--stdin"],
        env=env,
        input_text=content if content.endswith("\n") else content + "\n",
    ).stdout.strip()


def stage_path(env: dict, rel: str, content: str | None = None, mode: str = "100644") -> None:
    if content is None:
        abs_path = ROOT / rel
        blob = run(["git", "hash-object", "-w", str(abs_path)], env=env).stdout.strip()
    else:
        blob = write_blob(env, content)
    run(
        ["git", "update-index", "--add", "--cacheinfo", f"{mode},{blob},{rel}"],
        env=env,
    )


def update_needs(doc: dict, evidence_rel: str, self_sha: str) -> dict:
    for action in doc.get("actions", []):
        if action.get("action_id") != "b1_restore_drill_local":
            continue
        action["status"] = "DONE_LOCAL"
        action["evidence"] = evidence_rel
        action["executed"] = (
            "Re-run 2026-07-20: seed img_a3d2663ad90d (252 files, 8.0 MB) restored via robocopy "
            "from data_c_backup_relocated/packages to runtime_artifacts/b1_restore_drill; "
            "`maskfactory verify-package img_a3d2663ad90d --root runtime_artifacts/b1_restore_drill` "
            "-> PASS p0+p1; independent `img_51945db358cb` PASS. D:\\MaskFactoryBackup absent."
        )
        action["rerun_20260720T1517"] = {
            "evidence": evidence_rel,
            "self_sha256": self_sha,
            "source": "C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated\\packages\\img_a3d2663ad90d",
            "tier": "RUNTIME_PASS_BOUNDED",
            "verify_package": "PASS p0+p1",
        }
        action["no_human_wait"] = True
        break
    return doc


def update_tracker(tracker: dict, evidence_rel: str, self_sha: str) -> tuple[dict, dict]:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    item = tracker["items"]["MF-P1-09.05"]
    old_status = item.get("status")
    old_pct = item.get("percent_complete")
    item["status"] = "complete"
    item["percent_complete"] = 100
    item["blocked_reason"] = None
    item["evidence"] = f"{evidence_rel} (self_sha256 {self_sha})"
    item["updated_at"] = ts
    notes = item.setdefault("notes", [])
    if not any(NOTE in (n.get("text") or "") for n in notes):
        notes.append({"ts": ts, "actor": "ai_agent", "text": NOTE})
    changelog = {
        "ts": ts,
        "id": "MF-P1-09.05",
        "actor": "ai_agent",
        "old_status": old_status,
        "new_status": "complete",
        "percent_complete": 100,
        "note": NOTE,
        "evidence": f"{evidence_rel} (self_sha256 {self_sha})",
        "blocked_reason": None,
        "old_percent": old_pct,
    }
    return tracker, changelog


def render_p1(tracker: dict) -> str:
    sys.path.insert(0, str(ROOT / "Plan" / "Tracker"))
    import tracker as tr  # type: ignore

    # render_phase_file writes to disk; capture via temp override
    phases_dir = ROOT / "Plan" / "Tracker" / "phases"
    original = tr.PHASES_DIR
    tr.PHASES_DIR = phases_dir
    try:
        tr.render_phase_file(tracker, "P1")
    finally:
        tr.PHASES_DIR = original
    return (phases_dir / "P1.md").read_text(encoding="utf-8")


def main() -> None:
    evidence_path = ROOT / EVIDENCE_REL
    if not evidence_path.is_file():
        raise SystemExit(f"missing evidence {evidence_path}; run seal first")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    self_sha = evidence["self_sha256"]

    msg_path = ROOT / MSG_REL
    msg_path.write_text(
        "evidence(ops): reseal MF-P1-09.05 local B1 restore drill from C: backup seed\n"
        "\n"
        "Re-ran robocopy restore of img_a3d2663ad90d into runtime_artifacts/b1_restore_drill "
        "and verify-package PASS for p0+p1 (D: B1 media absent; local C: backup only).\n",
        encoding="utf-8",
    )

    for attempt in range(1, 16):
        head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        head_ops = run(["git", "show", f"{head}:Plan/OPS_LOG.md"]).stdout
        if MARKER in head_ops:
            print(f"OPS_LOG already sealed on {head}; nothing to do")
            return

        head_tracker = json.loads(
            run(["git", "show", f"{head}:Plan/Tracker/tracker.json"]).stdout
        )
        tracker, changelog = update_tracker(head_tracker, EVIDENCE_REL, self_sha)
        # Render P1 from the updated tracker into WT then read for blob
        p1_text = render_p1(tracker)

        head_needs = json.loads(
            run(
                ["git", "show", f"{head}:qa/live_verification/needs_agent_actions_20260720.json"]
            ).stdout
        )
        needs = update_needs(head_needs, EVIDENCE_REL, self_sha)

        head_changelog = run(
            ["git", "show", f"{head}:Plan/Tracker/CHANGELOG.jsonl"]
        ).stdout
        if not head_changelog.endswith("\n"):
            head_changelog += "\n"
        new_changelog = head_changelog + json.dumps(changelog, ensure_ascii=False) + "\n"

        new_ops = head_ops.rstrip() + "\n" + OPS_ENTRY
        if not new_ops.endswith("\n"):
            new_ops += "\n"

        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(TMP_INDEX)
        if TMP_INDEX.exists():
            TMP_INDEX.unlink()
        run(["git", "read-tree", head], env=env)

        stage_path(env, "Plan/OPS_LOG.md", new_ops)
        stage_path(
            env,
            "Plan/Tracker/tracker.json",
            json.dumps(tracker, indent=2, ensure_ascii=False) + "\n",
        )
        stage_path(env, "Plan/Tracker/CHANGELOG.jsonl", new_changelog)
        stage_path(env, "Plan/Tracker/phases/P1.md", p1_text)
        stage_path(
            env,
            "qa/live_verification/needs_agent_actions_20260720.json",
            json.dumps(needs, indent=2, ensure_ascii=False) + "\n",
        )
        stage_path(env, EVIDENCE_REL)
        stage_path(env, SEAL_REL)
        stage_path(env, COMMIT_HELPER_REL)
        stage_path(env, MSG_REL)

        tree = run(["git", "write-tree"], env=env).stdout.strip()
        commit = run(
            ["git", "commit-tree", tree, "-p", head, "-F", str(msg_path)]
        ).stdout.strip()
        cas = run(
            ["git", "update-ref", f"refs/heads/{BRANCH}", commit, head],
            check=False,
        )
        if cas.returncode == 0:
            print(f"committed {commit} parent {head} (attempt {attempt})")
            print(f"evidence_sha={self_sha}")
            if TMP_INDEX.exists():
                TMP_INDEX.unlink()
            # Refresh default index view of HEAD without clobbering WT
            run(["git", "read-tree", "HEAD"], check=False)
            return
        print(f"CAS lost (attempt {attempt}); retrying")
        time.sleep(1.5)
    raise SystemExit("failed to land B1 restore drill commit after retries")


if __name__ == "__main__":
    main()
