"""Typed closed response contracts for Mode B localhost client calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ERROR_INVALID_REQUEST = "INVALID_REQUEST"
ERROR_SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
ERROR_DEADLINE_EXPIRED = "DEADLINE_EXPIRED"
ERROR_TIMEOUT = "TIMEOUT"
ERROR_MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
ERROR_UNSUPPORTED_LABEL = "UNSUPPORTED_LABEL"
ERROR_AUTHORITY_FLOOR_VIOLATION = "AUTHORITY_FLOOR_VIOLATION"

CLIENT_ERROR_CODES = frozenset(
    {
        ERROR_INVALID_REQUEST,
        ERROR_SERVICE_UNAVAILABLE,
        ERROR_DEADLINE_EXPIRED,
        ERROR_TIMEOUT,
        ERROR_MALFORMED_RESPONSE,
        ERROR_UNSUPPORTED_LABEL,
        ERROR_AUTHORITY_FLOOR_VIOLATION,
    }
)

CLIENT_ACTIONS = frozenset({"health", "capability", "predict", "refine"})


@dataclass(frozen=True)
class TransportRequest:
    method: str
    path: str
    timeout_seconds: float
    headers: dict[str, str]
    body: bytes | None = None


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    body: bytes
    headers: dict[str, str]


@dataclass(frozen=True)
class ClientError:
    code: str
    message: str
    retryable: bool
    http_status: int | None = None
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.code not in CLIENT_ERROR_CODES:
            raise ValueError(f"unsupported client error code: {self.code}")
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("client error message must be non-empty")
