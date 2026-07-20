#!/usr/bin/env python3
"""Convenience entrypoint: run the isolated Main-side MaskFactory consumer.

Runs from a plain checkout without installing the package: it puts ``src`` on
``sys.path`` and delegates to ``mf_main_consumer.runner.main``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from mf_main_consumer.runner import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
