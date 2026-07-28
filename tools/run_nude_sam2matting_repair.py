#!/usr/bin/env python3
"""Run SAM2Matting as a bounded draft-repair provider on a selected RunPod pod."""

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

from maskfactory.nude_reference_mask_repair import (  # noqa: E402
    build_reference_person_repair_reentry_batch,
    execute_reference_person_repair_batch,
    validate_reference_person_repair_batch,
)
from maskfactory.providers.sam2matting import SAM2MattingProvider  # noqa: E402


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-batch", type=Path, required=True)
    parser.add_argument("--visual-review", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-paths", type=Path, required=True)
    parser.add_argument("--target-contracts", type=Path, required=True)
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--repair-output", type=Path, required=True)
    parser.add_argument("--reentry-output", type=Path, required=True)
    parser.add_argument("--reentry-contracts-output", type=Path, required=True)
    parser.add_argument("--maximum-attempts", type=int, default=3)
    return parser.parse_args()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    args = _args()
    provider = SAM2MattingProvider(
        runtime_python=args.runtime_python,
        source_root=args.source_root,
        checkpoint_path=args.checkpoint,
    )
    source_paths = {key: Path(value) for key, value in _read_object(args.source_paths).items()}
    contracts = _read_object(args.target_contracts)
    repair = execute_reference_person_repair_batch(
        provider_batch=_read_object(args.provider_batch),
        visual_review=_read_object(args.visual_review),
        evidence_root=args.evidence_root,
        output_root=args.output_root,
        source_paths=source_paths,
        target_contracts=contracts,
        repair_provider=provider,
        maximum_attempts=args.maximum_attempts,
    )
    validate_reference_person_repair_batch(repair, output_root=args.output_root)
    reentry, reentry_contracts = build_reference_person_repair_reentry_batch(
        parent_provider_batch=_read_object(args.provider_batch),
        repair_batch=repair,
        output_root=args.output_root,
        parent_target_contracts=contracts,
    )
    _write_json(args.repair_output, repair)
    _write_json(args.reentry_output, reentry)
    _write_json(args.reentry_contracts_output, reentry_contracts)
    print(json.dumps({"status_counts": repair["status_counts"], "authority_claimed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
