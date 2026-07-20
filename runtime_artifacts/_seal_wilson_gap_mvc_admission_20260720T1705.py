"""Seal exact Wilson / exact-zero sample gap for autonomous_certified_gold.

Honest quantification only — does not fabricate samples or mint certificates.
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
OUT = REPO / f"qa/live_verification/wilson_sample_gap_mvc_{TS}.json"
ADMISSION_OUT = REPO / f"qa/live_verification/autonomous_gold_admission_wilson_gap_{TS}.json"
REPAIR_OUT = REPO / f"qa/live_verification/corpus_envelope_repair_wilson_gap_{TS}.json"
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


def main() -> int:
    profile = load_autonomous_gold_profile()
    floors = profile["statistical_floors"]
    conf = float(floors["confidence_level"])
    max_fa = float(floors["maximum_false_accept_upper_bound"])
    max_serious = float(floors["maximum_serious_false_accept_upper_bound"])
    min_bucket = int(floors["minimum_autonomous_verified_per_risk_bucket"])

    pool = scan_lifecycle_pool(REPO / "runs")
    mvc = int(pool["machine_verified_candidate_count"])

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
    gap = max(0, binding_n - mvc)
    wilson_gap = max(0, n_wilson - mvc)
    exact_gap = max(0, n_exact - mvc)

    # Repair envelopes under production runs/
    repair = subprocess.run(
        [
            sys.executable,
            str(REPO / "tools/repair_corpus_envelope_roots.py"),
            "--machine-root",
            "runs",
            "--output",
            str(REPAIR_OUT),
        ],
        cwd=str(REPO),
        text=True,
        capture_output=True,
        check=False,
        timeout=600,
    )

    # Re-scan after repair
    pool_after = scan_lifecycle_pool(REPO / "runs")
    mvc_after = int(pool_after["machine_verified_candidate_count"])
    gap_after = max(0, binding_n - mvc_after)

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
            str(ADMISSION_OUT),
        ],
        cwd=str(REPO),
        text=True,
        capture_output=True,
        check=False,
        timeout=600,
    )
    admission_status = "unknown"
    try:
        admission_status = json.loads(admission.stdout.strip().splitlines()[-1]).get(
            "status", "unknown"
        )
    except (json.JSONDecodeError, IndexError, AttributeError):
        if ADMISSION_OUT.is_file():
            admission_status = json.loads(ADMISSION_OUT.read_text(encoding="utf-8")).get(
                "status", "unknown"
            )

    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO), text=True).strip()
    head_short = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO), text=True
    ).strip()

    z = NormalDist().inv_cdf(conf)
    evidence = {
        "artifact_type": "wilson_sample_gap_to_autonomous_certified_gold",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authority": "autonomous_certified_gold_profile",
        "lane": "GOLD_FACTORY",
        "git_head": head,
        "git_head_short": head_short,
        "pipeline_fingerprint": PIPELINE_FP,
        "profile_id": profile["profile_id"],
        "profile_sha256": profile["profile_sha256"],
        "mvc_gate": {"required_minimum": 33, "met": mvc_after >= 33},
        "pool_before_repair": pool,
        "pool_after_repair": pool_after,
        "mvc": mvc_after,
        "envelopes": int(pool_after["corpus_record_envelopes_seen"]),
        "calibrated_auto_accepted": int(pool_after["calibrated_auto_accepted_count"]),
        "autonomous_certified_gold": 0,
        "statistical_floors": {
            "confidence_level": conf,
            "minimum_autonomous_verified_per_risk_bucket": min_bucket,
            "maximum_false_accept_upper_bound": max_fa,
            "aggregate_false_accept_bound_method": "one_sided_wilson",
            "maximum_serious_false_accept_upper_bound": max_serious,
            "serious_false_accept_bound_method": "exact_zero_failure",
            "z_one_sided": z,
        },
        "zero_defect_requirements": {
            "n_for_wilson_false_accept_le_0_01": n_wilson,
            "wilson_upper_at_n": _wilson_upper(0, n_wilson, conf),
            "n_for_exact_serious_le_0_005": n_exact,
            "exact_upper_at_n": _exact_zero_failure_upper(0, n_exact, conf),
            "binding_n": binding_n,
            "binding_constraint": binding_constraint,
        },
        "observed_bounds_at_current_mvc": {
            "mvc": mvc_after,
            "wilson_false_accept_upper_0_defect": (
                _wilson_upper(0, mvc_after, conf) if mvc_after else 1.0
            ),
            "exact_serious_upper_0_defect": (
                _exact_zero_failure_upper(0, mvc_after, conf) if mvc_after else 1.0
            ),
        },
        "exact_sample_gap": {
            "gap_to_binding_floor": gap_after,
            "gap_to_wilson_floor": max(0, n_wilson - mvc_after),
            "gap_to_exact_serious_floor": max(0, n_exact - mvc_after),
            "formula": "gap = max(0, binding_n - mvc) with binding_n = max(min_bucket, n_wilson, n_exact)",
            "pre_repair_gap_binding": gap,
            "pre_repair_gap_wilson": wilson_gap,
            "pre_repair_gap_exact": exact_gap,
        },
        "admission": {
            "status": admission_status,
            "exit_code": admission.returncode,
            "output": str(ADMISSION_OUT.relative_to(REPO)).replace("\\", "/"),
            "certificate_minted": False,
        },
        "repair": {
            "exit_code": repair.returncode,
            "output": str(REPAIR_OUT.relative_to(REPO)).replace("\\", "/"),
            "stdout_tail": (repair.stdout or "")[-500:],
        },
        "claim_boundary": {
            "certificate_minted": False,
            "no_fabricated_wilson_samples": True,
            "no_force_registered_champions": True,
            "mvc_is_not_autonomous_certified_gold": True,
            "wilson_math_unchanged": True,
        },
        "next_agent_step": (
            f"Emit/repair genuine machine_verified_candidate envelopes until MVC>={binding_n} "
            f"(binding={binding_constraint}); current gap={gap_after}. Run visual+VLM critic on "
            "real MVC; then assemble image-disjoint corpus and re-run admission --corpus."
        ),
    }
    evidence = _seal(evidence)
    OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "mvc": mvc_after,
                "gold": 0,
                "gap_binding": gap_after,
                "binding_n": binding_n,
                "binding_constraint": binding_constraint,
                "n_wilson": n_wilson,
                "n_exact": n_exact,
                "admission": admission_status,
                "head": head_short,
                "output": str(OUT.relative_to(REPO)).replace("\\", "/"),
                "self_sha256": evidence["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0 if mvc_after >= 33 else 1


if __name__ == "__main__":
    raise SystemExit(main())
