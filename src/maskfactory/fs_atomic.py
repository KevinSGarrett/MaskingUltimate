"""Bounded atomic filesystem mutations resilient to transient Windows sharing locks."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
from pathlib import Path

DEFAULT_REPLACE_DELAYS = (0.01, 0.05, 0.1, 0.25, 0.5)


def replace_with_retry(
    source: Path,
    destination: Path,
    *,
    delays: Sequence[float] = DEFAULT_REPLACE_DELAYS,
    replace: Callable[[Path, Path], None] = os.replace,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    """Perform ``os.replace`` and retry only transient permission/share violations."""
    source = Path(source)
    destination = Path(destination)
    for attempt in range(len(delays) + 1):
        try:
            replace(source, destination)
            return
        except PermissionError:
            if attempt == len(delays):
                raise
            sleeper(float(delays[attempt]))
