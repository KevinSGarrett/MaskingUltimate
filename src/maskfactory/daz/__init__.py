"""Optional, default-disabled DAZ exact-synthetic supervision lane."""

from .policy import (
    DazPolicyError,
    daz_foundation_doctor,
    inspect_acquisition_queue,
    validate_daz_configuration,
    validate_synthetic_authority,
    validate_synthetic_share,
)

__all__ = [
    "DazPolicyError",
    "daz_foundation_doctor",
    "inspect_acquisition_queue",
    "validate_daz_configuration",
    "validate_synthetic_authority",
    "validate_synthetic_share",
]
