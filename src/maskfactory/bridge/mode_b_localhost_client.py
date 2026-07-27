"""Mode B localhost health/capability/predict/refine client.

This client is additive to the existing runtime API and wraps all calls in
typed, closed response envelopes. Raw service outputs are never promotion-
eligible and are fail-closed to draft-only authority.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import socket
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .runtime_client_types import (
    CLIENT_ACTIONS,
    ERROR_AUTHORITY_FLOOR_VIOLATION,
    ERROR_DEADLINE_EXPIRED,
    ERROR_INVALID_REQUEST,
    ERROR_MALFORMED_RESPONSE,
    ERROR_SERVICE_UNAVAILABLE,
    ERROR_TIMEOUT,
    ERROR_UNSUPPORTED_LABEL,
    ClientError,
    TransportRequest,
    TransportResponse,
)

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "mode_b_localhost_client_response.schema.json"
)
_AUTHORITY_FLOOR_REASON = "raw_mode_b_outputs_are_draft_only"
_RESPONSE_VERSION = "1.0.0"
_RECORD_TYPE = "mode_b_localhost_client_response"
_RAW_DRAFT_STATUS = "draft_model_generated"


class ModeBLocalhostClient:
    """Fail-closed localhost client for Mode B endpoints."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8765",
        default_timeout_seconds: float = 30.0,
        transport: Callable[[TransportRequest], TransportResponse] | None = None,
    ) -> None:
        fixed = base_url.rstrip("/")
        if fixed not in {"http://127.0.0.1:8765", "http://localhost:8765"}:
            raise ValueError("Mode B client is fixed to localhost:8765")
        if not isinstance(default_timeout_seconds, (int, float)) or default_timeout_seconds <= 0:
            raise ValueError("default timeout must be positive")
        self.base_url = fixed
        self.default_timeout_seconds = float(default_timeout_seconds)
        self._transport = transport or self._urllib_transport
        self._validator = Draft202012Validator(json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")))

    def health(self, *, deadline_at: str | None = None) -> dict[str, Any]:
        started = dt.datetime.now(dt.UTC)
        outcome = self._request_json(
            action="health",
            method="GET",
            path="/health",
            deadline_at=deadline_at,
        )
        if outcome["kind"] == "error":
            return self._error_response("health", started, deadline_at, outcome["error"])
        body = outcome["body"]
        if not isinstance(body, Mapping):
            return self._error_response(
                "health",
                started,
                deadline_at,
                ClientError(
                    code=ERROR_MALFORMED_RESPONSE,
                    message="health response must be an object",
                    retryable=False,
                    http_status=outcome["status_code"],
                ),
            )
        versions = body.get("versions")
        if not isinstance(versions, Mapping) or not isinstance(versions.get("mode_b_api"), str):
            return self._error_response(
                "health",
                started,
                deadline_at,
                ClientError(
                    code=ERROR_MALFORMED_RESPONSE,
                    message="health response is missing versions.mode_b_api",
                    retryable=False,
                    http_status=outcome["status_code"],
                ),
            )
        response = self._ok_response(
            action="health",
            started_at=started,
            deadline_at=deadline_at,
            request_sha256=None,
            result={
                "raw_response_sha256": _canonical_sha256(body),
                "raw_status": str(body.get("status")),
                "mode_b_api_version": str(versions["mode_b_api"]),
            },
        )
        return self._validate_response(response)

    def capability(self, *, deadline_at: str | None = None) -> dict[str, Any]:
        started = dt.datetime.now(dt.UTC)
        outcome = self._request_json(
            action="capability",
            method="GET",
            path="/models",
            deadline_at=deadline_at,
        )
        if outcome["kind"] == "error":
            return self._error_response("capability", started, deadline_at, outcome["error"])
        body = outcome["body"]
        if not isinstance(body, Mapping):
            return self._error_response(
                "capability",
                started,
                deadline_at,
                ClientError(
                    code=ERROR_MALFORMED_RESPONSE,
                    message="capability response must be an object",
                    retryable=False,
                    http_status=outcome["status_code"],
                ),
            )
        models = body.get("models")
        if not isinstance(models, list):
            return self._error_response(
                "capability",
                started,
                deadline_at,
                ClientError(
                    code=ERROR_MALFORMED_RESPONSE,
                    message="capability response is missing models[]",
                    retryable=False,
                    http_status=outcome["status_code"],
                ),
            )
        response = self._ok_response(
            action="capability",
            started_at=started,
            deadline_at=deadline_at,
            request_sha256=None,
            result={
                "raw_response_sha256": _canonical_sha256(body),
                "raw_status": "ok",
                "model_count": len(models),
            },
        )
        return self._validate_response(response)

    def predict(
        self,
        *,
        request_document: Mapping[str, Any],
        image_bytes: bytes,
        deadline_at: str | None = None,
    ) -> dict[str, Any]:
        started = dt.datetime.now(dt.UTC)
        request_error = self._validate_mode_b_request(
            request_document, expected_access_mode="mode_b_live_predict"
        )
        if request_error is not None:
            return self._error_response("predict", started, deadline_at, request_error)
        try:
            labels = _labels_from_request(request_document)
        except ValueError as exc:
            return self._error_response(
                "predict",
                started,
                deadline_at,
                ClientError(code=ERROR_INVALID_REQUEST, message=str(exc), retryable=False),
            )
        form = {
            "labels": ",".join(labels),
            "return_mode": "binaries",
            "inpaint": "null",
        }
        outcome = self._request_json(
            action="predict",
            method="POST",
            path="/predict",
            deadline_at=deadline_at,
            multipart=(form, {"image": image_bytes}),
        )
        request_sha = _canonical_sha256(dict(request_document))
        if outcome["kind"] == "error":
            return self._error_response(
                "predict", started, deadline_at, outcome["error"], request_sha
            )
        body = outcome["body"]
        validation_error = self._validate_predict_response(body)
        if validation_error is not None:
            return self._error_response(
                "predict", started, deadline_at, validation_error, request_sha
            )
        if str(body.get("status")) != _RAW_DRAFT_STATUS:
            return self._error_response(
                "predict",
                started,
                deadline_at,
                ClientError(
                    code=ERROR_AUTHORITY_FLOOR_VIOLATION,
                    message="raw predict status is not draft-only",
                    retryable=False,
                    http_status=outcome["status_code"],
                ),
                request_sha,
            )
        response = self._ok_response(
            action="predict",
            started_at=started,
            deadline_at=deadline_at,
            request_sha256=request_sha,
            result={
                "raw_response_sha256": _canonical_sha256(body),
                "raw_status": str(body["status"]),
                "label_count": len(body["labels"]),
                "width": int(body["width"]),
                "height": int(body["height"]),
            },
        )
        return self._validate_response(response)

    def refine(
        self,
        *,
        request_document: Mapping[str, Any],
        image_bytes: bytes,
        deadline_at: str | None = None,
    ) -> dict[str, Any]:
        started = dt.datetime.now(dt.UTC)
        request_error = self._validate_mode_b_request(
            request_document, expected_access_mode="mode_b_live_refine"
        )
        if request_error is not None:
            return self._error_response("refine", started, deadline_at, request_error)
        payload = request_document.get("mode_payload")
        label = str((payload or {}).get("prior_mask", {}).get("label") or "")
        if not label:
            return self._error_response(
                "refine",
                started,
                deadline_at,
                ClientError(
                    code=ERROR_INVALID_REQUEST,
                    message="refine request is missing mode_payload.prior_mask.label",
                    retryable=False,
                ),
            )
        clicks_payload = []
        for key, polarity in (("positive_clicks", 1), ("negative_clicks", 0)):
            points = payload.get(key) if isinstance(payload, Mapping) else None
            if not isinstance(points, list):
                return self._error_response(
                    "refine",
                    started,
                    deadline_at,
                    ClientError(
                        code=ERROR_INVALID_REQUEST,
                        message=f"refine request {key} must be a list",
                        retryable=False,
                    ),
                )
            for point in points:
                if not isinstance(point, Mapping):
                    return self._error_response(
                        "refine",
                        started,
                        deadline_at,
                        ClientError(
                            code=ERROR_INVALID_REQUEST,
                            message=f"refine request {key} contains malformed point",
                            retryable=False,
                        ),
                    )
                clicks_payload.append(
                    {
                        "x": int(point.get("x", -1)),
                        "y": int(point.get("y", -1)),
                        "is_positive": polarity,
                    }
                )
        outcome = self._request_json(
            action="refine",
            method="POST",
            path="/refine",
            deadline_at=deadline_at,
            multipart=(
                {"label": label, "clicks": json.dumps(clicks_payload, separators=(",", ":"))},
                {"image": image_bytes},
            ),
        )
        request_sha = _canonical_sha256(dict(request_document))
        if outcome["kind"] == "error":
            return self._error_response(
                "refine", started, deadline_at, outcome["error"], request_sha
            )
        body = outcome["body"]
        validation_error = self._validate_refine_response(body)
        if validation_error is not None:
            return self._error_response(
                "refine", started, deadline_at, validation_error, request_sha
            )
        if str(body.get("status")) != _RAW_DRAFT_STATUS:
            return self._error_response(
                "refine",
                started,
                deadline_at,
                ClientError(
                    code=ERROR_AUTHORITY_FLOOR_VIOLATION,
                    message="raw refine status is not draft-only",
                    retryable=False,
                    http_status=outcome["status_code"],
                ),
                request_sha,
            )
        response = self._ok_response(
            action="refine",
            started_at=started,
            deadline_at=deadline_at,
            request_sha256=request_sha,
            result={
                "raw_response_sha256": _canonical_sha256(body),
                "raw_status": str(body["status"]),
                "label": str(body["label"]),
                "area_px": int(body["area_px"]),
            },
        )
        return self._validate_response(response)

    def _validate_mode_b_request(
        self, request_document: Mapping[str, Any], *, expected_access_mode: str
    ) -> ClientError | None:
        if not isinstance(request_document, Mapping):
            return ClientError(
                code=ERROR_INVALID_REQUEST,
                message="request document must be a mapping",
                retryable=False,
            )
        if request_document.get("record_type") != "mask_acquisition_request":
            return ClientError(
                code=ERROR_INVALID_REQUEST,
                message="request record_type must be mask_acquisition_request",
                retryable=False,
            )
        if request_document.get("access_mode") != expected_access_mode:
            return ClientError(
                code=ERROR_INVALID_REQUEST,
                message=f"request access_mode must be {expected_access_mode}",
                retryable=False,
            )
        payload = request_document.get("mode_payload")
        expected_payload = expected_access_mode
        if not isinstance(payload, Mapping) or payload.get("payload_type") != expected_payload:
            return ClientError(
                code=ERROR_INVALID_REQUEST,
                message=f"request mode_payload.payload_type must be {expected_payload}",
                retryable=False,
            )
        return None

    def _validate_predict_response(self, body: object) -> ClientError | None:
        if not isinstance(body, Mapping):
            return ClientError(
                code=ERROR_MALFORMED_RESPONSE,
                message="predict response must be an object",
                retryable=False,
            )
        required = {"status", "labels", "masks", "width", "height"}
        if not required.issubset(set(body)):
            return ClientError(
                code=ERROR_MALFORMED_RESPONSE,
                message="predict response is missing required fields",
                retryable=False,
            )
        labels = body.get("labels")
        if (
            not isinstance(labels, list)
            or not labels
            or not all(isinstance(x, str) for x in labels)
        ):
            return ClientError(
                code=ERROR_MALFORMED_RESPONSE,
                message="predict response labels must be non-empty strings",
                retryable=False,
            )
        masks = body.get("masks")
        if not isinstance(masks, Mapping) or set(masks) != set(labels):
            return ClientError(
                code=ERROR_MALFORMED_RESPONSE,
                message="predict response masks must match labels exactly",
                retryable=False,
            )
        width, height = body.get("width"), body.get("height")
        if any(not isinstance(value, int) or value <= 0 for value in (width, height)):
            return ClientError(
                code=ERROR_MALFORMED_RESPONSE,
                message="predict width and height must be positive integers",
                retryable=False,
            )
        return None

    def _validate_refine_response(self, body: object) -> ClientError | None:
        if not isinstance(body, Mapping):
            return ClientError(
                code=ERROR_MALFORMED_RESPONSE,
                message="refine response must be an object",
                retryable=False,
            )
        required = {"status", "label", "mask", "area_px"}
        if not required.issubset(set(body)):
            return ClientError(
                code=ERROR_MALFORMED_RESPONSE,
                message="refine response is missing required fields",
                retryable=False,
            )
        if not isinstance(body.get("label"), str) or not body["label"]:
            return ClientError(
                code=ERROR_MALFORMED_RESPONSE,
                message="refine response label must be non-empty",
                retryable=False,
            )
        if not isinstance(body.get("mask"), str) or not body["mask"]:
            return ClientError(
                code=ERROR_MALFORMED_RESPONSE,
                message="refine response mask must be base64 data",
                retryable=False,
            )
        if not isinstance(body.get("area_px"), int) or body["area_px"] < 0:
            return ClientError(
                code=ERROR_MALFORMED_RESPONSE,
                message="refine response area_px must be >= 0",
                retryable=False,
            )
        return None

    def _request_json(
        self,
        *,
        action: str,
        method: str,
        path: str,
        deadline_at: str | None,
        multipart: tuple[Mapping[str, str], Mapping[str, bytes]] | None = None,
    ) -> dict[str, Any]:
        timeout_or_error = _resolve_timeout_seconds(
            deadline_at=deadline_at, default_timeout_seconds=self.default_timeout_seconds
        )
        if isinstance(timeout_or_error, ClientError):
            return {"kind": "error", "error": timeout_or_error}
        timeout = timeout_or_error
        headers = {"Accept": "application/json"}
        body = None
        if multipart is not None:
            body, multipart_headers = _encode_multipart(multipart[0], multipart[1])
            headers.update(multipart_headers)
        request = TransportRequest(
            method=method, path=path, timeout_seconds=timeout, headers=headers, body=body
        )
        try:
            response = self._transport(request)
        except TimeoutError:
            return {
                "kind": "error",
                "error": ClientError(
                    code=ERROR_TIMEOUT,
                    message=f"{action} request timed out",
                    retryable=True,
                ),
            }
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            if isinstance(getattr(exc, "reason", None), TimeoutError) or isinstance(
                getattr(exc, "reason", None), socket.timeout
            ):
                return {
                    "kind": "error",
                    "error": ClientError(
                        code=ERROR_TIMEOUT,
                        message=f"{action} request timed out",
                        retryable=True,
                    ),
                }
            return {
                "kind": "error",
                "error": ClientError(
                    code=ERROR_SERVICE_UNAVAILABLE,
                    message=f"{action} request unavailable: {exc}",
                    retryable=True,
                ),
            }
        if response.status_code >= 500:
            detail = _safe_json_detail(response.body)
            code = (
                ERROR_UNSUPPORTED_LABEL
                if "unknown ontology label requested" in detail
                else ERROR_SERVICE_UNAVAILABLE
            )
            return {
                "kind": "error",
                "error": ClientError(
                    code=code,
                    message=detail or f"{action} endpoint returned HTTP {response.status_code}",
                    retryable=code != ERROR_UNSUPPORTED_LABEL,
                    http_status=response.status_code,
                ),
            }
        try:
            body_json = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {
                "kind": "error",
                "error": ClientError(
                    code=ERROR_MALFORMED_RESPONSE,
                    message=f"{action} endpoint did not return valid JSON",
                    retryable=False,
                    http_status=response.status_code,
                ),
            }
        return {"kind": "ok", "body": body_json, "status_code": response.status_code}

    def _ok_response(
        self,
        *,
        action: str,
        started_at: dt.datetime,
        deadline_at: str | None,
        request_sha256: str | None,
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        if action not in CLIENT_ACTIONS:
            raise ValueError(f"unsupported action: {action}")
        completed_at = dt.datetime.now(dt.UTC)
        payload = {
            "schema_version": _RESPONSE_VERSION,
            "record_type": _RECORD_TYPE,
            "action": action,
            "status": "ok",
            "request_sha256": request_sha256,
            "deadline_at": deadline_at,
            "timing": _timing(started_at, completed_at),
            "authority_floor": {
                "operational_authority_state": "draft",
                "promotion_eligible": False,
                "reason": _AUTHORITY_FLOOR_REASON,
            },
            "result": dict(result),
            "error": None,
        }
        return payload

    def _error_response(
        self,
        action: str,
        started_at: dt.datetime,
        deadline_at: str | None,
        error: ClientError,
        request_sha256: str | None = None,
    ) -> dict[str, Any]:
        if action not in CLIENT_ACTIONS:
            raise ValueError(f"unsupported action: {action}")
        completed_at = dt.datetime.now(dt.UTC)
        payload = {
            "schema_version": _RESPONSE_VERSION,
            "record_type": _RECORD_TYPE,
            "action": action,
            "status": "error",
            "request_sha256": request_sha256,
            "deadline_at": deadline_at,
            "timing": _timing(started_at, completed_at),
            "authority_floor": {
                "operational_authority_state": "draft",
                "promotion_eligible": False,
                "reason": _AUTHORITY_FLOOR_REASON,
            },
            "result": None,
            "error": {
                "code": error.code,
                "message": error.message,
                "retryable": error.retryable,
                "http_status": error.http_status,
                "details": error.details or {},
            },
        }
        return self._validate_response(payload)

    def _validate_response(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        errors = sorted(self._validator.iter_errors(payload), key=lambda err: list(err.path))
        if errors:
            first = errors[0]
            pointer = "/" + "/".join(str(part) for part in first.path)
            raise ValueError(
                f"mode-b localhost client response failed schema: {pointer} {first.message}"
            )
        return dict(payload)

    def _urllib_transport(self, request: TransportRequest) -> TransportResponse:
        url = f"{self.base_url}{request.path}"
        call = urllib.request.Request(
            url,
            data=request.body,
            headers=request.headers,
            method=request.method,
        )
        try:
            with urllib.request.urlopen(call, timeout=request.timeout_seconds) as response:
                return TransportResponse(
                    status_code=int(getattr(response, "status", 200)),
                    body=response.read(),
                    headers={key: value for key, value in response.headers.items()},
                )
        except urllib.error.HTTPError as exc:
            return TransportResponse(
                status_code=int(exc.code),
                body=exc.read(),
                headers=dict(exc.headers.items()),
            )


def _canonical_sha256(document: Mapping[str, Any]) -> str:
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _labels_from_request(request_document: Mapping[str, Any]) -> tuple[str, ...]:
    intents = request_document.get("mask_intents")
    if not isinstance(intents, list):
        raise ValueError("request.mask_intents must be a list")
    labels: list[str] = []
    for row in intents:
        if not isinstance(row, Mapping) or not isinstance(row.get("label"), str):
            raise ValueError("request.mask_intents entries must contain label")
        labels.append(row["label"])
    if not labels:
        raise ValueError("request must include at least one mask intent")
    if len(labels) != len(set(labels)):
        raise ValueError("request labels must be unique")
    return tuple(labels)


def _resolve_timeout_seconds(
    *, deadline_at: str | None, default_timeout_seconds: float
) -> float | ClientError:
    if deadline_at is None:
        return default_timeout_seconds
    try:
        deadline = dt.datetime.fromisoformat(deadline_at.replace("Z", "+00:00"))
    except ValueError:
        return ClientError(
            code=ERROR_INVALID_REQUEST,
            message="deadline_at must be RFC3339",
            retryable=False,
        )
    now = dt.datetime.now(dt.timezone.utc)
    remaining = (deadline - now).total_seconds()
    if remaining <= 0:
        return ClientError(
            code=ERROR_DEADLINE_EXPIRED,
            message="deadline already expired before request execution",
            retryable=False,
        )
    return max(0.001, min(default_timeout_seconds, remaining))


def _encode_multipart(
    fields: Mapping[str, str], files: Mapping[str, bytes]
) -> tuple[bytes, dict[str, str]]:
    boundary = f"maskfactory-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("ascii"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{key}"\r\n'
                "Content-Type: text/plain; charset=utf-8\r\n\r\n"
                f"{value}\r\n"
            ).encode("utf-8")
        )
    for key, raw in files.items():
        chunks.append(f"--{boundary}\r\n".encode("ascii"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{key}"; filename="{key}.bin"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(bytes(raw))
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    payload = b"".join(chunks)
    return payload, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def _safe_json_detail(raw: bytes) -> str:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(parsed, Mapping):
        return ""
    detail = parsed.get("detail")
    return str(detail) if isinstance(detail, str) else ""


def _timing(started_at: dt.datetime, completed_at: dt.datetime) -> dict[str, Any]:
    elapsed = (completed_at - started_at).total_seconds() * 1000
    return {
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "elapsed_ms": max(0, int(round(elapsed))),
    }


__all__ = [
    "ModeBLocalhostClient",
    "TransportRequest",
    "TransportResponse",
    "ClientError",
]
