#!/usr/bin/env python3
"""Prepare sealed RunPod autonomous work-cell mission artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from maskfactory.autonomy.work_cell_mission_builder import build_mission_artifacts


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--providers", type=Path, required=True)
    parser.add_argument("--roles", type=Path, required=True)
    parser.add_argument("--handlers", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--authority-ceiling", default="machine_verified_candidate")
    parser.add_argument("--allowed-output-prefix")
    parser.add_argument("--repair-policy", type=Path)
    parser.add_argument("--execution", type=Path)
    parser.add_argument("--bulk-policy", type=Path)
    args = parser.parse_args()

    result = build_mission_artifacts(
        mission_id=args.mission_id,
        input_manifest_path=args.input_manifest,
        records=_read(args.records),
        shard_count=args.shard_count,
        bindings=_read(args.bindings),
        provider_bindings=_read(args.providers),
        role_bindings=_read(args.roles),
        handlers=_read(args.handlers),
        output_dir=args.output_dir,
        authority_ceiling=args.authority_ceiling,
        allowed_output_prefix=args.allowed_output_prefix,
        repair_policy=_read(args.repair_policy) if args.repair_policy else None,
        execution=_read(args.execution) if args.execution else None,
        bulk_policy=_read(args.bulk_policy) if args.bulk_policy else None,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
