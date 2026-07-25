#!/usr/bin/env python3
"""Checkpoint one sealed person-catalog batch as durable nonterminal queue evidence."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from maskfactory.nude_batch_queue import NudeBatchQueue
from maskfactory.nude_person_catalog_queue_bridge import bridge_person_catalog_batch_to_queue

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-batch", type=Path, required=True)
    parser.add_argument("--nude-shard", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--platform", choices=("local", "runpod"), required=True)
    parser.add_argument("--queue-shard-path", required=True)
    parser.add_argument("--lease-token", required=True)
    args = parser.parse_args()
    result = bridge_person_catalog_batch_to_queue(catalog_batch_path=args.catalog_batch, nude_shard_path=args.nude_shard, output_path=args.output, queue=NudeBatchQueue(args.queue), platform=args.platform, shard_path=args.queue_shard_path, lease_token=args.lease_token)
    print(json.dumps(result, sort_keys=True))
if __name__ == "__main__":
    main()