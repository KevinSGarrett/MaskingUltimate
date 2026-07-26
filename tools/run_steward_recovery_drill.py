#!/usr/bin/env python3
"""Run the one-shot CPU-safe self-hosted steward recovery acceptance drill."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.steward.recovery_drill import run_recovery_drill


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    result = run_recovery_drill(parse_args().output_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
