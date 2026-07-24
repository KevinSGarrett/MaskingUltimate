from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from maskfactory.autonomy.serverless_overflow import (
    OverflowBroker,
    OverflowConfig,
    OverflowError,
)

COMFY_SESSION = "019f9200-4805-7632-83d3-ee9ae614c603"
MASK_SESSION = "019f91d1-ea20-7d81-83ff-03d393eaa1f5"


def config(tmp_path: Path) -> OverflowConfig:
    document = yaml.safe_load(
        Path("configs/runpod_serverless_overflow.yaml").read_text(encoding="utf-8")
    )
    document["runpod"]["endpoints"] = {
        "comfyui": "endpoint-comfy",
        "maskfactory": "endpoint-mask",
    }
    document["durability"]["runpod_root"] = str(tmp_path)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return OverflowConfig.load(path)


def test_config_binds_exact_sessions_volume_region_and_budget() -> None:
    document = yaml.safe_load(
        Path("configs/runpod_serverless_overflow.yaml").read_text(encoding="utf-8")
    )
    assert set(document["sessions"]) == {COMFY_SESSION, MASK_SESSION}
    assert document["sessions"][COMFY_SESSION]["profile"] == "comfyui"
    assert document["sessions"][MASK_SESSION]["profile"] == "maskfactory"
    assert document["runpod"]["network_volume_id"] == "o9qv2ld91c"
    assert document["runpod"]["datacenter_id"] == "US-WA-1"
    assert document["runpod"]["workers_min"] == 0
    assert document["runpod"]["workers_max"] == 1
    assert document["budget"]["hard_daily_limit_usd"] == 13.0
    assert document["budget"]["rolling_hour_hard_limit_usd"] == 0.54
    assert (
        document["budget"]["admission_limit_usd"]
        + document["budget"]["provider_variance_reserve_usd"]
        == 13.0
    )
    assert (
        document["budget"]["rolling_hour_admission_limit_usd"]
        + document["budget"]["rolling_hour_variance_reserve_usd"]
        == 0.54
    )


def test_shared_global_inflight_lock_applies_across_profiles(tmp_path: Path) -> None:
    broker = OverflowBroker(config(tmp_path), root=tmp_path, clock=lambda: 1_800_000_000)
    first = broker.reserve(
        session_id=COMFY_SESSION,
        profile="comfyui",
        payload={"workflow": {"1": {"class_type": "LoadImage"}}},
        requested_seconds=60,
    )
    assert first["state"] == "reserved"
    assert first["reserved_usd"] == pytest.approx((634 + 300 + 5) * 0.00053)
    with pytest.raises(OverflowError, match="already has an in-flight job"):
        broker.reserve(
            session_id=MASK_SESSION,
            profile="maskfactory",
            payload={"argv": ["/workspace/maskfactory/tools/example.py"]},
            requested_seconds=60,
        )


def test_session_cannot_cross_route_to_other_profile(tmp_path: Path) -> None:
    broker = OverflowBroker(config(tmp_path), root=tmp_path)
    with pytest.raises(OverflowError, match="session/profile binding mismatch"):
        broker.reserve(
            session_id=COMFY_SESSION,
            profile="maskfactory",
            payload={"argv": ["forbidden"]},
            requested_seconds=60,
        )


def test_budget_reservation_fails_before_daily_limit(tmp_path: Path) -> None:
    broker = OverflowBroker(config(tmp_path), root=tmp_path)
    with pytest.raises(OverflowError, match="daily Serverless admission limit"):
        broker.reserve(
            session_id=COMFY_SESSION,
            profile="comfyui",
            payload={"workflow": {"test": True}},
            requested_seconds=634,
            observed_provider_spend_usd=11.1,
        )


def test_budget_reservation_fails_before_rolling_hour_limit(tmp_path: Path) -> None:
    broker = OverflowBroker(config(tmp_path), root=tmp_path)
    with pytest.raises(OverflowError, match="rolling hourly Serverless admission limit"):
        broker.reserve(
            session_id=COMFY_SESSION,
            profile="comfyui",
            payload={"workflow": {"test": True}},
            requested_seconds=60,
            observed_provider_hour_spend_usd=0.40,
        )


def test_payload_is_hash_bound_between_reserve_and_submit(tmp_path: Path) -> None:
    broker = OverflowBroker(config(tmp_path), root=tmp_path)
    payload = {"workflow": {"test": True}}
    row = broker.reserve(
        session_id=COMFY_SESSION,
        profile="comfyui",
        payload=payload,
        requested_seconds=60,
    )

    class Client:
        def submit(self, endpoint_id, value):  # pragma: no cover - must not be reached
            raise AssertionError((endpoint_id, value))

    with pytest.raises(OverflowError, match="payload changed"):
        broker.submit_reserved(row["job_id"], {"workflow": {"test": False}}, Client())


def test_successful_submission_and_reconciliation_release_global_slot(tmp_path: Path) -> None:
    broker = OverflowBroker(config(tmp_path), root=tmp_path)
    payload = {"workflow": {"test": True}}
    row = broker.reserve(
        session_id=COMFY_SESSION,
        profile="comfyui",
        payload=payload,
        requested_seconds=60,
    )

    class Client:
        def submit(self, endpoint_id, value):
            assert endpoint_id == "endpoint-comfy"
            assert value == payload
            return {"id": "provider-job-1", "status": "IN_QUEUE"}

        def status(self, endpoint_id, provider_job_id):
            assert endpoint_id == "endpoint-comfy"
            assert provider_job_id == "provider-job-1"
            return {"id": provider_job_id, "status": "COMPLETED", "executionTime": 1000}

    submitted = broker.submit_reserved(row["job_id"], payload, Client())
    assert submitted["state"] == "submitted"
    completed = broker.reconcile(row["job_id"], Client())
    assert completed["state"] == "completed"
    assert completed["actual_usd"] == pytest.approx((1 + 300 + 5) * 0.00053)
    report = broker.report()
    assert report["active_jobs"] == 0
    assert json.loads(completed["provider_status_json"])["status"] == "COMPLETED"


def test_maskfactory_reservation_uses_handler_enforced_request_timeout(tmp_path: Path) -> None:
    broker = OverflowBroker(config(tmp_path), root=tmp_path)
    row = broker.reserve(
        session_id=MASK_SESSION,
        profile="maskfactory",
        payload={"argv": ["/workspace/maskfactory/tools/example.py"]},
        requested_seconds=60,
    )
    assert row["reserved_usd"] == pytest.approx((60 + 300 + 5) * 0.00053)


def test_cancelled_job_releases_global_and_budget_reservations(tmp_path: Path) -> None:
    broker = OverflowBroker(config(tmp_path), root=tmp_path)
    payload = {"workflow": {"test": True}}
    row = broker.reserve(
        session_id=COMFY_SESSION,
        profile="comfyui",
        payload=payload,
        requested_seconds=60,
    )

    class Client:
        def submit(self, endpoint_id, value):
            return {"id": "provider-job-cancel", "status": "IN_QUEUE"}

        def cancel(self, endpoint_id, provider_job_id):
            return {"id": provider_job_id, "status": "CANCELLED"}

    broker.submit_reserved(row["job_id"], payload, Client())
    cancelled = broker.cancel(row["job_id"], Client())
    assert cancelled["state"] == "cancelled"
    assert broker.report()["active_jobs"] == 0
    replacement = broker.reserve(
        session_id=MASK_SESSION,
        profile="maskfactory",
        payload={"argv": ["/workspace/maskfactory/tools/example.py"]},
        requested_seconds=60,
    )
    assert replacement["state"] == "reserved"
