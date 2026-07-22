#!/usr/bin/env python3
"""Run deterministic hard QC over every adopted adult-corpus polygon record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.nude_polygon_hard_qc import run_full_polygon_hard_qc, write_polygon_qc_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--intake",
        type=Path,
        default=Path(r"C:\Comfy_UI_Main\MaskedWarehouse\Nude\_MASKFACTORY_INTAKE"),
    )
    parser.add_argument("--split-summary", type=Path, required=True)
    parser.add_argument("--split-mapping", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    records, summary = run_full_polygon_hard_qc(
        args.intake,
        split_summary=args.split_summary,
        split_mapping=args.split_mapping,
    )
    result = write_polygon_qc_evidence(records, summary, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
