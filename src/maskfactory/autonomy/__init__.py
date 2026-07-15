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
from .operations import (
    build_multi_person_audit_queue,
    build_weekly_audit_queue,
    process_audit_outcomes,
    process_multi_person_audit_outcomes,
    run_serious_failure_drill,
)
from .pseudo_dataset import build_weighted_pseudo_manifest
from .repair import (
    RepairGuardResult,
    RepairRegion,
    build_pose_side_evidence,
    evaluate_repair_candidate,
    immutable_protected_union,
    load_repair_regions,
    merge_specialist_repair_regions,
    normalized_roi_points_to_source,
    requires_reconstruction,
)
from .tournament import CandidateEvidence, TournamentDecision, run_candidate_tournament

__all__ = [
    "CandidateEvidence",
    "MaskCandidateInput",
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
    "RepairGuardResult",
    "RepairRegion",
    "evaluate_repair_candidate",
    "immutable_protected_union",
    "load_repair_regions",
    "merge_specialist_repair_regions",
    "normalized_roi_points_to_source",
    "requires_reconstruction",
    "evaluate_immediate_revocation",
    "evaluate_multi_person_candidate_gate",
    "evaluate_multi_person_certification_scope",
    "load_autonomy_config",
    "load_scoped_certificate",
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
]
