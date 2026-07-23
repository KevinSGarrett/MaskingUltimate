#!/usr/bin/env python3
"""Consolidate disjoint provider waves into one atomic provider/hard-QA package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from maskfactory.nude_box_mask_consolidation import (  # noqa: E402
    consolidate_box_prompt_provider_batches,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-batch", type=Path, required=True)
    parser.add_argument("--source-shard", type=Path, required=True)
    parser.add_argument("--provider-batch", type=Path, action="append", required=True)
    parser.add_argument("--provider-root", type=Path, action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _source_paths(path: Path) -> dict[str, Path]:
    shard = _load(path)
    if shard.get("schema_version") != "maskfactory.nude_batch_shard.v1":
        raise ValueError("source shard schema is invalid")
    body = {key: value for key, value in shard.items() if key != "self_sha256"}
    import hashlib

    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    if shard.get("self_sha256") != hashlib.sha256(encoded).hexdigest():
        raise ValueError("source shard self hash is stale")
    samples = shard.get("samples")
    if not isinstance(samples, list) or len(samples) != shard.get("sample_count"):
        raise ValueError("source shard sample count is invalid")
    result = {}
    for sample in samples:
        sample_id = sample.get("sample_id")
        source_path = sample.get("source_path_readonly")
        if (
            not isinstance(sample_id, str)
            or not isinstance(source_path, str)
            or sample_id in result
        ):
            raise ValueError("source shard sample identity is invalid")
        result[sample_id] = Path(source_path)
    return result


def main() -> int:
    args = _args()
    if len(args.provider_batch) != len(args.provider_root):
        raise SystemExit("--provider-batch and --provider-root counts must match")
    manifest = consolidate_box_prompt_provider_batches(
        catalog_batch=_load(args.catalog_batch),
        provider_batches=[
            (_load(batch), root)
            for batch, root in zip(
                args.provider_batch,
                args.provider_root,
                strict=True,
            )
        ],
        source_paths=_source_paths(args.source_shard),
        output_root=args.output_root,
    )
    print(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
