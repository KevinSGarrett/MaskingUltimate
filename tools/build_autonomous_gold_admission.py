"""Governed autonomous-gold admission driver (Unblock 2).

Activates the approved autonomous-certified-gold admission tier that replaces the
human-anchor calibration authority with independent multi-provider agreement +
stability + hard-veto QA (see configs/autonomy_autonomous_gold_profile.yaml). It
NEVER weakens the Wilson/zero-failure math and NEVER fabricates samples.

Two modes:
  * default: report the true admission state — scan `runs/` autonomy lifecycle
    sidecars for autonomously-verified candidates, and fail closed with the exact
    next agent step when there are too few (the current honest state: no CUDA
    multi-provider tournament has produced machine_verified_candidate masks yet;
    that step now runs in the Docker GPU container from Unblock 1).
  * --corpus PATH: build a real autonomous-gold certificate from a frozen,
    image-disjoint autonomous-verification corpus and report pass/fail.

Usage:
  python tools/build_autonomous_gold_admission.py \
      --label torso --context solo --pipeline-fingerprint <fp> \
      [--corpus <corpus.json>] [--machine-root runs] \
      --output qa/live_verification/autonomous_gold_admission_<ts>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maskfactory.autonomy.calibration import (
    AutonomyCalibrationError,
    build_autonomous_gold_certificate,
    load_autonomous_gold_profile,
    verify_autonomy_certificate,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
NEXT_STEP = (
    "Run the multi-provider autonomous tournament in the Docker GPU container "
    "(docker/Dockerfile.train -> maskfactory/train:cu128) on gold-volume sources "
    "(MaskedWarehouse / reference library / DAZ) to produce machine_verified_candidate "
    "lifecycle sidecars under runs/, then assemble a frozen image-disjoint "
    "autonomous-verification corpus and re-run this tool with --corpus."
)


def scan_verified_candidates(machine_root: Path) -> dict[str, Any]:
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--instance-context", default="solo")
    parser.add_argument("--risk-bucket", default=None)
    parser.add_argument("--pipeline-fingerprint", required=True)
    parser.add_argument("--corpus", type=Path, default=None)
    parser.add_argument("--machine-root", type=Path, default=REPO_ROOT / "runs")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    evidence: dict[str, Any] = {
        "artifact_type": "autonomous_gold_admission",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authority": "autonomous_certified_gold_profile",
    }

    try:
        profile = load_autonomous_gold_profile()
        evidence["profile_ok"] = True
        evidence["profile_id"] = profile["profile_id"]
        evidence["profile_sha256"] = profile["profile_sha256"]
    except AutonomyCalibrationError as exc:
        evidence["profile_ok"] = False
        evidence["error"] = str(exc)
        evidence["status"] = "profile_invalid"
        _write(args.output, evidence)
        return 2

    pool = scan_verified_candidates(args.machine_root)
    evidence["autonomous_verified_pool"] = pool

    if args.corpus is None:
        # Honest state report: no fabricated corpus. Fail closed with next step.
        evidence["status"] = "insufficient_autonomous_verified_samples"
        evidence["certificate_passed"] = False
        evidence["next_agent_step"] = NEXT_STEP
        evidence["claim_boundary"] = {
            "admission_tier_implemented_and_gated": True,
            "certificate_minted": False,
            "no_fabricated_samples": True,
        }
        _seal(evidence)
        _write(args.output, evidence)
        print(json.dumps({"status": evidence["status"], "pool": pool}, sort_keys=True))
        return 1

    try:
        certificate = build_autonomous_gold_certificate(
            args.corpus,
            label=args.label,
            context=args.context,
            instance_context=args.instance_context,
            risk_bucket=args.risk_bucket,
            pipeline_fingerprint=args.pipeline_fingerprint,
            profile=profile,
            machine_artifacts_root=args.machine_root,
        )
    except (AutonomyCalibrationError, OSError, json.JSONDecodeError) as exc:
        evidence["status"] = "corpus_invalid"
        evidence["error"] = str(exc)
        _seal(evidence)
        _write(args.output, evidence)
        print(json.dumps({"status": evidence["status"], "error": str(exc)}, sort_keys=True))
        return 2

    valid, reason = verify_autonomy_certificate(
        certificate,
        label=args.label,
        context=args.context,
        instance_context=args.instance_context,
        pipeline_fingerprint=args.pipeline_fingerprint,
        risk_bucket=args.risk_bucket,
        allow_autonomous_profile=True,
    )
    evidence["certificate"] = certificate
    evidence["certificate_passed"] = bool(certificate.get("passed"))
    evidence["verify_valid"] = valid
    evidence["verify_reason"] = reason
    evidence["status"] = (
        "autonomous_certified_gold" if (certificate.get("passed") and valid) else "fail_closed"
    )
    evidence["claim_boundary"] = {
        "admission_tier_implemented_and_gated": True,
        "certificate_minted": bool(certificate.get("passed")),
        "authority": "autonomous_certified_gold_profile",
        "is_not_independent_real_accuracy_claim": True,
        "is_not_human_anchor_holdout": True,
    }
    if not (certificate.get("passed") and valid):
        evidence["next_agent_step"] = NEXT_STEP
    _seal(evidence)
    _write(args.output, evidence)
    print(json.dumps({"status": evidence["status"], "reason": reason}, sort_keys=True))
    return 0 if evidence["status"] == "autonomous_certified_gold" else 1


def _seal(evidence: dict[str, Any]) -> None:
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()


def _write(output: Path, evidence: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
