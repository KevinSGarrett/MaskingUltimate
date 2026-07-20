"""Seal exact Wilson / binding gap for authoritative MVC~43-51 band.

Honesty: real post-hard-QA / peak MVC is authoritative; glue pool is not.
No fabricated samples; no certificate mint.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import NormalDist

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from maskfactory.autonomy.calibration import (  # noqa: E402
    _exact_zero_failure_upper,
    _minimum_zero_failure_sample,
    _wilson_upper,
    load_autonomous_gold_profile,
)
from maskfactory.autonomy.corpus import scan_lifecycle_pool  # noqa: E402

TS = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
CRIT_PATH = REPO / "qa/live_verification/gold_factory_critical_status_20260720T171840Z.json"
PIPELINE_FP = "multiprovider-local-cuda-tournament-20260720-v1"


def _seal(doc: dict) -> dict:
    doc.pop("self_sha256", None)
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    doc["self_sha256"] = hashlib.sha256(payload).hexdigest()
    return doc


def _min_wilson_n(max_fa: float, conf: float) -> int:
    n = 1
    while n <= 100_000:
        if _wilson_upper(0, n, conf) <= max_fa:
            return n
        n += 1
    raise RuntimeError("wilson search failed")


def _gap_block(mvc: int, n_wilson: int, n_exact: int, binding_n: int, conf: float) -> dict:
    return {
        "mvc": mvc,
        "gap_to_wilson_floor": max(0, n_wilson - mvc),
        "gap_to_exact_serious_floor": max(0, n_exact - mvc),
        "gap_to_binding_floor": max(0, binding_n - mvc),
        "wilson_false_accept_upper_0_defect": _wilson_upper(0, mvc, conf) if mvc else 1.0,
        "exact_serious_upper_0_defect": _exact_zero_failure_upper(0, mvc, conf) if mvc else 1.0,
    }


def main() -> int:
    profile = load_autonomous_gold_profile()
    floors = profile["statistical_floors"]
    conf = float(floors["confidence_level"])
    max_fa = float(floors["maximum_false_accept_upper_bound"])
    max_serious = float(floors["maximum_serious_false_accept_upper_bound"])
    min_bucket = int(floors["minimum_autonomous_verified_per_risk_bucket"])

    n_wilson = _min_wilson_n(max_fa, conf)
    n_exact = _minimum_zero_failure_sample(max_serious, conf)
    binding_n = max(min_bucket, n_wilson, n_exact)
    binding_constraint = (
        "exact_zero_failure_serious"
        if n_exact == binding_n
        else (
            "one_sided_wilson_false_accept" if n_wilson == binding_n else "minimum_per_risk_bucket"
        )
    )

    crit = json.loads(CRIT_PATH.read_text(encoding="utf-8"))
    mvc_live = int(crit["mvc"]["post_hard_qa_live_approx"])
    mvc_peak = int(crit["mvc"]["peak_reported"])
    mvc_real_fp = int(crit["mvc"]["pool_unique_real_multiprovider_fp"])

    pool = scan_lifecycle_pool(REPO / "runs")
    pool_mvc = int(pool["machine_verified_candidate_count"])

    admission_out = REPO / f"qa/live_verification/autonomous_gold_admission_mvc43_51_{TS}.json"
    admission = subprocess.run(
        [
            sys.executable,
            str(REPO / "tools/build_autonomous_gold_admission.py"),
            "--label",
            "torso",
            "--context",
            "solo",
            "--pipeline-fingerprint",
            PIPELINE_FP,
            "--machine-root",
            "runs",
            "--output",
            str(admission_out),
        ],
        cwd=str(REPO),
        text=True,
        capture_output=True,
        check=False,
        timeout=600,
    )
    adm_status = "unknown"
    try:
        adm_status = json.loads(admission.stdout.strip().splitlines()[-1]).get("status", "unknown")
    except (json.JSONDecodeError, IndexError, AttributeError):
        if admission_out.is_file():
            adm_status = json.loads(admission_out.read_text(encoding="utf-8")).get(
                "status", "unknown"
            )

    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO), text=True).strip()
    head_short = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO), text=True
    ).strip()

    wilson_gap_43 = max(0, n_wilson - mvc_live)
    wilson_gap_51 = max(0, n_wilson - mvc_peak)
    binding_gap_43 = max(0, binding_n - mvc_live)
    binding_gap_51 = max(0, binding_n - mvc_peak)

    evidence = {
        "artifact_type": "wilson_sample_gap_to_autonomous_certified_gold",
        "schema_version": "1.1.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authority": "autonomous_certified_gold_profile",
        "lane": "GOLD_FACTORY",
        "model": "cursor-grok-4.5-high-fast",
        "git_head": head,
        "git_head_short": head_short,
        "pipeline_fingerprint": PIPELINE_FP,
        "profile_id": profile["profile_id"],
        "profile_sha256": profile["profile_sha256"],
        "mvc_band": {
            "label": "MVC~43-51",
            "post_hard_qa_live": mvc_live,
            "peak_reported": mvc_peak,
            "pool_unique_real_multiprovider_fp": mvc_real_fp,
            "source_status": str(CRIT_PATH.relative_to(REPO)).replace("\\", "/"),
        },
        "authoritative_gaps": {
            "at_mvc_43_post_hard_qa_live": _gap_block(mvc_live, n_wilson, n_exact, binding_n, conf),
            "at_mvc_51_peak": _gap_block(mvc_peak, n_wilson, n_exact, binding_n, conf),
            "primary_report_mvc": mvc_live,
            "exact_wilson_gap_primary": wilson_gap_43,
            "exact_wilson_gap_at_peak_51": wilson_gap_51,
            "exact_binding_gap_primary": binding_gap_43,
            "exact_binding_gap_at_peak_51": binding_gap_51,
            "formula": (
                "gap = max(0, floor_n - mvc); wilson_floor=n_for_FA_UB<=0.01; "
                "binding=max(min_bucket,n_wilson,n_exact)"
            ),
        },
        "pool_scan_inflated_not_authoritative_for_real_feed": {
            "machine_verified_candidate_count": pool_mvc,
            "note": (
                "includes prove-emit/tournament-emit glue; " "not real multiprovider feed coverage"
            ),
            "gap_to_wilson_floor_if_counted": max(0, n_wilson - pool_mvc),
            "gap_to_binding_floor_if_counted": max(0, binding_n - pool_mvc),
        },
        "autonomous_certified_gold": 0,
        "calibrated_auto_accepted": 0,
        "statistical_floors": {
            "confidence_level": conf,
            "minimum_autonomous_verified_per_risk_bucket": min_bucket,
            "maximum_false_accept_upper_bound": max_fa,
            "aggregate_false_accept_bound_method": "one_sided_wilson",
            "maximum_serious_false_accept_upper_bound": max_serious,
            "serious_false_accept_bound_method": "exact_zero_failure",
            "z_one_sided": NormalDist().inv_cdf(conf),
        },
        "zero_defect_requirements": {
            "n_for_wilson_false_accept_le_0_01": n_wilson,
            "wilson_upper_at_n": _wilson_upper(0, n_wilson, conf),
            "n_for_exact_serious_le_0_005": n_exact,
            "exact_upper_at_n": _exact_zero_failure_upper(0, n_exact, conf),
            "binding_n": binding_n,
            "binding_constraint": binding_constraint,
        },
        "admission": {
            "status": adm_status,
            "exit_code": admission.returncode,
            "output": str(admission_out.relative_to(REPO)).replace("\\", "/"),
            "certificate_minted": False,
        },
        "claim_boundary": {
            "certificate_minted": False,
            "no_fabricated_wilson_samples": True,
            "no_force_registered_champions": True,
            "mvc_is_not_autonomous_certified_gold": True,
            "wilson_math_unchanged": True,
            "glue_emit_not_real_mvc_coverage": True,
            "authoritative_mvc_band_is_43_to_51": True,
        },
        "next_agent_step": (
            f"Grow real multiprovider MVC from {mvc_live} toward binding_n={binding_n} "
            f"(Wilson floor {n_wilson} gap={wilson_gap_43}; binding gap={binding_gap_43}). "
            "Continue GPU-seq tournament on remaining feed; assemble image-disjoint "
            "corpus; re-run admission --corpus."
        ),
    }
    evidence = _seal(evidence)
    out = REPO / f"qa/live_verification/wilson_gap_mvc43_51_{TS}.json"
    latest = REPO / "qa/live_verification/wilson_gap_mvc43_51_latest.json"
    text = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    out.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    print(
        json.dumps(
            {
                "mvc_live_43": mvc_live,
                "mvc_peak_51": mvc_peak,
                "wilson_gap_at_43": wilson_gap_43,
                "wilson_gap_at_51": wilson_gap_51,
                "binding_gap_at_43": binding_gap_43,
                "binding_gap_at_51": binding_gap_51,
                "n_wilson": n_wilson,
                "n_exact": n_exact,
                "binding_n": binding_n,
                "admission": adm_status,
                "gold": 0,
                "pool_inflated": pool_mvc,
                "output": str(out.relative_to(REPO)).replace("\\", "/"),
                "self_sha256": evidence["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
