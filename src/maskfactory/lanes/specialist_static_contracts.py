"""STATIC_PASS specialist lane / QC-panel / residual-routing contracts.

Fixture-seeded only: never claims MF-P3-07 SOP cadence, 100 certified packages,
MF-P3-EXIT, Kevin review minutes, doctor-green, gold, or PRODUCTION_EVIDENCE_PASS.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ..serve.routing import build_certificate_aware_serving_route
from ..validation import validate_document
from .chest import (
    build_breast_seeds,
    clothing_boundary_chest,
    render_mandatory_chest_panels,
    visible_breast_truth,
)
from .feet import apply_footwear_logic, split_foot_base_toes
from .hair import apply_hair_shoulder_zorder, build_face_protected, render_hairline_panel
from .hand import (
    apply_finger_merge_policy,
    assign_gap_ownership,
    build_hand_geometry,
)

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "specialist_static_contracts_report"
AUTHORITY = "specialist_static_contracts_only_no_sop_cadence_100_certified_or_p3_exit_authority"
SCHEMA_VERSION = "1.0.0"
PIPELINE = "pipeline-v1-static-specialist"

LANE_FAMILIES = (
    "hand_gap_ownership_and_finger_merge_residual",
    "chest_visible_truth_and_boundary_band",
    "hair_shoulder_zorder_and_face_protect",
    "feet_shod_material_and_toes_not_visible",
)
PANEL_FAMILIES = (
    "mandatory_chest_panel_2560x512",
    "hairline_panel_2560x512",
)
ROUTING_FAMILIES = (
    "certificate_covered_serves_without_routine_review",
    "uncertified_routes_residual_only",
    "preselected_audit_destination",
    "review_sample_excludes_certificate_covered_routine",
)

SPECIALIST_LABELS = (
    "left_hand_base",
    "left_breast",
    "hair",
    "left_foot_base",
)


class SpecialistStaticContractError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha(document: dict[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _hand_landmarks() -> np.ndarray:
    points = np.zeros((21, 2), dtype=np.float64)
    points[0] = (50, 90)
    points[1:5] = [(42, 82), (35, 75), (30, 67), (25, 60)]
    for start, x in ((5, 28), (9, 44), (13, 60), (17, 76)):
        points[start : start + 4] = [(x, 72), (x, 58), (x, 44), (x, 30)]
    return points


def _chest_torso() -> np.ndarray:
    torso = np.zeros((200, 200), dtype=bool)
    torso[40:160, 60:140] = True
    return torso


def _evaluate_lane_families() -> dict[str, bool]:
    parsing = np.zeros((120, 100), dtype=bool)
    parsing[20:100, 12:90] = True
    geometry = build_hand_geometry(_hand_landmarks(), parsing, side="left")
    finger_union = np.logical_or.reduce(tuple(geometry.finger_masks.values()))
    gap_ok = (
        geometry.finger_gap_regions.any()
        and not (geometry.finger_gap_regions & finger_union).any()
        and geometry.hand_base.any()
        and not (geometry.hand_base & finger_union).any()
    )
    behind = np.zeros(parsing.shape, dtype=np.uint16)
    behind[geometry.finger_gap_regions] = 7
    owned = assign_gap_ownership(geometry.finger_gap_regions, behind)
    ownership_ok = bool(
        np.all(owned[geometry.finger_gap_regions] == 7)
        and np.all(owned[~geometry.finger_gap_regions] == 0)
    )
    low_conf = np.full(21, 0.9, dtype=np.float64)
    low_conf[5:9] = 0.2
    merge = apply_finger_merge_policy(geometry, low_conf, side="left")
    merge_ok = (
        merge.fingers_merged_or_ambiguous
        and merge.failure_queue_record is not None
        and merge.failure_queue_record["reason"] == "finger_merge"
        and merge.visibility_states.get("left_index_finger") == "ambiguous_do_not_use"
    )
    hand_ok = gap_ok and ownership_ok and merge_ok

    seeds = build_breast_seeds(
        _chest_torso(),
        left_shoulder_xy=(140, 45),
        right_shoulder_xy=(60, 45),
        under_bust_y=115,
        view="front",
    )
    empty_skin = np.zeros_like(seeds.left)
    fabric = seeds.left | seeds.right
    clothed = visible_breast_truth(seeds, skin_contour=empty_skin, fabric_contour=fabric)
    region = np.zeros((100, 100), dtype=bool)
    region[20:80, 20:80] = True
    skin_half = np.zeros_like(region)
    clothing_half = np.zeros_like(region)
    skin_half[20:80, 20:50] = True
    clothing_half[20:80, 50:80] = True
    band = clothing_boundary_chest(region, skin_half, clothing_half)
    chest_ok = (
        clothed.left_part.any()
        and clothed.right_part.any()
        and not clothed.left_breast_skin.any()
        and not clothed.right_breast_skin.any()
        and band.any()
    )

    shape = (100, 100)
    details = {}
    for index, name in enumerate(
        ("left_eye", "right_eye", "mouth", "nose", "left_brow", "right_brow", "jawline")
    ):
        mask = np.zeros(shape, dtype=bool)
        mask[30 + index : 32 + index, 40:45] = True
        details[name] = mask
    protected = build_face_protected(details, shape=shape)
    hair = np.zeros(shape, dtype=bool)
    hair[10:60, 20:80] = True
    left = np.zeros(shape, dtype=bool)
    right = np.zeros(shape, dtype=bool)
    left[50:80, 20:50] = True
    right[50:80, 50:80] = True
    carved, states = apply_hair_shoulder_zorder(
        hair, {"left_shoulder": left, "right_shoulder": right}
    )
    hair_ok = (
        protected.any()
        and not (carved["left_shoulder"] & hair).any()
        and states == {"left_shoulder": "partially_visible", "right_shoulder": "partially_visible"}
    )

    foot = np.zeros((60, 100), dtype=bool)
    foot[20:40, 10:90] = True
    split = split_foot_base_toes(foot, heel_xy=(15, 30), big_toe_xy=(85, 24), small_toe_xy=(85, 36))
    shod = apply_footwear_logic(
        split, side="left", coverage="closed_shoe", visible_skin=foot.copy()
    )
    feet_ok = (
        np.array_equal(shod.foot_base, foot)
        and not shod.toes.any()
        and shod.visibility_states["left_toes"] == "not_visible"
        and np.all(shod.material_map[foot] == 8)
        and not shod.visible_body_skin.any()
    )

    results = {
        "hand_gap_ownership_and_finger_merge_residual": bool(hand_ok),
        "chest_visible_truth_and_boundary_band": bool(chest_ok),
        "hair_shoulder_zorder_and_face_protect": bool(hair_ok),
        "feet_shod_material_and_toes_not_visible": bool(feet_ok),
    }
    if set(results) != set(LANE_FAMILIES) or not all(results.values()):
        raise SpecialistStaticContractError("seeded_lane_families_incomplete_or_failed")
    return results


def _evaluate_panel_families() -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="p3_static_panels_") as tmp:
        root = Path(tmp)
        region = np.zeros((100, 100), dtype=bool)
        region[20:80, 20:80] = True
        skin = np.zeros_like(region)
        clothing = np.zeros_like(region)
        skin[20:80, 20:50] = True
        clothing[20:80, 50:80] = True
        band = clothing_boundary_chest(region, skin, clothing)
        chest_panels = render_mandatory_chest_panels(
            Image.new("RGB", (100, 100), "gray"),
            {"clothing_boundary_chest": band},
            np.zeros_like(region),
            root / "chest",
        )
        chest_ok = len(chest_panels) == 1 and Image.open(chest_panels[0]).size == (2560, 512)

        shape = (100, 100)
        details = {}
        for index, name in enumerate(
            ("left_eye", "right_eye", "mouth", "nose", "left_brow", "right_brow", "jawline")
        ):
            mask = np.zeros(shape, dtype=bool)
            mask[30 + index : 32 + index, 40:45] = True
            details[name] = mask
        protected = build_face_protected(details, shape=shape)
        hair = np.zeros(shape, dtype=bool)
        hair[10:60, 20:80] = True
        hairline = render_hairline_panel(
            Image.new("RGB", (100, 100), "gray"),
            hair,
            protected,
            root / "hairline.png",
        )
        hair_ok = Image.open(hairline).size == (2560, 512)

    results = {
        "mandatory_chest_panel_2560x512": bool(chest_ok),
        "hairline_panel_2560x512": bool(hair_ok),
    }
    if set(results) != set(PANEL_FAMILIES) or not all(results.values()):
        raise SpecialistStaticContractError("seeded_panel_families_incomplete_or_failed")
    return results


def _seal_certificate(label: str, *, risk_bucket: str) -> dict[str, Any]:
    document = {
        "schema_version": "2.0.0",
        "audit_authority": "human_anchor_gold",
        "passed": True,
        "risk_bucket": risk_bucket,
        "instance_context": "solo",
        "covered_labels": [label],
        "covered_contexts": ["solo"],
        "pipeline_fingerprint": PIPELINE,
        "issued_at": "2026-07-19T00:00:00Z",
        "expires_at": "2026-08-19T00:00:00Z",
    }
    document["sha256"] = _sha(document)
    return document


def _lifecycle(label: str, *, certified: bool) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "image_id": "img_a1b2c3d4e5f6",
        "instance_id": "p0",
        "label": label,
        "context": "solo",
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
        "reason": "specialist_static_fixture",
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


def _evaluate_routing_families() -> dict[str, bool]:
    label_buckets = {
        "left_hand_base": "fingers",
        "left_breast": "chest_boundary",
        "hair": "hairline",
        "left_foot_base": "toes",
    }
    if set(label_buckets) != set(SPECIALIST_LABELS):
        raise SpecialistStaticContractError("specialist_label_set_drift")

    with tempfile.TemporaryDirectory(prefix="p3_static_routes_") as tmp:
        revocations = Path(tmp) / "revocations"
        revocations.mkdir()
        now = datetime(2026, 7, 19, 18, tzinfo=UTC)
        review_sample: list[dict[str, str]] = []

        certified_ok = True
        residual_ok = True
        audit_ok = True
        for label, risk_bucket in label_buckets.items():
            cert = _seal_certificate(label, risk_bucket=risk_bucket)
            served = build_certificate_aware_serving_route(
                _lifecycle(label, certified=True),
                cert,
                expected_pipeline_fingerprint=PIPELINE,
                selected_for_audit=False,
                revocations_root=revocations,
                now=now,
            )
            certified_ok = certified_ok and (
                served["routing"]["destination"] == "served_without_routine_review"
                and served["routing"]["residual_reason"] is None
            )

            residual = build_certificate_aware_serving_route(
                _lifecycle(label, certified=False),
                cert,
                expected_pipeline_fingerprint=PIPELINE,
                selected_for_audit=False,
                revocations_root=revocations,
                now=now,
            )
            residual_reason = residual["routing"]["residual_reason"]
            residual_ok = residual_ok and (
                residual["routing"]["destination"] == "cvat_residual_review"
                and isinstance(residual_reason, str)
                and residual_reason.startswith("lifecycle_not_certified:")
            )
            if residual_ok:
                review_sample.append(
                    {
                        "label": label,
                        "destination": residual["routing"]["destination"],
                        "reason": residual_reason,
                    }
                )

            audit = build_certificate_aware_serving_route(
                _lifecycle(label, certified=True),
                cert,
                expected_pipeline_fingerprint=PIPELINE,
                selected_for_audit=True,
                revocations_root=revocations,
                now=now,
            )
            audit_ok = audit_ok and (
                audit["routing"]["destination"] == "cvat_preselected_audit"
                and audit["routing"]["audit_reason"] == "preselected_random_or_risk_audit"
                and audit["routing"]["residual_reason"] is None
            )
            if audit_ok:
                review_sample.append(
                    {
                        "label": label,
                        "destination": audit["routing"]["destination"],
                        "reason": str(audit["routing"]["audit_reason"]),
                    }
                )

        allowed_destinations = {"cvat_residual_review", "cvat_preselected_audit"}
        sample_ok = bool(review_sample) and all(
            item["destination"] in allowed_destinations
            and item["destination"] != "served_without_routine_review"
            for item in review_sample
        )

    results = {
        "certificate_covered_serves_without_routine_review": bool(certified_ok),
        "uncertified_routes_residual_only": bool(residual_ok),
        "preselected_audit_destination": bool(audit_ok),
        "review_sample_excludes_certificate_covered_routine": bool(sample_ok),
    }
    if set(results) != set(ROUTING_FAMILIES) or not all(results.values()):
        raise SpecialistStaticContractError("seeded_routing_families_incomplete_or_failed")
    return results


def run_specialist_static_contract_suite() -> dict[str, Any]:
    """Execute fixture-seeded lane + panel + residual-routing STATIC contracts."""
    lanes = _evaluate_lane_families()
    panels = _evaluate_panel_families()
    routing = _evaluate_routing_families()
    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "specialist_labels": list(SPECIALIST_LABELS),
        "seeded_lane_checks": dict(sorted(lanes.items())),
        "seeded_panel_checks": dict(sorted(panels.items())),
        "seeded_routing_checks": dict(sorted(routing.items())),
        "checks": {
            "hand_chest_hair_feet_lane_contracts": "pass",
            "qc_panel_fixtures": "pass",
            "residual_and_preselected_audit_routing": "pass",
        },
        "mf_p3_07_01_sop_cadence_complete": False,
        "mf_p3_07_02_100_certified_complete": False,
        "mf_p3_07_03_labor_metrics_complete": False,
        "mf_p3_07_04_second_look_complete": False,
        "mf_p3_exit_complete": False,
        "kevin_sop_cadence_required": True,
        "certified_package_count": 0,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "visual_qa_pass_claimed": False,
        "main_complete_claimed": False,
        "production_evidence_pass_claimed": False,
        "honest_non_claims": [
            "mf_p3_07_sop_cadence",
            "mf_p3_07_100_certified_packages",
            "mf_p3_07_kevin_review_minutes",
            "mf_p3_07_fresh_day_second_look",
            "mf_p3_exit",
            "doctor_green",
            "gold",
            "production_evidence_pass",
        ],
    }
    digest = _sha(draft)
    draft["report_id"] = f"ssc_{digest[:24]}"
    draft["seal_sha256"] = digest
    draft["sha256"] = _sha({key: value for key, value in draft.items() if key != "sha256"})
    issues = validate_document(draft, "specialist_static_contracts_report")
    if issues:
        detail = "; ".join(f"{issue.pointer or '/'}: {issue.message}" for issue in issues)
        raise SpecialistStaticContractError(f"report_schema_invalid: {detail}")
    return draft


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "LANE_FAMILIES",
    "PANEL_FAMILIES",
    "PROOF_TIER",
    "ROUTING_FAMILIES",
    "SCHEMA_VERSION",
    "SPECIALIST_LABELS",
    "SpecialistStaticContractError",
    "run_specialist_static_contract_suite",
]
