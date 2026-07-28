"""STATIC leakage / authority / index contracts for MF-P9-14.

Fixture- and claim-document gates only. Never walks or copies the ~83k-image
source corpus, never materializes the capacity-held 18k retrieval tier, and
never elevates unlabeled references into truth or training authority.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

PROOF_TIER = "STATIC_PASS"
AUTHORITY = "reference_library_static_gates_no_truth_no_corpus_copy"
ARTIFACT_TYPE = "reference_library_static_gate_report"
SCHEMA_VERSION = "1.0.0"

EXPECTED_BENCHMARK_COUNT = 2500
EXPECTED_RETRIEVAL_COUNT = 18000
SOFT_FLOOR_GIB = 150
HARD_FLOOR_GIB = 100
DHASH_HAMMING_THRESHOLD = 3
CONSERVATIVE_NEAR_RULE = "dhash_hamming_lte_3_blocks_without_requiring_embedding_confirmation"

# Frozen live inventory / selection identities from prior governed evidence.
# These bind claim documents only; they are not re-proven by walking F:.
FROZEN_INVENTORY = {
    "discovered_images": 83422,
    "valid_images": 83411,
    "exact_duplicate_files_beyond_first": 14013,
    "exact_representatives": 69398,
    "classified": 69398,
    "invalid": 0,
    "remaining": 0,
}
FROZEN_SELECTION = {
    "benchmark_reference_count": EXPECTED_BENCHMARK_COUNT,
    "retrieval_reference_count": EXPECTED_RETRIEVAL_COUNT,
    "near_group_fingerprint": ("6e1831840a8103a214eb8c805f3000297aba3a71fa0800927a02dee57241994b"),
    "selection_fingerprint": ("70fe46a65ee46691dfa9a4ede7bfd728d5c38251a8acee46fc2abb2783c74900"),
}
FROZEN_BENCHMARK_MATERIALIZATION = {
    "verified_count": EXPECTED_BENCHMARK_COUNT,
    "materialized_fingerprint": (
        "5e1bd31cbf1697f3e2dbe41dfe7c0e96f9064bda001739d5e05393f0d7dac401"
    ),
}
FROZEN_BENCHMARK_ISOLATION_FINGERPRINT = (
    "c577bbd85760705fd48d86d7668f2a4190832436cfae150afe7049258eb1635e"
)

FORBIDDEN_AUTHORITY_TRUE_KEYS = (
    "training_eligible",
    "truth_authority_granted",
    "gold_claim",
    "human_anchor_gold",
    "selection_or_retrieval_creates_truth",
    "corpus_copy_performed",
    "retrieval_materialization_complete",
    "full_corpus_walk_performed",
)


class ReferenceLibraryStaticGateError(ValueError):
    """Reference-library STATIC contract violated."""


def _canonical_sha256(document: Mapping[str, Any]) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def evaluate_index_progress_contract(
    index_progress: Mapping[str, Any],
    *,
    exact_representatives: int,
) -> dict[str, Any]:
    """Fail closed when classified/remaining/complete disagree with representatives."""

    if not isinstance(index_progress, Mapping):
        raise ReferenceLibraryStaticGateError("index_progress missing")
    if not isinstance(exact_representatives, int) or exact_representatives < 0:
        raise ReferenceLibraryStaticGateError("exact_representatives must be a non-negative int")
    classified = index_progress.get("classified")
    remaining = index_progress.get("remaining")
    complete = index_progress.get("complete")
    issues: list[str] = []
    if not isinstance(classified, int) or classified < 0:
        issues.append("invalid_classified")
    if not isinstance(remaining, int) or remaining < 0:
        issues.append("invalid_remaining")
    if not isinstance(complete, bool):
        issues.append("invalid_complete")
    if not issues:
        expected_remaining = max(0, exact_representatives - classified)
        if remaining != expected_remaining:
            issues.append(f"remaining:{remaining}!={expected_remaining}")
        if complete is not (classified == exact_representatives):
            issues.append("complete_disagrees_with_classified_vs_representatives")
        if complete and remaining != 0:
            issues.append("complete_with_nonzero_remaining")
        if complete and classified != exact_representatives:
            issues.append("complete_with_partial_classification")
    return {
        "schema_version": SCHEMA_VERSION,
        "contract": "index_progress",
        "exact_representatives": exact_representatives,
        "index_progress": dict(index_progress),
        "issues": sorted(set(issues)),
        "passed": not issues,
        "proof_tier": PROOF_TIER,
    }


def evaluate_inventory_claim_contract(
    claim: Mapping[str, Any],
    *,
    require_frozen_live_counts: bool = False,
) -> dict[str, Any]:
    """Validate an inventory claim document without walking the source tree."""

    if not isinstance(claim, Mapping):
        raise ReferenceLibraryStaticGateError("inventory claim missing")
    issues: list[str] = []
    discovered = claim.get("discovered_images")
    valid = claim.get("valid_images")
    reps = claim.get("exact_representatives")
    classified = claim.get("classified")
    remaining = claim.get("remaining")
    invalid = claim.get("invalid", 0)
    for field, value in (
        ("discovered_images", discovered),
        ("valid_images", valid),
        ("exact_representatives", reps),
        ("classified", classified),
        ("remaining", remaining),
    ):
        if not isinstance(value, int) or value < 0:
            issues.append(f"invalid_{field}")
    if claim.get("full_corpus_walk_performed") is True:
        issues.append("full_corpus_walk_performed_forbidden_under_static_gates")
    if claim.get("corpus_copy_performed") is True:
        issues.append("corpus_copy_performed_forbidden_under_static_gates")
    if not issues:
        if valid > discovered:
            issues.append("valid_exceeds_discovered")
        if reps > valid:
            issues.append("representatives_exceed_valid")
        if classified > reps:
            issues.append("classified_exceeds_representatives")
        if remaining != max(0, reps - classified):
            issues.append(f"remaining:{remaining}!={max(0, reps - classified)}")
        if isinstance(invalid, int) and invalid < 0:
            issues.append("invalid_invalid_count")
        if claim.get("complete") is True and remaining != 0:
            issues.append("complete_with_nonzero_remaining")
    if require_frozen_live_counts:
        for key, expected in FROZEN_INVENTORY.items():
            if claim.get(key) != expected:
                issues.append(f"frozen_inventory_drift:{key}:{claim.get(key)}!={expected}")
    return {
        "schema_version": SCHEMA_VERSION,
        "contract": "inventory_claim",
        "require_frozen_live_counts": require_frozen_live_counts,
        "issues": sorted(set(issues)),
        "passed": not issues,
        "proof_tier": PROOF_TIER,
        "honest_non_claims": [
            "full_83k_corpus_walk",
            "full_83k_corpus_copy",
            "retrieval_18k_materialization",
        ],
    }


def evaluate_authority_surface(document: Mapping[str, Any]) -> dict[str, Any]:
    """Refuse any surface that grants truth/training authority to references."""

    if not isinstance(document, Mapping):
        raise ReferenceLibraryStaticGateError("authority document missing")
    issues: list[str] = []
    truth = document.get("truth_authority")
    if truth not in {None, "none"}:
        issues.append(f"truth_authority:{truth}")
    if document.get("training_eligible") is True:
        issues.append("training_eligible")
    if document.get("source_role") not in {None, "unlabeled_reference_corpus"}:
        issues.append(f"source_role:{document.get('source_role')}")
    for key in FORBIDDEN_AUTHORITY_TRUE_KEYS:
        if document.get(key) is True:
            issues.append(f"forbidden_true:{key}")
    nested = document.get("authority")
    if isinstance(nested, Mapping):
        nested_report = evaluate_authority_surface(nested)
        issues.extend(nested_report["issues"])
    candidates = document.get("candidates")
    if isinstance(candidates, Sequence):
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, Mapping):
                issues.append(f"candidate_not_mapping:{index}")
                continue
            if candidate.get("truth_authority") not in {None, "none"}:
                issues.append(f"candidate_truth_authority:{index}")
            if candidate.get("training_eligible") is True:
                issues.append(f"candidate_training_eligible:{index}")
    return {
        "schema_version": SCHEMA_VERSION,
        "contract": "authority_surface",
        "issues": sorted(set(issues)),
        "passed": not issues,
        "proof_tier": PROOF_TIER,
    }


def evaluate_isolation_receipt(
    receipt: Mapping[str, Any],
    *,
    require_production_benchmark_count: bool = True,
    require_frozen_live_fingerprint: bool = False,
) -> dict[str, Any]:
    """Validate a builder/launcher reference-benchmark isolation receipt."""

    if not isinstance(receipt, Mapping):
        raise ReferenceLibraryStaticGateError("isolation receipt missing")
    issues: list[str] = []
    if receipt.get("schema_version") != "1.0.0":
        issues.append("schema_version")
    if receipt.get("passed") is not True:
        issues.append("passed_not_true")
    if receipt.get("issues") not in ([], ()):
        issues.append("nonempty_issues")
    benchmark_count = receipt.get("benchmark_count")
    if require_production_benchmark_count:
        if benchmark_count != EXPECTED_BENCHMARK_COUNT:
            issues.append(f"benchmark_count:{benchmark_count}!={EXPECTED_BENCHMARK_COUNT}")
    elif not isinstance(benchmark_count, int) or benchmark_count < 1:
        issues.append("benchmark_count_invalid")
    fingerprint = receipt.get("benchmark_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        issues.append("benchmark_fingerprint")
    if require_frozen_live_fingerprint and fingerprint != FROZEN_BENCHMARK_ISOLATION_FINGERPRINT:
        issues.append("frozen_isolation_fingerprint_drift")
    if int(receipt.get("record_count") or 0) < 1:
        issues.append("record_count")
    threshold = receipt.get("dhash_hamming_threshold", DHASH_HAMMING_THRESHOLD)
    if threshold != DHASH_HAMMING_THRESHOLD:
        issues.append(f"dhash_hamming_threshold:{threshold}")
    rule = receipt.get("conservative_near_duplicate_rule")
    if rule is not None and rule != CONSERVATIVE_NEAR_RULE:
        issues.append("conservative_near_duplicate_rule_drift")
    return {
        "schema_version": SCHEMA_VERSION,
        "contract": "isolation_receipt",
        "require_production_benchmark_count": require_production_benchmark_count,
        "require_frozen_live_fingerprint": require_frozen_live_fingerprint,
        "issues": sorted(set(issues)),
        "passed": not issues,
        "proof_tier": PROOF_TIER,
    }


def require_isolation_receipt(
    receipt: Mapping[str, Any] | None,
    *,
    require_production_benchmark_count: bool = True,
) -> dict[str, Any]:
    """Raise when a training dataset lacks a passing isolation receipt."""

    if not isinstance(receipt, Mapping):
        raise ReferenceLibraryStaticGateError(
            "training dataset lacks frozen reference-benchmark isolation"
        )
    report = evaluate_isolation_receipt(
        receipt,
        require_production_benchmark_count=require_production_benchmark_count,
    )
    if not report["passed"]:
        raise ReferenceLibraryStaticGateError(
            "training dataset lacks frozen reference-benchmark isolation: "
            + ", ".join(report["issues"])
        )
    return report


def evaluate_materialization_honesty(report: Mapping[str, Any]) -> dict[str, Any]:
    """Capacity holds must remain incomplete; no silent complete claim."""

    if not isinstance(report, Mapping):
        raise ReferenceLibraryStaticGateError("materialization report missing")
    issues: list[str] = []
    capacity_hold = report.get("capacity_hold")
    complete = report.get("complete")
    if capacity_hold is not None:
        if not isinstance(capacity_hold, Mapping):
            issues.append("capacity_hold_not_mapping")
        else:
            reason = capacity_hold.get("reason")
            if reason not in {
                "storage_below_soft_floor",
                "storage_below_hard_floor",
                "projected_below_soft_floor",
            }:
                issues.append(f"capacity_hold_reason:{reason}")
            soft = capacity_hold.get("soft_floor_gib", SOFT_FLOOR_GIB)
            if soft != SOFT_FLOOR_GIB:
                issues.append(f"soft_floor_gib:{soft}")
        if complete is True:
            issues.append("complete_true_under_capacity_hold")
        if report.get("retrieval_materialization_complete") is True:
            issues.append("retrieval_materialization_complete_under_capacity_hold")
        # Capacity hold must refuse new copies in the held chunk.
        if report.get("processed_this_chunk") not in {0, None}:
            issues.append("processed_under_capacity_hold")
    if report.get("corpus_copy_performed") is True:
        issues.append("corpus_copy_performed")
    return {
        "schema_version": SCHEMA_VERSION,
        "contract": "materialization_honesty",
        "capacity_held": capacity_hold is not None,
        "issues": sorted(set(issues)),
        "passed": not issues,
        "proof_tier": PROOF_TIER,
        "honest_status": (
            "capacity_held_incomplete" if capacity_hold is not None else "capacity_not_held"
        ),
    }


def evaluate_capacity_held_portfolio_status(
    *,
    benchmark_materialized_count: int,
    retrieval_materialized_count: int,
    contact_sheets_complete: bool,
    soft_floor_gib: float = SOFT_FLOOR_GIB,
) -> dict[str, Any]:
    """Honest MF-P9-14.06 posture: benchmark may be done; retrieval may stay held."""

    issues: list[str] = []
    if benchmark_materialized_count != EXPECTED_BENCHMARK_COUNT:
        issues.append(
            f"benchmark_materialized_count:{benchmark_materialized_count}"
            f"!={EXPECTED_BENCHMARK_COUNT}"
        )
    if soft_floor_gib != SOFT_FLOOR_GIB:
        issues.append(f"soft_floor_gib:{soft_floor_gib}")
    if retrieval_materialized_count < 0:
        issues.append("retrieval_materialized_count_negative")
    retrieval_complete = retrieval_materialized_count == EXPECTED_RETRIEVAL_COUNT
    capacity_held = not retrieval_complete
    if capacity_held and retrieval_materialized_count != 0:
        # Partial unsafe copy is not the governed capacity-held posture.
        issues.append(
            "partial_retrieval_copy_not_governed_capacity_held_posture:"
            f"{retrieval_materialized_count}"
        )
    portfolio_complete = (
        benchmark_materialized_count == EXPECTED_BENCHMARK_COUNT
        and retrieval_complete
        and contact_sheets_complete
    )
    if capacity_held and portfolio_complete:
        issues.append("portfolio_complete_while_capacity_held")
    return {
        "schema_version": SCHEMA_VERSION,
        "contract": "capacity_held_portfolio",
        "benchmark_materialized_count": benchmark_materialized_count,
        "retrieval_materialized_count": retrieval_materialized_count,
        "expected_retrieval_count": EXPECTED_RETRIEVAL_COUNT,
        "contact_sheets_complete": contact_sheets_complete,
        "capacity_held": capacity_held,
        "portfolio_complete_claim_allowed": portfolio_complete and not capacity_held,
        "mf_p9_14_06_complete_claim_allowed": portfolio_complete and not issues,
        "issues": sorted(set(issues)),
        "passed": not issues,
        "proof_tier": PROOF_TIER,
        "honest_non_claims": [
            "retrieval_18k_materialization",
            "mf_p9_14_06_complete_while_capacity_held",
            "full_83k_corpus_copy",
        ],
    }


def build_static_gate_evidence(
    *,
    index_report: Mapping[str, Any],
    inventory_report: Mapping[str, Any],
    authority_report: Mapping[str, Any],
    isolation_report: Mapping[str, Any],
    materialization_report: Mapping[str, Any],
    portfolio_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble a sealed STATIC evidence document for tracker / OPS_LOG."""

    reports = {
        "index_progress": dict(index_report),
        "inventory_claim": dict(inventory_report),
        "authority_surface": dict(authority_report),
        "isolation_receipt": dict(isolation_report),
        "materialization_honesty": dict(materialization_report),
        "capacity_held_portfolio": dict(portfolio_report),
    }
    all_passed = all(bool(report.get("passed")) for report in reports.values())
    document = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "date": "2026-07-19",
        "items": ["MF-P9-14.06", "MF-P9-14.07", "MF-P9-14.09"],
        "result": (
            "pass_reference_library_static_gates"
            if all_passed
            else "fail_reference_library_static_gates"
        ),
        "contracts": reports,
        "frozen_bindings": {
            "inventory": dict(FROZEN_INVENTORY),
            "selection": dict(FROZEN_SELECTION),
            "benchmark_materialization": dict(FROZEN_BENCHMARK_MATERIALIZATION),
            "benchmark_isolation_fingerprint": FROZEN_BENCHMARK_ISOLATION_FINGERPRINT,
        },
        "honest_non_claims": [
            "full_83k_corpus_walk_or_copy",
            "retrieval_18k_materialization",
            "MF-P9-14.06 complete",
            "MF-P9-14.09 complete while 14.06 capacity-held",
            "truth_authority_or_training_eligibility_for_references",
            "doctor-green",
            "gold",
            "PRODUCTION_EVIDENCE_PASS",
        ],
        "implementation": {
            "module": "src/maskfactory/reference_library_static_gates.py",
            "tests": ["tests/test_reference_library_static_gates.py"],
            "wired_into": ["src/maskfactory/training/launch.py"],
        },
    }
    document["sha256"] = _canonical_sha256(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    return document


def write_static_gate_evidence(document: Mapping[str, Any], output: Path) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(output)
    return output


__all__ = [
    "AUTHORITY",
    "ARTIFACT_TYPE",
    "CONSERVATIVE_NEAR_RULE",
    "DHASH_HAMMING_THRESHOLD",
    "EXPECTED_BENCHMARK_COUNT",
    "EXPECTED_RETRIEVAL_COUNT",
    "FROZEN_BENCHMARK_ISOLATION_FINGERPRINT",
    "FROZEN_BENCHMARK_MATERIALIZATION",
    "FROZEN_INVENTORY",
    "FROZEN_SELECTION",
    "HARD_FLOOR_GIB",
    "PROOF_TIER",
    "ReferenceLibraryStaticGateError",
    "SCHEMA_VERSION",
    "SOFT_FLOOR_GIB",
    "build_static_gate_evidence",
    "evaluate_authority_surface",
    "evaluate_capacity_held_portfolio_status",
    "evaluate_index_progress_contract",
    "evaluate_inventory_claim_contract",
    "evaluate_isolation_receipt",
    "evaluate_materialization_honesty",
    "require_isolation_receipt",
    "write_static_gate_evidence",
]
