#!/usr/bin/env python3
"""Build the sealed ontology-v2 autonomous-resolution workload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.nude_corpus_intake import sha256_file
from maskfactory.ontology_v2_resolution_workload import build_resolution_workload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pilot = json.loads(args.pilot.read_text(encoding="utf-8"))
    workload = build_resolution_workload(pilot, pilot_manifest_file_sha256=sha256_file(args.pilot))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(workload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS_QUEUED_NO_AUTHORITY",
                "work_units": workload["work_unit_count"],
                "completed": workload["completed_count"],
                "self_sha256": workload["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
