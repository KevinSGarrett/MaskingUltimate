import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
import yaml
from click.testing import CliRunner
from PIL import Image

from maskfactory.autonomy.adapters import MaskCandidateInput, build_mask_candidate_evidence
from maskfactory.autonomy.audit import (
    evaluate_immediate_revocation,
    select_mixed_human_audits,
    select_sparse_human_audits,
)
from maskfactory.autonomy.calibration import (
    AutonomyCalibrationError,
    build_autonomy_certificate,
    build_autonomy_pipeline_fingerprint,
    verify_autonomy_certificate,
    verify_machine_audit_record,
)
from maskfactory.autonomy.controller import run_autonomous_correction_loop
from maskfactory.autonomy.lifecycle import (
    certificate_is_revoked,
    load_scoped_certificate,
    write_lifecycle_sidecar,
)
from maskfactory.autonomy.operations import build_weekly_audit_queue, process_audit_outcomes
from maskfactory.autonomy.pseudo_dataset import build_weighted_pseudo_manifest
from maskfactory.autonomy.review_draft import (
    CandidateQaOutcome,
    ReviewDraftSelection,
    build_autonomous_review_draft,
    select_pre_review_candidate,
)
from maskfactory.autonomy.risk_buckets import (
    evaluate_exchangeability,
    load_risk_bucket_policy,
)
from maskfactory.autonomy.stability import (
    evaluate_candidate_stability,
    load_stability_policy,
)
from maskfactory.autonomy.tournament import CandidateEvidence, run_candidate_tournament
from maskfactory.cli import main
from maskfactory.io.png_strict import write_binary_mask, write_label_map
from maskfactory.ontology import get_ontology


def _config():
    return yaml.safe_load(Path("configs/autonomous_masks.yaml").read_text(encoding="utf-8"))


def _audit(tmp_path: Path, count: int, *, defects=(), serious=()) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    records = []
    for index in range(count):
        records.append(
            {
                "record_id": f"r{index}",
                "image_id": f"img_{index:04d}",
                "label": "hair",
                "context": "solo",
                "machine_accepted": True,
                "human_defect": index in defects,
                "serious_defect": index in serious,
                "pipeline_fingerprint": "pipeline-v1",
                "audit_authority": "human_approved_gold_only",
                "auditor": "kevin",
                "audited_at": "2026-07-12T12:00:00Z",
                "gold_package_path": f"img_{index:04d}/instances/p0",
                "gold_manifest_sha256": "a" * 64,
                "gold_freeze_sha256": "b" * 64,
                "gold_mask_sha256": "c" * 64,
                "machine_lifecycle_path": f"img_{index:04d}/hair.lifecycle.json",
                "machine_lifecycle_sha256": "e" * 64,
                "machine_mask_path": f"img_{index:04d}/hair.png",
                "machine_mask_sha256": "d" * 64,
            }
        )
    path = tmp_path / "audit.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "frozen": True,
                "image_disjoint": True,
                "records": records,
            }
        ),
        encoding="utf-8",
    )
    return path


def _accept_test_gold(_record: dict, _packages_root: Path) -> None:
    """Unit-only authority stub; production certificate creation uses the real verifier."""


def _accept_test_machine(_record: dict, _artifacts_root: Path) -> None:
    """Unit-only machine-proof stub; dedicated tests exercise the real verifier."""


def _candidate(candidate_id="winner", **overrides):
    values = {
        "candidate_id": candidate_id,
        "mask_path": f"{candidate_id}.png",
        "mask_sha256": candidate_id * 4,
        "independent_sources": 5,
        "consensus_iou": 0.98,
        "boundary_agreement": 0.98,
        "pose_consistency": 0.98,
        "critic_pass_weight": 0.96,
        "critic_disagreement": False,
        "protected_overlap": 0.0,
        "exclusive_overlap": 0.0,
        "component_count": 1,
        "ontology_max_components": 1,
        "format_valid": True,
        "block_qc_ids": (),
    }
    values.update(overrides)
    return CandidateEvidence(**values)


def _passing_stability(tmp_path: Path, label: str, risk_bucket: str):
    root = tmp_path / f"stability_{label}"
    base = np.zeros((64, 64), dtype=bool)
    base[13:51, 17:45] = True
    base_path = write_binary_mask(root / "base.png", base)
    variants = []
    ontology_label = get_ontology().label(label)
    for perturbation in ("resize", "crop", "color", "prompt", "horizontal_flip"):
        mask = np.flip(base, axis=1) if perturbation == "horizontal_flip" else base
        path = write_binary_mask(root / f"{perturbation}.png", mask)
        variants.append(
            {
                "perturbation": perturbation,
                "mask_path": path,
                "reported_label": (
                    ontology_label.swap_partner or label
                    if perturbation == "horizontal_flip"
                    else label
                ),
                "inverse_aligned": perturbation != "horizontal_flip",
            }
        )
    return evaluate_candidate_stability(
        base_path,
        variants,
        candidate_id=f"fixture-{label}",
        pipeline_fingerprint="pipeline-v1",
        risk_bucket=risk_bucket,
        label=label,
        policy=load_stability_policy(),
    )


def test_pipeline_fingerprint_binds_gate_and_every_component(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "controller.py").write_text("POLICY = 1\n", encoding="utf-8")
    config = tmp_path / "autonomy.yaml"
    config.write_text("threshold: 0.88\n", encoding="utf-8")
    components = {"source": source, "config": config}

    baseline = build_autonomy_pipeline_fingerprint("gate-v1", components=components)
    assert baseline == build_autonomy_pipeline_fingerprint(
        "gate-v1", components=dict(reversed(tuple(components.items())))
    )
    assert baseline != build_autonomy_pipeline_fingerprint("gate-v2", components=components)

    (source / "controller.py").write_text("POLICY = 2\n", encoding="utf-8")
    assert baseline != build_autonomy_pipeline_fingerprint("gate-v1", components=components)
    with pytest.raises(AutonomyCalibrationError, match="component is missing"):
        build_autonomy_pipeline_fingerprint("gate-v1", components={"missing": tmp_path / "missing"})


def test_95_percent_certificate_requires_enough_zero_failure_human_audits(tmp_path: Path):
    policy = _config()["calibration"]
    insufficient = build_autonomy_certificate(
        _audit(tmp_path / "small", 300),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        policy=policy,
        now=datetime(2026, 7, 12, tzinfo=UTC),
        gold_authority_validator=_accept_test_gold,
        machine_authority_validator=_accept_test_machine,
    )
    assert not insufficient["passed"]
    assert "serious_false_accept_upper_bound_exceeded" in insufficient["failures"]

    passed = build_autonomy_certificate(
        _audit(tmp_path / "large", 600),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        policy=policy,
        now=datetime(2026, 7, 12, tzinfo=UTC),
        gold_authority_validator=_accept_test_gold,
        machine_authority_validator=_accept_test_machine,
    )
    assert passed["passed"]
    assert passed["false_accept_upper_bound"] < 0.01
    assert passed["serious_false_accept_upper_bound"] < 0.005


def test_certificate_is_hash_scope_fingerprint_and_expiry_bound(tmp_path: Path):
    issued = datetime(2026, 7, 12, tzinfo=UTC)
    certificate = build_autonomy_certificate(
        _audit(tmp_path, 600),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        policy=_config()["calibration"],
        now=issued,
        gold_authority_validator=_accept_test_gold,
        machine_authority_validator=_accept_test_machine,
    )
    assert verify_autonomy_certificate(
        certificate,
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        now=issued,
    )[0]
    assert (
        verify_autonomy_certificate(
            certificate,
            label="hair",
            context="duo",
            pipeline_fingerprint="pipeline-v1",
            now=issued,
        )[1]
        == "certificate_scope_mismatch"
    )
    assert (
        verify_autonomy_certificate(
            certificate,
            label="hair",
            context="solo",
            pipeline_fingerprint="pipeline-v2",
            now=issued,
        )[1]
        == "certificate_scope_mismatch"
    )
    assert (
        verify_autonomy_certificate(
            certificate,
            label="hair",
            context="solo",
            pipeline_fingerprint="pipeline-v1",
            now=issued + timedelta(days=31),
        )[1]
        == "certificate_expired"
    )


def test_certificate_pools_multiple_labels_and_contexts_by_explicit_risk_bucket(
    tmp_path: Path,
):
    audit_path = _audit(tmp_path, 600)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["schema_version"] = "2.0.0"
    for index, record in enumerate(audit["records"]):
        record["risk_bucket"] = "small_parts"
        record["audit_authority"] = "human_anchor_gold"
        record["label"] = "hair" if index % 2 == 0 else "left_hand_base"
        record["context"] = "solo" if index % 3 else "duo"
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    risk_policy = load_risk_bucket_policy()
    pooling_evidence = evaluate_exchangeability(
        [
            {
                "record_id": record["record_id"],
                "risk_bucket": "small_parts",
                "stratum": f"{record['label']}::{record['context']}",
                "human_defect": record["human_defect"],
                "serious_defect": record["serious_defect"],
            }
            for record in audit["records"]
        ],
        risk_bucket="small_parts",
        policy=risk_policy,
        generated_at=datetime(2026, 7, 12, tzinfo=UTC),
    )
    issued = datetime(2026, 7, 12, tzinfo=UTC)
    with pytest.raises(AutonomyCalibrationError, match="stability evidence must cover"):
        build_autonomy_certificate(
            audit_path,
            label="hair",
            context="solo",
            risk_bucket="small_parts",
            pooling_evidence=pooling_evidence,
            pipeline_fingerprint="pipeline-v1",
            policy=_config()["calibration"],
            now=issued,
            gold_authority_validator=_accept_test_gold,
            machine_authority_validator=_accept_test_machine,
        )
    stability = [
        _passing_stability(tmp_path, "hair", "small_parts"),
        _passing_stability(tmp_path, "left_hand_base", "small_parts"),
    ]
    certificate = build_autonomy_certificate(
        audit_path,
        label="hair",
        context="solo",
        risk_bucket="small_parts",
        pooling_evidence=pooling_evidence,
        stability_evidence=stability,
        pipeline_fingerprint="pipeline-v1",
        policy=_config()["calibration"],
        now=issued,
        gold_authority_validator=_accept_test_gold,
        machine_authority_validator=_accept_test_machine,
    )
    assert certificate["schema_version"] == "2.0.0"
    assert certificate["audit_authority"] == "human_anchor_gold"
    assert certificate["covered_labels"] == ["hair", "left_hand_base"]
    assert certificate["covered_contexts"] == ["duo", "solo"]
    assert certificate["risk_bucket_policy_sha256"] == pooling_evidence["policy_sha256"]
    assert certificate["pooling_evidence_sha256"] == pooling_evidence["sha256"]
    assert certificate["stability_evidence_sha256s"] == sorted(row["sha256"] for row in stability)
    assert verify_autonomy_certificate(
        certificate,
        label="left_hand_base",
        context="duo",
        risk_bucket="small_parts",
        pipeline_fingerprint="pipeline-v1",
        now=issued,
    )[0]
    assert not verify_autonomy_certificate(
        certificate,
        label="right_foot",
        context="solo",
        risk_bucket="small_parts",
        pipeline_fingerprint="pipeline-v1",
        now=issued,
    )[0]


def test_certificate_refuses_unproven_cross_stratum_pooling(tmp_path: Path):
    audit_path = _audit(tmp_path, 60)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["schema_version"] = "2.0.0"
    for index, record in enumerate(audit["records"]):
        record["risk_bucket"] = "small_parts"
        record["audit_authority"] = "human_anchor_gold"
        record["label"] = "hair" if index % 2 == 0 else "left_hand"
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    with pytest.raises(AutonomyCalibrationError, match="empirical exchangeability"):
        build_autonomy_certificate(
            audit_path,
            label="hair",
            context="solo",
            risk_bucket="small_parts",
            pipeline_fingerprint="pipeline-v1",
            policy=_config()["calibration"],
            gold_authority_validator=_accept_test_gold,
            machine_authority_validator=_accept_test_machine,
        )


def test_certificate_rejects_audit_rows_without_real_gold_packages(tmp_path: Path):
    with pytest.raises(AutonomyCalibrationError, match="manifest or freeze marker is missing"):
        build_autonomy_certificate(
            _audit(tmp_path / "audit", 1),
            label="hair",
            context="solo",
            pipeline_fingerprint="pipeline-v1",
            policy=_config()["calibration"],
            gold_packages_root=tmp_path / "packages",
        )


def test_machine_audit_row_is_bound_to_real_lifecycle_winner_and_mask(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    machine_mask = write_binary_mask(
        artifacts / "masks/hair.png",
        np.pad(np.ones((8, 8), dtype=np.uint8) * 255, ((4, 4), (4, 4))),
    )
    mask_hash = hashlib.sha256(machine_mask.read_bytes()).hexdigest()
    decision = run_candidate_tournament(
        (_candidate(mask_path=str(machine_mask), mask_sha256=mask_hash),),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        config=_config(),
    )
    lifecycle_path = artifacts / "lifecycle/hair.json"
    write_lifecycle_sidecar(
        lifecycle_path,
        image_id="img_a3f9c2e17b04",
        instance_id="p0",
        pipeline_fingerprint="pipeline-v1",
        decision=decision,
    )
    record = {
        "image_id": "img_a3f9c2e17b04",
        "label": "hair",
        "context": "solo",
        "pipeline_fingerprint": "pipeline-v1",
        "machine_lifecycle_path": "lifecycle/hair.json",
        "machine_lifecycle_sha256": hashlib.sha256(lifecycle_path.read_bytes()).hexdigest(),
        "machine_mask_path": "masks/hair.png",
        "machine_mask_sha256": mask_hash,
    }
    verify_machine_audit_record(record, artifacts)
    write_binary_mask(machine_mask, np.ones((16, 16), dtype=np.uint8) * 255)
    with pytest.raises(AutonomyCalibrationError, match="machine mask hash mismatch"):
        verify_machine_audit_record(record, artifacts)


def test_legacy_certificate_cannot_authorize_autonomy(tmp_path: Path):
    issued = datetime(2026, 7, 12, tzinfo=UTC)
    certificate = build_autonomy_certificate(
        _audit(tmp_path, 600),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        policy=_config()["calibration"],
        now=issued,
        gold_authority_validator=_accept_test_gold,
        machine_authority_validator=_accept_test_machine,
    )
    certificate["schema_version"] = "1.0.0"
    certificate.pop("audit_authority")
    certificate["sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in certificate.items() if key != "sha256"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert (
        verify_autonomy_certificate(
            certificate,
            label="hair",
            context="solo",
            pipeline_fingerprint="pipeline-v1",
            now=issued,
        )[1]
        == "certificate_human_anchor_authority_missing"
    )


def test_tournament_progresses_from_machine_verified_to_calibrated_autoaccept(tmp_path: Path):
    config = _config()
    challenger = _candidate(
        "challenger",
        consensus_iou=0.75,
        boundary_agreement=0.75,
        pose_consistency=0.8,
        critic_pass_weight=0.7,
    )
    uncalibrated = run_candidate_tournament(
        (_candidate(), challenger),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        config=config,
    )
    assert uncalibrated.status == "machine_verified_candidate"
    assert uncalibrated.human_audit_required
    certificate = build_autonomy_certificate(
        _audit(tmp_path, 600),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        policy=config["calibration"],
        gold_authority_validator=_accept_test_gold,
        machine_authority_validator=_accept_test_machine,
    )
    calibrated = run_candidate_tournament(
        (_candidate(), challenger),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        config=config,
        certificate=certificate,
    )
    assert calibrated.status == "calibrated_auto_accepted"
    assert not calibrated.human_audit_required
    assert calibrated.authoritative_gold
    assert calibrated.truth_tier == "autonomous_certified_gold"


def test_hard_veto_disagreement_and_small_margin_prevent_autonomous_acceptance():
    config = _config()
    vetoed = run_candidate_tournament(
        (_candidate(protected_overlap=0.2),),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        config=config,
    )
    assert vetoed.status == "residual_human_queue"
    assert "protected_overlap" in vetoed.ranking[0].vetoes

    disputed = run_candidate_tournament(
        (_candidate(critic_disagreement=True),),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        config=config,
    )
    assert disputed.status == "residual_human_queue"

    tied = run_candidate_tournament(
        (_candidate("a"), _candidate("b", consensus_iou=0.975)),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        config=config,
    )
    assert tied.status == "residual_human_queue"


def test_residual_candidate_that_clears_baseline_hard_veto_improves_review_draft():
    config = _config()
    decision = run_candidate_tournament(
        (
            _candidate("s09_baseline", component_count=2, ontology_max_components=1),
            _candidate(
                "local_correction_r1",
                consensus_iou=0.78,
                boundary_agreement=0.78,
                pose_consistency=0.78,
                critic_pass_weight=0.75,
            ),
        ),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        config=config,
    )
    assert decision.status == "residual_human_queue"
    selection = select_pre_review_candidate(
        decision,
        policy=config["operations"],
        provider_votes=(
            {
                "provider": "self_hosted_qwen",
                "participated": True,
                "verdict": "better",
            },
        ),
    )
    assert selection is not None
    assert selection.status == "pre_review_improvement"
    assert selection.selection_reason == "candidate_clears_baseline_hard_veto"
    assert selection.before_metrics["vetoes"] == ["component_overflow"]
    assert selection.after_metrics["eligible"] is True


def test_uncertain_residual_candidate_does_not_replace_safe_baseline():
    config = _config()
    decision = run_candidate_tournament(
        (
            _candidate(
                "s09_baseline",
                consensus_iou=0.75,
                boundary_agreement=0.75,
                pose_consistency=0.75,
                critic_pass_weight=0.5,
            ),
            _candidate(
                "local_correction_r1",
                consensus_iou=0.79,
                boundary_agreement=0.79,
                pose_consistency=0.79,
                critic_pass_weight=0.5,
            ),
        ),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        config=config,
    )
    assert decision.status == "residual_human_queue"
    assert select_pre_review_candidate(decision, policy=config["operations"]) is None


def test_autonomy_cli_builds_certificate_and_runs_tournament(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "maskfactory.autonomy.calibration.verify_human_gold_audit_record",
        _accept_test_gold,
    )
    monkeypatch.setattr(
        "maskfactory.autonomy.calibration.verify_machine_audit_record",
        _accept_test_machine,
    )
    audit = _audit(tmp_path, 600)
    certificate = tmp_path / "certificate.json"
    built = CliRunner().invoke(
        main,
        [
            "autonomy",
            "build-certificate",
            str(audit),
            "--label",
            "hair",
            "--context",
            "solo",
            "--pipeline-fingerprint",
            "pipeline-v1",
            "--output",
            str(certificate),
        ],
    )
    assert built.exit_code == 0, built.output
    tournament_input = tmp_path / "tournament.json"
    tournament_input.write_text(
        json.dumps(
            {
                "label": "hair",
                "context": "solo",
                "pipeline_fingerprint": "pipeline-v1",
                "candidates": [
                    {
                        **_candidate().__dict__,
                        "block_qc_ids": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "decision.json"
    decided = CliRunner().invoke(
        main,
        [
            "autonomy",
            "tournament",
            str(tournament_input),
            "--certificate",
            str(certificate),
            "--output",
            str(output),
        ],
    )
    assert decided.exit_code == 0, decided.output
    assert json.loads(output.read_text())["status"] == "calibrated_auto_accepted"


def test_bounded_correction_loop_adds_novel_candidate_and_stops_on_selection():
    config = _config()
    weak = _candidate(
        "weak",
        mask_sha256="weak-hash",
        consensus_iou=0.5,
        boundary_agreement=0.5,
        pose_consistency=0.5,
        critic_pass_weight=0.5,
    )

    def generate(**kwargs):
        assert kwargs["round_number"] == 1
        return (_candidate("corrected", mask_sha256="corrected-hash"),)

    result = run_autonomous_correction_loop(
        (weak,),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        config=config,
        correction_generator=generate,
    )
    assert result.decision.status == "machine_verified_candidate"
    assert result.decision.winner_id == "corrected"
    assert result.rounds_executed == 1


def test_bounded_correction_loop_stops_when_generator_repeats_mask():
    config = _config()
    weak = _candidate(
        "weak",
        mask_sha256="same-hash",
        consensus_iou=0.5,
        boundary_agreement=0.5,
        pose_consistency=0.5,
        critic_pass_weight=0.5,
    )

    def duplicate(**_kwargs):
        return (_candidate("renamed", mask_sha256="same-hash"),)

    result = run_autonomous_correction_loop(
        (weak,),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        config=config,
        correction_generator=duplicate,
    )
    assert result.stopped_reason == "no_novel_safe_candidate"
    assert result.candidate_count == 1


def test_sparse_audit_selection_is_deterministic_non_confidence_based_and_minimum_bounded():
    records = tuple(
        {
            "record_id": f"r{index}",
            "image_id": f"img_{index}",
            "label": "hair",
            "context": "solo",
            "pipeline_fingerprint": "v1",
            "confidence": index / 1000,
        }
        for index in range(1000)
    )
    first = select_sparse_human_audits(records, fraction=0.02, minimum=20, period_id="2026-W28")
    second = select_sparse_human_audits(
        tuple(reversed(records)), fraction=0.02, minimum=20, period_id="2026-W28"
    )
    assert first == second
    assert first.selected_count == 20
    assert set(first.selected_record_ids) != {"r980", "r981", "r982", "r983"}


def test_mixed_audit_preserves_random_sample_and_covers_risk_buckets():
    records = tuple(
        {
            "record_id": f"r{index}",
            "image_id": f"i{index}",
            "label": "hair" if index < 50 else "finger",
            "context": "solo",
            "pipeline_fingerprint": "pipeline-v1",
            "risk_bucket": "boundary" if index < 50 else "small_part",
            "risk_priority": 0.2 if index < 50 else 0.9,
        }
        for index in range(100)
    )
    selected = select_mixed_human_audits(
        records,
        random_fraction=0.02,
        minimum_random=2,
        risk_oversample_fraction=0.02,
        minimum_per_high_risk_bucket=3,
        period_id="2026-W28",
    )
    assert set(selected.random_record_ids) <= set(selected.selected_record_ids)
    assert set(selected.risk_record_ids) <= set(selected.selected_record_ids)
    selected_buckets = {
        record["risk_bucket"]
        for record in records
        if record["record_id"] in selected.risk_record_ids
    }
    assert selected_buckets == {"boundary", "small_part"}


def test_serious_failure_or_drift_immediately_revokes_autonomy():
    outcomes = (
        {
            "record_id": "r1",
            "human_defect": True,
            "serious_defect": True,
            "distribution_drift": False,
        },
    )
    revoked, reasons = evaluate_immediate_revocation(
        outcomes, revoke_on_first_serious_false_accept=True
    )
    assert revoked and reasons == ("serious_false_accept",)
    drifted = ({**outcomes[0], "serious_defect": False, "distribution_drift": True},)
    assert evaluate_immediate_revocation(drifted, revoke_on_first_serious_false_accept=True) == (
        True,
        ("distribution_drift",),
    )
    malformed = ({**outcomes[0], "serious_defect": "true"},)
    with pytest.raises(ValueError, match="booleans are invalid"):
        evaluate_immediate_revocation(malformed, revoke_on_first_serious_false_accept=True)


def test_real_mask_adapter_and_lifecycle_sidecar_connect_tournament_artifacts(tmp_path: Path):
    first = np.zeros((20, 20), dtype=bool)
    first[4:16, 5:15] = True
    second = first.copy()
    second[4, 5] = False
    first_path = write_binary_mask(tmp_path / "first.png", first)
    second_path = write_binary_mask(tmp_path / "second.png", second)
    evidence = build_mask_candidate_evidence(
        (
            MaskCandidateInput("first", first_path, ("sam2", "parsing", "pose"), 0.98, False, 0.99),
            MaskCandidateInput(
                "second", second_path, ("sam2", "parsing", "pose"), 0.70, False, 0.95
            ),
        ),
        protected_neighbor=np.zeros_like(first),
        mutually_exclusive=np.zeros_like(first),
        ontology_max_components=1,
    )
    decision = run_candidate_tournament(
        evidence,
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        config=_config(),
    )
    assert decision.winner_id == "first"
    sidecar = write_lifecycle_sidecar(
        tmp_path / "lifecycle/hair.json",
        image_id="img_0123456789ab",
        instance_id="p0",
        pipeline_fingerprint="pipeline-v1",
        decision=decision,
    )
    assert sidecar["status"] == "machine_verified_candidate"
    assert sidecar["authoritative_human_gold"] is False
    assert sidecar["winner_mask_path"] == "first.png"
    certificate_root = tmp_path / "certificates"
    certificate_root.mkdir()
    (certificate_root / "hair__solo.json").write_text(json.dumps({"passed": False}))
    assert load_scoped_certificate(certificate_root, label="hair", context="solo") == {
        "passed": False
    }
    revocations = tmp_path / "revocations"
    revocations.mkdir()
    (revocations / "hair__solo.json").write_text(json.dumps({"pipeline_fingerprint": "v1"}))
    assert certificate_is_revoked(
        revocations, label="hair", context="solo", pipeline_fingerprint="v1"
    )


def test_autonomous_review_draft_promotes_only_after_full_map_qa_and_rolls_back(tmp_path: Path):
    base = np.zeros((24, 24), dtype=np.uint16)
    base[4:18, 4:10] = 18  # left_forearm
    base_path = write_label_map(tmp_path / "base.png", base, bits=16)
    improved = np.zeros((24, 24), dtype=bool)
    improved[3:19, 4:10] = True
    candidate_path = write_binary_mask(tmp_path / "candidate.png", improved)
    selection = ReviewDraftSelection(
        "left_forearm",
        "local_correction_r2",
        str(candidate_path),
        hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
        "machine_verified_candidate",
        0.93,
    )

    accepted = build_autonomous_review_draft(
        base_path,
        (selection,),
        tmp_path / "accepted",
        map_validator=lambda path, tag: CandidateQaOutcome((), str(path), "pass"),
    )
    assert accepted["promoted_for_human_review"] is True
    accepted_map = np.asarray(Image.open(accepted["review_part_map"]))
    assert np.count_nonzero(accepted_map == 18) == int(improved.sum())
    assert accepted["authoritative_human_gold"] is False
    persisted = json.loads((tmp_path / "accepted/report.json").read_text())
    assert persisted["proposed_part_map"] == "proposed_label_map_part.png"
    assert persisted["review_part_map"] == "label_map_part.png"
    assert ".tmp-" not in json.dumps(persisted)

    rejected = build_autonomous_review_draft(
        base_path,
        (selection,),
        tmp_path / "rejected",
        map_validator=lambda path, tag: CandidateQaOutcome(("QC-014",), str(path), "fail"),
    )
    assert rejected["promoted_for_human_review"] is False
    assert rejected["rolled_back"][0]["candidate_id"] == "local_correction_r2"
    assert np.array_equal(np.asarray(Image.open(rejected["review_part_map"])), base)


def test_autonomous_review_draft_rolls_back_only_the_failing_label(tmp_path: Path):
    base = np.zeros((24, 24), dtype=np.uint16)
    base[4:18, 2:8] = 18  # left_forearm
    base[4:18, 16:22] = 19  # right_forearm
    base_path = write_label_map(tmp_path / "base.png", base, bits=16)
    left = np.zeros((24, 24), dtype=bool)
    left[3:19, 2:8] = True
    right = np.zeros((24, 24), dtype=bool)
    right[3:19, 16:22] = True
    left_path = write_binary_mask(tmp_path / "left.png", left)
    right_path = write_binary_mask(tmp_path / "right.png", right)
    selections = (
        ReviewDraftSelection(
            "left_forearm",
            "local_correction_r1",
            str(left_path),
            hashlib.sha256(left_path.read_bytes()).hexdigest(),
            "pre_review_improvement",
            0.81,
        ),
        ReviewDraftSelection(
            "right_forearm",
            "cloud_gemini",
            str(right_path),
            hashlib.sha256(right_path.read_bytes()).hexdigest(),
            "pre_review_improvement",
            0.80,
        ),
    )

    def validator(_path: Path, tag: str) -> CandidateQaOutcome:
        if "right_forearm" in tag:
            return CandidateQaOutcome(("QC-014",), None, "fail")
        return CandidateQaOutcome((), None, "pass")

    result = build_autonomous_review_draft(
        base_path,
        selections,
        tmp_path / "draft",
        map_validator=validator,
    )
    draft = np.asarray(Image.open(result["review_part_map"]))
    assert result["promoted_for_human_review"] is True
    assert result["changed_labels"] == ["left_forearm"]
    assert result["applied"][0]["candidate_id"] == "local_correction_r1"
    assert result["rolled_back"][0]["candidate_id"] == "cloud_gemini"
    assert np.count_nonzero(draft == 18) == int(left.sum())
    assert np.count_nonzero(draft == 19) == np.count_nonzero(base == 19)
    assert result["human_gold_approval_required"] is True


def test_weekly_audit_queue_revokes_and_writes_retraining_plan(tmp_path: Path):
    lifecycle_root = tmp_path / "lifecycle"
    lifecycle_root.mkdir()
    config = _config()
    certificate = build_autonomy_certificate(
        _audit(tmp_path / "audit", 600),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        policy=config["calibration"],
        gold_authority_validator=_accept_test_gold,
        machine_authority_validator=_accept_test_machine,
    )
    for index in range(30):
        mask_path = write_binary_mask(
            tmp_path / f"masks/{index}.png",
            np.pad(np.ones((8, 8), dtype=np.uint8) * 255, ((4, 4), (4, 4))),
        )
        mask_hash = hashlib.sha256(mask_path.read_bytes()).hexdigest()
        decision = run_candidate_tournament(
            (_candidate(mask_path=str(mask_path), mask_sha256=mask_hash),),
            label="hair",
            context="solo",
            pipeline_fingerprint="pipeline-v1",
            config=config,
            certificate=certificate,
        )
        write_lifecycle_sidecar(
            lifecycle_root / f"hair_{index}.json",
            image_id=f"img_{index:012x}",
            instance_id="p0",
            pipeline_fingerprint="pipeline-v1",
            decision=decision,
        )
    queue_path = tmp_path / "queue.json"
    queue = build_weekly_audit_queue(
        lifecycle_root,
        queue_path,
        period_id="2026-W28",
        operations_policy=config["operations"],
    )
    assert queue["selected_count"] >= 20
    assert queue["random_selected_count"] == 20
    assert queue["risk_selected_count"] >= 5
    outcomes_path = tmp_path / "outcomes.json"
    outcomes_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "records": [
                    {
                        "record_id": record["record_id"],
                        "human_defect": index == 0,
                        "serious_defect": index == 0,
                        "distribution_drift": False,
                        "corrected_gold_sha256": "a" * 64 if index == 0 else None,
                    }
                    for index, record in enumerate(queue["records"])
                ],
            }
        )
    )
    retraining = dict(config["retraining"])
    retraining["minimum_audit_failures"] = 1
    result = process_audit_outcomes(
        queue_path,
        outcomes_path,
        revocations_root=tmp_path / "revocations",
        retraining_policy=retraining,
        operations_policy=config["operations"],
        retraining_output_path=tmp_path / "retrain.json",
    )
    assert result["retraining_requested"]
    assert len(result["revocations"]) == 1
    assert Path(result["revocations"][0]).is_file()
    assert json.loads((tmp_path / "retrain.json").read_text())["requested"] is True


def test_revocations_preserve_multiple_pipeline_fingerprints_for_one_scope(tmp_path: Path):
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "record_id": f"r{index}",
                        "label": "hair",
                        "context": "solo",
                        "pipeline_fingerprint": fingerprint,
                    }
                    for index, fingerprint in enumerate(("pipeline-v1", "pipeline-v2"), 1)
                ]
            }
        ),
        encoding="utf-8",
    )
    outcomes_path = tmp_path / "outcomes.json"
    outcomes_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "records": [
                    {
                        "record_id": f"r{index}",
                        "human_defect": True,
                        "serious_defect": True,
                        "distribution_drift": False,
                        "corrected_gold_sha256": ("a" if index == 1 else "b") * 64,
                    }
                    for index in (1, 2)
                ],
            }
        ),
        encoding="utf-8",
    )
    config = _config()
    result = process_audit_outcomes(
        queue_path,
        outcomes_path,
        revocations_root=tmp_path / "revocations",
        retraining_policy=config["retraining"],
        operations_policy=config["operations"],
        retraining_output_path=tmp_path / "retrain.json",
    )
    assert len(result["revocations"]) == 2
    assert len(set(result["revocations"])) == 2
    for fingerprint in ("pipeline-v1", "pipeline-v2"):
        assert certificate_is_revoked(
            tmp_path / "revocations",
            label="hair",
            context="solo",
            pipeline_fingerprint=fingerprint,
        )


def test_audit_processing_rejects_nonboolean_outcomes_and_fake_gold_hash(tmp_path: Path):
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "record_id": "r1",
                        "label": "hair",
                        "context": "solo",
                        "pipeline_fingerprint": "pipeline-v1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    outcome = {
        "record_id": "r1",
        "human_defect": False,
        "serious_defect": False,
        "distribution_drift": False,
        "corrected_gold_sha256": "not-a-hash",
    }
    outcomes_path = tmp_path / "outcomes.json"
    outcomes_path.write_text(
        json.dumps({"schema_version": "1.0.0", "records": [outcome]}),
        encoding="utf-8",
    )
    config = _config()
    arguments = {
        "revocations_root": tmp_path / "revocations",
        "retraining_policy": config["retraining"],
        "operations_policy": config["operations"],
        "retraining_output_path": tmp_path / "retrain.json",
    }
    with pytest.raises(ValueError, match="corrected-gold hash is invalid"):
        process_audit_outcomes(queue_path, outcomes_path, **arguments)
    outcome["corrected_gold_sha256"] = None
    outcome["human_defect"] = "false"
    outcomes_path.write_text(
        json.dumps({"schema_version": "1.0.0", "records": [outcome]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="outcome booleans are invalid"):
        process_audit_outcomes(queue_path, outcomes_path, **arguments)


def test_calibrated_pseudo_manifest_is_hash_verified_train_only_and_holdout_safe(tmp_path: Path):
    config = _config()
    mask = np.zeros((20, 20), dtype=bool)
    mask[4:16, 5:15] = True
    mask_path = write_binary_mask(tmp_path / "mask.png", mask)
    candidate = MaskCandidateInput(
        "winner", mask_path, ("sam2", "parsing", "pose"), 1.0, False, 1.0
    )
    evidence = build_mask_candidate_evidence(
        (candidate,),
        protected_neighbor=np.zeros_like(mask),
        mutually_exclusive=np.zeros_like(mask),
        ontology_max_components=1,
    )
    certificate = build_autonomy_certificate(
        _audit(tmp_path / "audit", 600),
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        policy=config["calibration"],
        gold_authority_validator=_accept_test_gold,
        machine_authority_validator=_accept_test_machine,
    )
    certificate_root = tmp_path / "certificates"
    certificate_root.mkdir()
    (certificate_root / "hair__solo.json").write_text(json.dumps(certificate))
    decision = run_candidate_tournament(
        evidence,
        label="hair",
        context="solo",
        pipeline_fingerprint="pipeline-v1",
        config=config,
        certificate=certificate,
    )
    lifecycle_root = tmp_path / "lifecycle"
    write_lifecycle_sidecar(
        lifecycle_root / "hair.json",
        image_id="img_0123456789ab",
        instance_id="p0",
        pipeline_fingerprint="pipeline-v1",
        decision=decision,
    )
    holdout = tmp_path / "holdout.txt"
    holdout.write_text("img_ffffffffffff\n")
    manifest = build_weighted_pseudo_manifest(
        lifecycle_root,
        tmp_path / "pseudo.json",
        certificate_root=certificate_root,
        revocations_root=tmp_path / "revocations",
        protected_anchor_ids_path=holdout,
        operations_policy=config["operations"],
    )
    assert manifest["record_count"] == 1
    assert manifest["records"][0]["split"] == "train_only"
    assert (
        manifest["records"][0]["loss_weight"]
        == config["operations"]["autonomous_certified_loss_weight"]
    )
    holdout.write_text("img_0123456789ab\n")
    with pytest.raises(ValueError, match="protected calibration/holdout anchor"):
        build_weighted_pseudo_manifest(
            lifecycle_root,
            tmp_path / "forbidden.json",
            certificate_root=certificate_root,
            revocations_root=tmp_path / "revocations",
            protected_anchor_ids_path=holdout,
            operations_policy=config["operations"],
        )
    holdout.write_text("img_ffffffffffff\n")
    lifecycle_path = lifecycle_root / "hair.json"
    escaped = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    escaped["winner_mask_path"] = "../outside.png"
    lifecycle_path.write_text(json.dumps(escaped), encoding="utf-8")
    with pytest.raises(ValueError, match="relative and contained"):
        build_weighted_pseudo_manifest(
            lifecycle_root,
            tmp_path / "escaped.json",
            certificate_root=certificate_root,
            revocations_root=tmp_path / "revocations",
            protected_anchor_ids_path=holdout,
            operations_policy=config["operations"],
        )
