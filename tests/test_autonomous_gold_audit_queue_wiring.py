"""Measured-path wiring: autonomous-gold certificate -> lifecycle -> audit queue.

These tests prove the plumbing that was silently dropped: the governed
autonomous-certified-gold authority (default OFF) must be forwarded through the
bounded correction loop so an authorized certificate can raise a tournament
decision to ``calibrated_auto_accepted``. Only then does the weekly audit queue
observe a non-empty population. With the flag OFF the behavior is unchanged
(``machine_verified_candidate`` -> population_count == 0), so there is zero
regression and no tier inflation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from maskfactory.autonomy.calibration import build_autonomous_gold_certificate
from maskfactory.autonomy.controller import run_autonomous_correction_loop
from maskfactory.autonomy.lifecycle import write_lifecycle_sidecar
from maskfactory.autonomy.operations import build_weekly_audit_queue
from maskfactory.autonomy.tournament import CandidateEvidence
from maskfactory.io.png_strict import write_binary_mask

LABEL = "hair"
CONTEXT = "solo"
PIPELINE_FP = "autonomous-gold-wiring-fingerprint"


def _config() -> dict[str, Any]:
    return yaml.safe_load(Path("configs/autonomous_masks.yaml").read_text(encoding="utf-8"))


def _no_op_validator(_record: dict[str, Any], _root: Path) -> None:
    return None


def _autonomous_record(index: int) -> dict[str, Any]:
    return {
        "record_id": f"rec{index:04d}",
        "image_id": f"img{index:04d}",
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
        "machine_lifecycle_sha256": "a" * 64,
        "machine_mask_sha256": "b" * 64,
        "machine_lifecycle_path": f"lifecycle/{index}.json",
        "machine_mask_path": f"masks/{index}.png",
    }


def _passing_autonomous_certificate(tmp_path: Path) -> dict[str, Any]:
    corpus_path = tmp_path / "autonomous_corpus.json"
    corpus_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "frozen": True,
                "image_disjoint": True,
                "records": [_autonomous_record(i) for i in range(600)],
            }
        ),
        encoding="utf-8",
    )
    certificate = build_autonomous_gold_certificate(
        corpus_path,
        label=LABEL,
        context=CONTEXT,
        pipeline_fingerprint=PIPELINE_FP,
        machine_authority_validator=_no_op_validator,
    )
    assert certificate["passed"] is True
    return certificate


def _winner_candidate(mask_path: Path) -> CandidateEvidence:
    mask_hash = hashlib.sha256(mask_path.read_bytes()).hexdigest()
    return CandidateEvidence(
        candidate_id="winner",
        mask_path=str(mask_path),
        mask_sha256=mask_hash,
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


def test_autonomous_profile_off_stays_machine_verified(tmp_path: Path) -> None:
    certificate = _passing_autonomous_certificate(tmp_path)
    mask_path = write_binary_mask(
        tmp_path / "masks/hair.png",
        np.pad(np.ones((8, 8), dtype=np.uint8) * 255, ((4, 4), (4, 4))),
    )
    result = run_autonomous_correction_loop(
        (_winner_candidate(mask_path),),
        label=LABEL,
        context=CONTEXT,
        pipeline_fingerprint=PIPELINE_FP,
        config=_config(),
        correction_generator=_no_correction,
        certificate=certificate,
    )
    # Default OFF: the autonomous authority is not honored, so the winner is a
    # machine-verified candidate that never reaches the calibrated audit queue.
    assert result.decision.status == "machine_verified_candidate"
    assert result.decision.certificate_valid is False
    assert result.decision.certificate_reason == "autonomous_profile_not_enabled"


def test_autonomous_profile_on_reaches_audit_queue(tmp_path: Path) -> None:
    certificate = _passing_autonomous_certificate(tmp_path)
    config = _config()
    lifecycle_root = tmp_path / "lifecycle"
    lifecycle_root.mkdir()
    for index in range(30):
        mask_path = write_binary_mask(
            tmp_path / f"masks/{index}.png",
            np.pad(np.ones((8, 8), dtype=np.uint8) * 255, ((4, 4), (4, 4))),
        )
        result = run_autonomous_correction_loop(
            (_winner_candidate(mask_path),),
            label=LABEL,
            context=CONTEXT,
            pipeline_fingerprint=PIPELINE_FP,
            config=config,
            correction_generator=_no_correction,
            certificate=certificate,
            allow_autonomous_profile=True,
        )
        assert result.decision.status == "calibrated_auto_accepted"
        assert result.decision.truth_tier == "autonomous_certified_gold"
        write_lifecycle_sidecar(
            lifecycle_root / f"hair_{index}.json",
            image_id=f"img_{index:012x}",
            instance_id="p0",
            pipeline_fingerprint=PIPELINE_FP,
            decision=result.decision,
        )

    queue = build_weekly_audit_queue(
        lifecycle_root,
        tmp_path / "queue.json",
        period_id="2026-W29",
        operations_policy=config["operations"],
    )
    # The measured path now yields a real audit population instead of zero.
    assert queue["population_count"] == 30
    assert queue["selected_count"] > 0
    assert queue["outcomes_status"] == "pending"
