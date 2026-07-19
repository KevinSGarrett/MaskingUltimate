"""STATIC zero-tolerance selective-autonomy hard gates (MF-P9-15.02).

Binds existing QA/certification hard-block identities for cross-instance bleed,
left/right swaps, and format integrity. STATIC_PASS only: never claims live
production audit completion, doctor-green, gold, or PRODUCTION_EVIDENCE_PASS.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "selective_autonomy_hard_gates_static_report"
AUTHORITY = "selective_autonomy_hard_gates_static_only"

# Existing hard-block identities already enforced in QA/certification paths.
FORMAT_INTEGRITY_QC_IDS = ("QC-001", "QC-002", "QC-003")
CROSS_INSTANCE_BLEED_QC_IDS = ("QC-035", "QC-036")
LEFT_RIGHT_SWAP_SIGNALS = (
    "wrong_side",
    "maximum_left_right_swap_count",
    "QC-V2 side/swap fixtures",
)

ZERO_TOLERANCE = {
    "cross_instance_bleed": 0,
    "left_right_swaps": 0,
    "format_integrity_failures": 0,
}


class SelectiveAutonomyHardGateError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def build_selective_autonomy_hard_gates_report(
    *,
    seeded_violation_blocks: Mapping[str, bool],
) -> dict[str, Any]:
    """Build a STATIC report binding zero-tolerance hard gates.

    ``seeded_violation_blocks`` must prove each required family fails closed on a
    seeded defect (True = seeded defect blocked). Missing/false fails closed.
    """
    required = {
        "format_integrity",
        "cross_instance_bleed",
        "left_right_swap",
    }
    if set(seeded_violation_blocks) != required:
        raise SelectiveAutonomyHardGateError("seeded_violation_blocks_incomplete")
    if not all(bool(seeded_violation_blocks[key]) for key in required):
        raise SelectiveAutonomyHardGateError("seeded_violation_not_blocked")

    draft: dict[str, Any] = {
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "zero_tolerance": dict(ZERO_TOLERANCE),
        "bound_qc_ids": {
            "format_integrity": list(FORMAT_INTEGRITY_QC_IDS),
            "cross_instance_bleed": list(CROSS_INSTANCE_BLEED_QC_IDS),
            "left_right_swap_signals": list(LEFT_RIGHT_SWAP_SIGNALS),
        },
        "seeded_violation_blocks": {key: True for key in sorted(required)},
        "any_seeded_or_audited_violation_blocks_or_revokes": True,
        "production_audit_complete": False,
        "live_autonomous_runs_measured": False,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "visual_qa_pass_claimed": False,
        "main_complete_claimed": False,
        "production_evidence_pass_claimed": False,
    }
    digest = _sha(draft)
    draft["report_id"] = f"sahg_{digest[:24]}"
    draft["seal_sha256"] = digest
    return draft


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "CROSS_INSTANCE_BLEED_QC_IDS",
    "FORMAT_INTEGRITY_QC_IDS",
    "LEFT_RIGHT_SWAP_SIGNALS",
    "PROOF_TIER",
    "ZERO_TOLERANCE",
    "SelectiveAutonomyHardGateError",
    "build_selective_autonomy_hard_gates_report",
]
