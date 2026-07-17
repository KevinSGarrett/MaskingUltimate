"""Coverage vocabulary, deficit, sampling, and corpus-planning contracts."""

from .candidates import (
    CandidateGenerationError,
    build_candidate_batch,
    load_candidate_generation_policy,
    publish_candidate_batch,
    validate_candidate_batch,
    validate_candidate_generation_policy,
)
from .deficits import (
    RealDeficitSignalError,
    build_real_deficit_signal_report,
    load_deficit_adapter_policy,
    publish_real_deficit_signal_report,
    validate_deficit_adapter_policy,
    validate_real_deficit_signal_report,
)
from .vocabulary import (
    CoverageVocabularyError,
    build_coverage_vocabulary_report,
    load_coverage_vocabulary,
    publish_coverage_vocabulary_report,
    validate_coverage_vocabulary,
    validate_coverage_vocabulary_report,
)

__all__ = [
    "CandidateGenerationError",
    "CoverageVocabularyError",
    "RealDeficitSignalError",
    "build_candidate_batch",
    "build_coverage_vocabulary_report",
    "build_real_deficit_signal_report",
    "load_candidate_generation_policy",
    "load_coverage_vocabulary",
    "load_deficit_adapter_policy",
    "publish_candidate_batch",
    "publish_coverage_vocabulary_report",
    "publish_real_deficit_signal_report",
    "validate_candidate_batch",
    "validate_candidate_generation_policy",
    "validate_coverage_vocabulary",
    "validate_coverage_vocabulary_report",
    "validate_deficit_adapter_policy",
    "validate_real_deficit_signal_report",
]
