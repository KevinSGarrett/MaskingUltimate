"""Progressive autonomous mask selection and calibration."""

from .adapters import (
    MaskCandidateInput,
    build_mask_candidate_evidence,
    summarize_candidate_provenance,
)
from .audit import (
    evaluate_immediate_revocation,
    select_mixed_human_audits,
    select_mixed_multi_person_audits,
    select_sparse_human_audits,
)
from .calibration import (
    build_autonomy_certificate,
    load_autonomy_config,
    verify_autonomy_certificate,
)
from .controller import AutonomousLoopResult, run_autonomous_correction_loop
from .emit import (
    AutonomyEmitError,
    emit_lifecycle_and_corpus_record,
    prove_emit_machine_verified_candidate,
    repair_corpus_envelopes,
    resolve_production_machine_root,
)
from .lifecycle import load_scoped_certificate, write_lifecycle_sidecar
from .multi_person_gate import (
    MultiPersonCandidateGateResult,
    MultiPersonGateCheck,
    evaluate_multi_person_candidate_gate,
)
from .multi_person_scope import (
    MultiPersonCertificationScopeResult,
    evaluate_multi_person_certification_scope,
)
from .operational_repair import (
    DurableRepairExecutor,
    LiveRepairProposal,
    OperationalRepairError,
    OperationalRepairResult,
)
from .operations import (
    build_multi_person_audit_queue,
    build_weekly_audit_queue,
    process_audit_outcomes,
    process_multi_person_audit_outcomes,
    run_serious_failure_drill,
)
from .pseudo_dataset import build_weighted_pseudo_manifest
from .repair import (
    BoundedRepairDecision,
    BoundedRepairLimits,
    RepairAttempt,
    RepairGuardResult,
    RepairRegion,
    build_pose_side_evidence,
    decide_bounded_repair,
    evaluate_repair_candidate,
    immutable_protected_union,
    load_repair_regions,
    merge_specialist_repair_regions,
    normalized_roi_points_to_source,
    repair_limits_from_policy,
    requires_reconstruction,
)
from .tournament import CandidateEvidence, TournamentDecision, run_candidate_tournament
from .visual_defect_policy import (
    BLOCKED_VISUAL_PASS_CLAIM,
    HIGHEST_VISUAL_TIER_WITH_RESIDUALS,
    STRUCTURAL_ABSTAIN_DEFECT_CLASSES,
    VisualRepairPromotionDecision,
    decide_visual_repair_promotion,
    seeded_structural_defect_kinds,
)

__all__ = [
    "AutonomyEmitError",
    "CandidateEvidence",
    "MaskCandidateInput",
    "emit_lifecycle_and_corpus_record",
    "prove_emit_machine_verified_candidate",
    "repair_corpus_envelopes",
    "resolve_production_machine_root",
    "MultiPersonCandidateGateResult",
    "MultiPersonCertificationScopeResult",
    "MultiPersonGateCheck",
    "AutonomousLoopResult",
    "TournamentDecision",
    "build_autonomy_certificate",
    "build_multi_person_audit_queue",
    "build_mask_candidate_evidence",
    "summarize_candidate_provenance",
    "build_pose_side_evidence",
    "build_weekly_audit_queue",
    "build_weighted_pseudo_manifest",
    "BoundedRepairDecision",
    "BoundedRepairLimits",
    "RepairAttempt",
    "RepairGuardResult",
    "RepairRegion",
    "evaluate_repair_candidate",
    "decide_bounded_repair",
    "immutable_protected_union",
    "load_repair_regions",
    "merge_specialist_repair_regions",
    "normalized_roi_points_to_source",
    "repair_limits_from_policy",
    "requires_reconstruction",
    "evaluate_immediate_revocation",
    "evaluate_multi_person_candidate_gate",
    "evaluate_multi_person_certification_scope",
    "load_autonomy_config",
    "load_scoped_certificate",
    "LiveRepairProposal",
    "DurableRepairExecutor",
    "OperationalRepairError",
    "OperationalRepairResult",
    "run_candidate_tournament",
    "process_audit_outcomes",
    "process_multi_person_audit_outcomes",
    "run_serious_failure_drill",
    "run_autonomous_correction_loop",
    "select_mixed_human_audits",
    "select_mixed_multi_person_audits",
    "select_sparse_human_audits",
    "verify_autonomy_certificate",
    "write_lifecycle_sidecar",
    "BLOCKED_VISUAL_PASS_CLAIM",
    "HIGHEST_VISUAL_TIER_WITH_RESIDUALS",
    "STRUCTURAL_ABSTAIN_DEFECT_CLASSES",
    "VisualRepairPromotionDecision",
    "decide_visual_repair_promotion",
    "seeded_structural_defect_kinds",
]
