"""Progressive autonomous mask selection and calibration.

Public exports are resolved only when requested so CPU-safe work-cell tooling does
not import optional pixel-analysis dependencies such as SciPy.
"""

from __future__ import annotations

from importlib import import_module
from typing import Final

_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "CandidateEvidence": ("tournament", "CandidateEvidence"),
    "MaskCandidateInput": ("adapters", "MaskCandidateInput"),
    "MultiPersonCandidateGateResult": ("multi_person_gate", "MultiPersonCandidateGateResult"),
    "MultiPersonCertificationScopeResult": (
        "multi_person_scope",
        "MultiPersonCertificationScopeResult",
    ),
    "MultiPersonGateCheck": ("multi_person_gate", "MultiPersonGateCheck"),
    "AutonomousLoopResult": ("controller", "AutonomousLoopResult"),
    "TournamentDecision": ("tournament", "TournamentDecision"),
    "build_autonomy_certificate": ("calibration", "build_autonomy_certificate"),
    "build_multi_person_audit_queue": ("operations", "build_multi_person_audit_queue"),
    "build_mask_candidate_evidence": ("adapters", "build_mask_candidate_evidence"),
    "summarize_candidate_provenance": ("adapters", "summarize_candidate_provenance"),
    "build_pose_side_evidence": ("repair", "build_pose_side_evidence"),
    "build_weekly_audit_queue": ("operations", "build_weekly_audit_queue"),
    "build_weighted_pseudo_manifest": ("pseudo_dataset", "build_weighted_pseudo_manifest"),
    "BoundedRepairDecision": ("repair", "BoundedRepairDecision"),
    "BoundedRepairLimits": ("repair", "BoundedRepairLimits"),
    "RepairAttempt": ("repair", "RepairAttempt"),
    "RepairGuardResult": ("repair", "RepairGuardResult"),
    "RepairRegion": ("repair", "RepairRegion"),
    "evaluate_repair_candidate": ("repair", "evaluate_repair_candidate"),
    "decide_bounded_repair": ("repair", "decide_bounded_repair"),
    "immutable_protected_union": ("repair", "immutable_protected_union"),
    "load_repair_regions": ("repair", "load_repair_regions"),
    "merge_specialist_repair_regions": ("repair", "merge_specialist_repair_regions"),
    "normalized_roi_points_to_source": ("repair", "normalized_roi_points_to_source"),
    "repair_limits_from_policy": ("repair", "repair_limits_from_policy"),
    "requires_reconstruction": ("repair", "requires_reconstruction"),
    "evaluate_immediate_revocation": ("audit", "evaluate_immediate_revocation"),
    "evaluate_multi_person_candidate_gate": (
        "multi_person_gate",
        "evaluate_multi_person_candidate_gate",
    ),
    "evaluate_multi_person_certification_scope": (
        "multi_person_scope",
        "evaluate_multi_person_certification_scope",
    ),
    "load_autonomy_config": ("calibration", "load_autonomy_config"),
    "load_scoped_certificate": ("lifecycle", "load_scoped_certificate"),
    "LiveRepairProposal": ("operational_repair", "LiveRepairProposal"),
    "DurableRepairExecutor": ("operational_repair", "DurableRepairExecutor"),
    "OperationalRepairError": ("operational_repair", "OperationalRepairError"),
    "OperationalRepairResult": ("operational_repair", "OperationalRepairResult"),
    "run_candidate_tournament": ("tournament", "run_candidate_tournament"),
    "process_audit_outcomes": ("operations", "process_audit_outcomes"),
    "process_multi_person_audit_outcomes": ("operations", "process_multi_person_audit_outcomes"),
    "run_serious_failure_drill": ("operations", "run_serious_failure_drill"),
    "run_autonomous_correction_loop": ("controller", "run_autonomous_correction_loop"),
    "select_mixed_human_audits": ("audit", "select_mixed_human_audits"),
    "select_mixed_multi_person_audits": ("audit", "select_mixed_multi_person_audits"),
    "select_sparse_human_audits": ("audit", "select_sparse_human_audits"),
    "verify_autonomy_certificate": ("calibration", "verify_autonomy_certificate"),
    "write_lifecycle_sidecar": ("lifecycle", "write_lifecycle_sidecar"),
    "BLOCKED_VISUAL_PASS_CLAIM": ("visual_defect_policy", "BLOCKED_VISUAL_PASS_CLAIM"),
    "HIGHEST_VISUAL_TIER_WITH_RESIDUALS": (
        "visual_defect_policy",
        "HIGHEST_VISUAL_TIER_WITH_RESIDUALS",
    ),
    "STRUCTURAL_ABSTAIN_DEFECT_CLASSES": (
        "visual_defect_policy",
        "STRUCTURAL_ABSTAIN_DEFECT_CLASSES",
    ),
    "VisualRepairPromotionDecision": ("visual_defect_policy", "VisualRepairPromotionDecision"),
    "decide_visual_repair_promotion": ("visual_defect_policy", "decide_visual_repair_promotion"),
    "seeded_structural_defect_kinds": ("visual_defect_policy", "seeded_structural_defect_kinds"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> object:
    """Resolve a documented autonomy export without importing unrelated modules."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(f"{__name__}.{module_name}"), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
