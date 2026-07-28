"""STATIC binders for budget circuit-breaker, shadow teachers, incremental-value audit.

Code/fixture only. Never executes paid cloud calls. Never claims MF-P4-10.08/09
complete, human-anchor ≥200 corpus authority, doctor-green, gold, or
PRODUCTION_EVIDENCE_PASS.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from ..validation import validate_document
from .cloud_budget import CloudBudgetError, DailyBudgetLedger
from .cloud_teacher import load_cloud_teacher_config

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "cloud_teacher_static_report"
AUTHORITY = "cloud_teacher_static_only_no_paid_calls_no_mf_p4_10_08_09_human_anchor_authority"
SCHEMA_VERSION = "1.0.0"

REQUIRED_COVERAGE_THEMES = (
    "serious_anatomy_swap",
    "missing_part",
    "neighbor_person_contamination",
    "clothing_skin_boundary",
    "hair",
    "hands_fingers",
    "feet_toes",
    "occlusion",
    "multi_person_contact",
    "good_mask",
)

MINIMUM_INCREMENTAL_CASES = 200

SHADOW_AUTHORITY = "shadow_advisory_human_approval_required"

HONEST_NON_CLAIMS = (
    "mf_p4_10_08_complete",
    "mf_p4_10_09_complete",
    "human_anchor_ge_200_corpus",
    "paid_cloud_calls_executed",
    "doctor_green",
    "gold",
    "PRODUCTION_EVIDENCE_PASS",
    "quick_pass_authority",
    "blocker_clearance_authority",
)


class CloudTeacherStaticError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def refuse_mf_p4_10_08_09_claim(document: Mapping[str, Any]) -> None:
    """Fail closed if a binder overclaims the Kevin-gated incremental-value items."""
    for key in (
        "mf_p4_10_08_complete",
        "mf_p4_10_09_complete",
        "human_anchor_ge_200_corpus",
        "paid_cloud_calls_executed",
    ):
        if document.get(key) is True:
            raise CloudTeacherStaticError(f"overclaim_mf_p4_10_08_09:{key}")


def prove_budget_circuit_breaker(
    *,
    ledger_path: Path,
    hard_limit_usd: Decimal | str | float = "15.00",
    reservation_usd: Decimal | str | float = "1.00",
) -> dict[str, Any]:
    """Prove hash-chained hard-cap refusal without any paid provider dispatch."""
    ledger = DailyBudgetLedger(
        ledger_path,
        timezone_name="America/Chicago",
        hard_limit_usd=hard_limit_usd,
    )
    hard = Decimal(str(hard_limit_usd)).quantize(Decimal("0.000001"))
    reserve = Decimal(str(reservation_usd)).quantize(Decimal("0.000001"))
    if reserve <= 0 or hard <= 0:
        raise CloudTeacherStaticError("budget_limits_must_be_positive")

    # Fill the day to one reservation short of the hard cap.
    filled = 0
    while True:
        snap = ledger.snapshot()
        if snap.available_usd < reserve:
            break
        request_id = f"static_fill_{filled:04d}"
        ledger.reserve(
            request_id=request_id,
            provider="gemini",
            model="static-fixture",
            image_id=f"img_fill_{filled:04d}",
            label="hair",
            maximum_cost_usd=reserve,
        )
        ledger.commit(
            request_id,
            actual_cost_usd=reserve,
            input_tokens=1,
            output_tokens=1,
        )
        filled += 1
        if filled > 100:
            raise CloudTeacherStaticError("budget_fill_did_not_approach_cap")

    # Next reservation must trip the circuit breaker.
    tripped = False
    try:
        ledger.reserve(
            request_id="static_over_cap",
            provider="openai",
            model="static-fixture",
            image_id="img_over_cap",
            label="hair",
            maximum_cost_usd=reserve,
        )
    except CloudBudgetError as exc:
        tripped = "hard limit would be exceeded" in str(exc)
        if not tripped:
            raise CloudTeacherStaticError(f"unexpected_budget_error:{exc}") from exc
    if not tripped:
        raise CloudTeacherStaticError("circuit_breaker_did_not_trip")

    # Duplicate request IDs and automatic retry of the same ID are refused.
    ledger2_path = ledger_path.with_name(ledger_path.stem + "_retry.jsonl")
    ledger2 = DailyBudgetLedger(
        ledger2_path,
        timezone_name="America/Chicago",
        hard_limit_usd=hard_limit_usd,
    )
    ledger2.reserve(
        request_id="static_once",
        provider="anthropic",
        model="static-fixture",
        image_id="img_once",
        label="hair",
        maximum_cost_usd=reserve,
    )
    duplicate_refused = False
    try:
        ledger2.reserve(
            request_id="static_once",
            provider="anthropic",
            model="static-fixture",
            image_id="img_once",
            label="hair",
            maximum_cost_usd=reserve,
        )
    except CloudBudgetError as exc:
        duplicate_refused = "already exists" in str(exc)
    if not duplicate_refused:
        raise CloudTeacherStaticError("automatic_paid_retry_not_refused")

    final = ledger.snapshot()
    return {
        "hard_limit_usd": str(hard),
        "reservation_usd": str(reserve),
        "filled_reservations": filled,
        "committed_usd": str(final.committed_usd),
        "available_usd": str(final.available_usd),
        "circuit_breaker_tripped": True,
        "duplicate_request_refused": True,
        "paid_cloud_calls_executed": False,
        "hash_chained_ledger": True,
    }


def build_shadow_teacher_judgment(
    *,
    provider: str,
    model: str,
    verdict: str,
    confidence: float,
    defects: list[str] | tuple[str, ...],
    evidence: str = "static fixture observation",
) -> dict[str, Any]:
    """Build a schema-valid shadow teacher judgment with no gold authority."""
    if provider not in {"gemini", "openai", "anthropic"}:
        raise CloudTeacherStaticError(f"unknown_shadow_provider:{provider}")
    if verdict not in {"pass", "fail", "uncertain"}:
        raise CloudTeacherStaticError(f"invalid_shadow_verdict:{verdict}")
    if not 0 <= float(confidence) <= 1:
        raise CloudTeacherStaticError("invalid_shadow_confidence")
    if verdict == "pass" and defects:
        raise CloudTeacherStaticError("shadow_pass_cannot_include_defects")
    document = {
        "schema_version": SCHEMA_VERSION,
        "authority": SHADOW_AUTHORITY,
        "provider": provider,
        "model": model,
        "verdict": verdict,
        "confidence": float(confidence),
        "defects": list(defects),
        "observations": {
            "full_context": "static full context",
            "source_crop": "static source crop",
            "mask": "static mask",
            "overlay": "static overlay",
            "contour": "static contour",
            "neighbor_overlap": "static neighbor overlap",
        },
        "evidence": evidence,
        "correction": {
            "tool": "none",
            "polygon": [],
            "positive_points": [],
            "negative_points": [],
            "rationale": "static shadow fixture",
        },
        "may_approve_gold": False,
        "may_clear_blocks": False,
        "may_write_authoritative_masks": False,
        "may_create_quick_pass": False,
        "paid_cloud_calls_executed": False,
    }
    issues = validate_document(document, "shadow_teacher_judgment")
    if issues:
        raise CloudTeacherStaticError(
            "shadow_schema_validation_failed: "
            + "; ".join(f"{issue.pointer or '/'} {issue.message}" for issue in issues)
        )
    return document


def assess_shadow_consensus_authority(
    *,
    judgments: list[Mapping[str, Any]],
    deterministic_veto: bool,
) -> dict[str, Any]:
    """Unanimous cloud consensus remains correlated shadow evidence, not truth."""
    if not judgments:
        raise CloudTeacherStaticError("shadow_consensus_requires_judgments")
    for judgment in judgments:
        if judgment.get("authority") != SHADOW_AUTHORITY:
            raise CloudTeacherStaticError("shadow_authority_missing")
        for key in (
            "may_approve_gold",
            "may_clear_blocks",
            "may_write_authoritative_masks",
            "may_create_quick_pass",
        ):
            if judgment.get(key) is not False:
                raise CloudTeacherStaticError(f"shadow_authority_overclaim:{key}")
    verdicts = {str(item["verdict"]) for item in judgments}
    unanimous = len(verdicts) == 1
    # Deterministic non-pass always wins; unanimous cloud cannot clear it.
    if deterministic_veto:
        destination = "residual_human_queue"
        reason = "deterministic_veto_overrides_shadow_consensus"
        may_quick_pass = False
        may_clear_blocks = False
    elif unanimous and "fail" in verdicts:
        destination = "residual_human_queue"
        reason = "unanimous_shadow_fail_still_requires_human"
        may_quick_pass = False
        may_clear_blocks = False
    elif unanimous and "pass" in verdicts:
        destination = "shadow_advisory_only"
        reason = "unanimous_shadow_pass_is_correlated_evidence_not_truth"
        may_quick_pass = False
        may_clear_blocks = False
    else:
        destination = "residual_human_queue"
        reason = "shadow_disagreement_routes_residual"
        may_quick_pass = False
        may_clear_blocks = False
    return {
        "schema_version": SCHEMA_VERSION,
        "unanimous": unanimous,
        "verdicts": sorted(verdicts),
        "deterministic_veto": bool(deterministic_veto),
        "destination": destination,
        "reason": reason,
        "may_approve_gold": False,
        "may_clear_blocks": may_clear_blocks,
        "may_create_quick_pass": may_quick_pass,
        "authority": SHADOW_AUTHORITY,
        "proof_tier": PROOF_TIER,
    }


def audit_incremental_value_corpus(
    corpus: Mapping[str, Any],
    *,
    train_image_ids: frozenset[str] | set[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Structural audit for incremental-value corpora (no paid calls, no auto-complete).

    Passing structural checks on a synthetic fixture never completes MF-P4-10.08/09.
    Human-anchor truth and Kevin-authorized live evaluation remain required.
    """
    required_top = {
        "schema_version",
        "frozen",
        "provider",
        "model",
        "human_anchor_truth",
        "cases",
    }
    if not isinstance(corpus, Mapping) or set(corpus) != required_top:
        raise CloudTeacherStaticError(f"corpus_requires_exactly:{sorted(required_top)}")
    if corpus["schema_version"] != SCHEMA_VERSION:
        raise CloudTeacherStaticError("corpus_schema_version_invalid")
    if corpus["frozen"] is not True:
        raise CloudTeacherStaticError("corpus_must_be_frozen")
    if corpus["provider"] not in {"gemini", "openai", "anthropic"}:
        raise CloudTeacherStaticError("corpus_provider_invalid")
    cases = corpus["cases"]
    if not isinstance(cases, list) or not cases:
        raise CloudTeacherStaticError("corpus_has_no_cases")

    case_ids: list[str] = []
    image_ids: list[str] = []
    themes: set[str] = set()
    natural_count = 0
    for index, case in enumerate(cases):
        required_case = {
            "case_id",
            "image_id",
            "label",
            "coverage_theme",
            "naturally_occurring",
            "severity",
            "human_verdict",
        }
        if not isinstance(case, Mapping) or set(case) != required_case:
            raise CloudTeacherStaticError(f"case_{index}_shape_invalid")
        case_id = str(case["case_id"]).strip()
        image_id = str(case["image_id"]).strip()
        theme = str(case["coverage_theme"]).strip()
        if not case_id or not image_id:
            raise CloudTeacherStaticError(f"case_{index}_identity_blank")
        if theme not in REQUIRED_COVERAGE_THEMES:
            raise CloudTeacherStaticError(f"unknown_coverage_theme:{theme}")
        if case["severity"] not in {"none", "minor", "serious"}:
            raise CloudTeacherStaticError(f"case_{index}_severity_invalid")
        if case["human_verdict"] not in {"pass", "fail"}:
            raise CloudTeacherStaticError(f"case_{index}_human_verdict_invalid")
        if (case["human_verdict"] == "pass") != (case["severity"] == "none"):
            raise CloudTeacherStaticError(f"case_{index}_verdict_severity_disagree")
        if case["naturally_occurring"] is not True:
            raise CloudTeacherStaticError(f"case_{index}_not_naturally_occurring")
        case_ids.append(case_id)
        image_ids.append(image_id)
        themes.add(theme)
        natural_count += 1

    failures: list[str] = []
    if len(set(case_ids)) != len(case_ids):
        failures.append("duplicate_case_id")
    if len(set(image_ids)) != len(image_ids):
        failures.append("image_disjoint_violation")
    leaked = sorted(set(image_ids) & set(train_image_ids))
    if leaked:
        failures.append(f"train_leakage:{','.join(leaked)}")
    missing_themes = sorted(set(REQUIRED_COVERAGE_THEMES) - themes)
    if missing_themes:
        failures.append("coverage_gap:" + ",".join(missing_themes))
    if len(cases) < MINIMUM_INCREMENTAL_CASES:
        failures.append(f"case_count_below_{MINIMUM_INCREMENTAL_CASES}:{len(cases)}")

    human_anchor = corpus["human_anchor_truth"] is True
    structural_pass = not failures
    # Honest gate: structural fixture pass is never MF-P4-10.08/09 completion.
    mf_08 = False
    mf_09 = False
    if human_anchor and structural_pass:
        # Still refuse completion in STATIC binder — live Kevin corpus/budget required.
        mf_08 = False
        mf_09 = False

    result = {
        "schema_version": SCHEMA_VERSION,
        "structural_pass": structural_pass,
        "case_count": len(cases),
        "unique_image_count": len(set(image_ids)),
        "naturally_occurring_count": natural_count,
        "coverage_themes_present": sorted(themes),
        "coverage_themes_required": list(REQUIRED_COVERAGE_THEMES),
        "failures": failures,
        "human_anchor_truth": human_anchor,
        "human_anchor_ge_200_corpus": False,
        "mf_p4_10_08_complete": mf_08,
        "mf_p4_10_09_complete": mf_09,
        "paid_cloud_calls_executed": False,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
    }
    refuse_mf_p4_10_08_09_claim(result)
    return result


def prove_config_shadow_budget_defaults(
    config_path: Path = Path("configs/cloud_teacher.yaml"),
) -> dict[str, Any]:
    """Prove config remains shadow-only with $14.50/$15/$1/max-3 without dispatch."""
    config = load_cloud_teacher_config(config_path)
    budget = config["budget"]
    if config["mode"] != "shadow_only":
        raise CloudTeacherStaticError("config_mode_not_shadow_only")
    if float(budget["operational_limit_usd"]) != 14.50:
        raise CloudTeacherStaticError("operational_limit_drift")
    if float(budget["hard_limit_usd"]) != 15.00:
        raise CloudTeacherStaticError("hard_limit_drift")
    for name, settings in config["providers"].items():
        if float(settings["maximum_reserved_cost_usd"]) != 1.00:
            raise CloudTeacherStaticError(f"reservation_drift:{name}")
    if int(budget["maximum_calls_per_image"]) != 3:
        raise CloudTeacherStaticError("max_calls_per_image_drift")
    gov = config["governance"]
    if any(
        gov[key] is not False
        for key in ("may_approve_gold", "may_clear_blocks", "may_write_authoritative_masks")
    ):
        raise CloudTeacherStaticError("governance_authority_drift")
    evaluation = config["evaluation"]
    if int(evaluation["minimum_cases"]) < MINIMUM_INCREMENTAL_CASES:
        raise CloudTeacherStaticError("evaluation_minimum_cases_below_200")
    if evaluation["promotion_grants_mask_authority"] is not False:
        raise CloudTeacherStaticError("evaluation_grants_mask_authority")
    return {
        "mode": config["mode"],
        "enabled": bool(config["enabled"]),
        "operational_limit_usd": float(budget["operational_limit_usd"]),
        "hard_limit_usd": float(budget["hard_limit_usd"]),
        "reservation_usd": 1.00,
        "maximum_calls_per_image": int(budget["maximum_calls_per_image"]),
        "minimum_incremental_cases": int(evaluation["minimum_cases"]),
        "may_approve_gold": False,
        "paid_cloud_calls_executed": False,
    }


def run_cloud_teacher_static_suite(tmp_ledger_dir: Path) -> dict[str, Any]:
    """Execute seeded STATIC proofs and return sealed binder report."""
    tmp_ledger_dir.mkdir(parents=True, exist_ok=True)
    budget_proof = prove_budget_circuit_breaker(
        ledger_path=tmp_ledger_dir / "budget_circuit.jsonl",
    )
    config_proof = prove_config_shadow_budget_defaults()

    judgments = [
        build_shadow_teacher_judgment(
            provider="gemini", model="static-fixture", verdict="pass", confidence=0.9, defects=[]
        ),
        build_shadow_teacher_judgment(
            provider="openai", model="static-fixture", verdict="pass", confidence=0.88, defects=[]
        ),
        build_shadow_teacher_judgment(
            provider="anthropic",
            model="static-fixture",
            verdict="pass",
            confidence=0.91,
            defects=[],
        ),
    ]
    consensus_veto = assess_shadow_consensus_authority(
        judgments=judgments,
        deterministic_veto=True,
    )
    if consensus_veto["destination"] != "residual_human_queue":
        raise CloudTeacherStaticError("unanimous_cloud_did_not_remain_residual_under_veto")

    # Under-sized fixture: audit must reject (<200) without claiming 10.08.
    small_cases = []
    for index, theme in enumerate(REQUIRED_COVERAGE_THEMES):
        severity = "none" if theme == "good_mask" else "serious"
        human = "pass" if theme == "good_mask" else "fail"
        small_cases.append(
            {
                "case_id": f"case_{index:03d}",
                "image_id": f"img_{index:012x}",
                "label": "hair" if theme == "hair" else "left_hand_base",
                "coverage_theme": theme,
                "naturally_occurring": True,
                "severity": severity,
                "human_verdict": human,
            }
        )
    small_audit = audit_incremental_value_corpus(
        {
            "schema_version": SCHEMA_VERSION,
            "frozen": True,
            "provider": "gemini",
            "model": "static-fixture",
            "human_anchor_truth": False,
            "cases": small_cases,
        }
    )
    if small_audit["structural_pass"] is not False:
        raise CloudTeacherStaticError("undersized_corpus_incorrectly_passed")
    if "case_count_below_200" not in "".join(small_audit["failures"]):
        raise CloudTeacherStaticError("undersized_corpus_missing_count_failure")

    # Leakage + duplicate rejection.
    leak_cases = list(small_cases)
    leak_cases[0] = {
        **leak_cases[0],
        "case_id": "case_dup_a",
        "image_id": "img_train_leak",
    }
    leak_cases.append(
        {
            **leak_cases[0],
            "case_id": "case_dup_b",
            "image_id": "img_train_leak",
        }
    )
    try:
        leak_audit = audit_incremental_value_corpus(
            {
                "schema_version": SCHEMA_VERSION,
                "frozen": True,
                "provider": "openai",
                "model": "static-fixture",
                "human_anchor_truth": False,
                "cases": leak_cases,
            },
            train_image_ids={"img_train_leak"},
        )
    except CloudTeacherStaticError:
        raise
    if "image_disjoint_violation" not in leak_audit["failures"]:
        raise CloudTeacherStaticError("duplicate_image_not_rejected")
    if not any(item.startswith("train_leakage:") for item in leak_audit["failures"]):
        raise CloudTeacherStaticError("train_leakage_not_rejected")

    # Coverage gap rejection.
    gap_cases = [case for case in small_cases if case["coverage_theme"] != "occlusion"]
    gap_audit = audit_incremental_value_corpus(
        {
            "schema_version": SCHEMA_VERSION,
            "frozen": True,
            "provider": "anthropic",
            "model": "static-fixture",
            "human_anchor_truth": False,
            "cases": gap_cases,
        }
    )
    if not any(item.startswith("coverage_gap:") for item in gap_audit["failures"]):
        raise CloudTeacherStaticError("coverage_gap_not_rejected")

    overclaim_refused = False
    try:
        refuse_mf_p4_10_08_09_claim({"mf_p4_10_08_complete": True})
    except CloudTeacherStaticError:
        overclaim_refused = True
    if not overclaim_refused:
        raise CloudTeacherStaticError("overclaim_not_refused")

    seeded = {
        "budget_circuit_breaker": True,
        "config_shadow_budget_defaults": True,
        "shadow_judgment_schema": True,
        "unanimous_cloud_deterministic_veto_residual": True,
        "undersized_corpus_rejected": True,
        "leakage_and_duplicate_rejected": True,
        "coverage_gap_rejected": True,
        "mf_p4_10_08_09_overclaim_refused": True,
    }
    return build_cloud_teacher_static_report(
        seeded_fixture_blocks=seeded,
        budget_proof=budget_proof,
        config_proof=config_proof,
        consensus_veto=consensus_veto,
        small_audit_failures=tuple(small_audit["failures"]),
    )


def build_cloud_teacher_static_report(
    *,
    seeded_fixture_blocks: Mapping[str, bool],
    budget_proof: Mapping[str, Any],
    config_proof: Mapping[str, Any],
    consensus_veto: Mapping[str, Any],
    small_audit_failures: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    """Seal STATIC binder for teacher/cloud host-side proofs."""
    required = {
        "budget_circuit_breaker",
        "config_shadow_budget_defaults",
        "shadow_judgment_schema",
        "unanimous_cloud_deterministic_veto_residual",
        "undersized_corpus_rejected",
        "leakage_and_duplicate_rejected",
        "coverage_gap_rejected",
        "mf_p4_10_08_09_overclaim_refused",
    }
    if set(seeded_fixture_blocks) != required:
        raise CloudTeacherStaticError("seeded_fixture_blocks_incomplete")
    if not all(bool(seeded_fixture_blocks[key]) for key in required):
        raise CloudTeacherStaticError("seeded_fixture_not_blocked")
    if budget_proof.get("paid_cloud_calls_executed") is not False:
        raise CloudTeacherStaticError("budget_proof_paid_calls_claimed")
    if consensus_veto.get("may_create_quick_pass") is not False:
        raise CloudTeacherStaticError("consensus_quick_pass_overclaim")

    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "coverage_themes_required": list(REQUIRED_COVERAGE_THEMES),
        "minimum_incremental_cases": MINIMUM_INCREMENTAL_CASES,
        "checks": {
            "budget_circuit_breaker": "pass",
            "shadow_teacher_schema": "pass",
            "shadow_consensus_residual": "pass",
            "incremental_value_corpus_audit": "pass",
            "config_shadow_budget_defaults": "pass",
        },
        "seeded_fixture_blocks": {key: True for key in sorted(required)},
        "budget_proof": {
            "hard_limit_usd": budget_proof["hard_limit_usd"],
            "reservation_usd": budget_proof["reservation_usd"],
            "circuit_breaker_tripped": True,
            "duplicate_request_refused": True,
            "paid_cloud_calls_executed": False,
        },
        "config_proof": {
            "mode": config_proof["mode"],
            "operational_limit_usd": config_proof["operational_limit_usd"],
            "hard_limit_usd": config_proof["hard_limit_usd"],
            "reservation_usd": config_proof["reservation_usd"],
            "maximum_calls_per_image": config_proof["maximum_calls_per_image"],
            "minimum_incremental_cases": config_proof["minimum_incremental_cases"],
        },
        "shadow_consensus": {
            "destination": consensus_veto["destination"],
            "reason": consensus_veto["reason"],
            "may_approve_gold": False,
            "may_clear_blocks": False,
            "may_create_quick_pass": False,
        },
        "incremental_audit_fixture_failures": list(small_audit_failures),
        "mf_p4_10_08_complete": False,
        "mf_p4_10_09_complete": False,
        "human_anchor_ge_200_corpus": False,
        "paid_cloud_calls_executed": False,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "production_evidence_pass_claimed": False,
        "honest_non_claims": list(HONEST_NON_CLAIMS),
        "items": [
            "MF-P4-10.04",
            "MF-P4-10.05",
            "MF-P4-10.07",
            "MF-P4-10.08",
            "MF-P4-10.09",
        ],
    }
    refuse_mf_p4_10_08_09_claim(draft)
    digest = _sha(draft)
    draft["report_id"] = f"cts_{digest[:24]}"
    draft["seal_sha256"] = digest
    issues = validate_document(draft, "cloud_teacher_static_report")
    if issues:
        raise CloudTeacherStaticError(
            "schema_validation_failed: "
            + "; ".join(f"{issue.pointer or '/'} {issue.message}" for issue in issues)
        )
    return draft


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "HONEST_NON_CLAIMS",
    "MINIMUM_INCREMENTAL_CASES",
    "PROOF_TIER",
    "REQUIRED_COVERAGE_THEMES",
    "SHADOW_AUTHORITY",
    "CloudTeacherStaticError",
    "assess_shadow_consensus_authority",
    "audit_incremental_value_corpus",
    "build_cloud_teacher_static_report",
    "build_shadow_teacher_judgment",
    "prove_budget_circuit_breaker",
    "prove_config_shadow_budget_defaults",
    "refuse_mf_p4_10_08_09_claim",
    "run_cloud_teacher_static_suite",
]
