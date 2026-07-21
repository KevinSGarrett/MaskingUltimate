"""STATIC_PASS multi-person exclusivity/bleed/contact/identity + residual routing.

Fixture-seeded only: never claims MF-P8-11.07 real 10–20 image demo, Kevin
sources, doctor-green, gold, or PRODUCTION_EVIDENCE_PASS.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from ..qa.multi_instance import MultiInstanceQcInputs
from ..serve.routing import build_multi_person_image_routes
from ..validation import validate_document
from .multi_person_gate import evaluate_multi_person_candidate_gate
from .tournament import CandidateEvidence, run_candidate_tournament

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "multi_person_static_contracts_report"
AUTHORITY = "multi_person_static_contracts_only_no_real_demo_kevin_sources_or_production_authority"
SCHEMA_VERSION = "1.0.0"
PIPELINE = "pipeline-v1-static-mp"

GATE_FAMILIES = (
    "exclusivity_qc035",
    "bleed_qc036",
    "identity_containment_aut_mp_001",
    "contact_reciprocity_aut_mp_002_003",
)
ROUTING_FAMILIES = (
    "failed_gate_routes_residual",
    "mixed_certified_residual_one_truth_partition",
    "certified_duo_serves_without_routine_review",
)


class MultiPersonStaticContractError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha(document: dict[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _clean_duo_inputs() -> tuple[MultiInstanceQcInputs, dict[tuple[str, str], str]]:
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
        atomic_unions={"p0": p0.copy(), "p1": p1.copy()},
        contact_bands={("p0", "p1"): band0, ("p1", "p0"): band1},
        recorded_relationships={"p0": frozenset({"p1"}), "p1": frozenset({"p0"})},
        expected_promoted_count=2,
    )
    return inputs, {("p0", "p1"): "contact", ("p1", "p0"): "contact"}


def _gate(inputs: MultiInstanceQcInputs, relationships: dict[tuple[str, str], str]):
    return evaluate_multi_person_candidate_gate(
        inputs,
        instance_context="duo",
        promoted_instances=("p0", "p1"),
        relationships=relationships,
    )


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


def _tournament_config() -> dict[str, Any]:
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


def _seal_certificate() -> dict[str, Any]:
    document = {
        "schema_version": "2.0.0",
        "audit_authority": "human_anchor_gold",
        "passed": True,
        "risk_bucket": "contact",
        "instance_context": "duo",
        "covered_labels": ["hair"],
        "covered_contexts": ["duo"],
        "pipeline_fingerprint": PIPELINE,
        "issued_at": "2026-07-19T00:00:00Z",
        "expires_at": "2026-08-19T00:00:00Z",
    }
    document["sha256"] = _sha(document)
    return document


def _lifecycle(instance_id: str, *, certified: bool) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "image_id": "img_a1b2c3d4e5f6",
        "instance_id": instance_id,
        "label": "hair",
        "context": "duo",
        "pipeline_fingerprint": PIPELINE,
        "status": "calibrated_auto_accepted" if certified else "residual_human_queue",
        "truth_tier": "autonomous_certified_gold" if certified else "machine_candidate",
        "training_loss_weight": 0.65 if certified else 0.0,
        "holdout_eligible": False,
        "winner_id": "candidate",
        "winner_mask_path": "mask.png",
        "winner_mask_sha256": "a" * 64,
        "winner_score": 0.99,
        "certificate_valid": certified,
        "certificate_reason": "certificate_valid" if certified else "not_certified",
        "human_audit_required": not certified,
        "authoritative_human_gold": False,
        "serve_eligible": certified,
        "pseudo_train_eligible": certified,
        "reason": "multi_person_static_fixture",
        "ranking": [
            {
                "candidate_id": "candidate",
                "score": 0.99,
                "eligible": True,
                "vetoes": [],
                "mask_sha256": "a" * 64,
            }
        ],
    }


def _evaluate_gate_families() -> dict[str, bool]:
    inputs, relationships = _clean_duo_inputs()
    if not _gate(inputs, relationships).passed:
        raise MultiPersonStaticContractError("clean_duo_gate_failed")

    overlap = replace(
        inputs,
        silhouettes={"p0": inputs.silhouettes["p0"], "p1": inputs.silhouettes["p0"].copy()},
        atomic_unions={"p0": inputs.atomic_unions["p0"], "p1": inputs.atomic_unions["p0"].copy()},
    )
    exclusivity = "QC-035" in _gate(overlap, relationships).blockers

    bleed_atomics = dict(inputs.atomic_unions)
    bleed_atomics["p0"] = bleed_atomics["p0"] | inputs.silhouettes["p1"]
    bleed_result = _gate(replace(inputs, atomic_unions=bleed_atomics), relationships)
    bleed = "QC-036" in bleed_result.blockers
    identity = "AUT-MP-001" in bleed_result.blockers

    one_way = {("p0", "p1"): "contact"}
    contact = {"AUT-MP-002", "AUT-MP-003"} <= set(_gate(inputs, one_way).blockers)

    results = {
        "exclusivity_qc035": exclusivity,
        "bleed_qc036": bleed,
        "identity_containment_aut_mp_001": identity,
        "contact_reciprocity_aut_mp_002_003": contact,
    }
    if set(results) != set(GATE_FAMILIES) or not all(results.values()):
        raise MultiPersonStaticContractError("seeded_gate_families_incomplete_or_unblocked")
    return results


def _evaluate_routing_families() -> dict[str, bool]:
    inputs, relationships = _clean_duo_inputs()
    p0 = inputs.silhouettes["p0"]
    seeded = replace(
        inputs,
        silhouettes={"p0": p0, "p1": p0.copy()},
        atomic_unions={"p0": p0, "p1": p0.copy()},
    )
    failed_gate = _gate(seeded, relationships)
    decision = run_candidate_tournament(
        (_candidate(),),
        label="hair",
        context="contact",
        instance_context="duo",
        multi_person_gate=failed_gate,
        pipeline_fingerprint=PIPELINE,
        config=_tournament_config(),
    )
    failed_gate_routes_residual = (
        decision.status == "residual_human_queue"
        and "multi_person_gate:QC-035" in decision.ranking[0].vetoes
    )

    with tempfile.TemporaryDirectory(prefix="mp_static_routes_") as tmp:
        revocations = Path(tmp) / "revocations"
        revocations.mkdir()
        now = datetime(2026, 7, 19, 18, tzinfo=UTC)
        cert = _seal_certificate()
        mixed = build_multi_person_image_routes(
            {
                "p0": _lifecycle("p0", certified=True),
                "p1": _lifecycle("p1", certified=False),
            },
            {"p0": cert, "p1": cert},
            expected_pipeline_fingerprint=PIPELINE,
            selected_for_audit=False,
            revocations_root=revocations,
            now=now,
        )
        mixed_ok = (
            mixed["truth_partition"] == "residual"
            and set(mixed["instance_truth_partitions"].values()) == {"residual"}
            and mixed["residual_instance_ids"] == ["p1"]
            and mixed["routes"]["p0"]["routing"]["destination"] == "served_without_routine_review"
        )

        certified = build_multi_person_image_routes(
            {
                "p0": _lifecycle("p0", certified=True),
                "p1": _lifecycle("p1", certified=True),
            },
            {"p0": cert, "p1": cert},
            expected_pipeline_fingerprint=PIPELINE,
            selected_for_audit=False,
            revocations_root=revocations,
            now=now,
        )
        certified_ok = (
            certified["truth_partition"] == "train"
            and certified["cvat_instance_ids"] == []
            and {route["routing"]["destination"] for route in certified["routes"].values()}
            == {"served_without_routine_review"}
        )

    results = {
        "failed_gate_routes_residual": failed_gate_routes_residual,
        "mixed_certified_residual_one_truth_partition": mixed_ok,
        "certified_duo_serves_without_routine_review": certified_ok,
    }
    if set(results) != set(ROUTING_FAMILIES) or not all(results.values()):
        raise MultiPersonStaticContractError("seeded_routing_families_incomplete_or_failed")
    return results


def run_multi_person_static_contract_suite() -> dict[str, Any]:
    """Execute fixture-seeded gate + residual-routing STATIC contracts."""
    gate_blocks = _evaluate_gate_families()
    routing = _evaluate_routing_families()
    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "seeded_gate_blocks": dict(sorted(gate_blocks.items())),
        "seeded_routing_checks": dict(sorted(routing.items())),
        "checks": {
            "exclusivity_bleed_identity_contact_gates": "pass",
            "residual_routing_and_split_integrity": "pass",
        },
        "mf_p8_11_07_demo_complete": False,
        "kevin_multi_person_sources_required": True,
        "real_10_20_image_demo_claimed": False,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "visual_qa_pass_claimed": False,
        "main_complete_claimed": False,
        "production_evidence_pass_claimed": False,
        "honest_non_claims": [
            "mf_p8_11_07_real_demo",
            "kevin_governed_multi_person_sources",
            "d11_g9_headline_measurement",
            "doctor_green",
            "gold",
            "production_evidence_pass",
        ],
    }
    digest = _sha(draft)
    draft["report_id"] = f"mpsc_{digest[:24]}"
    draft["seal_sha256"] = digest
    draft["sha256"] = _sha({key: value for key, value in draft.items() if key != "sha256"})
    issues = validate_document(draft, "multi_person_static_contracts_report")
    if issues:
        detail = "; ".join(f"{issue.pointer or '/'}: {issue.message}" for issue in issues)
        raise MultiPersonStaticContractError(f"report_schema_invalid: {detail}")
    return draft


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "GATE_FAMILIES",
    "PROOF_TIER",
    "ROUTING_FAMILIES",
    "SCHEMA_VERSION",
    "MultiPersonStaticContractError",
    "run_multi_person_static_contract_suite",
]
