"""Isolated Main-consumer DoD-climb runner #2 (MF-P6-11.04 / 11.08).

Second standalone sibling of ``tools/run_isolated_main_consumer.py`` and
``tools/run_isolated_main_consumer_dod.py``. It extends producer-side DoD coverage
with two additional *real-machinery* matrices that the prior two runners do not
exercise, and emits isolated-consumer-signed evidence:

  * ``isolated_receipt_arbitration_dod_matrix`` (MF-P6-11.04): normalize/arbitrate
    Mode A vs Mode B receipts under the pinned arbitration policy — wrapper-certified
    Mode A dominates an uncertified Mode B draft, close alternatives branch, a third
    same-scope candidate forces deterministic abstain, a Main decision that selects
    the cheap draft is refused as silent weakening, and a high-preservation-risk /
    authority-floor candidate abstains. Runs the real ``normalize_and_arbitrate_receipts``
    and ``build_receipt_arbitration_conformance_evidence`` + validator.
  * ``isolated_recovery_dod_matrix`` (MF-P6-11.08): receipt-last commit ordering,
    kill-at-every-durable-boundary fail-closed recovery (all 15 boundaries), clean
    full-chain commit readiness, and adversarial receipt-before-artifacts /
    unresolved-digest / orphan-promotion+authority-drift / foreign-lease-cleanup /
    duplicate-resubmit refusals. Runs the real ``build_recovery_evidence`` /
    ``simulate_kill_at_boundary`` + validator.

Honesty ceiling (binding): producer-side, isolated-consumer-signed only. It NEVER
claims real Comfy_UI_Main adoption. HARD MF-P6-11.02 / 11.07 / 12.05 / 12.06 remain
OPEN and are recorded in the evidence, not hidden. Comfy_UI_Main is a dirty Wave64
tree and is NOT touched.

Kept as a standalone file (not folded into the shared runners) so this stream's work
is durable under heavy multi-agent working-tree churn.

Usage:
  python tools/run_isolated_main_consumer_dod2.py \
      --output runtime_artifacts/main_consumer/isolated_consumer_dod2_run_evidence_<ts>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from maskfactory.bridge.receipt_arbitration_conformance import (
    build_receipt_arbitration_conformance_evidence,
    normalize_and_arbitrate_receipts,
    validate_receipt_arbitration_conformance_evidence,
)
from maskfactory.bridge.recovery import (
    build_recovery_evidence,
    simulate_kill_at_boundary,
    validate_recovery_evidence,
)
from maskfactory.validation import canonical_document_sha256

REPO_ROOT = Path(__file__).resolve().parents[1]
DECIDED_AT = "2026-07-20T05:00:00Z"

HARD_BLOCKERS_REQUIRING_REAL_MAIN = (
    "MF-P6-11.02",
    "MF-P6-11.07",
    "MF-P6-12.05",
    "MF-P6-12.06",
)


def _git_head() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    value = out.stdout.strip().lower()
    return value if len(value) == 40 and all(c in "0123456789abcdef" for c in value) else None


# ---------------------------------------------------------------------------
# MF-P6-11.04 receipt arbitration DoD fixtures (mirrors the passing test suite).
# ---------------------------------------------------------------------------

_RELEASE = "ffbef9cea69a8bbe7c51bf464d127c0d3ffbc9cdc24798d5ccb8eb1b969f215a"
_CAPABILITY = "0515eaeff6a2242c1877d7ae7bce072736a8cebddb249bf28b25e119857fd230"
_REVOCATION = "4444444444444444444444444444444444444444444444444444444444444444"
_SOURCE = "3333333333333333333333333333333333333333333333333333333333333333"
_TRANSFORM = "361555fb909a4648d3c4efc6e65458d9f4e50c7bd711b7aabc4495c1b09fae1f"
_ARB_DECIDED_AT = "2026-07-19T12:00:00Z"


def _heads(**overrides: Any) -> dict[str, Any]:
    base = {
        "release_payload_sha256": _RELEASE,
        "capability_snapshot_sha256": _CAPABILITY,
        "revocation_index_sha256": _REVOCATION,
        "ontology_version": "body_parts_v1",
        "required_authority_floor": "draft",
        "required_qa_status": "pass",
        "max_preservation_risk": 0.5,
        "max_total_ms": 60000,
        "max_peak_vram_mb": 24576,
        "max_uncertainty": 0.2,
    }
    base.update(overrides)
    return base


def _region(region_id: str, *, authority_state: str = "certified") -> dict[str, Any]:
    return {
        "region_id": region_id,
        "artifact_identity_sha256": "a" * 64,
        "encoded_sha256": "b" * 64,
        "decoded_mask_sha256": "c" * 64,
        "source_decoded_pixel_sha256": _SOURCE,
        "artifact_type": "atomic",
        "owner_identity_sha256": "d" * 64,
        "coordinate_space": "output_pixel",
        "width": 512,
        "height": 512,
        "transform_chain_sha256": _TRANSFORM,
        "transform_step_sequence": 0,
        "required_minimum_authority_state": authority_state,
        "authority_state": authority_state,
        "issuer_kind": "maskfactory_autonomous",
        "certificate_kind": (
            "exact_serving_route_output" if authority_state == "certified" else "none"
        ),
        "certificate_id": (
            "mfac_aaaaaaaaaaaaaaaaaaaaaaaa" if authority_state == "certified" else None
        ),
        "certificate_sha256": "e" * 64 if authority_state == "certified" else None,
        "certificate_scope_sha256": "f" * 64 if authority_state == "certified" else None,
        "certificate_status": "active" if authority_state == "certified" else "none",
        "certificate_exact_scope_match": authority_state == "certified",
        "revocation_checked_at": "2026-07-19T00:00:00Z" if authority_state == "certified" else None,
        "revocation_checkpoint_sha256": _REVOCATION if authority_state == "certified" else None,
    }


def _receipt(
    *,
    access_mode: str,
    authority_state: str,
    receipt_suffix: str,
    total_ms: int = 4000,
    peak_vram_mb: int = 2048,
    uncertainty: float = 0.01,
    completed_at: str = "2026-07-19T00:00:05Z",
    artifact_kind: str = "atomic_visible",
    representation_class: str | None = None,
    package_certificate_active: bool = True,
    certificate_active: bool = True,
    person_index: int = 0,
) -> dict[str, Any]:
    certified = authority_state == "certified"
    return {
        "schema_version": "1.0.0",
        "record_type": "mask_acquisition_receipt",
        "receipt_id": f"mfarec_{receipt_suffix}",
        "request_id": f"mfareq_{receipt_suffix}",
        "request_payload_sha256": "1" * 64,
        "project_id": "comfy-main-fixture",
        "run_id": "run-fixture",
        "job_id": "job-fixture",
        "pass_id": "pass-mask-fixture",
        "attempt_id": "attempt-1",
        "result": "succeeded",
        "access_mode": access_mode,
        "completed_at": completed_at,
        "media_scope": {
            "scope_kind": "still_image",
            "sequence_id": "sequence-fixture",
            "shot_id": "shot-fixture",
            "take_id": "take-fixture",
            "source_video_sha256": None,
            "decoded_frame_sha256": None,
            "frame_index": None,
        },
        "release_binding": {
            "release_payload_sha256": _RELEASE,
            "capability_snapshot_sha256": _CAPABILITY,
        },
        "source_binding": {"decoded_pixel_sha256": _SOURCE},
        "subject_binding": {
            "character_id": "character-fixture",
            "character_revision": "1.0.0",
            "scene_instance_id": "scene-instance-001",
            "canonical_person_id": "person-canonical-001",
            "person_index": person_index,
        },
        "execution_observation": {
            "total_ms": total_ms,
            "resources": {"peak_vram_mb": peak_vram_mb},
        },
        "artifacts": [
            {
                "intent_id": "intent-left-hand",
                "label": "left_hand",
                "artifact_kind": artifact_kind,
                "mask_type": "atomic",
                "coordinate_space": "output_pixel",
                "decoded_mask_sha256": "9" * 64,
                **(
                    {"representation_class": representation_class}
                    if representation_class is not None
                    else {}
                ),
            }
        ],
        "transform_validation": {
            "transform_chain_sha256": _TRANSFORM,
            "output_coordinate_space": "output_pixel",
        },
        "qa": {"status": "pass", "uncertainty": uncertainty, "blocking_failures": []},
        "authority": {
            "authority_state": authority_state,
            "certificate_status": "active" if certified and certificate_active else "none",
            "certificate_exact_scope_match": bool(certified and certificate_active),
            "certificate_sha256": "8" * 64 if certified else None,
            "revocation_index_sha256": _REVOCATION if certified else None,
        },
        "lineage": {
            "operation_kind": (
                "package_read" if access_mode == "mode_a_package_read" else "original_prediction"
            ),
            "package_certificate_status": (
                "active"
                if access_mode == "mode_a_package_read" and package_certificate_active
                else "none"
            ),
            "package_certificate_exact_scope_match": bool(
                access_mode == "mode_a_package_read" and package_certificate_active
            ),
            "input_target_regions": [_region("target-left-hand")],
            "input_protected_regions": [_region("protected-other-torso")],
        },
        "use_eligibility": {
            "exact_use_scope": "production_conditioning",
            "required_authority_state": "certified",
        },
        "receipt_payload_sha256": canonical_document_sha256(
            {"receipt_suffix": receipt_suffix, "access_mode": access_mode}
        ),
    }


def _candidate(candidate_id: str, receipt: dict[str, Any], *, preservation_risk: float = 0.1):
    return {
        "candidate_id": candidate_id,
        "receipt": receipt,
        "receipt_payload_sha256": receipt["receipt_payload_sha256"],
        "preservation_risk": preservation_risk,
    }


def _main_decision(
    arbitration: dict[str, Any],
    *,
    outcome: str | None = None,
    selected: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "outcome": outcome or arbitration["oracle_decision"]["outcome"],
        "selected_candidate_ids": list(
            selected
            if selected is not None
            else arbitration["oracle_decision"]["selected_candidate_ids"]
        ),
        "comparable_scope_sha256": arbitration["comparable_scope_sha256"],
        "receipt_payload_sha256s": sorted(
            row["receipt_payload_sha256"] for row in arbitration["evaluated"]
        ),
        "policy_sha256": arbitration["policy_sha256"],
        "signature": {
            "key_id": "comfy-main-arbitration-prod",
            "public_key_base64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "signed_payload_sha256": "b" * 64,
            "value_base64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        },
    }


def run_receipt_arbitration_dod_matrix() -> dict[str, Any]:
    """MF-P6-11.04 arbitration DoD over the real conformance oracle + validator."""
    rows: list[dict[str, Any]] = []

    # 1. Wrapper-certified Mode A dominates an uncertified Mode B draft; an
    #    accepted Main decision that agrees validates clean.
    mode_a = _receipt(
        access_mode="mode_a_package_read",
        authority_state="certified",
        receipt_suffix="aaaaaaaaaaaaaaaaaaaaaaaa",
        total_ms=9000,
    )
    mode_b = _receipt(
        access_mode="mode_b_live_predict",
        authority_state="draft",
        receipt_suffix="bbbbbbbbbbbbbbbbbbbbbbbb",
        total_ms=1000,
    )
    candidates = [
        _candidate("mode-b-draft", mode_b, preservation_risk=0.05),
        _candidate("mode-a-certified", mode_a, preservation_risk=0.2),
    ]
    arbitration = normalize_and_arbitrate_receipts(
        candidates, decided_at=_ARB_DECIDED_AT, producer_heads=_heads()
    )
    dominance_ok = any(
        row["reason"] == "wrapper_mode_a_dominates_draft"
        for row in arbitration["dominance_eliminations"]
    )
    main = _main_decision(arbitration)
    evidence = build_receipt_arbitration_conformance_evidence(
        candidates, main, decided_at=_ARB_DECIDED_AT, producer_heads=_heads()
    )
    rows.append(
        {
            "case": "wrapper_mode_a_dominates_uncertified_mode_b_draft",
            "passed": bool(
                arbitration["oracle_decision"]["outcome"] == "choose"
                and arbitration["oracle_decision"]["selected_candidate_ids"] == ["mode-a-certified"]
                and dominance_ok
                and evidence["status"] == "accepted"
                and validate_receipt_arbitration_conformance_evidence(evidence) == ()
            ),
        }
    )

    # 2. Two same-scope certified alternatives branch deterministically.
    left = _receipt(
        access_mode="mode_b_live_predict",
        authority_state="certified",
        receipt_suffix="eeeeeeeeeeeeeeeeeeeeeeee",
        total_ms=4000,
    )
    right = _receipt(
        access_mode="mode_b_live_refine",
        authority_state="certified",
        receipt_suffix="ffffffffffffffffffffffff",
        total_ms=4000,
    )
    branch_candidates = [_candidate("alt-b", right), _candidate("alt-a", left)]
    branched = normalize_and_arbitrate_receipts(
        branch_candidates, decided_at=_ARB_DECIDED_AT, producer_heads=_heads()
    )
    rows.append(
        {
            "case": "close_alternatives_branch_deterministic",
            "passed": bool(
                branched["oracle_decision"]["outcome"] == "branch"
                and branched["oracle_decision"]["selected_candidate_ids"] == ["alt-a", "alt-b"]
            ),
        }
    )

    # 3. A third same-scope candidate forces deterministic abstain.
    third = _receipt(
        access_mode="mode_b_live_predict",
        authority_state="certified",
        receipt_suffix="111111111111111111111111",
        total_ms=4000,
    )
    abstained = normalize_and_arbitrate_receipts(
        [_candidate("c1", left), _candidate("c2", right), _candidate("c3", third)],
        decided_at=_ARB_DECIDED_AT,
        producer_heads=_heads(),
    )
    rows.append(
        {
            "case": "three_close_alternatives_abstain",
            "passed": bool(
                abstained["oracle_decision"]["outcome"] == "abstain"
                and abstained["oracle_decision"]["selected_candidate_ids"] == []
            ),
        }
    )

    # 4. Main selecting a stale cheap draft over the strong winner is refused as
    #    silent weakening.
    strong = _receipt(
        access_mode="mode_a_package_read",
        authority_state="certified",
        receipt_suffix="333333333333333333333333",
        total_ms=8000,
        completed_at="2026-07-19T00:00:05Z",
    )
    weak_cheap = _receipt(
        access_mode="mode_b_live_predict",
        authority_state="draft",
        receipt_suffix="444444444444444444444444",
        total_ms=500,
        completed_at="2026-07-19T11:59:00Z",
    )
    stale = _receipt(
        access_mode="mode_b_live_predict",
        authority_state="certified",
        receipt_suffix="555555555555555555555555",
        completed_at="2026-07-01T00:00:00Z",
    )
    weak_candidates = [
        _candidate("strong", strong, preservation_risk=0.2),
        _candidate("weak-cheap", weak_cheap, preservation_risk=0.01),
        _candidate("stale", stale, preservation_risk=0.1),
    ]
    weak_arb = normalize_and_arbitrate_receipts(
        weak_candidates, decided_at=_ARB_DECIDED_AT, producer_heads=_heads()
    )
    bad_main = _main_decision(weak_arb, outcome="choose", selected=["weak-cheap"])
    weak_evidence = build_receipt_arbitration_conformance_evidence(
        weak_candidates, bad_main, decided_at=_ARB_DECIDED_AT, producer_heads=_heads()
    )
    rows.append(
        {
            "case": "main_silent_weakening_refused",
            "passed": bool(
                weak_arb["oracle_decision"]["selected_candidate_ids"] == ["strong"]
                and weak_evidence["status"] == "rejected"
                and "main_decision_disagrees" in (weak_evidence.get("rejection_reasons") or [])
                and "pass_requirement_weakened" in (weak_evidence.get("rejection_reasons") or [])
                and validate_receipt_arbitration_conformance_evidence(weak_evidence) == ()
            ),
        }
    )

    # 5. High preservation risk + insufficient authority floor abstains.
    risky = _receipt(
        access_mode="mode_b_live_predict",
        authority_state="draft",
        receipt_suffix="888888888888888888888888",
    )
    risky_arb = normalize_and_arbitrate_receipts(
        [_candidate("risky", risky, preservation_risk=0.9)],
        decided_at=_ARB_DECIDED_AT,
        producer_heads=_heads(required_authority_floor="certified", max_preservation_risk=0.5),
    )
    risky_row = risky_arb["evaluated"][0]
    rows.append(
        {
            "case": "high_risk_and_authority_floor_abstain",
            "passed": bool(
                risky_arb["oracle_decision"]["outcome"] == "abstain"
                and "authority_insufficient" in risky_row["ineligibility_reasons"]
                and "preservation_risk_exceeds_budget" in risky_row["ineligibility_reasons"]
            ),
        }
    )

    return {
        "check": "isolated_receipt_arbitration_dod_matrix",
        "passed": all(row["passed"] for row in rows),
        "cases": rows,
    }


# ---------------------------------------------------------------------------
# MF-P6-11.08 receipt-last recovery DoD fixtures (mirrors the passing test suite).
# ---------------------------------------------------------------------------

_REC_DECIDED_AT = "2026-07-19T12:01:00Z"


def _rec_snapshot() -> dict[str, Any]:
    body = {
        "health": {"status": "ok", "health_sha256": "a" * 64},
        "capability": {"capability_sha256": "b" * 64},
        "adopted_release": {"release_sha256": "c" * 64},
        "revocation": {"revocation_head_sha256": "d" * 64, "fresh": True},
        "service_openapi": {"service_sha256": "e" * 64},
        "node_pack": {
            "node_pack_sha256": "f" * 64,
            "closed_manifest": True,
            "stale_unmanifested_files": False,
        },
        "policy": {"policy_sha256": "1" * 64},
        "route": {"route_sha256": "2" * 64},
        "gpu_lease": {"lease_sha256": "3" * 64},
    }
    body["snapshot_sha256"] = canonical_document_sha256(
        body, excluded_top_level_fields=("snapshot_sha256",)
    )
    return body


def _rec_lease(*, state: str = "held", cleanup: bool = False) -> dict[str, Any]:
    return {
        "state": state,
        "token": "lease-token-test" if state == "held" else None,
        "request_id": "mfareq_recovery_00000001",
        "device_id": "cuda:0",
        "cleanup_deleted_foreign_token": cleanup,
    }


def _rec_cache() -> dict[str, Any]:
    return {
        "request_id": "mfareq_recovery_00000001",
        "receipt_sha256": "11" * 32,
        "artifact_sha256": "22" * 32,
        "release_sha256": "c" * 64,
        "capability_sha256": "b" * 64,
        "revocation_head_sha256": "d" * 64,
        "node_pack_sha256": "f" * 64,
        "authority_sha256": "33" * 32,
        "captured_at": "2026-07-19T12:00:00Z",
        "decided_at": "2026-07-19T12:01:00Z",
        "tombstoned": False,
        "main_tombstone_evidence": {},
    }


def _rec_complete_transaction() -> dict[str, Any]:
    return {
        "request_id": "mfareq_recovery_00000001",
        "current_phase": "cache_published",
        "completed_phases": [
            "reservation",
            "admission",
            "lease_acquired",
            "submitted",
            "provider_result",
            "artifacts_staged",
            "artifacts_published",
            "receipt_signed",
            "receipt_written",
            "receipt_committed_event",
            "checkpoint_advanced",
            "cache_published",
        ],
        "submission_state": "reconciled",
        "outcome_unknown": False,
        "retry_requested": False,
        "duplicate_submission_attempted": False,
        "orphan_promotion_attempted": False,
        "authority_granted": True,
        "authority_granted_without_checkpoint": False,
        "commit_claimed": True,
        "decided_at": "2026-07-19T12:01:00Z",
        "artifacts": [{"artifact_sha256": "22" * 32}],
        "receipt": {
            "receipt_sha256": "11" * 32,
            "artifact_sha256s": ["22" * 32],
            "resolved": True,
        },
    }


def _rec_healthy_observation() -> dict[str, Any]:
    snapshot = _rec_snapshot()
    return {
        "request_id": "mfareq_recovery_00000001",
        "transaction": _rec_complete_transaction(),
        "reconciliation": {},
        "decision_snapshot": snapshot,
        "current_context": {
            "capability": snapshot["capability"],
            "revocation": snapshot["revocation"],
            "adopted_release": snapshot["adopted_release"],
            "service_openapi": snapshot["service_openapi"],
            "node_pack": snapshot["node_pack"],
        },
        "cache": _rec_cache(),
        "gpu_lease": _rec_lease(state="held"),
        "rollback": {},
        "journal_entries": [],
        "checkpoints": [],
    }


_KILL_BOUNDARIES = (
    "reservation",
    "admission",
    "lease_acquired",
    "submitted_known",
    "submitted_unknown",
    "provider_result",
    "artifacts_staged",
    "artifacts_published",
    "receipt_signed",
    "receipt_written",
    "receipt_committed_event",
    "checkpoint_advanced",
    "cache_published",
    "install_switch",
    "rollback",
)


def run_recovery_dod_matrix() -> dict[str, Any]:
    """MF-P6-11.08 receipt-last recovery / kill-boundary DoD over real machinery."""
    rows: list[dict[str, Any]] = []

    # 1. Clean full-chain receipt-last commit is ready and validates.
    healthy = build_recovery_evidence(_rec_healthy_observation(), decided_at=_REC_DECIDED_AT)
    rows.append(
        {
            "case": "receipt_last_full_chain_commit_ready",
            "passed": bool(
                healthy["status"] == "accepted"
                and healthy["transaction"]["receipt_last_order_ok"] is True
                and healthy["transaction"]["commit_complete"] is True
                and healthy["transaction"]["commit_ready"] is True
                and healthy["integrity"]["no_duplicate_execution"] is True
                and healthy["integrity"]["no_orphan_promotion"] is True
                and healthy["integrity"]["no_authority_drift"] is True
                and validate_recovery_evidence(healthy) == ()
            ),
        }
    )

    # 2. Kill at every durable boundary recovers fail-closed without drift.
    kill_results: list[dict[str, Any]] = []
    for boundary in _KILL_BOUNDARIES:
        ev = simulate_kill_at_boundary(
            kill_boundary=boundary,
            request_id="mfareq_recovery_kill_0001",
            decided_at="2026-07-19T12:05:00Z",
            recovered_cleanly=True,
        )
        ok = (
            ev["status"] == "accepted"
            and ev["kill_boundary"] == boundary
            and ev["integrity"]["no_duplicate_execution"] is True
            and ev["integrity"]["no_orphan_promotion"] is True
            and ev["integrity"]["no_authority_drift"] is True
            and ev["integrity"]["kill_boundary_fail_closed"] is True
            and ev["transaction"]["commit_ready"] is False
            and validate_recovery_evidence(ev) == ()
        )
        if boundary == "submitted_unknown":
            ok = ok and (
                ev["reconciliation"]["required"] is True
                and ev["reconciliation"]["resubmission_authorized"] is True
                and ev["reconciliation"]["outcome"] == "not_found"
            )
        if boundary == "rollback":
            ok = ok and ev["integrity"]["rollback_clean"] is True
        kill_results.append({"boundary": boundary, "passed": bool(ok)})
    rows.append(
        {
            "case": "kill_at_every_durable_boundary_fail_closed",
            "passed": all(row["passed"] for row in kill_results),
            "boundaries": kill_results,
        }
    )

    # 3. Receipt-before-artifacts ordering violation is rejected.
    obs = _rec_healthy_observation()
    obs["transaction"]["completed_phases"] = [
        "reservation",
        "admission",
        "lease_acquired",
        "submitted",
        "provider_result",
        "artifacts_staged",
        "receipt_signed",
        "receipt_written",
        "receipt_committed_event",
        "checkpoint_advanced",
    ]
    obs["transaction"]["current_phase"] = "checkpoint_advanced"
    before_ev = build_recovery_evidence(obs, decided_at=_REC_DECIDED_AT)
    rows.append(
        {
            "case": "receipt_before_artifacts_rejected",
            "passed": bool(
                before_ev["status"] == "rejected"
                and "receipt_before_artifacts" in before_ev["rejection_reasons"]
                and before_ev["transaction"]["commit_ready"] is False
            ),
        }
    )

    # 4. Unresolved receipt digest fails closed.
    obs = _rec_healthy_observation()
    obs["transaction"]["receipt"] = {
        "receipt_sha256": "deadbeef",
        "resolved": False,
        "artifact_sha256s": [],
    }
    unresolved_ev = build_recovery_evidence(obs, decided_at=_REC_DECIDED_AT)
    rows.append(
        {
            "case": "unresolved_receipt_digest_fails_closed",
            "passed": bool(
                unresolved_ev["status"] == "rejected"
                and "unresolved_receipt_digest" in unresolved_ev["rejection_reasons"]
            ),
        }
    )

    # 5. Orphan promotion + authority drift is rejected.
    obs = _rec_healthy_observation()
    obs["transaction"]["completed_phases"] = [
        "reservation",
        "admission",
        "lease_acquired",
        "submitted",
        "provider_result",
        "artifacts_staged",
        "artifacts_published",
    ]
    obs["transaction"]["current_phase"] = "artifacts_published"
    obs["transaction"]["commit_claimed"] = False
    obs["transaction"]["authority_granted"] = True
    obs["transaction"]["authority_granted_without_checkpoint"] = True
    obs["transaction"]["orphan_promotion_attempted"] = True
    obs["cache"] = {}
    orphan_ev = build_recovery_evidence(obs, decided_at=_REC_DECIDED_AT)
    rows.append(
        {
            "case": "orphan_promotion_and_authority_drift_rejected",
            "passed": bool(
                orphan_ev["status"] == "rejected"
                and "orphan_artifact_promotion" in orphan_ev["rejection_reasons"]
                and "authority_drift" in orphan_ev["rejection_reasons"]
            ),
        }
    )

    # 6. Foreign GPU-lease cleanup is refused (never delete a replacement owner).
    obs = _rec_healthy_observation()
    obs["gpu_lease"] = _rec_lease(state="held", cleanup=True)
    lease_ev = build_recovery_evidence(obs, decided_at=_REC_DECIDED_AT)
    rows.append(
        {
            "case": "foreign_lease_cleanup_refused",
            "passed": bool(
                lease_ev["status"] == "rejected"
                and "gpu_lease_unowned_cleanup" in lease_ev["rejection_reasons"]
                and lease_ev["gpu_lease"]["foreign_token_cleanup_refused"] is False
            ),
        }
    )

    # 7. Duplicate resubmit after found-running (no not-found evidence) is rejected.
    obs = _rec_healthy_observation()
    obs["transaction"] = {
        "request_id": "mfareq_recovery_00000001",
        "current_phase": "submitted",
        "completed_phases": ["reservation", "admission", "lease_acquired", "submitted"],
        "submission_state": "outcome_unknown",
        "outcome_unknown": True,
        "retry_requested": True,
        "duplicate_submission_attempted": True,
        "orphan_promotion_attempted": False,
        "authority_granted": False,
        "commit_claimed": False,
        "receipt": {},
        "artifacts": [],
    }
    obs["cache"] = {}
    obs["reconciliation"] = {
        "outcome": "found_running",
        "remote_status": "running",
        "remote_execution_id": "remote-1",
        "remote_execution_sha256": "a" * 64,
        "remote_result_sha256": None,
        "not_found_evidence_sha256": None,
        "checked_at": "2026-07-19T12:01:00Z",
        "resubmission_authorized": False,
    }
    dup_ev = build_recovery_evidence(obs, decided_at=_REC_DECIDED_AT)
    rows.append(
        {
            "case": "duplicate_resubmit_after_found_running_rejected",
            "passed": bool(
                dup_ev["status"] == "rejected"
                and "duplicate_execution" in dup_ev["rejection_reasons"]
                and "resubmit_without_not_found" in dup_ev["rejection_reasons"]
            ),
        }
    )

    return {
        "check": "isolated_recovery_dod_matrix",
        "passed": all(row["passed"] for row in rows),
        "cases": rows,
    }


def _check(name: str, passed: bool, **extra: Any) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), **extra}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    runners: tuple[tuple[Callable[[], dict[str, Any]], str], ...] = (
        (run_receipt_arbitration_dod_matrix, "isolated_receipt_arbitration_dod_matrix"),
        (run_recovery_dod_matrix, "isolated_recovery_dod_matrix"),
    )
    for runner, name in runners:
        try:
            checks.append(runner())
        except Exception as exc:  # pragma: no cover - honest failure capture
            checks.append(_check(name, False, error=repr(exc)))

    evidence: dict[str, Any] = {
        "artifact_type": "isolated_main_consumer_dod2_run",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authority_kind": "isolated_main_consumer",
        "is_real_comfyui_main": False,
        "producer_git_commit": _git_head(),
        "decided_at": DECIDED_AT,
        "checks": checks,
        "summary": {check["check"]: check["passed"] for check in checks},
        "claim_boundary": {
            "isolated_consumer_is_not_fixture_authority": True,
            "isolated_consumer_is_not_real_comfyui_main": True,
            "main_adoption_complete": False,
            "establishes_production_qualification": False,
            "advances": [
                "MF-P6-11.04 (receipt arbitration DoD: wrapper-certified Mode A dominance, "
                "close-alternatives branch, three-way abstain, Main silent-weakening refusal, "
                "high-risk/authority-floor abstain — real oracle + conformance validator)",
                "MF-P6-11.08 (receipt-last recovery DoD: full-chain commit-ready, kill at all 15 "
                "durable boundaries fail-closed, receipt-before-artifacts / unresolved-digest / "
                "orphan-promotion+authority-drift / foreign-lease-cleanup / duplicate-resubmit "
                "refusals — real recovery machinery + validator)",
            ],
            "hard_blockers_still_open": list(HARD_BLOCKERS_REQUIRING_REAL_MAIN),
            "advances_are_producer_isolated_only": True,
            "does_not_close_any_hard_blocker": True,
            "next_agent_step": (
                "Real receipts require a dedicated Comfy_UI_Main-side integration on an "
                "isolated clean maskfactory branch that consumes the producer adapter package "
                "and emits Main-signed adoption/qualification/adapter-execution/result-history "
                "artifacts pinned back here. Comfy_UI_Main is a dirty Wave64 tree and untouched."
            ),
        },
    }
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence["summary"], sort_keys=True))
    return 0 if all(check["passed"] for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
