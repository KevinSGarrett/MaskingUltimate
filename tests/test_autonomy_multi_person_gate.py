from dataclasses import replace

import numpy as np

from maskfactory.autonomy.multi_person_gate import evaluate_multi_person_candidate_gate
from maskfactory.autonomy.tournament import CandidateEvidence, run_candidate_tournament
from maskfactory.qa.multi_instance import MultiInstanceQcInputs


def _inputs() -> tuple[MultiInstanceQcInputs, dict[tuple[str, str], str]]:
    p0 = np.zeros((64, 96), dtype=bool)
    p1 = np.zeros_like(p0)
    p0[8:56, 4:36] = True
    p1[8:56, 60:92] = True
    band0 = np.zeros_like(p0)
    band1 = np.zeros_like(p0)
    band0[28:36, 32:36] = True
    band1[28:36, 60:64] = True
    inputs = MultiInstanceQcInputs(
        silhouettes={"p0": p0, "p1": p1},
        atomic_unions={"p0": p0, "p1": p1},
        contact_bands={("p0", "p1"): band0, ("p1", "p0"): band1},
        recorded_relationships={"p0": frozenset({"p1"}), "p1": frozenset({"p0"})},
        expected_promoted_count=2,
    )
    return inputs, {("p0", "p1"): "contact", ("p1", "p0"): "contact"}


def _candidate() -> CandidateEvidence:
    return CandidateEvidence(
        "candidate",
        "candidate.png",
        "a" * 64,
        3,
        0.99,
        0.99,
        0.99,
        1.0,
        False,
        0.0,
        0.0,
        1,
        1,
        True,
        (),
    )


def _config() -> dict:
    return {
        "tournament": {
            "maximum_candidates_per_label": 8,
            "minimum_independent_sources": 2,
            "minimum_score": 0.5,
            "minimum_winner_margin": 0.0,
            "weights": {
                "consensus_iou": 0.25,
                "boundary_agreement": 0.25,
                "pose_consistency": 0.15,
                "source_diversity": 0.15,
                "critic_support": 0.20,
            },
            "hard_veto": {
                "require_format_valid": True,
                "reject_any_block_qc": True,
                "maximum_protected_overlap": 0.0,
                "maximum_exclusive_overlap": 0.0,
                "reject_component_overflow": True,
            },
        },
        "operations": {
            "cloud_disagreement_forces_residual_queue": True,
            "calibrated_status": "calibrated_auto_accepted",
            "uncalibrated_status": "machine_verified_candidate",
            "calibrated_truth_tier": "autonomous_certified_gold",
            "uncalibrated_truth_tier": "machine_candidate",
        },
        "truth_tiers": {
            "autonomous_certified_gold": {"training_weight": 0.65},
            "machine_candidate": {"training_weight": 0.0},
        },
    }


def _gate(inputs: MultiInstanceQcInputs, relationships: dict[tuple[str, str], str]):
    return evaluate_multi_person_candidate_gate(
        inputs,
        instance_context="duo",
        promoted_instances=("p0", "p1"),
        relationships=relationships,
    )


def test_clean_duo_passes_every_multi_person_autonomy_gate() -> None:
    inputs, relationships = _inputs()
    result = _gate(inputs, relationships)
    assert result.passed
    assert result.blockers == ()


def test_duo_tournament_requires_explicit_passing_image_gate() -> None:
    missing = run_candidate_tournament(
        (_candidate(),),
        label="hair",
        context="contact",
        instance_context="duo",
        pipeline_fingerprint="pipeline-v1",
        config=_config(),
    )
    assert missing.status == "residual_human_queue"
    assert "multi_person_gate_missing" in missing.ranking[0].vetoes

    inputs, relationships = _inputs()
    passed = run_candidate_tournament(
        (_candidate(),),
        label="hair",
        context="contact",
        instance_context="duo",
        multi_person_gate=_gate(inputs, relationships),
        pipeline_fingerprint="pipeline-v1",
        config=_config(),
    )
    assert passed.status == "residual_human_queue"
    assert "multi_person_scope_missing" in passed.ranking[0].vetoes


def test_seeded_qc035_overlap_blocks_every_candidate() -> None:
    inputs, relationships = _inputs()
    p0 = inputs.silhouettes["p0"]
    seeded = replace(
        inputs,
        silhouettes={"p0": p0, "p1": p0.copy()},
        atomic_unions={"p0": p0, "p1": p0.copy()},
    )
    result = _gate(seeded, relationships)
    assert "QC-035" in result.blockers
    decision = run_candidate_tournament(
        (_candidate(),),
        label="torso",
        context="duo_overlap",
        instance_context="duo",
        multi_person_gate=result,
        pipeline_fingerprint="pipeline-v1",
        config=_config(),
    )
    assert decision.status == "residual_human_queue"
    assert "multi_person_gate:QC-035" in decision.ranking[0].vetoes


def test_seeded_cross_person_identity_bleed_and_missing_identity_block() -> None:
    inputs, relationships = _inputs()
    atomics = dict(inputs.atomic_unions)
    atomics["p0"] = atomics["p0"] | inputs.silhouettes["p1"]
    result = _gate(replace(inputs, atomic_unions=atomics), relationships)
    assert {"QC-036", "AUT-MP-001"} <= set(result.blockers)

    missing = dict(inputs.atomic_unions)
    missing["p1"] = np.zeros_like(missing["p1"])
    assert "AUT-MP-001" in _gate(replace(inputs, atomic_unions=missing), relationships).blockers


def test_seeded_contact_and_occlusion_reciprocity_defects_block() -> None:
    inputs, relationships = _inputs()
    one_way = {("p0", "p1"): "contact"}
    result = _gate(inputs, one_way)
    assert {"AUT-MP-002", "AUT-MP-003"} <= set(result.blockers)

    occlusion = {("p0", "p1"): "occludes", ("p1", "p0"): "occludes"}
    assert "AUT-MP-002" in _gate(inputs, occlusion).blockers

    inverse = {("p0", "p1"): "occludes", ("p1", "p0"): "occluded_by"}
    assert _gate(inputs, inverse).passed
