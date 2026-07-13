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
    select_sparse_human_audits,
)
from maskfactory.autonomy.calibration import (
    AutonomyCalibrationError,
    build_autonomy_certificate,
    build_autonomy_pipeline_fingerprint,
    verify_autonomy_certificate,
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
)
from maskfactory.autonomy.tournament import CandidateEvidence, run_candidate_tournament
from maskfactory.cli import main
from maskfactory.io.png_strict import write_binary_mask, write_label_map


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
    assert not calibrated.authoritative_gold


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


def test_autonomy_cli_builds_certificate_and_runs_tournament(tmp_path: Path):
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
        pipeline_fingerprint="v1",
        config=_config(),
    )
    assert decision.winner_id == "first"
    sidecar = write_lifecycle_sidecar(
        tmp_path / "lifecycle/hair.json",
        image_id="img_0123456789ab",
        instance_id="p0",
        pipeline_fingerprint="v1",
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


def test_weekly_audit_queue_revokes_and_writes_retraining_plan(tmp_path: Path):
    lifecycle_root = tmp_path / "lifecycle"
    lifecycle_root.mkdir()
    for index in range(30):
        (lifecycle_root / f"hair_{index}.json").write_text(
            json.dumps(
                {
                    "status": "calibrated_auto_accepted",
                    "image_id": f"img_{index}",
                    "instance_id": "p0",
                    "label": "hair",
                    "context": "solo",
                    "pipeline_fingerprint": "v1",
                    "winner_mask_path": f"masks/{index}.png",
                    "winner_mask_sha256": f"hash_{index}",
                }
            )
        )
    config = _config()
    queue_path = tmp_path / "queue.json"
    queue = build_weekly_audit_queue(
        lifecycle_root,
        queue_path,
        period_id="2026-W28",
        operations_policy=config["operations"],
    )
    assert queue["selected_count"] == 20
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
                        "corrected_gold_sha256": "corrected" if index == 0 else None,
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
                        "corrected_gold_sha256": f"gold-{index}",
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
        human_holdout_ids_path=holdout,
        operations_policy=config["operations"],
    )
    assert manifest["record_count"] == 1
    assert manifest["records"][0]["split"] == "train_only"
    assert manifest["records"][0]["loss_weight"] == 0.25
    holdout.write_text("img_0123456789ab\n")
    with pytest.raises(ValueError, match="overlaps a human holdout"):
        build_weighted_pseudo_manifest(
            lifecycle_root,
            tmp_path / "forbidden.json",
            certificate_root=certificate_root,
            revocations_root=tmp_path / "revocations",
            human_holdout_ids_path=holdout,
            operations_policy=config["operations"],
        )
