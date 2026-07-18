"""Fail-closed MaskFactory runtime authority operations."""

from .complete_map_hard_veto import (
    CompleteMapHardVetoError,
    bind_complete_map_report,
    build_complete_map_hard_veto_report,
    complete_map_hard_veto_report_sha256,
)
from .operational_certificate import (
    OperationalCertificateIssuanceError,
    canonical_decoded_raster_sha256,
    issue_operational_autonomy_certificate,
)
from .operational_policy import (
    OperationalPolicyError,
    bind_operational_policy_report,
    build_operational_policy_replay_observation,
    evaluate_operational_policy,
    load_operational_policy,
    prepare_operational_policy_replay,
    verify_operational_policy_report,
)

__all__ = [
    "CompleteMapHardVetoError",
    "OperationalCertificateIssuanceError",
    "OperationalPolicyError",
    "bind_operational_policy_report",
    "bind_complete_map_report",
    "build_operational_policy_replay_observation",
    "build_complete_map_hard_veto_report",
    "canonical_decoded_raster_sha256",
    "complete_map_hard_veto_report_sha256",
    "evaluate_operational_policy",
    "issue_operational_autonomy_certificate",
    "load_operational_policy",
    "prepare_operational_policy_replay",
    "verify_operational_policy_report",
]
