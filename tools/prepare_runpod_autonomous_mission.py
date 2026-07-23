#!/usr/bin/env python3
"""Prepare sealed RunPod autonomous work-cell mission artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from maskfactory.autonomy.work_cell_mission_builder import (  # noqa: E402
    build_mission_artifacts,
    build_wrapper_handler_specs,
)


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
    parser.add_argument("--handlers", type=Path)
    parser.add_argument("--stage-commands", type=Path)
    parser.add_argument("--handler-artifact-root", type=Path)
    parser.add_argument(
        "--stage-wrapper",
        type=Path,
        default=Path("tools/run_runpod_work_cell_stage.py"),
    )
    parser.add_argument("--python-executable", default="python")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--authority-ceiling", default="machine_verified_candidate")
    parser.add_argument("--allowed-output-prefix")
    parser.add_argument("--repair-policy", type=Path)
    parser.add_argument("--execution", type=Path)
    parser.add_argument("--bulk-policy", type=Path)
    args = parser.parse_args()
    if args.handlers and args.stage_commands:
        parser.error("--handlers and --stage-commands are mutually exclusive")
    if not args.handlers and not args.stage_commands:
        parser.error("--handlers or --stage-commands is required")
    if args.stage_commands and args.handler_artifact_root is None:
        parser.error("--handler-artifact-root is required with --stage-commands")
    handlers = (
        _read(args.handlers)
        if args.handlers
        else build_wrapper_handler_specs(
            _read(args.stage_commands),
            artifact_root=args.handler_artifact_root,
            wrapper_path=args.stage_wrapper,
            python_executable=args.python_executable,
        )
    )

    result = build_mission_artifacts(
        mission_id=args.mission_id,
        input_manifest_path=args.input_manifest,
        records=_read(args.records),
        shard_count=args.shard_count,
        bindings=_read(args.bindings),
        provider_bindings=_read(args.providers),
        role_bindings=_read(args.roles),
        handlers=handlers,
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
