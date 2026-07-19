"""STATIC binders for horizon multi-person and video go/no-go decisions.

Binds Plan/HORIZON_MULTI_PERSON_GO_NO_GO.md and Plan/HORIZON_VIDEO_GO_NO_GO.md.
Fixture- and memo-bound only: refuses independent-real / production GO without
required evidence, never claims GO, doctor-green, gold, Main-complete, or
PRODUCTION_EVIDENCE_PASS.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .validation import validate_document

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "horizon_go_no_go_static_report"
AUTHORITY = "horizon_go_no_go_static_only_no_production_or_independent_real_go"
SCHEMA_VERSION = "1.0.0"

MULTI_PERSON_MEMO = Path("Plan/HORIZON_MULTI_PERSON_GO_NO_GO.md")
VIDEO_MEMO = Path("Plan/HORIZON_VIDEO_GO_NO_GO.md")

# Optional independent_real_accuracy / production promotion for multi-person
# (HORIZON_MULTI_PERSON_GO_NO_GO.md — MF-P8-10 / D11 / G9).
MULTI_PERSON_GO_EVIDENCE = (
    "governed_real_2_to_4_person_images_ge_10",
    "kevin_sop_1_through_6_complete",
    "d11_demonstration_recorded",
    "g9_cross_instance_bleed_rate_zero",
    "mf_p8_10_01_through_06_complete",
    "mf_p8_exit_complete",
)

# Core production use after autonomous temporal certificate + bridge gates
# (HORIZON_VIDEO_GO_NO_GO.md — doc-24 production gate).
VIDEO_PRODUCTION_GO_EVIDENCE = (
    "temporal_package_schema_qualified",
    "track_identity_ownership_authority",
    "temporal_hard_qa_clean",
    "zero_identity_switch_gate",
    "autonomous_temporal_certificate",
    "bridge_gates_pass",
)

# Optional independent real-video / human-gold claim (additional to production).
VIDEO_INDEPENDENT_GO_EVIDENCE = (
    "governed_10_clip_corpus",
    "reviewed_truth_present",
    "measured_drift_present",
    "operator_cost_evidence_present",
)

HONEST_NON_CLAIMS = (
    "multi_person_independent_real_accuracy_go",
    "multi_person_production_go",
    "video_production_use_go",
    "video_independent_real_accuracy_go",
    "mf_p8_exit_complete",
    "mf_p7_exit_complete",
    "doctor_green",
    "gold",
    "VISUAL_QA_PASS_BOUNDED",
    "Main-complete",
    "PRODUCTION_EVIDENCE_PASS",
)


class HorizonGoNoGoStaticError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _missing_keys(evidence: Mapping[str, Any], keys: tuple[str, ...]) -> list[str]:
    return [key for key in keys if evidence.get(key) is not True]


def bind_horizon_memos(
    *,
    multi_person_memo: Path = MULTI_PERSON_MEMO,
    video_memo: Path = VIDEO_MEMO,
) -> dict[str, Any]:
    """Prove both horizon decision memos exist and are non-empty."""

    bindings: dict[str, Any] = {}
    for label, path in (
        ("multi_person", multi_person_memo),
        ("video", video_memo),
    ):
        if not path.is_file():
            raise HorizonGoNoGoStaticError(f"horizon_memo_missing:{label}:{path.as_posix()}")
        text = path.read_text(encoding="utf-8")
        if len(text.strip()) < 64:
            raise HorizonGoNoGoStaticError(f"horizon_memo_too_short:{label}")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        bindings[label] = {
            "path": path.as_posix(),
            "sha256": digest,
            "bytes": len(text.encode("utf-8")),
        }
    return bindings


def evaluate_multi_person_horizon(
    evidence: Mapping[str, Any],
    *,
    claim_independent_real_go: bool = False,
    claim_production_go: bool = False,
) -> dict[str, Any]:
    """Architecture may already be in P8; independent/production GO needs MF-P8-10 evidence."""

    missing = _missing_keys(evidence, MULTI_PERSON_GO_EVIDENCE)
    evidence_complete = not missing
    decision = "GO" if evidence_complete else "NO_GO"

    if claim_independent_real_go and not evidence_complete:
        raise HorizonGoNoGoStaticError(
            "multi_person_independent_real_go_refused:" + ",".join(missing)
        )
    if claim_production_go and not evidence_complete:
        raise HorizonGoNoGoStaticError("multi_person_production_go_refused:" + ",".join(missing))

    return {
        "architecture_into_p8": True,
        "independent_real_accuracy_decision": decision,
        "production_promotion_decision": decision,
        "required_evidence_keys": list(MULTI_PERSON_GO_EVIDENCE),
        "missing_evidence_keys": missing,
        "evidence_complete": evidence_complete,
        "claim_independent_real_go": claim_independent_real_go,
        "claim_production_go": claim_production_go,
    }


def evaluate_video_horizon(
    evidence: Mapping[str, Any],
    *,
    claim_production_go: bool = False,
    claim_independent_real_go: bool = False,
) -> dict[str, Any]:
    """Doc-24 authorizes contract/runtime work; production/independent GO need evidence."""

    prod_missing = _missing_keys(evidence, VIDEO_PRODUCTION_GO_EVIDENCE)
    indep_missing = _missing_keys(
        evidence, VIDEO_PRODUCTION_GO_EVIDENCE + VIDEO_INDEPENDENT_GO_EVIDENCE
    )
    production_complete = not prod_missing
    independent_complete = not indep_missing
    production_decision = "GO" if production_complete else "NO_GO"
    independent_decision = "GO" if independent_complete else "NO_GO"

    if claim_production_go and not production_complete:
        raise HorizonGoNoGoStaticError("video_production_go_refused:" + ",".join(prod_missing))
    if claim_independent_real_go and not independent_complete:
        raise HorizonGoNoGoStaticError(
            "video_independent_real_go_refused:" + ",".join(indep_missing)
        )

    return {
        "core_contract_implementation_authorized": True,
        "production_use_decision": production_decision,
        "independent_real_accuracy_decision": independent_decision,
        "production_required_evidence_keys": list(VIDEO_PRODUCTION_GO_EVIDENCE),
        "independent_required_evidence_keys": list(
            VIDEO_PRODUCTION_GO_EVIDENCE + VIDEO_INDEPENDENT_GO_EVIDENCE
        ),
        "production_missing_evidence_keys": prod_missing,
        "independent_missing_evidence_keys": indep_missing,
        "production_evidence_complete": production_complete,
        "independent_evidence_complete": independent_complete,
        "claim_production_go": claim_production_go,
        "claim_independent_real_go": claim_independent_real_go,
    }


def refuse_horizon_overclaim(report: Mapping[str, Any]) -> None:
    """Fail closed if a sealed report tries to claim GO or exit completion."""

    forbidden_true = (
        ("multi_person_independent_real_accuracy_go_claimed", "mp_independent_go_overclaim"),
        ("multi_person_production_go_claimed", "mp_production_go_overclaim"),
        ("video_production_use_go_claimed", "video_production_go_overclaim"),
        ("video_independent_real_accuracy_go_claimed", "video_independent_go_overclaim"),
        ("mf_p8_exit_complete", "mf_p8_exit_overclaim"),
        ("mf_p7_exit_complete", "mf_p7_exit_overclaim"),
        ("doctor_green_claimed", "doctor_green_overclaim"),
        ("gold_claimed", "gold_overclaim"),
        ("visual_qa_pass_claimed", "visual_qa_overclaim"),
        ("main_complete_claimed", "main_complete_overclaim"),
        ("production_evidence_pass_claimed", "production_evidence_overclaim"),
    )
    for field, reason in forbidden_true:
        if report.get(field) is True:
            raise HorizonGoNoGoStaticError(reason)

    for field, expected in (
        ("multi_person_independent_real_accuracy_decision", "NO_GO"),
        ("multi_person_production_promotion_decision", "NO_GO"),
        ("video_production_use_decision", "NO_GO"),
        ("video_independent_real_accuracy_decision", "NO_GO"),
    ):
        if report.get(field) not in (None, expected) and report.get(field) != expected:
            raise HorizonGoNoGoStaticError(f"horizon_decision_overclaim:{field}")


def _empty_evidence(keys: tuple[str, ...]) -> dict[str, bool]:
    return {key: False for key in keys}


def run_horizon_go_no_go_static_suite(
    *,
    multi_person_memo: Path = MULTI_PERSON_MEMO,
    video_memo: Path = VIDEO_MEMO,
) -> dict[str, Any]:
    """Execute horizon go/no-go STATIC binders and seal a schema-valid report."""

    memos = bind_horizon_memos(
        multi_person_memo=multi_person_memo,
        video_memo=video_memo,
    )

    mp_evidence = _empty_evidence(MULTI_PERSON_GO_EVIDENCE)
    video_evidence = _empty_evidence(VIDEO_PRODUCTION_GO_EVIDENCE + VIDEO_INDEPENDENT_GO_EVIDENCE)

    multi_person = evaluate_multi_person_horizon(mp_evidence)
    video = evaluate_video_horizon(video_evidence)

    if multi_person["independent_real_accuracy_decision"] != "NO_GO":
        raise HorizonGoNoGoStaticError("multi_person_fixture_unexpected_go")
    if video["production_use_decision"] != "NO_GO":
        raise HorizonGoNoGoStaticError("video_fixture_unexpected_go")

    # Negative fixtures: claiming GO with empty evidence must fail closed.
    try:
        evaluate_multi_person_horizon(mp_evidence, claim_independent_real_go=True)
        raise HorizonGoNoGoStaticError("multi_person_negative_go_fixture_passed")
    except HorizonGoNoGoStaticError as exc:
        if "multi_person_independent_real_go_refused" not in exc.reason:
            raise
        multi_person_negative_blocked = True

    try:
        evaluate_video_horizon(video_evidence, claim_production_go=True)
        raise HorizonGoNoGoStaticError("video_negative_go_fixture_passed")
    except HorizonGoNoGoStaticError as exc:
        if "video_production_go_refused" not in exc.reason:
            raise
        video_negative_blocked = True

    try:
        evaluate_video_horizon(video_evidence, claim_independent_real_go=True)
        raise HorizonGoNoGoStaticError("video_independent_negative_go_fixture_passed")
    except HorizonGoNoGoStaticError as exc:
        if "video_independent_real_go_refused" not in exc.reason:
            raise
        video_independent_negative_blocked = True

    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "items": ["MF-P7-05.01", "MF-P7-05.02"],
        "memo_bindings": memos,
        "multi_person": {
            "architecture_into_p8": True,
            "independent_real_accuracy_decision": "NO_GO",
            "production_promotion_decision": "NO_GO",
            "required_evidence_keys": list(MULTI_PERSON_GO_EVIDENCE),
            "missing_evidence_keys": list(MULTI_PERSON_GO_EVIDENCE),
            "evidence_complete": False,
        },
        "video": {
            "core_contract_implementation_authorized": True,
            "production_use_decision": "NO_GO",
            "independent_real_accuracy_decision": "NO_GO",
            "production_required_evidence_keys": list(VIDEO_PRODUCTION_GO_EVIDENCE),
            "independent_required_evidence_keys": list(
                VIDEO_PRODUCTION_GO_EVIDENCE + VIDEO_INDEPENDENT_GO_EVIDENCE
            ),
            "production_missing_evidence_keys": list(VIDEO_PRODUCTION_GO_EVIDENCE),
            "independent_missing_evidence_keys": list(
                VIDEO_PRODUCTION_GO_EVIDENCE + VIDEO_INDEPENDENT_GO_EVIDENCE
            ),
            "production_evidence_complete": False,
            "independent_evidence_complete": False,
        },
        "checks": {
            "multi_person_memo_bound": "pass",
            "video_memo_bound": "pass",
            "multi_person_go_refused_without_evidence": "pass",
            "video_production_go_refused_without_evidence": "pass",
            "video_independent_go_refused_without_evidence": "pass",
        },
        "multi_person_negative_go_fixture_blocked": multi_person_negative_blocked,
        "video_production_negative_go_fixture_blocked": video_negative_blocked,
        "video_independent_negative_go_fixture_blocked": video_independent_negative_blocked,
        "multi_person_independent_real_accuracy_decision": "NO_GO",
        "multi_person_production_promotion_decision": "NO_GO",
        "video_production_use_decision": "NO_GO",
        "video_independent_real_accuracy_decision": "NO_GO",
        "multi_person_independent_real_accuracy_go_claimed": False,
        "multi_person_production_go_claimed": False,
        "video_production_use_go_claimed": False,
        "video_independent_real_accuracy_go_claimed": False,
        "mf_p8_exit_complete": False,
        "mf_p7_exit_complete": False,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "visual_qa_pass_claimed": False,
        "main_complete_claimed": False,
        "production_evidence_pass_claimed": False,
        "honest_non_claims": list(HONEST_NON_CLAIMS),
    }
    refuse_horizon_overclaim(draft)

    digest = _sha(draft)
    draft["report_id"] = f"hgn_{digest[:24]}"
    draft["seal_sha256"] = digest
    draft["sha256"] = _sha({key: value for key, value in draft.items() if key != "sha256"})

    issues = validate_document(draft, "horizon_go_no_go_static_report")
    if issues:
        detail = "; ".join(
            f"{getattr(issue, 'pointer', None) or '/'}: {issue.message}" for issue in issues
        )
        raise HorizonGoNoGoStaticError(f"schema_validation_failed:{detail}")
    return draft


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "HONEST_NON_CLAIMS",
    "MULTI_PERSON_GO_EVIDENCE",
    "MULTI_PERSON_MEMO",
    "PROOF_TIER",
    "SCHEMA_VERSION",
    "VIDEO_INDEPENDENT_GO_EVIDENCE",
    "VIDEO_MEMO",
    "VIDEO_PRODUCTION_GO_EVIDENCE",
    "HorizonGoNoGoStaticError",
    "bind_horizon_memos",
    "evaluate_multi_person_horizon",
    "evaluate_video_horizon",
    "refuse_horizon_overclaim",
    "run_horizon_go_no_go_static_suite",
]
