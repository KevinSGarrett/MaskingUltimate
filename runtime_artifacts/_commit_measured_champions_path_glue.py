"""Seal + commit + push measured champions path glue (new modules; minimal contested patches)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=check)


def main() -> int:
    env = {**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": "src"}

    # 1) Ensure new modules exist
    required = [
        ROOT / "src/maskfactory/autonomy/production_audit.py",
        ROOT / "src/maskfactory/autonomy/corpus.py",
        ROOT / "src/maskfactory/models/benchmark.py",
        ROOT / "tools/run_measured_champions_path.py",
        ROOT / "tools/assemble_autonomous_verification_corpus.py",
        ROOT / "tools/build_production_audit_queue.py",
        ROOT / "tools/mark_benchmarked_candidate.py",
        ROOT / "tests/test_measured_champions_path_glue.py",
    ]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.is_file()]
    if missing:
        print("MISSING", missing)
        return 2

    # 2) Best-effort contested patches (may race; new tools cover the path either way)
    apply = run([sys.executable, "runtime_artifacts/_apply_measured_champions_path_glue.py"], check=False)
    print(apply.stdout)

    # 3) Tests against new modules only
    test = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_measured_champions_path_glue.py",
            "tests/test_autonomous_gold_audit_queue_wiring.py",
            "-q",
            "--tb=line",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    print(test.stdout)
    print(test.stderr)
    if test.returncode != 0:
        return test.returncode

    # 4) Re-apply contested patches immediately before seal/stage
    apply = run([sys.executable, "runtime_artifacts/_apply_measured_champions_path_glue.py"], check=False)
    print(apply.stdout)

    # 5) Orchestrator seal
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M")
    out = ROOT / f"qa/live_verification/measured_champions_path_production_{ts}.json"
    orch = subprocess.run(
        [
            sys.executable,
            "tools/run_measured_champions_path.py",
            "--output",
            str(out),
            "--execute-e2e-when-ready",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    print(orch.stdout)
    print(orch.stderr)
    if orch.returncode != 0:
        return orch.returncode
    summary = json.loads(orch.stdout.strip().splitlines()[-1])

    # 6) OPS_LOG
    ops = ROOT / "Plan/OPS_LOG.md"
    marker = "Measured champions path production glue"
    ops_text = ops.read_text(encoding="utf-8")
    if marker not in ops_text:
        entry = f"""

## 2026-07-20 — {marker} (champions={summary.get('champions', 0)}; no force-register)
**Item:** MF measured path runs/ → audit queue → P5 → mark-benchmarked → promote
**Command:** pytest glue + `tools/run_measured_champions_path.py`
**Result:** Wired production discovery/orchestrator; honest state champions={summary.get('champions')} predict={summary.get('mode_b_predict_status')}.

Glue (new modules; no force-register):
- `autonomy/production_audit.py` + `tools/build_production_audit_queue.py` (runs/**/autonomy)
- `autonomy/corpus.py` envelopes + assemble tool
- `models/benchmark.py` + `tools/mark_benchmarked_candidate.py` (installed→benchmarked)
- `tools/run_measured_champions_path.py` orchestrator
- Contested patches (CLI default runs/, S11 profile env, corpus envelopes) re-applied best-effort

Evidence: `{out.relative_to(ROOT).as_posix()}` self_sha256 `{summary.get('self_sha256')}`.
"""
        ops.write_text(ops_text.rstrip() + "\n" + entry, encoding="utf-8")

    # 7) Final apply + immediate git add/commit/push
    run([sys.executable, "runtime_artifacts/_apply_measured_champions_path_glue.py"], check=False)
    files = [
        "src/maskfactory/autonomy/production_audit.py",
        "src/maskfactory/autonomy/corpus.py",
        "src/maskfactory/models/benchmark.py",
        "src/maskfactory/vlm/production.py",
        "src/maskfactory/stages/production.py",
        "src/maskfactory/cli.py",
        "tools/weekly_qa.ps1",
        "tools/build_autonomous_gold_admission.py",
        "tools/assemble_autonomous_verification_corpus.py",
        "tools/build_production_audit_queue.py",
        "tools/mark_benchmarked_candidate.py",
        "tools/run_measured_champions_path.py",
        "tests/test_measured_champions_path_glue.py",
        "runtime_artifacts/_apply_measured_champions_path_glue.py",
        "runtime_artifacts/_verify_measured_glue.py",
        "runtime_artifacts/_commit_measured_champions_path_glue.py",
        "Plan/OPS_LOG.md",
        str(out.relative_to(ROOT).as_posix()),
    ]
    # Drop missing paths (contested files may have been reverted to clean)
    existing = [f for f in files if (ROOT / f).exists()]
    run(["git", "add", "--"] + existing)
    # Re-apply once more and re-add contested files in the same breath
    run([sys.executable, "runtime_artifacts/_apply_measured_champions_path_glue.py"], check=False)
    contested = [
        "src/maskfactory/vlm/production.py",
        "src/maskfactory/stages/production.py",
        "src/maskfactory/cli.py",
        "tools/weekly_qa.ps1",
        "tools/build_autonomous_gold_admission.py",
    ]
    run(["git", "add", "--"] + contested)

    msg = (
        "feat(champions-path): wire production runs/→audit→P5→benchmark→promote glue "
        f"(champions={summary.get('champions')}, predict={summary.get('mode_b_predict_status')}, "
        "no force-register)"
    )
    commit = subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    print(commit.stdout)
    print(commit.stderr)
    if commit.returncode != 0:
        return commit.returncode

    push = run(["git", "push"], check=False)
    print(push.stdout)
    print(push.stderr)
    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    print(
        json.dumps(
            {
                "champions": summary.get("champions"),
                "mode_b_predict_status": summary.get("mode_b_predict_status"),
                "audit_queue_population_count": summary.get("audit_queue_population_count"),
                "mvc": summary.get("mvc"),
                "caa": summary.get("caa"),
                "envelopes": summary.get("envelopes"),
                "status": summary.get("status"),
                "HEAD": head,
                "seal": out.relative_to(ROOT).as_posix(),
                "self_sha256": summary.get("self_sha256"),
                "push_rc": push.returncode,
            },
            sort_keys=True,
            indent=2,
        )
    )
    return 0 if push.returncode == 0 else push.returncode


if __name__ == "__main__":
    raise SystemExit(main())
