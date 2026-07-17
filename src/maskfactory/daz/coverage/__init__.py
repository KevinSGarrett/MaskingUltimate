"""Coverage vocabulary, deficit, sampling, and corpus-planning contracts."""

from .candidates import (
    CandidateGenerationError,
    build_candidate_batch,
    load_candidate_generation_policy,
    publish_candidate_batch,
    validate_candidate_batch,
    validate_candidate_generation_policy,
)
from .concentration import (
    ConcentrationError,
    build_concentration_report,
    derive_candidate_history_record,
    load_concentration_policy,
    publish_concentration_report,
    validate_concentration_policy,
    validate_concentration_report,
)
from .deficits import (
    RealDeficitSignalError,
    build_real_deficit_signal_report,
    load_deficit_adapter_policy,
    publish_real_deficit_signal_report,
    validate_deficit_adapter_policy,
    validate_real_deficit_signal_report,
)
from .selection import (
    CandidateSelectionError,
    build_candidate_selection,
    load_candidate_utility_policy,
    publish_candidate_selection,
    validate_candidate_selection,
    validate_candidate_utility_policy,
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
    "CandidateSelectionError",
    "ConcentrationError",
    "CoverageVocabularyError",
    "RealDeficitSignalError",
    "build_candidate_batch",
    "build_candidate_selection",
    "build_concentration_report",
    "build_coverage_vocabulary_report",
    "build_real_deficit_signal_report",
    "load_candidate_generation_policy",
    "load_candidate_utility_policy",
    "load_concentration_policy",
    "load_coverage_vocabulary",
    "load_deficit_adapter_policy",
    "publish_candidate_batch",
    "publish_candidate_selection",
    "publish_concentration_report",
    "publish_coverage_vocabulary_report",
    "publish_real_deficit_signal_report",
    "validate_candidate_batch",
    "validate_candidate_generation_policy",
    "validate_candidate_selection",
    "validate_candidate_utility_policy",
    "validate_concentration_policy",
    "validate_concentration_report",
    "validate_coverage_vocabulary",
    "validate_coverage_vocabulary_report",
    "validate_deficit_adapter_policy",
    "validate_real_deficit_signal_report",
    "derive_candidate_history_record",
]
