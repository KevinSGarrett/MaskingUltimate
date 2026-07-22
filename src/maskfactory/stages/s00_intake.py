"""Stable S00 intake stage boundary (doc 07 S00, doc 01 §7)."""

from __future__ import annotations

from ..intake import (
    DecodeRejected,
    IntakeError,
    IntakeResult,
    ingest_one,
)

run_s00 = ingest_one

__all__ = [
    "DecodeRejected",
    "IntakeError",
    "IntakeResult",
    "ingest_one",
    "run_s00",
]
