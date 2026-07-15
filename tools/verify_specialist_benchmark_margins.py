from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maskfactory.providers.benchmark_policy import (
    SPECIALIST_MARGIN_MANIFEST_SHA256,
    SpecialistBenchmarkPolicyError,
    load_specialist_margin_manifest,
    validate_specialist_benchmark_results,
    validate_specialist_margin_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def _canonical_sha256(document: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _result(role: str, margins: dict[str, float], manifest_sha256: str) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "benchmark_id": "pre-result-validator-smoke",
        "role": role,
        "margin_manifest_sha256": manifest_sha256,
        "results_opened_at": "2026-07-15T02:00:00Z",
        "primary_win_or_labor_reduction": True,
        "rows": [
            {
                "bucket": bucket,
                "observed_delta": 0.0,
                "noninferiority_margin": margin,
                "passed": True,
            }
            for bucket, margin in sorted(margins.items())
        ],
    }
    document["sha256"] = _canonical_sha256(document)
    return document


def _reseal(document: dict[str, Any]) -> None:
    payload = {key: value for key, value in document.items() if key != "sha256"}
    document["sha256"] = _canonical_sha256(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify frozen specialist benchmark margins")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "qa" / "live_verification" / "specialist_benchmark_margins_20260715.json",
    )
    args = parser.parse_args()

    manifest, expanded = load_specialist_margin_manifest()
    exact_rows = 0
    role_summary: dict[str, Any] = {}
    for role_name, buckets in sorted(expanded.items()):
        validate_specialist_benchmark_results(
            _result(role_name, buckets, manifest["sha256"]),
            margin_manifest=manifest,
        )
        role = manifest["roles"][role_name]
        exact_rows += len(buckets)
        role_summary[role_name] = {
            "target_provider_role": role["target_provider_role"],
            "hard_label_count": len(role["hard_labels"]),
            "high_risk_context_count": len(role["high_risk_contexts"]),
            "zero_regression_metric_count": len(role["zero_regression_metrics"]),
            "expanded_bucket_count": len(buckets),
            "primary_objective": role["primary_objective"],
        }

    edited = copy.deepcopy(manifest)
    edited["roles"]["hand_finger_segmentation"]["label_margins"]["mean_iou"] = 0.20
    payload = {key: value for key, value in edited.items() if key != "sha256"}
    edited["sha256"] = _canonical_sha256(payload)
    try:
        validate_specialist_margin_manifest(edited)
    except SpecialistBenchmarkPolicyError as exc:
        edit_rejection = str(exc)
    else:
        raise RuntimeError("edited specialist margin manifest unexpectedly passed")

    regression = _result(
        "chest_pelvic_segmentation",
        expanded["chest_pelvic_segmentation"],
        manifest["sha256"],
    )
    first = regression["rows"][0]
    first["observed_delta"] = -float(first["noninferiority_margin"]) - 0.000001
    first["passed"] = False
    _reseal(regression)
    try:
        validate_specialist_benchmark_results(regression, margin_manifest=manifest)
    except SpecialistBenchmarkPolicyError as exc:
        regression_rejection = str(exc)
    else:
        raise RuntimeError("hard-bucket regression unexpectedly passed")

    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "captured_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "result": "pass",
        "authority": "pre_result_policy_verification_only_no_benchmark_or_promotion_authority",
        "manifest_id": manifest["manifest_id"],
        "manifest_sha256": manifest["sha256"],
        "locked_sha256": SPECIALIST_MARGIN_MANIFEST_SHA256,
        "frozen_at": manifest["frozen_at"],
        "results_state": manifest["results_state"],
        "source_hashes": manifest["source_hashes"],
        "role_count": len(expanded),
        "expanded_bucket_count": exact_rows,
        "roles": role_summary,
        "negative_probes": {
            "post_freeze_margin_edit_rejected": True,
            "post_freeze_margin_edit_reason": edit_rejection,
            "average_win_with_hard_bucket_regression_rejected": True,
            "hard_bucket_regression_reason": regression_rejection,
        },
        "benchmark_results_claimed": False,
        "promotion_claimed": False,
    }
    document["sha256"] = _canonical_sha256(document)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
