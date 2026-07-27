from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

from maskfactory.autonomy.serverless_overflow import OverflowBroker, OverflowConfig, OverflowError
from maskfactory.steward.continuous_contract import canonical_sha256


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def test_execution_host_preflight_is_hash_bound_and_provider_free(tmp_path: Path) -> None:
    config = _config(tmp_path)
    broker = OverflowBroker(config, root=config.runpod_root)
    assert broker.db_path.is_file()
    config_path = tmp_path / "config.yaml"

    result = subprocess.run(
        [
            sys.executable,
            str(MANAGER_PATH),
            "--config",
            str(config_path),
            "--root",
            str(config.runpod_root),
            "preflight",
            "--session-id",
            MASK_SESSION,
            "--expected-manager-sha256",
            _sha256(MANAGER_PATH),
            "--expected-config-sha256",
            _sha256(config_path),
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["provider_calls"] is False
    assert receipt["broker_write"] is False
    assert receipt["profile"] == "maskfactory"
    assert receipt["execution_host"]["ledger_path"] == str(broker.db_path.resolve())
    assert receipt["execution_host"]["manager_sha256"] == _sha256(MANAGER_PATH)
    assert receipt["execution_host"]["config_sha256"] == _sha256(config_path)
    sealed = dict(receipt)
    sealed["receipt_sha256"] = "0" * 64
    assert receipt["receipt_sha256"] == canonical_sha256(sealed)


def test_execution_host_preflight_rejects_hash_drift_before_broker_write(tmp_path: Path) -> None:
    config = _config(tmp_path)
    broker = OverflowBroker(config, root=config.runpod_root)
    before = broker.db_path.read_bytes()
    config_path = tmp_path / "config.yaml"

    result = subprocess.run(
        [
            sys.executable,
            str(MANAGER_PATH),
            "--config",
            str(config_path),
            "--root",
            str(config.runpod_root),
            "preflight",
            "--session-id",
            MASK_SESSION,
            "--expected-manager-sha256",
            "0" * 64,
            "--expected-config-sha256",
            _sha256(config_path),
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert "preflight manager hash mismatch" in result.stderr
    assert broker.db_path.read_bytes() == before


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
