"""Progressive autonomous mask selection and calibration."""

from .adapters import MaskCandidateInput, build_mask_candidate_evidence
from .audit import evaluate_immediate_revocation, select_sparse_human_audits
from .calibration import (
    build_autonomy_certificate,
    load_autonomy_config,
    verify_autonomy_certificate,
)
from .controller import AutonomousLoopResult, run_autonomous_correction_loop
from .lifecycle import load_scoped_certificate, write_lifecycle_sidecar
from .operations import build_weekly_audit_queue, process_audit_outcomes
from .pseudo_dataset import build_weighted_pseudo_manifest
from .tournament import CandidateEvidence, TournamentDecision, run_candidate_tournament

__all__ = [
    "CandidateEvidence",
    "MaskCandidateInput",
    "AutonomousLoopResult",
    "TournamentDecision",
    "build_autonomy_certificate",
    "build_mask_candidate_evidence",
    "build_weekly_audit_queue",
    "build_weighted_pseudo_manifest",
    "evaluate_immediate_revocation",
    "load_autonomy_config",
    "load_scoped_certificate",
    "run_candidate_tournament",
    "process_audit_outcomes",
    "run_autonomous_correction_loop",
    "select_sparse_human_audits",
    "verify_autonomy_certificate",
    "write_lifecycle_sidecar",
]
