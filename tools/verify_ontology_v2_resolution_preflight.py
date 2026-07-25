#!/usr/bin/env python3
"""Run the authority-neutral ontology-v2 real-source preflight."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.nude_corpus_intake import sha256_file
from maskfactory.ontology_v2_resolution_preflight import build_resolution_preflight


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pilot = json.loads(args.pilot.read_text(encoding="utf-8"))
    workload = json.loads(args.workload.read_text(encoding="utf-8"))
    receipt = build_resolution_preflight(
        pilot,
        workload,
        pilot_file_sha256=sha256_file(args.pilot),
        workload_file_sha256=sha256_file(args.workload),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "images": receipt["image_count"],
                "work_units": receipt["work_unit_count"],
                "self_sha256": receipt["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
