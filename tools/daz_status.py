from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.daz import daz_foundation_doctor, inspect_acquisition_queue


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only MaskFactory DAZ foundation status.")
    parser.add_argument("--config-root", type=Path, default=Path("configs/daz"))
    parser.add_argument("--queue-only", action="store_true")
    args = parser.parse_args()
    if args.queue_only:
        report = inspect_acquisition_queue(
            Path(r"F:\DAZ\00_control\render_state_ingest\queue.sqlite3")
        )
    else:
        report = daz_foundation_doctor(args.config_root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
