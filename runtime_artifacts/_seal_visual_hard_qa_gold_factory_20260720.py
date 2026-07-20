"""Seal GOLD FACTORY visual/hard QA lane progress (honest counts)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    mvc = 0
    vlm_pass = 0
    residual_visual = 0
    pass_ids: list[str] = []
    for p in (REPO / "runs").rglob("autonomy/torso.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        status = d.get("status")
        image_id = str(d.get("image_id") or "")
        if status == "machine_verified_candidate":
            mvc += 1
            rev_path = p.with_name("torso.visual_hard_qa.json")
            if rev_path.is_file():
                try:
                    rev = json.loads(rev_path.read_text(encoding="utf-8"))
                except Exception:
                    rev = {}
                if rev.get("outcome") == "VISUAL_HARD_QA_PASS_BOUNDED":
                    vlm_pass += 1
                    pass_ids.append(image_id)
        elif status == "residual_human_queue" and "visual_hard" in str(
            d.get("reason") or ""
        ):
            residual_visual += 1

    admission_path = (
        REPO
        / "qa/live_verification/autonomous_gold_admission_after_visual_20260720T122023.json"
    )
    main_qa = (
        REPO / "qa/live_verification/tournament_mvc_visual_hard_qa_20260720T1153.json"
    )
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    cert = admission.get("certificate") or {}
    head = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO)
        .decode()
        .strip()
    )

    evidence = {
        "artifact_type": "gold_factory_visual_hard_qa_lane",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "lane": "GOLD_FACTORY_visual_hard_qa",
        "model": "cursor-grok-4.5-high-fast",
        "git_head": head,
        "honesty": [
            "NOT draft-corpus VISUAL_QA_REVIEWED_WITH_DEFECTS theater",
            "Ollama qwen2.5vl:7b critic-only (may_author_masks=false, may_approve_gold=false)",
            "autonomous_certified_gold remains 0 until Wilson floors clear",
        ],
        "counts": {
            "machine_verified_candidate": mvc,
            "visual_hard_qa_pass_bounded": vlm_pass,
            "residual_demoted_by_visual_hard_qa": residual_visual,
            "autonomous_certified_gold": 0,
            "admission_sample_count": cert.get("sample_count"),
            "admission_false_accept_upper_bound": cert.get("false_accept_upper_bound"),
        },
        "vlm_pass_image_ids": sorted(pass_ids),
        "primary_visual_qa_seal": str(main_qa.relative_to(REPO)).replace("\\", "/"),
        "primary_visual_qa_sha256": _sha(main_qa) if main_qa.is_file() else None,
        "admission_seal": str(admission_path.relative_to(REPO)).replace("\\", "/"),
        "admission_status": admission.get("status"),
        "admission_failures": cert.get("failures"),
        "certificate_minted": bool(
            (admission.get("claim_boundary") or {}).get("certificate_minted")
        ),
        "blocker": (
            "wilson_false_accept_upper_bound_exceeded_n31_need_approx_270_zero_defect"
            if cert.get("failures")
            else None
        ),
        "tooling_fixes": [
            "tools/run_tournament_mvc_visual_hard_qa.py: broader source index, "
            "skip existing pass sidecars, no demote on source index gap, "
            "Ollama transport retries, discover emit_prove/autonomous_gold roots",
        ],
        "next_agent_step": (
            "Keep tournament emitting MVC; re-run visual/hard QA on new winners; "
            "grow image-disjoint VLM-passed corpus toward Wilson n≈270 zero-defect "
            "before autonomous_certified_gold can mint."
        ),
    }
    out = (
        REPO
        / "qa/live_verification/gold_factory_visual_hard_qa_lane_20260720T1222.json"
    )
    raw = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    evidence["self_sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest = REPO / "qa/live_verification/gold_factory_visual_hard_qa_lane_latest.json"
    latest.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(out.relative_to(REPO)).replace("\\", "/"),
                "counts": evidence["counts"],
                "blocker": evidence["blocker"],
                "self_sha256": evidence["self_sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
