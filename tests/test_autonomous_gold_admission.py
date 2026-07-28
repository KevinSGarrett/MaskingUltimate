"""Tests for the governed autonomous-certified-gold admission tier (Unblock 2).

The autonomous path replaces the human-anchor calibration authority with
independent multi-provider agreement + stability + hard-veto QA, WITHOUT
weakening the exact one-sided Wilson / zero-failure bounds. These tests prove:
  * the sealed profile loads and is contract-valid;
  * a sufficiently large zero-defect autonomous corpus may pass its historical
    population statistics but never verifies as per-record authority;
  * the exact bounds are preserved (thin or defect-heavy corpora fail closed);
  * a human-anchor-only verify never honors an autonomous certificate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from maskfactory.autonomy.calibration import (
    AUTONOMOUS_GOLD_AUTHORITY,
    AUTONOMOUS_GOLD_CERTIFICATE_SCHEMA,
    AutonomyCalibrationError,
    build_autonomous_gold_certificate,
    load_autonomous_gold_profile,
    verify_autonomy_certificate,
)

PIPELINE_FP = "autonomous-gold-test-fingerprint"
LABEL = "torso"
CONTEXT = "solo"
BUCKET = "torso_solo"


def _record(index: int, *, disagree: bool = False, serious: bool = False) -> dict[str, Any]:
    return {
        "record_id": f"rec{index:04d}",
        "image_id": f"img{index:04d}",
        "label": LABEL,
        "context": CONTEXT,
        "risk_bucket": BUCKET,
        "pipeline_fingerprint": PIPELINE_FP,
        "machine_accepted": True,
        "independent_family_count": 3,
        "cross_family_disagreement": disagree,
        "serious_cross_family_disagreement": serious,
        "candidate_stability_pass": True,
        "perturbation_stability_pass": True,
        "complete_map_hard_veto_pass": True,
        "machine_lifecycle_sha256": "a" * 64,
        "machine_mask_sha256": "b" * 64,
        "machine_lifecycle_path": f"lifecycle/{index}.json",
        "machine_mask_path": f"masks/{index}.png",
    }


def _corpus(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "frozen": True,
        "image_disjoint": True,
        "records": records,
    }


def _write(tmp_path: Path, records: list[dict[str, Any]]) -> Path:
    path = tmp_path / "autonomous_corpus.json"
    path.write_text(json.dumps(_corpus(records)), encoding="utf-8")
    return path


def _no_op_validator(_record: dict[str, Any], _root: Path) -> None:
    return None


def test_profile_loads_and_is_sealed() -> None:
    profile = load_autonomous_gold_profile()
    assert profile["authority"] == AUTONOMOUS_GOLD_AUTHORITY
    assert profile["independent_provider_families_minimum"] >= 3
    assert profile["authority_replacement"]["does_not_weaken_wilson_math"] is True
    assert profile["enabled"] is False
    assert profile["claim_boundary"]["is_per_record_authority"] is False


def test_profile_cannot_restore_population_admission_authority() -> None:
    profile = load_autonomous_gold_profile()
    profile["claim_boundary"]["is_operational_admission_authority"] = True
    with pytest.raises(AutonomyCalibrationError, match="claim boundary is invalid"):
        build_autonomous_gold_certificate(
            Path("missing-does-not-matter.json"),
            label=LABEL,
            context=CONTEXT,
            risk_bucket=BUCKET,
            pipeline_fingerprint=PIPELINE_FP,
            profile=profile,
        )


def test_large_zero_defect_corpus_passes_statistics_but_not_record_authority(
    tmp_path: Path,
) -> None:
    # ~600 zero-defect samples are required to satisfy BOTH the 0.01 Wilson bound
    # and the 0.005 exact zero-failure serious bound — identical rigor to the
    # human-anchor certificate, not a weakened threshold.
    corpus = _write(tmp_path, [_record(i) for i in range(600)])
    certificate = build_autonomous_gold_certificate(
        corpus,
        label=LABEL,
        context=CONTEXT,
        risk_bucket=BUCKET,
        pipeline_fingerprint=PIPELINE_FP,
        machine_authority_validator=_no_op_validator,
    )
    assert certificate["passed"] is True
    assert certificate["schema_version"] == AUTONOMOUS_GOLD_CERTIFICATE_SCHEMA
    assert certificate["audit_authority"] == AUTONOMOUS_GOLD_AUTHORITY

    valid, reason = verify_autonomy_certificate(
        certificate,
        label=LABEL,
        context=CONTEXT,
        risk_bucket=BUCKET,
        pipeline_fingerprint=PIPELINE_FP,
        allow_autonomous_profile=True,
    )
    assert valid is False
    assert reason == "population_certificate_not_per_record_authority"
    assert certificate["per_record_authority"] is False
    assert certificate["autonomous_certified_gold_authority"] is False


def test_default_off_rejects_autonomous_certificate(tmp_path: Path) -> None:
    corpus = _write(tmp_path, [_record(i) for i in range(600)])
    certificate = build_autonomous_gold_certificate(
        corpus,
        label=LABEL,
        context=CONTEXT,
        risk_bucket=BUCKET,
        pipeline_fingerprint=PIPELINE_FP,
        machine_authority_validator=_no_op_validator,
    )
    # Hot tournament path default: autonomous authority is NOT honored.
    valid, reason = verify_autonomy_certificate(
        certificate,
        label=LABEL,
        context=CONTEXT,
        risk_bucket=BUCKET,
        pipeline_fingerprint=PIPELINE_FP,
    )
    assert valid is False
    assert reason == "autonomous_profile_not_enabled"


def test_thin_corpus_fails_wilson_floor(tmp_path: Path) -> None:
    corpus = _write(tmp_path, [_record(i) for i in range(30)])
    certificate = build_autonomous_gold_certificate(
        corpus,
        label=LABEL,
        context=CONTEXT,
        risk_bucket=BUCKET,
        pipeline_fingerprint=PIPELINE_FP,
        machine_authority_validator=_no_op_validator,
    )
    assert certificate["passed"] is False
    assert "false_accept_upper_bound_exceeded" in certificate["failures"]


def test_defect_heavy_corpus_fails_closed(tmp_path: Path) -> None:
    records = [_record(i, disagree=(i < 60), serious=(i < 20)) for i in range(600)]
    corpus = _write(tmp_path, records)
    certificate = build_autonomous_gold_certificate(
        corpus,
        label=LABEL,
        context=CONTEXT,
        risk_bucket=BUCKET,
        pipeline_fingerprint=PIPELINE_FP,
        machine_authority_validator=_no_op_validator,
    )
    assert certificate["passed"] is False
    assert "false_accept_upper_bound_exceeded" in certificate["failures"]
    assert "serious_false_accept_upper_bound_exceeded" in certificate["failures"]


def test_low_independence_samples_are_not_admitted(tmp_path: Path) -> None:
    # Correlated (fewer than 3 independent families) samples must not count toward
    # the certified set even when accepted.
    records = [_record(i) for i in range(600)]
    for record in records:
        record["independent_family_count"] = 2
    corpus = _write(tmp_path, records)
    certificate = build_autonomous_gold_certificate(
        corpus,
        label=LABEL,
        context=CONTEXT,
        risk_bucket=BUCKET,
        pipeline_fingerprint=PIPELINE_FP,
        machine_authority_validator=_no_op_validator,
    )
    assert certificate["sample_count"] == 0
    assert certificate["passed"] is False


def test_serious_defect_requires_disagreement(tmp_path: Path) -> None:
    records = [_record(i) for i in range(10)]
    records[0]["serious_cross_family_disagreement"] = True
    records[0]["cross_family_disagreement"] = False
    corpus = _write(tmp_path, records)
    with pytest.raises(AutonomyCalibrationError):
        build_autonomous_gold_certificate(
            corpus,
            label=LABEL,
            context=CONTEXT,
            risk_bucket=BUCKET,
            pipeline_fingerprint=PIPELINE_FP,
            machine_authority_validator=_no_op_validator,
        )
