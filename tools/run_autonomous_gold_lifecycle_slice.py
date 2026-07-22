"""Runtime driver: prove population evidence cannot promote per-record authority.

This closes the *runtime* gap left by the measured-path wiring fix: the unit
test (``tests/test_autonomous_gold_audit_queue_wiring.py``) proves the code path
in ``tmp_path`` but leaves no sealed on-disk artifact, and no tool actually
writes autonomy lifecycle sidecars and builds a weekly audit queue against real
files. This driver runs the *real* end-to-end path with the *unchanged*
certificate/Wilson math:

  1. write real ``machine_verified_candidate`` lifecycle sidecars + a real winner
     mask into an isolated demonstration machine-root (NEVER the production
     ``runs/`` pool);
  2. assemble a frozen, image-disjoint autonomous-verification corpus from them;
  3. build historical machine-population evidence via
     ``build_autonomous_gold_certificate`` (real ``verify_machine_audit_record``,
     one-sided Wilson + exact zero-failure bounds preserved) — the certificate
     only passes because the sample floor genuinely satisfies both bounds;
  4. prove the real verifier refuses per-record authority even when the
     population statistics pass;
  5. prove no ``calibrated_auto_accepted`` sidecars or gold audit population
     are created.

Honest boundary (EVIDENCE_TIER = DEMONSTRATION, never inflated):
  * The provider "families" are synthetic construction used to exercise the
    plumbing; this is NOT an independent real-accuracy claim, NOT a champion,
    NOT PRODUCTION_EVIDENCE, and it does NOT write into the production ``runs/``
    pool. The production pool is scanned separately and reported honestly (it
    stays whatever it truly is; producing real gold there still requires the
    multi-provider GPU tournament runtime).
  * It preserves the Wilson/zero-failure calculation as diagnostic evidence,
    but passing statistics never authorize pixels or a package.

Usage:
  python tools/run_autonomous_gold_lifecycle_slice.py \
      --output qa/live_verification/autonomous_gold_lifecycle_slice_<ts>.json
  python tools/run_autonomous_gold_lifecycle_slice.py --verify \
      --output qa/live_verification/autonomous_gold_lifecycle_slice_<ts>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from maskfactory.autonomy.calibration import (
    build_autonomous_gold_certificate,
    load_autonomous_gold_profile,
    verify_autonomy_certificate,
)
from maskfactory.autonomy.controller import run_autonomous_correction_loop
from maskfactory.autonomy.lifecycle import write_lifecycle_sidecar
from maskfactory.autonomy.operations import build_weekly_audit_queue
from maskfactory.autonomy.tournament import CandidateEvidence
from maskfactory.io.hashing import sha256_file
from maskfactory.io.png_strict import write_binary_mask

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_TYPE = "autonomous_gold_lifecycle_slice"
SCHEMA_VERSION = "1.0.0"
EVIDENCE_TIER = "DEMONSTRATION"
AUTHORITY = "machine_verified_population_risk_evidence"
LABEL = "torso"
CONTEXT = "solo"
PIPELINE_FP = "autonomous-gold-lifecycle-slice-fp-v1"
NEXT_STEP = (
    "Real autonomous_certified_gold requires one exact immutable package with "
    "qualified per-label/context QA, semantic alignment, independent critic quorum, "
    "complete package hashes, and current revocation evidence. Population Wilson "
    "evidence remains advisory only."
)


def _config() -> dict[str, Any]:
    path = REPO_ROOT / "configs/autonomous_masks.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _winner_candidate(mask_path: Path, mask_sha256: str) -> CandidateEvidence:
    """A single genuinely-eligible winner (>=3 independent sources, score >=0.88)."""
    return CandidateEvidence(
        candidate_id="winner",
        mask_path=str(mask_path),
        mask_sha256=mask_sha256,
        independent_sources=5,
        consensus_iou=0.98,
        boundary_agreement=0.98,
        pose_consistency=0.98,
        critic_pass_weight=0.96,
        critic_disagreement=False,
        protected_overlap=0.0,
        exclusive_overlap=0.0,
        component_count=1,
        ontology_max_components=1,
        format_valid=True,
        block_qc_ids=(),
    )


def _no_correction(**_kwargs: Any) -> tuple[CandidateEvidence, ...]:
    return ()


def _image_id(prefix: str, index: int) -> str:
    digest = hashlib.sha256(f"{prefix}:{index}".encode()).hexdigest()
    return f"img_{digest[:12]}"


def _write_mask(path: Path) -> tuple[Path, str]:
    array = np.pad(np.ones((8, 8), dtype=np.uint8) * 255, ((4, 4), (4, 4)))
    written = write_binary_mask(path, array)
    return written, sha256_file(written)


def _corpus_record(
    index: int, *, lifecycle_rel: str, mask_rel: str, mask_sha: str, lifecycle_sha: str
) -> dict[str, Any]:
    return {
        "record_id": f"rec{index:06d}",
        "image_id": _image_id("draft", index),
        "label": LABEL,
        "context": CONTEXT,
        "risk_bucket": CONTEXT,
        "pipeline_fingerprint": PIPELINE_FP,
        "machine_accepted": True,
        "independent_family_count": 3,
        "cross_family_disagreement": False,
        "serious_cross_family_disagreement": False,
        "candidate_stability_pass": True,
        "perturbation_stability_pass": True,
        "complete_map_hard_veto_pass": True,
        "machine_lifecycle_path": lifecycle_rel,
        "machine_lifecycle_sha256": lifecycle_sha,
        "machine_mask_path": mask_rel,
        "machine_mask_sha256": mask_sha,
    }


def run_slice(
    workdir: Path, *, draft_count: int, calibrated_count: int, production_machine_root: Path
) -> dict[str, Any]:
    config = _config()
    profile = load_autonomous_gold_profile()

    machine_root = workdir / "machine_root"
    (machine_root / "lifecycle").mkdir(parents=True, exist_ok=True)
    (machine_root / "masks").mkdir(parents=True, exist_ok=True)

    # Phase 1: real machine_verified_candidate sidecars + one shared winner mask.
    draft_mask_path, draft_mask_sha = _write_mask(machine_root / "masks/draft.png")
    records: list[dict[str, Any]] = []
    for index in range(draft_count):
        candidate = _winner_candidate(draft_mask_path, draft_mask_sha)
        result = run_autonomous_correction_loop(
            (candidate,),
            label=LABEL,
            context=CONTEXT,
            pipeline_fingerprint=PIPELINE_FP,
            config=config,
            correction_generator=_no_correction,
            certificate=None,
        )
        if result.decision.status != "machine_verified_candidate":
            raise RuntimeError(
                f"draft {index} did not reach machine_verified_candidate: "
                f"{result.decision.status}"
            )
        image_id = _image_id("draft", index)
        lifecycle_path = machine_root / "lifecycle" / f"draft_{index:06d}.json"
        write_lifecycle_sidecar(
            lifecycle_path,
            image_id=image_id,
            instance_id="p0",
            pipeline_fingerprint=PIPELINE_FP,
            decision=result.decision,
        )
        records.append(
            _corpus_record(
                index,
                lifecycle_rel=f"lifecycle/draft_{index:06d}.json",
                mask_rel="masks/draft.png",
                mask_sha=draft_mask_sha,
                lifecycle_sha=sha256_file(lifecycle_path),
            )
        )

    # Phase 2: frozen, image-disjoint autonomous-verification corpus.
    corpus = {
        "schema_version": "1.0.0",
        "frozen": True,
        "image_disjoint": True,
        "records": records,
    }
    corpus_path = workdir / "autonomous_corpus.json"
    corpus_path.write_text(json.dumps(corpus, sort_keys=True), encoding="utf-8")

    # Phase 3: mint the certificate with the UNCHANGED Wilson/zero-failure math
    # and the REAL machine-authority validator (no bypass).
    certificate = build_autonomous_gold_certificate(
        corpus_path,
        label=LABEL,
        context=CONTEXT,
        pipeline_fingerprint=PIPELINE_FP,
        profile=profile,
        machine_artifacts_root=machine_root,
    )
    cert_valid, cert_reason = verify_autonomy_certificate(
        certificate,
        label=LABEL,
        context=CONTEXT,
        pipeline_fingerprint=PIPELINE_FP,
        allow_autonomous_profile=True,
    )

    calibrated_written = 0
    audit_queue: dict[str, Any] = {}
    if certificate.get("passed") and cert_valid:
        # Phase 4: raise real winners to calibrated_auto_accepted via the loop.
        calibrated_stage = workdir / "calibrated"
        lifecycle_root = calibrated_stage / "lifecycle"
        lifecycle_root.mkdir(parents=True, exist_ok=True)
        (calibrated_stage / "masks").mkdir(parents=True, exist_ok=True)
        cal_mask_path, cal_mask_sha = _write_mask(calibrated_stage / "masks/cal.png")
        for index in range(calibrated_count):
            candidate = _winner_candidate(cal_mask_path, cal_mask_sha)
            result = run_autonomous_correction_loop(
                (candidate,),
                label=LABEL,
                context=CONTEXT,
                pipeline_fingerprint=PIPELINE_FP,
                config=config,
                correction_generator=_no_correction,
                certificate=certificate,
                allow_autonomous_profile=True,
            )
            if result.decision.status != "calibrated_auto_accepted":
                raise RuntimeError(
                    f"calibrated {index} did not reach calibrated_auto_accepted: "
                    f"{result.decision.status}"
                )
            write_lifecycle_sidecar(
                lifecycle_root / f"{LABEL}_{index:06d}.json",
                image_id=_image_id("calibrated", index),
                instance_id="p0",
                pipeline_fingerprint=PIPELINE_FP,
                decision=result.decision,
            )
            calibrated_written += 1

        # Phase 5: the weekly audit queue now sees a real population.
        audit_queue = build_weekly_audit_queue(
            lifecycle_root,
            workdir / "audit_queue.json",
            period_id="2026-W29",
            operations_policy=config["operations"],
        )

    # Phase 6: honest production pool scan (kept separate; never inflated).
    production_pool = _scan_production_pool(production_machine_root)

    evidence: dict[str, Any] = {
        "artifact_type": ARTIFACT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "evidence_tier": EVIDENCE_TIER,
        "authority": AUTHORITY,
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "profile_id": profile["profile_id"],
        "profile_sha256": profile["profile_sha256"],
        "scope": {
            "label": LABEL,
            "context": CONTEXT,
            "risk_bucket": CONTEXT,
            "pipeline_fingerprint": PIPELINE_FP,
        },
        "certificate_summary": {
            "schema_version": certificate.get("schema_version"),
            "audit_authority": certificate.get("audit_authority"),
            "sample_count": certificate.get("sample_count"),
            "false_accept_count": certificate.get("false_accept_count"),
            "serious_false_accept_count": certificate.get("serious_false_accept_count"),
            "false_accept_upper_bound": certificate.get("false_accept_upper_bound"),
            "serious_false_accept_upper_bound": certificate.get("serious_false_accept_upper_bound"),
            "aggregate_false_accept_bound_method": certificate.get(
                "aggregate_false_accept_bound_method"
            ),
            "serious_false_accept_bound_method": certificate.get(
                "serious_false_accept_bound_method"
            ),
            "passed": certificate.get("passed"),
            "failures": certificate.get("failures"),
            "certificate_sha256": certificate.get("sha256"),
        },
        "certificate_verify_valid": cert_valid,
        "certificate_verify_reason": cert_reason,
        "demonstration_counts": {
            "machine_verified_candidate_sidecars": len(records),
            "calibrated_auto_accepted_sidecars": calibrated_written,
            "audit_queue_population_count": int(audit_queue.get("population_count", 0)),
            "audit_queue_selected_count": int(audit_queue.get("selected_count", 0)),
            "audit_queue_outcomes_status": audit_queue.get("outcomes_status", "empty"),
        },
        "production_pool_honest": production_pool,
        "honest_state": {
            "production_audit_queue_population_count": production_pool[
                "calibrated_auto_accepted_count"
            ],
            "production_autonomy_lifecycle_sidecars_in_runs": production_pool[
                "lifecycle_sidecars_seen"
            ],
        },
        "claim_boundary": {
            "is_operational_admission_authority_demonstration": False,
            "is_per_record_authority": False,
            "is_autonomous_certified_gold_authority": False,
            "is_not_independent_real_accuracy_claim": True,
            "is_not_production_evidence_pass": True,
            "does_not_touch_production_runs_pool": True,
            "no_champion_registered": True,
            "no_champion_force_registered": True,
            "wilson_math_unchanged": True,
            "certificate_uses_real_machine_authority_validator": True,
            "synthetic_provider_families_for_plumbing_only": True,
        },
        "next_agent_step": NEXT_STEP,
    }
    return evidence


def _scan_production_pool(machine_root: Path) -> dict[str, Any]:
    root = Path(machine_root)
    verified = 0
    calibrated = 0
    total = 0
    if root.is_dir():
        for path in root.rglob("*.json"):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(doc, dict):
                continue
            status = doc.get("status")
            if status == "machine_verified_candidate":
                total += 1
                verified += 1
            elif status == "calibrated_auto_accepted":
                total += 1
                calibrated += 1
    return {
        "machine_root": str(root),
        "machine_verified_candidate_count": verified,
        "calibrated_auto_accepted_count": calibrated,
        "lifecycle_sidecars_seen": total,
    }


def _seal(evidence: dict[str, Any]) -> dict[str, Any]:
    evidence.pop("self_sha256", None)
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    return evidence


def _verify_seal(evidence: dict[str, Any]) -> None:
    claimed = evidence.get("self_sha256")
    body = {key: value for key, value in evidence.items() if key != "self_sha256"}
    actual = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if claimed != actual:
        raise SystemExit(f"seal mismatch: recomputed={actual} stored={claimed}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, default=None)
    parser.add_argument("--draft-count", type=int, default=600)
    parser.add_argument("--calibrated-count", type=int, default=30)
    parser.add_argument("--production-machine-root", type=Path, default=REPO_ROOT / "runs")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        evidence = json.loads(args.output.read_text(encoding="utf-8"))
        _verify_seal(evidence)
        print(
            json.dumps(
                {
                    "verified": True,
                    "demonstration_counts": evidence["demonstration_counts"],
                    "honest_state": evidence["honest_state"],
                },
                sort_keys=True,
            )
        )
        return 0

    owns_workdir = args.workdir is None
    workdir = args.workdir or Path(tempfile.mkdtemp(prefix="autonomous_gold_slice_"))
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        evidence = run_slice(
            workdir,
            draft_count=args.draft_count,
            calibrated_count=args.calibrated_count,
            production_machine_root=args.production_machine_root,
        )
    finally:
        if owns_workdir:
            shutil.rmtree(workdir, ignore_errors=True)

    _seal(evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "demonstration_counts": evidence["demonstration_counts"],
                "certificate_passed": evidence["certificate_summary"]["passed"],
                "honest_state": evidence["honest_state"],
                "self_sha256": evidence["self_sha256"],
            },
            sort_keys=True,
        )
    )
    passed = (
        evidence["certificate_verify_valid"] is False
        and evidence["certificate_verify_reason"]
        == "population_certificate_not_per_record_authority"
        and evidence["demonstration_counts"]["calibrated_auto_accepted_sidecars"] == 0
        and evidence["demonstration_counts"]["audit_queue_population_count"] == 0
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
