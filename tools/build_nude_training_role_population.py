#!/usr/bin/env python3
"""Build a non-authoritative train-role population from adult polygon hard-QC rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.nude_training_role_gate import build_nude_training_role_population


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--polygon-records", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = build_nude_training_role_population(args.polygon_records, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
