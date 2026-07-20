"""Production measured-champions-path orchestrator (fail-closed, no force-register).

Wires REAL tournament outputs under ``runs/`` through:

  1. discover machine_verified_candidate / calibrated_auto_accepted + corpus envelopes
  2. assemble frozen image-disjoint corpus (when envelopes exist)
  3. build weekly audit queue from production ``runs/`` (CAA population)
  4. report P5 / shadow / promote readiness (never mutates champions)

When siblings have not yet produced >=3-family MVC envelopes, this tool seals an
honest ``AWAITING_RUNTIME`` / ``insufficient`` report with champions=0.

Usage:
  python tools/run_measured_champions_path.py \\
      --output qa/live_verification/measured_champions_path_<ts>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from maskfactory.autonomy.corpus import (  # noqa: E402
    AutonomousCorpusError,
    assemble_autonomous_verification_corpus,
    scan_lifecycle_pool,
)
from maskfactory.autonomy.production_audit import (  # noqa: E402
    build_production_weekly_audit_queue,
)
from maskfactory.models.registry import champion_status  # noqa: E402

ARTIFACT_TYPE = "measured_champions_path_production"
SCHEMA_VERSION = "1.0.0"
EVIDENCE_TIER = "RUNTIME_PASS_BOUNDED"


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _seal(evidence: dict[str, Any]) -> dict[str, Any]:
    evidence.pop("self_sha256", None)
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    return evidence


def _period_id(now: datetime) -> str:
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def run_path(
    *,
    machine_root: Path,
    output: Path,
    label: str,
    context: str,
    pipeline_fingerprint: str | None,
    period_id: str | None,
    execute_e2e_when_ready: bool,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    period = period_id or _period_id(now)
    pool = scan_lifecycle_pool(machine_root)
    champions = champion_status(
        registry_path=REPO_ROOT / "models" / "model_registry.json",
        history_path=REPO_ROOT / "runs" / "champion_history.jsonl",
    )
    champion_count = len(champions["champions"])

    stages: list[dict[str, Any]] = []
    corpus_summary: dict[str, Any] | None = None
    audit_queue: dict[str, Any] | None = None
    status = "awaiting_tournament_candidates"
    next_step = (
        "Sibling multi-provider GPU tournament must emit machine_verified_candidate "
        "sidecars under runs/**/autonomy/ with companion *.corpus_record.json envelopes "
        "(>=3 independent families). Then re-run this tool; champions>0 only via "
        "measured promote_custom_segmenter_role — never force-register."
    )

    stages.append(
        {
            "stage": "1_discover",
            "role": "scan production runs/ autonomy lifecycle + corpus envelopes",
            "tier": "RUNTIME_PASS_BOUNDED",
            "pool": pool,
        }
    )

    family_ready = False
    if pool["corpus_record_envelopes_seen"] > 0:
        try:
            corpus_path = (
                REPO_ROOT
                / "qa"
                / "autonomy"
                / "corpora"
                / f"autonomous_verification_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
            )
            corpus_summary = assemble_autonomous_verification_corpus(
                machine_root,
                corpus_path,
                label=label,
                context=context,
                pipeline_fingerprint=pipeline_fingerprint,
                minimum_records=1,
            )
            family_ready = int(corpus_summary.get("max_independent_family_count", 0)) >= 3
            stages.append(
                {
                    "stage": "2_assemble_corpus",
                    "role": "frozen image-disjoint autonomous-verification corpus",
                    "tier": "RUNTIME_PASS_BOUNDED" if family_ready else "INSUFFICIENT_FAMILIES",
                    "summary": corpus_summary,
                }
            )
            if family_ready:
                status = "corpus_ready_awaiting_certificate_volume"
                next_step = (
                    "Re-run tools/build_autonomous_gold_admission.py --corpus "
                    f"{corpus_path.as_posix()} once sample floor is met; place cert under "
                    "qa/autonomy/certificates; set "
                    "MASKFACTORY_AUTONOMY_ALLOW_AUTONOMOUS_PROFILE=1 and re-run S11 to "
                    "raise CAA; then audit-queue → P5 → mark-benchmarked → "
                    "promote-custom-segmenter."
                )
            else:
                status = "insufficient_independent_families"
        except AutonomousCorpusError as exc:
            stages.append(
                {
                    "stage": "2_assemble_corpus",
                    "role": "frozen image-disjoint autonomous-verification corpus",
                    "tier": "FAIL_CLOSED",
                    "error": str(exc),
                }
            )
            status = "corpus_assembly_failed"
    else:
        stages.append(
            {
                "stage": "2_assemble_corpus",
                "role": "frozen image-disjoint autonomous-verification corpus",
                "tier": "AWAITING_RUNTIME",
                "note": "no *.corpus_record.json envelopes beside production autonomy sidecars",
            }
        )

    config = yaml.safe_load(
        (REPO_ROOT / "configs" / "autonomous_masks.yaml").read_text(encoding="utf-8")
    )
    audit_output = (
        REPO_ROOT / "qa" / "autonomy" / "audit_queues" / f"{period}_measured_path_probe.json"
    )
    audit_queue = build_production_weekly_audit_queue(
        machine_root,
        audit_output,
        period_id=period,
        operations_policy=config["operations"],
    )
    stages.append(
        {
            "stage": "3_audit_queue",
            "role": "build_weekly_audit_queue from production runs/",
            "tier": (
                "RUNTIME_PASS_BOUNDED"
                if int(audit_queue.get("population_count", 0)) > 0
                else "EMPTY_POPULATION"
            ),
            "population_count": int(audit_queue.get("population_count", 0)),
            "selected_count": int(audit_queue.get("selected_count", 0)),
            "outcomes_status": audit_queue.get("outcomes_status"),
            "output": audit_output.relative_to(REPO_ROOT).as_posix(),
        }
    )

    stages.append(
        {
            "stage": "4_p5_register",
            "role": "register_training_candidate -> challenger_bodypart only",
            "tier": "READY_WHEN_TRAINING_COMPLETE",
            "note": (
                "CLI: maskfactory models register-training-candidate <run> <key>. "
                "Refuses champion_* (no force-register)."
            ),
            "execute_e2e": False,
        }
    )
    stages.append(
        {
            "stage": "5_shadow_benchmark",
            "role": "mark-benchmarked (installed -> benchmarked)",
            "tier": "READY_WHEN_CERTIFICATE_EXISTS",
            "note": (
                "CLI: maskfactory models mark-benchmarked <key> --certificate <cert.json>. "
                "Requires validated custom-segmenter certificate; never assigns champion_*."
            ),
            "execute_e2e": False,
        }
    )
    stages.append(
        {
            "stage": "6_promote",
            "role": "promote_custom_segmenter_role (smoke-first, transactional)",
            "tier": "READY_WHEN_BENCHMARKED_PLUS_MATRIX_BUNDLE",
            "note": (
                "CLI: maskfactory models promote-custom-segmenter <key> --matrix-bundle <dir>. "
                "Not executed by this orchestrator; force-register forbidden."
            ),
            "execute_e2e": bool(
                execute_e2e_when_ready
                and family_ready
                and int(audit_queue.get("population_count", 0)) > 0
                and champion_count == 0
            ),
        }
    )

    if (
        execute_e2e_when_ready
        and family_ready
        and pool["machine_verified_candidate_count"] + pool["calibrated_auto_accepted_count"] >= 3
    ):
        status = "e2e_ready_partial"
        next_step = (
            "Corpus + audit path live with >=3-family envelopes. Complete admission sample "
            "floor, S11 CAA raise, P5 train/register, mark-benchmarked, then "
            "promote-custom-segmenter. champions remain 0 until promote succeeds."
        )

    mode_b_predict = (
        "RUNTIME_PASS_BOUNDED" if champion_count > 0 else "AWAITING_RUNTIME"
    )
    evidence = {
        "artifact_type": ARTIFACT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "evidence_tier": EVIDENCE_TIER if family_ready else "AWAITING_RUNTIME",
        "recorded_at": now.isoformat().replace("+00:00", "Z"),
        "git_head": _git_head(),
        "status": status,
        "scope": {
            "label": label,
            "context": context,
            "pipeline_fingerprint": pipeline_fingerprint,
            "period_id": period,
            "machine_root": str(machine_root),
        },
        "measured_path_stages": stages,
        "production_honest_state": {
            "production_champion_count": champion_count,
            "production_champions": champions["champions"],
            "production_champion_history_rows": len(champions["history"]),
            "production_audit_queue_population_count": int(
                audit_queue.get("population_count", 0)
            ),
            "production_autonomy_lifecycle_sidecars_in_runs": pool["lifecycle_sidecars_seen"],
            "production_corpus_record_envelopes": pool["corpus_record_envelopes_seen"],
            "mode_b_predict_status": mode_b_predict,
            "mode_b_predict_reason": (
                "champions configured"
                if champion_count > 0
                else "champion prediction provider is not configured (champions=0)"
            ),
        },
        "corpus_summary": corpus_summary,
        "claim_boundary": {
            "no_champion_force_registered": True,
            "no_champion_registered_by_this_tool": True,
            "does_not_mutate_model_registry_roles": True,
            "wilson_math_unchanged": True,
            "promotion_requires_mark_benchmarked_plus_matrix_bundle": True,
            "audit_queue_root_is_production_runs": True,
        },
        "next_agent_step": next_step,
    }
    _seal(evidence)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine-root", type=Path, default=REPO_ROOT / "runs")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", default="torso")
    parser.add_argument("--context", default="solo")
    parser.add_argument("--pipeline-fingerprint", default=None)
    parser.add_argument("--period-id", default=None)
    parser.add_argument(
        "--execute-e2e-when-ready",
        action="store_true",
        help="When >=3-family envelopes exist, mark e2e-ready (still never force-registers).",
    )
    args = parser.parse_args()
    evidence = run_path(
        machine_root=args.machine_root,
        output=args.output,
        label=args.label,
        context=args.context,
        pipeline_fingerprint=args.pipeline_fingerprint,
        period_id=args.period_id,
        execute_e2e_when_ready=args.execute_e2e_when_ready,
    )
    state = evidence["production_honest_state"]
    print(
        json.dumps(
            {
                "output": args.output.as_posix(),
                "status": evidence["status"],
                "champions": state["production_champion_count"],
                "mode_b_predict_status": state["mode_b_predict_status"],
                "audit_queue_population_count": state["production_audit_queue_population_count"],
                "mvc": evidence["measured_path_stages"][0]["pool"][
                    "machine_verified_candidate_count"
                ],
                "caa": evidence["measured_path_stages"][0]["pool"][
                    "calibrated_auto_accepted_count"
                ],
                "envelopes": state["production_corpus_record_envelopes"],
                "git_head": evidence["git_head"],
                "self_sha256": evidence["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
