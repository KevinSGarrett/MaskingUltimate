#!/usr/bin/env python3
"""Build a self-sealed adult-corpus dataset coverage report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.nude_dataset_coverage import build_nude_dataset_coverage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-records", type=Path, required=True)
    parser.add_argument("--ontology-crosswalk", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_nude_dataset_coverage(
        registry_records=args.registry_records,
        ontology_crosswalk=args.ontology_crosswalk,
        queue_path=args.queue,
        platform=args.platform,
    )
    if args.output.exists():
        raise SystemExit("output already exists")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "registry_record_count",
                    "processed_record_count",
                    "remaining_record_count",
                    "certification_yield",
                    "self_sha256",
                )
            },
            indent=2,
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
