#!/usr/bin/env python3
"""Read-only verification for an existing actual-child recovery drill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from maskfactory.steward.interrupted_recovery_drill import (  # noqa: E402
    InterruptedRecoveryDrillError,
    verify_interrupted_recovery_drill,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        verification = verify_interrupted_recovery_drill(args.output_root)
    except InterruptedRecoveryDrillError as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(verification, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
