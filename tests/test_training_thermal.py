import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from maskfactory.training.thermal import (
    MaskFactoryThermalCooldownHook,
    ThermalPolicyError,
    mmengine_thermal_config,
    query_max_gpu_temperature,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_thermal_hook_polls_at_30_minutes_and_sleeps_only_above_87(tmp_path: Path) -> None:
    clock = _Clock()
    temperatures = iter((87, 87.0001))
    sleeps = []
    hook = MaskFactoryThermalCooldownHook(
        clock=clock,
        sleeper=lambda seconds: (sleeps.append(seconds), clock.advance(seconds)),
        probe=lambda: next(temperatures),
    )
    runner = SimpleNamespace(iter=99, work_dir=str(tmp_path))
    hook.after_train_iter(runner, 0)
    assert not (tmp_path / "thermal.jsonl").exists()
    clock.advance(1800)
    hook.after_train_iter(runner, 1)
    assert sleeps == []
    clock.advance(1799.999)
    hook.after_train_iter(runner, 2)
    assert len((tmp_path / "thermal.jsonl").read_text().splitlines()) == 1
    clock.advance(0.001)
    runner.iter = 199
    hook.after_train_iter(runner, 3)
    assert sleeps == [60]
    events = [json.loads(line) for line in (tmp_path / "thermal.jsonl").read_text().splitlines()]
    assert [(event["temperature_celsius"], event["cooled"]) for event in events] == [
        (87, False),
        (87.0001, True),
    ]
    assert events[1]["iteration"] == 200 and events[1]["cooldown_seconds"] == 60


def test_mmengine_thermal_config_is_exact_and_fail_closed() -> None:
    config = mmengine_thermal_config(
        {
            "thermal": {
                "poll_interval_minutes": 30,
                "max_celsius": 87,
                "cooldown_seconds": 60,
            }
        }
    )
    assert config["custom_imports"]["imports"] == ["maskfactory.training.thermal"]
    assert config["custom_hooks"][0] == {
        "type": "MaskFactoryThermalCooldownHook",
        "poll_interval_minutes": 30.0,
        "max_celsius": 87.0,
        "cooldown_seconds": 60.0,
        "log_name": "thermal.jsonl",
        "priority": "VERY_HIGH",
    }
    with pytest.raises(ThermalPolicyError, match="30/87/60"):
        mmengine_thermal_config(
            {
                "thermal": {
                    "poll_interval_minutes": 30,
                    "max_celsius": 88,
                    "cooldown_seconds": 60,
                }
            }
        )
    with pytest.raises(ThermalPolicyError, match="exactly"):
        mmengine_thermal_config(
            {
                "thermal": {
                    "poll_interval_minutes": 30,
                    "max_celsius": 87,
                    "cooldown_seconds": 60,
                    "optional": True,
                }
            }
        )


def test_temperature_probe_uses_hottest_gpu_and_refuses_bad_output(monkeypatch) -> None:
    monkeypatch.setattr(
        "maskfactory.training.thermal.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="72\n89\n", stderr=""),
    )
    assert query_max_gpu_temperature() == 89
    monkeypatch.setattr(
        "maskfactory.training.thermal.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="unknown\n", stderr=""),
    )
    with pytest.raises(ThermalPolicyError, match="non-numeric"):
        query_max_gpu_temperature()


@pytest.mark.parametrize("value", [0, -1, float("nan"), True, "bad"])
def test_thermal_hook_refuses_invalid_policy(value: object) -> None:
    with pytest.raises(ThermalPolicyError):
        MaskFactoryThermalCooldownHook(max_celsius=value)
