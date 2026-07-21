"""Atomic document writers and strict mask/map writer boundary (doc 03 §1)."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from ..fs_atomic import replace_with_retry
from .png_strict import write_binary_mask, write_grayscale, write_label_map


def write_json_atomic(path: Path, document: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        replace_with_retry(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


__all__ = ["write_binary_mask", "write_grayscale", "write_json_atomic", "write_label_map"]
