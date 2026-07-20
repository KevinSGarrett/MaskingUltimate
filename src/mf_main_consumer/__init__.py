"""Isolated Comfy_UI_Main-side MaskFactory bridge consumer.

Emits real, non-fixture, isolated_main_consumer adoption/adapter/journal/circuit/
qualification evidence for MaskFactory MF-P6-11 / MF-P6-12 by importing and calling
the producer bridge contracts from the sibling C:\\Comfy_UI_Main_Masking checkout.

Honesty ceiling (binding): authority_kind == isolated_main_consumer. This is NOT
the real Comfy_UI_Main runtime; it never claims real Main adoption and never
closes HARD blockers MF-P6-11.02 / 11.07 / 12.05 / 12.06.
"""

from __future__ import annotations

# Make ``maskfactory`` importable from the sibling producer repo before any
# submodule that depends on it is imported.
from .producer_bridge import ensure_producer_importable

ensure_producer_importable()

__all__ = ["ensure_producer_importable"]
__version__ = "1.0.0"
