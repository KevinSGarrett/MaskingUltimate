"""External proposal-provider discovery, adapters, and governance gates."""

from .probe import probe_external_sources
from .promotion import SpecialistPromotionError, validate_specialist_promotion_packet

__all__ = [
    "SpecialistPromotionError",
    "probe_external_sources",
    "validate_specialist_promotion_packet",
]
