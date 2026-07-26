from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import yaml

from maskfactory.autonomy.serverless_overflow import OverflowBroker, OverflowConfig, OverflowError


PROJECT_ROOT = Path(__file__).parents[1]
MANAGER_PATH = PROJECT_ROOT / "tools" / "manage_runpod_serverless_overflow.py"
MASK_SESSION = "019f91d1-ea20-7d81-83ff-03d393eaa1f5"


def _manager_module():
    spec = importlib.util.spec_from_file_location("serverless_manager", MANAGER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config(tmp_path: Path) -> OverflowConfig:
    document = yaml.safe_load(
        (PROJECT_ROOT / "configs" / "runpod_serverless_overflow.yaml").read_text(
            encoding="utf-8"
        )
    )
    document["durability"]["runpod_root"] = str(tmp_path / "broker")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return OverflowConfig.load(config_path)


def test_canonical_manager_is_installed_and_can_make_a_decision(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(MANAGER_PATH),
            "--config",
            str(PROJECT_ROOT / "configs" / "runpod_serverless_overflow.yaml"),
            "--root",
            str(tmp_path / "broker"),
            "decide",
            "--session-id",
            MASK_SESSION,
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    decision = json.loads(result.stdout)
    assert decision["session_id"] == MASK_SESSION
    assert decision["profile"] == "maskfactory"
    assert decision["route"] in {"local_pod", "serverless_overflow"}


def test_billing_403_uses_terminal_ledger_spend_without_relaxing_admission(
    tmp_path: Path,
) -> None:
    manager = _manager_module()
    config = _config(tmp_path)
    broker = OverflowBroker(config, root=tmp_path / "broker")

    class BillingForbidden:
        def daily_endpoint_spend(self, _endpoint_ids):
            raise OverflowError("RunPod billing HTTP 403")

        def rolling_hour_endpoint_spend(self, _endpoint_ids):
            raise OverflowError("RunPod billing HTTP 403")

    daily, hourly, source = manager._provider_spend_observation(
        broker=broker,
        config=config,
        client=BillingForbidden(),
        observed_daily=None,
        observed_hourly=None,
    )

    assert (daily, hourly, source) == (0.0, 0.0, "ledger_fallback")
