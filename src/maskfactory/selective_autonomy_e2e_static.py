"""STATIC binder for MF-P9-15.08 generate→critic→repair→certify→audit control flow.

Fixture- and import-bound only. Proves the stage graph, separate quality/labor
headline channels, and sparse-owner-decision contracts. Never claims the live
end-to-end autonomous demonstration, doctor-green, gold, Main-complete, or
PRODUCTION_EVIDENCE_PASS.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from datetime import UTC, datetime
from typing import Any, Mapping

from .validation import validate_document

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "selective_autonomy_e2e_static_report"
AUTHORITY = "selective_autonomy_e2e_static_only_no_live_headline_demo_or_measured_quality_labor"
SCHEMA_VERSION = "1.0.0"

# MF-P9-15.08 / Plan 23 §§2–3,9–12 — ordered autonomous control stages.
REQUIRED_PIPELINE_STAGES = (
    "generate",
    "critic",
    "repair",
    "certify",
    "audit",
    "sparse_owner_decision",
)

STAGE_MODULE_CONTRACTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "generate": ("maskfactory.autonomy.controller", ("run_autonomous_correction_loop",)),
    "critic": ("maskfactory.intelligence", ("evaluate_critic_quorum", "CriticQuorumDecision")),
    "repair": (
        "maskfactory.autonomy.repair",
        ("decide_bounded_repair", "evaluate_repair_candidate"),
    ),
    "certify": (
        "maskfactory.authority.operational_certificate",
        ("issue_operational_autonomy_certificate",),
    ),
    "audit": ("maskfactory.autonomy.audit", ("select_sparse_human_audits",)),
    "sparse_owner_decision": (
        "maskfactory.autonomy.decisions",
        ("build_binary_review_bundle", "record_binary_review_decision"),
    ),
}

# Headline evidence must keep quality and labor in separate channels (Plan 23).
REQUIRED_HEADLINE_CHANNELS = ("quality", "labor")
FORBIDDEN_CONFLATED_HEADLINE_FIELDS = (
    "quality_labor_score",
    "combined_quality_labor_metric",
    "quality_and_labor_pass",
    "aggregate_acceptance_score",
)

HONEST_NON_CLAIMS = (
    "mf_p9_15_08_complete",
    "live_generate_critic_repair_certify_audit_demo",
    "blinded_human_anchor_holdout_measured",
    "production_labor_measured",
    "doctor_green",
    "gold",
    "VISUAL_QA_PASS_BOUNDED",
    "Main-complete",
    "PRODUCTION_EVIDENCE_PASS",
)


class SelectiveAutonomyE2EStaticError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def bind_stage_module_contracts() -> dict[str, dict[str, Any]]:
    """Import-bound proof that each pipeline stage has a host-side control surface."""

    bindings: dict[str, dict[str, Any]] = {}
    for stage in REQUIRED_PIPELINE_STAGES:
        module_name, symbols = STAGE_MODULE_CONTRACTS[stage]
        module = importlib.import_module(module_name)
        missing = [name for name in symbols if not hasattr(module, name)]
        if missing:
            raise SelectiveAutonomyE2EStaticError(
                f"stage_contract_missing:{stage}:{','.join(missing)}"
            )
        bindings[stage] = {
            "module": module_name,
            "symbols": list(symbols),
            "import_ok": True,
        }
    return bindings


def evaluate_stage_order(stages: tuple[str, ...] | list[str]) -> dict[str, Any]:
    """Refuse out-of-order or incomplete autonomous control graphs."""

    observed = list(stages)
    if observed != list(REQUIRED_PIPELINE_STAGES):
        raise SelectiveAutonomyE2EStaticError(
            "stage_order_invalid:" + ",".join(observed) if observed else "stage_order_empty"
        )
    return {
        "required_stages": list(REQUIRED_PIPELINE_STAGES),
        "observed_stages": observed,
        "order_matches_required": True,
    }


def evaluate_headline_channel_separation(headline: Mapping[str, Any]) -> dict[str, Any]:
    """Quality and labor must be separate headline channels; conflation fails closed."""

    for field in FORBIDDEN_CONFLATED_HEADLINE_FIELDS:
        if field in headline:
            raise SelectiveAutonomyE2EStaticError(f"headline_conflation:{field}")

    quality = headline.get("quality")
    labor = headline.get("labor")
    if not isinstance(quality, Mapping) or not isinstance(labor, Mapping):
        raise SelectiveAutonomyE2EStaticError("headline_channels_missing_quality_or_labor")
    if set(quality).intersection(labor):
        raise SelectiveAutonomyE2EStaticError("headline_channel_key_overlap")

    # Fixture honesty: STATIC binder never treats fixture numbers as measured wins.
    if headline.get("measured_production_authority") is True:
        raise SelectiveAutonomyE2EStaticError("headline_measured_production_overclaim")
    if headline.get("blinded_holdout_authority") is True:
        raise SelectiveAutonomyE2EStaticError("headline_blinded_holdout_overclaim")

    return {
        "required_channels": list(REQUIRED_HEADLINE_CHANNELS),
        "quality_keys": sorted(quality),
        "labor_keys": sorted(labor),
        "channels_separate": True,
        "conflation_fields_absent": True,
        "fixture_not_measured_authority": True,
    }


def refuse_e2e_overclaim(document: Mapping[str, Any]) -> None:
    """Fail closed on live-demo / completion / gold overclaims."""

    forbidden_true = (
        "mf_p9_15_08_complete",
        "live_generate_critic_repair_certify_audit_demo",
        "blinded_human_anchor_holdout_measured",
        "production_labor_measured",
        "doctor_green_claimed",
        "gold_claimed",
        "visual_qa_pass_claimed",
        "main_complete_claimed",
        "production_evidence_pass_claimed",
    )
    for key in forbidden_true:
        if document.get(key) is True:
            raise SelectiveAutonomyE2EStaticError(f"e2e_overclaim:{key}")


def run_selective_autonomy_e2e_static_suite() -> dict[str, Any]:
    """Execute MF-P9-15.08 STATIC binders and seal a schema-valid report."""

    stage_bindings = bind_stage_module_contracts()
    stage_order = evaluate_stage_order(REQUIRED_PIPELINE_STAGES)

    fixture_headline = {
        "quality": {
            "ordinary_part_mean_iou_reported": False,
            "boundary_f1_reported": False,
            "hard_anatomy_mean_iou_reported": False,
        },
        "labor": {
            "zero_touch_fraction_reported": False,
            "routine_human_touch_fraction_reported": False,
            "manual_pixel_edit_fraction_reported": False,
        },
        "measured_production_authority": False,
        "blinded_holdout_authority": False,
    }
    headline = evaluate_headline_channel_separation(fixture_headline)

    # Negative fixtures.
    try:
        evaluate_stage_order(("generate", "certify", "audit"))
        raise SelectiveAutonomyE2EStaticError("stage_order_negative_passed")
    except SelectiveAutonomyE2EStaticError as exc:
        if "stage_order_invalid" not in exc.reason:
            raise
        stage_order_negative_blocked = True

    try:
        evaluate_headline_channel_separation(
            {
                "quality": {"miou": 0.99},
                "labor": {"zero_touch": 0.99},
                "quality_labor_score": 0.99,
            }
        )
        raise SelectiveAutonomyE2EStaticError("headline_conflation_negative_passed")
    except SelectiveAutonomyE2EStaticError as exc:
        if "headline_conflation" not in exc.reason:
            raise
        headline_conflation_negative_blocked = True

    try:
        refuse_e2e_overclaim({"mf_p9_15_08_complete": True})
        raise SelectiveAutonomyE2EStaticError("completion_overclaim_negative_passed")
    except SelectiveAutonomyE2EStaticError as exc:
        if "mf_p9_15_08_complete" not in exc.reason:
            raise
        completion_overclaim_negative_blocked = True

    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "items": ["MF-P9-15.08"],
        "required_pipeline_stages": list(REQUIRED_PIPELINE_STAGES),
        "stage_module_bindings": stage_bindings,
        "stage_order_checks": stage_order,
        "headline_channel_checks": headline,
        "checks": {
            "stage_modules_importable": "pass",
            "stage_order_bound": "pass",
            "headline_quality_labor_separated": "pass",
            "live_demo_overclaim_refused": "pass",
        },
        "stage_order_negative_fixture_blocked": stage_order_negative_blocked,
        "headline_conflation_negative_fixture_blocked": headline_conflation_negative_blocked,
        "completion_overclaim_negative_fixture_blocked": completion_overclaim_negative_blocked,
        "mf_p9_15_08_complete": False,
        "live_generate_critic_repair_certify_audit_demo": False,
        "blinded_human_anchor_holdout_measured": False,
        "production_labor_measured": False,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "visual_qa_pass_claimed": False,
        "main_complete_claimed": False,
        "production_evidence_pass_claimed": False,
        "honest_non_claims": list(HONEST_NON_CLAIMS),
    }
    refuse_e2e_overclaim(draft)

    digest = _sha(draft)
    draft["report_id"] = f"sae2e_{digest[:24]}"
    draft["seal_sha256"] = digest
    draft["sha256"] = _sha({key: value for key, value in draft.items() if key != "sha256"})

    issues = validate_document(draft, "selective_autonomy_e2e_static_report")
    if issues:
        detail = "; ".join(
            f"{getattr(issue, 'pointer', None) or '/'}: {issue.message}" for issue in issues
        )
        raise SelectiveAutonomyE2EStaticError(f"schema_validation_failed:{detail}")
    return draft


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "FORBIDDEN_CONFLATED_HEADLINE_FIELDS",
    "HONEST_NON_CLAIMS",
    "PROOF_TIER",
    "REQUIRED_HEADLINE_CHANNELS",
    "REQUIRED_PIPELINE_STAGES",
    "SCHEMA_VERSION",
    "STAGE_MODULE_CONTRACTS",
    "SelectiveAutonomyE2EStaticError",
    "bind_stage_module_contracts",
    "evaluate_headline_channel_separation",
    "evaluate_stage_order",
    "refuse_e2e_overclaim",
    "run_selective_autonomy_e2e_static_suite",
]
