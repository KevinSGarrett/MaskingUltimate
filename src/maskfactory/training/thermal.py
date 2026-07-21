"""MMEngine training hook for MaskFactory's mandatory laptop cooldown policy."""

from __future__ import annotations

import json
import math
import os
import subprocess
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from mmengine.hooks import Hook
    from mmengine.registry import HOOKS
except ImportError:  # CI and package-reader environments deliberately omit MMEngine.

    class Hook:  # type: ignore[no-redef]
        """Import-compatible stand-in; real training requires MMEngine."""

    HOOKS = None


class ThermalPolicyError(RuntimeError):
    """Training cannot enforce the mandatory GPU thermal policy."""


class MaskFactoryThermalCooldownHook(Hook):
    """Pause training for 60 seconds every 30 minutes when GPU temperature exceeds 87 C."""

    priority = "VERY_HIGH"

    def __init__(
        self,
        *,
        poll_interval_minutes: float = 30,
        max_celsius: float = 87,
        cooldown_seconds: float = 60,
        log_name: str = "thermal.jsonl",
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        probe: Callable[[], float] | None = None,
    ) -> None:
        self.poll_interval_sec = _positive_finite(
            float(poll_interval_minutes) * 60, "thermal poll interval"
        )
        self.max_celsius = _positive_finite(max_celsius, "thermal maximum")
        self.cooldown_seconds = _positive_finite(cooldown_seconds, "thermal cooldown")
        if Path(log_name).name != log_name or not log_name.endswith(".jsonl"):
            raise ThermalPolicyError("thermal log_name must be a local .jsonl filename")
        self.log_name = log_name
        self.clock = clock
        self.sleeper = sleeper
        self.probe = probe or query_max_gpu_temperature
        self._next_poll = self.clock() + self.poll_interval_sec

    def after_train_iter(
        self,
        runner: Any,
        batch_idx: int,
        data_batch: Any | None = None,
        outputs: Mapping[str, Any] | None = None,
    ) -> None:
        """Poll on schedule and block this training process during a required cooldown."""
        del batch_idx, data_batch, outputs
        now = self.clock()
        if now < self._next_poll:
            return
        temperature = _positive_finite(self.probe(), "measured GPU temperature")
        cooled = temperature > self.max_celsius
        event = {
            "schema_version": "1.0.0",
            "measured_at": datetime.now(UTC).isoformat(),
            "iteration": int(getattr(runner, "iter", -1)) + 1,
            "temperature_celsius": temperature,
            "threshold_celsius": self.max_celsius,
            "poll_interval_seconds": self.poll_interval_sec,
            "cooldown_seconds": self.cooldown_seconds if cooled else 0,
            "cooled": cooled,
        }
        _append_event(Path(getattr(runner, "work_dir")) / self.log_name, event)
        if cooled:
            self.sleeper(self.cooldown_seconds)
        self._next_poll = self.clock() + self.poll_interval_sec


if HOOKS is not None:
    HOOKS.register_module(module=MaskFactoryThermalCooldownHook)


def query_max_gpu_temperature() -> float:
    """Return the hottest visible NVIDIA GPU temperature or fail closed."""
    command = ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"]
    try:
        process = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ThermalPolicyError(f"cannot execute nvidia-smi thermal probe: {exc}") from exc
    if process.returncode:
        detail = process.stderr.strip() or process.stdout.strip()
        raise ThermalPolicyError(f"nvidia-smi thermal probe failed: {detail[-500:]}")
    try:
        values = [float(line.strip()) for line in process.stdout.splitlines() if line.strip()]
    except ValueError as exc:
        raise ThermalPolicyError("nvidia-smi returned a non-numeric temperature") from exc
    if not values:
        raise ThermalPolicyError("nvidia-smi returned no GPU temperatures")
    return max(_positive_finite(value, "GPU temperature") for value in values)


def mmengine_thermal_config(config: Mapping[str, Any]) -> dict[str, object]:
    """Translate the governed YAML thermal section into an exact MMEngine hook config."""
    thermal = config.get("thermal")
    if not isinstance(thermal, Mapping):
        raise ThermalPolicyError("training config lacks the mandatory thermal section")
    required = {"poll_interval_minutes", "max_celsius", "cooldown_seconds"}
    if set(thermal) != required:
        raise ThermalPolicyError(f"thermal config must contain exactly {sorted(required)}")
    poll = _positive_finite(thermal["poll_interval_minutes"], "thermal poll interval")
    maximum = _positive_finite(thermal["max_celsius"], "thermal maximum")
    cooldown = _positive_finite(thermal["cooldown_seconds"], "thermal cooldown")
    if (poll, maximum, cooldown) != (30.0, 87.0, 60.0):
        raise ThermalPolicyError("MaskFactory release training requires thermal policy 30/87/60")
    return {
        "custom_imports": {
            "imports": ["maskfactory.training.thermal"],
            "allow_failed_imports": False,
        },
        "custom_hooks": [
            {
                "type": "MaskFactoryThermalCooldownHook",
                "poll_interval_minutes": poll,
                "max_celsius": maximum,
                "cooldown_seconds": cooldown,
                "log_name": "thermal.jsonl",
                "priority": "VERY_HIGH",
            }
        ],
    }


def _append_event(path: Path, event: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _positive_finite(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ThermalPolicyError(f"{name} must be a positive finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ThermalPolicyError(f"{name} must be a positive finite number") from exc
    if not math.isfinite(number) or number <= 0:
        raise ThermalPolicyError(f"{name} must be a positive finite number")
    return number
