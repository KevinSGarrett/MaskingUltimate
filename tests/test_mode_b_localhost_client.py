from __future__ import annotations

import datetime as dt
import json
from collections import deque
from collections.abc import Callable
from typing import Any

from maskfactory.bridge.mode_b_localhost_client import ModeBLocalhostClient
from maskfactory.bridge.runtime_client_types import (
    ERROR_AUTHORITY_FLOOR_VIOLATION,
    ERROR_DEADLINE_EXPIRED,
    ERROR_MALFORMED_RESPONSE,
    ERROR_SERVICE_UNAVAILABLE,
    ERROR_TIMEOUT,
    ERROR_UNSUPPORTED_LABEL,
    TransportRequest,
    TransportResponse,
)


def _predict_request(*, label: str = "left_hand") -> dict[str, Any]:
    return {
        "record_type": "mask_acquisition_request",
        "request_id": "request-1",
        "access_mode": "mode_b_live_predict",
        "mode_payload": {"payload_type": "mode_b_live_predict"},
        "mask_intents": [{"label": label}],
    }


def _refine_request(*, label: str = "left_hand") -> dict[str, Any]:
    return {
        "record_type": "mask_acquisition_request",
        "request_id": "request-2",
        "access_mode": "mode_b_live_refine",
        "mode_payload": {
            "payload_type": "mode_b_live_refine",
            "prior_mask": {"label": label},
            "positive_clicks": [{"x": 1, "y": 1}],
            "negative_clicks": [],
        },
    }


def _fake_transport(
    queue: deque[TransportResponse | Exception],
    seen: list[TransportRequest],
) -> Callable[[TransportRequest], TransportResponse]:
    def _transport(request: TransportRequest) -> TransportResponse:
        seen.append(request)
        outcome = queue.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return _transport


def _json_response(status_code: int, document: dict[str, Any]) -> TransportResponse:
    return TransportResponse(
        status_code=status_code,
        body=json.dumps(document).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def test_health_and_capability_return_closed_ok_responses() -> None:
    queue = deque(
        [
            _json_response(
                200,
                {"status": "ok", "versions": {"mode_b_api": "1.0.0"}, "pipeline_version": "1.0.0"},
            ),
            _json_response(200, {"models": [{"key": "champion_bodypart"}], "champions": {}}),
        ]
    )
    seen: list[TransportRequest] = []
    client = ModeBLocalhostClient(transport=_fake_transport(queue, seen))

    health = client.health()
    capability = client.capability()

    assert health["status"] == "ok"
    assert health["action"] == "health"
    assert health["authority_floor"]["operational_authority_state"] == "draft"
    assert capability["status"] == "ok"
    assert capability["action"] == "capability"
    assert capability["result"]["model_count"] == 1
    assert [request.path for request in seen] == ["/health", "/models"]


def test_predict_computes_request_hash_and_enforces_draft_floor() -> None:
    queue = deque(
        [
            _json_response(
                200,
                {
                    "status": "draft_model_generated",
                    "labels": ["left_hand"],
                    "masks": {"left_hand": "ZmFrZQ=="},
                    "width": 32,
                    "height": 32,
                },
            )
        ]
    )
    seen: list[TransportRequest] = []
    client = ModeBLocalhostClient(transport=_fake_transport(queue, seen))

    response = client.predict(request_document=_predict_request(), image_bytes=b"png")

    assert response["status"] == "ok"
    assert response["action"] == "predict"
    assert response["request_sha256"] is not None
    assert response["authority_floor"]["promotion_eligible"] is False
    assert response["result"]["raw_status"] == "draft_model_generated"
    assert seen[0].path == "/predict"


def test_predict_rejects_unsupported_label_with_typed_error() -> None:
    queue = deque([_json_response(503, {"detail": "unknown ontology label requested: fake_label"})])
    client = ModeBLocalhostClient(transport=_fake_transport(queue, []))

    response = client.predict(
        request_document=_predict_request(label="fake_label"), image_bytes=b"png"
    )

    assert response["status"] == "error"
    assert response["error"]["code"] == ERROR_UNSUPPORTED_LABEL
    assert response["error"]["retryable"] is False


def test_unavailable_timeout_and_deadline_paths_are_typed() -> None:
    unavailable_client = ModeBLocalhostClient(
        transport=_fake_transport(deque([ConnectionError("down")]), [])
    )
    unavailable = unavailable_client.health()
    assert unavailable["status"] == "error"
    assert unavailable["error"]["code"] == ERROR_SERVICE_UNAVAILABLE

    timeout_client = ModeBLocalhostClient(
        transport=_fake_transport(deque([TimeoutError("late")]), [])
    )
    timeout = timeout_client.capability()
    assert timeout["status"] == "error"
    assert timeout["error"]["code"] == ERROR_TIMEOUT

    never_called: list[TransportRequest] = []
    deadline_client = ModeBLocalhostClient(
        transport=_fake_transport(deque([_json_response(200, {"status": "ok"})]), never_called)
    )
    expired = deadline_client.health(deadline_at="2020-01-01T00:00:00Z")
    assert expired["status"] == "error"
    assert expired["error"]["code"] == ERROR_DEADLINE_EXPIRED
    assert never_called == []


def test_refine_and_predict_reject_malformed_or_promoted_raw_outputs() -> None:
    malformed_client = ModeBLocalhostClient(
        transport=_fake_transport(
            deque([_json_response(200, {"status": "draft_model_generated"})]), []
        )
    )
    malformed = malformed_client.refine(request_document=_refine_request(), image_bytes=b"png")
    assert malformed["status"] == "error"
    assert malformed["error"]["code"] == ERROR_MALFORMED_RESPONSE

    promoted_client = ModeBLocalhostClient(
        transport=_fake_transport(
            deque(
                [
                    _json_response(
                        200,
                        {
                            "status": "certified",
                            "labels": ["left_hand"],
                            "masks": {"left_hand": "ZmFrZQ=="},
                            "width": 32,
                            "height": 32,
                        },
                    )
                ]
            ),
            [],
        )
    )
    promoted = promoted_client.predict(request_document=_predict_request(), image_bytes=b"png")
    assert promoted["status"] == "error"
    assert promoted["error"]["code"] == ERROR_AUTHORITY_FLOOR_VIOLATION


def test_deadline_budgets_timeout_passed_to_transport() -> None:
    queue = deque(
        [
            _json_response(
                200,
                {
                    "status": "draft_model_generated",
                    "labels": ["left_hand"],
                    "masks": {"left_hand": "ZmFrZQ=="},
                    "width": 32,
                    "height": 32,
                },
            )
        ]
    )
    seen: list[TransportRequest] = []
    client = ModeBLocalhostClient(
        default_timeout_seconds=30,
        transport=_fake_transport(queue, seen),
    )
    deadline = (
        (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=2))
        .isoformat()
        .replace("+00:00", "Z")
    )

    response = client.predict(
        request_document=_predict_request(), image_bytes=b"png", deadline_at=deadline
    )

    assert response["status"] == "ok"
    assert 0 < seen[0].timeout_seconds <= 2.1
