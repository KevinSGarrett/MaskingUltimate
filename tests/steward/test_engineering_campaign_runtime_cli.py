from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "tools"
    / "run_engineering_campaign_runtime.py"
)
SPEC = importlib.util.spec_from_file_location(
    "engineering_campaign_runtime_cli", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_run_requires_exact_guarded_child_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "campaign"
    root.mkdir()
    campaign_id = "campaign-25"
    payload_sha256 = "a" * 64

    with pytest.raises(
        MODULE.EngineeringCampaignRuntimeError, match="GUARD_ACTIVE"
    ):
        MODULE._require_guard_context(
            campaign_root=root,
            campaign_id=campaign_id,
            payload_sha256=payload_sha256,
        )

    values = {
        "MASKFACTORY_SHARED_GPU_GUARD_ACTIVE": "1",
        "MASKFACTORY_SHARED_GPU_GUARD_JOB_ID": campaign_id,
        "MASKFACTORY_SHARED_GPU_GUARD_PAYLOAD_SHA256": payload_sha256,
        "MASKFACTORY_SHARED_GPU_GUARD_REQUEST_ID": "gpu-campaign-request",
        "MASKFACTORY_SHARED_GPU_GUARD_RECEIPT_ROOT": str(root.resolve()),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert MODULE._require_guard_context(
        campaign_root=root,
        campaign_id=campaign_id,
        payload_sha256=payload_sha256,
    ) == values

    monkeypatch.setenv(
        "MASKFACTORY_SHARED_GPU_GUARD_PAYLOAD_SHA256", "b" * 64
    )
    with pytest.raises(
        MODULE.EngineeringCampaignRuntimeError,
        match="GUARD_PAYLOAD_SHA256",
    ):
        MODULE._require_guard_context(
            campaign_root=root,
            campaign_id=campaign_id,
            payload_sha256=payload_sha256,
        )


def test_guard_context_contains_no_owner_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "campaign"
    root.mkdir()
    values = {
        "MASKFACTORY_SHARED_GPU_GUARD_ACTIVE": "1",
        "MASKFACTORY_SHARED_GPU_GUARD_JOB_ID": "campaign-25",
        "MASKFACTORY_SHARED_GPU_GUARD_PAYLOAD_SHA256": "a" * 64,
        "MASKFACTORY_SHARED_GPU_GUARD_REQUEST_ID": "gpu-campaign-request",
        "MASKFACTORY_SHARED_GPU_GUARD_RECEIPT_ROOT": str(root.resolve()),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    observed = MODULE._require_guard_context(
        campaign_root=root,
        campaign_id="campaign-25",
        payload_sha256="a" * 64,
    )
    assert all("TOKEN" not in name for name in observed)
    assert "owner" not in repr(observed).lower()
    assert os.environ.get("MASKFACTORY_SHARED_GPU_OWNER_TOKEN") is None
