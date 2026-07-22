#!/usr/bin/env python3
"""Seed and inspect the durable adult-corpus shard queue."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.nude_batch_queue import NudeBatchQueue
from maskfactory.nude_corpus_intake import load_adopted_intake


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--platform", choices=("local", "runpod"), required=True)
    parser.add_argument("--max-attempts", type=int, default=3)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    seed = subparsers.add_parser("seed")
    seed.add_argument(
        "--intake",
        type=Path,
        default=Path(r"C:\Comfy_UI_Main\MaskedWarehouse\Nude\_MASKFACTORY_INTAKE"),
    )
    subparsers.add_parser("summary")
    args = parser.parse_args()
    queue = NudeBatchQueue(args.queue, max_attempts=args.max_attempts)
    result: dict[str, object] = {}
    if args.operation == "seed":
        intake = load_adopted_intake(args.intake, platform=args.platform)
        result["seed"] = queue.seed(intake["platform_descriptors"], platform=args.platform)
    result["summary"] = queue.summary(platform=args.platform)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
