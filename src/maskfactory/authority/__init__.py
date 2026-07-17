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

__all__ = [
    "CompleteMapHardVetoError",
    "OperationalCertificateIssuanceError",
    "bind_complete_map_report",
    "build_complete_map_hard_veto_report",
    "canonical_decoded_raster_sha256",
    "complete_map_hard_veto_report_sha256",
    "issue_operational_autonomy_certificate",
]
