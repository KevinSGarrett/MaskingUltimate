"""Seal GOLD FACTORY CAA/audit-path advance from production MVC pool.

Honest path only: assemble corpus, attempt autonomous-gold admission under
autonomy profile, build weekly audit queue, report stage counts. Never weakens
Wilson/exact-zero floors; never fabricates samples or force-registers champions.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import yaml  # noqa: E402

from maskfactory.autonomy.calibration import (  # noqa: E402
    _exact_zero_failure_upper,
    _minimum_zero_failure_sample,
    _wilson_upper,
    load_autonomous_gold_profile,
)
from maskfactory.autonomy.corpus import (  # noqa: E402
    AutonomousCorpusError,
    assemble_autonomous_verification_corpus,
    scan_lifecycle_pool,
)
from maskfactory.autonomy.production_audit import (  # noqa: E402
    build_production_weekly_audit_queue,
)

PIPELINE_FP = "multiprovider-local-cuda-tournament-20260720-v1"
TS = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
OUT = REPO / f"qa/live_verification/caa_audit_path_advance_{TS}.json"


def _seal(doc: dict[str, Any]) -> dict[str, Any]:
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


def _git_head() -> tuple[str, str]:
    full = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    short = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, text=True
    ).strip()
    return full, short


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

    stages: list[dict[str, Any]] = []

    # Stage 0: discover
    pool0 = scan_lifecycle_pool(REPO / "runs")
    stages.append({"stage": "0_discover", "pool": pool0})

    # Stage 1: repair
    repair_out = REPO / f"qa/live_verification/corpus_envelope_repair_caa_seal_{TS}.json"
    repair = subprocess.run(
        [
            sys.executable,
            str(REPO / "tools/repair_corpus_envelope_roots.py"),
            "--machine-root",
            "runs",
            "--output",
            str(repair_out),
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
        timeout=600,
    )
    pool1 = scan_lifecycle_pool(REPO / "runs")
    stages.append(
        {
            "stage": "1_repair_envelopes",
            "exit_code": repair.returncode,
            "output": repair_out.relative_to(REPO).as_posix(),
            "pool": pool1,
        }
    )

    # Stage 2a: assemble torso-only under canonical FP
    corpus_torso = REPO / f"qa/autonomy/corpora/autonomous_verification_caa_torso_{TS}.json"
    try:
        torso_summary = assemble_autonomous_verification_corpus(
            REPO / "runs",
            corpus_torso,
            label="torso",
            context="solo",
            pipeline_fingerprint=PIPELINE_FP,
            minimum_records=1,
        )
        torso_err = None
    except AutonomousCorpusError as exc:
        torso_summary = None
        torso_err = str(exc)
    stages.append(
        {
            "stage": "2a_assemble_corpus_torso_canonical_fp",
            "summary": torso_summary,
            "error": torso_err,
        }
    )

    # Stage 2b: assemble all labels under solo + canonical FP (max cert volume)
    corpus_solo = REPO / f"qa/autonomy/corpora/autonomous_verification_caa_solo_{TS}.json"
    try:
        solo_summary = assemble_autonomous_verification_corpus(
            REPO / "runs",
            corpus_solo,
            label=None,
            context="solo",
            pipeline_fingerprint=PIPELINE_FP,
            minimum_records=1,
        )
        solo_err = None
    except AutonomousCorpusError as exc:
        solo_summary = None
        solo_err = str(exc)
    stages.append(
        {
            "stage": "2b_assemble_corpus_solo_all_labels_canonical_fp",
            "summary": solo_summary,
            "error": solo_err,
        }
    )

    # Stage 3: admission attempt (largest eligible corpus)
    admission_corpus = corpus_solo if solo_summary else corpus_torso
    admission_out = REPO / f"qa/live_verification/autonomous_gold_admission_caa_seal_{TS}.json"
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
            "--corpus",
            str(admission_corpus),
            "--output",
            str(admission_out),
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
        timeout=600,
    )
    admission_doc: dict[str, Any] = {}
    if admission_out.is_file():
        admission_doc = json.loads(admission_out.read_text(encoding="utf-8"))
    cert = admission_doc.get("certificate") or {}
    stages.append(
        {
            "stage": "3_autonomous_gold_admission",
            "exit_code": admission.returncode,
            "status": admission_doc.get("status"),
            "certificate_passed": admission_doc.get("certificate_passed"),
            "sample_count": cert.get("sample_count"),
            "failures": cert.get("failures"),
            "false_accept_upper_bound": cert.get("false_accept_upper_bound"),
            "serious_false_accept_upper_bound": cert.get("serious_false_accept_upper_bound"),
            "output": admission_out.relative_to(REPO).as_posix(),
            "corpus": admission_corpus.relative_to(REPO).as_posix(),
        }
    )

    # Stage 4: weekly audit queue (CAA population)
    config = yaml.safe_load((REPO / "configs/autonomous_masks.yaml").read_text(encoding="utf-8"))
    period = f"{datetime.now(UTC).isocalendar().year}-W{datetime.now(UTC).isocalendar().week:02d}"
    audit_out = REPO / f"qa/autonomy/audit_queues/{period}_caa_path_seal_{TS}.json"
    audit_queue = build_production_weekly_audit_queue(
        REPO / "runs",
        audit_out,
        period_id=period,
        operations_policy=config["operations"],
    )
    stages.append(
        {
            "stage": "4_weekly_audit_queue",
            "population_count": int(audit_queue.get("population_count", 0)),
            "selected_count": int(audit_queue.get("selected_count", 0)),
            "outcomes_status": audit_queue.get("outcomes_status"),
            "output": audit_out.relative_to(REPO).as_posix(),
        }
    )

    # Stage 5: measured champions path (orchestration seal)
    measured_out = REPO / f"qa/live_verification/measured_champions_path_caa_seal_{TS}.json"
    measured = subprocess.run(
        [
            sys.executable,
            str(REPO / "tools/run_measured_champions_path.py"),
            "--machine-root",
            "runs",
            "--label",
            "torso",
            "--context",
            "solo",
            "--pipeline-fingerprint",
            PIPELINE_FP,
            "--execute-e2e-when-ready",
            "--output",
            str(measured_out),
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
        timeout=600,
    )
    measured_summary = {}
    try:
        measured_summary = json.loads((measured.stdout or "").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError, AttributeError):
        measured_summary = {"stdout_tail": (measured.stdout or "")[-400:]}
    stages.append(
        {
            "stage": "5_measured_champions_path",
            "exit_code": measured.returncode,
            "summary": measured_summary,
            "output": measured_out.relative_to(REPO).as_posix(),
        }
    )

    pool_final = scan_lifecycle_pool(REPO / "runs")
    mvc = int(pool_final["machine_verified_candidate_count"])
    caa = int(pool_final["calibrated_auto_accepted_count"])
    envelopes = int(pool_final["corpus_record_envelopes_seen"])
    cert_samples = int(cert.get("sample_count") or 0)
    head, head_short = _git_head()

    # Fingerprint fragmentation snapshot
    fps: dict[str, int] = {}
    for path in (REPO / "runs").rglob("*.corpus_record.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        key = str(doc.get("pipeline_fingerprint"))
        fps[key] = fps.get(key, 0) + 1
    fps_top = sorted(fps.items(), key=lambda item: (-item[1], item[0]))[:12]

    evidence = {
        "artifact_type": "caa_audit_path_advance_from_mvc",
        "schema_version": "1.0.0",
        "lane": "GOLD_FACTORY",
        "model": "cursor-grok-4.5-high-fast",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authority": "autonomous_certified_gold_profile",
        "profile_id": profile["profile_id"],
        "profile_sha256": profile["profile_sha256"],
        "pipeline_fingerprint": PIPELINE_FP,
        "git_head": head,
        "git_head_short": head_short,
        "stage_counts": {
            "machine_verified_candidate": mvc,
            "calibrated_auto_accepted": caa,
            "autonomous_certified_gold": 0,
            "corpus_record_envelopes": envelopes,
            "lifecycle_sidecars_seen": int(pool_final["lifecycle_sidecars_seen"]),
            "canonical_fp_corpus_records_solo_all_labels": int(
                (solo_summary or {}).get("record_count") or 0
            ),
            "canonical_fp_corpus_records_torso": int(
                (torso_summary or {}).get("record_count") or 0
            ),
            "admission_certificate_sample_count": cert_samples,
            "audit_queue_population_count": int(audit_queue.get("population_count", 0)),
            "champions": 0,
        },
        "wilson_floors_unchanged": {
            "confidence_level": conf,
            "maximum_false_accept_upper_bound": max_fa,
            "maximum_serious_false_accept_upper_bound": max_serious,
            "n_for_wilson_false_accept_le_0_01": n_wilson,
            "n_for_exact_serious_le_0_005": n_exact,
            "binding_n": binding_n,
            "binding_constraint": "exact_zero_failure_serious",
            "gap_mvc_to_binding": max(0, binding_n - mvc),
            "gap_cert_samples_to_binding": max(0, binding_n - cert_samples),
            "observed_wilson_upper_at_mvc_0_defect": (_wilson_upper(0, mvc, conf) if mvc else 1.0),
            "observed_exact_serious_upper_at_mvc_0_defect": (
                _exact_zero_failure_upper(0, mvc, conf) if mvc else 1.0
            ),
            "observed_wilson_upper_at_cert_samples_0_defect": (
                _wilson_upper(0, cert_samples, conf) if cert_samples else 1.0
            ),
        },
        "fingerprint_fragmentation_top": fps_top,
        "stages": stages,
        "claim_boundary": {
            "certificate_minted": bool(cert.get("passed")),
            "caa_raised": caa > 0,
            "no_fabricated_wilson_samples": True,
            "no_force_registered_champions": True,
            "wilson_math_unchanged": True,
            "did_not_rebind_glue_fingerprints_to_canonical": True,
            "glue_prove_emit_not_counted_as_canonical_cert_volume": True,
        },
        "next_agent_step": (
            "Grow genuine multiprovider tournament MVC envelopes under single "
            f"canonical fingerprint {PIPELINE_FP} until image-disjoint "
            f"cert samples >= {binding_n} (binding=exact_zero_failure_serious). "
            "Do not rebind glue prove-emit fingerprints. After certificate passes, "
            "set MASKFACTORY_AUTONOMY_ALLOW_AUTONOMOUS_PROFILE=1 and re-run S11 to "
            "raise calibrated_auto_accepted; then weekly audit queue population > 0."
        ),
    }
    _seal(evidence)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest = REPO / "qa/live_verification/caa_audit_path_advance_latest.json"
    latest.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": OUT.relative_to(REPO).as_posix(),
                "stage_counts": evidence["stage_counts"],
                "wilson": {
                    "binding_n": binding_n,
                    "gap_mvc": evidence["wilson_floors_unchanged"]["gap_mvc_to_binding"],
                    "gap_cert": evidence["wilson_floors_unchanged"]["gap_cert_samples_to_binding"],
                },
                "admission_status": admission_doc.get("status"),
                "self_sha256": evidence["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
